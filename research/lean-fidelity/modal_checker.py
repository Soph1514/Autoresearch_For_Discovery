"""Isolated pinned Lean checker, deployable without a GPU."""
from pathlib import Path
import modal
app = modal.App("lean-checker")

lean_image = (modal.Image.debian_slim(python_version='3.11')
    .apt_install('curl', 'git', 'zstd')
    .run_commands('curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain leanprover/lean4:v4.19.0')
    .env({'PATH': '/root/.elan/bin:/usr/local/bin:/usr/bin:/bin'})
    .run_commands('git clone https://github.com/leanprover-community/mathlib4.git /opt/mathlib',
                  'cd /opt/mathlib && git checkout c44e0c8ee63ca166450922a373c7409c5d26b00b',
                  'cd /opt/mathlib && lake exe cache get'))

@app.function(image=lean_image, timeout=150, min_containers=0, max_containers=2)
def check(source: str) -> dict:
    import subprocess
    import tempfile
    import re
    if len(source) > 32000:
        return {'valid': False, 'diagnostics': 'Lean source exceeds 32000 characters.'}
    # Conservative admission policy before running untrusted Lean in an isolated worker.
    if re.search(r'\b(sorry|admit|axiom|unsafe)\b|#(eval|extern)|run_(tac|elab)|\bIO\.', source):
        return {'valid': False, 'diagnostics': 'Unsupported proof placeholder, axiom, or executable command.'}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'Generated.lean'
        path.write_text(source)
        try:
            result = subprocess.run(['lake', 'env', 'lean', str(path)], cwd='/opt/mathlib',
                                    capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return {'valid': False, 'diagnostics': 'Lean check exceeded 120 seconds.'}
        return {'valid': result.returncode == 0, 'diagnostics': (result.stdout + result.stderr)[-12000:]}
