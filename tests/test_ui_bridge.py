"""Integration bridge tests use the real engine and explicit demo ports."""
import asyncio
import copy
import pytest
from the_pigeon_holes.evolution import GenerationFailure, TokenUsage
from the_pigeon_holes.ui.bridge import ActiveRunClock, LabRun
from the_pigeon_holes.ui.contracts import InvalidControlTransition


def test_active_run_clock_excludes_fully_paused_time():
    current = [10.0]
    clock = ActiveRunClock(lambda: current[0])
    started = clock()
    current[0] += 2.0
    clock.pause()
    current[0] += 100.0
    assert clock() - started == 2.0
    clock.resume()
    current[0] += 3.0
    assert clock() - started == 5.0


def test_real_engine_publishes_lineage_evidence_and_ordered_events():
    async def scenario():
        run = LabRun(delay=0)
        await run.run()
        snapshot = run.snapshot
        assert snapshot['schemaVersion'] == 1
        assert snapshot['run']['status'] == 'completed'
        assert len(snapshot['ideas']) > 1
        assert len(snapshot['experiments']) == len(snapshot['ideas'])
        ids = {idea['id'] for idea in snapshot['ideas']}
        assert all(set(i['parents']) <= ids for i in snapshot['ideas'])
        assert all(set(i['inspirations']) <= ids for i in snapshot['ideas'])
        invalid = {e['ideaId'] for e in snapshot['experiments'] if not e['valid']}
        assert invalid
        assert max(e["metrics"]["poa"] for e in snapshot["experiments"] if e["valid"]) == pytest.approx(4 / 3)
        assert all(e['ideaId'] not in invalid for e in snapshot['elites'] if e['current'])
        assert [e['sequence'] for e in run.events] == list(range(1, snapshot['sequence']+1))
        assert any(e['niche'] == 'Global best' for e in snapshot['elites'])
        first = copy.deepcopy(run.events[0])
        run.log('test', 'later event')
        assert first == run.events[0]
    asyncio.run(scenario())


def test_generation_failures_and_control_acknowledgements_are_explicit():
    run = LabRun(delay=0)
    run.generation_failed(GenerationFailure(
        request_id="request-7",
        generation=2,
        error="provider unavailable",
        usage=TokenUsage(11, 3),
        prompt="private generation prompt",
    ))

    assert run.snapshot["generationFailures"] == [{
        "requestId": "request-7",
        "generation": 2,
        "error": "provider unavailable",
        "inputTokens": 11,
        "outputTokens": 3,
    }]
    acknowledgement = run.pause()
    assert acknowledgement == {
        "schemaVersion": 1,
        "runId": run.id,
        "action": "pause",
        "applied": True,
        "status": "pausing",
    }
    assert run.pause()["applied"] is False
    assert run.resume()["status"] == "running"
    with pytest.raises(InvalidControlTransition, match="cannot resume"):
        run.snapshot["run"]["status"] = "completed"
        run.resume()


def test_pause_at_batch_boundary_and_stop():
    async def scenario():
        run = LabRun(delay=.01)
        run.pause()
        run.task = asyncio.create_task(run.run())
        for _ in range(100):
            if run.snapshot['run']['status'] == 'paused':
                break
            await asyncio.sleep(.01)
        assert run.snapshot['run']['status'] == 'paused'
        assert len(run.snapshot['ideas']) == 1
        run.resume()
        await asyncio.sleep(.015)
        run.stop()
        await run.task
        assert run.snapshot['run']['status'] == 'stopped'
        assert not any(e['status'] == 'running' for e in run.snapshot['experiments'])
    asyncio.run(scenario())


def test_stopped_run_summary_retains_verified_winner(monkeypatch):
    from the_pigeon_holes.ui import api

    async def scenario():
        run = LabRun(delay=0)
        await run.run()
        expected = run.outcome['best_evaluation']['metrics']
        winner = run.outcome['best_candidate']['id']
        run.outcome = None
        run.snapshot['run']['status'] = 'stopped'
        monkeypatch.setattr(api, 'get_run', lambda _: run)
        summary = api.run_summary(run.id)
        assert summary['best_candidate_id'] == winner
        assert summary['best_metrics'] == expected
        assert run.snapshot['run']['status'] == 'stopped'
    asyncio.run(scenario())
