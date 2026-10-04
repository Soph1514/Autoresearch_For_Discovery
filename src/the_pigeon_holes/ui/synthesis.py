"""The human-in-the-loop scorer synthesis session.

Runs between a checked Lean statement and a frozen contract, only where
`compile_fitness` reports `unsupported_formalization`.

Each round is a background task that ends by writing `awaiting_review` and
exiting. No coroutine ever blocks waiting for a person: the human's decision
arrives as a separate request that starts the next round. That is what makes
`awaiting_review` survive a backend restart — the human's turn is the absence of
a running task.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, Field, model_validator

from the_pigeon_holes.execution.signature_extractor import (
    ExtractedInterface,
    MetricGoal,
    OptimisationGoal,
    Parameter,
    extract_signature,
    verify_interface_syntax,
)
from the_pigeon_holes.fitness.synthesis.adapter import (
    EVIDENCE_TIER,
    freeze_scorer,
    load_synthesised_fitness,
)
from the_pigeon_holes.fitness.synthesis.critic import ScorerCritic
from the_pigeon_holes.fitness.synthesis.generator import (
    ScorerCandidate,
    ScorerGenerator,
    ScorerSynthesisConfig,
)
from the_pigeon_holes.llm.budget import ProviderTokenBudget
from the_pigeon_holes.models.problem_contract import EvaluationCase

MAX_ROUNDS = 3
WORKING_STATES = ("extracting", "generating", "criticising")
TERMINAL_STATES = ("accepted", "exhausted", "abandoned", "failed")
KIND = "synthesis"


class SynthesisInput(BaseModel):
    formalization_id: str
    evaluation_suite_id: str = Field(min_length=1, max_length=200)
    evaluation_cases: dict[str, dict] = Field(min_length=1, max_length=1000)
    seed_program: str | None = Field(default=None, max_length=64000)
    alignment_reviewed: bool = False
    instance_reviewed: bool = False
    max_tokens: int = Field(default=400_000, gt=0, le=5_000_000)


class ReviewInput(BaseModel):
    decision: str = Field(pattern="^(accept|reject|abandon)$")
    feedback: str = Field(default="", max_length=8000)
    round_index: int = Field(gt=0, le=MAX_ROUNDS)

    @model_validator(mode="after")
    def check_feedback(self):
        if self.decision == "reject" and len(self.feedback.strip()) < 20:
            raise ValueError(
                "Explain the rejection in at least 20 characters; the next round is "
                "generated from this feedback."
            )
        if self.decision != "reject" and self.feedback.strip():
            raise ValueError("Feedback belongs with a rejection.")
        return self


class SynthesisConflict(RuntimeError):
    """The caller acted on a state the session is no longer in."""


def _now() -> float:
    return time.time()


def _goal_to_json(goal: OptimisationGoal) -> dict:
    return {"primary": {"name": goal.primary.name, "direction": goal.primary.direction},
            "aggregation": goal.aggregation,
            "tie_breakers": [{"name": t.name, "direction": t.direction} for t in goal.tie_breakers]}


def _interface_to_json(interface: ExtractedInterface) -> dict:
    return {"function_name": interface.function_name,
            "parameters": [{"name": p.name, "python_type": p.python_type}
                           for p in interface.parameters],
            "return_type": interface.return_type,
            "signature_str": interface.signature_str,
            "pydantic_classes_code": interface.pydantic_classes_code,
            "optimisation_goal": _goal_to_json(interface.optimisation_goal)}


def _interface_from_json(raw: Mapping) -> ExtractedInterface:
    goal = raw["optimisation_goal"]
    return ExtractedInterface(
        function_name=raw["function_name"],
        parameters=[Parameter(p["name"], p["python_type"]) for p in raw["parameters"]],
        return_type=raw["return_type"],
        signature_str=raw["signature_str"],
        pydantic_classes_code=raw["pydantic_classes_code"],
        optimisation_goal=OptimisationGoal(
            primary=MetricGoal(**goal["primary"]),
            aggregation=goal["aggregation"],
            tie_breakers=tuple(MetricGoal(**t) for t in goal.get("tie_breakers", []))),
    )


def _candidate_to_json(candidate: ScorerCandidate) -> dict:
    return {"slot": candidate.slot, "model": candidate.model, "framing": candidate.framing,
            "source_code": candidate.source_code, "metric_names": list(candidate.metric_names),
            "descriptor_arity": candidate.descriptor_arity,
            "descriptor_axes": [dict(axis) for axis in candidate.descriptor_axes],
            "validity_rules": list(candidate.validity_rules),
            "objective_derivation": candidate.objective_derivation,
            "reconciliation_notes": candidate.reconciliation_notes,
            "static_problems": list(candidate.static_problems),
            "usable": candidate.usable, "error": candidate.error,
            "usage": {"input_tokens": candidate.usage.input_tokens,
                      "output_tokens": candidate.usage.output_tokens}}


def create_session(body: SynthesisInput, artifact: Mapping | None, *, store,
                   unsupported_reason: str = "") -> dict:
    """Open a session against a checked formalization. Does not start a round."""
    if artifact is None:
        raise ValueError("Formalization not found. Submit and check the problem first.")
    result = artifact["result"]
    if not result["lean_checked"]:
        raise ValueError("Lean must pass checking before scorer synthesis.")
    has_instance = bool(artifact['input'].get('instance', '').strip())
    if (has_instance or result["status"] != "checked") and not body.alignment_reviewed:
        raise ValueError(
            "Review the Lean statement against the problem and acknowledge its "
            "alignment before continuing.")
    if has_instance and not body.instance_reviewed:
        raise ValueError('Review the instance JSON against your description before scorer synthesis.')
    from uuid import uuid4

    identity = str(uuid4())
    session = {
        "id": identity, "state": "extracting", "state_reason": "",
        "created_at": _now(), "updated_at": _now(),
        "formalization_id": body.formalization_id,
        "problem_statement": artifact["input"]["problem"],
        "lean_source": result["lean"],
        "unsupported_reason": unsupported_reason,
        "evaluation_suite_id": body.evaluation_suite_id,
        "evaluation_cases": dict(body.evaluation_cases),
        "seed_program": body.seed_program,
        "alignment_reviewed": body.alignment_reviewed,
        "interface": None,
        "round_index": 0, "max_rounds": MAX_ROUNDS,
        "budget": {"max_tokens": body.max_tokens, "spent_tokens": 0, "calls": []},
        "rounds": [], "accepted": None,
    }
    store.put(KIND, identity, session)
    return session


def _save(store, session: dict, **changes) -> dict:
    session.update(changes, updated_at=_now())
    store.put(KIND, session["id"], session)
    return session


def _feedback_history(session: Mapping) -> tuple[str, ...]:
    return tuple(entry["review"]["feedback"] for entry in session["rounds"]
                 if entry.get("review") and entry["review"]["decision"] == "reject")


def extract_interface(lean_source: str, *, model: str, client) -> ExtractedInterface:
    """Extract once per session so the reviewed interface is the frozen interface."""
    interface = extract_signature(lean_source, model=model, client=client)
    verify_interface_syntax(interface)
    return interface


async def run_round(session_id: str, *, store, client_factory=None, extractor=None,
                    config: ScorerSynthesisConfig | None = None,
                    critic_model: str | None = None) -> dict:
    """Run one generate-and-critique round, ending at `awaiting_review`.

    Any failure ends the session rather than leaving a round half-done; a round
    is counted as soon as it starts, so a crash loop cannot exceed the cap.
    """
    session = store.get(KIND, session_id)
    if session is None:
        raise ValueError("Synthesis session not found.")
    if session["state"] not in ("extracting", "generating"):
        raise SynthesisConflict(f"a round cannot start from state {session['state']!r}")
    if session["round_index"] >= session["max_rounds"]:
        raise SynthesisConflict("the round cap is already reached")

    model = os.environ.get("RESEARCH_MODEL")
    if not model:
        return _save(store, session, state="failed",
                     state_reason="Configure RESEARCH_MODEL before synthesising a scorer.")
    config = config or ScorerSynthesisConfig()
    if client_factory is None:
        import anthropic

        def client_factory():
            return anthropic.AsyncAnthropic(timeout=180, max_retries=0)
    if extractor is None:
        extractor = _default_extractor

    # Count the round before spending anything.
    round_index = session["round_index"] + 1
    session = _save(store, session, round_index=round_index, state="generating")
    remaining = session["budget"]["max_tokens"] - session["budget"]["spent_tokens"]
    if remaining <= 0:
        return _save(store, session, state="failed",
                     state_reason="The synthesis token budget is exhausted.")
    budget = ProviderTokenBudget(remaining)

    try:
        client = client_factory()
        try:
            if session["interface"] is None:
                interface = await asyncio.to_thread(
                    extractor, session["lean_source"], model)
                session = _save(store, session, interface=_interface_to_json(interface))
            else:
                interface = _interface_from_json(session["interface"])

            feedback = _feedback_history(session)
            generator = ScorerGenerator(config, client=client, budget=budget)
            a, b = await generator.synthesise(
                problem=session["problem_statement"], lean_source=session["lean_source"],
                interface=interface, feedback=feedback)

            session = _save(store, session, state="criticising")
            critic = ScorerCritic(model=critic_model or config.lean_primary_model,
                                  client=client, budget=budget)
            choice = await critic.choose(a, b, problem=session["problem_statement"],
                                         lean_source=session["lean_source"],
                                         interface=interface, feedback=feedback)
        finally:
            await _close(client)
    except Exception as error:  # noqa: BLE001 - the session records every failure mode
        return _save(store, session, state="failed",
                     state_reason=f"{type(error).__name__}: {error}")

    spent = (a.usage.total_tokens + b.usage.total_tokens + choice.usage.total_tokens)
    session["budget"]["spent_tokens"] += spent
    session["budget"]["calls"] = budget.summary()["calls"]
    session["rounds"].append({
        "index": round_index, "ended_at": _now(),
        "candidates": {"a": _candidate_to_json(a), "b": _candidate_to_json(b)},
        "critic": {"chosen": choice.chosen, "justification": choice.justification,
                   "key_differences": list(choice.key_differences),
                   "residual_risks": list(choice.residual_risks),
                   "unresolved_ambiguities": list(choice.unresolved_ambiguities),
                   "error": choice.error},
        "review": None,
    })
    return _save(store, session, state="awaiting_review", state_reason="")


def _default_extractor(lean_source: str, model: str) -> ExtractedInterface:
    """The extractor is synchronous, so it gets its own short-lived client."""
    import anthropic

    with anthropic.Anthropic(timeout=90, max_retries=0) as client:
        return extract_interface(lean_source, model=model, client=client)


async def _close(client) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def apply_review(session_id: str, body: ReviewInput, *, store,
                 artifacts: Path | None = None) -> dict:
    """Record the human's decision and move the session on.

    Rejection at the final round is terminal: nothing is frozen and nothing is
    registered, so `resolve()` keeps failing closed.
    """
    session = store.get(KIND, session_id)
    if session is None:
        raise ValueError("Synthesis session not found.")
    if session["state"] != "awaiting_review":
        raise SynthesisConflict(f"this session is {session['state']}, not awaiting review")
    if body.round_index != session["round_index"]:
        raise SynthesisConflict(
            f"this decision is for round {body.round_index} but the session is on "
            f"round {session['round_index']}; reload and look again")

    current = session["rounds"][-1]
    current["review"] = {"decision": body.decision, "feedback": body.feedback.strip(),
                         "at": _now()}

    if body.decision == "abandon":
        return _save(store, session, state="abandoned",
                     state_reason="A human abandoned the synthesis.")
    if body.decision == "reject":
        if session["round_index"] >= session["max_rounds"]:
            return _save(store, session, state="exhausted", state_reason=(
                f"Rejected at round {session['max_rounds']} of {session['max_rounds']}. "
                "No scorer was registered and no contract was created."))
        return _save(store, session, state="generating",
                     state_reason="Rejected; the next round uses this feedback.")

    chosen = _chosen_candidate(current)
    if chosen is None:
        raise SynthesisConflict("no usable scorer in this round can be accepted")
    other = "b" if chosen["slot"] == "a" else "a"
    interface = _interface_from_json(session["interface"])
    artifacts = artifacts or Path(store.path).parent / "fitness"
    case_id, inputs = next(iter(session["evaluation_cases"].items()))
    probe_output: Any = [] if interface.return_type.startswith("list") else 0

    scorer = freeze_scorer(
        source=chosen["source_code"], statement=session["problem_statement"],
        lean_source=session["lean_source"], interface=interface,
        metric_names_declared=tuple(chosen["metric_names"]),
        descriptor_arity=chosen["descriptor_arity"],
        descriptor_axes=tuple(chosen["descriptor_axes"]),
        artifacts=artifacts, probe_case=EvaluationCase(case_id, inputs),
        probe_output=probe_output,
        review={"rounds": session["rounds"], "accepted_round": session["round_index"],
                "accepted_slot": chosen["slot"], "accepted_at": _now()},
        rejected_source=current["candidates"][other]["source_code"],
    )
    store.put("fitness", scorer.reference.id,
              {"artifact": str(scorer.artifact), "manifest": scorer.manifest,
               "evidence_tier": EVIDENCE_TIER})
    return _save(store, session, state="accepted", state_reason="", accepted={
        "fitness_id": scorer.reference.id,
        "fitness_version": scorer.reference.version,
        "implementation_sha256": scorer.reference.implementation_sha256,
        "artifact": str(scorer.artifact), "evidence_tier": EVIDENCE_TIER,
        "slot": chosen["slot"], "model": chosen["model"], "round": session["round_index"]})


def _chosen_candidate(round_body: Mapping) -> dict | None:
    """The critic's pick when it is usable, else the only usable candidate."""
    candidates = round_body["candidates"]
    chosen = (round_body.get("critic") or {}).get("chosen")
    if chosen in candidates and candidates[chosen]["usable"]:
        return candidates[chosen]
    usable = [candidate for candidate in candidates.values() if candidate["usable"]]
    return usable[0] if len(usable) == 1 else None


def load_accepted_scorer(session: Mapping):
    """Reload the scorer a human accepted, by its content-bound reference."""
    from the_pigeon_holes.models.problem_contract import FitnessFunctionRef

    accepted = session.get("accepted")
    if not accepted:
        raise ValueError("This synthesis session has no accepted scorer.")
    reference = FitnessFunctionRef(accepted["fitness_id"], accepted["fitness_version"],
                                   accepted["implementation_sha256"])
    return load_synthesised_fitness(Path(accepted["artifact"]), reference)


def restore_sessions(store) -> int:
    """Fail any session whose round task died with the process.

    Auto-resuming would risk re-billing calls that may already have completed and
    double-counting the round cap, so an interrupted round ends the session and
    keeps the evidence from the rounds that finished.
    """
    interrupted = 0
    for session in store.all(KIND):
        if session.get("state") in WORKING_STATES:
            session["state"] = "failed"
            session["state_reason"] = (
                f"The backend restarted during round {session.get('round_index', 0)}. "
                "Provider calls may already have been billed; start a new synthesis.")
            session["updated_at"] = _now()
            store.put(KIND, session["id"], session)
            interrupted += 1
    return interrupted


def session_view(session: Mapping) -> dict:
    """The projection the UI polls. Carries every round, including rejected ones."""
    return {
        "id": session["id"], "state": session["state"],
        "state_reason": session.get("state_reason", ""),
        "round_index": session["round_index"], "max_rounds": session["max_rounds"],
        "formalization_id": session["formalization_id"],
        "unsupported_reason": session.get("unsupported_reason", ""),
        "evidence_tier": EVIDENCE_TIER,
        "budget": session["budget"],
        "interface": session.get("interface"),
        "rounds": session["rounds"],
        "accepted": session.get("accepted"),
        "terminal": session["state"] in TERMINAL_STATES,
    }
