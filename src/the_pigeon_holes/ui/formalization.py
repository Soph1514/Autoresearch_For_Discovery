"""UI preparation pipeline. Model credentials remain in the Python service."""
import asyncio
import re
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

async def remote_call(function, *args):
    call = await function.spawn.aio(*args)
    try:
        return await call.get.aio()
    except asyncio.CancelledError:
        await call.cancel.aio()
        raise

class HostedTools:
    async def generate(self, problem, feedback=''):
        import modal
        return await remote_call(modal.Cls.from_name('lean-generation', 'Generator')().generate, problem, feedback)

    async def check(self, source):
        import modal
        return await remote_call(modal.Function.from_name('lean-checker', 'check'), source)

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
        return await remote_call(modal.Cls.from_name('lean-fidelity-api', 'Fidelity')().score, payload)

async def prepare(body: FormalizationInput, tools=None, progress=None):
    tools = tools or HostedTools()
    generated_by_qwen = body.mode == "natural"
    async def emit(**event):
        if progress:
            await progress(event)
    await emit(stage='generating' if body.mode == 'natural' else 'checking', attempt=1)
    source = body.lean if body.mode == 'formal' else await tools.generate(body.problem)
    attempts = 0
    while True:
        attempts += 1
        await emit(stage='checking', attempt=attempts, lean=source)
        checked = await tools.check(source)
        await emit(stage='checked', attempt=attempts, lean=source, **checked)
        if checked['valid']:
            break
        await emit(stage='repairing', attempt=attempts + 1)
        if "don't know how to synthesize placeholder" in checked['diagnostics']:
            # Lean 4 refine needs an explicit tactic goal (?_), not an inference hole (_).
            repaired = re.sub(r'(?m)^([ \t]*refine[ \t]+⟨[^\n]*),[ \t]*_([ \t]*⟩)',
                              r'\1, ?_\2', source)
            if repaired != source:
                source = repaired
                continue
        feedback = (f'Repair attempt {attempts}. Keep the original problem, assumptions, and conclusion unchanged. '
                    'Fix the Lean errors; do not replace the claim with an easier statement or add sorry/axioms. '
                    'This is Lean 4.19, NOT Lean 3. Use := by and indentation, never begin/end, existsi, or comma-separated tactics. '
                    'Use rcases h with ⟨x, hx⟩ to unpack an existential; use refine ⟨witness, ?_⟩ to prove one. '
                    'Use import Mathlib when a specific module is missing; ring can prove polynomial identities.\n'
                    + source + '\nChecker diagnostics:\n' + checked['diagnostics'])
        if body.mode == 'formal':
            feedback += '\nOriginal user formulation (preserve its statement):\n' + body.lean
        source = await tools.generate(body.problem, feedback)
        generated_by_qwen = True
    await emit(stage='scoring', attempt=attempts, lean=source)
    fidelity = None
    fidelity_error = None
    if checked['valid']:
        try:
            fidelity = await tools.score(body.problem, source)
        except Exception:
            fidelity_error = 'Fidelity service unavailable; Lean output is preserved for review.'
    return {'check_artifact': checked.get('check_artifact'), 'lean': source, 'lean_checked': checked['valid'], 'diagnostics': checked['diagnostics'],
            'attempts': attempts, 'fidelity': fidelity, 'fidelity_error': fidelity_error,
            'status': ('checked' if fidelity and fidelity['fidelity_decision'] == 'accept'
                       else 'review' if checked['valid'] else 'invalid'),
            'generator': 'user' if not generated_by_qwen else 'Qwen/Qwen3-4B-Instruct-2507',
            'generation_fine_tuned': False}
