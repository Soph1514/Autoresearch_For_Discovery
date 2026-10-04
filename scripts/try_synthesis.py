"""Drive the scorer-synthesis review loop from the terminal, with real model calls.

Validates the part no test covers: whether a real model, given the frozen
protocol, writes a module that passes the static gate and the container probe.

    ANTHROPIC_API_KEY=... RESEARCH_MODEL=... PYTHONPATH=src \\
        .venv/bin/python scripts/try_synthesis.py

Needs Docker and the worker image. Each round makes three paid calls.

    docker build -t the-pigeon-holes/candidate-worker:v1 docker/worker
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from the_pigeon_holes.ui.storage import ArtifactStore  # noqa: E402
from the_pigeon_holes.ui.synthesis import (  # noqa: E402
    ReviewInput,
    SynthesisInput,
    apply_review,
    create_session,
    run_round,
    session_view,
)
from synthesis_fixture import FIXTURE  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=str(ROOT / "runs" / "synthesis-trial.sqlite3"))
    parser.add_argument("--max-tokens", type=int, default=400_000)
    return parser.parse_args()


def show(view: dict) -> None:
    print(f"\n{'=' * 78}\nround {view['round_index']}/{view['max_rounds']} · "
          f"{view['state']} · {view['budget']['spent_tokens']:,} tokens spent")
    if view["state_reason"]:
        print(f"  {view['state_reason']}")
    if not view["rounds"]:
        return
    current = view["rounds"][-1]
    critic = current["critic"] or {}
    print(f"{'-' * 78}\nCRITIC")
    if critic.get("chosen"):
        print(f"  recommends module {critic['chosen'].upper()}: {critic['justification']}")
        for label in ("key_differences", "residual_risks", "unresolved_ambiguities"):
            for item in critic.get(label) or ():
                print(f"  [{label}] {item}")
    else:
        print(f"  no recommendation: {critic.get('error')}")

    for slot, candidate in sorted(current["candidates"].items()):
        mark = " (recommended)" if slot == critic.get("chosen") else ""
        print(f"{'-' * 78}\nMODULE {slot.upper()}{mark} · {candidate['model']} "
              f"· {candidate['framing']}")
        if candidate["error"]:
            print(f"  NOT GENERATED: {candidate['error']}")
            continue
        if candidate["static_problems"]:
            print("  REJECTED BY THE GATE:")
            for problem in candidate["static_problems"]:
                print(f"    - {problem}")
        print("  claimed feasibility rules:")
        for rule in candidate["validity_rules"]:
            print(f"    - {rule}")
        print(f"  claimed objective: {candidate['objective_derivation']}")
        print(f"  metrics: {candidate['metric_names']} · arity {candidate['descriptor_arity']}")
        if candidate["reconciliation_notes"].strip():
            print(f"  conflicts vs Lean: {candidate['reconciliation_notes']}")
        print("  source:")
        for line in candidate["source_code"].splitlines():
            print(f"    | {line}")


def ask() -> tuple[str, str]:
    while True:
        answer = input("\naccept / reject / abandon > ").strip().lower()
        if answer in ("accept", "abandon"):
            return answer, ""
        if answer == "reject":
            feedback = input("why? (20+ chars, drives the next round) > ").strip()
            if len(feedback) >= 20:
                return answer, feedback
            print("  too short; the next round would get nothing useful.")
        else:
            print("  type accept, reject or abandon.")


async def main() -> int:
    args = parse_args()
    store = ArtifactStore(args.store)
    store.put("formalization", FIXTURE["id"], FIXTURE["artifact"])

    session = create_session(
        SynthesisInput(formalization_id=FIXTURE["id"], evaluation_suite_id="trial",
                       evaluation_cases=FIXTURE["cases"], seed_program=FIXTURE["seed"],
                       alignment_reviewed=True, max_tokens=args.max_tokens),
        FIXTURE["artifact"], store=store,
        unsupported_reason="local trial fixture: the compiler was not run")
    print(f"session {session['id']}  (store: {args.store})")

    while True:
        print("\nsynthesising two modules and asking the critic… (three paid calls)")
        current = await run_round(session["id"], store=store)
        view = session_view(current)
        show(view)
        if view["state"] != "awaiting_review":
            print(f"\nended: {view['state']} — {view['state_reason']}")
            return 1

        decision, feedback = ask()
        current = await asyncio.to_thread(
            apply_review, session["id"],
            ReviewInput(decision=decision, feedback=feedback,
                        round_index=view["round_index"]),
            store=store)
        view = session_view(current)
        if view["terminal"]:
            print(f"\n{view['state']}: {view['state_reason'] or ''}")
            if view["accepted"]:
                print(json.dumps(view["accepted"], indent=2))
                print("\nThe scorer is frozen and content-addressed. It is not proven "
                      "to match the statement.")
            else:
                print("Nothing was registered and no contract was created.")
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
