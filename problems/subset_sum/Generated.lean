-- Generated.lean
-- Formalization of the 0/1 knapsack problem:
-- Given a list of weights and a capacity, we define binary selection lists,
-- feasibility, the selected total, and optimality (maximizing the selected total).

-- No tactics, no sorry, no IO, no axioms beyond Lean core.

/-- A binary selection list is valid for a given weight list if:
    - it has the same length as the weight list, and
    - every entry is 0 or 1. -/
def IsBinarySelection (weights : List Nat) (chosen : List Nat) : Prop :=
  chosen.length = weights.length ∧
  ∀ x ∈ chosen, x = 0 ∨ x = 1

/-- Pointwise product of two lists of natural numbers.
    Entries beyond the shorter list are dropped (zip semantics). -/
def pointwiseProduct (xs ys : List Nat) : List Nat :=
  (xs.zip ys).map (fun p => p.1 * p.2)

/-- The selected total: sum of pointwise products of weights and chosen. -/
def selectedTotal (weights : List Nat) (chosen : List Nat) : Nat :=
  (pointwiseProduct weights chosen).sum

/-- A selection is feasible when the selected total does not exceed the capacity. -/
def IsFeasible (weights : List Nat) (capacity : Nat) (chosen : List Nat) : Prop :=
  IsBinarySelection weights chosen ∧
  selectedTotal weights chosen ≤ capacity

/-- A feasible selection `chosen` is optimal if no other feasible selection
    achieves a strictly greater selected total. -/
def IsOptimal (weights : List Nat) (capacity : Nat) (chosen : List Nat) : Prop :=
  IsFeasible weights capacity chosen ∧
  ∀ other : List Nat,
    IsFeasible weights capacity other →
    selectedTotal weights other ≤ selectedTotal weights chosen
