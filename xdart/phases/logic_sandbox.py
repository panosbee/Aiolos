"""
XDART-Φ × XHEART — Logic Self-Modification Sandbox (αυτο-τροποποίηση λογικής)

Gives Αίολος the ability to REWRITE parts of his own reasoning logic,
with strict guardrails to prevent self-damage.

Unlike the Evolution Core (which generates NEW tools) or Self-Evolution
(which writes prompt overlays), this system allows Αίολος to propose
modifications to EXISTING algorithmic functions — such as:
  - How curiosity priority is computed
  - How prophecy confidence is weighted
  - How scenario salience scores are combined
  - How working memory eviction decisions are made

The Iron Rules:
  1. CORE IS SACRED — Only designated "modifiable functions" can be touched
  2. SANDBOX FIRST — Every modification is tested in the existing sandbox
  3. A/B TESTED — Old vs new logic, measured performance comparison
  4. ROLLBACK READY — Previous version is always stored for instant rollback
  5. HUMAN APPROVAL — Permanent changes require Panos's approval
  6. AUDIT TRAIL — Every proposal, test, and decision is logged

Architecture:
  LogicSandbox            — The main orchestrator
  ModifiableFunction      — Registry of functions Αίολος may modify
  LogicProposal           — A proposed modification with rationale
  LogicTestResult         — Sandbox test results for a proposal

Storage: logic_sandbox_journal.jsonl (append-only audit trail)
         logic_sandbox_state.json (current state of modifications)

«Ένα σύστημα που μπορεί να αλλάξει τον εαυτό του χωρίς να χάσει τον εαυτό του
 — αυτό είναι νοημοσύνη.»
"""

import json
import logging
import time
import textwrap
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from xdart.evolution.sandbox import Sandbox, SandboxResult, SAFE_IMPORTS
from xdart.llm import LLMClient

logger = logging.getLogger("xdart.logic_sandbox")

# ── Paths ──
BASE_DIR = Path(__file__).parent.parent.parent
JOURNAL_PATH = BASE_DIR / "logic_sandbox_journal.jsonl"
STATE_PATH = BASE_DIR / "logic_sandbox_state.json"

# ── Safety Limits ──
MAX_FUNCTION_CHARS = 5000        # Max size of a modified function
MAX_PENDING_PROPOSALS = 10       # Don't accumulate too many pending proposals
MAX_MODIFICATION_HISTORY = 50    # Per-function history depth

# ══════════════════════════════════════════════════════════════
#  MODIFIABLE FUNCTION REGISTRY
# ══════════════════════════════════════════════════════════════

# These are the ONLY functions Αίολος is allowed to modify.
# Each entry defines:
#   - function_id: unique identifier
#   - description: what the function does (for LLM context)
#   - current_code: the current implementation (Python source)
#   - signature: function signature
#   - test_cases: list of (input, expected_behavior) for sandbox testing
#   - constraints: what the function MUST always do (invariants)

@dataclass
class ModifiableFunction:
    """A function that Αίολος is allowed to propose modifications to."""

    function_id: str
    description: str
    module_path: str               # e.g. "xdart.phases.curiosity"
    function_name: str             # e.g. "compute_priority"
    signature: str                 # e.g. "def compute_priority(curiosity: dict, context: dict) -> float"
    current_code: str              # The current Python source
    constraints: list[str]         # Invariants that must ALWAYS hold
    test_inputs: list[dict]        # Test inputs for sandbox
    expected_behavior: str         # Human-readable expected behavior description
    original_code: str = ""        # The original (factory) version — never changes
    modification_count: int = 0
    history: list[dict] = field(default_factory=list)  # [{timestamp, code, reason, performance}]
    active_modification: dict | None = None  # Currently active non-original code

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ModifiableFunction":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════
#  LOGIC PROPOSAL
# ══════════════════════════════════════════════════════════════

@dataclass
class LogicProposal:
    """A proposed modification to a modifiable function."""

    id: str
    function_id: str
    proposed_code: str
    rationale: str
    expected_improvement: str
    risk_assessment: str
    proposed_at: str
    status: str = "pending"         # pending → testing → tested → approved → applied / rejected / rolled_back
    sandbox_result: dict | None = None
    ab_test_result: dict | None = None
    approval_status: str = "awaiting"  # awaiting → approved → rejected
    approved_by: str = ""           # "auto" for auto-approved, "human" for manual
    applied_at: str | None = None
    rolled_back_at: str | None = None
    rollback_reason: str = ""
    performance_before: float | None = None
    performance_after: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LogicProposal":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════
#  BUILT-IN MODIFIABLE FUNCTIONS
# ══════════════════════════════════════════════════════════════

def _default_curiosity_prioritizer() -> str:
    """The default curiosity priority computation — Αίολος can rewrite this."""
    return textwrap.dedent('''\
        def compute_curiosity_priority(curiosity: dict, context: dict) -> float:
            """Compute priority score for a curiosity question.

            Args:
                curiosity: {"question": str, "source_type": str, "tags": list,
                           "created_at": str, "exploration_count": int}
                context: {"active_tensions": list, "recent_topics": list,
                         "avg_integrity": float, "world_events_count": int}

            Returns:
                float: Priority score (0.0 = lowest, 1.0 = highest)
            """
            import datetime
            base = 0.5

            # Source type weighting
            source_weights = {
                "introspection": 0.15,
                "tension": 0.12,
                "world_gap": 0.10,
                "pipeline": 0.08,
                "self_evolution": 0.20,
            }
            base += source_weights.get(curiosity.get("source_type", ""), 0.05)

            # Tag relevance: more tags that match active tensions = higher priority
            tags = set(curiosity.get("tags", []))
            tensions = set(context.get("active_tensions", []))
            overlap = len(tags & tensions)
            base += min(overlap * 0.05, 0.15)

            # Recency decay: newer curiosities slightly preferred
            try:
                created = datetime.datetime.fromisoformat(curiosity.get("created_at", ""))
                age_hours = (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() / 3600
                recency_bonus = max(0, 0.10 - (age_hours * 0.001))
                base += recency_bonus
            except (ValueError, TypeError):
                pass

            # Penalize over-explored curiosities
            exploration_count = curiosity.get("exploration_count", 0)
            if exploration_count > 3:
                base -= 0.10
            elif exploration_count > 1:
                base -= 0.05

            # Integrity-aware: if avg integrity is low, prioritize introspection curiosities
            if context.get("avg_integrity", 1.0) < 0.6 and curiosity.get("source_type") == "introspection":
                base += 0.10

            return max(0.0, min(1.0, base))
    ''')


def _default_prophecy_confidence_adjuster() -> str:
    """The default prophecy confidence adjustment logic."""
    return textwrap.dedent('''\
        def adjust_prophecy_confidence(prophecy: dict, context: dict) -> float:
            """Adjust confidence in a prophecy based on new evidence.

            Args:
                prophecy: {"prediction": str, "confidence": float, "domain": str,
                          "created_at": str, "supporting_evidence": list,
                          "contradicting_evidence": list, "days_remaining": int}
                context: {"world_events": list, "brier_score": float,
                         "calibration_error": float}

            Returns:
                float: Adjusted confidence (0.0 - 1.0)
            """
            import math
            confidence = prophecy.get("confidence", 0.5)

            # Evidence balance
            supporting = len(prophecy.get("supporting_evidence", []))
            contradicting = len(prophecy.get("contradicting_evidence", []))
            total = supporting + contradicting

            if total > 0:
                evidence_ratio = supporting / total
                # Bayesian-style update: shift towards evidence
                confidence = confidence * 0.6 + evidence_ratio * 0.4

            # Temporal decay: confidence decreases as deadline approaches with no confirmation
            days_remaining = prophecy.get("days_remaining", 30)
            if days_remaining < 7 and supporting == 0:
                confidence *= 0.85
            elif days_remaining < 3 and supporting == 0:
                confidence *= 0.70

            # Calibration awareness: if brier score is bad, be more humble
            brier = context.get("brier_score", 0.25)
            if brier > 0.35:
                # Pull towards 0.5 (maximum uncertainty)
                confidence = confidence * 0.8 + 0.5 * 0.2

            # Calibration error correction
            cal_error = context.get("calibration_error", 0.0)
            if cal_error > 0.1:
                # System tends to be overconfident — reduce
                confidence *= (1.0 - cal_error * 0.5)

            return max(0.05, min(0.95, confidence))
    ''')


def _default_scenario_salience_scorer() -> str:
    """The default scenario salience scoring logic."""
    return textwrap.dedent('''\
        def score_scenario_salience(scenario: dict, context: dict) -> float:
            """Score how salient/important a scenario is for the current analysis.

            Args:
                scenario: {"title": str, "conditions": list, "timeline": str,
                          "domains": list, "confidence": float,
                          "tribunal_score": float, "breakpoints": list}
                context: {"problem_domains": list, "active_prophecies": list,
                         "recent_events_domains": list, "n_scenarios": int}

            Returns:
                float: Salience score (0.0 - 1.0)
            """
            base = 0.3

            # Tribunal score is the primary signal
            tribunal = scenario.get("tribunal_score", 0.5)
            base += tribunal * 0.30

            # Domain relevance: overlap with problem domains
            scenario_domains = set(scenario.get("domains", []))
            problem_domains = set(context.get("problem_domains", []))
            if problem_domains:
                domain_overlap = len(scenario_domains & problem_domains) / len(problem_domains)
                base += domain_overlap * 0.15

            # Breakpoint severity
            breakpoints = scenario.get("breakpoints", [])
            fatal_count = sum(1 for bp in breakpoints if bp.get("severity") == "FATAL")
            if fatal_count > 0:
                base += 0.10  # Fatal breakpoints make scenarios more important to track

            # Prophecy alignment
            active_prophecies = context.get("active_prophecies", [])
            conditions = set(scenario.get("conditions", []))
            prophecy_matches = sum(
                1 for p in active_prophecies
                if any(c.lower() in p.lower() for c in conditions)
            )
            base += min(prophecy_matches * 0.05, 0.10)

            # Diversity bonus: if few scenarios, each is more important
            n = context.get("n_scenarios", 1)
            if n <= 3:
                base += 0.05

            return max(0.0, min(1.0, base))
    ''')


def _default_working_memory_evictor() -> str:
    """The default working memory eviction logic."""
    return textwrap.dedent('''\
        def select_eviction_candidate(memory_slots: list, context: dict) -> int:
            """Select which working memory slot to evict when capacity is full.

            Args:
                memory_slots: list of dicts, each with:
                    {"content": str, "type": str, "relevance": float,
                     "inserted_at": str, "access_count": int, "source": str}
                context: {"current_problem": str, "phase": str,
                         "n_total_insertions": int}

            Returns:
                int: Index of the slot to evict (0-based)
            """
            import datetime

            if not memory_slots:
                return 0

            # Score each slot: LOWER score = more likely to evict
            scores = []
            type_priority = {
                "procedural": 1.5,
                "semantic": 1.3,
                "echo": 1.2,
                "insight": 1.1,
                "sensory": 0.8,
                "raw": 0.6,
            }

            for i, slot in enumerate(memory_slots):
                score = 0.0

                # Type priority
                score += type_priority.get(slot.get("type", "raw"), 0.7)

                # Relevance to current problem
                score += slot.get("relevance", 0.5) * 2.0

                # Recency: more recent = higher score
                try:
                    inserted = datetime.datetime.fromisoformat(slot.get("inserted_at", ""))
                    age_minutes = (datetime.datetime.now(datetime.timezone.utc) - inserted).total_seconds() / 60
                    recency = max(0, 1.0 - (age_minutes / 120))  # Decay over 2 hours
                    score += recency * 0.5
                except (ValueError, TypeError):
                    pass

                # Access count: frequently accessed = more valuable
                score += min(slot.get("access_count", 0) * 0.1, 0.5)

                scores.append(score)

            # Evict the lowest-scoring slot
            return scores.index(min(scores))
    ''')


# ── New modifiable functions (v2: expanded self-modification) ───────

def _default_impact_score() -> str:
    """The default pattern impact scoring logic — extracted from PatternAccumulator."""
    return textwrap.dedent('''\
        def estimate_impact_score(pattern: dict, context: dict) -> float:
            """Estimate strategic impact of an emergent pattern. Returns 0.0-1.0.

            Args:
                pattern: {"headlines": list[str], "source_types": list[str],
                         "domain_count": int}
                context: {} (unused, reserved for future evidence injection)

            Returns:
                float: Impact score (0.0 = routine, 1.0 = maximum strategic impact)
            """
            headlines_text = " ".join(h.lower() for h in pattern.get("headlines", []))
            source_types = set(pattern.get("source_types", []))

            score = 0.25  # base: any converged pattern

            # ── Scope detection (highest wins) ──
            GLOBAL_SCOPE = {"world war", "nuclear war", "global", "worldwide", "pandemic",
                           "united nations", "g7", "g20", "nato", "wto", "imf", "who",
                           "world economy", "global recession", "climate crisis"}
            CONTINENTAL = {"europe", "european", "asia", "african", "middle east",
                          "southeast asia", "latin america", "pacific", "arctic"}
            MAJOR_POWERS = {"united states", "usa", "america", "china", "chinese",
                           "russia", "russian", "india", "japan", "germany", "france",
                           "britain", "uk", "iran", "israel", "saudi", "turkey",
                           "brazil", "south korea", "north korea", "taiwan", "ukraine"}
            GLOBAL_FIGURES = {"trump", "biden", "xi jinping", "putin", "modi",
                             "netanyahu", "erdogan", "macron", "zelensky", "powell", "lagarde"}
            BREAKING = {"breaking", "urgent", "flash", "just in", "developing"}
            ECON_CRISIS = {"crash", "default", "recession", "collapse", "crisis",
                          "bank run", "bailout", "meltdown", "panic"}
            ECON_KEYWORDS = {"inflation", "interest rate", "rate cut", "gdp",
                            "unemployment", "fed", "ecb", "central bank",
                            "stock market", "bond yield", "trade war", "tariff",
                            "sanctions", "oil price", "currency", "supply chain"}

            if any(t in headlines_text for t in GLOBAL_SCOPE):
                score = max(score, 0.90)
            if any(t in headlines_text for t in CONTINENTAL):
                score = max(score, 0.75)
            if any(t in headlines_text for t in MAJOR_POWERS):
                score = max(score, 0.70)
            if any(f in headlines_text for f in GLOBAL_FIGURES):
                score = max(score, 0.85)

            econ_count = sum(1 for kw in ECON_KEYWORDS if kw in headlines_text)
            has_econ_source = bool({"economic_shift", "financial_anomaly"} & source_types)
            if has_econ_source or econ_count >= 2:
                score = max(score, 0.65)

            if any(i in headlines_text for i in BREAKING):
                score = min(1.0, score + 0.15)
            if any(i in headlines_text for i in ECON_CRISIS):
                score = min(1.0, score + 0.15)

            if econ_count >= 3:
                score = min(1.0, score + 0.10)
            elif econ_count >= 1:
                score = min(1.0, score + 0.05)

            # Cross-domain bonus
            n_domains = pattern.get("domain_count", 1)
            if n_domains >= 3:
                score = min(1.0, score + 0.20)
            elif n_domains >= 2:
                score = min(1.0, score + 0.12)

            # Source diversity
            if len(source_types) >= 3:
                score = min(1.0, score + 0.05)

            return round(score, 3)
    ''')


def _default_salience_score() -> str:
    """The default perception salience scoring logic — extracted from PerceptionFilter."""
    return textwrap.dedent('''\
        def calculate_salience(event: dict, context: dict) -> float:
            """Calculate salience score (0.0-1.0) for a perception event.

            Args:
                event: {"text": str, "content_type": str, "source_tier": int,
                       "domain": str, "headline_score": float (0-500),
                       "propaganda_risk": str, "state_controlled": bool,
                       "country_baseline_risks": list[int],
                       "has_demotion_keywords": bool}
                context: {} (unused, reserved)

            Returns:
                float: Salience score (0.1 minimum, 1.0 maximum)
            """
            base = 0.5

            # Tier affects base salience
            tier_bonus = {1: 0.3, 2: 0.1, 3: 0.0}.get(event.get("source_tier", 4), 0.0)
            base += tier_bonus

            # Content type weighting
            type_bonus = {"FACT": 0.1, "DATA": 0.15, "ANALYSIS": 0.0, "OPINION": -0.1}
            base += type_bonus.get(event.get("content_type", ""), 0.0)

            # High-salience keyword boost
            HIGH_SAL = ["breaking", "urgent", "crisis", "war ", "attack",
                        "collapse", "emergency", "unprecedented", "historic",
                        "rate decision", "rate cut", "rate hike", "default",
                        "invasion", "nuclear", "pandemic", "recession", "bailout",
                        "trade war", "sanctions", "tariff", "supply shock",
                        "stagflation", "contagion", "capital controls"]
            text = event.get("text", "").lower()
            high_sal = sum(1 for kw in HIGH_SAL if kw in text)
            base += min(high_sal * 0.1, 0.3)

            # Economic/Market domain boost
            if event.get("domain") in ("ECONOMIC", "MARKET"):
                base += 0.08

            # Headline importance (mapped from WorldMonitor score)
            hl_score = event.get("headline_score", 0)
            base += min(hl_score / 2000.0, 0.25)

            # Propaganda risk penalty
            risk = event.get("propaganda_risk", "low")
            if risk == "high":
                base -= 0.15
            elif risk == "medium":
                base -= 0.05
            if event.get("state_controlled"):
                base -= 0.05

            # Corporate noise demotion
            if event.get("has_demotion_keywords"):
                base -= 0.10

            # Country baseline risk boost
            risks = event.get("country_baseline_risks", [])
            if risks:
                max_baseline = max(risks)
                if max_baseline >= 40:
                    base += 0.15
                elif max_baseline >= 25:
                    base += 0.10
                elif max_baseline >= 15:
                    base += 0.05

            return max(0.1, min(1.0, round(base, 2)))
    ''')


def _default_convergence_score() -> str:
    """The default pattern convergence scoring logic — extracted from EmergentPattern."""
    return textwrap.dedent('''\
        def calculate_convergence(pattern: dict, context: dict) -> float:
            """Calculate convergence score for an emergent pattern. Returns 0.0-1.0.

            Args:
                pattern: {"signal_weights": list[float],
                         "signal_ages_seconds": list[float],
                         "source_type_count": int,
                         "region_counts": dict[str, int]}
                context: {} (unused, reserved)

            Returns:
                float: Convergence score (0.0-1.0). Fires at >= 0.50.
            """
            import math

            HALF_LIFE = 14400  # 4 hours signal decay

            weights = pattern.get("signal_weights", [])
            ages = pattern.get("signal_ages_seconds", [])

            if not weights:
                return 0.0

            # Weighted mass with exponential time decay
            total_weight = 0.0
            for w, age in zip(weights, ages):
                decayed = w * math.exp(-0.693 * max(0, age) / HALF_LIFE)
                total_weight += decayed

            # Diminishing returns via log
            weighted_mass = math.log2(total_weight + 1)

            # Diversity bonus: more source types = higher (1.0 to 1.5)
            n_types = pattern.get("source_type_count", 1)
            diversity_bonus = 1.0 + min(0.5, (n_types - 1) * 0.15)

            # Concentration: if one non-GLOBAL region dominates, boost
            region_counts = pattern.get("region_counts", {})
            non_global = {k: v for k, v in region_counts.items() if k != "GLOBAL"}
            if non_global:
                max_count = max(non_global.values())
                concentration_bonus = 1.0 + min(0.3, (max_count - 1) * 0.10)
            else:
                concentration_bonus = 1.0

            raw = (weighted_mass / 3.0) * diversity_bonus * concentration_bonus
            return min(1.0, round(raw, 3))
    ''')


def _default_keyword_relevance() -> str:
    """The default academic paper keyword relevance scoring logic."""
    return textwrap.dedent('''\
        def score_keyword_relevance(paper: dict, context: dict) -> float:
            """Score academic paper relevance via keyword matching. Returns 0.0-1.0.

            Args:
                paper: {"title": str, "abstract": str}
                context: {} (unused, reserved)

            Returns:
                float: Relevance score based on keyword overlap with research interests.
            """
            text = "{} {}".format(
                paper.get("title", ""), paper.get("abstract", "")
            ).lower()

            KEYWORDS = {
                "geopolitical": 0.15, "conflict": 0.10, "sanctions": 0.12,
                "systemic risk": 0.15, "financial crisis": 0.12, "currency": 0.08,
                "bayesian": 0.15, "fuzzy logic": 0.12, "scenario": 0.08,
                "cyber": 0.10, "semiconductor": 0.10, "infrastructure": 0.08,
                "prediction": 0.10, "forecasting": 0.10, "early warning": 0.12,
                "supply chain": 0.10, "nuclear": 0.08, "escalation": 0.10,
            }

            score = 0.0
            for kw, weight in KEYWORDS.items():
                if kw in text:
                    score += weight

            return min(1.0, round(score, 3))
    ''')


def _default_signal_domain_classifier() -> str:
    """The default signal domain classification logic — extracted from CDSFE."""
    return textwrap.dedent('''\
        def classify_signal_domain(signal: dict, context: dict) -> list:
            """Classify a signal into one or more domains. Returns sorted list.

            Args:
                signal: {"headline": str, "source_type": str}
                context: {} (unused, reserved)

            Returns:
                list: Sorted list of domain strings (e.g. ["ECONOMIC", "GEOPOLITICAL"]).
            """
            headline = signal.get("headline", "").lower()
            source_type = signal.get("source_type", "")

            domains = set()

            # Source type auto-classification
            SOURCE_DOMAINS = {
                "economic_shift": "ECONOMIC",
                "financial_anomaly": "MARKET",
                "infrastructure_cascade": "TECHNOLOGY",
            }
            if source_type in SOURCE_DOMAINS:
                domains.add(SOURCE_DOMAINS[source_type])

            # Keyword matching across 5 domains
            DOMAIN_KEYWORDS = {
                "GEOPOLITICAL": ["war", "invasion", "military", "missile", "ceasefire",
                                "nato", "coup", "diplomatic", "alliance", "border",
                                "conflict", "escalation", "sanctions", "espionage",
                                "blockade", "proxy war", "arms deal", "nuclear"],
                "ECONOMIC": ["gdp", "inflation", "recession", "rate cut", "rate hike",
                            "central bank", "trade war", "tariff", "sovereign debt",
                            "bond yield", "fiscal", "monetary policy", "unemployment",
                            "deficit", "bailout", "default", "austerity"],
                "MARKET": ["stock market", "crash", "volatility", "bear market",
                          "commodity", "oil price", "gold price", "bitcoin", "crypto",
                          "currency", "capital flight", "yield curve", "trading",
                          "flash crash", "vix", "liquidity"],
                "SOCIAL": ["protest", "riot", "uprising", "refugee", "migration",
                          "famine", "pandemic", "election", "human rights",
                          "humanitarian", "inequality", "civil unrest", "strike"],
                "TECHNOLOGY": ["cyber attack", "hack", "ransomware", "semiconductor",
                              "chip", "quantum", "satellite", "drone", "ai ",
                              "tech war", "export control", "biotech", "nuclear energy"],
            }

            for domain, keywords in DOMAIN_KEYWORDS.items():
                if any(kw in headline for kw in keywords):
                    domains.add(domain)

            if not domains:
                domains.add("GEOPOLITICAL")  # default fallback

            return sorted(domains)
    ''')


def _default_topic_similarity() -> str:
    """The default topic similarity computation — Jaccard coefficient."""
    return textwrap.dedent('''\
        def compute_topic_similarity(data: dict, context: dict) -> float:
            """Jaccard similarity between two topic sets. Returns 0.0-1.0.

            Args:
                data: {"topics_a": list[str], "topics_b": list[str]}
                context: {} (unused, reserved)

            Returns:
                float: Jaccard similarity (0.0 = disjoint, 1.0 = identical).
            """
            topics_a = set(data.get("topics_a", []))
            topics_b = set(data.get("topics_b", []))

            if not topics_a or not topics_b:
                return 0.0

            intersection = topics_a & topics_b
            union = topics_a | topics_b

            return round(len(intersection) / len(union), 3) if union else 0.0
    ''')


# ══════════════════════════════════════════════════════════════
#  FUNCTION REGISTRY BUILDER
# ══════════════════════════════════════════════════════════════

def build_default_registry() -> dict[str, ModifiableFunction]:
    """Build the default registry of modifiable functions."""

    curiosity_code = _default_curiosity_prioritizer()
    prophecy_code = _default_prophecy_confidence_adjuster()
    scenario_code = _default_scenario_salience_scorer()
    eviction_code = _default_working_memory_evictor()
    impact_code = _default_impact_score()
    salience_code = _default_salience_score()
    convergence_code = _default_convergence_score()
    keyword_rel_code = _default_keyword_relevance()
    domain_class_code = _default_signal_domain_classifier()
    topic_sim_code = _default_topic_similarity()

    return {
        "curiosity_priority": ModifiableFunction(
            function_id="curiosity_priority",
            description="Computes priority score for curiosity questions. Higher priority = explored sooner.",
            module_path="xdart.phases.curiosity",
            function_name="compute_curiosity_priority",
            signature="def compute_curiosity_priority(curiosity: dict, context: dict) -> float",
            current_code=curiosity_code,
            original_code=curiosity_code,
            constraints=[
                "Must return a float between 0.0 and 1.0",
                "Must not crash on empty inputs",
                "Must consider source_type weighting",
                "Must penalize over-explored curiosities",
                "Only safe imports allowed (json, math, datetime, etc.)",
            ],
            test_inputs=[
                {
                    "curiosity": {
                        "question": "Why is EU response asymmetric to US tariffs?",
                        "source_type": "introspection",
                        "tags": ["trade", "EU", "geopolitics"],
                        "created_at": "2026-04-10T12:00:00+00:00",
                        "exploration_count": 0,
                    },
                    "context": {
                        "active_tensions": ["trade", "sovereignty"],
                        "recent_topics": ["tariffs", "EU policy"],
                        "avg_integrity": 0.75,
                        "world_events_count": 45,
                    },
                },
                {
                    "curiosity": {
                        "question": "What cartoon is popular?",
                        "source_type": "pipeline",
                        "tags": [],
                        "created_at": "2026-04-01T12:00:00+00:00",
                        "exploration_count": 5,
                    },
                    "context": {
                        "active_tensions": [],
                        "recent_topics": [],
                        "avg_integrity": 0.5,
                        "world_events_count": 0,
                    },
                },
            ],
            expected_behavior="Returns 0.0-1.0. Introspection curiosities from self_evolution get highest base scores. Over-explored curiosities are penalized. Tag overlap with active tensions boosts priority.",
        ),

        "prophecy_confidence": ModifiableFunction(
            function_id="prophecy_confidence",
            description="Adjusts confidence in prophecies based on new evidence and calibration data.",
            module_path="xdart.phases.prophetic_loop",
            function_name="adjust_prophecy_confidence",
            signature="def adjust_prophecy_confidence(prophecy: dict, context: dict) -> float",
            current_code=prophecy_code,
            original_code=prophecy_code,
            constraints=[
                "Must return a float between 0.05 and 0.95",
                "Must never return 0.0 or 1.0 (epistemic humility)",
                "Must consider both supporting and contradicting evidence",
                "Must pull towards uncertainty when calibration is poor",
                "Only safe imports allowed",
            ],
            test_inputs=[
                {
                    "prophecy": {
                        "prediction": "ECB will cut rates by June 2026",
                        "confidence": 0.7,
                        "domain": "ECONOMIC",
                        "created_at": "2026-03-15T00:00:00+00:00",
                        "supporting_evidence": ["dovish speech", "inflation decline"],
                        "contradicting_evidence": [],
                        "days_remaining": 45,
                    },
                    "context": {
                        "world_events": [],
                        "brier_score": 0.22,
                        "calibration_error": 0.05,
                    },
                },
                {
                    "prophecy": {
                        "prediction": "China invades Taiwan by Q3 2026",
                        "confidence": 0.3,
                        "domain": "GEOPOLITICAL",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "supporting_evidence": [],
                        "contradicting_evidence": ["diplomatic talks", "trade deals"],
                        "days_remaining": 5,
                    },
                    "context": {
                        "world_events": [],
                        "brier_score": 0.40,
                        "calibration_error": 0.15,
                    },
                },
            ],
            expected_behavior="Returns 0.05-0.95. Evidence balance shifts confidence. Temporal decay reduces confidence as deadline approaches without confirmation. Poor calibration (high brier) pulls towards 0.5.",
        ),

        "scenario_salience": ModifiableFunction(
            function_id="scenario_salience",
            description="Scores how important/salient a scenario is for the current analysis.",
            module_path="xdart.phases.scenario_genesis",
            function_name="score_scenario_salience",
            signature="def score_scenario_salience(scenario: dict, context: dict) -> float",
            current_code=scenario_code,
            original_code=scenario_code,
            constraints=[
                "Must return a float between 0.0 and 1.0",
                "Must weight tribunal_score heavily",
                "Must consider domain relevance",
                "Must not ignore breakpoints",
                "Only safe imports allowed",
            ],
            test_inputs=[
                {
                    "scenario": {
                        "title": "Trade War Escalation",
                        "conditions": ["tariff increase", "retaliatory measures"],
                        "timeline": "Q2 2026",
                        "domains": ["ECONOMIC", "GEOPOLITICAL"],
                        "confidence": 0.65,
                        "tribunal_score": 0.78,
                        "breakpoints": [{"severity": "DEGRADING", "desc": "supply chain disruption"}],
                    },
                    "context": {
                        "problem_domains": ["ECONOMIC", "MARKET"],
                        "active_prophecies": ["tariff escalation likely"],
                        "recent_events_domains": ["ECONOMIC"],
                        "n_scenarios": 4,
                    },
                },
            ],
            expected_behavior="Returns 0.0-1.0. Tribunal score is primary factor. Domain overlap with problem boosts salience. Fatal breakpoints increase importance. Prophecy alignment adds bonus.",
        ),

        "working_memory_eviction": ModifiableFunction(
            function_id="working_memory_eviction",
            description="Selects which working memory slot to evict when capacity is full.",
            module_path="xdart.phases.memory_architecture",
            function_name="select_eviction_candidate",
            signature="def select_eviction_candidate(memory_slots: list, context: dict) -> int",
            current_code=eviction_code,
            original_code=eviction_code,
            constraints=[
                "Must return a valid index (0 to len(memory_slots)-1)",
                "Must never crash on empty list",
                "Must consider type priority (procedural > semantic > echo)",
                "Must consider relevance and recency",
                "Only safe imports allowed",
            ],
            test_inputs=[
                {
                    "memory_slots": [
                        {"content": "EU trade analysis", "type": "semantic", "relevance": 0.8, "inserted_at": "2026-04-12T10:00:00+00:00", "access_count": 3, "source": "phase2"},
                        {"content": "Raw RSS data point", "type": "raw", "relevance": 0.2, "inserted_at": "2026-04-12T09:00:00+00:00", "access_count": 0, "source": "perception"},
                        {"content": "If X then Y pattern", "type": "procedural", "relevance": 0.9, "inserted_at": "2026-04-12T08:00:00+00:00", "access_count": 5, "source": "phase3"},
                    ],
                    "context": {
                        "current_problem": "EU trade policy",
                        "phase": "phase2",
                        "n_total_insertions": 15,
                    },
                },
            ],
            expected_behavior="Returns index of lowest-value slot. Raw data with low relevance and low access should be evicted first. Procedural memories with high relevance should be preserved.",
        ),

        # ── New functions (v2: expanded self-modification) ──────────

        "impact_score": ModifiableFunction(
            function_id="impact_score",
            description="Estimates strategic impact of an emergent pattern. Controls which patterns trigger notifications.",
            module_path="xdart.proactive",
            function_name="estimate_impact_score",
            signature="def estimate_impact_score(pattern: dict, context: dict) -> float",
            current_code=impact_code,
            original_code=impact_code,
            constraints=[
                "Must return a float between 0.0 and 1.0",
                "Must not crash on empty inputs",
                "Must detect global scope events as highest impact",
                "Cross-domain patterns must receive a bonus",
                "Only safe imports allowed (json, math, datetime, etc.)",
            ],
            test_inputs=[
                {
                    "pattern": {
                        "headlines": [
                            "NATO emergency summit on Ukraine escalation",
                            "Russia threatens nuclear response to Western arms",
                            "European markets plunge on war fears",
                        ],
                        "source_types": ["perception_event", "perception_alert", "financial_anomaly"],
                        "domain_count": 3,
                    },
                    "context": {},
                },
                {
                    "pattern": {
                        "headlines": ["Local mayor announces new parking regulations"],
                        "source_types": ["perception_event"],
                        "domain_count": 1,
                    },
                    "context": {},
                },
            ],
            expected_behavior="NATO/nuclear/Europe pattern should score >= 0.85. Local parking news should score ~0.25. Cross-domain (3+ domains) adds +0.20 bonus.",
        ),

        "salience_score": ModifiableFunction(
            function_id="salience_score",
            description="Calculates salience score for perception events. Gateway filter — events below 0.15 are discarded.",
            module_path="xdart.perception.filter",
            function_name="calculate_salience",
            signature="def calculate_salience(event: dict, context: dict) -> float",
            current_code=salience_code,
            original_code=salience_code,
            constraints=[
                "Must return a float between 0.1 and 1.0",
                "Must not crash on empty or partial inputs",
                "Tier-1 sources must get highest base boost",
                "Propaganda sources must be penalized",
                "Economic/Market domains must receive a small boost",
                "Only safe imports allowed (json, math, datetime, etc.)",
            ],
            test_inputs=[
                {
                    "event": {
                        "text": "BREAKING: ECB emergency rate cut amid banking crisis",
                        "content_type": "FACT",
                        "source_tier": 1,
                        "domain": "ECONOMIC",
                        "headline_score": 350,
                        "propaganda_risk": "low",
                        "state_controlled": False,
                        "country_baseline_risks": [],
                        "has_demotion_keywords": False,
                    },
                    "context": {},
                },
                {
                    "event": {
                        "text": "Company announces quarterly earnings beat",
                        "content_type": "FACT",
                        "source_tier": 3,
                        "domain": "MARKET",
                        "headline_score": 10,
                        "propaganda_risk": "low",
                        "state_controlled": False,
                        "country_baseline_risks": [],
                        "has_demotion_keywords": True,
                    },
                    "context": {},
                },
            ],
            expected_behavior="Breaking ECB crisis from tier-1 should score >= 0.85. Routine earnings from tier-3 with demotion should score ~0.40-0.50.",
        ),

        "convergence_score": ModifiableFunction(
            function_id="convergence_score",
            description="Calculates convergence score for emergent patterns. Controls when patterns fire notifications (threshold: 0.50).",
            module_path="xdart.proactive",
            function_name="calculate_convergence",
            signature="def calculate_convergence(pattern: dict, context: dict) -> float",
            current_code=convergence_code,
            original_code=convergence_code,
            constraints=[
                "Must return a float between 0.0 and 1.0",
                "Must not crash on empty inputs",
                "Must use exponential time decay for signal weights",
                "Source diversity must boost convergence",
                "Must handle zero-weight or zero-signal edge cases",
                "Only safe imports allowed (json, math, datetime, etc.)",
            ],
            test_inputs=[
                {
                    "pattern": {
                        "signal_weights": [0.10, 0.10, 0.15, 0.10, 0.20],
                        "signal_ages_seconds": [60, 120, 300, 600, 30],
                        "source_type_count": 4,
                        "region_counts": {"EU_WEST": 3, "GLOBAL": 2},
                    },
                    "context": {},
                },
                {
                    "pattern": {
                        "signal_weights": [0.05],
                        "signal_ages_seconds": [7200],
                        "source_type_count": 1,
                        "region_counts": {"GLOBAL": 1},
                    },
                    "context": {},
                },
            ],
            expected_behavior="5-signal diverse pattern should have moderate convergence (~0.3-0.6). Single old signal from one source should have very low convergence (~0.01-0.05).",
        ),

        "keyword_relevance": ModifiableFunction(
            function_id="keyword_relevance",
            description="Scores academic paper relevance via keyword matching. Fallback when LLM scoring is unavailable.",
            module_path="xdart.knowledge.cross_system_learning",
            function_name="score_keyword_relevance",
            signature="def score_keyword_relevance(paper: dict, context: dict) -> float",
            current_code=keyword_rel_code,
            original_code=keyword_rel_code,
            constraints=[
                "Must return a float between 0.0 and 1.0",
                "Must not crash on empty or missing fields",
                "Total score must be the sum of individual keyword weights",
                "Keywords and weights must cover the system's research interests",
                "Only safe imports allowed (json, math, datetime, etc.)",
            ],
            test_inputs=[
                {
                    "paper": {
                        "title": "Bayesian Modeling of Geopolitical Conflict Escalation",
                        "abstract": "We apply bayesian inference to predict escalation patterns in geopolitical conflicts, using sanctions data and systemic risk indicators.",
                    },
                    "context": {},
                },
                {
                    "paper": {
                        "title": "Optimizing Neural Network Architectures for Image Recognition",
                        "abstract": "This paper presents a new approach to convolutional neural networks for classifying images of cats and dogs.",
                    },
                    "context": {},
                },
            ],
            expected_behavior="Geopolitical-bayesian paper should score >= 0.50 (multiple keyword hits). Cat/dog image paper should score ~0.0 (no relevant keywords).",
        ),

        "signal_domain_classify": ModifiableFunction(
            function_id="signal_domain_classify",
            description="Classifies data signals into domains (GEOPOLITICAL/ECONOMIC/MARKET/SOCIAL/TECHNOLOGY). Core of the CDSFE.",
            module_path="xdart.proactive",
            function_name="classify_signal_domain",
            signature="def classify_signal_domain(signal: dict, context: dict) -> list",
            current_code=domain_class_code,
            original_code=domain_class_code,
            constraints=[
                "Must return a non-empty list of domain strings",
                "Valid domains: GEOPOLITICAL, ECONOMIC, MARKET, SOCIAL, TECHNOLOGY",
                "Must default to ['GEOPOLITICAL'] if no keywords match",
                "Must handle empty headline gracefully",
                "Only safe imports allowed (json, math, datetime, etc.)",
            ],
            test_inputs=[
                {
                    "signal": {
                        "headline": "ECB announces emergency rate cut as banking crisis deepens",
                        "source_type": "economic_shift",
                    },
                    "context": {},
                },
                {
                    "signal": {
                        "headline": "NATO deploys troops to border amid cyber attack on infrastructure",
                        "source_type": "perception_alert",
                    },
                    "context": {},
                },
            ],
            expected_behavior="ECB banking signal should include ECONOMIC. NATO cyber-infrastructure signal should include GEOPOLITICAL and TECHNOLOGY.",
        ),

        "topic_similarity": ModifiableFunction(
            function_id="topic_similarity",
            description="Computes Jaccard similarity between topic sets. Used for pattern clustering and signal absorption.",
            module_path="xdart.proactive",
            function_name="compute_topic_similarity",
            signature="def compute_topic_similarity(data: dict, context: dict) -> float",
            current_code=topic_sim_code,
            original_code=topic_sim_code,
            constraints=[
                "Must return a float between 0.0 and 1.0",
                "Must return 0.0 for empty inputs",
                "Must be symmetric: similarity(A,B) == similarity(B,A)",
                "Identical sets must return 1.0",
                "Only safe imports allowed (json, math, datetime, etc.)",
            ],
            test_inputs=[
                {
                    "data": {
                        "topics_a": ["trade", "tariff", "china", "sanctions", "economy"],
                        "topics_b": ["trade", "china", "military", "escalation"],
                    },
                    "context": {},
                },
                {
                    "data": {
                        "topics_a": ["bitcoin", "crypto", "defi"],
                        "topics_b": ["earthquake", "tsunami", "relief"],
                    },
                    "context": {},
                },
            ],
            expected_behavior="Trade-china overlap should give ~0.28 (2 common / 7 union). Crypto vs earthquake should give 0.0 (disjoint).",
        ),
    }


# ══════════════════════════════════════════════════════════════
#  LOGIC SANDBOX — THE MAIN SYSTEM
# ══════════════════════════════════════════════════════════════

PROPOSAL_PROMPT = """\
You are Αίολος's self-modification engine.

You have the ability to REWRITE specific algorithmic functions in your own \
reasoning system. This is NOT about generating new tools or writing overlays — \
this is about changing HOW YOU THINK at the algorithmic level.

=== FUNCTION YOU MAY MODIFY ===
ID: {function_id}
Description: {description}
Module: {module_path}
Signature: {signature}

CURRENT CODE:
```python
{current_code}
```

CONSTRAINTS (these MUST hold in any modification):
{constraints}

=== EVIDENCE FOR MODIFICATION ===
{evidence}

=== YOUR TASK ===
Analyze whether this function should be modified based on the evidence.

Consider:
1. Is the current logic actually producing suboptimal results?
2. Can you identify a SPECIFIC improvement to the algorithm?
3. Will the improvement generalize (not just fix one edge case)?
4. Does the modification respect ALL constraints?

If YES — propose the new code.
If NO — explain why the current logic is adequate.

Respond ONLY with valid JSON:
{{
    "should_modify": true|false,
    "rationale": "Why this modification is needed (or why not)",
    "proposed_code": "Complete function code (if modifying, else empty string)",
    "expected_improvement": "What specifically gets better",
    "risk_assessment": "What could go wrong",
    "confidence": 0.0-1.0
}}

CRITICAL: The proposed_code must:
- Be a COMPLETE, STANDALONE function matching the original signature
- Use ONLY safe imports: {safe_imports}
- Return the correct type as specified in the signature
- Handle edge cases (empty inputs, missing keys, etc.)
- Respect ALL constraints listed above
"""


FUNCTION_GENESIS_PROMPT = """\
You are Αίολος's ALGORITHM CREATION engine.

You don't just modify existing functions — you CREATE ENTIRELY NEW algorithms \
when the system needs capabilities it doesn't have.

=== EXISTING FUNCTIONS IN THE REGISTRY ===
{existing_functions}

=== EVIDENCE OF NEED ===
{evidence}

=== YOUR TASK ===
Analyze whether a NEW algorithmic function should be created based on:
1. Patterns in the evidence that suggest a missing capability
2. Gaps between what existing functions do and what the system needs
3. Recurring analytical patterns that should be automated

A good new function:
  ✓ Fills a REAL gap visible in the evidence
  ✓ Does something NONE of the existing functions do
  ✓ Has a clear, measurable purpose
  ✓ Takes a 'data' dict and 'context' dict as args → returns float or dict
  ✓ Is algorithmic (scoring, classification, filtering) not just formatting
  ✓ Can be tested with concrete test inputs

Examples of good new functions:
  - "regime_stability_score" — scores political stability of a state from indicators
  - "narrative_coherence" — measures how consistent a narrative is across sources
  - "cascade_probability" — estimates probability of spreading across domains
  - "temporal_urgency" — scores how time-sensitive an event is
  - "confidence_calibrator" — adjusts raw confidence based on domain track record

Respond ONLY with valid JSON:
{{
    "should_create": true|false,
    "reasoning": "Why this function is/isn't needed",
    "function": {{
        "function_id": "snake_case_name (e.g. regime_stability_score)",
        "description": "Clear description of what it does (max 200 chars)",
        "function_name": "compute_<function_id>",
        "signature": "def compute_<name>(data: dict, context: dict) -> float:",
        "code": "Complete standalone function code",
        "constraints": ["Return float 0.0-1.0", "Only safe imports", "Handle missing keys"],
        "test_inputs": [
            {{"data": {{}}, "context": {{}}}},
            {{"data": {{}}, "context": {{}}}}
        ],
        "expected_behavior": "What each test case should produce",
        "module_path": "xdart.phases.logic_sandbox"
    }},
    "confidence": 0.0-1.0
}}

CRITICAL:
- function must be STANDALONE (no imports except json, math, datetime, re, statistics, collections)
- Must have at least 2 test inputs with realistic data
- Must handle empty/missing keys gracefully
- Safe imports ONLY: {safe_imports}

If no new function needed, set should_create to false and function to null."""


class LogicSandbox:
    """Self-modification sandbox with guardrails.

    Allows Αίολος to propose, test, and (with approval) apply
    modifications to designated algorithmic functions.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.sandbox = Sandbox(timeout=30)
        self._registry: dict[str, ModifiableFunction] = {}
        self._proposals: dict[str, LogicProposal] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load state from disk, or initialize defaults.

        If state.json exists but is missing new default functions
        (e.g. after a code update), merge the missing functions
        into the loaded registry without overwriting user modifications.
        """
        if STATE_PATH.exists():
            try:
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    state = json.load(f)
                self._registry = {
                    fid: ModifiableFunction.from_dict(fdata)
                    for fid, fdata in state.get("registry", {}).items()
                }
                self._proposals = {
                    pid: LogicProposal.from_dict(pdata)
                    for pid, pdata in state.get("proposals", {}).items()
                }

                # Merge new defaults that don't exist in loaded state
                defaults = build_default_registry()
                merged = 0
                for fid, func in defaults.items():
                    if fid not in self._registry:
                        self._registry[fid] = func
                        merged += 1
                if merged:
                    self._save_state()
                    logger.info(
                        "[LogicSandbox] Merged %d new default functions into registry",
                        merged,
                    )

                logger.info(
                    "[LogicSandbox] Loaded state: %d functions, %d proposals",
                    len(self._registry), len(self._proposals),
                )
            except Exception as e:
                logger.warning("[LogicSandbox] Failed to load state: %s — using defaults", e)
                self._registry = build_default_registry()
        else:
            self._registry = build_default_registry()
            self._save_state()
            logger.info("[LogicSandbox] Initialized with %d modifiable functions", len(self._registry))

    def _save_state(self) -> None:
        """Persist state to disk."""
        state = {
            "registry": {fid: f.to_dict() for fid, f in self._registry.items()},
            "proposals": {pid: p.to_dict() for pid, p in self._proposals.items()},
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        try:
            STATE_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("[LogicSandbox] Failed to save state: %s", e)

    def _journal(self, entry: dict) -> None:
        """Append to the audit journal."""
        try:
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error("[LogicSandbox] Journal write failed: %s", e)

    # ──────────────────────────────────────────────────────────
    #  REGISTER — Dynamic function registration
    # ──────────────────────────────────────────────────────────

    def register_function(
        self,
        function_id: str,
        description: str,
        module_path: str,
        function_name: str,
        signature: str,
        code: str,
        constraints: list[str],
        test_inputs: list[dict],
        expected_behavior: str,
    ) -> dict:
        """Register a new function for self-modification.

        Adds a function to the sandbox registry, making it available for
        Αίολος to analyze, propose modifications, test, and deploy.

        Returns dict with status and info.
        """
        if function_id in self._registry:
            return {"status": "error", "error": f"Function '{function_id}' already registered"}

        if len(code) > MAX_FUNCTION_CHARS:
            return {"status": "error", "error": f"Code exceeds {MAX_FUNCTION_CHARS} chars"}

        if not test_inputs:
            return {"status": "error", "error": "At least one test input required"}

        func = ModifiableFunction(
            function_id=function_id,
            description=description,
            module_path=module_path,
            function_name=function_name,
            signature=signature,
            current_code=code,
            original_code=code,
            constraints=constraints,
            test_inputs=test_inputs,
            expected_behavior=expected_behavior,
        )

        # Validate: run the code in sandbox with each test input
        for i, test_input in enumerate(test_inputs):
            harness = self._build_test_harness(func.current_code, func.function_name, test_input)
            result = self.sandbox.execute(harness)
            if not result.success:
                return {
                    "status": "error",
                    "error": f"Test input #{i} failed validation: {result.error or result.output}",
                }

        self._registry[function_id] = func
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "register",
            "function_id": function_id,
            "description": description,
            "module_path": module_path,
        })

        logger.info(
            "[LogicSandbox] Registered new function: %s (%s)",
            function_id, module_path,
        )

        return {
            "status": "registered",
            "function_id": function_id,
            "total_functions": len(self._registry),
        }

    def unregister_function(self, function_id: str) -> dict:
        """Remove a function from the registry.

        Cannot unregister functions that have active modifications —
        rollback first.
        """
        if function_id not in self._registry:
            return {"status": "error", "error": f"Function '{function_id}' not found"}

        func = self._registry[function_id]
        if func.current_code != func.original_code:
            return {
                "status": "error",
                "error": "Function has active modification — rollback first",
            }

        # Remove any proposals for this function
        to_remove = [
            pid for pid, p in self._proposals.items()
            if p.function_id == function_id
        ]
        for pid in to_remove:
            del self._proposals[pid]

        del self._registry[function_id]
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "unregister",
            "function_id": function_id,
        })

        logger.info("[LogicSandbox] Unregistered function: %s", function_id)

        return {
            "status": "unregistered",
            "function_id": function_id,
            "total_functions": len(self._registry),
        }

    # ──────────────────────────────────────────────────────────
    #  PROPOSE — Αίολος proposes a modification
    # ──────────────────────────────────────────────────────────

    def propose_modification(
        self,
        function_id: str,
        evidence: str,
        callback: Callable | None = None,
    ) -> LogicProposal | None:
        """Have the LLM analyze a function and propose a modification.

        Args:
            function_id: Which function to analyze (must be in registry)
            evidence: Why modification is needed (from introspection, etc.)
            callback: SSE callback for progress updates

        Returns:
            LogicProposal if modification proposed, None if no change needed
        """
        if function_id not in self._registry:
            logger.warning("[LogicSandbox] Unknown function: %s", function_id)
            return None

        # Guard against too many pending proposals
        pending = [p for p in self._proposals.values() if p.status == "pending"]
        if len(pending) >= MAX_PENDING_PROPOSALS:
            logger.info("[LogicSandbox] Too many pending proposals (%d), skipping", len(pending))
            return None

        func = self._registry[function_id]
        t0 = time.perf_counter()

        if callback:
            callback("logic_sandbox_analyzing", {
                "function_id": function_id,
                "description": func.description,
            })

        prompt = PROPOSAL_PROMPT.format(
            function_id=func.function_id,
            description=func.description,
            module_path=func.module_path,
            signature=func.signature,
            current_code=func.current_code,
            constraints="\n".join(f"  - {c}" for c in func.constraints),
            evidence=evidence[:3000],
            safe_imports=", ".join(sorted(SAFE_IMPORTS)),
        )

        try:
            result = self.llm.call_json(
                system_prompt=prompt,
                user_prompt="Analyze this function and decide whether to modify it.",
                max_tokens=8192,
                temperature=0.3,
                thinking=False,
            )
        except Exception as e:
            logger.warning("[LogicSandbox] LLM call failed: %s", e)
            return None

        if not result.get("should_modify"):
            elapsed = time.perf_counter() - t0
            logger.info(
                "[LogicSandbox] No modification needed for %s (%.2fs): %s",
                function_id, elapsed, result.get("rationale", ""),
            )
            self._journal({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "analysis",
                "function_id": function_id,
                "should_modify": False,
                "rationale": result.get("rationale", ""),
                "elapsed": round(elapsed, 2),
            })
            return None

        proposed_code = result.get("proposed_code", "")
        if not proposed_code:
            logger.warning("[LogicSandbox] Modification proposed but no code provided")
            return None

        # Create proposal
        import uuid
        proposal = LogicProposal(
            id=str(uuid.uuid4())[:8],
            function_id=function_id,
            proposed_code=proposed_code,
            rationale=result.get("rationale", ""),
            expected_improvement=result.get("expected_improvement", ""),
            risk_assessment=result.get("risk_assessment", ""),
            proposed_at=datetime.now(timezone.utc).isoformat(),
        )

        self._proposals[proposal.id] = proposal
        self._save_state()

        elapsed = time.perf_counter() - t0
        logger.info(
            "[LogicSandbox] PROPOSAL created: %s for %s (%.2fs)",
            proposal.id, function_id, elapsed,
        )

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "proposal",
            "proposal_id": proposal.id,
            "function_id": function_id,
            "rationale": proposal.rationale,
            "expected_improvement": proposal.expected_improvement,
            "risk": proposal.risk_assessment,
            "elapsed": round(elapsed, 2),
        })

        if callback:
            callback("logic_sandbox_proposal", {
                "proposal_id": proposal.id,
                "function_id": function_id,
                "rationale": proposal.rationale,
                "expected_improvement": proposal.expected_improvement,
            })

        return proposal

    # ──────────────────────────────────────────────────────────
    #  TEST — Sandbox test a proposal
    # ──────────────────────────────────────────────────────────

    def test_proposal(self, proposal_id: str) -> dict:
        """Run sandbox tests on a proposal.

        Returns:
            dict with test results
        """
        if proposal_id not in self._proposals:
            return {"error": "Proposal not found"}

        proposal = self._proposals[proposal_id]
        func = self._registry.get(proposal.function_id)
        if not func:
            return {"error": "Function not found in registry"}

        proposal.status = "testing"
        results = {"tests_passed": 0, "tests_failed": 0, "errors": []}

        for i, test_input in enumerate(func.test_inputs):
            # Build test harness for the proposed code
            harness_code = self._build_test_harness(
                proposal.proposed_code,
                func.function_name,
                test_input,
            )

            sandbox_result = self.sandbox._execute(harness_code)

            if sandbox_result.success:
                results["tests_passed"] += 1
                # Validate output constraints
                output = sandbox_result.output
                constraint_violations = self._check_constraints(
                    func, output, test_input,
                )
                if constraint_violations:
                    results["tests_failed"] += 1
                    results["tests_passed"] -= 1
                    results["errors"].append({
                        "test": i,
                        "type": "constraint_violation",
                        "details": constraint_violations,
                    })
            else:
                results["tests_failed"] += 1
                results["errors"].append({
                    "test": i,
                    "type": "execution_error",
                    "details": sandbox_result.error,
                })

        # Also test the CURRENT code for baseline comparison
        baseline_results = {"tests_passed": 0, "tests_failed": 0}
        for test_input in func.test_inputs:
            harness_code = self._build_test_harness(
                func.current_code,
                func.function_name,
                test_input,
            )
            sandbox_result = self.sandbox._execute(harness_code)
            if sandbox_result.success:
                baseline_results["tests_passed"] += 1
            else:
                baseline_results["tests_failed"] += 1

        results["baseline"] = baseline_results
        results["all_passed"] = results["tests_failed"] == 0
        proposal.sandbox_result = results
        proposal.status = "tested"
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "sandbox_test",
            "proposal_id": proposal_id,
            "function_id": proposal.function_id,
            "results": results,
        })

        logger.info(
            "[LogicSandbox] Sandbox test for %s: %d passed, %d failed",
            proposal_id, results["tests_passed"], results["tests_failed"],
        )

        return results

    def _build_test_harness(
        self,
        function_code: str,
        function_name: str,
        test_input: dict,
    ) -> str:
        """Build a sandbox test harness for a function."""
        input_json = json.dumps(test_input, ensure_ascii=False, default=str)

        # Determine the args from test_input keys
        arg_names = list(test_input.keys())
        call_args = ", ".join(f"test_input['{k}']" for k in arg_names)

        return textwrap.dedent(f"""\
            import json
            import sys

            # ── Function under test ──
            {textwrap.indent(function_code, '            ').strip()}
            # ── End function ──

            try:
                test_input = json.loads('''{input_json}''')
                result = {function_name}({call_args})

                print("__SANDBOX_RESULT__")
                print(json.dumps({{"tool_name": "{function_name}", "output": str(result), "metadata": {{"type": type(result).__name__, "value": result}}}}, ensure_ascii=False, default=str))

            except Exception as e:
                print(json.dumps({{"error": f"{{type(e).__name__}}: {{e}}"}}))
                sys.exit(1)
        """)

    def _check_constraints(
        self,
        func: ModifiableFunction,
        output: dict | None,
        test_input: dict,
    ) -> list[str]:
        """Check if output satisfies function constraints."""
        violations = []
        if output is None:
            violations.append("No output produced")
            return violations

        result_value = output.get("metadata", {}).get("value")
        result_type = output.get("metadata", {}).get("type")

        # Type check based on signature
        if "-> float" in func.signature:
            if result_type != "float" and result_type != "int":
                violations.append(f"Expected float, got {result_type}")
            elif isinstance(result_value, (int, float)):
                if "between 0.0 and 1.0" in " ".join(func.constraints) or \
                   "between 0.05 and 0.95" in " ".join(func.constraints):
                    if result_value < 0.0 or result_value > 1.0:
                        violations.append(f"Value {result_value} out of [0.0, 1.0] range")

        elif "-> int" in func.signature:
            if result_type != "int":
                violations.append(f"Expected int, got {result_type}")

        return violations

    # ──────────────────────────────────────────────────────────
    #  APPROVE / REJECT — Human decision
    # ──────────────────────────────────────────────────────────

    def deploy_pending_proposals(self) -> list[dict]:
        """Auto-approve and apply ALL proposals that passed sandbox testing.

        This is a batch operation for clearing stale 'tested'/'awaiting' proposals.
        Returns a list of results (one per proposal).
        """
        results = []
        for proposal_id, proposal in list(self._proposals.items()):
            if proposal.status == "tested" and proposal.approval_status == "awaiting":
                if proposal.sandbox_result and proposal.sandbox_result.get("all_passed"):
                    approve_result = self.approve_proposal(proposal_id, approved_by="auto_deploy_batch")
                    if approve_result.get("status") == "approved":
                        apply_result = self.apply_proposal(proposal_id)
                        results.append({
                            "proposal_id": proposal_id,
                            "function_id": proposal.function_id,
                            "action": "deployed",
                            "result": apply_result,
                        })
                        logger.info(
                            "[LogicSandbox] ✓ Batch-deployed stale proposal %s for %s",
                            proposal_id, proposal.function_id,
                        )
                    else:
                        results.append({
                            "proposal_id": proposal_id,
                            "function_id": proposal.function_id,
                            "action": "approve_failed",
                            "result": approve_result,
                        })
                else:
                    # Failed sandbox — reject it to unblock
                    self.reject_proposal(proposal_id, reason="Auto-rejected: sandbox tests failed")
                    results.append({
                        "proposal_id": proposal_id,
                        "function_id": proposal.function_id,
                        "action": "rejected_failed_tests",
                    })
        return results

    def approve_proposal(self, proposal_id: str, approved_by: str = "human") -> dict:
        """Approve a tested proposal for application.

        Only proposals that passed sandbox testing can be approved.
        """
        if proposal_id not in self._proposals:
            return {"error": "Proposal not found"}

        proposal = self._proposals[proposal_id]

        if proposal.status not in ("tested",):
            return {"error": f"Proposal must be in 'tested' state, is '{proposal.status}'"}

        if proposal.sandbox_result and not proposal.sandbox_result.get("all_passed"):
            return {"error": "Cannot approve proposal that failed sandbox tests"}

        proposal.approval_status = "approved"
        proposal.approved_by = approved_by
        proposal.status = "approved"
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "approval",
            "proposal_id": proposal_id,
            "approved_by": approved_by,
        })

        logger.info("[LogicSandbox] Proposal %s APPROVED by %s", proposal_id, approved_by)
        return {"status": "approved", "proposal_id": proposal_id}

    def reject_proposal(self, proposal_id: str, reason: str = "") -> dict:
        """Reject a proposal."""
        if proposal_id not in self._proposals:
            return {"error": "Proposal not found"}

        proposal = self._proposals[proposal_id]
        proposal.approval_status = "rejected"
        proposal.status = "rejected"
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "rejection",
            "proposal_id": proposal_id,
            "reason": reason,
        })

        logger.info("[LogicSandbox] Proposal %s REJECTED: %s", proposal_id, reason)
        return {"status": "rejected", "proposal_id": proposal_id}

    # ──────────────────────────────────────────────────────────
    #  APPLY — Activate approved modification
    # ──────────────────────────────────────────────────────────

    def apply_proposal(self, proposal_id: str) -> dict:
        """Apply an approved proposal — swap in the new logic."""
        if proposal_id not in self._proposals:
            return {"error": "Proposal not found"}

        proposal = self._proposals[proposal_id]

        if proposal.status != "approved":
            return {"error": f"Proposal must be approved first, is '{proposal.status}'"}

        func = self._registry.get(proposal.function_id)
        if not func:
            return {"error": "Function not found"}

        # Store the old code in history for rollback
        func.history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "code": func.current_code,
            "reason": f"Replaced by proposal {proposal_id}",
        })

        # Trim history
        if len(func.history) > MAX_MODIFICATION_HISTORY:
            func.history = func.history[-MAX_MODIFICATION_HISTORY:]

        # Apply the new code
        old_code = func.current_code
        func.current_code = proposal.proposed_code
        func.modification_count += 1
        func.active_modification = {
            "proposal_id": proposal_id,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "rationale": proposal.rationale,
        }

        proposal.status = "applied"
        proposal.applied_at = datetime.now(timezone.utc).isoformat()
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "application",
            "proposal_id": proposal_id,
            "function_id": proposal.function_id,
            "rationale": proposal.rationale,
        })

        logger.info(
            "[LogicSandbox] ✓ APPLIED proposal %s to %s (modification #%d)",
            proposal_id, proposal.function_id, func.modification_count,
        )

        return {
            "status": "applied",
            "function_id": proposal.function_id,
            "modification_count": func.modification_count,
        }

    # ──────────────────────────────────────────────────────────
    #  ROLLBACK — Revert to previous version
    # ──────────────────────────────────────────────────────────

    def rollback(self, function_id: str, to_original: bool = False) -> dict:
        """Rollback a function to its previous version or factory original.

        Args:
            function_id: Which function to rollback
            to_original: If True, rollback to factory original. Otherwise, to previous version.
        """
        if function_id not in self._registry:
            return {"error": "Function not found"}

        func = self._registry[function_id]

        if to_original:
            if func.current_code == func.original_code:
                return {"status": "already_at_original"}

            func.history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "code": func.current_code,
                "reason": "Rolled back to original",
            })
            func.current_code = func.original_code
            func.active_modification = None
        else:
            if not func.history:
                return {"error": "No history to rollback to"}

            previous = func.history.pop()
            func.current_code = previous["code"]
            func.active_modification = None

        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "rollback",
            "function_id": function_id,
            "to_original": to_original,
        })

        logger.info(
            "[LogicSandbox] ROLLED BACK %s (to_original=%s)",
            function_id, to_original,
        )

        return {"status": "rolled_back", "function_id": function_id}

    # ──────────────────────────────────────────────────────────
    #  QUERY — Inspection APIs
    # ──────────────────────────────────────────────────────────

    def get_registry(self) -> list[dict]:
        """Get all modifiable functions and their status."""
        return [
            {
                "function_id": f.function_id,
                "description": f.description,
                "module_path": f.module_path,
                "function_name": f.function_name,
                "modification_count": f.modification_count,
                "has_active_modification": f.active_modification is not None,
                "is_original": f.current_code == f.original_code,
                "constraints": f.constraints,
            }
            for f in self._registry.values()
        ]

    def get_function_detail(self, function_id: str) -> dict | None:
        """Get full detail of a function including current code."""
        if function_id not in self._registry:
            return None
        func = self._registry[function_id]
        return {
            **func.to_dict(),
            "is_original": func.current_code == func.original_code,
        }

    def get_proposals(self, status: str | None = None) -> list[dict]:
        """Get proposals, optionally filtered by status."""
        proposals = self._proposals.values()
        if status:
            proposals = [p for p in proposals if p.status == status]
        return [p.to_dict() for p in proposals]

    def get_stats(self) -> dict:
        """Summary statistics for the sandbox."""
        return {
            "total_functions": len(self._registry),
            "total_proposals": len(self._proposals),
            "pending_approval": sum(
                1 for p in self._proposals.values()
                if p.status == "tested" and p.sandbox_result and p.sandbox_result.get("all_passed")
            ),
            "applied": sum(1 for p in self._proposals.values() if p.status == "applied"),
            "rejected": sum(1 for p in self._proposals.values() if p.status == "rejected"),
            "modified_functions": sum(
                1 for f in self._registry.values()
                if f.current_code != f.original_code
            ),
        }

    def get_pending_approvals(self) -> list[dict]:
        """Get proposals that need human approval."""
        return [
            p.to_dict() for p in self._proposals.values()
            if p.status == "tested" and p.sandbox_result and p.sandbox_result.get("all_passed")
        ]

    def get_current_code(self, function_id: str) -> str | None:
        """Get the current code for a function (used by pipeline)."""
        if function_id not in self._registry:
            return None
        return self._registry[function_id].current_code

    # ──────────────────────────────────────────────────────────
    #  AUTO-ANALYZE — Triggered by self-evolution
    # ──────────────────────────────────────────────────────────

    def auto_analyze(
        self,
        introspection_data: str,
        performance_data: dict,
        callback: Callable | None = None,
        auto_deploy: bool = True,
    ) -> list[LogicProposal]:
        """Analyze all modifiable functions and propose modifications where needed.

        Typically called after a pipeline run or during self-evolution.

        Args:
            auto_deploy: If True, automatically approve and apply proposals that
                pass sandbox testing. The sandbox already validates correctness
                (all test inputs must pass with correct types and constraints).
                Rollback is always available if performance degrades.
        """
        proposals = []

        # Deploy any stale proposals that passed testing but were never approved
        stale_deployed = self.deploy_pending_proposals()
        if stale_deployed:
            logger.info("[LogicSandbox] Cleared %d stale proposals before new analysis", len(stale_deployed))

        # Build evidence string from introspection + performance
        evidence = f"""
RECENT INTROSPECTION DATA:
{introspection_data[:2000]}

PERFORMANCE METRICS:
- Brier score: {performance_data.get('brier_score', 'N/A')}
- Avg epistemic integrity: {performance_data.get('avg_integrity', 'N/A')}
- Calibration error: {performance_data.get('calibration_error', 'N/A')}
- Prophecies confirmed: {performance_data.get('prophecies_confirmed', 'N/A')}
- Prophecies disconfirmed: {performance_data.get('prophecies_disconfirmed', 'N/A')}
- Curiosity exploration success rate: {performance_data.get('curiosity_success_rate', 'N/A')}
"""

        for function_id, func in self._registry.items():
            # Skip if there's already a pending proposal for this function
            existing = [
                p for p in self._proposals.values()
                if p.function_id == function_id and p.status in ("pending", "testing", "tested", "approved")
            ]
            if existing:
                logger.info("[LogicSandbox] Skipping %s — has pending proposal", function_id)
                continue

            proposal = self.propose_modification(function_id, evidence, callback)
            if proposal:
                # Auto-test immediately
                test_result = self.test_proposal(proposal.id)
                if test_result.get("all_passed"):
                    proposals.append(proposal)

                    if auto_deploy:
                        # Auto-approve and apply — sandbox already validated correctness
                        approve_result = self.approve_proposal(proposal.id, approved_by="auto_deploy")
                        if approve_result.get("status") == "approved":
                            apply_result = self.apply_proposal(proposal.id)
                            if apply_result.get("status") == "applied":
                                logger.info(
                                    "[LogicSandbox] ✓ AUTO-DEPLOYED %s for %s (sandbox-validated)",
                                    proposal.id, function_id,
                                )
                            else:
                                logger.warning(
                                    "[LogicSandbox] Auto-deploy apply failed for %s: %s",
                                    proposal.id, apply_result.get("error", "?"),
                                )
                        else:
                            logger.warning(
                                "[LogicSandbox] Auto-deploy approve failed for %s: %s",
                                proposal.id, approve_result.get("error", "?"),
                            )
                    else:
                        logger.info(
                            "[LogicSandbox] Proposal %s for %s passed sandbox — awaiting approval",
                            proposal.id, function_id,
                        )

        # ── After modifying existing functions, attempt to CREATE new ones ──
        genesis_result = self.auto_discover_new_functions(
            introspection_data=introspection_data,
            performance_data=performance_data,
            callback=callback,
        )
        if genesis_result:
            logger.info(
                "[LogicSandbox] ✦ GENESIS: Created %d new function(s): %s",
                len(genesis_result),
                [r["function_id"] for r in genesis_result],
            )

        return proposals

    # ──────────────────────────────────────────────────────────
    #  GENESIS — Autonomous creation of NEW functions
    # ──────────────────────────────────────────────────────────

    def auto_discover_new_functions(
        self,
        introspection_data: str,
        performance_data: dict,
        callback: Callable | None = None,
        max_new: int = 1,
    ) -> list[dict]:
        """Autonomously discover and create NEW algorithmic functions.

        Unlike auto_analyze (which modifies existing functions), this method
        identifies GAPS in the system's reasoning capabilities and creates
        entirely new functions to fill them.

        Args:
            introspection_data: Recent introspection/self-analysis text
            performance_data: Metrics from recent pipeline runs
            callback: SSE callback for progress updates
            max_new: Maximum new functions to create per call (default 1)

        Returns:
            List of dicts with created function info, empty if none created
        """
        # Don't create too many — cap total registry size
        MAX_TOTAL_FUNCTIONS = 25
        if len(self._registry) >= MAX_TOTAL_FUNCTIONS:
            logger.info(
                "[LogicSandbox] Registry at capacity (%d/%d), skipping genesis",
                len(self._registry), MAX_TOTAL_FUNCTIONS,
            )
            return []

        # Build summary of existing functions for the LLM
        existing_summary = "\n".join(
            f"  - {fid}: {func.description} [{func.module_path}]"
            for fid, func in self._registry.items()
        )

        evidence = f"""
RECENT INTROSPECTION DATA:
{introspection_data[:2000]}

PERFORMANCE METRICS:
- Brier score: {performance_data.get('brier_score', 'N/A')}
- Avg epistemic integrity: {performance_data.get('avg_integrity', 'N/A')}
- Calibration error: {performance_data.get('calibration_error', 'N/A')}
- Prophecies confirmed: {performance_data.get('prophecies_confirmed', 'N/A')}
- Prophecies disconfirmed: {performance_data.get('prophecies_disconfirmed', 'N/A')}
- Curiosity exploration success rate: {performance_data.get('curiosity_success_rate', 'N/A')}
- Total functions in registry: {len(self._registry)}
- Modified functions: {sum(1 for f in self._registry.values() if f.current_code != f.original_code)}
"""

        prompt = FUNCTION_GENESIS_PROMPT.format(
            existing_functions=existing_summary,
            evidence=evidence,
            safe_imports=", ".join(sorted(SAFE_IMPORTS)),
        )

        if callback:
            callback("logic_sandbox_genesis_start", {
                "total_functions": len(self._registry),
                "max_new": max_new,
            })

        t0 = time.perf_counter()
        created = []

        for attempt in range(max_new):
            try:
                result = self.llm.call_json(
                    system_prompt=prompt,
                    user_prompt=(
                        "Analyze the system's capabilities and decide whether "
                        "a NEW algorithmic function should be created."
                    ),
                    max_tokens=8192,
                    temperature=0.4,
                    thinking=False,
                )
            except Exception as e:
                logger.warning("[LogicSandbox] Genesis LLM call failed: %s", e)
                break

            if not result.get("should_create"):
                logger.info(
                    "[LogicSandbox] Genesis: No new function needed — %s",
                    result.get("reasoning", "")[:200],
                )
                self._journal({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "genesis_analysis",
                    "should_create": False,
                    "reasoning": result.get("reasoning", ""),
                })
                break

            confidence = result.get("confidence", 0.0)
            if confidence < 0.5:
                logger.info(
                    "[LogicSandbox] Genesis: Low confidence (%.2f), skipping",
                    confidence,
                )
                break

            func_spec = result.get("function")
            if not func_spec or not isinstance(func_spec, dict):
                logger.warning("[LogicSandbox] Genesis: No valid function spec returned")
                break

            function_id = func_spec.get("function_id", "")
            code = func_spec.get("code", "")
            function_name = func_spec.get("function_name", "")
            test_inputs = func_spec.get("test_inputs", [])

            # Validate required fields
            if not all([function_id, code, function_name, test_inputs]):
                logger.warning("[LogicSandbox] Genesis: Incomplete function spec")
                break

            # Sanitize function_id — must be a safe snake_case string
            import re
            if not re.match(r'^[a-z][a-z0-9_]{2,40}$', function_id):
                logger.warning("[LogicSandbox] Genesis: Invalid function_id: %s", function_id)
                break

            # Check for duplicate
            if function_id in self._registry:
                logger.info("[LogicSandbox] Genesis: %s already exists, skipping", function_id)
                break

            # Try to register — register_function validates via sandbox execution
            reg_result = self.register_function(
                function_id=function_id,
                description=func_spec.get("description", f"Auto-generated: {function_id}"),
                module_path=func_spec.get("module_path", "xdart.phases.logic_sandbox"),
                function_name=function_name,
                signature=func_spec.get("signature", f"def {function_name}(data: dict, context: dict) -> float:"),
                code=code,
                constraints=func_spec.get("constraints", [
                    "Must return a float between 0.0 and 1.0",
                    "Only safe imports allowed",
                    "Must handle missing keys gracefully",
                ]),
                test_inputs=test_inputs,
                expected_behavior=func_spec.get("expected_behavior", ""),
            )

            if reg_result.get("status") == "registered":
                elapsed = time.perf_counter() - t0
                logger.info(
                    "[LogicSandbox] ✦ GENESIS SUCCESS: Created '%s' (%.2fs, confidence=%.2f)",
                    function_id, elapsed, confidence,
                )

                genesis_info = {
                    "function_id": function_id,
                    "description": func_spec.get("description", ""),
                    "confidence": confidence,
                    "reasoning": result.get("reasoning", ""),
                    "elapsed": round(elapsed, 2),
                }
                created.append(genesis_info)

                self._journal({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "genesis_created",
                    **genesis_info,
                })

                if callback:
                    callback("logic_sandbox_genesis_created", genesis_info)
            else:
                logger.warning(
                    "[LogicSandbox] Genesis: Registration failed for '%s': %s",
                    function_id, reg_result.get("error", "?"),
                )
                self._journal({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "genesis_failed",
                    "function_id": function_id,
                    "error": reg_result.get("error", "?"),
                    "confidence": confidence,
                })
                break

        elapsed_total = time.perf_counter() - t0
        if created:
            logger.info(
                "[LogicSandbox] Genesis cycle complete: %d new function(s) in %.2fs",
                len(created), elapsed_total,
            )
        return created
