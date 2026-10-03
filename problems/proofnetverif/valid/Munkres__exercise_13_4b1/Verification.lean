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
    ∃! t : TopologicalSpace X,
      (∀ i, {s : Set X | IsOpen[T i] s} ⊆ {s : Set X | IsOpen[t] s}) ∧
      ∀ t' : TopologicalSpace X,
        (∀ i, {s : Set X | IsOpen[T i] s} ⊆ {s : Set X | IsOpen[t'] s}) →
        {s : Set X | IsOpen[t] s} ⊆ {s : Set X | IsOpen[t'] s}

def reference_statement : Prop :=
  ∀ (X : Type u) (I : Type v) (T : I → Set (Set X)) (h : ∀ i, is_topology X (T i)),
  ∃! T', is_topology X T' ∧ (∀ i, T i ⊆ T') ∧
  ∀ T'', is_topology X T'' → (∀ i, T i ⊆ T'') → T' ⊆ T''

theorem generated_true : generated_statement.{u,v} := by
  intro X ι T
  have key : ∀ (a b : TopologicalSpace X),
      a ≤ b ↔ {s : Set X | IsOpen[b] s} ⊆ {s : Set X | IsOpen[a] s} := fun a b => Iff.rfl
  refine ⟨⨅ i, T i, ⟨?_, ?_⟩, ?_⟩
  · intro i
    exact (key _ _).1 (iInf_le T i)
  · intro t' ht'
    exact (key _ _).1 (le_iInf (fun i => (key _ _).2 (ht' i)))
  · rintro t ⟨h1, h2⟩
    have b : (⨅ i, T i) ≤ t := (key _ _).2 (h2 _ (fun i => (key _ _).1 (iInf_le T i)))
    have a : t ≤ (⨅ i, T i) := le_iInf (fun i => (key _ _).2 (h1 i))
    exact le_antisymm a b

theorem reference_true : reference_statement.{u,v} := by
  intro X I T h
  let T' : Set (Set X) := {s | ∀ T'', is_topology X T'' → (∀ i, T i ⊆ T'') → s ∈ T''}
  have hT' : is_topology X T' := by
    refine ⟨?_, ?_, ?_⟩
    · intro T'' hT'' _; exact hT''.1
    · intro s t hs ht T'' hT'' hi
      exact hT''.2.1 s t (hs T'' hT'' hi) (ht T'' hT'' hi)
    · intro S hS T'' hT'' hi
      exact hT''.2.2 S (fun t ht => hS t ht T'' hT'' hi)
  have hmin : ∀ T'', is_topology X T'' → (∀ i, T i ⊆ T'') → T' ⊆ T'' :=
    fun T'' h1 h2 s hs => hs T'' h1 h2
  have hsub : ∀ i, T i ⊆ T' := fun i s hs T'' _ hi => hi i hs
  refine ⟨T', ⟨hT', hsub, hmin⟩, ?_⟩
  rintro T2 ⟨h1, h2, h3⟩
  exact Set.Subset.antisymm (h3 T' hT' hsub) (hmin T2 h1 h2)

theorem generated_iff_reference : generated_statement.{u,v} ↔ reference_statement.{u,v} :=
  ⟨fun _ => reference_true, fun _ => generated_true⟩

#print axioms generated_iff_reference
