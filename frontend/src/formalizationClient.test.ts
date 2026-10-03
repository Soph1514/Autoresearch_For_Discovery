import test from 'node:test';
import assert from 'node:assert/strict';
import { formalize } from './formalizationClient';

test('streams failed checks before receiving a later success across chunk boundaries', async (t) => {
  const text = [
    {type:'progress', stage:'checked', attempt:1, valid:false, diagnostics:'unknown identifier'},
    {type:'progress', stage:'checking', attempt:3, lean:'fixed source'},
    {type:'result', result:{lean_checked:true, attempts:3}},
  ].map((event) => JSON.stringify(event) + '\n').join('');
  const encoder = new TextEncoder();
  t.mock.method(globalThis, 'fetch', async () => new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text.slice(0, 17)));
      controller.enqueue(encoder.encode(text.slice(17)));
      controller.close();
    },
  })));
  const events: unknown[] = [];
  const result = await formalize({mode:'natural', problem:'test', lean:''}, new AbortController().signal, (event) => events.push(event));
  assert.equal(events.length, 2);
  assert.equal(result.attempts, 3);
  assert.equal(result.lean_checked, true);
});

test('a broken connection does not report success', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('{"type":"heartbeat"}\n'));
  await assert.rejects(formalize({mode:'natural', problem:'test', lean:''}, new AbortController().signal, () => {}), /before completion/);
});
