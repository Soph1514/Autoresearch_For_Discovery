import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

theorem exercise_13_6 (Tl TK : TopologicalSpace ℝ)
    (hl : Tl = generateFrom {S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ico a b})
    (hK : TK = generateFrom {S : Set ℝ | (∃ a b : ℝ, a < b ∧ S = Ioo a b) ∨
      (∃ a b : ℝ, a < b ∧ S = Ioo a b \ {x : ℝ | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)})}) :
    ¬ (Tl ≤ TK) ∧ ¬ (TK ≤ Tl) := by sorry
