import Mathlib

open Fintype Subgroup Set Polynomial Ideal
open scoped BigOperators

def generated_statement : Prop :=
  ∀ {p m : ℕ} (hp : Nat.Prime p) (hm : 0 < m),
    IsNilpotent (Ideal.span ({(p : ZMod (p ^ m))} : Set (ZMod (p ^ m))))

def reference_statement : Prop :=
  ∀ {p m : ℕ} (hp : p.Prime),
    IsNilpotent (span ({↑p} : Set $ ZMod $ p^m) : Ideal $ ZMod $ p^m)

theorem generated_iff_reference : generated_statement ↔ reference_statement := by
  constructor
  · intro h p m hp
    rcases Nat.eq_zero_or_pos m with rfl | hm
    · haveI : Subsingleton (ZMod (p ^ 0)) := by
        rw [pow_zero]; infer_instance
      haveI : Subsingleton (Ideal (ZMod (p ^ 0))) := inferInstance
      exact ⟨1, Subsingleton.elim _ _⟩
    · exact h hp hm
  · intro h p m hp _
    exact h hp

#print axioms generated_iff_reference
