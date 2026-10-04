/** Shared handoff used by the workbench and the engine's problem composer. */
export function mountCustomResearch(host: HTMLElement, formalizationId: string) {
  const controller = new AbortController();
  host.innerHTML = `<h3>Prepare algorithm research</h3>
    <p>Provide a baseline implementation and fixed evaluation cases for your evaluator.</p>
    <label class="field">Seed Python<textarea data-field="seed" rows="8" aria-label="Seed Python"></textarea></label>
    <label class="field">Evaluation suite ID<input data-field="suite" aria-label="Evaluation suite ID"></label>
    <label class="field">Case inputs (JSON object keyed by case ID)<textarea data-field="cases" rows="6" aria-label="Case inputs" placeholder='{"case-1": {"parameter": 1}}'></textarea></label>
    <label class="field">Evaluator version<input data-field="evaluator" aria-label="Evaluator version"></label>
    <label><input type="checkbox" data-field="reviewed"> I reviewed the Lean statement against my problem.</label>
    <p><button type="button" data-action="prepare">Prepare contract</button></p>
    <p data-status role="status"></p><button type="button" data-action="refresh">Check evaluator availability</button>
    <label class="field">Research time limit (seconds)<input type="number" data-field="seconds" value="300" min="1" max="3600"></label>
    <label class="field">Token budget<input type="number" data-field="tokens" value="32768" min="1" max="1000000"></label>
    <p><button type="button" data-action="start" disabled>Start research</button></p>`;
  const field = (name: string) => host.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[data-field="${name}"]`)!;
  const prepare = host.querySelector<HTMLButtonElement>('[data-action="prepare"]')!;
  const refresh = host.querySelector<HTMLButtonElement>('[data-action="refresh"]')!;
  const start = host.querySelector<HTMLButtonElement>('[data-action="start"]')!;
  const status = host.querySelector<HTMLElement>('[data-status]')!;
  let contractId: string | null = null;
  let evaluatorConfigured = false;
  let working = false;
  const inputs = Array.from(host.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input, textarea'));
  const lock = (busy: boolean) => {
    working = busy; prepare.disabled = busy; refresh.disabled = busy;
    inputs.forEach(input => { input.disabled = busy; });
    start.disabled = busy || !contractId || !evaluatorConfigured;
  };
  host.oninput = event => {
    const target = event.target as HTMLElement;
    if (!['seconds', 'tokens'].includes(target.dataset.field || '')) { contractId = null; start.disabled = true; }
  };
  async function request(path: string, body?: unknown) {
    const response = await fetch(path, {method: body ? 'POST' : 'GET', signal: controller.signal,
      headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
    const result = await response.json();
    if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Check the input fields and try again.');
    return result;
  }
  refresh.onclick = async () => {
    lock(true);
    try {
      const capabilities = await request('/api/capabilities');
      evaluatorConfigured = capabilities.custom_evaluator_configured && capabilities.model_configured;
      status.textContent = evaluatorConfigured ? (contractId ? 'Ready to evaluate the seed and start research.' : 'Evaluator configured. Prepare a contract first.') : 'Waiting for the evaluator and research model configuration.';
    } catch (error) { status.textContent = error instanceof Error ? error.message : String(error); }
    finally { lock(false); }
  };
  prepare.onclick = async () => {
    if (working) return;
    lock(true); contractId = null; status.textContent = 'Extracting the interface and validating your contract…';
    try {
      const result = await request('/api/contracts', {formalization_id: formalizationId,
        seed_program: field('seed').value, evaluation_suite_id: field('suite').value,
        evaluation_cases: JSON.parse(field('cases').value), evaluator_version: field('evaluator').value,
        alignment_reviewed: (field('reviewed') as HTMLInputElement).checked});
      contractId = result.id;
      const capabilities = await request('/api/capabilities');
      evaluatorConfigured = capabilities.custom_evaluator_configured && capabilities.model_configured;
      status.textContent = `${result.signature} · ${result.direction} ${result.metric}. Contract saved (${result.id}). ` +
        (evaluatorConfigured ? 'The seed will be evaluated before generation starts.' : 'Waiting for the Python evaluator to be connected.');
    } catch (error) { status.textContent = error instanceof Error ? error.message : String(error); }
    finally { lock(false); }
  };
  start.onclick = async () => {
    if (working || !contractId) return;
    lock(true); status.textContent = 'Starting research…';
    try {
      const run = await request('/api/runs', {mode: 'custom', contract_id: contractId,
        max_tokens: Number(field('tokens').value), max_time_seconds: Number(field('seconds').value)});
      sessionStorage.setItem('research-run', run.id);
      window.location.assign('/engine.html');
    } catch (error) { status.textContent = error instanceof Error ? error.message : String(error); lock(false); }
  };
  return () => { controller.abort(); host.oninput = null; };
}
