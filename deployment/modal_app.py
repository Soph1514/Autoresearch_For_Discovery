"""Deploy with: modal deploy --strategy recreate deployment/modal_app.py.

Use deployment/deploy.py for updates: it drains active work before replacing
the singleton. Never use a rolling update with the SQLite volume.
"""
import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App('autoresearch-lab')
data = modal.Volume.from_name('autoresearch-lab-data', create_if_missing=True)
credentials = modal.Secret.from_name('autoresearch-lab-secrets',
                                     required_keys=['ANTHROPIC_API_KEY', 'RESEARCH_DEPLOY_TOKEN'])

candidate_image = (modal.Image.from_registry(
    'python@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81')
    .add_local_file(ROOT / 'docker/worker/worker.py', '/opt/worker/worker.py', copy=True))

web_image = (modal.Image.debian_slim(python_version='3.13')
    .apt_install('curl', 'git', 'zstd')
    .run_commands('curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain leanprover/lean4:v4.19.0')
    .env({'PATH': '/root/.elan/bin:/usr/local/bin:/usr/bin:/bin'})
    .run_commands('git clone https://github.com/leanprover-community/mathlib4.git /opt/mathlib',
                  'cd /opt/mathlib && git checkout c44e0c8ee63ca166450922a373c7409c5d26b00b',
                  'cd /opt/mathlib && lake exe cache get')
    .pip_install('fastapi>=0.115', 'uvicorn>=0.30', 'modal==1.6.1', 'httpx>=0.28',
                 'anthropic>=1.11.0', 'pydantic>=2.13.5')
    .add_local_dir(ROOT / 'src', '/app/src', copy=True, ignore=['**/__pycache__/**'])
    .add_local_dir(ROOT / 'problems', '/app/problems', copy=True,
                   ignore=['**/.lake/**', '**/__pycache__/**'])
    .add_local_dir(ROOT / 'frontend/dist', '/app/frontend/dist', copy=True)
    .add_local_file(ROOT / 'frontend/src/paper-theme.css', '/app/frontend/src/paper-theme.css', copy=True)
    .env({'PYTHONPATH': '/app/src:/app', 'RESEARCH_STORE': '/data/research.sqlite3',
          'RESEARCH_LEAN_PROJECT': '/opt/mathlib', 'RESEARCH_MODEL': 'claude-sonnet-4-6',
          'RESEARCH_EXECUTION_BACKEND': 'modal',
          'RESEARCH_REVISION': os.environ.get('RESEARCH_REVISION', 'local')})
    .workdir('/app'))


@app.function(image=candidate_image, timeout=60)
def candidate_runtime():
    """Register the immutable worker image; candidate code only runs in Sandboxes."""
    return candidate_image.object_id


@app.function(image=modal.Image.debian_slim(python_version='3.13'), secrets=[credentials])
def deployment_access():
    """Private Modal RPC for authorized deployers; never exposed as an HTTP route."""
    import os
    return {key: os.environ.get(key, '') for key in
            ('RESEARCH_DEPLOY_TOKEN', 'RESEARCH_API_USER', 'RESEARCH_API_PASSWORD')}


@app.function(image=web_image, volumes={'/data': data}, secrets=[credentials],
              cpu=2, memory=4096, min_containers=1, max_containers=1, timeout=3600)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def web():
    from the_pigeon_holes.execution.modal_runner import configure
    from the_pigeon_holes.ui.api import app as api, runs
    from the_pigeon_holes.ui.hosting import configure_hosting
    configure(app, modal.Image.from_id(candidate_runtime.remote()))
    return configure_hosting(api, runs, data, '/app/frontend/dist')


@app.function(image=web_image, timeout=180)
async def smoke_candidate():
    from the_pigeon_holes.execution.modal_runner import configure, run_candidate
    from the_pigeon_holes.execution.container_runner import ContainerLimits
    from dataclasses import asdict
    configure(app, modal.Image.from_id(await candidate_runtime.remote.aio()))
    return asdict(await run_candidate('def solve(x): return x + 1', 'solve', {'x': 41},
                                     ContainerLimits(memory_mb=128, timeout_seconds=30)))


@app.function(image=web_image, cpu=2, memory=4096, timeout=240)
def smoke_compiler():
    import tempfile
    from pathlib import Path
    from the_pigeon_holes.fitness.compiler import compile_fitness
    from the_pigeon_holes.models.problem_contract import EvaluationCase
    with tempfile.TemporaryDirectory() as directory:
        scorer = compile_fitness(
            statement='Select weights up to capacity.', instance={'weights': [3, 4, 5], 'capacity': 7},
            lean_source=Path('/app/problems/subset_sum/Generated.lean').read_text(),
            lean_project=Path('/opt/mathlib'), artifacts=Path(directory))
        result = scorer.evaluate_case(EvaluationCase('seven', {'weights': [3, 4, 5], 'capacity': 7}),
                                      [1, 1, 0])
        return {'valid': result.valid, 'objective': result.metrics.get('objective')}
