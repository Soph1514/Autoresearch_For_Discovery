import { useEffect, useRef, useState } from 'react';
import { layoutForest, nodeKey, project, treeUrl, type Bridge, type Forest } from './forestModel';
import './forest.css';

export function useForest() {
  const [forest, setForest] = useState<Forest | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const response = await fetch('/api/forest', {signal: controller.signal});
        if (!response.ok) throw Error('Could not load research trees.');
        setForest(await response.json()); setError('');
      } catch (e) { if (!controller.signal.aborted) setError(String(e)); }
      finally { if (!controller.signal.aborted) timer = setTimeout(refresh, 2000); }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  return {forest, error};
}

export function TreeNavigation({forest, selected, combined}: {forest: Forest | null; selected?: string; combined: boolean}) {
  return <nav className="tree-navigation" aria-label="Research pages">
    <a href="/engine.html?view=forest" aria-current={combined ? 'page' : undefined}>All trees · 3D</a>
    {forest?.trees.map(tree => <a key={tree.id} href={treeUrl(tree.id)} aria-current={!combined && selected === tree.id ? 'page' : undefined}>
      <span>{tree.title}</span><small>{tree.author || 'Anonymous mathematician'} · {tree.backend === 'python-demo' ? 'demo · ' : ''}{tree.status}</small>
    </a>)}
  </nav>;
}

function BridgeDetails({bridge, forest}: {bridge: Bridge; forest: Forest}) {
  const source = forest.trees.find(t => t.id === bridge.sourceRunId);
  const target = forest.trees.find(t => t.id === bridge.targetRunId);
  return <article className="bridge-detail">
    <div className="eyebrow">{bridge.demo ? 'DEMO · ' : ''}TECHNIQUE TRANSFER · {bridge.status}</div>
    <p><a href={treeUrl(bridge.sourceRunId, bridge.sourceIdeaId)}>{source?.title ?? 'Source tree'} ↗</a>
      {' → '}<a href={treeUrl(bridge.targetRunId, bridge.targetIdeaId)}>{target?.title ?? 'Receiving tree'} ↗</a></p>
    {bridge.demo && <p>Offline demo: scripted generation exercises the coordination flow.</p>}
    <p>{bridge.explanation}</p>
    {bridge.adaptation && <p>{bridge.adaptation}</p>}
    {bridge.targetEvidence && <p>Receiving evaluation: {bridge.targetEvidence.valid ? 'valid' : 'failed'}
      {Object.entries(bridge.targetEvidence.metrics).map(([name, value]) => <span key={name}> · {name}: {value.toFixed(4)}</span>)}
      {bridge.baseline != null && <> · best at dispatch: {bridge.baseline.toFixed(4)}</>}</p>}
    <small>Triggered by {bridge.reasons.map(r => r.replaceAll('_', ' ')).join(' + ')}. No mathematical equivalence is claimed.</small>
    <p><a href={`/api/forest/bridges/${encodeURIComponent(bridge.id)}`} target="_blank" rel="noreferrer">Inspect source and evaluation evidence ↗</a></p>
  </article>;
}

export function CollaborationTraces({forest, runId, ideaId}: {forest: Forest | null; runId: string; ideaId?: string}) {
  if (!forest) return null;
  const bridges = forest.bridges.filter(b => (b.sourceRunId === runId && (!ideaId || b.sourceIdeaId === ideaId)) ||
    (b.targetRunId === runId && (!ideaId || b.targetIdeaId === ideaId)));
  if (ideaId && !bridges.length) return null;
  return <section className="collaboration-traces" aria-label="Collaboration traces">
    <details open={Boolean(ideaId)}>
      <summary>Connections to other trees · {bridges.length}</summary>
      {bridges.length ? bridges.map(b => <BridgeDetails key={b.id} bridge={b} forest={forest}/>) :
        <p className="muted">Discovery runs on a new tree, every 10 iterations, and a materially better verified result.</p>}
    </details>
  </section>;
}

export function ForestView({forest, onAdd}: {forest: Forest | null; onAdd: () => void}) {
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [yaw, setYaw] = useState(-.3), [tilt, setTilt] = useState(.65);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState('');
  const drag = useRef<{x:number; y:number; yaw:number; tilt:number} | null>(null);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(host.current); return () => observer.disconnect();
  }, []);
  const trees = forest?.trees ?? [];
  const coordinates = layoutForest(trees);
  const height = Math.max(420, Math.min(760, trees.length * 130 + 240));
  const scale = Math.min(width / 800, height / Math.max(500, trees.length * 190));
  const point = (p: {x:number; y:number; z:number}) => project(p, yaw, tilt, width, height, scale);
  const positions = new Map([...coordinates].map(([key,p]) => [key, point(p)]));
  const chosen = forest?.bridges.find(b => b.id === selected);
  return <section className="forest-view">
    <div className="intro"><div><div className="eyebrow">SHARED RESEARCH</div><h1>A forest of ideas.</h1>
      <p className="muted">Each plane is a problem. Connections carry ideas and their evidence between trees.</p></div>
      <button className="primary" onClick={onAdd}>＋ Add problem</button></div>
    <div className="forest-controls">
      <label>Focus <select value={focus} onChange={e => setFocus(e.target.value)}><option value="">All problems</option>{trees.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label>
      <label>Rotate <input aria-label="Rotate forest" type="range" min="-1.4" max="1.4" step=".02" value={yaw} onChange={e=>setYaw(Number(e.target.value))}/></label>
      <label>Tilt <input aria-label="Tilt forest" type="range" min=".1" max="1.3" step=".02" value={tilt} onChange={e=>setTilt(Number(e.target.value))}/></label>
    </div>
    <div ref={host} className="forest-canvas">
      {trees.length === 0 ? <div className="empty"><h2>Your first idea starts here.</h2><p>Add a problem or a photo to grow a research tree.</p></div> :
      <svg viewBox={`0 0 ${width} ${height}`} style={{height}} role="img" aria-label="Stacked research trees in three dimensions. Drag to rotate, or use the rotation controls. Select a node to open its problem page."
        onPointerDown={e => {if ((e.target as Element).closest('a, [data-bridge]')) return; drag.current={x:e.clientX,y:e.clientY,yaw,tilt};e.currentTarget.setPointerCapture(e.pointerId);}}
        onPointerMove={e => {if(drag.current){setYaw(drag.current.yaw+(e.clientX-drag.current.x)*.005);setTilt(Math.max(.1,Math.min(1.3,drag.current.tilt+(e.clientY-drag.current.y)*.004)));}}}
        onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}>
        {trees.map((tree, index) => {
          const y=(index-(trees.length-1)/2)*180;
          const corners=[[-310,-175],[310,-175],[310,175],[-310,175]].map(([x,z])=>point({x,y,z}));
          return <g key={tree.id} opacity={!focus || focus===tree.id ? 1 : .2}>
            <polygon points={corners.map(p=>`${p.x},${p.y}`).join(' ')} className="forest-plane"/>
            <a href={treeUrl(tree.id)}><text x={corners[0].x+5} y={corners[0].y-10}>{tree.title.length>42 ? tree.title.slice(0,39)+'…' : tree.title}</text><title>{tree.title} · {tree.author}</title></a>
            {tree.ideas.flatMap(idea=>idea.parents.map(parent=>{
              const a=positions.get(nodeKey(tree.id,parent)),b=positions.get(nodeKey(tree.id,idea.id));
              return a&&b ? <line key={`${parent}:${idea.id}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="forest-lineage"/> : null;
            }))}
            {tree.ideas.map(idea=>{const p=positions.get(nodeKey(tree.id,idea.id))!;return <a key={idea.id} href={treeUrl(tree.id,idea.id)} aria-label={`Inspect ${idea.title}`}>
              <circle cx={p.x} cy={p.y} r={5} className={idea.inactive?'forest-node inactive':'forest-node'}/>
              <circle cx={p.x} cy={p.y} r={10} fill="transparent"/><title>{idea.title}</title></a>;})}
          </g>;
        })}
        {forest?.bridges.map(bridge=>{
          const a=positions.get(nodeKey(bridge.sourceRunId,bridge.sourceIdeaId));
          const target=trees.find(t=>t.id===bridge.targetRunId);
          const b=positions.get(nodeKey(bridge.targetRunId,bridge.targetIdeaId ?? target?.ideas[0]?.id ?? ''));
          if(!a||!b)return null;
          const d=`M${a.x},${a.y} C${a.x+55},${a.y},${b.x+55},${b.y},${b.x},${b.y}`;
          return <g key={bridge.id} data-bridge={bridge.id} onClick={()=>setSelected(bridge.id)} opacity={!focus || [bridge.sourceRunId,bridge.targetRunId].includes(focus)?1:.15}>
            <path d={d} className={`forest-bridge ${bridge.status==='improved'?'improved':''} ${selected===bridge.id?'selected':''}`}/>
            <path d={d} fill="none" stroke="transparent" strokeWidth="18"/><title>{bridge.status}: {bridge.explanation}</title>
          </g>;
        })}
      </svg>}
    </div>
    <p className="muted forest-caption">Solid lines: ancestry · Dashed curves: transfer attempts · Green curves: evaluated improvements</p>
    {chosen && forest && <BridgeDetails bridge={chosen} forest={forest}/>}
    {forest && <div className="forest-connections"><h2>Collaboration</h2>
      <p className="muted">New tree · every {forest.policy.interval} iterations · more than {forest.policy.materialImprovement*100}% verified improvement. One iteration is a completed generation.</p>
      {forest.bridges.length ? forest.bridges.map(b=><button key={b.id} aria-pressed={selected===b.id} onClick={()=>setSelected(b.id)}>
        {b.demo ? 'Demo · ' : ''}{forest.trees.find(t=>t.id===b.sourceRunId)?.title} → {forest.trees.find(t=>t.id===b.targetRunId)?.title} · {b.status}
      </button>) : <p>No connections yet. Trees share relevant, evaluated ideas as research progresses.</p>}
    </div>}
  </section>;
}
