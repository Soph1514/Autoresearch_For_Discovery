/** Shared handoff used by the workbench and the engine's problem composer. */
import { mountScorerReview, type SynthesisView } from './scorerReview';

type FitnessReference = { id: string; version: string };
export type PreparationFields = {
  seed: string; suite: string; cases: string; reviewed: boolean;
  instanceReviewed?: boolean;
  fitness: FitnessReference | null;
};

export function contractInput(formalizationId: string, fields: PreparationFields) {
  return {
    formalization_id: formalizationId,
    seed_program: fields.seed.trim() ? fields.seed : null,
    evaluation_suite_id: fields.suite,
    evaluation_cases: fields.cases.trim() ? JSON.parse(fields.cases) : null,
    fitness_function_id: fields.fitness?.id ?? null,
    fitness_function_version: fields.fitness?.version ?? null,
    alignment_reviewed: fields.reviewed,
    instance_reviewed: fields.instanceReviewed ?? false,
  };
}

/** Carries the server's structured detail so callers can react to it, not just show it. */
export class PreparationFailure extends Error {
  constructor(message: string, readonly detail: unknown) { super(message); }
}

export function synthesisRequired(detail: unknown): boolean {
  return Boolean(detail && typeof detail === 'object' && 'synthesis_required' in detail
    && (detail as { synthesis_required?: unknown }).synthesis_required);
}

export function preparationError(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'stage' in detail && 'message' in detail) {
    return `${detail.stage}: ${detail.message}`;
  }
  return 'Check the input fields and try again.';
}

export type InstanceReview = {
  lean?: string;
  instance?: string;
  evaluation_cases?: Record<string, Record<string, unknown>> | null;
  instance_error?: string | null;
  prepared_contract?: PreparedReview;
};

export type PreparedReview = {
  id: string; evaluation_cases: Record<string, Record<string, unknown>>;
  metric: string; direction: string;
  objective?: {lean: string; feasible: string} | null;
};

export function mountCustomResearch(host: HTMLElement, formalizationId: string, generated: InstanceReview = {}) {
  const hasInstance = Boolean(generated.instance?.trim());
  const controller = new AbortController();
  host.innerHTML = `<h3>Review Lean and instance JSON</h3>
    <div class="formulation-review">
    <section ${generated.lean ? '' : 'hidden'}>
      <label class="field">General problem — Lean<textarea data-field="lean-review" rows="14" readonly aria-label="Checked Lean source"></textarea></label>
      <label><input type="checkbox" data-field="reviewed"> I reviewed the Lean statement against my problem.</label>
    </section>
    <section>
    <label class="field">Instance JSON (editable)<textarea data-field="cases" rows="14" aria-label="Instance JSON"></textarea></label>
    <p data-instance-error role="alert" hidden></p>
    <p>${hasInstance ? 'Review the JSON against your instance description. These are the actual inputs research will solve. You can edit them before continuing.' : 'Cases are the concrete inputs used to compare algorithms. Leave this empty to generate small feasible starter cases for a compiled Lean problem.'}</p>
    <label ${hasInstance ? '' : 'hidden'}><input type="checkbox" data-field="instance-reviewed"> I reviewed the JSON inputs against my instance description.</label>
    <details ${hasInstance ? '' : 'hidden'}><summary>Your instance description</summary><p data-description></p></details>
    </section></div>
    <section data-objective class="objective-review" aria-label="Compiled objective" hidden>
      <h3>Objective function</h3><p data-objective-goal></p>
      <pre data-objective-source aria-label="Objective function Lean source"></pre>
      <details data-feasibility><summary>Feasibility predicate</summary><pre data-feasibility-source></pre></details>
    </section>
    <h3>Prepare algorithm research</h3>
    <p>Select an existing problem family to reuse its scorer. For a new problem, the compiler builds a scorer from the checked Lean. Compilation does not prove that Lean matches your description.</p>
    <label class="field">Problem family<select data-field="fitness" aria-label="Problem family"><option value="">New problem — Lean compiler</option></select></label>
    <label class="field">Evaluation suite ID<input data-field="suite" aria-label="Evaluation suite ID" value="instance"></label>
    <label class="field">Seed Python (optional)<textarea data-field="seed" rows="6" aria-label="Seed Python"></textarea></label>
    <p>Leave the seed empty to use the family baseline or the compiler’s initial candidate. The compiler’s candidate can be repaired during search.</p>
    <p><button type="button" data-action="prepare">Prepare research</button></p>
    <p data-status role="status"></p>
    <section data-review hidden></section>
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
  host.querySelector<HTMLElement>('[data-description]')!.textContent = generated.instance || '';
  field('lean-review').value = generated.lean || '';
  const cases = generated.prepared_contract?.evaluation_cases ?? generated.evaluation_cases;
  field('cases').value = cases ? JSON.stringify(cases, null, 2) : '';
  field('cases').setAttribute('placeholder', hasInstance ? 'Instance JSON unavailable. See the conversion error below.' : 'No instance JSON saved with this specification. Enter inputs or prepare to generate starter cases.');
  const instanceError = host.querySelector<HTMLElement>('[data-instance-error]')!;
  instanceError.textContent = generated.instance_error || '';
  instanceError.hidden = !generated.instance_error;
  const prepare = host.querySelector<HTMLButtonElement>('[data-action="prepare"]')!;
  const refresh = host.querySelector<HTMLButtonElement>('[data-action="refresh"]')!;
  const start = host.querySelector<HTMLButtonElement>('[data-action="start"]')!;
  const status = host.querySelector<HTMLElement>('[data-status]')!;
  const compilerLink = host.querySelector<HTMLAnchorElement>('[data-compiler]')!;
  const objective = host.querySelector<HTMLElement>('[data-objective]')!;
  function showObjective(result: PreparedReview) {
    objective.hidden = false;
    host.querySelector<HTMLElement>('[data-objective-goal]')!.textContent = `${result.direction} ${result.metric}`;
    host.querySelector<HTMLElement>('[data-objective-source]')!.textContent = result.objective?.lean || 'The selected scorer supplies this metric.';
    host.querySelector<HTMLElement>('[data-feasibility-source]')!.textContent = result.objective?.feasible || '';
    host.querySelector<HTMLElement>('[data-feasibility]')!.hidden = !result.objective?.feasible;
  }
  if (generated.prepared_contract) {
    showObjective(generated.prepared_contract);
    compilerLink.hidden = !generated.prepared_contract.objective;
    compilerLink.href = `/api/contracts/${encodeURIComponent(generated.prepared_contract.id)}/compiler`;
  }
  const reviewHost = host.querySelector<HTMLElement>('[data-review]')!;
  let disposeReview: (() => void) | null = null;
  const family = field('fitness') as HTMLSelectElement;
  let contractId: string | null = null;
  let evaluatorConfigured = false;
  let working = false;
  const inputs = Array.from(host.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('input, textarea, select'));
  const reviewed = () => !hasInstance || (
    (field('reviewed') as HTMLInputElement).checked &&
    (field('instance-reviewed') as HTMLInputElement).checked && Boolean(field('cases').value.trim()));
  const lock = (busy: boolean) => {
    working = busy; prepare.disabled = busy || !reviewed(); refresh.disabled = busy;
    inputs.forEach(input => { input.disabled = busy; });
    start.disabled = busy || !contractId || !evaluatorConfigured;
  };
  host.oninput = event => {
    const target = event.target as HTMLElement;
    if (target.dataset.field === 'cases') (field('instance-reviewed') as HTMLInputElement).checked = false;
    prepare.disabled = working || !reviewed();
    if (!['seconds', 'tokens', 'critic', 'dollars', 'model', 'literature', 'output', 'execution'].includes(target.dataset.field || '')) {
      contractId = null; start.disabled = true; compilerLink.hidden = true;
      if (target.dataset.field === 'fitness') objective.hidden = true;
    }
  };
  async function request(path: string, body?: unknown) {
    const response = await fetch(path, {method: body ? 'POST' : 'GET', signal: controller.signal,
      headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
    const result = await response.json();
    if (!response.ok) throw new PreparationFailure(preparationError(result.detail), result.detail);
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
    if (working || !reviewed()) return;
    const useCompiler = !family.value;
    lock(true); contractId = null; compilerLink.hidden = true;
    status.textContent = useCompiler ? 'Compiling and checking the Lean scorer…' : 'Preparing research with the registered scorer…';
    try {
      const result = await request('/api/contracts', contractInput(formalizationId, {
        seed: field('seed').value, suite: field('suite').value, cases: field('cases').value,
        fitness: family.value ? JSON.parse(family.value) : null,
        reviewed: (field('reviewed') as HTMLInputElement).checked,
        instanceReviewed: (field('instance-reviewed') as HTMLInputElement).checked,
      }));
      contractId = result.id;
      field('cases').value = JSON.stringify(result.evaluation_cases, null, 2);
      showObjective(result);
      objective.scrollIntoView({block: 'center'});
      compilerLink.hidden = !result.compiler;
      compilerLink.href = `/api/contracts/${encodeURIComponent(result.id)}/compiler`;
      const compiled = result.compiler ? 'Lean scorer compiled, verified and frozen. ' : 'Using the registered scorer. ';
      status.textContent = `${compiled}${result.signature} · ${result.direction} ${result.metric}. ${result.seed_status}.`;
      if (result.cases_generated) status.textContent += ' Generated feasible starter cases above; you can edit them before starting.';
      try {
        const ready = await capabilities();
        if (!evaluatorConfigured) status.textContent += ` ${ready.evaluator_error || 'Configure the research model before starting.'}`;
      } catch (error) {
        evaluatorConfigured = false;
        status.textContent += ` Research prepared; availability check failed: ${error instanceof Error ? error.message : String(error)}`;
      }
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : String(error);
      if (error instanceof PreparationFailure && synthesisRequired(error.detail)) {
        offerSynthesis(error.detail as { message?: string });
      }
    }
    finally { lock(false); }
  };
  function offerSynthesis(detail: { message?: string }) {
    // Offered, never started automatically: synthesis costs money.
    reviewHost.hidden = false;
    reviewHost.replaceChildren();
    const explain = document.createElement('p');
    explain.textContent = `The Lean compiler cannot build a scorer for this statement`
      + (detail.message ? `: ${detail.message}. ` : '. ')
      + 'Two models can each write one instead, a third picks one, and you decide '
      + 'whether to accept it. Up to three rounds; if you reject the last one, nothing '
      + 'is registered.';
    const begin = document.createElement('button');
    begin.type = 'button';
    begin.textContent = 'Synthesise a scorer for review';
    begin.onclick = async () => {
      begin.disabled = true;
      try {
        if (!field('cases').value.trim()) {
          throw Error('Enter case inputs above for scorer synthesis. Automatic cases require a compiled Lean scorer.');
        }
        const session = await request('/api/syntheses', {
          formalization_id: formalizationId,
          evaluation_suite_id: field('suite').value,
          evaluation_cases: JSON.parse(field('cases').value),
          seed_program: field('seed').value.trim() ? field('seed').value : null,
          alignment_reviewed: (field('reviewed') as HTMLInputElement).checked,
          instance_reviewed: (field('instance-reviewed') as HTMLInputElement).checked,
        });
        disposeReview?.();
        disposeReview = mountScorerReview(reviewHost, session.id, {
          onAccepted: view => { void prepareFromSynthesis(view); },
        });
      } catch (error) {
        explain.textContent = error instanceof Error ? error.message : String(error);
        begin.disabled = false;
      }
    };
    reviewHost.append(explain, begin);
  }
  async function prepareFromSynthesis(view: SynthesisView) {
    status.textContent = 'Freezing the contract around the scorer you accepted…';
    try {
      const result = await request('/api/contracts', {
        ...contractInput(formalizationId, {
          seed: field('seed').value, suite: field('suite').value, cases: field('cases').value,
          fitness: null, reviewed: (field('reviewed') as HTMLInputElement).checked,
          instanceReviewed: (field('instance-reviewed') as HTMLInputElement).checked,
        }),
        synthesis_id: view.id,
      });
      contractId = result.id;
      showObjective(result);
      objective.scrollIntoView({block: 'center'});
      status.textContent = `Contract frozen around the scorer you accepted. ${result.signature} · `
        + `${result.direction} ${result.metric}. Evidence tier: ${view.evidence_tier}.`;
      await capabilities();
      start.disabled = !evaluatorConfigured;
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : String(error);
    }
  }
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
  return () => { controller.abort(); disposeReview?.(); host.oninput = null; };
}
