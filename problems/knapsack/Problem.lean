import Mathlib.Algebra.BigOperators.Group.Finset.Basic

namespace Knapsack

structure Item where
  weight : Nat
  value : Nat

def items : Fin 5 → Item
  | 0 => ⟨2, 3⟩
  | 1 => ⟨3, 4⟩
  | 2 => ⟨4, 8⟩
  | 3 => ⟨5, 8⟩
  | 4 => ⟨9, 10⟩

def capacity : Nat := 10

end Knapsack
