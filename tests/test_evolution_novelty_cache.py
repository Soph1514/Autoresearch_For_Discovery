"""Feature-cache behavior for repeated novelty comparisons."""

from the_pigeon_holes.evolution.models import EvolutionOperator, ProgramCandidate
from the_pigeon_holes.evolution.novelty import NoveltyFeatureCache, candidate_distance


def _candidate(identity: str, source: str) -> ProgramCandidate:
    return ProgramCandidate(
        id=identity, generation=0, island_id=None,
        operator=EvolutionOperator.RESTART, parent_ids=(), inspiration_ids=(),
        hypothesis="h", predicted_effect="p", falsification_condition="f",
        mechanism_tags=("constructive",), source_code=source,
        source_fingerprint=identity,
    )


def test_feature_cache_parses_each_source_only_once(monkeypatch):
    from the_pigeon_holes.evolution import novelty

    calls = 0
    original = novelty.ast.parse

    def counting_parse(source):
        nonlocal calls
        calls += 1
        return original(source)

    monkeypatch.setattr(novelty.ast, "parse", counting_parse)
    cache = NoveltyFeatureCache()
    left = _candidate("left", "def solve(x: int) -> int:\n    return x + 1\n")
    right = _candidate("right", "def solve(x: int) -> int:\n    return x * 2\n")

    for _ in range(5):
        candidate_distance(
            left, None, right, None,
            behavior_weight=0.7, lineage_weight=0.1,
            feature_cache=cache,
        )

    assert calls == 2
