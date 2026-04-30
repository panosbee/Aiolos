"""
Tests for P2 — HypothesisEngine (Persistent Hypotheses).

Tests:
  1. Hypothesis creation and duplicate detection
  2. Signal checking — trigger and outcome matching
  3. Trigger detection lifecycle (active → trigger_detected)
  4. Expiry handling
  5. Digest generation
  6. Stats tracking
  7. State persistence (save/load)
  8. Max active cap enforcement
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))


def _make_engine():
    """Create a minimal mock ProactiveEngine with HypothesisEngine."""
    from xdart.proactive import HypothesisEngine

    # Mock ProactiveEngine
    mock_engine = MagicMock()
    mock_engine.llm = MagicMock()
    mock_engine._mongo = None

    # Clean state files for testing
    test_state = Path("hypothesis_state_test.json")
    test_journal = Path("hypothesis_journal_test.json")
    for p in (test_state, test_journal):
        if p.exists():
            p.unlink()

    he = HypothesisEngine(mock_engine)
    # Override persist paths for isolation
    he._PERSIST_PATH = test_state
    he._JOURNAL_PATH = test_journal
    return he, mock_engine


def test_create_hypothesis():
    he, _ = _make_engine()
    hyp = he.create_hypothesis(
        hypothesis_text="IF Iran closes Strait of Hormuz THEN oil prices spike above $100 within 14 days",
        trigger_condition="Iran military action blocking Strait of Hormuz shipping",
        expected_outcome="Brent crude oil price exceeds $100 per barrel",
        trigger_keywords={"hormuz", "iran", "blockade", "strait"},
        outcome_keywords={"oil", "brent", "crude", "$100", "spike"},
        trigger_entities={"Iran", "Strait of Hormuz"},
        outcome_entities=set(),
        timeframe_days=14,
        confidence=0.6,
        source="user",
        domains=["SECURITY", "ECONOMIC"],
    )
    assert hyp is not None, "Hypothesis should be created"
    assert hyp.status == "active"
    assert hyp.id.startswith("hyp_")
    assert hyp.confidence == 0.6
    assert "hormuz" in hyp.trigger_keywords
    assert "oil" in hyp.outcome_keywords
    assert hyp.timeframe_days == 14
    print("  PASS: test_create_hypothesis")


def test_duplicate_detection():
    he, _ = _make_engine()
    hyp1 = he.create_hypothesis(
        hypothesis_text="IF China invades Taiwan THEN semiconductor prices triple within 30 days",
        trigger_condition="Chinese military assault on Taiwan",
        expected_outcome="Global semiconductor prices triple",
        trigger_keywords={"china", "taiwan", "invasion", "military"},
        outcome_keywords={"semiconductor", "chip", "prices", "triple"},
        timeframe_days=30,
        confidence=0.4,
        source="pattern",
    )
    assert hyp1 is not None

    # Near-duplicate (slightly different wording)
    hyp2 = he.create_hypothesis(
        hypothesis_text="IF China invades Taiwan THEN semiconductor chip prices triple within 30 days",
        trigger_condition="Chinese military assault on Taiwan",
        expected_outcome="Global semiconductor prices triple",
        trigger_keywords={"china", "taiwan", "invasion"},
        outcome_keywords={"semiconductor", "chip", "triple"},
        timeframe_days=30,
        confidence=0.5,
        source="pattern",
    )
    assert hyp2 is None, "Near-duplicate should be rejected"
    assert len(he._active_hypotheses()) == 1
    print("  PASS: test_duplicate_detection")


def test_signal_trigger_matching():
    he, _ = _make_engine()
    hyp = he.create_hypothesis(
        hypothesis_text="IF Russia escalates in Donbas THEN NATO increases eastern deployment within 21 days",
        trigger_condition="Russian military escalation in Donbas region",
        expected_outcome="NATO troop deployments increase in eastern Europe",
        trigger_keywords={"russia", "donbas", "escalation", "offensive"},
        outcome_keywords={"nato", "deployment", "troops", "eastern europe"},
        trigger_entities={"Russia", "Donbas"},
        outcome_entities={"NATO"},
        timeframe_days=21,
        confidence=0.5,
        source="user",
    )

    # Signal that matches trigger
    events = he.check_signal(
        headline="Russia launches major offensive in Donbas region, heavy shelling reported",
        entities={"Russia", "Donbas", "Ukraine"},
        source_type="perception_alert",
        region="EUROPE",
    )

    assert hyp.trigger_confidence > 0.0, "Trigger confidence should increase"
    assert len(hyp.trigger_evidence) == 1, "Should have 1 trigger evidence"
    assert hyp.outcome_confidence == 0.0, "Outcome confidence should be unchanged"

    # Second trigger signal
    he.check_signal(
        headline="Russia escalation continues in Donbas with new troop deployments",
        entities={"Russia", "Donbas"},
        source_type="perception_alert",
        region="EUROPE",
    )
    assert hyp.trigger_confidence > 0.15, "Trigger confidence should increase further"
    assert len(hyp.trigger_evidence) == 2
    print("  PASS: test_signal_trigger_matching")


def test_signal_outcome_matching():
    he, _ = _make_engine()
    hyp = he.create_hypothesis(
        hypothesis_text="IF Turkey blocks Bosphorus THEN grain prices surge within 14 days",
        trigger_condition="Turkey restricts Bosphorus strait shipping",
        expected_outcome="Global grain prices surge significantly",
        trigger_keywords={"turkey", "bosphorus", "block", "shipping"},
        outcome_keywords={"grain", "wheat", "prices", "surge"},
        trigger_entities={"Turkey"},
        outcome_entities=set(),
        timeframe_days=14,
        confidence=0.5,
        source="user",
    )

    # Signal matching outcome
    he.check_signal(
        headline="Global wheat prices surge 15% amid supply concerns",
        entities=set(),
        source_type="financial_anomaly",
        region="GLOBAL",
    )
    assert hyp.outcome_confidence > 0.0, "Outcome confidence should increase"
    assert len(hyp.outcome_evidence) == 1
    print("  PASS: test_signal_outcome_matching")


def test_trigger_detection_lifecycle():
    he, _ = _make_engine()
    hyp = he.create_hypothesis(
        hypothesis_text="IF Fed raises rates THEN tech stocks drop 5% within 7 days",
        trigger_condition="Federal Reserve raises interest rates",
        expected_outcome="Tech stocks decline by 5% or more",
        trigger_keywords={"fed", "rate", "hike", "raise", "federal reserve"},
        outcome_keywords={"tech", "stocks", "drop", "decline", "nasdaq"},
        timeframe_days=7,
        confidence=0.6,
        source="user",
    )
    assert hyp.status == "active"

    # Feed multiple trigger signals to cross 0.50 confidence
    for i in range(5):
        he.check_signal(
            headline=f"Federal Reserve signals imminent rate hike #{i+1}",
            entities={"Federal Reserve", "United States"},
            source_type="economic_shift",
            region="NORTH_AMERICA",
        )

    assert hyp.status == "trigger_detected", f"Status should be trigger_detected, got {hyp.status}"
    assert hyp.trigger_confidence >= 0.50
    print("  PASS: test_trigger_detection_lifecycle")


def test_expiry():
    he, _ = _make_engine()
    hyp = he.create_hypothesis(
        hypothesis_text="IF test trigger THEN test outcome within 1 day",
        trigger_condition="test trigger",
        expected_outcome="test outcome",
        trigger_keywords={"test_trigger_xyz"},
        outcome_keywords={"test_outcome_xyz"},
        timeframe_days=1,
        confidence=0.5,
        source="user",
    )

    # Force deadline to past
    hyp.deadline = time.time() - 10

    events = he.check_signal(
        headline="Unrelated headline about test_trigger_xyz event",
        entities=set(),
        source_type="perception_alert",
        region="GLOBAL",
    )

    expired_events = [e for e in events if e["type"] == "expired"]
    assert len(expired_events) == 1, "Should have 1 expired event"
    assert hyp.status == "expired"
    print("  PASS: test_expiry")


def test_digest_generation():
    he, _ = _make_engine()
    # Empty digest
    assert he.get_digest() == "", "Empty engine should return empty digest"

    # Create some hypotheses
    he.create_hypothesis(
        hypothesis_text="IF A happens THEN B follows within 30 days",
        trigger_condition="A happens",
        expected_outcome="B follows",
        trigger_keywords={"event_a"},
        outcome_keywords={"consequence_b"},
        timeframe_days=30,
        confidence=0.7,
        source="pattern",
        domains=["SECURITY"],
    )
    he.create_hypothesis(
        hypothesis_text="IF C occurs THEN D results within 14 days",
        trigger_condition="C occurs",
        expected_outcome="D results",
        trigger_keywords={"event_c"},
        outcome_keywords={"result_d"},
        timeframe_days=14,
        confidence=0.5,
        source="synthesis",
        domains=["ECONOMIC"],
    )

    digest = he.get_digest()
    assert "PERSISTENT HYPOTHESES" in digest
    assert "IF A happens" in digest
    assert "IF C occurs" in digest
    assert "SECURITY" in digest
    assert "ECONOMIC" in digest
    print("  PASS: test_digest_generation")


def test_stats():
    he, _ = _make_engine()
    stats = he.stats()
    assert stats["active"] == 0
    assert stats["total_created"] == 0
    assert stats["confirmed"] == 0
    assert stats["accuracy"] == 0.0

    he.create_hypothesis(
        hypothesis_text="IF X THEN Y within 10 days",
        trigger_condition="X",
        expected_outcome="Y",
        trigger_keywords={"x_keyword"},
        outcome_keywords={"y_keyword"},
        timeframe_days=10,
        source="user",
    )

    stats = he.stats()
    assert stats["active"] == 1
    assert stats["total_created"] == 1
    print("  PASS: test_stats")


def test_persistence():
    he, _ = _make_engine()
    state_path = he._PERSIST_PATH

    hyp = he.create_hypothesis(
        hypothesis_text="IF persistence test trigger THEN persistence test outcome within 30 days",
        trigger_condition="persistence trigger",
        expected_outcome="persistence outcome",
        trigger_keywords={"persist_trigger"},
        outcome_keywords={"persist_outcome"},
        trigger_entities={"TestEntity"},
        timeframe_days=30,
        confidence=0.65,
        source="user",
        domains=["SECURITY"],
    )

    # Feed a signal so there's evidence
    he.check_signal(
        headline="Signal matching persist_trigger keyword",
        entities={"TestEntity"},
        source_type="perception_alert",
        region="GLOBAL",
    )

    # Verify file was written
    assert state_path.exists(), "State file should exist after creation"

    # Load in a new engine instance (don't use _make_engine — it deletes state files)
    from xdart.proactive import HypothesisEngine
    mock_engine2 = MagicMock()
    mock_engine2.llm = MagicMock()
    mock_engine2._mongo = None
    he2 = HypothesisEngine.__new__(HypothesisEngine)
    he2.engine = mock_engine2
    he2._hypotheses = []
    he2._last_verification = {}
    he2._last_auto_gen_ts = 0.0
    he2._total_created = 0
    he2._total_confirmed = 0
    he2._total_disconfirmed = 0
    he2._total_expired = 0
    he2._total_signals_checked = 0
    he2._PERSIST_PATH = state_path
    he2._JOURNAL_PATH = Path("hypothesis_journal_test.json")
    he2._load_state()

    assert len(he2._hypotheses) == 1, f"Should load 1 hypothesis, got {len(he2._hypotheses)}"
    loaded = he2._hypotheses[0]
    assert loaded.hypothesis_text == hyp.hypothesis_text
    assert loaded.confidence == hyp.confidence
    assert "persist_trigger" in loaded.trigger_keywords
    assert "TestEntity" in loaded.trigger_entities
    assert len(loaded.trigger_evidence) >= 1
    print("  PASS: test_persistence")

    # Cleanup
    if state_path.exists():
        state_path.unlink()


def test_max_active_cap():
    he, _ = _make_engine()
    he._MAX_ACTIVE = 3  # Low cap for testing

    # Use completely distinct hypothesis texts to avoid duplicate detection
    texts = [
        ("IF Iran closes Hormuz THEN oil spikes", "Iran closes Hormuz", "Oil spikes"),
        ("IF China invades Taiwan THEN chips triple", "China invades Taiwan", "Chips triple"),
        ("IF Russia cuts gas THEN euro falls hard", "Russia cuts gas", "Euro falls hard"),
        ("IF Fed hikes rates THEN tech crashes badly", "Fed hikes rates", "Tech crashes badly"),
        ("IF India bans exports THEN rice surges globally", "India bans exports", "Rice surges"),
    ]
    for i, (hyp_text, trigger, outcome) in enumerate(texts):
        result = he.create_hypothesis(
            hypothesis_text=hyp_text,
            trigger_condition=trigger,
            expected_outcome=outcome,
            trigger_keywords={f"trigger_{i}"},
            outcome_keywords={f"outcome_{i}"},
            timeframe_days=30,
            source="user",
        )
        if i < 3:
            assert result is not None, f"Hypothesis {i} should be created"
        else:
            assert result is None, f"Hypothesis {i} should be rejected (cap)"

    assert len(he._active_hypotheses()) == 3
    print("  PASS: test_max_active_cap")


def test_keyword_case_insensitivity():
    he, _ = _make_engine()
    hyp = he.create_hypothesis(
        hypothesis_text="IF IRAN escalates THEN OIL spikes within 14 days",
        trigger_condition="Iran escalation",
        expected_outcome="Oil price spike",
        trigger_keywords={"IRAN", "Escalation", "Military"},
        outcome_keywords={"OIL", "Spike", "Price"},
        timeframe_days=14,
        source="user",
    )

    # Keywords should be lowercased
    assert "iran" in hyp.trigger_keywords
    assert "escalation" in hyp.trigger_keywords
    assert "oil" in hyp.outcome_keywords

    # Matching should work case-insensitively (headline is lowered)
    he.check_signal(
        headline="IRAN ANNOUNCES MILITARY ESCALATION IN GULF REGION",
        entities={"Iran"},
        source_type="perception_alert",
        region="MIDDLE_EAST",
    )
    assert hyp.trigger_confidence > 0, "Should match case-insensitively"
    print("  PASS: test_keyword_case_insensitivity")


def test_entity_matching():
    he, _ = _make_engine()
    hyp = he.create_hypothesis(
        hypothesis_text="IF China sanctions Taiwan THEN TSMC stock drops within 14 days",
        trigger_condition="China imposes sanctions on Taiwan",
        expected_outcome="TSMC stock price drops significantly",
        trigger_keywords={"sanctions"},
        outcome_keywords={"tsmc", "stock"},
        trigger_entities={"China", "Taiwan"},
        outcome_entities={"TSMC"},
        timeframe_days=14,
        source="user",
    )

    # Signal with entity match but no keyword
    he.check_signal(
        headline="Beijing unveils new trade measures targeting Taipei",
        entities={"China", "Taiwan"},
        source_type="perception_alert",
        region="ASIA",
    )
    assert hyp.trigger_confidence > 0, "Entity match should boost trigger confidence"
    assert len(hyp.trigger_evidence) == 1
    print("  PASS: test_entity_matching")


if __name__ == "__main__":
    print("=" * 60)
    print("  P2 — Hypothesis Engine Tests")
    print("=" * 60)

    tests = [
        test_create_hypothesis,
        test_duplicate_detection,
        test_signal_trigger_matching,
        test_signal_outcome_matching,
        test_trigger_detection_lifecycle,
        test_expiry,
        test_digest_generation,
        test_stats,
        test_persistence,
        test_max_active_cap,
        test_keyword_case_insensitivity,
        test_entity_matching,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    # Cleanup test files
    for p in [Path("hypothesis_state_test.json"), Path("hypothesis_journal_test.json")]:
        if p.exists():
            p.unlink()

    sys.exit(0 if failed == 0 else 1)
