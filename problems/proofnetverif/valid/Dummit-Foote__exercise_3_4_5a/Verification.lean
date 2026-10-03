import Mathlib

open Fintype Subgroup Set Polynomial Ideal
open scoped BigOperators

universe u

def generated_statement : Prop :=
  ∀ {G : Type u} [Group G] (H : Subgroup G) [IsSolvable G], IsSolvable H

def reference_statement : Prop :=
  ∀ {G : Type u} [Group G] (H : Subgroup G) [IsSolvable G], IsSolvable H

theorem generated_iff_reference : generated_statement.{u} ↔ reference_statement.{u} := by
  constructor
  · intro h
    exact h
  · intro h
    exact h

#print axioms generated_iff_reference
