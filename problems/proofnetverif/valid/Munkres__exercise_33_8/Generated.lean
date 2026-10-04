import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

theorem exercise_33_8 {X : Type*} [TopologicalSpace X] [CompletelyRegularSpace X]
    (A B : Set X) (hA : IsClosed A) (hB : IsClosed B) (hAB : Disjoint A B)
    (hAc : IsCompact A) :
    ∃ f : X → unitInterval, Continuous f ∧ f '' A ⊆ {0} ∧ f '' B ⊆ {1} := by sorry
