"""Focused handoff check from contract preparation into evolution ports."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from the_pigeon_holes.evolution import (
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionLimits,
    EvolutionLoop,
    StopReason,
)
from the_pigeon_holes.llm import AnthropicGeneratorConfig, AnthropicProgramGenerator
from the_pigeon_holes.models.problem_contract import ResourceLimits, build_problem_contract


def _extractor_client():
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_extracted_interface"
    block.input = {
        "parameters": [{"name": "items", "python_type": "list[Item]"}],
        "return_type": "int",
        "signature_str": "def solve(items: list[Item]) -> int:",
        "pydantic_classes_code": (
            "class Item(BaseModel):\n"
            "    weight: int\n"
            "    label: str\n"
        ),
        "optimisation_goal": {
            "primary": {"name": "score", "direction": "maximize"},
            "aggregation": "mean",
        },
    }
    response = MagicMock(content=[block], stop_reason="tool_use")
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_structured_contract_reaches_generation_and_evaluation_ports():
    secret_label = "benchmark-value-not-for-generator"
    contract = build_problem_contract(
        natural_language_spec="Choose from structured items.",
        lean_specification="structure Item where weight : Nat; label : String",
        seed_program="def solve(items: list[Item]) -> int:\n    return 0\n",
        evaluation_suite_id="structured-v1",
        evaluation_cases={
            "case-a": {"items": [{"weight": 2, "label": secret_label}]},
            "case-b": {"items": [{"weight": 5, "label": "b"}]},
        },
        resource_limits=ResourceLimits(1.0, 5.0, 128, 100),
        evaluator_version="structured-evaluator-v1",
        model="test-model",
        client=_extractor_client(),
    )

    async def create_candidate(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        assert "class Item(BaseModel)" in prompt
        assert secret_label not in prompt
        block = SimpleNamespace(
            type="tool_use",
            name="submit_candidate",
            input={
                "hypothesis": "Count the supplied items.",
                "predicted_effect": "Return a finite score for every case.",
                "falsification_condition": "A case cannot be processed.",
                "mechanism_tags": ["count"],
                "source_code": (
                    "def solve(items: list[Item]) -> int:\n"
                    "    return len(items)\n"
                ),
            },
        )
        return SimpleNamespace(
            content=[block],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=4, output_tokens=6),
        )

    provider = SimpleNamespace(
        messages=SimpleNamespace(create=create_candidate),
    )
    generator = AnthropicProgramGenerator(
        AnthropicGeneratorConfig(
            model="test-model",
            max_attempts=1,
            max_concurrency=1,
        ),
        client=provider,
    )

    class Evaluator:
        async def evaluate(self, candidates, problem):
            assert problem is contract
            assert problem.interface.supporting_types_code.startswith("class Item")
            cases = [case.materialize_inputs() for case in problem.evaluation_suite.cases]
            assert cases[0]["items"][0]["label"] == secret_label
            return tuple(
                CandidateEvaluation(
                    candidate.id,
                    valid=True,
                    metrics={"score": 1.0},
                    passing_cases=2,
                    total_cases=2,
                )
                for candidate in candidates
            )

    outcome = asyncio.run(
        EvolutionLoop(
            config=EvolutionConfig(
                min_islands=1,
                max_islands=1,
                offspring_per_island=1,
                max_batch_size=1,
                max_tokens_per_request=10,
            ),
            limits=EvolutionLimits(max_tokens=10),
            generator=generator,
            evaluator=Evaluator(),
        ).run(contract)
    )

    assert outcome.stop_reason is StopReason.TOKEN_LIMIT
    assert outcome.candidates_evaluated == 2
