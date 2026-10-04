import { test } from 'node:test';
import assert from 'node:assert/strict';
import { contractInput, preparationError } from './customResearch';

test('blank cases request automatic generation; supplied edits are preserved', () => {
  const fields = {seed: '', suite: 'instance', cases: '  ', reviewed: true, fitness: null};
  assert.equal(contractInput('saved', fields).evaluation_cases, null);
  fields.cases = '{"edited":{"capacity":17}}';
  assert.deepEqual(contractInput('saved', fields).evaluation_cases, {edited: {capacity: 17}});
});

test('new problem requests compilation of saved Lean without a seed or scorer ID', () => {
  const body = contractInput('saved-lean', {seed: '', suite: 'instance',
    cases: '{"one":{"weights":[3,4,5],"capacity":7}}', reviewed: true, fitness: null});
  assert.equal(body.formalization_id, 'saved-lean');
  assert.equal(body.fitness_function_id, null);
  assert.equal(body.fitness_function_version, null);
  assert.equal(body.seed_program, null);
  assert.deepEqual(body.evaluation_cases, {one: {weights: [3,4,5], capacity: 7}});
  assert.equal(body.alignment_reviewed, true);
});

test('selected family uses its registered scorer and preserves a supplied seed', () => {
  const seed = 'def solve() -> int:\n    return 0\n';
  const body = contractInput('saved', {seed, suite: 'suite', cases: '{"one":{}}',
    reviewed: false, fitness: {id: 'knapsack', version: 'exact-v1'}});
  assert.equal(body.fitness_function_id, 'knapsack');
  assert.equal(body.fitness_function_version, 'exact-v1');
  assert.equal(body.seed_program, seed);
});

test('compiler rejection displays its stage and reason; invalid case JSON stops submission', () => {
  assert.equal(preparationError({stage: 'unsupported_formalization', message: 'No objective comparison'}),
    'unsupported_formalization: No objective comparison');
  assert.throws(() => contractInput('saved', {seed: '', suite: 'test', cases: '{', reviewed: true, fitness: null}));
});

test('instance review and edited JSON are submitted with Lean review', () => {
  const body = contractInput('saved', {seed: '', suite: 'instance',
    cases: '{"instance":{"weights":[3,4,5],"capacity":4}}', reviewed: true,
    instanceReviewed: true, fitness: null});
  assert.equal(body.instance_reviewed, true);
  assert.equal(body.alignment_reviewed, true);
  assert.equal(body.evaluation_cases.instance.capacity, 4);
});
