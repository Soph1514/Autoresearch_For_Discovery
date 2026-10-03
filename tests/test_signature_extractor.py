"""Unit tests for Lean 4 to Python signature and Pydantic schema extraction."""

from unittest.mock import MagicMock
import pytest

from the_pigeon_holes.execution.signature_extractor import (
    ExtractedInterface,
    MetricGoal,
    OptimisationGoal,
    Parameter,
    extract_signature,
    verify_interface_syntax,
)


GOAL = OptimisationGoal(MetricGoal("value", "maximize"), "mean")


def test_interface_syntax_verification_valid():
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[Parameter(name="items", python_type="list[tuple[int, int]]")],
        return_type="list[bool]",
        signature_str="def solve(items: list[tuple[int, int]]) -> list[bool]:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    assert verify_interface_syntax(interface) is True


def test_interface_rejects_unknown_direction():
    with pytest.raises(ValueError, match="must be 'maximize' or 'minimize'"):
        MetricGoal("value", "largest")


def test_interface_syntax_verification_catches_wrong_function_name():
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[],
        return_type="int",
        signature_str="def other(x: int) -> int:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    with pytest.raises(ValueError, match="function name is 'other'"):
        verify_interface_syntax(interface)


def test_interface_syntax_verification_requires_function_named_solve():
    interface = ExtractedInterface(
        function_name="knapsack",
        parameters=[],
        return_type="int",
        signature_str="def knapsack() -> int:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    with pytest.raises(ValueError, match="must be 'solve'"):
        verify_interface_syntax(interface)


def test_interface_syntax_verification_catches_parameter_mismatch():
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[Parameter(name="items", python_type="list[int]")],
        return_type="int",
        signature_str="def solve(values: list[int]) -> int:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    with pytest.raises(ValueError, match="parameter names"):
        verify_interface_syntax(interface)


def test_interface_syntax_verification_catches_annotation_mismatch():
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[Parameter(name="items", python_type="list[int]")],
        return_type="int",
        signature_str="def solve(items: list[str]) -> int:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    with pytest.raises(ValueError, match="parameter 'items' is 'list\\[str\\]'"):
        verify_interface_syntax(interface)


def test_interface_syntax_verification_catches_return_mismatch():
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[],
        return_type="list[bool]",
        signature_str="def solve() -> int:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    with pytest.raises(ValueError, match="return annotation is 'int'"):
        verify_interface_syntax(interface)


def test_interface_syntax_verification_ignores_whitespace_in_types():
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[Parameter(name="items", python_type="list[ tuple[int,int] ]")],
        return_type="list[bool]",
        signature_str="def solve(items: list[tuple[int, int]]) -> list[bool]:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    assert verify_interface_syntax(interface) is True


@pytest.mark.parametrize("bad_name", ["from", "n'", "2x"])
def test_interface_syntax_verification_rejects_non_python_identifiers(bad_name):
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[Parameter(name=bad_name, python_type="int")],
        return_type="int",
        signature_str=f"def solve({bad_name}: int) -> int:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    with pytest.raises(ValueError, match="not a valid Python identifier"):
        verify_interface_syntax(interface)


def test_interface_syntax_verification_catches_duplicate_parameters():
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[Parameter(name="x", python_type="int"), Parameter(name="x", python_type="int")],
        return_type="int",
        signature_str="def solve(x: int, x: int) -> int:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    with pytest.raises(ValueError, match="duplicate parameter names"):
        verify_interface_syntax(interface)


def test_extract_signature_rejects_truncated_response():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.stop_reason = "max_tokens"
    mock_response.content = []
    mock_client.messages.create.return_value = mock_response
    with pytest.raises(RuntimeError, match="truncated"):
        extract_signature("def solve (n : Nat) : Nat", model="claude-sonnet-5-5", client=mock_client)


def test_interface_syntax_verification_catches_invalid_syntax():
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[],
        return_type="int",
        signature_str="def solve(broken syntax here",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    with pytest.raises(ValueError, match="failed Python syntax verification"):
        verify_interface_syntax(interface)


def test_interface_code_generation_with_pydantic_classes():
    pydantic_code = (
        "class Task(BaseModel):\n"
        "    machine_id: int\n"
        "    duration: int\n\n"
        "class Job(BaseModel):\n"
        "    tasks: list[Task]\n"
        "Job.model_rebuild()"
    )
    interface = ExtractedInterface(
        function_name="solve",
        parameters=[
            Parameter(name="jobs", python_type="list[Job]"),
            Parameter(name="num_machines", python_type="int"),
        ],
        return_type="list[list[int]]",
        signature_str="def solve(jobs: list[Job], num_machines: int) -> list[list[int]]:",
        pydantic_classes_code=pydantic_code,
        optimisation_goal=GOAL,
    )

    assert verify_interface_syntax(interface) is True
    full_code = interface.to_interface_code()
    assert "class Task(BaseModel):" in full_code
    assert "class Job(BaseModel):" in full_code
    assert "def solve(jobs: list[Job], num_machines: int) -> list[list[int]]:" in full_code

    # Execute and validate Pydantic functionality
    scope = {}
    exec(full_code, scope)
    TaskClass = scope["Task"]
    JobClass = scope["Job"]
    t = TaskClass(machine_id=1, duration=5)
    j = JobClass(tasks=[t])
    assert j.tasks[0].duration == 5


def test_extract_signature_via_llm_tool_call():
    """Verify that extract_signature invokes Claude with tool-use and returns ExtractedInterface."""
    mock_client = MagicMock()
    mock_tool_block = MagicMock()
    mock_tool_block.type = "tool_use"
    mock_tool_block.name = "submit_extracted_interface"
    mock_tool_block.input = {
        "function_name": "solve",
        "parameters": [
            {"name": "items", "python_type": "list[tuple[int, int]]"},
            {"name": "capacity", "python_type": "int"},
        ],
        "return_type": "list[bool]",
        "signature_str": "def solve(items: list[tuple[int, int]], capacity: int) -> list[bool]:",
        "pydantic_classes_code": "",
        "optimisation_goal": {"primary": {"name": "value", "direction": "maximize"}, "aggregation": "mean"},
    }
    mock_response = MagicMock()
    mock_response.content = [mock_tool_block]
    mock_client.messages.create.return_value = mock_response

    lean_code = "def solve (items : List (Nat × Nat)) (capacity : Nat) : List Bool"
    interface = extract_signature(lean_code, model="claude-sonnet-5-5", client=mock_client)

    assert isinstance(interface, ExtractedInterface)
    assert interface.function_name == "solve"
    assert len(interface.parameters) == 2
    assert interface.parameters[0].name == "items"
    assert interface.parameters[0].python_type == "list[tuple[int, int]]"
    assert interface.return_type == "list[bool]"
    assert verify_interface_syntax(interface) is True
    assert mock_client.messages.create.call_args.kwargs["model"] == "claude-sonnet-5-5"


def test_extract_signature_requires_model():
    with pytest.raises(TypeError):
        extract_signature("def solve (n : Nat) : Nat", client=MagicMock())
