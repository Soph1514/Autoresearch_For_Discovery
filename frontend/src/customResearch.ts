/** Shared handoff used by the workbench and the engine's problem composer. */
type FitnessReference = { id: string; version: string };
export type PreparationFields = {
  seed: string; suite: string; cases: string; reviewed: boolean;
  fitness: FitnessReference | null;
};

export function contractInput(formalizationId: string, fields: PreparationFields) {
  return {
    formalization_id: formalizationId,
    seed_program: fields.seed.trim() ? fields.seed : null,
    evaluation_suite_id: fields.suite,
    evaluation_cases: JSON.parse(fields.cases),
    fitness_function_id: fields.fitness?.id ?? null,
    fitness_function_version: fields.fitness?.version ?? null,
    alignment_reviewed: fields.reviewed,
  };
}

export function preparationError(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'stage' in detail && 'message' in detail) {
    return `${detail.stage}: ${detail.message}`;
  }
  return 'Check the input fields and try again.';
}

export function mountCustomResearch(host: HTMLElement, formalizationId: string) {
  const controller = new AbortController();
  host.innerHTML = `<h3>Prepare algorithm research</h3>
    <p>Select an existing problem family to reuse its scorer. For a new problem, the compiler builds a scorer from the checked Lean. Compilation does not prove that Lean matches your description.</p>
    <label class="field">Problem family<select data-field="fitness" aria-label="Problem family"><option value="">New problem — Lean compiler</option></select></label>
    <label class="field">Evaluation suite ID<input data-field="suite" aria-label="Evaluation suite ID" value="instance"></label>
    <label class="field">Case inputs (JSON object keyed by case ID)<textarea data-field="cases" rows="6" aria-label="Case inputs" placeholder='{"case-1": {"parameter": 1}}'></textarea></label>
    <label class="field">Seed Python (optional)<textarea data-field="seed" rows="6" aria-label="Seed Python"></textarea></label>
    <p>Leave the seed empty to use the family baseline or the compiler’s initial candidate. The compiler’s candidate can be repaired during search.</p>
    <label><input type="checkbox" data-field="reviewed"> I reviewed the Lean statement against my problem.</label>
    <p><button type="button" data-action="prepare">Prepare research</button></p>
    <p data-status role="status"></p>
    <p><a data-compiler hidden target="_blank" rel="noopener">View compiler result</a></p>
    <button type="button" data-action="refresh">Check evaluator availability</button>
    <label class="field">Research time limit (seconds, optional)<input type="number" data-field="seconds" placeholder="No time cap" min="1"></label>
    <label class="field">Research API budget (USD)<input type="number" data-field="dollars" value="50" min="0.01" max="1000" step="0.01"></label>
    <p>Shared cap for literature search, generation and critic calls. Preparation and hosting are separate.</p>
    <label class="field">Reasoning model<select data-field="model"><option value="claude-opus-5-5">Opus 5.5 · high reasoning</option><option value="claude-opus-4-6">Opus 4.6 · high reasoning</option><option value="claude-sonnet-4-6">Sonnet 4.6 · high reasoning</option></select></label>
    <label><input type="checkbox" data-field="literature" checked> Search the literature before evolution</label>
    <label class="field">Output tokens per call (optional)<input type="number" data-field="output" placeholder="Model maximum" min="1" max="128000"></label>
    <label><input type="checkbox" data-field="execution"> Use the prepared contract's execution time limits</label>
    <label class="field">Token budget<input type="number" data-field="tokens" value="5000000" min="1" max="20000000"></label>
    <label class="field">Advisory critic calls<input type="number" data-field="critic" value="3" min="0" max="100"></label>
    <p><button type="button" data-action="start" disabled>Start research</button></p>`;
  const field = (name: string) => host.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(`[data-field="${name}"]`)!;
  const prepare = host.querySelector<HTMLButtonElement>('[data-action="prepare"]')!;
  const refresh = host.querySelector<HTMLButtonElement>('[data-action="refresh"]')!;
  const start = host.querySelector<HTMLButtonElement>('[data-action="start"]')!;
  const status = host.querySelector<HTMLElement>('[data-status]')!;
  const compilerLink = host.querySelector<HTMLAnchorElement>('[data-compiler]')!;
  const family = field('fitness') as HTMLSelectElement;
  let contractId: string | null = null;
  let evaluatorConfigured = false;
  let working = false;
  const inputs = Array.from(host.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('input, textarea, select'));
  const lock = (busy: boolean) => {
    working = busy; prepare.disabled = busy; refresh.disabled = busy;
    inputs.forEach(input => { input.disabled = busy; });
    start.disabled = busy || !contractId || !evaluatorConfigured;
  };
  host.oninput = event => {
    const target = event.target as HTMLElement;
    if (!['seconds', 'tokens', 'critic', 'dollars', 'model', 'literature', 'output', 'execution'].includes(target.dataset.field || '')) {
      contractId = null; start.disabled = true; compilerLink.hidden = true;
    }
  };
  async function request(path: string, body?: unknown) {
    const response = await fetch(path, {method: body ? 'POST' : 'GET', signal: controller.signal,
      headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
    const result = await response.json();
    if (!response.ok) throw Error(preparationError(result.detail));
    return result;
  }
  async function capabilities() {
    const result = await request('/api/capabilities');
    evaluatorConfigured = result.custom_evaluator_configured && result.model_configured && result.evaluator_ready !== false;
    const selection = family.value;
    family.options.length = 1;
    for (const reference of result.fitness_functions || []) {
      family.add(new Option(`${reference.id} (${reference.version})`, JSON.stringify({id: reference.id, version: reference.version})));
    }
    family.value = selection;
    return result;
  }
  async function refreshAvailability() {
    lock(true);
    try {
      const result = await capabilities();
      status.textContent = evaluatorConfigured ? (contractId ? 'Ready to start research.' : 'Choose a problem family and prepare research.') : (result.evaluator_error || 'Configure the research model before starting.');
    } catch (error) { status.textContent = error instanceof Error ? error.message : String(error); }
    finally { lock(false); }
  }
  refresh.onclick = refreshAvailability;
  prepare.onclick = async () => {
    if (working) return;
    const useCompiler = !family.value;
    lock(true); contractId = null; compilerLink.hidden = true;
    status.textContent = useCompiler ? 'Compiling and checking the Lean scorer…' : 'Preparing research with the registered scorer…';
    try {
      const result = await request('/api/contracts', contractInput(formalizationId, {
        seed: field('seed').value, suite: field('suite').value, cases: field('cases').value,
        fitness: family.value ? JSON.parse(family.value) : null,
        reviewed: (field('reviewed') as HTMLInputElement).checked,
      }));
      contractId = result.id;
      compilerLink.hidden = !result.compiler;
      compilerLink.href = `/api/contracts/${encodeURIComponent(result.id)}/compiler`;
      const compiled = result.compiler ? 'Lean scorer compiled, verified and frozen. ' : 'Using the registered scorer. ';
      status.textContent = `${compiled}${result.signature} · ${result.direction} ${result.metric}. ${result.seed_status}.`;
      try {
        const ready = await capabilities();
        if (!evaluatorConfigured) status.textContent += ` ${ready.evaluator_error || 'Configure the research model before starting.'}`;
      } catch (error) {
        evaluatorConfigured = false;
        status.textContent += ` Research prepared; availability check failed: ${error instanceof Error ? error.message : String(error)}`;
      }
    } catch (error) { status.textContent = error instanceof Error ? error.message : String(error); }
    finally { lock(false); }
  };
  start.onclick = async () => {
    if (working || !contractId) return;
    lock(true); status.textContent = 'Starting research…';
    try {
      const run = await request('/api/runs', {mode: 'custom', contract_id: contractId,
        max_cost_usd: Number(field('dollars').value), reasoning_model: field('model').value,
        literature_review: (field('literature') as HTMLInputElement).checked, max_critic_calls: Number(field('critic').value), max_tokens: Number(field('tokens').value), max_time_seconds: field('seconds').value ? Number(field('seconds').value) : null,
        max_output_tokens: field('output').value ? Number(field('output').value) : null,
        enforce_execution_time_limits: (field('execution') as HTMLInputElement).checked});
      sessionStorage.setItem('research-run', run.id);
      window.location.assign('/engine.html');
    } catch (error) { status.textContent = error instanceof Error ? error.message : String(error); lock(false); }
  };
  // Populate both composers from the actual server registry, rather than assuming a family.
  void refreshAvailability();
  return () => { controller.abort(); host.oninput = null; };
}
