import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

def lower_limit_topology (X : Type) [Preorder X] :=
  generateFrom {S : Set X | ∃ a b, a < b ∧ S = Ico a b}

def Rl := lower_limit_topology ℝ

def K : Set ℝ := {r | ∃ n : ℕ, r = 1 / n}

def K_topology := generateFrom
  ({S : Set ℝ | ∃ a b, a < b ∧ S = Ioo a b} ∪ {S : Set ℝ | ∃ a b, a < b ∧ S = Ioo a b \ K})

def generated_statement : Prop :=
    let K : Set ℝ := {x | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)}
    let Rl : TopologicalSpace ℝ := generateFrom {S | ∃ a b : ℝ, S = Ico a b}
    let RK : TopologicalSpace ℝ :=
      generateFrom ({S | ∃ a b : ℝ, S = Ioo a b} ∪ {S | ∃ a b : ℝ, S = Ioo a b \ K})
    ¬ Rl ≤ RK ∧ ¬ RK ≤ Rl

def reference_statement : Prop :=
  ¬ (∀ U, Rl.IsOpen U → K_topology.IsOpen U) ∧ ¬ (∀ U, K_topology.IsOpen U → Rl.IsOpen U)

-- The reference statement is false: `K` contains `0` (since `1 / (0:ℝ) = 0`), so `K` is closed
-- and the "K-topology" coincides with a coarsening of the lower limit topology.
theorem reference_false : ¬ reference_statement := by
  intro h
  apply h.2
  intro U hU
  have hKc : IsClosed K := by
    have : K = insert 0 (range fun n : ℕ => 1 / (n : ℝ)) := by
      ext r
      simp only [K, mem_setOf_eq, mem_insert_iff, mem_range]
      constructor
      · rintro ⟨n, hn⟩; exact Or.inr ⟨n, hn.symm⟩
      · rintro (h | ⟨n, hn⟩)
        · exact ⟨0, by simp [h]⟩
        · exact ⟨n, hn.symm⟩
    rw [this]
    exact (tendsto_one_div_atTop_nhds_zero_nat.isCompact_insert_range).isClosed
  have hIco : ∀ a b : ℝ, a < b → IsOpen[Rl] (Ico a b) := fun a b hab =>
    TopologicalSpace.GenerateOpen.basic _ ⟨a, b, hab, rfl⟩
  have hstd : ∀ V : Set ℝ, IsOpen V → IsOpen[Rl] V := by
    intro V hV
    refine (@isOpen_iff_forall_mem_open ℝ V Rl).2 ?_
    intro x hx
    obtain ⟨ε, hε, hball⟩ := Metric.isOpen_iff.1 hV x hx
    refine ⟨Ico x (x + ε), ?_, hIco _ _ (by linarith), by simp [hε]⟩
    intro z hz
    apply hball
    rw [Metric.mem_ball, Real.dist_eq, abs_lt]
    constructor <;> linarith [hz.1, hz.2]
  have hle : Rl ≤ K_topology := by
    unfold K_topology
    rw [le_generateFrom_iff_subset_isOpen]
    rintro S (⟨a, b, -, rfl⟩ | ⟨a, b, -, rfl⟩)
    · exact hstd _ isOpen_Ioo
    · exact hstd _ (isOpen_Ioo.sdiff hKc)
  exact hle _ hU

#print axioms reference_false
