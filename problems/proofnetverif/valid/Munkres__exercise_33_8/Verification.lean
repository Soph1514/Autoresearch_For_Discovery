import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

universe u

def generated_statement : Prop :=
  ∀ {X : Type u} [TopologicalSpace X] [CompletelyRegularSpace X]
    (A B : Set X) (_hA : IsClosed A) (_hB : IsClosed B) (_hAB : Disjoint A B)
    (_hAc : IsCompact A),
    ∃ f : X → unitInterval, Continuous f ∧ f '' A ⊆ {0} ∧ f '' B ⊆ {1}

def reference_statement : Prop :=
  ∀ (X : Type u) [TopologicalSpace X] [CompletelyRegularSpace X]
    (A B : Set X) (_hA : IsClosed A) (_hB : IsClosed B)
    (_hAB : Disjoint A B) (_hAc : IsCompact A),
    ∃ (f : X → Icc 0 1), Continuous f ∧ f '' A = {0} ∧ f '' B = {1}

/-- The reference statement is false (take A = B = ∅: then `f '' ∅ = ∅ ≠ {0}`),
whereas the generated statement is the (true) Munkres exercise. So the two
statements are NOT equivalent; no proof of `generated_iff_reference` exists
(unless the generated statement is false, which it is not). -/
theorem reference_false : ¬ reference_statement.{0} := by
  intro h
  obtain ⟨f, -, hf, -⟩ := h PUnit ∅ ∅ isClosed_empty isClosed_empty
    (disjoint_empty _) isCompact_empty
  rw [Set.image_empty] at hf
  exact (Set.singleton_ne_empty _) hf.symm

#print axioms reference_false
