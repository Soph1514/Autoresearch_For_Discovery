"""Restore a completed exported demo into a local store, without executing candidates.

Restart the backend after import. Use a separate store for untrusted exports.
"""
import argparse
import json
from pathlib import Path
from the_pigeon_holes.ui.storage import ArtifactStore, contract_from_dict

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('artifact', type=Path)
p.add_argument('--store', type=Path, default=Path('runs/research.sqlite3'))
a = p.parse_args()
record = json.loads(a.artifact.read_text())
contract_from_dict(record['contract'])
run = record['snapshot']['run']
if run['status'] not in ('completed','failed','stopped'):
    raise ValueError('Only terminal run snapshots may be imported.')
if record['snapshot']['schemaVersion'] != 1:
    raise ValueError('Unsupported snapshot version.')
store = ArtifactStore(a.store)
if store.get('run', run['id']) is not None:
    raise ValueError('Run already exists; refusing to overwrite history.')
formalization_id = (record.get('provenance') or {}).get('formalization_id')
source = a.artifact.parent / 'formalization.json'
if formalization_id and source.exists():
    artifact = json.loads(source.read_text())
    existing = store.get('formalization', formalization_id)
    if existing is not None and existing != artifact:
        raise ValueError('Conflicting formalization history.')
    store.put('formalization', formalization_id, artifact)
store.put('run', run['id'], record)
print(f"Imported {run['id']}. Restart the backend, then open /engine.html?run={run['id']}")
