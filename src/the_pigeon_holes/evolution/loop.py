"""Budgeted orchestration of the evolution sub-loop."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence

from the_pigeon_holes.models.problem_contract import ProblemContract

from .engine import EvolutionEngine, validate_source_signature
from .models import (
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionLimits,
    EvolutionOperator,
    EvolutionOutcome,
    EvolutionProtocolError,
    EvolutionState,
    GenerationFailure,
    GenerationRequest,
    GenerationResult,
    ProgramCandidate,
    StopReason,
    TokenUsage,
)
from .novelty import source_fingerprint
from .ports import CandidateEvaluator, ProgramGenerator


class _BudgetTracker:
    def __init__(
        self,
        limits: EvolutionLimits,
        max_tokens_per_request: int,
        clock: Callable[[], float],
    ) -> None:
        self.limits = limits
        self.max_tokens_per_request = max_tokens_per_request
        self.clock = clock
        self.started_at = clock()
        self.tokens_used = 0

    @property
    def elapsed_seconds(self) -> float:
        return self.clock() - self.started_at

    @property
    def remaining_tokens(self) -> int | None:
        if self.limits.max_tokens is None:
            return None
        return max(0, self.limits.max_tokens - self.tokens_used)

    def affordable_requests(self, requested: int) -> int:
        remaining = self.remaining_tokens
        if remaining is None:
            return requested
        return min(requested, remaining // self.max_tokens_per_request)

    def record(self, usages: Sequence[TokenUsage]) -> None:
        self.tokens_used += sum(usage.total_tokens for usage in usages)

    def stop_reason(self) -> StopReason | None:
        time_reached = (
            self.limits.max_time_seconds is not None
            and self.elapsed_seconds >= self.limits.max_time_seconds
        )
        tokens_reached = (
            self.limits.max_tokens is not None
            and self.tokens_used >= self.limits.max_tokens
        )
        if time_reached and tokens_reached:
            return StopReason.TIME_AND_TOKEN_LIMIT
        if time_reached:
            return StopReason.TIME_LIMIT
        if tokens_reached:
            return StopReason.TOKEN_LIMIT
        return None


class EvolutionLoop:
    """Run program evolution against injected generation and evaluation ports."""

    def __init__(
        self,
        *,
        config: EvolutionConfig,
        limits: EvolutionLimits,
        generator: ProgramGenerator,
        evaluator: CandidateEvaluator,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.limits = limits
        self.generator = generator
        self.evaluator = evaluator
        self.clock = clock
        self.engine = EvolutionEngine(config)

    async def run(self, problem: ProblemContract) -> EvolutionOutcome:
        budget = _BudgetTracker(
            self.limits,
            self.config.max_tokens_per_request,
            self.clock,
        )
        seed = ProgramCandidate(
            id="candidate-000000",
            generation=0,
            island_id=None,
            operator=EvolutionOperator.RESTART,
            parent_ids=(),
            inspiration_ids=(),
            hypothesis="User-provided seed program.",
            predicted_effect="Establish a baseline for evolutionary search.",
            falsification_condition="The seed fails deterministic evaluation.",
            mechanism_tags=("seed",),
            source_code=problem.seed_program,
            source_fingerprint=source_fingerprint(problem.seed_program),
        )
        seed_static_error = validate_source_signature(
            seed.source_code,
            problem.solve_signature,
        )
        if seed_static_error:
            seed_evaluation = self._static_failure(seed, seed_static_error)
        else:
            seed_evaluation = (await self._evaluate((seed,), problem))[0]
        state = self.engine.initialise(seed, seed_evaluation)

        stop_reason: StopReason | None = None
        while stop_reason is None:
            stop_reason = budget.stop_reason()
            if stop_reason is not None:
                break

            desired = min(
                len(state.active_islands) * self.config.offspring_per_island,
                self.config.max_batch_size,
            )
            affordable = budget.affordable_requests(desired)
            if affordable == 0:
                stop_reason = StopReason.NO_AFFORDABLE_REQUEST
                break

            requests = self.engine.plan_generation(state, problem, affordable)
            if not requests:
                stop_reason = StopReason.NO_AFFORDABLE_REQUEST
                break

            generated = tuple(await self.generator.generate(requests))
            self._validate_generation_results(requests, generated)
            budget.record([result.usage for result in generated])

            candidates, local_evaluations = self._materialize_generation(
                state,
                requests,
                generated,
                problem,
            )
            if not candidates:
                stop_reason = StopReason.GENERATION_FAILED
                break
            external_candidates = tuple(
                candidate
                for candidate in candidates
                if candidate.id not in local_evaluations
            )
            external_evaluations = (
                await self._evaluate(external_candidates, problem)
                if external_candidates
                else ()
            )
            evaluations = tuple(local_evaluations.values()) + tuple(external_evaluations)
            state = self.engine.apply_generation(
                state,
                candidates,
                evaluations,
                problem.optimisation_goal,
            )

        assert stop_reason is not None
        return self._outcome(state, budget, stop_reason)

    def _materialize_generation(
        self,
        state: EvolutionState,
        requests: Sequence[GenerationRequest],
        results: Sequence[GenerationResult],
        problem: ProblemContract,
    ) -> tuple[tuple[ProgramCandidate, ...], dict[str, CandidateEvaluation]]:
        request_by_id = {request.id: request for request in requests}
        candidates: list[ProgramCandidate] = []
        local_evaluations: dict[str, CandidateEvaluation] = {}
        known_fingerprints = {
            candidate.source_fingerprint for candidate in state.candidates.values()
        }

        for result in sorted(results, key=lambda item: item.request_id):
            request = request_by_id[result.request_id]
            if result.error is not None:
                state.generation_failures.append(
                    GenerationFailure(
                        request_id=result.request_id,
                        generation=request.generation,
                        error=result.error,
                        usage=result.usage,
                        prompt=request.prompt,
                    )
                )
                continue

            assert result.draft is not None
            draft = result.draft
            candidate_id = f"candidate-{state.next_candidate_number:06d}"
            state.next_candidate_number += 1
            fingerprint = source_fingerprint(draft.source_code)
            candidate = ProgramCandidate(
                id=candidate_id,
                generation=request.generation,
                island_id=request.island_id,
                operator=request.operator,
                parent_ids=request.parent_ids,
                inspiration_ids=request.inspiration_ids,
                hypothesis=draft.hypothesis.strip(),
                predicted_effect=draft.predicted_effect.strip(),
                falsification_condition=draft.falsification_condition.strip(),
                mechanism_tags=tuple(
                    sorted({tag.strip().casefold() for tag in draft.mechanism_tags if tag.strip()})
                ),
                source_code=draft.source_code,
                source_fingerprint=fingerprint,
                request_id=request.id,
                generation_prompt=request.prompt,
                generation_usage=result.usage,
            )
            candidates.append(candidate)

            error = validate_source_signature(candidate.source_code, problem.solve_signature)
            if error is None and fingerprint in known_fingerprints:
                error = "candidate duplicates a previously generated normalized source tree"
            if error is not None:
                local_evaluations[candidate.id] = self._static_failure(candidate, error)
            known_fingerprints.add(fingerprint)

        return tuple(candidates), local_evaluations

    async def _evaluate(
        self,
        candidates: Sequence[ProgramCandidate],
        problem: ProblemContract,
    ) -> tuple[CandidateEvaluation, ...]:
        evaluations = tuple(await self.evaluator.evaluate(candidates, problem))
        expected = {candidate.id for candidate in candidates}
        actual = {evaluation.candidate_id for evaluation in evaluations}
        if actual != expected or len(actual) != len(evaluations):
            raise EvolutionProtocolError(
                "evaluator must return exactly one result for every requested candidate"
            )
        configured_metrics = (
            problem.optimisation_goal.primary,
            *problem.optimisation_goal.tie_breakers,
        )
        expected_cases = len(problem.evaluation_suite.cases)
        for evaluation in evaluations:
            if evaluation.valid:
                if (
                    evaluation.total_cases != expected_cases
                    or evaluation.passing_cases != expected_cases
                ):
                    raise EvolutionProtocolError(
                        "valid evaluator result must pass every evaluation-suite case"
                    )
                for metric in configured_metrics:
                    value = evaluation.metrics.get(metric.name)
                    if value is None or not math.isfinite(value):
                        raise EvolutionProtocolError(
                            "valid evaluator result must contain finite configured metric "
                            f"{metric.name!r}"
                        )
            if evaluation.behavioral_descriptor is not None and not all(
                math.isfinite(value) for value in evaluation.behavioral_descriptor
            ):
                raise EvolutionProtocolError("behavioral descriptors must contain finite values")
        return tuple(sorted(evaluations, key=lambda evaluation: evaluation.candidate_id))

    @staticmethod
    def _validate_generation_results(
        requests: Sequence[GenerationRequest],
        results: Sequence[GenerationResult],
    ) -> None:
        expected = {request.id for request in requests}
        actual = {result.request_id for result in results}
        if actual != expected or len(actual) != len(results):
            raise EvolutionProtocolError(
                "generator must return exactly one result for every generation request"
            )

    @staticmethod
    def _static_failure(
        candidate: ProgramCandidate,
        reason: str,
    ) -> CandidateEvaluation:
        return CandidateEvaluation(
            candidate_id=candidate.id,
            valid=False,
            failure_stage="static_validation",
            failure_reasons=(reason,),
            repairable=True,
            informative=True,
        )

    @staticmethod
    def _outcome(
        state: EvolutionState,
        budget: _BudgetTracker,
        stop_reason: StopReason,
    ) -> EvolutionOutcome:
        best_candidate = state.candidates.get(state.global_best_id or "")
        best_evaluation = state.evaluations.get(state.global_best_id or "")
        elite_ids = {
            island.elite_id for island in state.active_islands.values() if island.elite_id
        }
        return EvolutionOutcome(
            best_candidate=best_candidate,
            best_evaluation=best_evaluation,
            stop_reason=stop_reason,
            elapsed_seconds=budget.elapsed_seconds,
            tokens_used=budget.tokens_used,
            generations_completed=state.generation,
            candidates_generated=len(state.candidates),
            candidates_evaluated=len(state.evaluations),
            active_islands=len(state.active_islands),
            elite_count=len(elite_ids),
            novelty_count=len(state.novelty_records),
            state=state,
        )
