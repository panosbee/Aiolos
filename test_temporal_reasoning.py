"""
Tests for P3 Temporal Reasoning Engine.

Covers:
  1. TemporalObservation creation + serialization
  2. RecurringPattern creation + aggregation
  3. Pattern key normalization (event name dedup)
  4. Observation recording + auto-aggregation
  5. Precursor matching (signal fingerprint comparison)
  6. Sequence A→B detection
  7. Digest generation
  8. Persistence (save/load roundtrip)
  9. Window boundary calculation
  10. Topic extraction utility
"""

import json
import os
import sys
import time
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from xdart.phases.temporal_reasoning import (
    TemporalReasoningEngine,
    TemporalObservation,
    RecurringPattern,
    PendingSequence,
    _extract_simple_topics,
    MIN_OBSERVATIONS,
    PRECURSOR_MATCH_THRESHOLD,
)


# ── Helpers ──

def _make_observation(
    event_name: str = "FOMC Decision",
    category: str = "central_bank",
    window: str = "pre_3d",
    domains: list | None = None,
    topics: list | None = None,
    entities: list | None = None,
    signal_count: int = 25,
) -> TemporalObservation:
    return TemporalObservation(
        timestamp=time.time(),
        event_name=event_name,
        event_category=category,
        window=window,
        signal_domains=domains or ["ECONOMIC", "MARKET"],
        signal_topics=topics or ["interest", "rate", "federal", "reserve", "inflation"],
        signal_entities=entities or ["Federal Reserve", "Jerome Powell"],
        signal_count=signal_count,
        headline_sample=["Fed expected to hold rates", "Markets brace for FOMC"],
        market_context={"VIX": {"price": 18.5, "change_pct": 2.3}},
    )


def _make_engine(
    with_calendar: bool = False,
    persist_path: str | None = None,
) -> TemporalReasoningEngine:
    """Create engine with mocked LLM and optional calendar."""
    mock_llm = MagicMock()
    mock_llm.call_json.return_value = {
        "description": "Pre-FOMC anxiety: VIX rises and gold spikes as markets hedge",
        "confidence": 0.72,
        "key_signals": ["VIX", "gold", "rate uncertainty"],
        "typical_sequence": "VIX starts rising 3 days before, gold follows 1 day before",
        "reasoning": "Consistent pattern across 5 observations",
    }

    mock_calendar = None
    if with_calendar:
        mock_calendar = MagicMock()
        mock_calendar.get_upcoming_events.return_value = [
            {
                "name": "FOMC Decision",
                "category": "central_bank",
                "date": (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d"),
                "days_until": 3,
            }
        ]
        mock_calendar._curated_events = [
            {
                "name": "FOMC Decision",
                "category": "central_bank",
                "date": (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d"),
            }
        ]
        mock_calendar._dynamic_events = []

    engine = TemporalReasoningEngine(llm=mock_llm, calendar=mock_calendar)

    # Override persist paths to temp
    if persist_path:
        import xdart.phases.temporal_reasoning as mod
        mod._PERSIST_PATH = Path(persist_path)
        mod._JOURNAL_PATH = Path(persist_path.replace(".json", "_journal.jsonl"))

    return engine


# ═══════════════════════════════════════════════════════════════
#  TESTS
# ═══════════════════════════════════════════════════════════════

def test_01_observation_serialization():
    """TemporalObservation roundtrip to/from dict."""
    obs = _make_observation()
    d = obs.to_dict()
    assert d["event_name"] == "FOMC Decision"
    assert d["window"] == "pre_3d"
    assert d["signal_count"] == 25
    assert "Federal Reserve" in d["signal_entities"]

    restored = TemporalObservation.from_dict(d)
    assert restored.event_name == obs.event_name
    assert restored.signal_count == obs.signal_count
    assert restored.signal_entities == obs.signal_entities
    print("  ✓ test_01 PASSED — Observation serialization roundtrip")


def test_02_pattern_serialization():
    """RecurringPattern roundtrip to/from dict."""
    obs1 = _make_observation()
    obs2 = _make_observation(signal_count=30, topics=["interest", "rate", "bond", "yield"])

    pattern = RecurringPattern(
        pattern_id="fomc decision__central_bank__pre_3d",
        pattern_type="pre_event",
        anchor_event="FOMC Decision",
        anchor_category="central_bank",
        window="pre_3d",
        description="Pre-FOMC VIX spike pattern",
        observations=[obs1, obs2],
        avg_signal_count=27.5,
        typical_domains=["ECONOMIC", "MARKET"],
        typical_topics=["interest", "rate", "federal"],
        typical_entities=["Federal Reserve", "Jerome Powell"],
        confidence=0.65,
        last_matched=0.0,
        times_predicted=3,
        times_correct=2,
        created_at=time.time(),
    )

    d = pattern.to_dict()
    assert d["pattern_id"] == "fomc decision__central_bank__pre_3d"
    assert len(d["observations"]) == 2
    assert d["confidence"] == 0.65

    restored = RecurringPattern.from_dict(d)
    assert restored.pattern_id == pattern.pattern_id
    assert restored.observation_count == 2
    assert restored.accuracy == 2 / 3
    print("  ✓ test_02 PASSED — Pattern serialization roundtrip")


def test_03_pattern_key_normalization():
    """Pattern keys strip year suffixes and qualifiers."""
    engine = _make_engine()

    key1 = engine._pattern_key("FOMC Decision", "central_bank", "pre_3d")
    key2 = engine._pattern_key("FOMC Decision 2025", "central_bank", "pre_3d")
    key3 = engine._pattern_key("FOMC Decision + Projections", "central_bank", "pre_3d")
    key4 = engine._pattern_key("FOMC Decision", "central_bank", "post_1d")

    assert key1 == key2, f"Year suffix not stripped: {key1} != {key2}"
    assert key1 == key3, f"Qualifier not stripped: {key1} != {key3}"
    assert key1 != key4, "Different windows should produce different keys"
    print("  ✓ test_03 PASSED — Pattern key normalization")


def test_04_event_name_matching():
    """Event name matching handles variations."""
    engine = _make_engine()
    assert engine._event_name_matches("FOMC Decision", "FOMC Decision")
    assert engine._event_name_matches("FOMC Decision", "FOMC Decision 2026")
    assert engine._event_name_matches("FOMC Decision", "FOMC Decision + Projections")
    assert not engine._event_name_matches("FOMC Decision", "ECB Decision")
    print("  ✓ test_04 PASSED — Event name matching")


def test_05_add_observation_creates_pattern():
    """Adding observations auto-creates pattern slots."""
    engine = _make_engine()
    assert len(engine._patterns) == 0

    obs = _make_observation()
    engine._add_observation(obs)

    assert len(engine._patterns) == 1
    p = engine._patterns[0]
    assert p.anchor_event == "FOMC Decision"
    assert p.observation_count == 1
    assert not p.is_mature  # needs MIN_OBSERVATIONS

    # Add more to same pattern
    for _ in range(MIN_OBSERVATIONS - 1):
        engine._add_observation(_make_observation())

    assert p.observation_count == MIN_OBSERVATIONS
    assert p.is_mature
    print("  ✓ test_05 PASSED — Observation creates and populates pattern")


def test_06_aggregate_recomputation():
    """Aggregates (avg_signal_count, typical_domains, confidence) update correctly."""
    engine = _make_engine()

    # 4 observations with varying data
    observations = [
        _make_observation(signal_count=20, domains=["ECONOMIC", "MARKET"], topics=["rate", "inflation"]),
        _make_observation(signal_count=30, domains=["ECONOMIC", "SECURITY"], topics=["rate", "oil"]),
        _make_observation(signal_count=25, domains=["ECONOMIC", "MARKET"], topics=["rate", "bonds"]),
        _make_observation(signal_count=35, domains=["ECONOMIC", "MARKET"], topics=["rate", "vix"]),
    ]

    for obs in observations:
        engine._add_observation(obs)

    p = engine._patterns[0]
    assert p.observation_count == 4
    assert abs(p.avg_signal_count - 27.5) < 0.1
    assert "ECONOMIC" in p.typical_domains  # appears in all 4
    assert p.confidence > 0.0  # should have some confidence with 4 obs
    assert p.is_mature  # 4 >= MIN_OBSERVATIONS (3)
    print(f"  ✓ test_06 PASSED — Aggregates correct (avg={p.avg_signal_count:.1f}, conf={p.confidence:.2f})")


def test_07_precursor_match_scoring():
    """Precursor match score calculation."""
    engine = _make_engine()

    # Create a mature pattern
    pattern = RecurringPattern(
        pattern_id="test",
        pattern_type="pre_event",
        anchor_event="FOMC Decision",
        anchor_category="central_bank",
        window="pre_3d",
        description="Test pattern",
        observations=[_make_observation() for _ in range(5)],
        avg_signal_count=25.0,
        typical_domains=["ECONOMIC", "MARKET"],
        typical_topics=["interest", "rate", "inflation", "federal", "reserve"],
        typical_entities=["Federal Reserve", "Jerome Powell"],
        confidence=0.7,
        last_matched=0.0,
        times_predicted=0,
        times_correct=0,
        created_at=time.time(),
    )

    # High match — same domains, topics, entities
    current_high = {
        "domains": ["ECONOMIC", "MARKET", "TECHNOLOGY"],
        "topics": ["interest", "rate", "inflation", "bond"],
        "entities": ["Federal Reserve", "Treasury"],
        "signal_count": 22,
    }
    score_high = engine._compute_precursor_match(pattern, current_high)
    assert score_high > PRECURSOR_MATCH_THRESHOLD, f"High match score too low: {score_high}"

    # Low match — different domains, topics, entities
    current_low = {
        "domains": ["SECURITY", "SOCIAL"],
        "topics": ["military", "conflict", "troops", "border"],
        "entities": ["NATO", "Russia"],
        "signal_count": 40,
    }
    score_low = engine._compute_precursor_match(pattern, current_low)
    assert score_low < PRECURSOR_MATCH_THRESHOLD, f"Low match score too high: {score_low}"

    assert score_high > score_low
    print(f"  ✓ test_07 PASSED — Precursor match: high={score_high:.3f}, low={score_low:.3f}")


def test_08_sequence_detection():
    """A→B sequence watch and completion."""
    engine = _make_engine()

    # Start watching for B
    seq_id = engine.start_sequence_watch(
        event_a_headline="US imposes new sanctions on Iran",
        event_a_topics={"sanctions", "iran", "oil", "exports"},
        event_a_entities={"Iran", "United States"},
        event_a_domains={"SECURITY", "ECONOMIC"},
        expected_b_topics={"retaliation", "iran", "strait", "hormuz"},
        expected_b_entities={"Iran", "IRGC"},
        max_delay_days=7,
    )
    assert seq_id is not None
    assert len(engine._pending_sequences) == 1
    assert not engine._pending_sequences[0].observed_b

    # Signal that doesn't match
    matches = engine.check_sequence_signal(
        headline="Japan GDP growth exceeds expectations",
        topics={"japan", "gdp", "growth", "economy"},
        entities={"Japan", "Bank of Japan"},
    )
    assert len(matches) == 0

    # Signal that matches (Iran retaliation)
    matches = engine.check_sequence_signal(
        headline="Iran threatens to close Strait of Hormuz in retaliation",
        topics={"iran", "strait", "hormuz", "retaliation", "oil"},
        entities={"Iran", "IRGC", "Strait of Hormuz"},
    )
    assert len(matches) == 1
    assert "delay_hours" in matches[0]
    assert matches[0]["topic_overlap"] >= 2
    print(f"  ✓ test_08 PASSED — Sequence A→B detection (delay={matches[0]['delay_hours']:.1f}h)")


def test_09_digest_generation():
    """Digest generates correct format with mature patterns."""
    engine = _make_engine(with_calendar=True)

    # Add a mature pattern
    for i in range(5):
        engine._add_observation(_make_observation(
            topics=["interest", "rate", "federal", "reserve", "inflation", "vix"],
        ))

    # Force learn
    p = engine._patterns[0]
    p.description = "Pre-FOMC VIX spike: volatility increases as markets hedge rate uncertainty"
    p.confidence = 0.75

    # Mock current signal snapshot
    engine.perception_db = MagicMock()
    engine.perception_db.get_recent_events.return_value = [
        {"domain": "ECONOMIC", "headline": "Fed rate decision looms", "collected_at": datetime.now(timezone.utc).isoformat()},
        {"domain": "MARKET", "headline": "VIX rises ahead of FOMC", "collected_at": datetime.now(timezone.utc).isoformat()},
    ] * 5

    engine._last_digest_ts = 0  # force regeneration
    digest = engine.get_temporal_digest()

    assert "TEMPORAL INTELLIGENCE" in digest
    print(f"  ✓ test_09 PASSED — Digest generation ({len(digest)} chars)")
    if digest:
        # Print first few lines for inspection
        for line in digest.split("\n")[:4]:
            if line.strip():
                print(f"    {line.strip()[:80]}")


def test_10_persistence_roundtrip():
    """Save and load state preserves patterns and sequences."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persist_path = os.path.join(tmpdir, "temporal_test.json")
        journal_path = os.path.join(tmpdir, "temporal_test_journal.jsonl")

        import xdart.phases.temporal_reasoning as mod
        orig_persist = mod._PERSIST_PATH
        orig_journal = mod._JOURNAL_PATH
        mod._PERSIST_PATH = Path(persist_path)
        mod._JOURNAL_PATH = Path(journal_path)

        try:
            engine = _make_engine()
            # Add observations
            for _ in range(4):
                engine._add_observation(_make_observation())
            # Add sequence
            engine._pending_sequences.append(PendingSequence(
                sequence_id="seq_test",
                event_a_topics={"sanctions", "iran"},
                event_a_entities={"Iran"},
                event_a_domains={"SECURITY"},
                event_a_headline="Test sanctions",
                event_a_ts=time.time(),
                expected_b_topics={"retaliation"},
                expected_b_entities={"Iran"},
                max_delay_days=7,
                observed_b=False,
                created_at=time.time(),
            ))
            engine._total_observations = 4
            engine._save_state()

            # Verify file exists
            assert Path(persist_path).exists()

            # Load into new engine
            engine2 = TemporalReasoningEngine(llm=None, calendar=None)
            assert len(engine2._patterns) == 1
            assert engine2._patterns[0].observation_count == 4
            assert len(engine2._pending_sequences) == 1
            assert engine2._pending_sequences[0].sequence_id == "seq_test"
            assert engine2._total_observations == 4

            print("  ✓ test_10 PASSED — Persistence roundtrip")
        finally:
            mod._PERSIST_PATH = orig_persist
            mod._JOURNAL_PATH = orig_journal


def test_11_topic_extraction():
    """Simple topic extraction filters stop words."""
    topics = _extract_simple_topics("The Federal Reserve is expected to raise interest rates by 25 basis points")
    assert "federal" in topics
    assert "reserve" in topics
    assert "interest" in topics
    assert "rates" in topics
    assert "the" not in topics
    assert "is" not in topics
    assert "to" not in topics
    print(f"  ✓ test_11 PASSED — Topic extraction: {topics}")


def test_12_window_boundaries():
    """Window boundary calculation returns correct ranges."""
    engine = _make_engine()
    event_date = datetime(2025, 3, 19, 18, 0, tzinfo=timezone.utc)

    start, end = engine._window_boundaries("pre_3d", event_date)
    assert start == event_date - timedelta(days=3)
    assert end == event_date - timedelta(days=1)

    start, end = engine._window_boundaries("post_1d", event_date)
    assert start == event_date
    assert end == event_date + timedelta(days=1)

    start, end = engine._window_boundaries("pre_1d", event_date)
    assert start == event_date - timedelta(days=1)
    assert end == event_date
    print("  ✓ test_12 PASSED — Window boundaries correct")


# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        test_01_observation_serialization,
        test_02_pattern_serialization,
        test_03_pattern_key_normalization,
        test_04_event_name_matching,
        test_05_add_observation_creates_pattern,
        test_06_aggregate_recomputation,
        test_07_precursor_match_scoring,
        test_08_sequence_detection,
        test_09_digest_generation,
        test_10_persistence_roundtrip,
        test_11_topic_extraction,
        test_12_window_boundaries,
    ]

    print(f"\n{'='*60}")
    print(f"  P3 TEMPORAL REASONING — {len(tests)} tests")
    print(f"{'='*60}\n")

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  ✗ {test_fn.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed}/{len(tests)} passed, {failed} failed")
    print(f"{'='*60}\n")

    sys.exit(1 if failed else 0)
