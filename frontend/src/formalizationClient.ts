export interface Progress {
  type: string; stage?: string; attempt?: number; lean?: string; diagnostics?: string; valid?: boolean;
}
export async function formalize(input: {mode: string; problem: string; instance: string; lean: string}, signal: AbortSignal,
  progress: (event: Progress) => void) {
  const response = await fetch('/api/formalizations?stream=true', {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(input), signal});
  if (!response.ok) {
    const error = await response.json();
    throw Error(typeof error.detail === 'string' ? error.detail : 'Could not submit formulation.');
  }
  if (!response.body) throw Error('The server did not return a progress stream.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  try {
    while (true) {
      const {done, value} = await reader.read();
      pending += decoder.decode(value, {stream: !done});
      let end;
      while ((end = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, end); pending = pending.slice(end + 1);
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === 'result') return event.result;
        if (event.type === 'error') throw Error(event.message);
        if (event.type === 'progress') progress(event);
      }
      if (done) throw Error('Connection closed before completion. The latest source is preserved.');
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
