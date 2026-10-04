import Mathlib

open Filter Set TopologicalSpace
open scoped Topology

universe u v

def is_topology (X : Type*) (T : Set (Set X)) :=
  univ ∈ T ∧
  (∀ s t, s ∈ T → t ∈ T → s ∩ t ∈ T) ∧
  (∀s, (∀t ∈ s, t ∈ T) → sUnion s ∈ T)

def generated_statement : Prop :=
  ∀ {X : Type u} {ι : Type v} (T : ι → TopologicalSpace X),
    ∃! T' : TopologicalSpace X,
      (∀ i, {s : Set X | IsOpen[T i] s} ⊆ {s : Set X | IsOpen[T'] s}) ∧
      ∀ T'' : TopologicalSpace X,
        (∀ i, {s : Set X | IsOpen[T i] s} ⊆ {s : Set X | IsOpen[T''] s}) →
        {s : Set X | IsOpen[T'] s} ⊆ {s : Set X | IsOpen[T''] s}

def reference_statement : Prop :=
  ∀ (X : Type u) (I : Type v) (T : I → Set (Set X)) (h : ∀ i, is_topology X (T i)),
  ∃! T', is_topology X T' ∧ (∀ i, T i ⊆ T') ∧
  ∀ T'', is_topology X T'' → (∀ i, T i ⊆ T'') → T' ⊆ T''

theorem is_top_of {X : Type u} (t : TopologicalSpace X) :
    is_topology X {s : Set X | IsOpen[t] s} :=
  ⟨@isOpen_univ _ t, fun s u hs hu => by letI := t; exact IsOpen.inter hs hu,
    fun s hs => @isOpen_sUnion _ t s hs⟩

def mkTop {X : Type u} (S : Set (Set X)) (h : is_topology X S) : TopologicalSpace X where
  IsOpen s := s ∈ S
  isOpen_univ := h.1
  isOpen_inter := h.2.1
  isOpen_sUnion := h.2.2

theorem generated_iff_reference : generated_statement.{u, v} ↔ reference_statement.{u, v} := by
  constructor
  · intro G X I T h
    obtain ⟨t', ⟨h1, h2⟩, uniq⟩ := G (fun i => mkTop (T i) (h i))
    refine ⟨{s : Set X | IsOpen[t'] s}, ⟨is_top_of t', ?_, ?_⟩, ?_⟩
    · intro i s hs
      exact h1 i hs
    · intro T'' hT'' hT
      exact h2 (mkTop T'' hT'') (fun i => hT i)
    · intro y ⟨hy, hy1, hy2⟩
      have := uniq (mkTop y hy) ⟨fun i => hy1 i, fun T'' hT'' =>
        hy2 {s : Set X | IsOpen[T''] s} (is_top_of T'') hT''⟩
      rw [← this]
      rfl
  · intro R X ι T
    obtain ⟨S, ⟨hS, h1, h2⟩, uniq⟩ := R X ι (fun i => {s : Set X | IsOpen[T i] s})
      (fun i => is_top_of (T i))
    refine ⟨mkTop S hS, ⟨fun i => h1 i, ?_⟩, ?_⟩
    · intro T'' hT''
      exact h2 _ (is_top_of T'') hT''
    · intro y ⟨hy1, hy2⟩
      have := uniq {s : Set X | IsOpen[y] s}
        ⟨is_top_of y, hy1, fun T'' hT'' hT => hy2 (mkTop T'' hT'') hT⟩
      apply TopologicalSpace.ext
      funext s
      apply propext
      show IsOpen[y] s ↔ s ∈ S
      rw [← this]
      rfl

#print axioms generated_iff_reference
