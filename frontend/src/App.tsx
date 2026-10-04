import { useEffect, useRef, useState } from "react";
import { useResearch } from "./research";
import { IdeaGraph, operationLabel } from "./IdeaGraph";
import { Composer } from "./Composer";
import type { Run, Snapshot } from "./contracts";
function RunProvenance({runId, status}: {runId: string; status: string}) {
  const [summary, setSummary] = useState<{formalization_id?: string; contract_id?: string; compiler?: {status: string}; model?: string; reported_tokens?: number; generations?: number; stop_reason?: string;
    published_baseline?: {agent?: string; c1?: number; cells?: number; source?: string; repository?: string};
    budget?: {max_cost_usd: number; estimated_cost_usd: number; committed_cost_usd: number};
    literature?: {text: string; sources: {url: string; title: string}[]; queries: string[]}} | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => fetch(`/api/runs/${runId}/summary`, {signal: controller.signal}).then(r => r.ok ? r.json() : null)
      .then(setSummary).catch(() => {});
    void refresh();
    const timer = ["completed", "failed", "stopped"].includes(status) ? undefined : setInterval(refresh, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [runId, status]);
  if (!summary) return null;
  return <div className="run-summary">
    {summary.formalization_id && <a href={`/?formalization=${summary.formalization_id}`}>Checked specification & alignment review ↗</a>}
    {summary.published_baseline && <span>Imported published baseline: {summary.published_baseline.agent ?? 'TTT-Discover'}
      {summary.published_baseline.c1 != null && <> · c1 {summary.published_baseline.c1.toFixed(12)}</>}
      {summary.published_baseline.cells && <> · {summary.published_baseline.cells.toLocaleString()} cells</>}
      {' · credit belongs to the source construction; improvements are measured from this seed.'}</span>}
    {summary.compiler && summary.contract_id && <a href={`/api/contracts/${encodeURIComponent(summary.contract_id)}/compiler`} target="_blank" rel="noopener">Compiled scorer & verification ↗</a>}
    {summary.budget && <span>API estimate ${summary.budget.estimated_cost_usd.toFixed(2)} / ${summary.budget.max_cost_usd.toFixed(2)} cap · ${summary.budget.committed_cost_usd.toFixed(2)} including reservations</span>}
    {summary.literature && <details className="literature-review"><summary>Opening literature review · {summary.literature.sources.length} sources</summary>
      <p style={{whiteSpace: 'pre-wrap'}}>{summary.literature.text}</p>
      <ul>{summary.literature.sources.filter(s => /^https?:\/\//.test(s.url)).map(s => <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a></li>)}</ul>
      <p>Source claims guide exploration; only the fixed evaluator decides validity and scores.</p></details>}
    {summary.model && <span>Model: {summary.model}</span>}
    {summary.reported_tokens != null && <span>{summary.reported_tokens.toLocaleString()} reported evolution tokens · {summary.generations} generations · {summary.stop_reason?.replaceAll('_', ' ')}</span>}
  </div>;
}
type Rational = {numerator: string; denominator: string};
type CaseWitness = {output?: number[]; lower_bound?: number} & Record<string, unknown>;

function rationalFor(witness: CaseWitness, metric: string): Rational | undefined {
  // Every fitness function records its metric under "<metric>_exact".
  const value = witness[`${metric}_exact`] as Rational | undefined;
  return value && value.numerator !== undefined ? value : undefined;
}

function Witness({runId, candidateId, metric}: {runId: string; candidateId: string; metric?: string}) {
  const [record, setRecord] = useState<{cases: Record<string, CaseWitness & {fitness_evidence?: CaseWitness}>} | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setRecord(null);
    fetch(`/api/runs/${runId}/numerical/${candidateId}`, {signal: controller.signal})
      .then(r => r.ok ? r.json() : null).then(setRecord).catch(() => {});
    return () => controller.abort();
  }, [runId, candidateId]);
  // Without the run's metric name there is no witness key to look up.
  if (!record || !metric) return null;
  return <section><h3>Constructed witnesses</h3>{Object.entries(record.cases).map(([id, c]) => {
    const witness = c.fitness_evidence ?? c;
    if (witness?.kernel_checked && typeof witness.lean_certificate === 'string') {
      return <div key={id} className="witness">
        <p>{id} · Checked by the Lean kernel</p>
        <details><summary>Lean certificate</summary>
          <pre style={{whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'}}>{witness.lean_certificate}</pre>
        </details>
      </div>;
    }
    const exact = witness && rationalFor(witness, metric);
    if (!witness?.output || !exact) return null;
    const q = witness.output, n = q.length;
    const approx = Number(exact.numerator) / Number(exact.denominator);
    return <div key={id} className="witness">
      <p>{id} · {n} values · {metric} ≈ {Number.isInteger(approx) ? approx : approx.toFixed(8)}
        {witness.lower_bound !== undefined && <> · proven bound {witness.lower_bound}</>}</p>
      {/* The step-function plot only means anything for the autocorrelation family. */}
      {metric === "c1" ? <StepFunction id={id} values={q} /> : <OutputPreview values={q} />}
      <details><summary>Exact rational certificate</summary><p className="exact-score">{exact.numerator} / {exact.denominator}</p><p className="muted">Computed independently with integer arithmetic. The full witness is included in the evidence download.</p></details>
    </div>;
  })}</section>;
}

function StepFunction({id, values}: {id: string; values: number[]}) {
  const peak = Math.max(...values), n = values.length;
  const path = values.map((x,i) => `${i ? 'L' : 'M'} ${10 + 280*i/n} ${90-75*x/peak} H ${10+280*(i+1)/n}`).join(' ');
  return <svg viewBox="0 0 300 112" role="img" aria-label={`Step function witness for ${id}, heights normalized for display`}>
    <path d="M10 90H290" stroke="#bcb5a9"/><path d={path} fill="none" stroke="#655d52" strokeWidth="1.5"/>
    <text x="10" y="108" fontSize="10">−1/4</text><text x="267" y="108" fontSize="10">1/4</text>
  </svg>;
}

function OutputPreview({values}: {values: number[]}) {
  const shown = values.slice(0, 48);
  return <p className="exact-score">
    {shown.join(", ")}{values.length > shown.length && ` … (${values.length} values)`}
  </p>;
}
function Inspector({
  snapshot,
  selected,
  onSelect,
}: {
  snapshot: Snapshot;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const idea = snapshot.ideas.find((i) => i.id === selected);
  if (!idea)
    return (
      <aside className="inspector">
        <div className="eyebrow">RESEARCH NOTES</div>
        <h2>Follow an idea.</h2>
        <p className="muted">
          Select a node to inspect its hypothesis, ancestry, and experimental
          evidence.
        </p>
      </aside>
    );
  const elites = snapshot.elites.filter((e) => e.ideaId === idea.id);
  return (
    <aside className="inspector" aria-label="Idea details">
      <div className="eyebrow">
        IDEA {idea.id} / {operationLabel(idea.operation)}
      </div>
      <h2>{idea.title}</h2>
      {elites.map((e) => (
        <span key={e.niche} className="badge">
          {e.current ? "★ Elite" : "Former elite"} · {e.niche}
        </span>
      ))}
      {snapshot.run.backend === "python" && <Witness runId={snapshot.run.id} candidateId={idea.id} metric={snapshot.run.metricName} />}
      <h3>Candidate hypothesis</h3>
      <p className="muted">Proposed by the generator. Only the recorded test cases were evaluated.</p>
      <ul className="idea-points">{idea.description.split(/(?<=\.)\s+(?=[A-Z])/).map((point, i) => <li key={i}>{point}</li>)}</ul>
      <h3>How it was formed</h3>
      <div className="parent-links">
        {idea.parents.length ? (
          idea.parents.map((p) => (
            <button key={p} onClick={() => onSelect(p)}>
              Parent #{p}
            </button>
          ))
        ) : (
          <span>Initial seed</span>
        )}
      </div>
      {idea.operation === "merge" && (
        <p>
          Backend crossover; additional mutation is not separately reported.
        </p>
      )}
      {idea.mutation && (
        <p>
          <strong>Mutation:</strong> {idea.mutation}
        </p>
      )}
      {idea.island && <p>Search island: {idea.island}</p>}
      {idea.inspirations?.length ? (
        <>
          <h3>Inspirations (not parents)</h3>
          <div className="parent-links">
            {idea.inspirations.map((id) => (
              <button key={id} onClick={() => onSelect(id)}>
                {id}
              </button>
            ))}
          </div>
        </>
      ) : null}
      {idea.predictedEffect && (
        <p>
          <strong>Prediction:</strong> {idea.predictedEffect}
        </p>
      )}
      {idea.falsificationCondition && (
        <p>
          <strong>Falsification:</strong> {idea.falsificationCondition}
        </p>
      )}
      {idea.sourceCode && (
        <details>
          <summary>Candidate source</summary>
          <pre>{idea.sourceCode}</pre>
        </details>
      )}
      {(snapshot.assessments || []).filter(a => a.candidateId === idea.id).map(a => <section key={a.candidateId}>
        <h3>Advisory critic</h3>
        <p>{a.approachSummary}</p><p>{a.noveltyNote}</p>
        <p>Promise: {a.promiseRating}/5 · {a.model}</p>
        {a.riskFlags.length > 0 && <p>Risks: {a.riskFlags.join("; ")}</p>}
        <p className="muted">Advisory only; validity and scores come from the deterministic fitness function.</p>
      </section>)}
      <h3>Experiment attempts</h3>
      {snapshot.experiments
        .filter((e) => e.ideaId === idea.id)
        .map((e) => (
          <section className="attempt" key={e.id}>
            <div className="metric">
              <span>{e.id}</span>
              <strong>{e.status}</strong>
            </div>
            <div className="metric">
              <span>Validity</span>
              <strong>
                {e.valid === null
                  ? "Pending"
                  : e.valid
                    ? "Passed fitness function"
                    : "Failed"}
              </strong>
            </div>
            {Object.entries(e.metrics).map(([name, value]) => (
              <div className="metric" key={name}>
                <span>{name === "poa" ? "PoA witness" : name}</span>
                <strong>{value.toFixed(4)}</strong>
              </div>
            ))}
            <p className="feedback">
              {e.feedback || "Experiment in progress…"}
            </p>
          </section>
        ))}
    </aside>
  );
}
function ResearchLog({
  snapshot,
  onSelect,
}: {
  snapshot: Snapshot;
  onSelect: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [unread, setUnread] = useState(false);
  useEffect(() => {
    if (following.current && ref.current)
      ref.current.scrollTop = ref.current.scrollHeight;
    else setUnread(true);
  }, [snapshot.logs.length]);
  return (
    <section className="research-log">
      <div className="log-heading">
        <strong>Research log</strong>
        <span>{snapshot.run.status} · {snapshot.run.backend === "python-demo" ? "demo" : "research"} events</span>
        {unread && (
          <button
            onClick={() => {
              following.current = true;
              setUnread(false);
              if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
            }}
          >
            New updates ↓
          </button>
        )}
      </div>
      <div
        className="log-lines"
        ref={ref}
        role="log"
        aria-label="Research updates"
        onScroll={() => {
          const el = ref.current!;
          following.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 25;
          if (following.current) setUnread(false);
        }}
      >
        {snapshot.logs.map((l) => (
          <div className="log-line" key={l.id}>
            <time>{new Date(l.timestamp).toLocaleTimeString("en-GB")}</time>
            <span className="log-category">{l.category}</span>
            {l.ideaId ? (
              <button onClick={() => onSelect(l.ideaId!)}>
                #{l.ideaId} {l.message}
              </button>
            ) : (
              <span>{l.message}</span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
export default function App() {
  const { snapshot, error, busy, command } = useResearch();
  const [composer, setComposer] = useState(false),
    [selected, setSelected] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => setSelected(null), [snapshot?.run.id]);
  const [history, setHistory] = useState<Run[]>([]);
  useEffect(() => {
    fetch('/api/runs').then(r => { if (!r.ok) throw Error('History unavailable'); return r.json(); })
      .then(setHistory).catch(() => setHistory([]));
  }, [snapshot?.run.id, snapshot?.run.status]);
  const custom = snapshot?.run.backend === "python";
  const status = snapshot?.run.status;
  const active =
    status && ["running", "pausing", "paused", "stopping"].includes(status);
  const metric = snapshot?.run.metricName ?? "poa";
  const values =
    snapshot?.experiments
      .filter((e) => e.valid && e.metrics[metric] != null)
      .map((e) => e.metrics[metric]) ?? [];
  const best = values.length
    ? snapshot?.run.direction === "minimize"
      ? Math.min(...values)
      : Math.max(...values)
    : null;
  const winner = snapshot?.experiments.find(e => e.valid && e.metrics[metric] === best);
  useEffect(() => {
    if (status && ['completed', 'stopped', 'failed'].includes(status) && winner) setSelected(winner.ideaId);
  }, [snapshot?.run.id, status]);
  const baseline = snapshot?.experiments.find(e => e.ideaId === 'candidate-000000' && e.valid)?.metrics[metric];
  const improvement = best !== null && baseline && baseline !== 0 ?
    100 * (snapshot?.run.direction === 'minimize' ? baseline-best : best-baseline) / Math.abs(baseline) : null;
  const elapsed = snapshot
    ? Math.max(
        0,
        Math.floor(
          ((snapshot.run.endedAt ? Date.parse(snapshot.run.endedAt) : now) -
            Date.parse(snapshot.run.startedAt)) /
            1000,
        ),
      )
    : 0;
  return (
    <>
      <header>
        <span className="wordmark">Research lab</span>
        <span className="demo-label">
          {custom ? "PYTHON ENGINE · CUSTOM RESEARCH" : "PYTHON ENGINE · DEMO GENERATOR & EVALUATOR"}
        </span>
        <button onClick={() => setComposer(true)}>＋ Add problem</button>
        <a href="/">Back to workbench ↗</a>
        {active ? (
          <>
            <button
              className="primary"
              disabled={busy || status === "pausing" || status === "stopping"}
              onClick={() =>
                void command(status === "paused" ? "resume" : "pause")
              }
            >
              {status === "running"
                ? "Ⅱ Lab running"
                : status === "paused"
                  ? "▶ Lab paused"
                  : status === "pausing"
                    ? "Pausing…"
                    : "Stopping…"}
            </button>
            <button
              disabled={busy || status === "stopping"}
              onClick={() => void command("stop")}
            >
              Stop
            </button>
          </>
        ) : (
          <button
            className="primary"
            disabled={busy}
            onClick={() => void command("start")}
          >
            {snapshot && !custom ? "Run demo again" : "Run routing demo"}
          </button>
        )}
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <main>
        {history.length > 0 && <nav className="run-history" aria-label="Saved runs">
          <label htmlFor="run-history">Saved runs</label>
          <select id="run-history" value={snapshot?.run.id || ''} onChange={e => window.location.assign(`/engine.html?run=${encodeURIComponent(e.target.value)}`)}>
            <option value="" disabled>Select a research run</option>
            {[...history].reverse().map(run => <option key={run.id} value={run.id}>{run.title} · {run.id.slice(0, 8)} · {run.status} · {new Date(run.startedAt).toLocaleString('en-GB')}</option>)}
          </select>
          {snapshot && <span className="badge">{snapshot.run.status} · {snapshot.sequence} saved events</span>}
        </nav>}
        <section className="intro">
          <div>
            <div className="eyebrow">{custom ? "ALGORITHM RESEARCH" : "ROUTING GAMES / LOWER-BOUND SEARCH"}</div>
            <h1>{snapshot?.run.title ?? "A space for branching ideas."}</h1>
            {custom && <p className="muted">Deterministic evaluation · {snapshot?.run.direction === 'maximize' ? 'higher' : 'lower'} {snapshot?.run.metricName || 'objective'} is better. Candidate scores do not prove global optimality.</p>}
            {!custom && <><p className="muted">
              Pigou network · unit demand · route delays ℓ₁(x) = x and ℓ₂(x) = c
            </p>
            <p className="source">
              Known target: 4/3. This demo rediscovers a known bound.{" "}
              <a
                href="https://arxiv.org/abs/1907.10101"
                target="_blank"
                rel="noreferrer"
              >
                Research context ↗
              </a>
            </p></>}
          </div>
          <div className="stats">
            <div>
              <span>Candidates</span>
              <strong>{snapshot?.ideas.length ?? 0}</strong>
            </div>
            <div>
              <span>Best {metric === "poa" ? "PoA witness" : metric}</span>
              <strong>{best != null ? best.toFixed(4) : "—"}</strong>
            </div>
            <div>
              <span>Wall time</span>
              <strong>
                {String(Math.floor(elapsed / 60)).padStart(2, "0")}:
                {String(elapsed % 60).padStart(2, "0")}
              </strong>
            </div>
          </div>
        </section>
        {active && snapshot && <p className="activity" role="status">{status === 'paused' ? 'Paused between batches. Resume to continue.' : status === 'pausing' ? 'Finishing the active batch before pausing…' : status === 'stopping' ? 'Cancelling active work…' : snapshot.experiments.some(e => e.status === 'running') ? 'Evaluating candidate programs in the isolated worker…' : snapshot.ideas.length === 0 ? 'Searching and reviewing prior work before evolution…' : 'Research engine active · generating and reviewing the next batch. Model calls can take a few minutes.'}</p>}
        {snapshot && best !== null && <div className="run-summary">
          {improvement !== null && <span><strong>{improvement.toFixed(1)}%</strong> improvement over this run’s seed</span>}
          <span><strong>{snapshot.experiments.filter(e => e.valid).length}</strong> valid candidates</span>
          <span><strong>{snapshot.experiments.filter(e => e.valid === false).length}</strong> rejected attempts</span>
          <span><strong>{new Set(snapshot.elites.filter(e => e.current).map(e => e.ideaId)).size}</strong> current elites</span>
          <span><strong>{snapshot.generationFailures.length}</strong> generation failures</span>
          {!active && <strong>Final best in this run: {best.toFixed(6)} · {winner?.ideaId}</strong>}
          <button onClick={() => { if (winner) setSelected(winner.ideaId); }}>Inspect best candidate ↗</button>
        </div>}
        {snapshot ? (
          <>
            <div className="workspace">
              <IdeaGraph
                winnerId={winner?.ideaId}
                snapshot={snapshot}
                selected={selected}
                onSelect={setSelected}
              />
              <Inspector
                snapshot={snapshot}
                selected={selected}
                onSelect={setSelected}
              />
            </div>
            <ResearchLog snapshot={snapshot} onSelect={setSelected} />
          </>
        ) : (
          <section className="empty">
            <div className="branch-symbol">↗</div>
            <h2>Watch the research take shape.</h2>
            <p>
              Start the routing demo to explore hypotheses, two-parent merges,
              <br />
              mutations, failed attempts, and real island elite selection.
            </p>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void command("start")}
            >
              Run routing demo
            </button>
            <p className="muted">
              Use Add problem to generate or validate a Lean formulation.
              <br />
              Qwen fidelity scoring highlights formulations that need review.
            </p>
          </section>
        )}
        {snapshot && <RunProvenance runId={snapshot.run.id} status={snapshot.run.status} />}
        {snapshot && <p><a href={`/api/runs/${snapshot.run.id}/artifact`} download="research-run.json">Download run evidence</a></p>}
        {snapshot?.run.contract && (
          <details className="contract">
            <summary>Problem contract · Python backend</summary>
            {Object.entries(snapshot.run.contract).map(([key, value]) => (
              <div className="metric" key={key}>
                <span>{key}</span>
                <strong>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}</strong>
              </div>
            ))}
          </details>
        )}
        <footer>
          <span>
            All candidates preserved. Backend owns validity and archive
            decisions.
          </span>
          <span>Python backend · saved run history</span>
        </footer>
      </main>
      {composer && <Composer onClose={() => setComposer(false)} />}
    </>
  );
}
