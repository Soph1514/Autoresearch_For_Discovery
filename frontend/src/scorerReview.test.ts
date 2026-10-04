import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  MIN_FEEDBACK, NOT_PROVEN, canAccept, canReject, isFinalRound, rejectLabel, slotOrder,
  type ScorerRoundView, type SynthesisView,
} from './scorerReview';
import { preparationError, synthesisRequired } from './customResearch';

function candidate(slot: string, overrides: Record<string, unknown> = {}) {
  return {
    slot, model: `model-${slot}`, framing: 'lean_primary',
    source_code: 'def validate(output):\n    return None\n',
    metric_names: ['total_value'], descriptor_arity: 1,
    descriptor_axes: [{name: 'length', lo: 0, hi: 10}],
    validity_rules: ['output must be a list'], objective_derivation: 'sum of values',
    reconciliation_notes: '', static_problems: [], usable: true, error: null,
    ...overrides,
  };
}

function round(overrides: Record<string, unknown> = {}): ScorerRoundView {
  return {
    index: 1,
    candidates: {a: candidate('a'), b: candidate('b')},
    critic: {chosen: 'b', justification: 'B is closer', key_differences: [],
      residual_risks: [], unresolved_ambiguities: [], error: null},
    review: null,
    ...overrides,
  } as ScorerRoundView;
}

function view(overrides: Partial<SynthesisView> = {}): SynthesisView {
  return {
    id: 's-1', state: 'awaiting_review', state_reason: '', round_index: 1, max_rounds: 3,
    evidence_tier: 'lean_checked_synthesised', unsupported_reason: 'List Rat is not supported',
    budget: {max_tokens: 400000, spent_tokens: 1200}, rounds: [round()],
    accepted: null, terminal: false, ...overrides,
  } as SynthesisView;
}

test('a rejection needs an explanation, because it is all the next round is given', () => {
  assert.equal(canReject(''), false);
  assert.equal(canReject('  too short  '), false);
  assert.equal(canReject('x'.repeat(MIN_FEEDBACK)), true);
});

test('nothing can be accepted when both modules failed the conformance gate', () => {
  assert.equal(canAccept(round()), true);
  assert.equal(canAccept(round({candidates: {
    a: candidate('a', {usable: false, static_problems: ['bad import']}),
    b: candidate('b', {usable: false, static_problems: ['no descriptor']}),
  }})), false);
});

test('the final round warns that rejecting produces no contract', () => {
  assert.equal(isFinalRound(view()), false);
  assert.equal(rejectLabel(view()), 'Reject and try again');

  const last = view({round_index: 3});
  assert.equal(isFinalRound(last), true);
  assert.match(rejectLabel(last), /no contract will be created/);
});

test('the recommended module is shown first', () => {
  assert.deepEqual(slotOrder(round()), ['b', 'a']);
  assert.deepEqual(slotOrder(round({critic: null})), ['a', 'b']);
});

test('the standing caveat refuses to treat agreement as correctness', () => {
  assert.match(NOT_PROVEN, /Nothing here proves it matches the Lean statement/);
  assert.match(NOT_PROVEN, /not evidence that either is right/);
  assert.match(NOT_PROVEN, /lean_checked_synthesised/);
});

test('the 409 offer is recognised and other preparation failures are not', () => {
  assert.equal(synthesisRequired({synthesis_required: true, stage: 'unsupported_formalization'}), true);
  assert.equal(synthesisRequired({stage: 'lean_compile_failed', message: 'nope'}), false);
  assert.equal(synthesisRequired('a plain message'), false);
  assert.equal(synthesisRequired(null), false);
  assert.equal(preparationError({stage: 'unsupported_formalization', message: 'List Rat'}),
    'unsupported_formalization: List Rat');
});

test('the review panel never routes model output through innerHTML', () => {
  // Structural guarantee: synthesised source and critic prose are untrusted, so
  // the panel builds DOM nodes and assigns textContent only.
  const source = readFileSync(new URL('./scorerReview.ts', import.meta.url), 'utf8');
  // Match property access, so the prose above describing the rule does not trip it.
  for (const sink of ['.innerHTML', '.outerHTML', '.insertAdjacentHTML', 'document.write']) {
    assert.equal(source.includes(sink), false, `scorerReview.ts must not use ${sink}`);
  }
  assert.match(source, /textContent/);
});
