"""UI preparation pipeline. Model credentials remain in the Python service."""
import asyncio
import hashlib
import os
import re
import subprocess
from pathlib import Path
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


# Lean sources that would let a "check" pass without proving anything, or run
# arbitrary code. Mirrors the hosted checker's admission policy.
UNSAFE_LEAN = re.compile(r'\b(sorry|admit|axiom|unsafe)\b|#(eval|extern)|run_(tac|elab)|\bIO\.')


def lean_project() -> Path:
    return Path(os.environ.get('RESEARCH_LEAN_PROJECT') or
                Path(__file__).resolve().parents[3] / 'problems' / 'lean')


class LocalTools:
    """Check Lean with the local pinned project instead of the hosted service.

    The hosted checker is `lake env lean` against mathlib in a container, so this
    runs the same command against `problems/lean` and records the same provenance
    shape. It removes the dependency on a teammate's Modal workspace for local
    work, and unlike a stub it produces a real check.

    Generation and fidelity scoring stay hosted; there is no local Qwen.
    """

    def __init__(self, project: Path | None = None, timeout: float = 240.0):
        self.project = (project or lean_project()).resolve()
        self.timeout = timeout

    async def generate(self, problem, feedback=''):
        raise RuntimeError(
            'Local Lean mode cannot generate a formalization. Paste Lean in formal '
            'mode, or configure Modal for the hosted Qwen generator.')

    async def score(self, problem, source):
        raise RuntimeError('Local Lean mode has no fidelity model.')

    async def check(self, source):
        return await asyncio.to_thread(self._check, source)

    def _check(self, source: str) -> dict:
        if len(source) > 32000:
            return {'valid': False, 'diagnostics': 'Lean source exceeds 32000 characters.'}
        if UNSAFE_LEAN.search(source):
            return {'valid': False,
                    'diagnostics': 'Unsupported proof placeholder, axiom, or executable command.'}
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Generated.lean'
            path.write_text(source)
            try:
                result = subprocess.run(['lake', 'env', 'lean', str(path)], cwd=self.project,
                                        capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                return {'valid': False,
                        'diagnostics': f'Lean check exceeded {self.timeout:.0f} seconds.'}
            except OSError as error:
                return {'valid': False, 'diagnostics': f'Local Lean unavailable: {error}'}
            diagnostics = (result.stdout + result.stderr)[-12000:]
            version = subprocess.run(['lake', 'env', 'lean', '--version'], cwd=self.project,
                                     capture_output=True, text=True).stdout.strip()
            return {'valid': result.returncode == 0, 'diagnostics': diagnostics,
                    'check_artifact': {
                        'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
                        'toolchain': (self.project / 'lean-toolchain').read_text().strip(),
                        'lean_version': version,
                        'dependencies': {'lake_manifest':
                                         (self.project / 'lake-manifest.json').read_text()},
                        'command': ['lake', 'env', 'lean', 'Generated.lean'],
                        'exit_code': result.returncode, 'diagnostics': diagnostics,
                        'checker': 'local'}}


def default_tools():
    """Hosted unless RESEARCH_LOCAL_LEAN is set, so deployed behaviour is unchanged."""
    return LocalTools() if os.environ.get('RESEARCH_LOCAL_LEAN') else HostedTools()


async def prepare(body: FormalizationInput, tools=None, progress=None):
    tools = tools or default_tools()
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
