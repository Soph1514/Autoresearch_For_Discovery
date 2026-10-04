import { useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  Handle,
  Position,
  useReactFlow,
  useUpdateNodeInternals,
  type NodeProps,
  type Node,
  type Edge,
  getViewportForBounds,
  MarkerType,
} from "@xyflow/react";
import { buildLineage, revealNext } from "./lineage";
import type { Snapshot } from "./contracts";
export const operationLabel = (op: string) =>
  op === "merge_mutation"
    ? "Merge + mutation"
    : op.charAt(0).toUpperCase() + op.slice(1);
type IdeaNode = Node<{
  title: string;
  operation: string;
  status: string;
  elite: boolean;
  inactive: boolean;
  score?: number;
  metric: string;
  parents: string[];
  select: () => void;
}>;
function IdeaBox({ data, selected, id }: NodeProps<IdeaNode>) {
  return (
    <button
      type="button"
      onClick={data.select}
      aria-label={`Inspect idea ${id}: ${data.title}`}
      aria-pressed={selected}
      className={`idea-box ${data.elite ? "elite" : ""} ${data.inactive ? "inactive" : ""} ${selected ? "selected" : ""}`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="node-meta">
        IDEA {id.replace("candidate-", "")}
        <span>
          {data.elite
            ? "★ ELITE"
            : data.status === "running"
              ? "● RUNNING"
              : data.status.toUpperCase()}
        </span>
      </div>
      <strong>{data.title}</strong>
      <div className="node-operation">
        {operationLabel(data.operation)}
        {data.parents.length > 0 &&
          ` · ${data.parents.map((p) => "#" + p.replace("candidate-", "")).join(" + ")}`}
      </div>
      <div className="node-score">
        {data.score != null
          ? `${data.metric} ${data.score.toFixed(4)}`
          : data.status === "failed"
            ? "Invalid · evidence retained"
            : data.status === "cancelled"
              ? "Cancelled"
              : "Awaiting evaluation"}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </button>
  );
}
function WaveLabel({ data }: NodeProps<Node<{ label: string }>>) {
  return <div className="wave-label">{data.label}</div>;
}
const nodeTypes = { idea: IdeaBox, wave: WaveLabel };
function Graph({
  snapshot,
  selected,
  onSelect,
}: {
  snapshot: Snapshot;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [follow, setFollow] = useState(true);
  const lineage = useMemo(() => buildLineage(snapshot.ideas), [snapshot.ideas]);
  const [visibleIds, setVisibleIds] = useState<string[]>(() =>
    ["completed", "stopped", "failed"].includes(snapshot.run.status)
      ? lineage.ordered.map(i => i.id) : []);
  const [displayPaused, setDisplayPaused] = useState(false);
  const [beat, setBeat] = useState(2000);
  const [replay, setReplay] = useState(0);
  const pendingIdeas = useRef(lineage.ordered);
  pendingIdeas.current = lineage.ordered;
  useEffect(() => {
    if (displayPaused) return;
    const timer = setInterval(() => {
      setVisibleIds(previous => revealNext(pendingIdeas.current, previous));
    }, beat);
    return () => clearInterval(timer);
  }, [displayPaused, beat, replay]);
  // Explicit inspection from the log may jump ahead, but never orphan a child.
  useEffect(() => {
    if (!selected) return;
    setDisplayPaused(true);
    const index = lineage.ordered.findIndex(i => i.id === selected);
    if (index >= 0) setVisibleIds(previous => [...new Set([
      ...previous, ...lineage.ordered.slice(0, index + 1).map(i => i.id),
    ])]);
  }, [selected]);
  const visibleIdeas = lineage.ordered.filter(i => visibleIds.includes(i.id));
  const queued = lineage.ordered.length - visibleIdeas.length;
  const canvas = useRef<HTMLDivElement>(null);
  const pointerStart = useRef<{ x: number; y: number } | null>(null);
  const flow = useReactFlow();
  const updateNodeInternals = useUpdateNodeInternals();
  const initialized = useRef(false);
  const [viewportReady, setViewportReady] = useState(false);
  const inactiveIds = new Set(
    snapshot.ideas
      .filter((i) => {
        const done = snapshot.experiments.some(
          (e) => e.ideaId === i.id && e.status !== "running",
        );
        const running = snapshot.experiments.some(
          (e) => e.ideaId === i.id && e.status === "running",
        );
        const elite = snapshot.elites.some(
          (e) => e.ideaId === i.id && e.current,
        );
        const former = snapshot.elites.some(
          (e) => e.ideaId === i.id && !e.current,
        );
        return done && !running && !elite && (i.inactive || former);
      })
      .map((i) => i.id),
  );
  const structuralKey = visibleIdeas
    .map((i) => i.id + ":" + i.parents.join(","))
    .join("|");
  const positions = lineage.positions;
  const nodes: IdeaNode[] = visibleIdeas.map((i) => {
    const experiment = snapshot.experiments
      .filter((e) => e.ideaId === i.id)
      .at(-1);
    const elite = snapshot.elites.some((e) => e.ideaId === i.id && e.current);
    return {
      id: i.id,
      type: "idea",
      width: 202,
      height: 112,
      position: positions[i.id],
      selected: i.id === selected,
      ariaLabel: `Idea ${i.id}: ${i.title}, ${operationLabel(i.operation)}`,
      data: {
        select: () => { setDisplayPaused(true); onSelect(i.id); },
        title: i.title,
        operation: i.operation,
        parents: i.parents,
        status: experiment?.status ?? "proposed",
        elite,
        inactive: inactiveIds.has(i.id),
        score: experiment?.valid
          ? experiment.metrics[snapshot.run.metricName ?? "poa"]
          : undefined,
        metric:
          snapshot.run.metricName === "poa" || !snapshot.run.metricName
            ? "PoA"
            : snapshot.run.metricName,
      },
    };
  });
  const edges: Edge[] = visibleIdeas.flatMap((i) =>
    i.parents.map((p, index) => ({
      id: p + "-" + i.id,
      source: p,
      target: i.id,
      type: "default",
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#958772" },
      className: inactiveIds.has(i.id) ? "receded-edge" : "",
      style: {
        stroke: index ? "#776953" : "#958772",
        strokeWidth: 1.8,
        strokeDasharray: index ? "5 5" : undefined,
      },
    })),
  );
  const waveNodes: Node[] = Array.from(new Set(visibleIdeas.map(i => lineage.ranks.get(i.id)!))).map(
    (generation) => {
      const members = nodes.filter((n) => lineage.ranks.get(n.id) === generation);
      return {
        id: `wave-${generation}`,
        type: "wave",
        position: {
          x: Math.min(...members.map((n) => n.position.x)),
          y: Math.min(...members.map((n) => n.position.y)) - 32,
        },
        width: 230,
        height: 20,
        selectable: false,
        draggable: false,
        focusable: false,
        data: {
          label:
            [
              `01 / STARTING POINT`,
              `02 / EXPLORE DIRECTIONS`,
              `03 / REFINE & COMBINE`,
            ][generation] ?? `${generation + 1} / NEXT LAYER`,
        },
      };
    },
  );
  const reducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  function frameGraph(gradual: boolean) {
    if (!nodes.length || !canvas.current) return;
    const left = Math.min(...nodes.map((n) => n.position.x)) - 25;
    const top = Math.min(...nodes.map((n) => n.position.y)) - 50;
    const right =
      Math.max(...nodes.map((n) => n.position.x + (n.width ?? 202))) + 25;
    const bottom =
      Math.max(...nodes.map((n) => n.position.y + (n.height ?? 112))) + 25;
    const viewport = getViewportForBounds(
      { x: left, y: top, width: right - left, height: bottom - top },
      canvas.current.clientWidth,
      canvas.current.clientHeight,
      0.2,
      0.88,
      0.12,
    );
    // Automatic framing only pulls back; it never zooms into a receding branch.
    if (gradual && initialized.current) {
      viewport.zoom = Math.min(viewport.zoom, flow.getZoom());
      viewport.x =
        canvas.current.clientWidth / 2 - ((left + right) / 2) * viewport.zoom;
      viewport.y =
        canvas.current.clientHeight / 2 - ((top + bottom) / 2) * viewport.zoom;
    }
    void flow
      .setViewport(viewport, {
        duration:
          !initialized.current || reducedMotion ? 0 : gradual ? 650 : 450,
      })
      .then(() => setViewportReady(true));
    initialized.current = true;
  }
  useEffect(() => {
    if (!follow && initialized.current) return;
    const timer = setTimeout(() => frameGraph(true), 120);
    return () => clearTimeout(timer);
  }, [structuralKey, follow]);
  useEffect(() => {
    if (!viewportReady) return;
    const frame = requestAnimationFrame(() => updateNodeInternals(visibleIdeas.map(i => i.id)));
    return () => cancelAnimationFrame(frame);
  }, [viewportReady, structuralKey, updateNodeInternals]);
  useEffect(() => {
    if (!selected || !positions[selected]) return;
    setFollow(false);
    const point = positions[selected];
    void flow.setCenter(point.x + 101, point.y + 56, {zoom: 0.95, duration: reducedMotion ? 0 : 350});
  }, [selected]);
  return (
    <section className="graph-panel">
      <div className="graph-toolbar">
        <strong>Idea lineage</strong>
        <span className="legend">
          ★ Elite <span>● Exploring</span> <span>○ Inactive</span>
        </span>
        <label>
          <input
            type="checkbox"
            checked={follow}
            onChange={(e) => setFollow(e.target.checked)}
          />{" "}
          Auto overview
        </label>
        <button onClick={() => frameGraph(false)}>Fit graph</button>
      </div>
      <div className="reveal-controls" role="group" aria-label="Lineage playback">
        <span aria-live="polite">{visibleIdeas.length} / {lineage.ordered.length} ideas shown · {queued} queued</span>
        <button onClick={() => setDisplayPaused(p => !p)}>{displayPaused ? "Play reveals" : "Pause reveals"}</button>
        <button disabled={!queued} onClick={() => {
          setDisplayPaused(true);
          setVisibleIds(previous => revealNext(pendingIdeas.current, previous));
        }}>Next idea</button>
        <label>Reveal pace <select aria-label="Reveal pace" value={beat} onChange={e => setBeat(Number(e.target.value))}>
          <option value={1000}>1 second</option>
          <option value={2000}>2 seconds</option>
          <option value={4000}>4 seconds</option>
        </select></label>
        <button onClick={() => { setVisibleIds([]); setDisplayPaused(false); setFollow(true); initialized.current = false; setReplay(value => value + 1); }}>Replay tree</button>
        <button disabled={!queued} onClick={() => setVisibleIds(lineage.ordered.map(i => i.id))}>Show all</button>
      </div>
      {lineage.blocked.length > 0 && <p role="alert">{lineage.blocked.length} ideas have missing or cyclic ancestry and cannot yet be drawn.</p>}
      <div
        className="graph-canvas"
        ref={canvas}
        style={{ visibility: viewportReady ? "visible" : "hidden" }}
        onWheelCapture={() => setFollow(false)}
        onPointerDownCapture={(event) => {
          pointerStart.current = { x: event.clientX, y: event.clientY };
        }}
        onPointerMoveCapture={(event) => {
          const start = pointerStart.current;
          if (
            start &&
            Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5
          )
            setFollow(false);
        }}
        onPointerUpCapture={() => {
          pointerStart.current = null;
        }}
        onPointerCancelCapture={() => {
          pointerStart.current = null;
        }}
      >
        <ReactFlow
          nodes={[...waveNodes, ...nodes]}
          edges={edges}
          nodeTypes={nodeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          minZoom={0.2}
          maxZoom={1.5}
          proOptions={{ hideAttribution: false }}
        >
          <Background color="#d5cfc4" gap={23} />
          <Controls
            showInteractive={false}
            onZoomIn={() => setFollow(false)}
            onZoomOut={() => setFollow(false)}
            onFitView={() => setFollow(false)}
          />
        </ReactFlow>
      </div>
      <div className="graph-caption">
        One idea per beat, parents before children. Display controls do not pause research. Replays show saved results, not historical evaluation timing.
      </div>
    </section>
  );
}
export function IdeaGraph(props: Parameters<typeof Graph>[0]) {
  return (
    <ReactFlowProvider>
      <Graph key={props.snapshot.run.id} {...props} />
    </ReactFlowProvider>
  );
}
