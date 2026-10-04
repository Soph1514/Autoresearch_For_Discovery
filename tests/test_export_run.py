"""The exporter's independent recheck must verify real evaluator evidence.

`scripts/export_run.py` is a script, not a package module, so it is loaded by path.
It rebuilds the run's contract, resolves the fitness function the run recorded, and
rescores every saved output. That is the only reason an export can claim a witness
was independently verified, and nothing exercised it before, which is why it went
unnoticed when the evidence layout changed.
"""

import importlib.util
from pathlib import Path

import pytest

from the_pigeon_holes.problems.autocorrelation import autocorrelation_contract
from the_pigeon_holes.problems.bin_packing import (
    BEST_KNOWN,
    CAPACITY,
    INSTANCES,
    bin_packing_contract,
    optimal_assignment,
    triplet_sizes,
)
from the_pigeon_holes.ui.storage import encode

ROOT = Path(__file__).resolve().parents[1]
SCALE = 2**40
# q = [SCALE, SCALE] has max autoconvolution 2*SCALE**2 and sum 2*SCALE, so
# c1 = 2*n*max/sum**2 = 8*SCALE**2 / 4*SCALE**2 = 2 exactly.
EXACT_TWO = {"numerator": "2", "denominator": "1"}


def load_exporter():
    spec = importlib.util.spec_from_file_location("export_run", ROOT / "scripts" / "export_run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = load_exporter()


def artifact_for(contract, numerical):
    """Wrap evidence in the artifact shape the API serves."""
    return {"contract": encode(contract), "evidence": {"numerical": numerical}}


# --- Autocorrelation: exact rationals, mean aggregation --------------------------


def autocorrelation_artifact(nested=True):
    contract = autocorrelation_contract(n=2)
    case_id = contract.evaluation_suite.cases[0].id
    witness = {"output": [SCALE, SCALE], "c1_exact": dict(EXACT_TWO)}
    case = {"inputs": {"n": 2}, "ok": True}
    if nested:
        case["fitness_evidence"] = witness
        record = {"cases": {case_id: case}, "aggregate_metrics_exact": {"c1": dict(EXACT_TWO)}}
    else:
        case.update(witness)
        record = {"cases": {case_id: case}, "mean_c1_exact": dict(EXACT_TWO)}
    return artifact_for(contract, {"candidate": record})


def test_nested_evaluator_evidence_is_rechecked():
    assert exporter.recheck_witnesses(autocorrelation_artifact()) == 1


def test_pre_restructure_evidence_stays_verifiable():
    """Runs saved before the layout change must not silently recheck nothing."""
    assert exporter.recheck_witnesses(autocorrelation_artifact(nested=False)) == 1


def test_main_historical_scorer_hash_stays_exportable():
    artifact = autocorrelation_artifact()
    artifact['contract']['fitness_function']['implementation_sha256'] = (
        '5ff3185e8a5cebb0a0920e3cbab0b3d83cfd937e3bbd6a46cc5b871b19ee7a5f'
    )
    assert exporter.recheck_witnesses(artifact) == 1


def test_absent_evidence_rechecks_nothing():
    contract = autocorrelation_contract(n=2)
    assert exporter.recheck_witnesses(artifact_for(contract, {})) == 0


def test_candidate_without_a_witness_is_skipped():
    contract = autocorrelation_contract(n=2)
    case_id = contract.evaluation_suite.cases[0].id
    record = {"cases": {case_id: {"inputs": {"n": 2}, "ok": False, "failure_reason": "crash"}}}
    assert exporter.recheck_witnesses(artifact_for(contract, {"candidate": record})) == 0


@pytest.mark.parametrize("corrupt", [
    pytest.param(lambda case: case["fitness_evidence"].__setitem__(
        "c1_exact", {"numerator": "3", "denominator": "1"}), id="per-case-metric"),
    pytest.param(lambda case: case["fitness_evidence"].__setitem__(
        "output", [SCALE, SCALE, SCALE]), id="output-length"),
])
def test_tampered_case_evidence_fails_the_recheck(corrupt):
    artifact = autocorrelation_artifact()
    corrupt(artifact["evidence"]["numerical"]["candidate"]["cases"]["n-2"])
    with pytest.raises(AssertionError):
        exporter.recheck_witnesses(artifact)


def test_tampered_aggregate_fails_the_recheck():
    artifact = autocorrelation_artifact()
    artifact["evidence"]["numerical"]["candidate"]["aggregate_metrics_exact"]["c1"] = {
        "numerator": "5", "denominator": "1"}
    with pytest.raises(AssertionError):
        exporter.recheck_witnesses(artifact)


def test_an_output_recorded_as_valid_but_infeasible_is_caught():
    """A zeroed-out witness fails revalidation even with a consistent stored score."""
    artifact = autocorrelation_artifact()
    case = artifact["evidence"]["numerical"]["candidate"]["cases"]["n-2"]
    case["fitness_evidence"]["output"] = [0, 0]
    with pytest.raises(AssertionError, match="fails revalidation"):
        exporter.recheck_witnesses(artifact)


# --- Bin packing: integer metric, sum aggregation --------------------------------


def bin_packing_artifact():
    """Evidence for an optimal packing of all three triplet instances."""
    contract = bin_packing_contract()
    cases = {}
    for case_id, triples, seed in INSTANCES:
        assignment = optimal_assignment(triples, seed=seed)
        cases[case_id] = {
            "inputs": {"capacity": CAPACITY, "sizes": triplet_sizes(triples, seed=seed)},
            "ok": True,
            "fitness_evidence": {
                "output": assignment,
                "bins_used_exact": {"numerator": str(triples), "denominator": "1"},
                "lower_bound": triples,
            },
        }
    total = sum(target["value"] for target in BEST_KNOWN.values())
    record = {
        "cases": cases,
        "aggregate_metrics_exact": {"bins_used": {"numerator": str(total), "denominator": "1"}},
    }
    return artifact_for(contract, {"candidate": record})


def test_a_second_problem_rechecks_without_exporter_changes():
    """The exporter is driven by the contract, so a new problem needs no edits here."""
    assert exporter.recheck_witnesses(bin_packing_artifact()) == len(INSTANCES)


def test_sum_aggregation_is_verified_not_assumed():
    """The aggregate is recomputed with the contract's aggregation, not averaged."""
    artifact = bin_packing_artifact()
    mean_instead_of_sum = sum(t["value"] for t in BEST_KNOWN.values()) // len(BEST_KNOWN)
    artifact["evidence"]["numerical"]["candidate"]["aggregate_metrics_exact"]["bins_used"] = {
        "numerator": str(mean_instead_of_sum), "denominator": "1"}
    with pytest.raises(AssertionError):
        exporter.recheck_witnesses(artifact)


def test_a_suboptimal_packing_still_rechecks_consistently():
    """Rechecking verifies the recorded score, not that the score was good."""
    artifact = bin_packing_artifact()
    record = artifact["evidence"]["numerical"]["candidate"]
    case_id, triples, seed = INSTANCES[0]
    sizes = triplet_sizes(triples, seed=seed)
    record["cases"][case_id]["fitness_evidence"] = {
        "output": list(range(len(sizes))),  # one bin per item: feasible, not optimal
        "bins_used_exact": {"numerator": str(len(sizes)), "denominator": "1"},
        "lower_bound": triples,
    }
    others = sum(t["value"] for case, t in BEST_KNOWN.items() if case != case_id)
    record["aggregate_metrics_exact"]["bins_used"] = {
        "numerator": str(len(sizes) + others), "denominator": "1"}
    assert exporter.recheck_witnesses(artifact) == len(INSTANCES)
