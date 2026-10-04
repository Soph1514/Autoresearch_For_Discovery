import { useEffect, useRef, useState } from "react";
import { useResearch } from "./research";
import { IdeaGraph, operationLabel } from "./IdeaGraph";
import { Composer } from "./Composer";
import type { Run, Snapshot } from "./contracts";
function RunProvenance({runId, status}: {runId: string; status: string}) {
  const [summary, setSummary] = useState<{formalization_id?: string; model?: string; reported_tokens?: number; generations?: number; stop_reason?: string} | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/runs/${runId}/summary`, {signal: controller.signal}).then(r => r.ok ? r.json() : null)
      .then(setSummary).catch(() => {});
    return () => controller.abort();
  }, [runId, status]);
  if (!summary) return null;
  return <div className="run-summary">
    {summary.formalization_id && <a href={`/?formalization=${summary.formalization_id}`}>Checked specification & alignment review ↗</a>}
    {summary.model && <span>Model: {summary.model}</span>}
    {summary.reported_tokens != null && <span>{summary.reported_tokens.toLocaleString()} reported evolution tokens · {summary.generations} generations · {summary.stop_reason?.replaceAll('_', ' ')}</span>}
  </div>;
}
function Witness({runId, candidateId}: {runId: string; candidateId: string}) {
  const [record, setRecord] = useState<{cases: Record<string, {output?: number[]; c1_exact?: {numerator: string; denominator: string}}> } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setRecord(null);
    fetch(`/api/runs/${runId}/numerical/${candidateId}`, {signal: controller.signal})
      .then(r => r.ok ? r.json() : null).then(setRecord).catch(() => {});
    return () => controller.abort();
  }, [runId, candidateId]);
  if (!record) return null;
  return <section><h3>Constructed witnesses</h3>{Object.entries(record.cases).map(([id, c]) => {
    if (!c.output || !c.c1_exact) return null;
    const q = c.output, peak = Math.max(...q), n = q.length;
    const path = q.map((x,i) => `${i ? 'L' : 'M'} ${10 + 280*i/n} ${90-75*x/peak} H ${10+280*(i+1)/n}`).join(' ');
    return <div key={id} className="witness">
      <p>{id} · {n} cells · c1 ≈ {(Number(c.c1_exact.numerator)/Number(c.c1_exact.denominator)).toFixed(8)}</p>
      <svg viewBox="0 0 300 112" role="img" aria-label={`Step function witness for ${id}, heights normalized for display`}>
        <path d="M10 90H290" stroke="#bcb5a9"/><path d={path} fill="none" stroke="#655d52" strokeWidth="1.5"/>
        <text x="10" y="108" fontSize="10">−1/4</text><text x="267" y="108" fontSize="10">1/4</text>
      </svg>
      <details><summary>Exact rational certificate</summary><p className="exact-score">{c.c1_exact.numerator} / {c.c1_exact.denominator}</p><p className="muted">Computed independently with integer arithmetic. Full integer heights are included in the evidence download.</p></details>
    </div>;
  })}</section>;
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
      {snapshot.run.backend === "python" && <Witness runId={snapshot.run.id} candidateId={idea.id} />}
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
        <p className="muted">Advisory only; validity and scores come from the evaluator.</p>
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
                    ? "Passed evaluator"
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
            {[...history].reverse().map(run => <option key={run.id} value={run.id}>{run.title} · {run.status} · {new Date(run.startedAt).toLocaleString('en-GB')}</option>)}
          </select>
          {snapshot && <span className="badge">{snapshot.run.status} · {snapshot.sequence} saved events</span>}
        </nav>}
        <section className="intro">
          <div>
            <div className="eyebrow">{custom ? "ALGORITHM RESEARCH" : "ROUTING GAMES / LOWER-BOUND SEARCH"}</div>
            <h1>{snapshot?.run.title ?? "A space for branching ideas."}</h1>
            {custom && <p className="muted">Exact numerical evaluation · lower c1 is better. A checked specification is not a proof of the optimal constant.</p>}
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
        {active && snapshot && <p className="activity" role="status">{status === 'paused' ? 'Paused between batches. Resume to continue.' : status === 'pausing' ? 'Finishing the active batch before pausing…' : status === 'stopping' ? 'Cancelling active work…' : snapshot.experiments.some(e => e.status === 'running') ? 'Evaluating candidate programs in the isolated worker…' : 'Research engine active · generating and reviewing the next batch. Model calls can take a few minutes.'}</p>}
        {snapshot && best !== null && <div className="run-summary">
          {improvement !== null && <span><strong>{improvement.toFixed(1)}%</strong> improvement over this run’s seed</span>}
          <span><strong>{snapshot.experiments.filter(e => e.valid).length}</strong> valid candidates</span>
          <span><strong>{snapshot.experiments.filter(e => e.valid === false).length}</strong> rejected attempts</span>
          <span><strong>{new Set(snapshot.elites.filter(e => e.current).map(e => e.ideaId)).size}</strong> current elites</span>
          <span><strong>{snapshot.generationFailures.length}</strong> generation failures</span>
          <button onClick={() => { const winner = snapshot.experiments.find(e => e.valid && e.metrics[metric] === best); if (winner) setSelected(winner.ideaId); }}>Inspect best candidate ↗</button>
        </div>}
        {snapshot ? (
          <>
            <div className="workspace">
              <IdeaGraph
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
                <strong>{value}</strong>
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
