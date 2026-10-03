import Mathlib

open Fintype Subgroup Set Polynomial Ideal
open scoped BigOperators



theorem exercise_7_3_37 {p m : ℕ} (hp : p.Prime) :
  IsNilpotent (span ({↑p} : Set $ ZMod $ p^m) : Ideal $ ZMod $ p^m) :=
