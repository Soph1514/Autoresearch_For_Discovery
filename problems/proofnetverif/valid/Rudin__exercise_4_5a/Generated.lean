import Mathlib

open Topology Filter Real Complex TopologicalSpace Finset
open scoped BigOperators

theorem exercise_4_5a
  (f : ℝ → ℝ)
  (E : Set ℝ)
  (hf : ContinuousOn f E)
  (hE : IsClosed E) :
  ∃ (g : ℝ → ℝ), Continuous g ∧ ∀ x ∈ E, f x = g x := by sorry
