"""UI preparation pipeline. Model credentials remain in the Python service."""
import asyncio
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class FormalizationInput(BaseModel):
    mode: Literal['natural', 'formal'] = 'natural'
    problem: str = Field(min_length=1, max_length=16000)
    lean: str = Field(default='', max_length=32000)

    @model_validator(mode='after')
    def check_input(self):
        if not self.problem.strip():
            raise ValueError('Describe the problem to assess fidelity.')
        if self.mode == 'formal' and not self.lean.strip():
            raise ValueError('Provide the existing Lean formulation.')
        return self

class HostedTools:
    async def generate(self, problem, feedback=''):
        import modal
        return await modal.Cls.from_name('lean-generation', 'Generator')().generate.remote.aio(problem, feedback)

    async def check(self, source):
        import modal
        return await modal.Function.from_name('lean-checker', 'check').remote.aio(source)

    async def score(self, problem, source):
        import os
        import modal
        payload = {'problem': problem, 'lean_context': 'import Mathlib', 'candidate': source}
        endpoint = os.environ.get('FIDELITY_ENDPOINT')
        if endpoint:
            import httpx
            headers = {'Modal-Key': os.environ['FIDELITY_TOKEN_ID'],
                       'Modal-Secret': os.environ['FIDELITY_TOKEN_SECRET']}
            async with httpx.AsyncClient(timeout=600) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        return await modal.Cls.from_name('lean-fidelity-api', 'Fidelity')().score.remote.aio(payload)

async def prepare(body: FormalizationInput, tools=None):
    tools = tools or HostedTools()
    source = body.lean if body.mode == 'formal' else await tools.generate(body.problem)
    attempts = []
    for attempt in range(2 if body.mode == 'natural' else 1):
        checked = await tools.check(source)
        attempts.append(checked)
        if checked['valid']:
            break
        if body.mode == 'natural' and attempt == 0:
            source = await tools.generate(body.problem, source + '\n' + checked['diagnostics'])
    fidelity = None
    fidelity_error = None
    if checked['valid']:
        try:
            fidelity = await tools.score(body.problem, source)
        except Exception:
            fidelity_error = 'Fidelity service unavailable; Lean output is preserved for review.'
    return {'lean': source, 'lean_checked': checked['valid'], 'diagnostics': checked['diagnostics'],
            'attempts': len(attempts), 'fidelity': fidelity, 'fidelity_error': fidelity_error,
            'status': ('checked' if fidelity and fidelity['fidelity_decision'] == 'accept'
                       else 'review' if checked['valid'] else 'invalid'),
            'generator': 'user' if body.mode == 'formal' else 'Qwen/Qwen3-4B-Instruct-2507',
            'generation_fine_tuned': False}
