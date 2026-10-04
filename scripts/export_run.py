"""Export a durable run and independently recheck every saved exact witness.

Usage: PYTHONPATH=src .venv/bin/python scripts/export_run.py RUN_ID
"""
import argparse
import csv
import json
import urllib.request
from pathlib import Path
from fractions import Fraction
from the_pigeon_holes.fitness.autocorrelation import c1

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('run_id')
parser.add_argument('--api', default='http://127.0.0.1:8000')
parser.add_argument('--output', type=Path, default=Path('runs/exports'))
args = parser.parse_args()
with urllib.request.urlopen(f'{args.api}/api/runs/{args.run_id}/artifact') as response:
    artifact = json.load(response)
folder = args.output / args.run_id
folder.mkdir(parents=True, exist_ok=True)
(folder / 'run.json').write_text(json.dumps(artifact, indent=2))
formalization_id = (artifact.get('provenance') or {}).get('formalization_id')
if formalization_id:
    with urllib.request.urlopen(f'{args.api}/api/formalizations/{formalization_id}') as response:
        (folder / 'formalization.json').write_text(json.dumps(json.load(response), indent=2))
(folder / 'events.ndjson').write_text(''.join(json.dumps(e) + '\n' for e in artifact['events']))
verified = 0
for candidate_id, record in artifact['evidence'].get('numerical', {}).items():
    scores = []
    for case in record['cases'].values():
        witness = case.get('fitness_evidence', case)
        if 'c1_exact' not in witness:
            continue
        exact = witness['c1_exact']
        score = c1(witness['output'])
        assert len(witness['output']) == case['inputs']['n']
        assert score == Fraction(int(exact['numerator']), int(exact['denominator']))
        scores.append(score)
        verified += 1
    mean = record.get('mean_c1_exact') or record.get('aggregate_metrics_exact', {}).get('c1')
    if mean:
        assert sum(scores) / len(scores) == Fraction(int(mean['numerator']), int(mean['denominator']))
rows = []
for idea in artifact['snapshot']['ideas']:
    evaluation = artifact['evidence']['evaluations'].get(idea['id'], {})
    rows.append({'id': idea['id'], 'generation': idea.get('generation'), 'operation': idea['operation'],
        'parents': ','.join(idea['parents']), 'hypothesis': idea['description'],
        'valid': evaluation.get('valid'), 'c1': evaluation.get('metrics', {}).get('c1'),
        'failure': '; '.join(evaluation.get('failure_reasons', []))})
with (folder / 'lineage.csv').open('w') as f:
    writer = csv.DictWriter(f, fieldnames=['id','generation','operation','parents','hypothesis','valid','c1','failure'])
    writer.writeheader(); writer.writerows(rows)
outcome = artifact.get('outcome') or {}
best = outcome.get('best_candidate')
best_evaluation = outcome.get('best_evaluation')
if best is None:
    # A stopped run has no EvolutionOutcome, but its verified elite is durable.
    winner_id = next((e['ideaId'] for e in artifact['snapshot']['elites']
                      if e['current'] and e['niche'] == 'Global best'), None)
    best = artifact['evidence']['candidates'].get(winner_id)
    best_evaluation = artifact['evidence']['evaluations'].get(winner_id)
if best:
    (folder / 'best.py').write_text(best['source_code'])
    (folder / 'best-witnesses.json').write_text(json.dumps(artifact['evidence']['numerical'].get(best['id']), indent=2))
summary = {'run_id': args.run_id, 'status': artifact['snapshot']['run']['status'], 'candidates':len(rows),
    'events': len(artifact['events']), 'independently_rechecked_witnesses':verified,
    'best': best_evaluation,
    'reported_tokens': (artifact.get('outcome') or {}).get('tokens_used'),
    'budget': artifact.get('budget'), 'literature': artifact.get('literature')}
(folder / 'summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
print(folder.resolve())
