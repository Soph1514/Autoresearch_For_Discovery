import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

def generated_statement : Prop :=
  ∀ {X : Type} [TopologicalSpace X] [T1Space X] [CompletelyRegularSpace X]
    (A B : Set X) (_hA : IsClosed A) (_hB : IsClosed B) (_hAB : Disjoint A B)
    (_hAc : IsCompact A),
    ∃ f : X → unitInterval, Continuous f ∧ (∀ x ∈ A, f x = 0) ∧ (∀ x ∈ B, f x = 1)

def reference_statement : Prop :=
  ∀ (X : Type) [TopologicalSpace X] [CompletelyRegularSpace X]
    (A B : Set X) (_hA : IsClosed A) (_hB : IsClosed B)
    (_hAB : Disjoint A B)
    (_hAc : IsCompact A),
    ∃ (f : X → Icc (0:ℝ) 1), Continuous f ∧ f '' A = {0} ∧ f '' B = {1}

-- The reference statement is false (take A = B = ∅ in a one-point space),
-- so it cannot be equivalent to the (true) generated statement.
theorem reference_false : ¬ reference_statement := by
  intro h
  obtain ⟨f, -, hf, -⟩ := h PUnit (∅ : Set PUnit) ∅ isClosed_empty isClosed_empty
    disjoint_bot_left isCompact_empty
  simp only [Set.image_empty] at hf
  exact (Set.singleton_ne_empty _ hf.symm).elim

#print axioms reference_false
