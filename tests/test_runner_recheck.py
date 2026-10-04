"""Container-backed tests for the generic post-run recheck.

These run real candidate code in Docker and are skipped when the daemon or the
worker image is unavailable. The recheck is what lets a summary claim a score was
reproduced outside the evolution loop, so it is tested against a real container
rather than a stub.
"""

import asyncio

import pytest

from the_pigeon_holes.execution.container_runner import preflight
from the_pigeon_holes.fitness.bin_packing import BinPackingFitnessFunction, bins_used
from the_pigeon_holes.pipeline.runner import (
    PROBLEMS,
    compare_to_best_known,
    container_limits,
    recheck_best,
)
from the_pigeon_holes.problems.bin_packing import (
    BEST_KNOWN,
    CAPACITY,
    SEED_SOURCE,
    bin_packing_contract,
    optimal_assignment,
    triplet_groups,
    triplet_sizes,
)

CRASHES = "def solve(capacity: int, sizes: list[int]) -> list[int]:\n    raise ValueError('no')\n"
# Returns one bin per item: always feasible, never optimal.
ONE_BIN_EACH = (
    "def solve(capacity: int, sizes: list[int]) -> list[int]:\n"
    "    return list(range(len(sizes)))\n"
)


@pytest.fixture(scope="module")
def docker_ready():
    try:
        preflight()
    except RuntimeError as error:
        pytest.skip(str(error))


@pytest.fixture(scope="module")
def contract():
    return bin_packing_contract(case_time_seconds=10.0, candidate_time_seconds=40.0)


def run_recheck(contract, source):
    return asyncio.run(
        recheck_best(contract, BinPackingFitnessFunction(), source, container_limits(contract))
    )


def test_seed_baseline_is_reproduced_case_by_case(docker_ready, contract):
    """Every case must come back valid with the metric the host recomputes locally."""
    recheck = run_recheck(contract, SEED_SOURCE)
    assert set(recheck) == {case.id for case in contract.evaluation_suite.cases}
    for case in contract.evaluation_suite.cases:
        inputs = case.materialize_inputs()
        expected = bins_used(
            _local_seed(inputs["capacity"], inputs["sizes"]), inputs["capacity"], inputs["sizes"]
        )
        assert recheck[case.id]["ok"]
        assert recheck[case.id]["metrics"]["bins_used"] == str(expected)


def _local_seed(capacity, sizes):
    namespace: dict = {}
    exec(SEED_SOURCE, namespace)
    return namespace["solve"](capacity, sizes)


def test_baseline_misses_every_target(docker_ready, contract):
    """The comparison must show the baseline short of the proven optimum."""
    recheck = run_recheck(contract, SEED_SOURCE)
    comparison = compare_to_best_known(recheck, BEST_KNOWN, "bins_used")
    assert comparison["matched_targets"] == 0
    assert comparison["total_targets"] == len(BEST_KNOWN)
    for case_id, entry in comparison["cases"].items():
        assert entry["kind"] == "optimal"
        assert int(entry["achieved"]) > int(entry["target"])


def test_optimal_candidate_matches_every_target(docker_ready, contract):
    """An optimal packing must come back matching all proven optima.

    This is the end-to-end check that the targets are reachable through the real
    container path and not only in host-side arithmetic. The candidate replays the
    construction's packing rather than searching for it, because what is under test
    is the recheck and comparison, not whether bin packing is solvable.
    """
    recheck = run_recheck(contract, _optimal_source(contract))
    comparison = compare_to_best_known(recheck, BEST_KNOWN, "bins_used")
    assert comparison["matched_targets"] == comparison["total_targets"]
    assert all(entry["matched"] for entry in comparison["cases"].values())


def _optimal_source(contract):
    """Build a candidate that returns the exhibited optimal packing per instance."""
    packings = {}
    for case in contract.evaluation_suite.cases:
        sizes = case.materialize_inputs()["sizes"]
        triples = BEST_KNOWN[case.id]["value"]
        packings[tuple(sizes)] = optimal_assignment(triples, seed=_seed_for(case.id))
    return (
        f"PACKINGS = {packings!r}\n"
        "def solve(capacity: int, sizes: list[int]) -> list[int]:\n"
        "    return list(PACKINGS[tuple(sizes)])\n"
    )


def test_crashing_candidate_is_reported_not_scored(docker_ready, contract):
    recheck = run_recheck(contract, CRASHES)
    for entry in recheck.values():
        assert not entry["ok"]
        assert entry["failure_reason"]
        assert "metrics" not in entry


def test_feasible_but_poor_candidate_is_scored(docker_ready, contract):
    recheck = run_recheck(contract, ONE_BIN_EACH)
    for case in contract.evaluation_suite.cases:
        items = len(case.materialize_inputs()["sizes"])
        assert recheck[case.id]["ok"]
        assert recheck[case.id]["metrics"]["bins_used"] == str(items)


# --- Comparison logic, no Docker needed ------------------------------------------


def test_comparison_is_absent_for_problems_without_targets():
    assert compare_to_best_known({}, None, "c1") is None
    assert PROBLEMS["autocorrelation"].best_known is None


def test_comparison_handles_exact_rational_metrics():
    recheck = {"only": {"ok": True, "metrics": {"c1": "3/2"}}}
    targets = {"only": {"value": "3/2", "kind": "best_known", "justification": "x"}}
    comparison = compare_to_best_known(recheck, targets, "c1")
    assert comparison["matched_targets"] == 1


def test_comparison_counts_a_missing_case_as_unmatched():
    targets = {"absent": {"value": 5, "kind": "optimal", "justification": "x"}}
    comparison = compare_to_best_known({}, targets, "bins_used")
    assert comparison["matched_targets"] == 0
    assert comparison["cases"]["absent"]["achieved"] is None


def test_builtin_problems_are_registered():
    assert set(PROBLEMS) == {"autocorrelation", "bin-packing"}
    assert PROBLEMS["bin-packing"].best_known == BEST_KNOWN


def test_container_limits_follow_the_contract():
    problem = bin_packing_contract(case_time_seconds=7.0, memory_mb=321)
    limits = container_limits(problem)
    assert limits.timeout_seconds == 7.0
    assert limits.memory_mb == 321


def test_triplet_targets_cover_every_case():
    problem = bin_packing_contract()
    assert {case.id for case in problem.evaluation_suite.cases} == set(BEST_KNOWN)
    for case in problem.evaluation_suite.cases:
        inputs = case.materialize_inputs()
        assert inputs["capacity"] == CAPACITY
        assert len(inputs["sizes"]) == 3 * BEST_KNOWN[case.id]["value"]
        assert len(triplet_groups(BEST_KNOWN[case.id]["value"])) == BEST_KNOWN[case.id]["value"]
        assert sorted(inputs["sizes"]) == sorted(
            triplet_sizes(BEST_KNOWN[case.id]["value"], seed=_seed_for(case.id))
        )


def _seed_for(case_id):
    from the_pigeon_holes.problems.bin_packing import INSTANCES

    return next(seed for name, _, seed in INSTANCES if name == case_id)
