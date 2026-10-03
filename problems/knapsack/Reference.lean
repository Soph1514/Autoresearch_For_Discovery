import Problem

namespace Knapsack.Reference

def feasible (chosen : Finset (Fin 5)) : Prop :=
  ∑ i ∈ chosen, (Knapsack.items i).weight ≤ Knapsack.capacity

def value (chosen : Finset (Fin 5)) : Nat :=
  ∑ i ∈ chosen, (Knapsack.items i).value

def optimal (chosen : Finset (Fin 5)) : Prop :=
  feasible chosen ∧
    ∀ other, feasible other → value other ≤ value chosen

end Knapsack.Reference
