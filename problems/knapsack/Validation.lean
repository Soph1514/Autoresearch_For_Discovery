import Generated
import Reference

theorem generated_iff_reference (chosen : Finset (Fin 5)) :
    Generated.optimal chosen ↔ Knapsack.Reference.optimal chosen := by
  simp only [Generated.optimal, Generated.feasible, Generated.objective,
    Knapsack.Reference.optimal, Knapsack.Reference.feasible,
    Knapsack.Reference.value, Knapsack.capacity, Finset.sum_filter]

#print axioms generated_iff_reference
