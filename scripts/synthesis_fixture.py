"""A problem the Lean fitness compiler cannot express, for trying the review loop.

The compiler accepts `Nat`, `Int`, `List Nat` and `List Int`. This statement's
instance carries `List (Nat x Nat)` pairs, so `#check_fitness_source` reports
`unsupported_formalization` and synthesis is the only route to a scorer. That is
the case the human-in-the-loop path exists for.

Used by `scripts/try_synthesis.py`, which drives the review loop in the terminal
and so skips the compiler entirely. For a UI run-through, do not use a fixture:
set RESEARCH_LOCAL_LEAN=1 and paste this Lean in formal mode, which produces a
real local check with real provenance.
"""

from __future__ import annotations

PROBLEM = """\
Given items : List (Nat x Nat) where each pair is (value, weight), and
capacity : Nat, construct a binary selection list chosen : List Nat of the same
length as items. Each chosen entry is 0 or 1. The selected weight is the sum of
the weights of the selected items and the selected value is the sum of their
values. The selection is feasible when the selected weight is at most capacity.
Maximize the selected value over all feasible binary selection lists. Empty
lists are allowed.

The instance parameters are named items and capacity. The candidate is chosen.
"""

LEAN = """\
-- Value-weight selection. Instance parameters first, candidate last.

def IsBinarySelection (items : List (Nat × Nat)) (chosen : List Nat) : Prop :=
  chosen.length = items.length ∧ ∀ x ∈ chosen, x = 0 ∨ x = 1

def selectedWeight (items : List (Nat × Nat)) (chosen : List Nat) : Nat :=
  ((items.zip chosen).map (fun p => p.1.2 * p.2)).sum

def selectedValue (items : List (Nat × Nat)) (chosen : List Nat) : Nat :=
  ((items.zip chosen).map (fun p => p.1.1 * p.2)).sum

def IsFeasible (items : List (Nat × Nat)) (capacity : Nat) (chosen : List Nat) : Prop :=
  IsBinarySelection items chosen ∧ selectedWeight items chosen ≤ capacity

def IsOptimal (items : List (Nat × Nat)) (capacity : Nat) (chosen : List Nat) : Prop :=
  IsFeasible items capacity chosen ∧
  ∀ other : List Nat,
    IsFeasible items capacity other →
    selectedValue items other ≤ selectedValue items chosen
"""

CASES = {
    "pairs-small": {"items": [[6, 3], [7, 4], [9, 5]], "capacity": 7},
    "pairs-tight": {"items": [[1, 1], [10, 9], [11, 10]], "capacity": 10},
}

SEED = ("def solve(items: list[list[int]], capacity: int) -> list[int]:\n"
        "    return [0] * len(items)\n")

IDENTITY = "trial-unsupported-pairs"


def session_artifact() -> dict:
    """Enough for a synthesis session: it checks lean_checked and status only."""
    return {"input": {"problem": PROBLEM, "mode": "formal", "lean": LEAN},
            "result": {"lean": LEAN, "lean_checked": True, "status": "checked",
                       "diagnostics": "", "attempts": 1, "fidelity": None,
                       "fidelity_error": None, "generator": "local-trial-fixture",
                       "generation_fine_tuned": False}}


FIXTURE = {"id": IDENTITY, "artifact": session_artifact(), "cases": CASES, "seed": SEED}
