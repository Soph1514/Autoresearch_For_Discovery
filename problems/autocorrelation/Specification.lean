import Mathlib

open MeasureTheory
open scoped BigOperators ENNReal

namespace SidonAutoconvolution

/- The continuous open problem, using nonnegative extended integrals so that
   singular functions are included. A supremum replaces a possibly unattained
   maximum. No value of the optimal constant is asserted. -/
noncomputable def mass (f : ℝ → ℝ≥0∞) : ℝ≥0∞ :=
  ∫⁻ x in Set.Icc (-(1 : ℝ) / 4) (1 / 4), f x

noncomputable def convolution (f : ℝ → ℝ≥0∞) (t : ℝ) : ℝ≥0∞ :=
  ∫⁻ x, f (t - x) * f x

noncomputable def peak (f : ℝ → ℝ≥0∞) : ℝ≥0∞ :=
  ⨆ t : Set.Icc (-(1 : ℝ) / 2) (1 / 2), convolution f t

noncomputable def UniversalBound (c : ℝ≥0∞) : Prop :=
  ∀ f : ℝ → ℝ≥0∞, Measurable f → 0 < mass f → mass f < ⊤ →
    c * mass f ^ 2 ≤ peak f

noncomputable def optimalConstant : ℝ≥0∞ :=
  sSup {c | UniversalBound c}

/- Finite witness-search contract. Heights are q_i / 2^40 and cell width
   is 1/(2n). The analytic step-function reduction is not proved in this file.
   The Python evaluator independently computes the rational expression below. -/
def scale : ℕ := 2 ^ 40

def coefficient (q : List ℕ) (k : ℕ) : ℕ :=
  ∑ i ∈ Finset.range q.length,
    if i ≤ k then q.getD i 0 * q.getD (k - i) 0 else 0

def maxCoefficient (q : List ℕ) : ℕ :=
  (Finset.range (2 * q.length - 1)).sup (coefficient q)

def integral (n : ℕ) (q : List ℕ) : ℚ :=
  (q.sum : ℚ) / ((2 * n : ℕ) * scale)

def feasible (n : ℕ) (q : List ℕ) : Prop :=
  2 ≤ n ∧ n ≤ 4096 ∧ q.length = n ∧ 0 < q.sum ∧
    (1 : ℚ) / 100000000 ≤ integral n q ^ 2

def c1 (n : ℕ) (q : List ℕ) : ℚ :=
  (2 * n : ℕ) * (maxCoefficient q : ℚ) / (q.sum : ℚ) ^ 2

/- Python interface: def solve(n: int) -> list[int]:
   A solver returns feasible q; search minimizes c1, with mean aggregation over
   the fixed evaluation suite and no tie-breakers. Optimality is not required.
   Nat outputs correspond to nonnegative Python integers. -/
def solveSpec (solve : ℕ → List ℕ) : Prop :=
  ∀ n, 2 ≤ n → n ≤ 4096 → feasible n (solve n)

def meanObjective (solve : ℕ → List ℕ) (suite : List ℕ) : ℚ :=
  (suite.map (fun n => c1 n (solve n))).sum / (suite.length : ℚ)

end SidonAutoconvolution
