"""Built-in problem contracts."""

from .autocorrelation import autocorrelation_contract
from .bin_packing import bin_packing_contract
from .knapsack import knapsack_contract
from .tsp import tsp_contract
from .max_cut import max_cut_contract
from .makespan import makespan_contract
from .specs import load_problem_text

__all__ = [
    "autocorrelation_contract",
    "bin_packing_contract",
    "knapsack_contract",
    "tsp_contract",
    "max_cut_contract",
    "makespan_contract",
    "load_problem_text",
]
