import Mathlib

open Topology Filter Real Complex TopologicalSpace Finset
open scoped BigOperators

def generated_statement : Prop :=
  ∀ {k : ℕ} (hk : k ≥ 2) (x : EuclideanSpace ℝ (Fin k)),
    ∃ y : EuclideanSpace ℝ (Fin k), y ≠ 0 ∧ (inner x y : ℝ) = 0

def reference_statement : Prop :=
  ∀ (n : ℕ) (h : n > 1) (x : EuclideanSpace ℝ (Fin n)),
    ∃ (y : EuclideanSpace ℝ (Fin n)), y ≠ 0 ∧ (inner x y) = (0 : ℝ)

theorem generated_iff_reference : generated_statement ↔ reference_statement := by
  constructor
  · intro h n hn x
    exact h (k := n) hn x
  · intro h k hk x
    exact h k hk x

#print axioms generated_iff_reference
