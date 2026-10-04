import type { Run } from './contracts';
export interface ForestIdea { id: string; title: string; parents: string[]; generation: number; operation: string; inactive: boolean }
export interface Tree extends Run { author?: string; generation: number; ideas: ForestIdea[] }
export interface Bridge {
  id: string; sourceRunId: string; sourceIdeaId: string; targetRunId: string; targetIdeaId: string | null;
  relation: string; status: string; explanation: string; reasons: string[]; adaptation?: string; demo: boolean;
  baseline: number | null; targetEvidence: {valid: boolean; metrics: Record<string, number>; failure_reasons: string[]} | null;
}
export interface Forest {
  trees: Tree[]; bridges: Bridge[];
  policy: {interval: number; materialImprovement: number; iteration: string; concurrentBatches: number};
}
export const treeUrl = (run: string, idea?: string | null) =>
  `/engine.html?run=${encodeURIComponent(run)}${idea ? `&idea=${encodeURIComponent(idea)}` : ''}`;
export const nodeKey = (run: string, idea: string) => JSON.stringify([run, idea]);
export type Point3 = {x: number; y: number; z: number};
export function project(p: Point3, yaw: number, tilt: number, width: number, height: number, zoom: number) {
  const x = p.x * Math.cos(yaw) - p.z * Math.sin(yaw);
  const depth = p.x * Math.sin(yaw) + p.z * Math.cos(yaw);
  return {x: width / 2 + x * zoom, y: height / 2 + (p.y * Math.cos(tilt) - depth * Math.sin(tilt)) * zoom,
    depth: p.y * Math.sin(tilt) + depth * Math.cos(tilt)};
}
export function layoutForest(trees: Tree[]) {
  const nodes = new Map<string, Point3>();
  trees.forEach((tree, layer) => {
    const levels = new Map<number, ForestIdea[]>();
    for (const idea of tree.ideas) {
      const generation = idea.generation ?? 0;
      levels.set(generation, [...(levels.get(generation) ?? []), idea]);
    }
    const max = Math.max(1, ...levels.keys());
    for (const [generation, ideas] of levels) ideas.forEach((idea, index) => nodes.set(nodeKey(tree.id, idea.id), {
      x: ((index + 1) / (ideas.length + 1) - .5) * 560,
      y: (layer - (trees.length - 1) / 2) * 180,
      z: (generation / max - .5) * 300,
    }));
  });
  return nodes;
}
