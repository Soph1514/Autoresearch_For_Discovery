import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

theorem exercise_13_6 :
    let K : Set ℝ := {x | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)}
    let Rl : TopologicalSpace ℝ := generateFrom {S | ∃ a b : ℝ, S = Ico a b}
    let RK : TopologicalSpace ℝ :=
      generateFrom ({S | ∃ a b : ℝ, S = Ioo a b} ∪ {S | ∃ a b : ℝ, S = Ioo a b \ K})
    ¬ Rl ≤ RK ∧ ¬ RK ≤ Rl := by sorry
