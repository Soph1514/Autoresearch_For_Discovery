import Mathlib

open Topology Filter Real Complex TopologicalSpace Finset
open scoped BigOperators

theorem exercise_1_18a {k : ℕ} (hk : k ≥ 2) (x : EuclideanSpace ℝ (Fin k)) :
    ∃ y : EuclideanSpace ℝ (Fin k), y ≠ 0 ∧ (inner x y : ℝ) = 0 := by sorry
