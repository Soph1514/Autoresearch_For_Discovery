import Mathlib

open Fintype Subgroup Set Polynomial Ideal
open scoped BigOperators

theorem exercise_7_3_37 {p m : ℕ} (hp : Nat.Prime p) (hm : 0 < m) :
    ∃ n : ℕ, 1 ≤ n ∧ (Ideal.span {(p : ZMod (p ^ m))}) ^ n = ⊥ := by sorry
