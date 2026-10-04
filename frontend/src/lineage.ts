import type { Idea } from './contracts';

/** Parent-first order. Unresolved ancestry (including cycles) stays off the DAG. */
export function buildLineage(ideas: Idea[]) {
  const pending = new Map(ideas.map(idea => [idea.id, idea]));
  const ordered: Idea[] = [];
  const positions: Record<string, { x: number; y: number }> = {};
  const ranks = new Map<string, number>();
  const rows = new Map<number, Set<number>>();
  while (pending.size) {
    const ready = [...pending.values()].find(idea =>
      idea.parents.every(parent => ranks.has(parent)));
    if (!ready) break;
    const rank = Math.max(0, ready.generation ?? 0,
      ...ready.parents.map(parent => ranks.get(parent)! + 1));
    const occupied = rows.get(rank) ?? new Set<number>();
    const target = ready.parents.length
      ? Math.round(ready.parents.reduce((sum, parent) => sum + positions[parent].x / 244, 0) / ready.parents.length)
      : 0;
    let lane = target;
    for (let distance = 0; occupied.has(lane); distance++) {
      lane = target + (distance % 2 === 0 ? 1 : -1) * (Math.floor(distance / 2) + 1);
    }
    occupied.add(lane);
    rows.set(rank, occupied);
    ranks.set(ready.id, rank);
    positions[ready.id] = { x: lane * 244, y: 48 + rank * 192 };
    ordered.push(ready);
    pending.delete(ready.id);
  }
  return { ordered, positions, ranks, blocked: [...pending.keys()] };
}

/** A display tick introduces at most one card, with every parent already visible. */
export function revealNext(ordered: Idea[], visible: string[]): string[] {
  const shown = new Set(visible);
  const next = ordered.find(idea => !shown.has(idea.id) && idea.parents.every(p => shown.has(p)));
  return next ? [...visible, next.id] : visible;
}
