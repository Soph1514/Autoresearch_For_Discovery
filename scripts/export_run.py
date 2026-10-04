"""Export a durable run and independently recheck every saved exact witness.

Usage: PYTHONPATH=src .venv/bin/python scripts/export_run.py RUN_ID
"""
import argparse
import csv
import json
import urllib.request
from pathlib import Path
from fractions import Fraction
from the_pigeon_holes.evaluation.production import aggregate_metric
from the_pigeon_holes.fitness.registry import configured_registry
from the_pigeon_holes.ui.storage import contract_from_dict


def recheck_witnesses(artifact):
    """Rescore every saved witness and return how many cases were rechecked.

    The run's own contract names the metric and aggregation. Historical
    autocorrelation exports are rescored with the current trusted implementation,
    as before; other scorers must match the recorded digest. Per-case scoring is nested under
    `fitness_evidence` and the aggregate under `aggregate_metrics_exact`; runs
    saved before that restructure hold both flat, so each is read with a fallback
    to keep older artifacts verifiable. A mismatch raises rather than exporting
    evidence that was never verified.
    """
    contract = contract_from_dict(artifact['contract'])
    registry = configured_registry()
    reference = contract.fitness_function
    if (reference.id, reference.version) == ('autocorrelation', 'exact-v1'):
        # Moving the scorer changed its source hash. Keep main's historical
        # witness recheck; this does not authorize restarting a run with a new scorer.
        from problems.autocorrelation.fitness import AutocorrelationFitnessFunction
        fitness_function = AutocorrelationFitnessFunction()
    else:
        fitness_function = registry.resolve(reference)
    goal = contract.optimisation_goal
    metric = goal.primary.name
    cases = {case.id: case for case in contract.evaluation_suite.cases}
    verified = 0
    for record in artifact.get('evidence', {}).get('numerical', {}).values():
        scored = []
        for case_id, saved in record.get('cases', {}).items():
            witness = saved.get('fitness_evidence') or saved
            if 'output' not in witness or case_id not in cases:
                continue
            fitness = fitness_function.evaluate_case(cases[case_id], witness['output'])
            assert fitness.valid, f'case {case_id} was recorded as scored but fails revalidation'
            value = fitness.metrics[metric]
            exact = witness.get(f'{metric}_exact')
            if exact:
                assert value == Fraction(int(exact['numerator']), int(exact['denominator']))
            scored.append(value)
            verified += 1
        aggregate = ((record.get('aggregate_metrics_exact') or {}).get(metric)
                     or record.get(f'mean_{metric}_exact'))
        if aggregate and len(scored) == len(cases):
            recomputed = aggregate_metric(scored, goal.aggregation, goal.primary)
            assert Fraction(recomputed) == Fraction(
                int(aggregate['numerator']), int(aggregate['denominator'])
            )
    return verified


def main():
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
    verified = recheck_witnesses(artifact)
    metric = artifact['snapshot']['run'].get('metricName') or 'metric'
    rows = []
    for idea in artifact['snapshot']['ideas']:
        evaluation = artifact['evidence']['evaluations'].get(idea['id'], {})
        rows.append({'id': idea['id'], 'generation': idea.get('generation'), 'operation': idea['operation'],
            'parents': ','.join(idea['parents']), 'hypothesis': idea['description'],
            'valid': evaluation.get('valid'), metric: evaluation.get('metrics', {}).get(metric),
            'failure': '; '.join(evaluation.get('failure_reasons', []))})
    with (folder / 'lineage.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=['id','generation','operation','parents','hypothesis','valid',metric,'failure'])
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
        'reported_tokens': outcome.get('tokens_used'),
        'budget': artifact.get('budget'), 'literature': artifact.get('literature')}
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(folder.resolve())


if __name__ == '__main__':
    main()
