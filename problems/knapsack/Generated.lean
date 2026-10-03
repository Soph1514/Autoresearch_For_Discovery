import Problem

namespace Generated

def feasible (chosen : Finset (Fin 5)) : Prop :=
  (chosen.sum fun i => (Knapsack.items i).weight) ≤ 10

def objective (chosen : Finset (Fin 5)) : Nat :=
  chosen.sum fun i => (Knapsack.items i).value

def optimal (chosen : Finset (Fin 5)) : Prop :=
  feasible chosen ∧
    ∀ candidate, feasible candidate → objective candidate ≤ objective chosen

end Generated
