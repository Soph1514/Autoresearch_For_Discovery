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
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
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
  compact: boolean;
  parents: string[];
  select: () => void;
}>;
function IdeaBox({ data, selected, id }: NodeProps<IdeaNode>) {
  const updateInternals = useUpdateNodeInternals();
  useEffect(() => {
    const frame = requestAnimationFrame(() => updateInternals(id));
    return () => cancelAnimationFrame(frame);
  }, [id, data.compact, updateInternals]);
  return (
    <button
      type="button"
      onClick={data.select}
      aria-label={`Inspect idea ${id}: ${data.title}`}
      aria-pressed={selected}
      className={`idea-box ${data.elite ? "elite" : ""} ${data.inactive ? "inactive" : ""} ${selected ? "selected" : ""} ${data.compact ? "compact" : ""}`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="node-meta">
        IDEA {id}
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
          ` · ${data.parents.map((p) => "#" + p).join(" + ")}`}
      </div>
      {!data.compact && (
        <div className="node-score">
          {data.score != null
            ? `PoA ${data.score.toFixed(4)}`
            : data.status === "failed"
              ? "Invalid · evidence retained"
              : data.status === "cancelled"
                ? "Cancelled"
                : "Awaiting evaluation"}
        </div>
      )}
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
  const [compact, setCompact] = useState(true),
    [follow, setFollow] = useState(true);
  // Coalesce arriving candidates into readable reveal beats, without delaying logs.
  const [visibleIds, setVisibleIds] = useState<string[]>([]);
  const pendingIdeas = useRef(snapshot.ideas);
  pendingIdeas.current = snapshot.ideas;
  useEffect(() => {
    setVisibleIds(pendingIdeas.current.map((i) => i.id));
    const timer = setInterval(() => {
      const ids = pendingIdeas.current.map((i) => i.id);
      setVisibleIds((previous) =>
        previous.join() === ids.join() ? previous : ids,
      );
    }, 1000);
    return () => clearInterval(timer);
  }, [snapshot.run.id]);
  const visibleIdeas = snapshot.ideas.filter(
    (i) => visibleIds.includes(i.id) || i.id === selected,
  );
  const canvas = useRef<HTMLDivElement>(null);
  const flow = useReactFlow();
  const initialized = useRef(false);
  const previousRun = useRef(snapshot.run.id);
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
    .map(
      (i) =>
        i.id +
        ":" +
        i.parents.join(",") +
        ":" +
        (compact && inactiveIds.has(i.id)),
    )
    .join("|");
  const positions = useMemo(() => {
    const g = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: "TB",
      nodesep: 42,
      ranksep: 55,
      marginx: 24,
      marginy: 48,
    });
    visibleIdeas.forEach((i) =>
      g.setNode(i.id, {
        width: compact && inactiveIds.has(i.id) ? 164 : 202,
        height: compact && inactiveIds.has(i.id) ? 86 : 112,
      }),
    );
    visibleIdeas.forEach((i) => i.parents.forEach((p) => g.setEdge(p, i.id)));
    dagre.layout(g);
    return Object.fromEntries(
      visibleIdeas.map((i) => {
        const p = g.node(i.id);
        return [
          i.id,
          {
            x: p.x - (compact && inactiveIds.has(i.id) ? 82 : 101),
            y: p.y - (compact && inactiveIds.has(i.id) ? 43 : 56),
          },
        ];
      }),
    );
  }, [structuralKey, compact]);
  const nodes: IdeaNode[] = visibleIdeas.map((i) => {
    const experiment = snapshot.experiments
      .filter((e) => e.ideaId === i.id)
      .at(-1);
    const elite = snapshot.elites.some((e) => e.ideaId === i.id && e.current);
    return {
      id: i.id,
      type: "idea",
      width: compact && inactiveIds.has(i.id) ? 164 : 202,
      height: compact && inactiveIds.has(i.id) ? 86 : 112,
      position: positions[i.id],
      selected: i.id === selected,
      ariaLabel: `Idea ${i.id}: ${i.title}, ${operationLabel(i.operation)}`,
      data: {
        select: () => onSelect(i.id),
        title: i.title,
        operation: i.operation,
        parents: i.parents,
        status: experiment?.status ?? "proposed",
        elite,
        inactive: inactiveIds.has(i.id),
        score: experiment?.valid ? experiment.metrics.poa : undefined,
        compact: compact && inactiveIds.has(i.id),
      },
    };
  });
  const edges: Edge[] = visibleIdeas.flatMap((i) =>
    i.parents.map((p, index) => ({
      id: p + "-" + i.id,
      source: p,
      target: i.id,
      type: "default",
      className: inactiveIds.has(i.id) ? "receded-edge" : "",
      style: {
        stroke: index ? "#87a89b" : "#c2cbbb",
        strokeWidth: 1.25,
        strokeDasharray: index ? "5 5" : undefined,
      },
    })),
  );
  const generations = new Map<string, number>();
  for (const idea of visibleIdeas) {
    generations.set(
      idea.id,
      idea.parents.length
        ? 1 + Math.max(...idea.parents.map((p) => generations.get(p) ?? 0))
        : 0,
    );
  }
  const waveNodes: Node[] = Array.from(new Set(generations.values())).map(
    (generation) => {
      const members = nodes.filter((n) => generations.get(n.id) === generation);
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
            ][generation] ?? `${generation + 1} / NEXT GENERATION`,
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
    void flow.setViewport(viewport, {
      duration: reducedMotion ? 0 : gradual ? 1100 : 450,
    });
    initialized.current = true;
  }
  useEffect(() => {
    if (previousRun.current !== snapshot.run.id) {
      initialized.current = false;
      previousRun.current = snapshot.run.id;
      setFollow(true);
    }
    if (!follow && initialized.current) return;
    const timer = setTimeout(() => frameGraph(true), 120);
    return () => clearTimeout(timer);
  }, [structuralKey, snapshot.run.id, follow]);
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
            checked={compact}
            onChange={(e) => setCompact(e.target.checked)}
          />{" "}
          Compact inactive
        </label>
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
      <div className="graph-canvas" ref={canvas}>
        <ReactFlow
          nodes={[...waveNodes, ...nodes]}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, n) => onSelect(n.id)}
          onNodeDragStart={() => setFollow(false)}
          onMoveStart={(e) => {
            if (e) setFollow(false);
          }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          minZoom={0.2}
          maxZoom={1.5}
          proOptions={{ hideAttribution: false }}
        >
          <Background color="#d9dfd2" gap={23} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="graph-caption">
        Ideas arrive in waves. Faded branches remain available to inspect.
      </div>
    </section>
  );
}
export function IdeaGraph(props: Parameters<typeof Graph>[0]) {
  return (
    <ReactFlowProvider>
      <Graph {...props} />
    </ReactFlowProvider>
  );
}
