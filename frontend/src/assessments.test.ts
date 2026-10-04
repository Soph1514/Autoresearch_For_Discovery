import test from 'node:test';
import assert from 'node:assert/strict';
import { applyEvent, type Snapshot, type ResearchEvent } from './contracts';

test('critic events preserve validity and advance replay sequence on old snapshots', () => {
  const before: Snapshot = {schemaVersion: 1, sequence: 0, run: {id: 'run', title: 'test', status: 'running', startedAt: ''},
    ideas: [], experiments: [{id: 'eval', ideaId: 'c1', status: 'completed', valid: true, metrics: {c1: 2}, feedback: ''}],
    elites: [], logs: [], generationFailures: []};
  const event: ResearchEvent = {schemaVersion: 1, runId: 'run', eventId: 'e1', sequence: 1, timestamp: '',
    type: 'assessment_recorded', payload: {candidateId: 'c1', promiseRating: 4, approachSummary: 'test',
      noveltyNote: 'test', riskFlags: [], model: 'test', promptVersion: 'critic-v1'}};
  const after = applyEvent(before, event);
  assert.equal(after.sequence, 1);
  assert.equal(after.assessments?.length, 1);
  assert.deepEqual(after.experiments, before.experiments);
  assert.equal(applyEvent(after, {...event, sequence: 2}).assessments?.length, 1);
});
