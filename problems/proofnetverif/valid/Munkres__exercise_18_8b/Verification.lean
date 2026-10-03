import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

universe u v

def generated_statement : Prop :=
  ∀ {X : Type u} {Y : Type v} [TopologicalSpace X] [TopologicalSpace Y]
    [LinearOrder Y] [OrderTopology Y] (f g : X → Y)
    (_hf : Continuous f) (_hg : Continuous g),
    Continuous (fun x => min (f x) (g x))

def reference_statement : Prop :=
  ∀ {X : Type u} {Y : Type v} [TopologicalSpace X] [TopologicalSpace Y]
    [LinearOrder Y] [OrderTopology Y] {f g : X → Y}
    (_hf : Continuous f) (_hg : Continuous g),
    Continuous (fun x => min (f x) (g x))

theorem generated_iff_reference : generated_statement.{u, v} ↔ reference_statement.{u, v} := by
  constructor
  · intro h X Y _ _ _ _ f g hf hg
    exact h f g hf hg
  · intro h X Y _ _ _ _ f g hf hg
    exact h hf hg

#print axioms generated_iff_reference
