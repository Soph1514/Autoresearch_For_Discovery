"""Budgeted orchestration of the evolution sub-loop."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import replace

from the_pigeon_holes.models.problem_contract import ProblemContract

from .engine import EvolutionEngine, validate_source_signature
from .models import (
    Assessment,
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
from .ports import (
    CandidateCritic,
    CandidateEvaluator,
    EvolutionObserver,
    ProgramGenerator,
    RunCheckpoint,
)


class _RunDeadlineReached(Exception):
    pass


class _NullObserver:
    def candidate_created(self, candidate: ProgramCandidate) -> None:
        pass

    def assessment_recorded(self, assessment: Assessment) -> None:
        pass

    def evaluation_started(self, candidate: ProgramCandidate) -> None:
        pass

    def evaluation_completed(self, evaluation: CandidateEvaluation) -> None:
        pass

    def generation_failed(self, failure: GenerationFailure) -> None:
        pass

    def state_committed(self, state: EvolutionState) -> None:
        pass


async def _open_checkpoint() -> None:
    """Default boundary hook for runs without external controls."""


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
        self.critic_calls = 0

    def critic_budget_allows(self, additional: int) -> bool:
        if self.limits.max_critic_calls is None:
            return True
        return self.critic_calls + additional <= self.limits.max_critic_calls

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
        observer: EvolutionObserver | None = None,
        checkpoint: RunCheckpoint = _open_checkpoint,
        clock: Callable[[], float] = time.monotonic,
        require_valid_seed: bool = False,
        prepare_requests: Callable[[Sequence[GenerationRequest]], Sequence[GenerationRequest]] | None = None,
        critic: CandidateCritic | None = None,
    ) -> None:
        self.prepare_requests = prepare_requests
        self.require_valid_seed = require_valid_seed
        self.config = config
        self.limits = limits
        self.generator = generator
        self.evaluator = evaluator
        self.observer = observer or _NullObserver()
        self.checkpoint = checkpoint
        self.clock = clock
        self.critic = critic
        self.engine = EvolutionEngine(config)
        # Assessments depend only on the source and its evidence, so identical
        # sources are never sent to the critic twice in one run.
        self._assessment_cache: dict[str, Assessment] = {}

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
        self.observer.candidate_created(seed)
        if seed_static_error:
            seed_evaluation = self._static_failure(seed, seed_static_error)
        else:
            self.observer.evaluation_started(seed)
            try:
                seed_evaluation = (await self._within_budget(self._evaluate((seed,), problem), budget))[0]
            except _RunDeadlineReached:
                seed_evaluation = CandidateEvaluation(seed.id, False, failure_stage="timeout",
                    failure_reasons=("Run deadline reached during seed evaluation.",))
        self.observer.evaluation_completed(seed_evaluation)
        state = self.engine.initialise(seed, seed_evaluation)
        try:
            await self._within_budget(self._assess_valid(state, (seed,), problem, budget), budget)
        except _RunDeadlineReached:
            self.observer.state_committed(state)
            return self._outcome(state, budget, StopReason.TIME_LIMIT)
        self.observer.state_committed(state)

        if self.require_valid_seed and not seed_evaluation.valid:
            return self._outcome(state, budget, budget.stop_reason() or StopReason.INVALID_SEED)

        stop_reason: StopReason | None = None
        while stop_reason is None:
            stop_reason = budget.stop_reason()
            if stop_reason is not None:
                break

            # Pause/cancellation belongs to orchestration, not provider adapters.
            # Existing work is committed before this next-batch boundary is reached.
            await self.checkpoint()
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

            if self.prepare_requests is not None:
                requests = self.prepare_requests(requests)

            try:
                generated = tuple(await self._within_budget(self.generator.generate(requests), budget))
            except _RunDeadlineReached:
                stop_reason = StopReason.TIME_LIMIT
                break
            self._validate_generation_results(requests, generated)
            budget.record([result.usage for result in generated])

            candidates, local_evaluations, duplicate_targets = self._materialize_generation(
                state,
                requests,
                generated,
                problem,
            )
            for candidate in candidates:
                self.observer.candidate_created(candidate)
            for evaluation in local_evaluations.values():
                self.observer.evaluation_completed(evaluation)
            if not candidates:
                stop_reason = StopReason.GENERATION_FAILED
                break
            external_candidates = tuple(
                candidate
                for candidate in candidates
                if candidate.id not in local_evaluations
                and candidate.id not in duplicate_targets
            )
            for candidate in external_candidates:
                self.observer.evaluation_started(candidate)
            try:
                external_evaluations = (
                    await self._within_budget(self._evaluate(external_candidates, problem), budget)
                    if external_candidates else ()
                )
            except _RunDeadlineReached:
                stop_reason = StopReason.TIME_LIMIT
                break
            for evaluation in external_evaluations:
                self.observer.evaluation_completed(evaluation)
            evaluation_by_id = {
                **local_evaluations,
                **{evaluation.candidate_id: evaluation for evaluation in external_evaluations},
            }
            duplicate_evaluations: list[CandidateEvaluation] = []
            for candidate_id, canonical_id in sorted(duplicate_targets.items()):
                canonical = evaluation_by_id.get(canonical_id) or state.evaluations.get(canonical_id)
                if canonical is None:
                    raise EvolutionProtocolError(
                        f"duplicate candidate {candidate_id!r} has unknown canonical source {canonical_id!r}"
                    )
                reused = replace(
                    canonical,
                    candidate_id=candidate_id,
                    executed=False,
                    reused_from_candidate_id=canonical_id,
                )
                duplicate_evaluations.append(reused)
                self.observer.evaluation_completed(reused)
            evaluations = (
                tuple(local_evaluations.values())
                + tuple(external_evaluations)
                + tuple(duplicate_evaluations)
            )
            state = self.engine.apply_generation(
                state,
                candidates,
                evaluations,
                problem.optimisation_goal,
            )
            try:
                await self._within_budget(self._assess_valid(state, candidates, problem, budget), budget)
            except _RunDeadlineReached:
                stop_reason = StopReason.TIME_LIMIT
            self.observer.state_committed(state)

        assert stop_reason is not None
        return self._outcome(state, budget, stop_reason)

    @staticmethod
    async def _within_budget(work, budget):
        remaining = (None if budget.limits.max_time_seconds is None else
                     max(0, budget.limits.max_time_seconds - budget.elapsed_seconds))
        timeout = asyncio.timeout(remaining)
        try:
            async with timeout:
                return await work
        except TimeoutError as error:
            if timeout.expired():
                raise _RunDeadlineReached() from error
            raise
    async def _assess_valid(
        self,
        state: EvolutionState,
        candidates: Sequence[ProgramCandidate],
        problem: ProblemContract,
        budget: _BudgetTracker,
    ) -> None:
        """Attach advisory critic output to valid candidates. Never affects validity or elites."""
        if self.critic is None:
            return
        pending: list[ProgramCandidate] = []
        for candidate in sorted(candidates, key=lambda item: item.id):
            evaluation = state.evaluations[candidate.id]
            if not evaluation.valid or evaluation.reused_from_candidate_id is not None:
                continue
            cached = self._assessment_cache.get(candidate.source_fingerprint)
            if cached is not None:
                self._record_assessment(state, replace(cached, candidate_id=candidate.id))
                continue
            if not budget.critic_budget_allows(len(pending) + 1):
                break
            pending.append(candidate)
        if not pending:
            return
        budget.critic_calls += len(pending)
        before = getattr(self.critic, 'usage', TokenUsage())
        tasks = [asyncio.create_task(self.critic.assess(candidate, state.evaluations[candidate.id], problem))
                 for candidate in pending]
        try:
            results = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            after = getattr(self.critic, 'usage', before)
            budget.record([TokenUsage(after.input_tokens - before.input_tokens, after.output_tokens - before.output_tokens)])
        for candidate, assessment in zip(pending, results):
            if assessment is None:
                continue
            self._assessment_cache[candidate.source_fingerprint] = assessment
            self._record_assessment(state, assessment)

    def _record_assessment(self, state: EvolutionState, assessment: Assessment) -> None:
        state.assessments[assessment.candidate_id] = assessment
        self.observer.assessment_recorded(assessment)

    def _materialize_generation(
        self,
        state: EvolutionState,
        requests: Sequence[GenerationRequest],
        results: Sequence[GenerationResult],
        problem: ProblemContract,
    ) -> tuple[
        tuple[ProgramCandidate, ...],
        dict[str, CandidateEvaluation],
        dict[str, str],
    ]:
        request_by_id = {request.id: request for request in requests}
        candidates: list[ProgramCandidate] = []
        local_evaluations: dict[str, CandidateEvaluation] = {}
        known_sources = dict(state.source_index)
        if not known_sources:
            known_sources = {
                candidate.source_fingerprint: candidate.id
                for candidate in state.candidates.values()
            }
        duplicate_targets: dict[str, str] = {}

        for result in sorted(results, key=lambda item: item.request_id):
            request = request_by_id[result.request_id]
            if result.error is not None:
                failure = GenerationFailure(
                    request_id=result.request_id,
                    generation=request.generation,
                    error=result.error,
                    usage=result.usage,
                    prompt=request.prompt,
                )
                state.generation_failures.append(failure)
                self.observer.generation_failed(failure)
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

            canonical_id = known_sources.get(fingerprint)
            if canonical_id is not None:
                duplicate_targets[candidate.id] = canonical_id
            else:
                error = validate_source_signature(candidate.source_code, problem.solve_signature)
                if error is not None:
                    local_evaluations[candidate.id] = self._static_failure(candidate, error)
                known_sources[fingerprint] = candidate.id

        return tuple(candidates), local_evaluations, duplicate_targets

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
            executed=False,
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
            candidates_evaluated=sum(
                1 for evaluation in state.evaluations.values() if evaluation.executed
            ),
            active_islands=len(state.active_islands),
            elite_count=len(elite_ids),
            novelty_count=len(state.novelty_records),
            state=state,
        )
