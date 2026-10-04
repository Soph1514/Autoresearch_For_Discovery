import test from 'node:test';
import assert from 'node:assert/strict';
import {layoutForest, nodeKey, project, treeUrl, type Tree} from './forestModel';
const tree = (id: string): Tree => ({id,title:id,status:'running',startedAt:'2026-01-01',generation:1,
  ideas:[{id:'candidate-0',title:'seed',parents:[],generation:0,operation:'seed',inactive:false},
    {id:'candidate-1',title:'child',parents:['candidate-0'],generation:1,operation:'mutation',inactive:false}]});
test('same candidate IDs in two trees retain distinct coordinates and URLs', () => {
  const nodes=layoutForest([tree('a'),tree('b')]);
  assert.equal(nodes.size,4);
  assert.notEqual(nodes.get(nodeKey('a','candidate-0'))?.y,nodes.get(nodeKey('b','candidate-0'))?.y);
  assert.equal(treeUrl('a b','c/d'),'/engine.html?run=a%20b&idea=c%2Fd');
});
test('rotation and tilt change the projected 3D geometry without changing lineage', () => {
  const p={x:100,y:100,z:80};
  const a=project(p,0,0,800,500,1), b=project(p,.5,.7,800,500,1);
  assert.notEqual(a.x,b.x);assert.notEqual(a.y,b.y);
  assert.ok(Object.values(b).every(Number.isFinite));
  assert.equal(layoutForest([]).size,0);
});
