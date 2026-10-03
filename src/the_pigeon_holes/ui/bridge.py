"""Translate evolution state into ordered UI records; leave the engine intact."""
import asyncio
import copy
import time
from datetime import datetime, timezone
from uuid import uuid4
from the_pigeon_holes.evolution.engine import EvolutionEngine
from the_pigeon_holes.evolution.loop import EvolutionLoop
from the_pigeon_holes.evolution.models import EvolutionConfig, EvolutionLimits
from .demo import demo_contract, DemoGenerator, DemoEvaluator


def now():
    return datetime.now(timezone.utc).isoformat()


class ActiveRunClock:
    """Monotonic clock whose value does not advance while fully paused."""

    def __init__(self, source=time.monotonic):
        self.source = source
        self.paused_at = None
        self.paused_seconds = 0.0

    def __call__(self):
        current = self.source()
        current_pause = 0.0 if self.paused_at is None else current - self.paused_at
        return current - self.paused_seconds - current_pause

    def pause(self):
        if self.paused_at is None:
            self.paused_at = self.source()

    def resume(self):
        if self.paused_at is not None:
            self.paused_seconds += self.source() - self.paused_at
            self.paused_at = None


class LabRun:
    def __init__(self, delay=.8):
        self.delay = delay
        self.wake = asyncio.Event()
        self.gate = asyncio.Event()
        self.gate.set()
        self.active_clock = ActiveRunClock()
        self.events = []
        self.task = None
        self.snapshot = {"run": {
            "id": str(uuid4()), "title": "How inefficient can selfish routing be?",
            "status": "running", "startedAt": now(), "metricName": "poa", "direction": "maximize",
            "backend": "python-demo", "contract": {
                "evaluationSuiteId": "pigou-unit-demand",
                "evaluatorVersion": "pigou-analytic-demo-v1",
                "signature": "def solve() -> float:", "formalVerification": "Not performed",
                "maxTokens": 160, "maxTimeSeconds": 60,
            }}, "ideas": [], "experiments": [], "elites": [], "logs": [], "sequence": 0}

    @property
    def id(self):
        return self.snapshot["run"]["id"]

    def emit(self, kind, payload):
        payload = copy.deepcopy(payload)
        self.snapshot["sequence"] += 1
        event = {"schemaVersion": 1, "runId": self.id, "eventId": str(uuid4()),
                 "sequence": self.snapshot["sequence"], "timestamp": now(), "type": kind, "payload": payload}
        if kind == "run_status_changed":
            self.snapshot["run"].update(payload)
        else:
            key, identity = {"idea_created": ("ideas", "id"), "experiment_updated": ("experiments", "id"),
                             "elite_changed": ("elites", "niche"), "log_added": ("logs", "id")}[kind]
            records = self.snapshot[key]
            index = next((i for i, record in enumerate(records) if record[identity] == payload[identity]
                          and (kind != "elite_changed" or record["ideaId"] == payload["ideaId"])), None)
            if index is None:
                records.append(payload)
            else:
                records[index] = payload
        self.events.append(event)
        self.wake.set()

    def log(self, category, message, idea_id=None):
        self.emit("log_added", {"id": str(uuid4()), "timestamp": now(), "category": category,
                                "message": message, "ideaId": idea_id})

    def candidate(self, candidate):
        if any(i["id"] == candidate.id for i in self.snapshot["ideas"]):
            return
        operation = {"mutate": "mutation", "crossover": "merge", "repair": "repair",
                     "develop_novelty": "exploration", "restart": "exploration"}[candidate.operator.value]
        if candidate.generation == 0:
            operation = "seed"
        self.emit("idea_created", {"id": candidate.id, "title": candidate.hypothesis[:90],
            "description": candidate.hypothesis, "parents": list(candidate.parent_ids),
            "inspirations": list(candidate.inspiration_ids), "operation": operation,
            "inactive": False, "island": candidate.island_id, "generation": candidate.generation,
            "predictedEffect": candidate.predicted_effect, "falsificationCondition": candidate.falsification_condition,
            "sourceCode": candidate.source_code})
        self.emit("experiment_updated", {"id": "eval-"+candidate.id, "ideaId": candidate.id,
            "status": "running", "valid": None, "metrics": {}, "feedback": "Evaluation pending."})
        self.log("candidate", f"{candidate.operator.value}: {candidate.hypothesis}", candidate.id)

    def evaluation(self, result):
        record = {"id": "eval-"+result.candidate_id, "ideaId": result.candidate_id,
            "status": "completed" if result.valid else "failed", "valid": result.valid,
            "metrics": dict(result.metrics), "feedback": "; ".join(result.failure_reasons) if not result.valid
            else "Analytic Pigou formula checked; no Python execution or Lean proof.",
            "passingCases": result.passing_cases, "totalCases": result.total_cases}
        existing = next((e for e in self.snapshot["experiments"] if e["id"] == record["id"]), None)
        if existing == record:
            return
        self.emit("experiment_updated", record)
        self.log("verify" if result.valid else "failure", record["feedback"], result.candidate_id)

    def state(self, state):
        # Engine decides elites and islands. Publish invalid/static-rejected candidates too.
        for candidate in state.candidates.values():
            self.candidate(candidate)
        for evaluation in state.evaluations.values():
            self.evaluation(evaluation)
        memberships = {island.id: island.elite_id for island in state.active_islands.values() if island.elite_id}
        if state.global_best_id:
            memberships["Global best"] = state.global_best_id
        for old in list(self.snapshot["elites"]):
            if old["current"] and memberships.get(old["niche"]) != old["ideaId"]:
                self.emit("elite_changed", {**old, "current": False})
        for niche, candidate_id in memberships.items():
            record = {"ideaId": candidate_id, "experimentId": "eval-"+candidate_id, "niche": niche, "current": True}
            if record not in self.snapshot["elites"]:
                self.emit("elite_changed", record)
        dormant = set(state.dormant_islands)
        for idea in list(self.snapshot["ideas"]):
            evaluation = state.evaluations.get(idea["id"])
            inactive = bool(evaluation and not evaluation.valid) or idea.get("island") in dormant
            if inactive != idea["inactive"]:
                self.emit("idea_created", {**idea, "inactive": inactive})
        self.log("generation", f"Generation {state.generation} recorded: {len(state.active_islands)} active islands, {len(state.dormant_islands)} dormant.")

    async def checkpoint(self):
        if not self.gate.is_set():
            self.active_clock.pause()
            self.emit("run_status_changed", {"status": "paused"})
            self.log("control", "Paused between batches; completed evidence retained.")
            try:
                await self.gate.wait()
            finally:
                self.active_clock.resume()

    def pause(self):
        if self.snapshot["run"]["status"] == "running":
            self.gate.clear()
            self.emit("run_status_changed", {"status": "pausing"})

    def resume(self):
        if self.snapshot["run"]["status"] in ("paused", "pausing"):
            self.gate.set()
            self.emit("run_status_changed", {"status": "running"})

    def stop(self):
        if self.task and not self.task.done():
            self.emit("run_status_changed", {"status": "stopping"})
            self.task.cancel()

    async def run(self):
        try:
            self.log("start", "Real evolution engine; deterministic demo generator and analytic demo evaluator. No LLM calls.")
            config = EvolutionConfig(min_islands=2, max_islands=4, max_batch_size=8, max_tokens_per_request=10)
            loop = EvolutionLoop(config=config, limits=EvolutionLimits(max_tokens=160, max_time_seconds=60),
                generator=DemoGenerator(self.checkpoint, self.log, self.delay),
                evaluator=DemoEvaluator(self.candidate, self.evaluation, self.delay),
                clock=self.active_clock)
            loop.engine = ObservedEngine(config, self.state)
            outcome = await loop.run(demo_contract())
            self.log("complete", f"Stopped: {outcome.stop_reason.value}; {outcome.tokens_used} demo tokens, {outcome.generations_completed} generations.")
            self.emit("run_status_changed", {"status": "completed", "endedAt": now()})
        except asyncio.CancelledError:
            for experiment in list(self.snapshot["experiments"]):
                if experiment["status"] == "running":
                    self.emit("experiment_updated", {**experiment, "status": "cancelled", "feedback": "Run stopped."})
            self.emit("run_status_changed", {"status": "stopped", "endedAt": now()})
        except Exception as error:
            self.log("error", str(error))
            self.emit("run_status_changed", {"status": "failed", "endedAt": now()})


class ObservedEngine(EvolutionEngine):
    """Observation only: policy and state transitions delegate to the original engine."""
    def __init__(self, config, publish):
        super().__init__(config)
        self.publish = publish

    def initialise(self, *args, **kwargs):
        state = super().initialise(*args, **kwargs)
        self.publish(state)
        return state

    def apply_generation(self, *args, **kwargs):
        state = super().apply_generation(*args, **kwargs)
        self.publish(state)
        return state
