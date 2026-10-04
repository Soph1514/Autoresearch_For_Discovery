"""Critic integration: advisory only, budgeted, and never able to change validity or elites."""

import asyncio
from types import SimpleNamespace

import pytest

from the_pigeon_holes.evolution.loop import EvolutionLoop
from the_pigeon_holes.evolution.models import (
    Assessment,
    CandidateDraft,
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionLimits,
    GenerationResult,
    TokenUsage,
)
from the_pigeon_holes.evolution.prompting import render_generation_prompt
from the_pigeon_holes.problems.autocorrelation import autocorrelation_contract
from the_pigeon_holes.llm.critic import AnthropicCritic, CriticConfig, _parse


def assessment(candidate_id, rating=4):
    return Assessment(
        candidate_id=candidate_id,
        promise_rating=rating,
        approach_summary="uses a dyadic construction",
        novelty_note="differs from the seed",
        risk_flags=("none",),
        model="fake",
        prompt_version="critic-v1",
    )


class FakeGenerator:
    def __init__(self):
        self.count = 0

    async def generate(self, requests):
        results = []
        for request in requests:
            self.count += 1
            source = f"def solve(n: int) -> list[int]:\n    # variant {self.count}\n    return [2**40] * n\n"
            results.append(
                GenerationResult(
                    request_id=request.id,
                    usage=TokenUsage(1, 1),
                    draft=CandidateDraft(
                        hypothesis=f"variant {self.count}",
                        predicted_effect="lower C1",
                        falsification_condition="no improvement",
                        mechanism_tags=("constant",),
                        source_code=source,
                    ),
                )
            )
        return tuple(results)


class FakeEvaluator:
    """Every candidate is valid with the same score, except sources containing 'bad'."""

    async def evaluate(self, candidates, problem):
        out = []
        for candidate in candidates:
            if "bad" in candidate.source_code:
                out.append(CandidateEvaluation(candidate.id, False, failure_stage="crash",
                                               failure_reasons=("x",), repairable=True,
                                               informative=True, total_cases=1))
            else:
                out.append(CandidateEvaluation(candidate.id, True, metrics={"c1": 2.0},
                                               behavioral_descriptor=(3.0, 1.0),
                                               passing_cases=1, total_cases=1))
        return tuple(out)


class FakeCritic:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    async def assess(self, candidate, evaluation, problem):
        assert evaluation.valid, "critic must only see valid candidates"
        self.calls.append(candidate.id)
        if self.result is not None:
            return self.result
        return assessment(candidate.id)


class Observer:
    def __init__(self):
        self.states = []
        self.assessments = []

    def candidate_created(self, candidate): pass
    def evaluation_started(self, candidate): pass
    def evaluation_completed(self, evaluation): pass
    def generation_failed(self, failure): pass
    def assessment_recorded(self, item): self.assessments.append(item)
    def state_committed(self, state): self.states.append(state)


def run_loop(critic, max_critic_calls=None):
    observer = Observer()
    loop = EvolutionLoop(
        config=EvolutionConfig(min_islands=2, max_islands=3, offspring_per_island=1,
                               max_batch_size=4, pool_size=4, tournament_size=2, random_seed=5),
        limits=EvolutionLimits(max_tokens=60, max_critic_calls=max_critic_calls),
        generator=FakeGenerator(),
        evaluator=FakeEvaluator(),
        observer=observer,
        critic=critic,
        clock=iter(range(0, 100000)).__next__,
    )
    outcome = asyncio.run(loop.run(autocorrelation_contract(8)))
    return outcome, observer


def test_critic_is_called_for_valid_candidates_only():
    critic = FakeCritic()
    _, observer = run_loop(critic)
    assert critic.calls, "expected at least one critic call"
    final = observer.states[-1]
    for candidate_id in critic.calls:
        assert final.evaluations[candidate_id].valid


def test_critic_budget_is_respected():
    critic = FakeCritic()
    run_loop(critic, max_critic_calls=2)
    assert len(critic.calls) <= 2


def test_critic_output_never_changes_validity_or_elites():
    _, with_critic = run_loop(FakeCritic(assessment("ignored", rating=5)))
    _, without = run_loop(None)
    assert with_critic.states[-1].global_best_id == without.states[-1].global_best_id
    assert {k: v.valid for k, v in with_critic.states[-1].evaluations.items()} == {
        k: v.valid for k, v in without.states[-1].evaluations.items()
    }


def test_missing_assessment_is_tolerated():
    _, observer = run_loop(_NoneCritic())
    assert observer.assessments == []
    assert observer.states, "loop must still commit states"


class _NoneCritic:
    async def assess(self, candidate, evaluation, problem):
        return None


def test_prompt_shows_critic_note_as_advisory():
    problem = autocorrelation_contract(8)
    from the_pigeon_holes.evolution.models import IslandState, IslandStatus, MutationStrength, SearchMode, EvolutionOperator, ProgramCandidate
    island = IslandState("island-1", None, None, SearchMode.EXPLOIT, IslandStatus.ACTIVE, 0)
    candidate = ProgramCandidate("c1", 1, "island-1", EvolutionOperator.MUTATE, (), (), "h", "p", "f",
                                 ("t",), "def solve(n: int) -> list[int]:\n    return []\n", "fp")
    evaluation = CandidateEvaluation("c1", True, metrics={"c1": 2.0}, passing_cases=1, total_cases=1)
    prompt = render_generation_prompt(
        problem=problem, island=island, operator=EvolutionOperator.MUTATE,
        mutation_strength=MutationStrength.MICRO,
        parents=[(candidate, evaluation)], inspirations=[],
        assessments={"c1": assessment("c1", rating=4)},
    )
    assert "Critic assessment (advisory" in prompt
    assert "promise 4/5" in prompt


def _response(data):
    block = SimpleNamespace(type="tool_use", name="submit_assessment", input=data)
    return SimpleNamespace(content=[block])


def test_parse_accepts_well_formed_output():
    data = {"approach_summary": "s", "promise_rating": 3, "novelty_note": "n", "risk_flags": []}
    parsed = _parse("c9", _response(data), "m")
    assert parsed.promise_rating == 3 and parsed.candidate_id == "c9"


@pytest.mark.parametrize("bad", [
    {"approach_summary": "s", "promise_rating": 9, "novelty_note": "n", "risk_flags": []},
    {"approach_summary": "s", "promise_rating": True, "novelty_note": "n", "risk_flags": []},
    {"approach_summary": "s", "promise_rating": 2, "novelty_note": "n", "risk_flags": "x"},
])
def test_parse_rejects_malformed_output(bad):
    assert _parse("c9", _response(bad), "m") is None


def test_critic_refuses_invalid_candidates():
    critic = AnthropicCritic(CriticConfig(model="m"), client=object())
    evaluation = CandidateEvaluation("c", False, failure_stage="crash", failure_reasons=("x",), total_cases=1)
    candidate = SimpleNamespace(id="c", source_code="", source_fingerprint="fp")
    with pytest.raises(ValueError):
        asyncio.run(critic.assess(candidate, evaluation, autocorrelation_contract(8)))


def test_critic_deadline_preserves_valid_seed_and_cancels_assessment():
    cancelled = []
    class SlowCritic:
        async def assess(self, *args):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.append(True)
    async def scenario():
        loop = EvolutionLoop(config=EvolutionConfig(), limits=EvolutionLimits(max_time_seconds=.02),
            generator=FakeGenerator(), evaluator=FakeEvaluator(), critic=SlowCritic())
        result = await loop.run(autocorrelation_contract(64))
        assert result.stop_reason.value == 'time_limit'
        assert result.best_evaluation.valid
        assert cancelled
    asyncio.run(scenario())


def test_critic_usage_includes_malformed_responses():
    response = SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=12, output_tokens=3))
    async def create(**kwargs):
        return response
    critic = AnthropicCritic(CriticConfig(model='test'), client=SimpleNamespace(messages=SimpleNamespace(create=create)))
    async def scenario():
        # The critic only needs a candidate's public generation context and source.
        candidate = SimpleNamespace(id='seed', hypothesis='seed', predicted_effect='baseline', source_code='def solve(n: int) -> list[int]: return [2**40]*n')
        result = await critic.assess(candidate, CandidateEvaluation('seed', True, metrics={'c1': 2.0}), autocorrelation_contract(64))
        assert result is None
        assert critic.usage == TokenUsage(12, 3)
    asyncio.run(scenario())
