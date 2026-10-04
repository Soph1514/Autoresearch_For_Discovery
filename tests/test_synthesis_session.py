"""The human-in-the-loop session: rounds, the cap, failing closed, and restarts.

Fakes stand in for the generator, critic and extractor. No Docker, no network.
"""

import asyncio

import pytest

from the_pigeon_holes.execution.signature_extractor import (
    ExtractedInterface,
    MetricGoal,
    OptimisationGoal,
    Parameter,
)
from the_pigeon_holes.fitness.synthesis.critic import ScorerChoice
from the_pigeon_holes.fitness.synthesis.generator import ScorerCandidate
from the_pigeon_holes.ui import synthesis as session_module
from the_pigeon_holes.ui.storage import ArtifactStore
from the_pigeon_holes.ui.synthesis import (
    MAX_ROUNDS,
    ReviewInput,
    SynthesisConflict,
    SynthesisInput,
    apply_review,
    create_session,
    restore_sessions,
    run_round,
    session_view,
)

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
          "def score(output, capacity):\n    return {'total_value': 0}\n\n"
          "def descriptor(output, capacity):\n    return (0.0,)\n")

ARTIFACT = {
    "input": {"problem": "Pick items under capacity."},
    "result": {"lean_checked": True, "status": "checked", "lean": "def solve"},
}


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(str(tmp_path / "research.sqlite3"))


@pytest.fixture(autouse=True)
def research_model(monkeypatch):
    monkeypatch.setenv("RESEARCH_MODEL", "claude-sonnet-4-6")


def _input(**overrides):
    body = dict(formalization_id="f-1", evaluation_suite_id="suite-1",
                evaluation_cases={"c1": {"capacity": 10}})
    body.update(overrides)
    return SynthesisInput(**body)


def _candidate(slot, **overrides):
    base = dict(slot=slot, model=f"model-{slot}", framing="f", source_code=SCORER,
                metric_names=("total_value",), descriptor_arity=1,
                descriptor_axes=({"name": "n", "lo": 0.0, "hi": 1.0},),
                validity_rules=("always valid",), objective_derivation="zero")
    base.update(overrides)
    return ScorerCandidate(**base)


class _FakeGenerator:
    def __init__(self, config, *, client, budget=None):
        self.config = config

    async def synthesise(self, *, problem, lean_source, interface, feedback=()):
        _FakeGenerator.seen_feedback = feedback
        return _candidate("a"), _candidate("b")


class _FakeCritic:
    def __init__(self, *, model, client, budget=None):
        pass

    async def choose(self, a, b, *, problem, lean_source, interface, feedback=()):
        return ScorerChoice(chosen="a", justification="A reads the Lean more literally")


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(session_module, "ScorerGenerator", _FakeGenerator)
    monkeypatch.setattr(session_module, "ScorerCritic", _FakeCritic)


def _round(store, session_id):
    return asyncio.run(run_round(
        session_id, store=store,
        client_factory=lambda: object(),
        extractor=lambda lean, model: INTERFACE))


def _start(store, **overrides):
    session = create_session(_input(**overrides), ARTIFACT, store=store)
    return _round(store, session["id"])


# --- opening a session -------------------------------------------------------

def test_a_session_needs_a_checked_lean_statement(store):
    unchecked = {**ARTIFACT, "result": {**ARTIFACT["result"], "lean_checked": False}}
    with pytest.raises(ValueError, match="Lean must pass checking"):
        create_session(_input(), unchecked, store=store)


def test_an_unreviewed_alignment_blocks_the_session(store):
    needs_review = {**ARTIFACT, "result": {**ARTIFACT["result"], "status": "review"}}
    with pytest.raises(ValueError, match="acknowledge its alignment"):
        create_session(_input(), needs_review, store=store)
    assert create_session(_input(alignment_reviewed=True), needs_review,
                          store=store)["state"] == "extracting"


def test_a_missing_formalization_is_refused(store):
    with pytest.raises(ValueError, match="Formalization not found"):
        create_session(_input(), None, store=store)


# --- one round ---------------------------------------------------------------

def test_a_round_ends_awaiting_review_with_both_candidates(store):
    session = _start(store)

    assert session["state"] == "awaiting_review"
    assert session["round_index"] == 1
    current = session["rounds"][0]
    assert set(current["candidates"]) == {"a", "b"}
    assert current["critic"]["chosen"] == "a"
    assert current["review"] is None
    assert session["interface"]["signature_str"] == INTERFACE.signature_str


def test_the_interface_is_extracted_once_and_reused(store):
    calls = []

    def extractor(lean, model):
        calls.append(lean)
        return INTERFACE

    created = create_session(_input(), ARTIFACT, store=store)
    asyncio.run(run_round(created["id"], store=store, client_factory=lambda: object(),
                          extractor=extractor))
    apply_review(created["id"], ReviewInput(decision="reject", round_index=1,
                                            feedback="validity ignores duplicate items"),
                 store=store)
    asyncio.run(run_round(created["id"], store=store, client_factory=lambda: object(),
                          extractor=extractor))

    assert len(calls) == 1


def test_rejection_feedback_reaches_the_next_round(store):
    session = _start(store)
    apply_review(session["id"], ReviewInput(decision="reject", round_index=1,
                                            feedback="the objective ignores the capacity"),
                 store=store)
    _round(store, session["id"])

    assert _FakeGenerator.seen_feedback == ("the objective ignores the capacity",)


def test_a_missing_research_model_fails_the_session(store, monkeypatch):
    monkeypatch.delenv("RESEARCH_MODEL", raising=False)
    created = create_session(_input(), ARTIFACT, store=store)

    session = _round(store, created["id"])

    assert session["state"] == "failed" and "RESEARCH_MODEL" in session["state_reason"]


def test_an_exception_mid_round_fails_the_session_rather_than_half_finishing(store, monkeypatch):
    class _Boom(_FakeGenerator):
        async def synthesise(self, **kwargs):
            raise RuntimeError("provider exploded")

    monkeypatch.setattr(session_module, "ScorerGenerator", _Boom)
    created = create_session(_input(), ARTIFACT, store=store)

    session = _round(store, created["id"])

    assert session["state"] == "failed" and "provider exploded" in session["state_reason"]


# --- review decisions --------------------------------------------------------

def test_rejection_must_carry_an_explanation():
    with pytest.raises(ValueError, match="at least 20 characters"):
        ReviewInput(decision="reject", feedback="no", round_index=1)


def test_acceptance_must_not_carry_feedback():
    with pytest.raises(ValueError, match="Feedback belongs with a rejection"):
        ReviewInput(decision="accept", feedback="looks fine to me honestly", round_index=1)


def test_a_stale_round_index_is_refused(store):
    """A browser tab left open must not reject a round the user already handled."""
    session = _start(store)
    with pytest.raises(SynthesisConflict, match="reload"):
        apply_review(session["id"], ReviewInput(decision="reject", round_index=2,
                                                feedback="this is a stale decision here"),
                     store=store)


def test_a_review_outside_awaiting_review_is_refused(store):
    session = _start(store)
    apply_review(session["id"], ReviewInput(decision="abandon", round_index=1), store=store)
    with pytest.raises(SynthesisConflict, match="not awaiting review"):
        apply_review(session["id"], ReviewInput(decision="abandon", round_index=1), store=store)


def test_abandoning_is_terminal_and_registers_nothing(store):
    session = _start(store)

    session = apply_review(session["id"], ReviewInput(decision="abandon", round_index=1),
                           store=store)

    assert session["state"] == "abandoned" and session["accepted"] is None
    assert store.all("fitness") == []


def test_three_rejections_exhaust_the_session_and_fail_closed(store):
    session = _start(store)
    for index in range(1, MAX_ROUNDS + 1):
        session = apply_review(
            session["id"],
            ReviewInput(decision="reject", round_index=index,
                        feedback=f"round {index} still mis-states the feasibility rule"),
            store=store)
        if index < MAX_ROUNDS:
            assert session["state"] == "generating"
            session = _round(store, session["id"])

    assert session["state"] == "exhausted"
    assert session["accepted"] is None
    assert "No scorer was registered" in session["state_reason"]
    # Failing closed means nothing resolvable was left behind.
    assert store.all("fitness") == []
    assert len(session["rounds"]) == MAX_ROUNDS


def test_a_fourth_round_cannot_be_started(store):
    session = _start(store)
    for index in range(1, MAX_ROUNDS + 1):
        apply_review(session["id"],
                     ReviewInput(decision="reject", round_index=index,
                                 feedback=f"round {index} is still wrong about validity"),
                     store=store)
        if index < MAX_ROUNDS:
            _round(store, session["id"])

    with pytest.raises(SynthesisConflict):
        _round(store, session["id"])


# --- restart -----------------------------------------------------------------

@pytest.mark.parametrize("state", ["extracting", "generating", "criticising"])
def test_a_round_interrupted_by_a_restart_fails(store, state):
    session = create_session(_input(), ARTIFACT, store=store)
    session["state"] = state
    session["round_index"] = 1
    store.put("synthesis", session["id"], session)

    assert restore_sessions(store) == 1

    reloaded = store.get("synthesis", session["id"])
    assert reloaded["state"] == "failed"
    assert "restarted" in reloaded["state_reason"]


def test_awaiting_review_survives_a_restart_and_is_still_reviewable(store):
    """The human's turn is the absence of a task, so nothing is in flight to lose."""
    session = _start(store)

    assert restore_sessions(store) == 0

    reloaded = store.get("synthesis", session["id"])
    assert reloaded["state"] == "awaiting_review"
    assert session_view(reloaded)["rounds"][0]["critic"]["chosen"] == "a"
    moved = apply_review(session["id"], ReviewInput(decision="reject", round_index=1,
                                                    feedback="still wrong about feasibility"),
                         store=store)
    assert moved["state"] == "generating"


def test_terminal_sessions_are_left_alone_by_a_restart(store):
    session = _start(store)
    apply_review(session["id"], ReviewInput(decision="abandon", round_index=1), store=store)

    assert restore_sessions(store) == 0
    assert store.get("synthesis", session["id"])["state"] == "abandoned"


# --- projection --------------------------------------------------------------

def test_the_view_reports_the_tier_and_terminality(store):
    session = _start(store)
    view = session_view(session)

    assert view["evidence_tier"] == "lean_checked_synthesised"
    assert view["terminal"] is False
    assert view["max_rounds"] == MAX_ROUNDS
    assert view["budget"]["max_tokens"] > 0
