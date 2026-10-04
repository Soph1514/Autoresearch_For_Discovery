"""Paired fidelity judgments on the Lea runner's default ten problem IDs.

Run: MODAL_PROFILE=arin06 .venv/bin/python research/lean-fidelity/benchmark_lea_ten.py
This evaluates dataset candidates, not Lea outputs or Lean generation.
"""
import hashlib
import html
import json
import re
import time
from pathlib import Path
import modal
from datasets import load_dataset
from experiment import partition

HERE = Path(__file__).parent
REVISION = '91183e5b12d64374827bf2782db629b5b0f8f319'
OUTPUT = HERE / 'reports' / 'lea-ten-fidelity-comparison.json'

def fields(row):
    candidate = re.sub(r'\s*:=\s*(?:by\s+)?sorry\s*$', '', row['lean4_prediction'].strip())
    return {'problem': row['nl_statement'], 'lean_context': row['lean4_src_header'], 'candidate': candidate}

def main():
    dataset = load_dataset('PAug/ProofNetVerif', revision=REVISION)
    splits = partition([dict(row) for split in dataset.values() for row in split])
    membership = {row['id']: name for name, examples in splits.items() for row in examples}
    selected, seen = [], set()
    for row in dataset['valid']:
        if row['id'] in seen:
            continue
        selected.append(dict(row)); seen.add(row['id'])
        if len(selected) == 10:
            break
    baseline = modal.Cls.from_name('lean-generation', 'Generator')()
    fine = modal.Cls.from_name('lean-fidelity-api', 'Fidelity')()
    report = {
        'task': 'Binary fidelity classification of the same saved dataset candidate for each problem',
        'dataset': 'PAug/ProofNetVerif', 'dataset_revision': REVISION,
        'selection': 'First candidate row for each of the first ten unique IDs in valid, matching default problem selection in the merged Lea runner. Actual friend run unconfirmed.',
        'baseline': 'Pretrained Qwen3-4B-Instruct-2507, greedy prompted faithful/unfaithful judgment',
        'fine_tuned': 'Frozen lean-fidelity-v1 sequence classifier; raw_logit >= 0 (equivalent to calibrated p >= 0.5)',
        'timing': 'Measured client wall time per sequential authenticated Modal request, excluding explicit warmup. Includes RPC overhead; one trial per candidate, not a timing estimate or distribution.',
        'lea': {'accuracy': None, 'seconds': None, 'reason': 'No saved predictions, verdicts or timing log in merged branch; Lea is a generation pipeline, not this classification task.'},
        'warmup_seconds': {}, 'rows': [],
    }
    # Same benign synthetic warmup for both; no dataset label is supplied.
    warmup = {'problem': 'For every natural number n, n + 0 = n.', 'lean_context': 'import Mathlib',
              'candidate': 'theorem example_statement (n : Nat) : n + 0 = n'}
    for name, call in [('baseline', lambda: baseline.judge.remote(**warmup)),
                       ('fine_tuned', lambda: fine.score.remote(warmup))]:
        start = time.perf_counter(); call()
        report['warmup_seconds'][name] = time.perf_counter() - start
        print(name, 'warmup', report['warmup_seconds'][name], flush=True)
    for index, row in enumerate(selected):
        payload = fields(row)
        start = time.perf_counter(); initial = baseline.judge.remote(**payload)
        initial_seconds = time.perf_counter() - start
        start = time.perf_counter(); tuned = fine.score.remote(payload)
        tuned_seconds = time.perf_counter() - start
        prediction = tuned['raw_logit'] >= 0 if tuned['raw_logit'] is not None else None
        item = {'id': row['id'], 'classifier_split': membership[row['id']], 'gold_faithful': bool(row['correct']),
                'candidate_sha256': hashlib.sha256(payload['candidate'].encode()).hexdigest(),
                'initial': {**initial, 'request_seconds': initial_seconds, 'correct': initial['faithful'] == bool(row['correct'])},
                'fine_tuned': {**tuned, 'faithful': prediction, 'request_seconds': tuned_seconds, 'correct': prediction == bool(row['correct'])}}
        report['rows'].append(item)
        OUTPUT.write_text(json.dumps(report, indent=2) + '\n')
        print(index + 1, row['id'], 'initial', item['initial']['correct'], 'fine-tuned', item['fine_tuned']['correct'], flush=True)
    report['summary'] = {key: {'correct': sum(r[key]['correct'] for r in report['rows']), 'total': len(selected),
                               'total_request_seconds': sum(r[key]['request_seconds'] for r in report['rows'])}
                         for key in ['initial', 'fine_tuned']}
    OUTPUT.write_text(json.dumps(report, indent=2) + '\n')
    def cell(value): return '<td>' + html.escape(str(value)) + '</td>'
    rows = []
    for r in report['rows']:
        rows.append('<tr>' + ''.join(cell(v) for v in [r['id'], r['classifier_split'],
            'faithful' if r['gold_faithful'] else 'unfaithful',
            '✓' if r['initial']['correct'] else '✗', f"{r['initial']['request_seconds']:.2f}",
            '✓' if r['fine_tuned']['correct'] else '✗', f"{r['fine_tuned']['request_seconds']:.2f}", 'Not recorded']) + '</tr>')
    page = '''<!doctype html><meta charset="utf-8"><title>Ten-problem fidelity benchmark</title>
<style>body{font:14px/1.6 ui-monospace,monospace;background:#f7f3eb;color:#302d28;margin:40px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #c7bfb2;padding:10px;text-align:left}h1{font-size:25px}th{background:#ece5d9}</style>
<h1>Ten-problem fidelity benchmark</h1>
<p>Same saved ProofNetVerif candidates, judged by initial Qwen and the fine-tuned fidelity classifier. This measures classification, not Lean generation.</p>
<p><strong>Overlap: 8 training problems, 1 development problem, 1 held-out problem. This is not a clean generalization result.</strong></p>
<table><thead><tr><th>Problem</th><th>Fine-tuning split</th><th>Gold label</th><th>Initial correct?</th><th>Initial time (s)</th><th>Fine-tuned correct?</th><th>Fine-tuned time (s)</th><th>Lea time</th></tr></thead><tbody>'''
    page += ''.join(rows) + '</tbody></table><h2>Measured totals</h2><ul>'
    for name, summary in report['summary'].items():
        page += f"<li>{html.escape(name)}: {summary['correct']}/10 correct; {summary['total_request_seconds']:.2f} seconds across ten requests.</li>"
    page += '</ul><p>Times are single measured warm requests including RPC overhead. Separate warm-up (includes cold start): ' + html.escape(json.dumps(report['warmup_seconds'])) + ' seconds.</p><p>Lea results and times were not saved in the merged branch. No claim that Lea is slower is supported by this experiment. The ten IDs are inferred from the runner defaults, not confirmed against the friend’s actual run.</p>'
    OUTPUT.with_suffix('.html').write_text(page)
    print(json.dumps(report['summary'], indent=2), flush=True)

if __name__ == '__main__':
    main()
