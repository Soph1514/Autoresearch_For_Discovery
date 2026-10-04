"""Checking Lean with the local pinned project instead of the hosted service."""

import asyncio
import shutil

import pytest

from the_pigeon_holes.ui.formalization import (
    FormalizationInput,
    HostedTools,
    LocalTools,
    default_tools,
    prepare,
)

PAIRS = """\
def IsFeasible (items : List (Nat × Nat)) (capacity : Nat) (chosen : List Nat) : Prop :=
  chosen.length = items.length ∧ ∀ x ∈ chosen, x = 0 ∨ x = 1
"""


@pytest.fixture(scope="module")
def lean_available():
    if shutil.which("lake") is None:
        pytest.skip("local Lean/mathlib required")
    return True


def test_hosted_tools_stay_the_default(monkeypatch):
    """Deployed behaviour must not change because a local project exists."""
    monkeypatch.delenv("RESEARCH_LOCAL_LEAN", raising=False)
    assert isinstance(default_tools(), HostedTools)
    monkeypatch.setenv("RESEARCH_LOCAL_LEAN", "1")
    assert isinstance(default_tools(), LocalTools)


@pytest.mark.parametrize("source, fragment", [
    ("theorem t : 1 = 1 := by sorry\n", "placeholder"),
    ("axiom cheat : False\n", "placeholder"),
    ("#eval IO.println \"x\"\n", "placeholder"),
    ("def x : Nat := 1\n" + "-- pad\n" * 20000, "exceeds 32000"),
])
def test_unsafe_or_oversized_sources_are_refused_without_running_lean(source, fragment):
    """The admission policy must not depend on Lean being installed."""
    result = asyncio.run(LocalTools().check(source))
    assert result["valid"] is False
    assert fragment in result["diagnostics"]
    assert "check_artifact" not in result


def test_a_missing_lake_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    result = asyncio.run(LocalTools().check("def x : Nat := 1\n"))
    assert result["valid"] is False
    assert "Local Lean unavailable" in result["diagnostics"]


def test_local_generation_and_fidelity_say_what_is_missing():
    with pytest.raises(RuntimeError, match="cannot generate"):
        asyncio.run(LocalTools().generate("a problem"))
    with pytest.raises(RuntimeError, match="no fidelity model"):
        asyncio.run(LocalTools().score("a problem", "def x : Nat := 1"))


def test_invalid_local_formalization_reports_repair_limit_without_hosted_calls():
    body = FormalizationInput(mode="formal", problem="Prove the claim.",
                              lean="theorem t : True := by sorry")
    with pytest.raises(RuntimeError, match="Local Lean mode cannot repair"):
        asyncio.run(prepare(body, tools=LocalTools()))


def test_a_real_check_records_provenance_the_contract_gate_accepts(lean_available):
    import hashlib

    result = asyncio.run(LocalTools().check(PAIRS))

    assert result["valid"] is True, result["diagnostics"]
    artifact = result["check_artifact"]
    assert artifact["source_sha256"] == hashlib.sha256(PAIRS.encode()).hexdigest()
    assert artifact["exit_code"] == 0
    # prepare_contract requires all four to be truthy.
    assert all(artifact[key] for key in ("toolchain", "dependencies", "command", "lean_version"))
    assert artifact["checker"] == "local"


def test_a_broken_statement_fails_with_lean_s_own_diagnostics(lean_available):
    result = asyncio.run(LocalTools().check('def broken : Nat := "not a nat"\n'))

    assert result["valid"] is False
    assert "type mismatch" in result["diagnostics"]


def test_formal_mode_completes_without_any_hosted_service(lean_available):
    """The whole preparation step, offline: checked Lean, no generator, no fidelity."""
    body = FormalizationInput(mode="formal", problem="Pick pairs under capacity.", lean=PAIRS)

    result = asyncio.run(prepare(body, tools=LocalTools()))

    assert result["lean_checked"] is True
    assert result["generator"] == "user"
    # No fidelity model locally, so it degrades to 'review' rather than claiming
    # acceptance, which keeps the alignment acknowledgement required downstream.
    assert result["status"] == "review"
    assert result["fidelity"] is None
    assert "Fidelity service unavailable" in result["fidelity_error"]
