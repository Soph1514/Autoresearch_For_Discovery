import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

/-! Reference auxiliary definitions (copied from Reference.lean). -/

def lower_limit_topology (X : Type) [Preorder X] :=
  generateFrom {S : Set X | ∃ a b, a < b ∧ S = Ico a b}

def Rl := lower_limit_topology ℝ

def K : Set ℝ := {r | ∃ n : ℕ, r = 1 / n}

def K_topology := generateFrom
  ({S : Set ℝ | ∃ a b, a < b ∧ S = Ioo a b} ∪ {S : Set ℝ | ∃ a b, a < b ∧ S = Ioo a b \ K})

def generated_statement : Prop :=
  ∀ (K : Set ℝ) (hK : K = {x : ℝ | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)})
    (Tl TK : TopologicalSpace ℝ)
    (hTl : Tl = generateFrom {S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ico a b})
    (hTK : TK = generateFrom ({S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ioo a b} ∪
      {S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ioo a b \ K})),
    ¬ (Tl ≤ TK) ∧ ¬ (TK ≤ Tl)

def reference_statement : Prop :=
  ¬ (∀ U, Rl.IsOpen U → K_topology.IsOpen U) ∧ ¬ (∀ U, K_topology.IsOpen U → Rl.IsOpen U)

/-! ### The reference K is closed (it contains 0 = 1/0), so the reference statement is false. -/

theorem K_closed : IsClosed K := by
  have h : IsCompact (insert (0:ℝ) (range fun n : ℕ => 1 / (n:ℝ))) :=
    (tendsto_const_div_atTop_nhds_zero_nat (1:ℝ)).isCompact_insert_range
  have : K = insert (0:ℝ) (range fun n : ℕ => 1 / (n:ℝ)) := by
    ext r
    simp only [K, mem_setOf_eq, mem_insert_iff, mem_range]
    constructor
    · rintro ⟨n, hn⟩; exact Or.inr ⟨n, hn.symm⟩
    · rintro (h | ⟨n, hn⟩)
      · exact ⟨0, by simp [h]⟩
      · exact ⟨n, hn.symm⟩
  rw [this]; exact h.isClosed

theorem std_open_Rl (U : Set ℝ) (hU : IsOpen U) :
    IsOpen[generateFrom {S : Set ℝ | ∃ a b, a < b ∧ S = Ico a b}] U := by
  letI T : TopologicalSpace ℝ := generateFrom {S : Set ℝ | ∃ a b, a < b ∧ S = Ico a b}
  rw [Metric.isOpen_iff] at hU
  have : ∀ x ∈ U, ∃ V, IsOpen[T] V ∧ x ∈ V ∧ V ⊆ U := by
    intro x hx
    obtain ⟨ε, hε, hb⟩ := hU x hx
    refine ⟨Ico x (x + ε), ?_, ⟨le_rfl, by linarith⟩, ?_⟩
    · exact TopologicalSpace.isOpen_generateFrom_of_mem ⟨x, x + ε, by linarith, rfl⟩
    · intro y hy
      apply hb
      rw [Metric.mem_ball, Real.dist_eq, abs_lt]
      constructor <;> linarith [hy.1, hy.2]
  have h2 : U = ⋃ x : U, Classical.choose (this x.1 x.2) := by
    ext y
    constructor
    · intro hy
      exact mem_iUnion.2 ⟨⟨y, hy⟩, (Classical.choose_spec (this y hy)).2.1⟩
    · intro hy
      obtain ⟨x, hx⟩ := mem_iUnion.1 hy
      exact (Classical.choose_spec (this x.1 x.2)).2.2 hx
  rw [h2]
  exact @isOpen_iUnion ℝ _ T _ (fun x => (Classical.choose_spec (this x.1 x.2)).1)

theorem reference_false : ¬ reference_statement := by
  intro ⟨_, hn⟩
  apply hn
  intro U hU
  induction hU with
  | basic s hs =>
    rcases hs with ⟨a, b, -, rfl⟩ | ⟨a, b, -, rfl⟩
    · exact std_open_Rl _ isOpen_Ioo
    · exact std_open_Rl _ (isOpen_Ioo.sdiff K_closed)
  | univ => exact @isOpen_univ ℝ Rl
  | inter s t _ _ h1 h2 => exact @TopologicalSpace.isOpen_inter ℝ Rl s t h1 h2
  | sUnion S _ ih => exact @isOpen_sUnion ℝ Rl S ih

/-! ### The generated statement is true. -/

theorem lemA (U : Set ℝ)
    (hU : IsOpen[generateFrom {S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ico a b}] U) (h0 : (0:ℝ) ∈ U) :
    ∃ ε > 0, Ico (0:ℝ) ε ⊆ U := by
  change TopologicalSpace.GenerateOpen _ U at hU
  induction hU with
  | basic s hs =>
    obtain ⟨a, b, -, rfl⟩ := hs
    exact ⟨b, by linarith [h0.2], fun y hy => ⟨by linarith [h0.1, hy.1], hy.2⟩⟩
  | univ => exact ⟨1, one_pos, fun _ _ => trivial⟩
  | inter s t _ _ h1 h2 =>
    obtain ⟨e1, p1, q1⟩ := h1 h0.1
    obtain ⟨e2, p2, q2⟩ := h2 h0.2
    refine ⟨min e1 e2, lt_min p1 p2, fun y hy => ⟨q1 ⟨hy.1, lt_of_lt_of_le hy.2 (min_le_left _ _)⟩,
      q2 ⟨hy.1, lt_of_lt_of_le hy.2 (min_le_right _ _)⟩⟩⟩
  | sUnion S _ ih =>
    obtain ⟨t, ht, h0t⟩ := h0
    obtain ⟨e, pe, qe⟩ := ih t ht h0t
    exact ⟨e, pe, fun y hy => ⟨t, ht, qe hy⟩⟩

theorem lemB (U : Set ℝ)
    (hU : IsOpen[generateFrom ({S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ioo a b} ∪
      {S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ioo a b \ {x : ℝ | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)}})] U)
    (h0 : (0:ℝ) ∈ U) :
    ∃ ε > 0, Ioo (-ε) ε \ {x : ℝ | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)} ⊆ U := by
  change TopologicalSpace.GenerateOpen _ U at hU
  induction hU with
  | basic s hs =>
    rcases hs with ⟨a, b, -, rfl⟩ | ⟨a, b, -, rfl⟩
    · refine ⟨min (-a) b, lt_min (by linarith [h0.1]) h0.2, fun y hy => ⟨?_, ?_⟩⟩
      · have := hy.1.1; have := min_le_left (-a) b; linarith
      · have := hy.1.2; have := min_le_right (-a) b; linarith
    · refine ⟨min (-a) b, lt_min (by linarith [h0.1.1]) h0.1.2, fun y hy => ⟨⟨?_, ?_⟩, hy.2⟩⟩
      · have := hy.1.1; have := min_le_left (-a) b; linarith
      · have := hy.1.2; have := min_le_right (-a) b; linarith
  | univ => exact ⟨1, one_pos, fun _ _ => trivial⟩
  | inter s t _ _ h1 h2 =>
    obtain ⟨e1, p1, q1⟩ := h1 h0.1
    obtain ⟨e2, p2, q2⟩ := h2 h0.2
    refine ⟨min e1 e2, lt_min p1 p2, fun y hy => ⟨q1 ⟨⟨?_, ?_⟩, hy.2⟩, q2 ⟨⟨?_, ?_⟩, hy.2⟩⟩⟩
    · have := hy.1.1; have := min_le_left e1 e2; linarith
    · have := hy.1.2; have := min_le_left e1 e2; linarith
    · have := hy.1.1; have := min_le_right e1 e2; linarith
    · have := hy.1.2; have := min_le_right e1 e2; linarith
  | sUnion S _ ih =>
    obtain ⟨t, ht, h0t⟩ := h0
    obtain ⟨e, pe, qe⟩ := ih t ht h0t
    exact ⟨e, pe, fun y hy => ⟨t, ht, qe hy⟩⟩

theorem generated_true : generated_statement := by
  intro K' hK Tl TK hTl hTK
  subst hK hTl hTK
  constructor
  · -- TK-open set not Tl-open: (-1,1) \ K'
    intro hle
    have hopen : IsOpen[generateFrom ({S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ioo a b} ∪
      {S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ioo a b \ {x : ℝ | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)}})]
        (Ioo (-1:ℝ) 1 \ {x : ℝ | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)}) :=
      TopologicalSpace.isOpen_generateFrom_of_mem (Or.inr ⟨-1, 1, by norm_num, rfl⟩)
    have h2 := hle _ hopen
    have h0 : (0:ℝ) ∈ Ioo (-1:ℝ) 1 \ {x : ℝ | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)} := by
      refine ⟨⟨by norm_num, by norm_num⟩, ?_⟩
      rintro ⟨n, hn, h⟩
      have : (0:ℝ) < 1 / (n:ℝ) := by positivity
      linarith
    obtain ⟨ε, hε, hsub⟩ := lemA _ h2 h0
    obtain ⟨n, hn⟩ := exists_nat_gt (1 / ε)
    have hnpos : 0 < n := by
      have : (0:ℝ) < n := lt_trans (by positivity) hn
      exact_mod_cast this
    have hnr : (0:ℝ) < n := by exact_mod_cast hnpos
    have hlt : 1 / (n:ℝ) < ε := by
      have hn2 : 1 < (n : ℝ) * ε := (div_lt_iff hε).mp hn
      exact (div_lt_iff hnr).2 (by nlinarith)
    have := hsub ⟨by positivity, hlt⟩
    exact this.2 ⟨n, hnpos, rfl⟩
  · -- Tl-open set not TK-open: [0,1)
    intro hle
    have hopen : IsOpen[generateFrom {S : Set ℝ | ∃ a b : ℝ, a < b ∧ S = Ico a b}] (Ico (0:ℝ) 1) :=
      TopologicalSpace.isOpen_generateFrom_of_mem ⟨0, 1, by norm_num, rfl⟩
    have h2 := hle _ hopen
    obtain ⟨ε, hε, hsub⟩ := lemB _ h2 ⟨le_rfl, by norm_num⟩
    have hmem : (-(min ε 1) / 2) ∈ Ioo (-ε) ε \
        {x : ℝ | ∃ n : ℕ, 0 < n ∧ x = 1 / (n : ℝ)} := by
      have h1 := min_le_left ε 1
      have h3 : 0 < min ε 1 := lt_min hε one_pos
      refine ⟨⟨by linarith, by linarith⟩, ?_⟩
      rintro ⟨n, hn, h⟩
      have : (0:ℝ) < 1 / (n:ℝ) := by
        have : (0:ℝ) < n := by exact_mod_cast hn
        positivity
      linarith
    have := hsub hmem
    have h3 : 0 < min ε 1 := lt_min hε one_pos
    linarith [this.1]

theorem generated_not_iff_reference : ¬ (generated_statement ↔ reference_statement) :=
  fun h => reference_false (h.mp generated_true)

#print axioms generated_not_iff_reference
