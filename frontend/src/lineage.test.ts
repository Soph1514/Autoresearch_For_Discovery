import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { Idea } from './contracts';
import { buildLineage, revealNext } from './lineage';
const idea = (id: string, parents: string[] = [], generation = 0): Idea => ({
  id, parents, generation, title: id, description: '', inactive: false, operation: parents.length ? 'mutation' : 'seed',
});

test('out-of-order arrivals and same-generation merges still form a downward DAG', () => {
  const { ordered, positions } = buildLineage([
    idea('merge', ['a', 'b'], 1), idea('a', ['seed'], 1), idea('b', ['seed'], 1), idea('seed'),
  ]);
  assert.deepEqual(ordered.map(i => i.id), ['seed', 'a', 'b', 'merge']);
  for (const node of ordered) for (const parent of node.parents) {
    assert.ok(positions[parent].y < positions[node.id].y);
  }
  assert.notEqual(positions.a.x, positions.b.x);
});

test('late children and independent restarts never relocate existing cards', () => {
  const initial = [idea('seed'), idea('a', ['seed'], 1), idea('b', ['seed'], 1)];
  const before = buildLineage(initial);
  const after = buildLineage([...initial, idea('fresh', [], 1), idea('merge', ['a', 'b'], 2)]);
  for (const node of initial) assert.deepEqual(after.positions[node.id], before.positions[node.id]);
  assert.equal(after.positions.fresh.y, after.positions.a.y);
});

test('cycles and missing parents are withheld until ancestry resolves', () => {
  const bad = [idea('orphan', ['missing']), idea('a', ['b']), idea('b', ['a']), idea('seed')];
  assert.deepEqual(buildLineage(bad).ordered.map(i => i.id), ['seed']);
  assert.deepEqual(buildLineage(bad).blocked, ['orphan', 'a', 'b']);
  assert.deepEqual(buildLineage([...bad, idea('missing')]).ordered.map(i => i.id), ['seed', 'missing', 'orphan']);
});

test('a burst reveals exactly one card each tick with all merge parents visible', () => {
  const { ordered } = buildLineage([idea('seed'), idea('a', ['seed']), idea('b', ['seed']), idea('merge', ['a', 'b'])]);
  let visible: string[] = [];
  for (let tick = 1; tick <= 4; tick++) {
    const next = revealNext(ordered, visible);
    assert.equal(next.length, visible.length + 1);
    const added = ordered.find(i => i.id === next.at(-1))!;
    assert.ok(added.parents.every(p => visible.includes(p)));
    visible = next;
  }
  assert.equal(revealNext(ordered, visible), visible);
});
