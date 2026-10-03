import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

theorem exercise_18_8b {X Y : Type*} [TopologicalSpace X] [TopologicalSpace Y]
    [LinearOrder Y] [OrderTopology Y] (f g : X → Y)
    (hf : Continuous f) (hg : Continuous g) :
    Continuous (fun x => min (f x) (g x)) := by
  exact hf.min hg
