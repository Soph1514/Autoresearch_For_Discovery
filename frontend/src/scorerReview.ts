/**
 * Human review of a model-synthesised scoring function.
 *
 * Shown only when the Lean compiler cannot express the checked statement. The
 * reviewer decides; the critic only recommends.
 *
 * Everything a model wrote reaches the DOM through textContent, never innerHTML.
 * The declared rules come first and the source is collapsed, because reviewing a
 * claim is a task a person can actually do and reading eighty lines of scoring
 * code is not.
 */

export type ReviewDecision = 'accept' | 'reject' | 'abandon';

export type ScorerCandidateView = {
  slot: string; model: string; framing: string; source_code: string;
  metric_names: string[]; descriptor_arity: number;
  descriptor_axes: { name?: string; lo?: number; hi?: number }[];
  validity_rules: string[]; objective_derivation: string; reconciliation_notes: string;
  static_problems: string[]; usable: boolean; error: string | null;
};

export type ScorerRoundView = {
  index: number;
  candidates: Record<string, ScorerCandidateView>;
  critic: {
    chosen: string | null; justification: string; key_differences: string[];
    residual_risks: string[]; unresolved_ambiguities: string[]; error: string | null;
  } | null;
  review: { decision: string; feedback: string } | null;
};

export type SynthesisView = {
  id: string; state: string; state_reason: string;
  round_index: number; max_rounds: number; evidence_tier: string;
  unsupported_reason: string;
  budget: { max_tokens: number; spent_tokens: number };
  rounds: ScorerRoundView[];
  accepted: { fitness_id: string; slot: string; model: string; round: number } | null;
  terminal: boolean;
};

const WORKING = ['extracting', 'generating', 'criticising'];

export const MIN_FEEDBACK = 20;

/** The standing caveat. Shown on every round, never softened by agreement. */
export const NOT_PROVEN =
  'This scoring function was written by a language model and chosen by another. ' +
  'Nothing here proves it matches the Lean statement, and the two models reading ' +
  'it the same way is not evidence that either is right. Results from this run are ' +
  'labelled lean_checked_synthesised and must not be reported beside kernel-checked ones.';

/** Rejecting is what drives the next round, so an empty reason is refused. */
export function canReject(feedback: string): boolean {
  return feedback.trim().length >= MIN_FEEDBACK;
}

/** Nothing can be accepted unless a module survived the conformance gate. */
export function canAccept(round: ScorerRoundView): boolean {
  return Object.values(round.candidates).some(candidate => candidate.usable);
}

/** The last round's rejection is terminal, so its button must say so. */
export function isFinalRound(view: SynthesisView): boolean {
  return view.round_index >= view.max_rounds;
}

export function rejectLabel(view: SynthesisView): string {
  return isFinalRound(view)
    ? 'Reject — this ends the synthesis and no contract will be created'
    : 'Reject and try again';
}

/** Slots ordered with the critic's pick first. */
export function slotOrder(round: ScorerRoundView): string[] {
  const chosen = round.critic?.chosen ?? null;
  return Object.keys(round.candidates).sort(
    (a, b) => (a === chosen ? -1 : b === chosen ? 1 : a.localeCompare(b)));
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, text?: string, className?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function list(items: string[], empty?: string): HTMLElement {
  if (!items.length) return el('p', empty ?? '(none)', 'muted');
  const ul = el('ul');
  for (const item of items) ul.append(el('li', item));
  return ul;
}

function candidateSection(candidate: ScorerCandidateView, chosen: boolean): HTMLElement {
  const section = el('section', undefined, chosen ? 'scorer chosen' : 'scorer');
  const heading = el('h4', `Module ${candidate.slot.toUpperCase()}${chosen ? ' — recommended' : ''}`);
  section.append(heading, el('p', `Written by ${candidate.model} (${candidate.framing}).`, 'muted'));

  if (candidate.error) {
    section.append(el('p', `Not generated: ${candidate.error}`, 'notice'));
    return section;
  }
  if (candidate.static_problems.length) {
    section.append(el('p', 'Rejected before review:', 'notice'), list(candidate.static_problems));
  }

  section.append(el('h5', 'Claimed feasibility rules'), list(candidate.validity_rules));
  section.append(el('h5', 'Claimed objective'), el('p', candidate.objective_derivation));
  section.append(el('p', `Metrics: ${candidate.metric_names.join(', ') || 'none'} · ` +
    `descriptor axes: ${candidate.descriptor_axes.map(a => a.name ?? '?').join(', ') || 'none'}`, 'muted'));
  if (candidate.reconciliation_notes.trim()) {
    section.append(el('h5', 'Conflicts it found against the Lean source'),
                   el('p', candidate.reconciliation_notes));
  }

  const details = el('details');
  details.append(el('summary', 'Source code'));
  const pre = el('pre');
  pre.append(el('code', candidate.source_code));
  details.append(pre);
  section.append(details);
  return section;
}

function criticSection(round: ScorerRoundView): HTMLElement {
  const section = el('section', undefined, 'critic');
  section.append(el('h4', 'The critic'));
  const critic = round.critic;
  if (!critic || critic.chosen === null) {
    section.append(el('p',
      `No recommendation: ${critic?.error ?? 'the critic produced nothing'}. ` +
      'Compare the two modules yourself.', 'notice'));
    return section;
  }
  section.append(el('p', `Recommends module ${critic.chosen.toUpperCase()}.`));
  section.append(el('p', critic.justification));
  section.append(el('h5', 'Where the two differ'),
                 list(critic.key_differences, 'The critic reported no differences. It did not run either module.'));
  section.append(el('h5', 'Risks it could not rule out'), list(critic.residual_risks));
  section.append(el('h5', 'Questions the specification does not answer'),
                 list(critic.unresolved_ambiguities));
  return section;
}

export function mountScorerReview(
  host: HTMLElement,
  sessionId: string,
  options: { onAccepted?: (view: SynthesisView) => void; pollMs?: number } = {},
): () => void {
  const controller = new AbortController();
  const pollMs = options.pollMs ?? 2000;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let busy = false;

  async function request(path: string, body?: unknown) {
    const response = await fetch(path, {
      method: body ? 'POST' : 'GET', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = result.detail;
      throw Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return result;
  }

  async function decide(decision: ReviewDecision, feedback: string, roundIndex: number) {
    if (busy) return;
    busy = true;
    try {
      const view: SynthesisView = await request(
        `/api/syntheses/${encodeURIComponent(sessionId)}/review`,
        { decision, feedback, round_index: roundIndex });
      render(view);
      if (view.state === 'accepted') options.onAccepted?.(view);
      if (!view.terminal) schedule();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      host.prepend(el('p', message, 'notice'));
    } finally {
      busy = false;
    }
  }

  function decisionControls(view: SynthesisView): HTMLElement {
    const section = el('section', undefined, 'decision');
    const round = view.rounds[view.rounds.length - 1];
    const usable = canAccept(round);
    const lastRound = isFinalRound(view);

    section.append(el('h4', 'Your decision'));
    const feedback = el('textarea');
    feedback.rows = 4;
    feedback.setAttribute('aria-label', 'Why are you rejecting this scorer?');
    feedback.placeholder =
      'What is wrong with it? This text is the only thing the next round is given.';
    const counter = el('p', '', 'muted');
    const accept = el('button', 'Accept this scorer');
    const reject = el('button', rejectLabel(view));
    const abandon = el('button', 'Abandon');
    accept.type = reject.type = abandon.type = 'button';
    if (lastRound) reject.className = 'destructive';
    accept.disabled = !usable;
    if (!usable) {
      section.append(el('p', 'Neither module can be accepted: both failed the conformance ' +
        'gate. Reject with feedback, or abandon.', 'notice'));
    }

    const sync = () => {
      const length = feedback.value.trim().length;
      reject.disabled = !canReject(feedback.value);
      counter.textContent = length < MIN_FEEDBACK
        ? `${MIN_FEEDBACK - length} more characters needed to reject.`
        : `${length} characters.`;
    };
    feedback.oninput = sync;
    sync();

    accept.onclick = () => decide('accept', '', view.round_index);
    reject.onclick = () => decide('reject', feedback.value, view.round_index);
    abandon.onclick = () => decide('abandon', '', view.round_index);

    section.append(el('label', 'Reason for rejecting'), feedback, counter);
    const buttons = el('p');
    buttons.append(accept, ' ', reject, ' ', abandon);
    section.append(buttons);
    return section;
  }

  function render(view: SynthesisView) {
    host.replaceChildren();
    host.append(el('h3', 'Review the synthesised scoring function'));
    host.append(el('p',
      `Round ${Math.max(view.round_index, 1)} of ${view.max_rounds} · ${view.state} · ` +
      `${view.budget.spent_tokens.toLocaleString()} of ` +
      `${view.budget.max_tokens.toLocaleString()} tokens used`, 'muted'));
    if (view.unsupported_reason) {
      host.append(el('p', `The Lean compiler could not build a scorer: ${view.unsupported_reason}`,
                     'muted'));
    }
    host.append(el('p', NOT_PROVEN, 'notice'));

    if (WORKING.includes(view.state)) {
      host.append(el('p', 'Writing two independent scoring functions and comparing them…',
                     'muted'));
      return;
    }
    if (view.state === 'accepted') {
      host.append(el('p', `Accepted module ${view.accepted?.slot.toUpperCase()} from round ` +
        `${view.accepted?.round}. Preparing the contract…`));
      return;
    }
    if (view.state !== 'awaiting_review') {
      host.append(el('p', view.state_reason || `This synthesis is ${view.state}.`, 'notice'));
      host.append(el('p', 'Nothing was registered and no contract was created.'));
      if (view.rounds.length) host.append(historySection(view));
      return;
    }

    const round = view.rounds[view.rounds.length - 1];
    host.append(criticSection(round));
    const chosen = round.critic?.chosen ?? null;
    for (const slot of slotOrder(round)) {
      host.append(candidateSection(round.candidates[slot], slot === chosen));
    }
    host.append(decisionControls(view));
    if (view.rounds.length > 1) host.append(historySection(view));
  }

  function historySection(view: SynthesisView): HTMLElement {
    const details = el('details');
    details.append(el('summary', `Earlier rounds (${view.rounds.length})`));
    for (const round of view.rounds) {
      const entry = el('p');
      const decision = round.review
        ? `${round.review.decision}${round.review.feedback ? `: ${round.review.feedback}` : ''}`
        : 'no decision recorded';
      entry.textContent = `Round ${round.index} — ${decision}`;
      details.append(entry);
    }
    return details;
  }

  function schedule() {
    timer = setTimeout(poll, pollMs);
  }

  async function poll() {
    try {
      const view: SynthesisView = await request(`/api/syntheses/${encodeURIComponent(sessionId)}`);
      render(view);
      if (view.state === 'accepted') options.onAccepted?.(view);
      else if (!view.terminal) schedule();
    } catch (error) {
      if (controller.signal.aborted) return;
      host.replaceChildren(el('p', error instanceof Error ? error.message : String(error),
                              'notice'));
      schedule();
    }
  }

  host.replaceChildren(el('p', 'Loading the synthesised scoring functions…', 'muted'));
  void poll();
  return () => {
    controller.abort();
    if (timer !== undefined) clearTimeout(timer);
  };
}
