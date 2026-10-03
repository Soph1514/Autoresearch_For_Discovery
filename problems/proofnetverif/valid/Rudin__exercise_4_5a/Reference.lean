import Mathlib

open Topology Filter Real Complex TopologicalSpace Finset
open scoped BigOperators



theorem exercise_4_5a
  (f : ℝ → ℝ)
  (E : Set ℝ)
  (h₁ : IsClosed E)
  (h₂ : ContinuousOn f E)
  : ∃ (g : ℝ → ℝ), Continuous g ∧ ∀ x ∈ E, f x = g x :=
