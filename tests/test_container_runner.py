"""Sandbox flags for candidate containers. Pinned so they cannot be weakened silently."""

from the_pigeon_holes.execution.container_runner import ContainerLimits, run_arguments


def test_sandbox_flags_are_all_present():
    args = run_arguments("candidate-test", ContainerLimits(memory_mb=128, timeout_seconds=5), "img")
    flags = " ".join(args)
    for required in (
        "--network none",
        "--read-only",
        "--memory 128m",
        "--memory-swap 128m",
        "--pids-limit 64",
        "--user 65534:65534",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--rm",
    ):
        assert required in flags, required
    assert args[-1] == "img"


def test_memory_swap_matches_memory_so_no_swap_is_used():
    args = run_arguments("n", ContainerLimits(memory_mb=64, timeout_seconds=1), "img")
    assert args[args.index("--memory") + 1] == args[args.index("--memory-swap") + 1]
