"""Check ordinary Lean declarations locally when the hosted checker is unavailable."""
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from the_pigeon_holes.fitness.compiler import COMPILER, LeanFitnessError, _run


def check(source):
    if len(source) > 32000:
        return {'valid': False, 'diagnostics': 'Lean source exceeds 32000 characters.'}
    project = Path(os.environ.get('RESEARCH_LEAN_PROJECT') or
                   Path(__file__).resolve().parents[3] / 'problems/lean').resolve()
    if not (project / 'lake-manifest.json').is_file():
        raise RuntimeError('Local Lean dependencies are missing; set RESEARCH_LEAN_PROJECT.')
    with tempfile.TemporaryDirectory(prefix='lean-check-') as directory:
        workspace = Path(directory)
        (workspace / 'Compiler.lean').write_bytes(COMPILER.read_bytes())
        _run(project, workspace, workspace / 'Compiler.lean', timeout=60,
             stage='checker_unavailable', output=workspace / 'Compiler.olean')
        generated = workspace / 'Generated.lean'
        generated.write_text(source)
        gate = workspace / 'Gate.lean'
        gate.write_text('import Compiler\n#check_fitness_source ' + json.dumps(str(generated)) + '\n')
        try:
            # Parse before elaboration: no local execution of generated tactics,
            # metaprograms, IO, custom imports, axioms or placeholders.
            _run(project, workspace, gate, timeout=60, stage='source_rejected')
            diagnostics = _run(project, workspace, generated, timeout=60, stage='lean_compile_failed')
        except LeanFitnessError as error:
            return {'valid': False, 'diagnostics': str(error) +
                    '\nLocal checking accepts ordinary definitions and term proofs only; do not use tactics (by).'}
        return {'valid': True, 'diagnostics': diagnostics, 'check_artifact': {
            'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'toolchain': (project / 'lean-toolchain').read_text().strip(),
            'lean_version': subprocess.check_output(['lake', 'env', 'lean', '--version'],
                cwd=project, text=True, timeout=30).strip(),
            'dependencies': json.loads((project / 'lake-manifest.json').read_text()),
            'command': ['lake', 'env', 'lean', 'Generated.lean'], 'exit_code': 0,
            'diagnostics': diagnostics, 'checker': 'local Lean (source admission checked)'}}
