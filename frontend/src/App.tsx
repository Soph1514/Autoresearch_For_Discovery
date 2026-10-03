import { useEffect, useRef, useState } from "react";
import { useResearch } from "./research";
import { IdeaGraph, operationLabel } from "./IdeaGraph";
import { Composer } from "./Composer";
import type { Snapshot } from "./contracts";
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
      <p>{idea.description}</p>
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
      {idea.operation === "merge" && <p>No additional mutation.</p>}
      {idea.mutation && (
        <p>
          <strong>Mutation:</strong> {idea.mutation}
        </p>
      )}
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
                    ? "Analytically checked"
                    : "Failed"}
              </strong>
            </div>
            {Object.entries(e.metrics).map(([name, value]) => (
              <div className="metric" key={name}>
                <span>{name === "poa" ? "PoA witness" : name + " cost"}</span>
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
        <span>{snapshot.run.status} · demo events</span>
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
  const status = snapshot?.run.status;
  const active =
    status && ["running", "pausing", "paused", "stopping"].includes(status);
  const best = snapshot?.experiments
    .filter((e) => e.valid && e.metrics.poa != null)
    .reduce((v, e) => Math.max(v, e.metrics.poa), 0);
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
          DEMO · SCRIPTED SEARCH, ANALYTIC VALUES
        </span>
        <button onClick={() => setComposer(true)}>＋ Add problem</button>
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
            {snapshot ? "Run demo again" : "Run routing demo"}
          </button>
        )}
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <main>
        <section className="intro">
          <div>
            <div className="eyebrow">ROUTING GAMES / LOWER-BOUND SEARCH</div>
            <h1>{snapshot?.run.title ?? "A space for branching ideas."}</h1>
            <p className="muted">
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
            </p>
          </div>
          <div className="stats">
            <div>
              <span>Candidates</span>
              <strong>{snapshot?.ideas.length ?? 0}</strong>
            </div>
            <div>
              <span>Best PoA witness</span>
              <strong>{best ? best.toFixed(4) : "—"}</strong>
            </div>
            <div>
              <span>Elapsed</span>
              <strong>
                {String(Math.floor(elapsed / 60)).padStart(2, "0")}:
                {String(elapsed % 60).padStart(2, "0")}
              </strong>
            </div>
          </div>
        </section>
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
              mutations, failed attempts, and elite selection.
            </p>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void command("start")}
            >
              Run routing demo
            </button>
            <p className="muted">
              Your own problem can be previewed with Add problem.
              <br />
              Its interpretation and execution await the backend.
            </p>
          </section>
        )}
        <footer>
          <span>
            All candidates preserved. Backend owns validity and archive
            decisions.
          </span>
          <span>Local mock · resets on refresh</span>
        </footer>
      </main>
      {composer && <Composer onClose={() => setComposer(false)} />}
    </>
  );
}
