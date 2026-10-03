import Mathlib

open Topology Filter Real Complex TopologicalSpace Finset
open scoped BigOperators

def generated_statement : Prop :=
  ∀ (f : ℝ → ℝ) (E : Set ℝ), ContinuousOn f E → IsClosed E →
    ∃ (g : ℝ → ℝ), Continuous g ∧ ∀ x ∈ E, f x = g x

def reference_statement : Prop :=
  ∀ (f : ℝ → ℝ) (E : Set ℝ), IsClosed E → ContinuousOn f E →
    ∃ (g : ℝ → ℝ), Continuous g ∧ ∀ x ∈ E, f x = g x

theorem generated_iff_reference : generated_statement ↔ reference_statement := by
  constructor
  · intro h f E h1 h2
    exact h f E h2 h1
  · intro h f E h1 h2
    exact h f E h2 h1

#print axioms generated_iff_reference
