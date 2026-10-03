import Mathlib

open Fintype Subgroup Set Polynomial Ideal
open scoped BigOperators

def generated_statement : Prop :=
  ∀ {p m : ℕ} (hp : Nat.Prime p) (hm : 0 < m),
    ∃ n : ℕ, 1 ≤ n ∧ (Ideal.span {(p : ZMod (p ^ m))}) ^ n = ⊥

def reference_statement : Prop :=
  ∀ {p m : ℕ} (hp : p.Prime),
    IsNilpotent (span ({↑p} : Set $ ZMod $ p^m) : Ideal $ ZMod $ p^m)

theorem generated_iff_reference : generated_statement ↔ reference_statement := by
  constructor
  · intro h p m hp
    rcases Nat.eq_zero_or_pos m with rfl | hm
    · refine ⟨1, ?_⟩
      haveI : Subsingleton (ZMod (p ^ 0)) := by
        simp only [pow_zero]; infer_instance
      exact Subsingleton.elim _ _
    · obtain ⟨n, -, hn⟩ := h hp hm
      exact ⟨n, hn⟩
  · intro h p m hp hm
    obtain ⟨n, hn⟩ := h (p := p) (m := m) hp
    rcases Nat.eq_zero_or_pos n with rfl | hn0
    · refine ⟨1, le_refl _, ?_⟩
      rw [pow_zero] at hn
      rw [Ideal.one_eq_top] at hn
      rw [pow_one]
      exact le_bot_iff.mp (le_trans le_top (le_of_eq hn))
    · exact ⟨n, hn0, hn⟩

#print axioms generated_iff_reference
