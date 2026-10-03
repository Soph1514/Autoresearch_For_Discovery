import Mathlib

open Real
open scoped BigOperators

def generated_statement : Prop := ¬ ∃ x y : ℤ, 7 * x ^ 3 + 2 = y ^ 3

def reference_statement : Prop := ¬ ∃ x y : ℤ, 7*x^3 + 2 = y^3

theorem generated_iff_reference : generated_statement ↔ reference_statement := by
  unfold generated_statement reference_statement
  exact Iff.rfl

#print axioms generated_iff_reference
