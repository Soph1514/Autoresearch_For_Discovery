"""Opt-in full-resolution Sidon refinement; preserves the original benchmark."""
from fractions import Fraction
from collections.abc import Sequence

from the_pigeon_holes.models.problem_contract import FitnessFunctionRef
from .base import CaseFitness
from .registry import source_sha256


def validate(values):
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not 2 <= len(values) <= 30000:
        raise ValueError('expected 2..30000 integer cells')
    if any(type(x) is not int or not 0 <= x <= 2**60 for x in values):
        raise ValueError('cells must be nonnegative integers at most 2**60')
    if Fraction(sum(values), 2 * len(values) * 2**40)**2 < Fraction(1, 10**8):
        raise ValueError('integral is too small')


def convolution(q):
    """Carry-free integer packing, with each coefficient <= n * max(q)^2."""
    width = (len(q) * max(q)**2).bit_length() // 8 + 1
    packed = int.from_bytes(b''.join(x.to_bytes(width, 'little') for x in q), 'little')
    raw = (packed * packed).to_bytes((2 * len(q) - 1) * width, 'little')
    return [int.from_bytes(raw[i:i+width], 'little') for i in range(0, len(raw), width)]


def exact_score(q):
    validate(q)
    return Fraction(2 * len(q) * max(convolution(q)), sum(q)**2)


class SidonRefinementFitness:
    reference = FitnessFunctionRef(id='sidon-refinement', version='exact-packed-v1',
                                   implementation_sha256=source_sha256(__file__))

    def validate_contract(self, problem):
        if problem.fitness_function != self.reference:
            raise ValueError('refinement fitness digest mismatch')
        if problem.solve_signature != 'def solve(initial: list[int]) -> list[int]:' or problem.interface.supporting_types_code.strip():
            raise ValueError('expected solve(initial: list[int]) -> list[int]')
        goal = problem.optimisation_goal
        if (goal.primary.name, goal.primary.direction, goal.aggregation) != ('c1', 'minimize', 'mean') or goal.tie_breakers:
            raise ValueError('expected mean c1 minimization')
        for case in problem.evaluation_suite.cases:
            validate(case.inputs['initial'])

    def evaluate_case(self, case, output):
        try:
            if not isinstance(output, list):
                raise ValueError('output must be a list')
            validate(output)
            if len(output) != len(case.inputs['initial']):
                raise ValueError('output length must preserve the input resolution')
            conv = convolution(output)
            value = Fraction(2 * len(output) * max(conv), sum(output)**2)
            peaks = sum(conv[i] > conv[i-1] and conv[i] > conv[i+1] for i in range(1, len(conv)-1))
            support = min(3, sum(x > 0 for x in output) * 4 // len(output))
            return CaseFitness(valid=True, metrics={'c1':value}, behavioral_descriptor=(support, min(8,peaks)),
                evidence={'output':output,'c1_exact':{'numerator':str(value.numerator),'denominator':str(value.denominator)}})
        except ValueError as error:
            return CaseFitness(valid=False, failure_reason=str(error))

