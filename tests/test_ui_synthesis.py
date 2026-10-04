"""The synthesis HTTP surface: the 409 offer, the review loop, and failing closed."""

import hashlib

import pytest
from fastapi.testclient import TestClient

from the_pigeon_holes.execution.signature_extractor import (
    ExtractedInterface,
    MetricGoal,
    OptimisationGoal,
    Parameter,
)
from the_pigeon_holes.fitness.compiler import LeanFitnessError
from the_pigeon_holes.fitness.synthesis.critic import ScorerChoice
from the_pigeon_holes.fitness.synthesis.generator import ScorerCandidate
from the_pigeon_holes.ui import api
from the_pigeon_holes.ui import synthesis as session_module
from the_pigeon_holes.ui.storage import ArtifactStore

GOAL = OptimisationGoal(MetricGoal("total_value", "maximize"), "sum")
INTERFACE = ExtractedInterface(
    function_name="solve",
    parameters=[Parameter("capacity", "int")],
    return_type="list[int]",
    signature_str="def solve(capacity: int) -> list[int]:",
    pydantic_classes_code="",
    optimisation_goal=GOAL,
)
SCORER = ("def validate(output, capacity):\n    return None\n\n"
          "def score(output, capacity):\n    return {'total_value': len(output)}\n\n"
          "def descriptor(output, capacity):\n    return (float(len(output)),)\n")
LEAN = "theorem spec : True := by trivial"


def _candidate(slot):
    return ScorerCandidate(
        slot=slot, model=f"model-{slot}", framing="f", source_code=SCORER,
        metric_names=("total_value",), descriptor_arity=1,
        descriptor_axes=({"name": "n", "lo": 0.0, "hi": 1.0},),
        validity_rules=("anything is feasible",), objective_derivation="count")


class _FakeGenerator:
    def __init__(self, config, *, client, budget=None):
        pass

    async def synthesise(self, *, problem, lean_source, interface, feedback=()):
        return _candidate("a"), _candidate("b")


class _FakeCritic:
    def __init__(self, *, model, client, budget=None):
        pass

    async def choose(self, a, b, *, problem, lean_source, interface, feedback=()):
        return ScorerChoice(chosen="a", justification="A is closer to the statement")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "store", ArtifactStore(tmp_path / "api.sqlite3"))
    monkeypatch.setattr(api, "runs", {})
    monkeypatch.setattr(api, "syntheses", {})
    monkeypatch.setenv("RESEARCH_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(session_module, "ScorerGenerator", _FakeGenerator)
    monkeypatch.setattr(session_module, "ScorerCritic", _FakeCritic)
    # The round task must not make real calls; inject the fakes' dependencies.
    original = session_module.run_round

    async def run_round(session_id, **kwargs):
        kwargs.setdefault("client_factory", lambda: object())
        kwargs.setdefault("extractor", lambda lean, model: INTERFACE)
        return await original(session_id, **kwargs)

    monkeypatch.setattr(api, "run_round", run_round)
    with TestClient(api.app) as test_client:
        yield test_client


def _check_artifact(lean=LEAN):
    """Complete provenance, as prepare_contract's gate requires."""
    return {"source_sha256": hashlib.sha256(lean.encode()).hexdigest(), "exit_code": 0,
            "toolchain": "leanprover/lean4:v4.19.0", "dependencies": {"mathlib": "pinned"},
            "command": "lake env lean", "lean_version": "4.19.0"}


def _formalization(client, status="checked"):
    api.store.put("formalization", "f-1", {
        "input": {"problem": "Pick items under capacity."},
        "result": {"lean": LEAN, "lean_checked": True, "status": status,
                   "check_artifact": _check_artifact(), "fidelity": None},
    })
    return "f-1"


def _start(client, **overrides):
    body = {"formalization_id": _formalization(client), "evaluation_suite_id": "suite-1",
            "evaluation_cases": {"c1": {"capacity": 10}}}
    body.update(overrides)
    return client.post("/api/syntheses", json=body)


def _await_round(client, session_id):
    """The round runs as a background task; poll until it has settled."""
    for _ in range(50):
        view = client.get(f"/api/syntheses/{session_id}").json()
        if view["state"] not in ("extracting", "generating", "criticising"):
            return view
    raise AssertionError(f"round never settled: {view['state']}")


# --- the offer ---------------------------------------------------------------

def test_an_unsupported_formalization_offers_synthesis_with_409(client, monkeypatch):
    """Not a user mistake: the compiler's language is small, so offer the fallback."""
    _formalization(client)

    async def unsupported(body, artifact, **kwargs):
        raise LeanFitnessError("unsupported_formalization", "List Rat is not supported")

    monkeypatch.setattr(api, "prepare_contract", unsupported)
    response = client.post("/api/contracts", json={
        "formalization_id": "f-1", "evaluation_suite_id": "s", "evaluation_cases": {"c1": {}}})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["synthesis_required"] is True
    assert detail["stage"] == "unsupported_formalization"


def test_other_compiler_failures_stay_422(client, monkeypatch):
    _formalization(client)

    async def broken(body, artifact, **kwargs):
        raise LeanFitnessError("lean_compile_failed", "it did not compile")

    monkeypatch.setattr(api, "prepare_contract", broken)
    response = client.post("/api/contracts", json={
        "formalization_id": "f-1", "evaluation_suite_id": "s", "evaluation_cases": {"c1": {}}})

    assert response.status_code == 422
    assert "synthesis_required" not in response.json()["detail"]


# --- the session over HTTP ---------------------------------------------------

def test_starting_a_synthesis_returns_a_session_and_runs_a_round(client):
    response = _start(client)

    assert response.status_code == 201
    view = response.json()
    assert view["max_rounds"] == 3
    assert view["evidence_tier"] == "lean_checked_synthesised"

    final = _await_round(client, view["id"])
    assert final["state"] == "awaiting_review"
    assert final["rounds"][0]["critic"]["chosen"] == "a"


def test_an_unreviewed_alignment_is_refused(client):
    api.store.put("formalization", "f-2", {
        "input": {"problem": "p"},
        "result": {"lean": LEAN, "lean_checked": True, "status": "review",
                   "check_artifact": _check_artifact()},
    })
    response = client.post("/api/syntheses", json={
        "formalization_id": "f-2", "evaluation_suite_id": "s",
        "evaluation_cases": {"c1": {"capacity": 1}}})

    assert response.status_code == 422
    assert "alignment" in response.json()["detail"]


def test_a_rejection_without_an_explanation_is_refused(client):
    view = _start(client).json()
    _await_round(client, view["id"])

    response = client.post(f"/api/syntheses/{view['id']}/review",
                           json={"decision": "reject", "feedback": "no", "round_index": 1})

    assert response.status_code == 422


def test_a_stale_round_index_is_a_conflict(client):
    view = _start(client).json()
    _await_round(client, view["id"])

    response = client.post(f"/api/syntheses/{view['id']}/review", json={
        "decision": "reject", "feedback": "this decision is for the wrong round",
        "round_index": 2})

    assert response.status_code == 409


def test_rejecting_three_times_exhausts_and_registers_nothing(client):
    view = _start(client).json()
    _await_round(client, view["id"])
    for index in (1, 2, 3):
        response = client.post(f"/api/syntheses/{view['id']}/review", json={
            "decision": "reject", "round_index": index,
            "feedback": f"round {index} still mis-states the feasibility rule"})
        assert response.status_code == 200
        if index < 3:
            _await_round(client, view["id"])

    final = client.get(f"/api/syntheses/{view['id']}").json()
    assert final["state"] == "exhausted"
    assert final["terminal"] is True
    assert final["accepted"] is None
    assert api.store.all("fitness") == []


def test_a_contract_from_an_exhausted_synthesis_is_refused(client):
    view = _start(client).json()
    _await_round(client, view["id"])
    for index in (1, 2, 3):
        client.post(f"/api/syntheses/{view['id']}/review", json={
            "decision": "reject", "round_index": index,
            "feedback": f"round {index} still mis-states the feasibility rule"})
        if index < 3:
            _await_round(client, view["id"])

    response = client.post("/api/contracts", json={
        "formalization_id": "f-1", "evaluation_suite_id": "suite-1",
        "evaluation_cases": {"c1": {"capacity": 10}}, "synthesis_id": view["id"]})

    assert response.status_code == 422
    assert "exhausted" in str(response.json()["detail"])


def test_a_scorer_is_served_as_a_plain_text_attachment(client):
    """Never rendered inline: this is untrusted model output."""
    view = _start(client).json()
    _await_round(client, view["id"])

    response = client.get(f"/api/syntheses/{view['id']}/scorer/a")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]
    assert response.text == SCORER


def test_an_unknown_session_is_404(client):
    assert client.get("/api/syntheses/missing").status_code == 404


def test_choosing_both_a_registered_function_and_a_synthesis_is_refused(client):
    view = _start(client).json()
    _await_round(client, view["id"])

    response = client.post("/api/contracts", json={
        "formalization_id": "f-1", "evaluation_suite_id": "suite-1",
        "evaluation_cases": {"c1": {"capacity": 10}}, "synthesis_id": view["id"],
        "fitness_function_id": "knapsack", "fitness_function_version": "exact-v1"})

    assert response.status_code == 422
    assert "not both" in str(response.json()["detail"])


def test_synthesis_without_cases_is_an_input_error(client):
    _formalization(client)
    response = client.post('/api/contracts', json={
        'formalization_id': 'f-1', 'evaluation_suite_id': 'suite-1',
        'synthesis_id': 'accepted-scorer', 'alignment_reviewed': True})
    assert response.status_code == 422
    assert 'Provide case inputs' in response.json()['detail']


def test_accepting_freezes_a_scorer_and_the_contract_carries_the_tier(client, tmp_path):
    """The whole fallback path, with a real container freeze probe."""
    from the_pigeon_holes.execution.container_runner import preflight

    try:
        preflight()
    except RuntimeError as error:
        pytest.skip(str(error))

    view = _start(client).json()
    _await_round(client, view["id"])

    accepted = client.post(f"/api/syntheses/{view['id']}/review",
                           json={"decision": "accept", "round_index": 1}).json()
    assert accepted["state"] == "accepted"
    assert accepted["accepted"]["fitness_id"].startswith("synth-")
    assert accepted["accepted"]["evidence_tier"] == "lean_checked_synthesised"

    response = client.post("/api/contracts", json={
        "formalization_id": "f-1", "evaluation_suite_id": "suite-1",
        "evaluation_cases": {"c1": {"capacity": 10}}, "synthesis_id": view["id"]})

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["evidence_tier"] == "lean_checked_synthesised"
    assert body["compiler"] is None
    assert body["synthesis"]["status"] == "human_accepted"
    assert body["synthesis"]["accepted_round"] == 1
    assert body["synthesis"]["correctness"] == "not_proven"
    assert body["fitness_function"]["id"].startswith("synth-")

    # The run path must be able to rebuild the evaluator from the stored artifact.
    from the_pigeon_holes.ui.preparation import make_evaluator
    from the_pigeon_holes.ui.storage import contract_from_dict

    stored = api.store.get("contract", body["id"])
    evaluator = make_evaluator(contract_from_dict(stored["contract"]), store=api.store)
    assert evaluator.fitness_function.reference.id == body["fitness_function"]["id"]
