import Mathlib.Algebra.BigOperators.Group.Finset.Basic

namespace Generated

def feasible {n : Nat} (weight : Fin n → Nat) (capacity : Nat)
    (chosen : Finset (Fin n)) : Prop :=
  (chosen.sum weight) ≤ capacity

def objective {n : Nat} (value : Fin n → Nat) (chosen : Finset (Fin n)) : Nat :=
  chosen.sum value

def optimal {n : Nat} (weight value : Fin n → Nat) (capacity : Nat)
    (chosen : Finset (Fin n)) : Prop :=
  feasible weight capacity chosen ∧
    ∀ candidate, feasible weight capacity candidate →
      objective value candidate ≤ objective value chosen

end Generated
