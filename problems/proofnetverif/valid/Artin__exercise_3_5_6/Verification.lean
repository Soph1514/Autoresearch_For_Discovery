import Mathlib

open Function Fintype Subgroup Ideal Polynomial Submodule Zsqrtd
open scoped BigOperators

universe u v w

def generated_statement : Prop :=
  ∀ {K : Type u} {V : Type v} [Field K] [AddCommGroup V] [Module K V]
    (S : Set V) (hS : S.Countable) (hS_inf : S.Infinite)
    (hspan : Submodule.span K S = ⊤)
    (T : Set V) (hT : LinearIndependent K (fun x : T => (x : V))),
    T.Finite ∨ (T.Countable ∧ T.Infinite)

def reference_statement : Prop :=
  ∀ {K : Type u} {V : Type v} [Field K] [AddCommGroup V] [Module K V]
    {S : Set V} (hS : Set.Countable S)
    (hS1 : span K S = ⊤) {ι : Type w} (R : ι → V)
    (hR : LinearIndependent K R), Countable ι

theorem ref_true : reference_statement.{u, v, w} := by
  intro K V _ _ _ S hS hS1 ι R hR
  have h1 : Cardinal.lift.{v} (Cardinal.mk ι) ≤ Cardinal.lift.{w} (Module.rank K V) :=
    hR.cardinal_lift_le_rank
  have h2 : Module.rank K V ≤ Cardinal.mk S := by
    rw [← rank_top, ← hS1]
    exact rank_span_le S
  have h3 : Cardinal.mk S ≤ Cardinal.aleph0 := hS.le_aleph0
  have h4 : Cardinal.lift.{v} (Cardinal.mk ι) ≤ Cardinal.aleph0 := by
    refine h1.trans ?_
    calc Cardinal.lift.{w} (Module.rank K V) ≤ Cardinal.lift.{w} Cardinal.aleph0 :=
          Cardinal.lift_le.2 (h2.trans h3)
      _ = Cardinal.aleph0 := Cardinal.lift_aleph0
  rw [← Cardinal.mk_le_aleph0_iff]
  have := Cardinal.lift_le_aleph0.1 h4
  exact this

theorem generated_iff_reference : generated_statement.{u, v} ↔ reference_statement.{u, v, v} := by
  constructor
  · intro _
    exact ref_true
  · intro h K V _ _ _ S hS hS_inf hspan T hT
    have := h hS hspan (fun x : T => (x : V)) hT
    by_cases hf : T.Finite
    · exact Or.inl hf
    · exact Or.inr ⟨Set.countable_coe_iff.1 this, hf⟩

#print axioms generated_iff_reference
