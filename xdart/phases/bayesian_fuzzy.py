"""
XDART-Φ — Phase 2.92: Bayesian-Fuzzy Reasoning Engine

Hybrid reasoning combining Fuzzy Logic qualitative-to-quantitative mapping
with Bayesian Network posterior probability updates.

Origin: Proposed by Αίολος via CuriosityEngine (priority 0.90) for
IAEA nuclear proliferation risk quantification. Extended to financial
stress analysis and general-purpose probabilistic reasoning.

Architecture:
  1. LLM extracts qualitative indicators from scenarios + world context
  2. Fuzzy Logic maps qualitative → membership degrees μ ∈ [0, 1]
  3. Bayesian Network updates P(H) → P(H|E) using fuzzy soft evidence
  4. LLM synthesizes risk narrative from posterior distributions

Mathematical Foundation:
  Fuzzy:   μ_A(x) ∈ [0,1] via triangular/trapezoidal membership functions
  Bayes:   P(H|E) = P(E|H)·P(H) / P(E)
  Bridge:  Fuzzy memberships = soft evidence for Jeffrey's rule update
           P'(H) = Σ_e P(H|E=e) · μ(e) — weighted posterior mixture
"""

import json
import logging
import math
import time

from xdart.config import BAYESIAN_FUZZY_PRIOR_WEIGHT
from xdart.llm import LLMClient
from xdart.models import (
    BayesianFuzzyResult,
    BayesianNodeState,
    FuzzyEvidence,
    RiskPosterior,
    Scenario,
    ScenarioTribunalResult,
)

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Fuzzy Membership Functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def triangular_mf(x: float, a: float, b: float, c: float) -> float:
    """Triangular membership function: peaks at b, zero outside [a, c].

    μ(x) = max(min((x-a)/(b-a), (c-x)/(c-b)), 0)
    """
    if x <= a or x >= c:
        return 0.0
    elif x <= b:
        return (x - a) / (b - a) if b != a else 1.0
    else:
        return (c - x) / (c - b) if c != b else 1.0


def trapezoidal_mf(x: float, a: float, b: float, c: float, d: float) -> float:
    """Trapezoidal membership function: full membership in [b, c], zero outside [a, d].

    μ(x) = max(min((x-a)/(b-a), 1, (d-x)/(d-c)), 0)
    """
    if x <= a or x >= d:
        return 0.0
    elif x < b:
        return (x - a) / (b - a) if b != a else 1.0
    elif x <= c:
        return 1.0
    else:
        return (d - x) / (d - c) if d != c else 1.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Domain Templates — Fuzzy Variable Definitions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Each template defines:
#   variables:     observable indicator → {terms: {name: (mf_type, params)}}
#   latent_nodes:  hidden risk variables to infer
#   causal_edges:  (parent, child) in the Bayesian DAG
#   priors:        P(latent_node) initial distribution
#

DOMAIN_TEMPLATES: dict[str, dict] = {

    # ── Nuclear Proliferation (IAEA data) ──────────────────
    "nuclear_proliferation": {
        "description": "IAEA nuclear proliferation risk — inspection delays, enrichment, capability",
        "variables": {
            "inspection_delay": {
                "description": "Delay or obstruction of IAEA inspections",
                "terms": {
                    "minimal":      ("trapezoidal", (0.0, 0.0, 0.1, 0.3)),
                    "moderate":     ("triangular",  (0.1, 0.35, 0.6)),
                    "significant":  ("triangular",  (0.4, 0.65, 0.85)),
                    "critical":     ("trapezoidal", (0.7, 0.9, 1.0, 1.0)),
                },
            },
            "technical_capability": {
                "description": "Technical advancement toward weapons capability",
                "terms": {
                    "nascent":       ("trapezoidal", (0.0, 0.0, 0.15, 0.35)),
                    "developing":    ("triangular",  (0.2, 0.4, 0.6)),
                    "advanced":      ("triangular",  (0.45, 0.7, 0.9)),
                    "weaponizable":  ("trapezoidal", (0.75, 0.9, 1.0, 1.0)),
                },
            },
            "enrichment_level": {
                "description": "Uranium enrichment beyond declared peaceful purposes",
                "terms": {
                    "leu":             ("trapezoidal", (0.0, 0.0, 0.1, 0.3)),
                    "moderate":        ("triangular",  (0.15, 0.35, 0.55)),
                    "heu_threshold":   ("triangular",  (0.4, 0.65, 0.85)),
                    "weapons_grade":   ("trapezoidal", (0.7, 0.9, 1.0, 1.0)),
                },
            },
            "diplomatic_signals": {
                "description": "Diplomatic posture toward nonproliferation regime",
                "terms": {
                    "cooperative": ("trapezoidal", (0.0, 0.0, 0.15, 0.35)),
                    "ambiguous":   ("triangular",  (0.2, 0.45, 0.7)),
                    "defiant":     ("triangular",  (0.5, 0.7, 0.9)),
                    "hostile":     ("trapezoidal", (0.75, 0.9, 1.0, 1.0)),
                },
            },
            "treaty_compliance": {
                "description": "Compliance with NPT and safeguards agreements",
                "terms": {
                    "full":           ("trapezoidal", (0.0, 0.0, 0.1, 0.25)),
                    "partial":        ("triangular",  (0.15, 0.4, 0.65)),
                    "non_compliant":  ("triangular",  (0.5, 0.7, 0.9)),
                    "withdrawn":      ("trapezoidal", (0.8, 0.9, 1.0, 1.0)),
                },
            },
        },
        "latent_nodes": ["proliferation_risk", "breakout_timeline"],
        "causal_edges": [
            ("inspection_delay",     "proliferation_risk"),
            ("technical_capability", "proliferation_risk"),
            ("enrichment_level",     "proliferation_risk"),
            ("diplomatic_signals",   "proliferation_risk"),
            ("treaty_compliance",    "proliferation_risk"),
            ("technical_capability", "breakout_timeline"),
            ("enrichment_level",     "breakout_timeline"),
            ("proliferation_risk",   "breakout_timeline"),
        ],
        "priors": {
            "proliferation_risk": {"low": 0.50, "medium": 0.30, "high": 0.15, "critical": 0.05},
            "breakout_timeline":  {"years": 0.40, "months": 0.30, "weeks": 0.20, "imminent": 0.10},
        },
    },

    # ── Financial Stress (macro data) ──────────────────────
    "financial_stress": {
        "description": "Financial systemic stress and regime shift assessment",
        "variables": {
            "yield_curve": {
                "description": "Yield curve shape — inversion signals recession risk",
                "terms": {
                    "normal":          ("trapezoidal", (0.0, 0.0, 0.15, 0.35)),
                    "flattening":      ("triangular",  (0.2, 0.4, 0.6)),
                    "inverted":        ("triangular",  (0.45, 0.7, 0.85)),
                    "deeply_inverted": ("trapezoidal", (0.7, 0.85, 1.0, 1.0)),
                },
            },
            "credit_spreads": {
                "description": "High-yield credit spread widening — stress indicator",
                "terms": {
                    "tight":      ("trapezoidal", (0.0, 0.0, 0.1, 0.3)),
                    "normal":     ("triangular",  (0.15, 0.35, 0.55)),
                    "widening":   ("triangular",  (0.4, 0.65, 0.85)),
                    "distressed": ("trapezoidal", (0.7, 0.9, 1.0, 1.0)),
                },
            },
            "fx_volatility": {
                "description": "Currency market volatility and stress",
                "terms": {
                    "calm":     ("trapezoidal", (0.0, 0.0, 0.1, 0.3)),
                    "elevated": ("triangular",  (0.2, 0.4, 0.6)),
                    "volatile": ("triangular",  (0.45, 0.7, 0.85)),
                    "crisis":   ("trapezoidal", (0.7, 0.9, 1.0, 1.0)),
                },
            },
            "policy_signal": {
                "description": "Central bank / fiscal policy stance",
                "terms": {
                    "accommodative": ("trapezoidal", (0.0, 0.0, 0.15, 0.35)),
                    "neutral":       ("triangular",  (0.2, 0.45, 0.7)),
                    "tightening":    ("triangular",  (0.5, 0.7, 0.9)),
                    "emergency":     ("trapezoidal", (0.75, 0.9, 1.0, 1.0)),
                },
            },
            "capital_flows": {
                "description": "Direction and urgency of capital movement",
                "terms": {
                    "inflow":   ("trapezoidal", (0.0, 0.0, 0.15, 0.3)),
                    "balanced": ("triangular",  (0.2, 0.4, 0.6)),
                    "outflow":  ("triangular",  (0.45, 0.7, 0.85)),
                    "flight":   ("trapezoidal", (0.7, 0.9, 1.0, 1.0)),
                },
            },
        },
        "latent_nodes": ["systemic_risk", "regime_shift_probability"],
        "causal_edges": [
            ("yield_curve",    "systemic_risk"),
            ("credit_spreads", "systemic_risk"),
            ("fx_volatility",  "systemic_risk"),
            ("policy_signal",  "systemic_risk"),
            ("capital_flows",  "systemic_risk"),
            ("systemic_risk",  "regime_shift_probability"),
            ("policy_signal",  "regime_shift_probability"),
            ("capital_flows",  "regime_shift_probability"),
        ],
        "priors": {
            "systemic_risk":             {"low": 0.45, "medium": 0.30, "high": 0.18, "critical": 0.07},
            "regime_shift_probability":  {"stable": 0.50, "transitioning": 0.30, "shifting": 0.15, "rupture": 0.05},
        },
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Custom Template Persistence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Custom templates are stored in bayesian_fuzzy_templates.json
# and loaded at engine startup. They merge WITH (not replace)
# the built-in DOMAIN_TEMPLATES.
#

from pathlib import Path as _Path

_CUSTOM_TEMPLATES_PATH = _Path(__file__).parent.parent.parent / "bayesian_fuzzy_templates.json"
_BUILTIN_DOMAIN_NAMES = frozenset(DOMAIN_TEMPLATES.keys())


def _load_custom_templates() -> dict[str, dict]:
    """Load custom templates from disk. Returns empty dict if none."""
    if not _CUSTOM_TEMPLATES_PATH.exists():
        return {}
    try:
        import json as _json
        raw = _json.loads(_CUSTOM_TEMPLATES_PATH.read_text(encoding="utf-8"))
        templates = raw.get("templates", {})
        loaded = {}
        for name, tmpl in templates.items():
            converted = _convert_stored_template(tmpl)
            if converted:
                loaded[name] = converted
        if loaded:
            logger.info("[BayesFuzzy] Loaded %d custom templates: %s", len(loaded), list(loaded.keys()))
        return loaded
    except Exception as e:
        logger.warning("[BayesFuzzy] Failed to load custom templates: %s", e)
        return {}


def _convert_stored_template(tmpl: dict) -> dict | None:
    """Convert a stored template (JSON-safe) to the runtime format.

    In JSON we store terms as: {"term_name": ["triangular", [0.1, 0.5, 0.9]]}
    At runtime we need: {"term_name": ("triangular", (0.1, 0.5, 0.9))}
    """
    try:
        converted = {
            "description": tmpl.get("description", ""),
            "keywords": tmpl.get("keywords", []),
            "latent_nodes": tmpl.get("latent_nodes", []),
            "causal_edges": [tuple(e) for e in tmpl.get("causal_edges", [])],
            "priors": tmpl.get("priors", {}),
            "variables": {},
        }
        for var_name, var_def in tmpl.get("variables", {}).items():
            terms = {}
            for term_name, term_spec in var_def.get("terms", {}).items():
                if isinstance(term_spec, (list, tuple)) and len(term_spec) == 2:
                    mf_type = term_spec[0]
                    params = tuple(term_spec[1])
                    terms[term_name] = (mf_type, params)
                else:
                    logger.warning("[BayesFuzzy] Invalid term spec for %s.%s: %s", var_name, term_name, term_spec)
                    return None
            converted["variables"][var_name] = {
                "description": var_def.get("description", ""),
                "terms": terms,
            }
        # Validate
        if not converted["variables"]:
            return None
        if not converted["latent_nodes"]:
            return None
        if not converted["causal_edges"]:
            return None
        if not converted["priors"]:
            return None
        # Validate priors sum ≈ 1.0
        for node, prior in converted["priors"].items():
            total = sum(prior.values())
            if abs(total - 1.0) > 0.05:
                logger.warning("[BayesFuzzy] Prior for %s sums to %.3f (expected ~1.0)", node, total)
                return None
        return converted
    except Exception as e:
        logger.warning("[BayesFuzzy] Template conversion failed: %s", e)
        return None


def _convert_template_for_storage(tmpl: dict) -> dict:
    """Convert runtime template to JSON-safe storage format.

    Runtime: {"term_name": ("triangular", (0.1, 0.5, 0.9))}
    Storage: {"term_name": ["triangular", [0.1, 0.5, 0.9]]}
    """
    stored = {
        "description": tmpl.get("description", ""),
        "keywords": tmpl.get("keywords", []),
        "latent_nodes": tmpl.get("latent_nodes", []),
        "causal_edges": [list(e) for e in tmpl.get("causal_edges", [])],
        "priors": tmpl.get("priors", {}),
        "variables": {},
    }
    for var_name, var_def in tmpl.get("variables", {}).items():
        terms = {}
        for term_name, term_spec in var_def.get("terms", {}).items():
            if isinstance(term_spec, (list, tuple)) and len(term_spec) == 2:
                terms[term_name] = [term_spec[0], list(term_spec[1])]
            else:
                terms[term_name] = term_spec
        stored["variables"][var_name] = {
            "description": var_def.get("description", ""),
            "terms": terms,
        }
    return stored


def save_custom_template(name: str, template: dict) -> dict:
    """Save or update a custom template to disk.

    Args:
        name: Template name (snake_case, alphanumeric + underscores)
        template: Template in EITHER runtime or storage format

    Returns:
        {"status": "saved", "name": name} or {"error": "..."}
    """
    import re
    import json as _json

    # Validate name
    if not re.match(r'^[a-z][a-z0-9_]{2,49}$', name):
        return {"error": "Name must be lowercase alphanumeric + underscores, 3-50 chars"}

    # Don't allow overwriting built-in templates
    if name in _BUILTIN_DOMAIN_NAMES:
        return {"error": f"Cannot overwrite built-in template '{name}'"}

    # Validate the template can convert
    converted = _convert_stored_template(template) if "keywords" in template else None
    if converted is None:
        # Maybe it's already in runtime format — try converting TO storage then back
        stored = _convert_template_for_storage(template)
        converted = _convert_stored_template(stored)
        if converted is None:
            return {"error": "Invalid template structure — check variables, latent_nodes, causal_edges, priors"}

    # Load existing custom templates
    existing = {}
    if _CUSTOM_TEMPLATES_PATH.exists():
        try:
            existing = _json.loads(_CUSTOM_TEMPLATES_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    if "templates" not in existing:
        existing["templates"] = {}

    # Store in JSON-safe format
    existing["templates"][name] = _convert_template_for_storage(template)
    existing["last_updated"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

    try:
        _CUSTOM_TEMPLATES_PATH.write_text(
            _json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        return {"error": f"Failed to write: {e}"}

    logger.info("[BayesFuzzy] Custom template saved: %s", name)
    return {"status": "saved", "name": name}


def delete_custom_template(name: str) -> dict:
    """Delete a custom template from disk."""
    import json as _json

    if name in _BUILTIN_DOMAIN_NAMES:
        return {"error": f"Cannot delete built-in template '{name}'"}

    if not _CUSTOM_TEMPLATES_PATH.exists():
        return {"error": "No custom templates file"}

    try:
        data = _json.loads(_CUSTOM_TEMPLATES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"error": "Failed to read templates file"}

    if name not in data.get("templates", {}):
        return {"error": f"Template '{name}' not found"}

    del data["templates"][name]
    data["last_updated"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

    _CUSTOM_TEMPLATES_PATH.write_text(
        _json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[BayesFuzzy] Custom template deleted: %s", name)
    return {"status": "deleted", "name": name}


def list_all_templates() -> dict:
    """List all available templates (built-in + custom) with metadata."""
    import json as _json

    result = {}

    # Built-in
    for name, tmpl in DOMAIN_TEMPLATES.items():
        result[name] = {
            "description": tmpl["description"],
            "type": "built-in",
            "variables": list(tmpl["variables"].keys()),
            "latent_nodes": tmpl["latent_nodes"],
            "n_edges": len(tmpl["causal_edges"]),
        }

    # Custom
    custom = _load_custom_templates()
    for name, tmpl in custom.items():
        result[name] = {
            "description": tmpl.get("description", ""),
            "type": "custom",
            "variables": list(tmpl.get("variables", {}).keys()),
            "latent_nodes": tmpl.get("latent_nodes", []),
            "n_edges": len(tmpl.get("causal_edges", [])),
        }

    return result


def get_template_detail(name: str) -> dict | None:
    """Get full template details (runtime format) by name."""
    if name in DOMAIN_TEMPLATES:
        tmpl = DOMAIN_TEMPLATES[name]
        return {"name": name, "type": "built-in", **_convert_template_for_storage(tmpl)}

    custom = _load_custom_templates()
    if name in custom:
        return {"name": name, "type": "custom", **_convert_template_for_storage(custom[name])}

    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LLM Prompts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INDICATOR_EXTRACTION_PROMPT = """You are the Bayesian-Fuzzy Evidence Extractor for the XDART-Φ framework.

Given a geopolitical/financial analysis context, extract QUANTITATIVE INDICATOR VALUES
for each variable in the domain template. Read the qualitative evidence and assign
a NUMERICAL VALUE [0.0, 1.0] representing the current state of each variable.

DOMAIN: {domain_name}
DOMAIN DESCRIPTION: {domain_description}

VARIABLES TO ASSESS:
{variables_description}

SCENARIOS:
{scenarios_text}

WORLD CONTEXT:
{world_context}

For each variable:
1. Cite the specific evidence from scenarios/context that informs your assessment
2. Assign a value from 0.0 (lowest/safest) to 1.0 (highest/most alarming)
3. Rate your confidence in the assessment (0.0 to 1.0)

Respond in JSON:
{{
  "domain_detected": "{domain_name}",
  "indicators": {{
    "variable_name": {{
      "value": 0.65,
      "confidence": 0.8,
      "evidence": "Specific evidence cited from context",
      "reasoning": "Why this value was assigned"
    }}
  }},
  "missing_data": ["variables where evidence is insufficient"],
  "cross_indicator_tensions": ["Where indicators seem contradictory"]
}}"""


RISK_SYNTHESIS_PROMPT = """You are the Bayesian-Fuzzy Risk Synthesizer for the XDART-Φ framework.

You receive POSTERIOR PROBABILITY distributions computed via Bayesian updating
with fuzzy-quantified evidence. Produce a RISK NARRATIVE that explains what
these posteriors MEAN in strategic terms.

DOMAIN: {domain_name}

FUZZY EVIDENCE (indicators with membership degrees):
{fuzzy_evidence_text}

BAYESIAN POSTERIORS (updated from priors using evidence):
{posteriors_text}

PRIOR → POSTERIOR SHIFTS (the signal — what changed from baseline):
{shift_text}

SCENARIOS (for context):
{scenarios_text}

YOUR TASKS:

1. RISK ASSESSMENT — Synthesize the posteriors into a clear risk statement.
   Focus on WHAT CHANGED from prior beliefs (the shift is the signal).

2. CAUSAL CHAIN — Trace the most critical causal pathway through the
   Bayesian network. Which parent nodes drive the posterior shift most?

3. UNCERTAINTY MAP — Where are the posteriors still wide (high entropy)?
   What additional evidence would narrow them?

4. STRATEGIC IMPLICATIONS — What do these risk posteriors mean for
   decision-makers? What actions become urgent at these probability levels?

5. BRIER-CALIBRATED CONFIDENCE — How calibrated do you assess this
   analysis to be? What systematic biases might affect the posteriors?

Respond in JSON:
{{
  "risk_assessment": "Clear 2-3 sentence risk statement",
  "dominant_risk_level": "low|medium|high|critical",
  "causal_chain": "A → B → C: explanation of the dominant causal pathway",
  "key_drivers": ["indicator1", "indicator2"],
  "uncertainty_map": {{
    "high_uncertainty": ["node1: why uncertain"],
    "low_uncertainty": ["node2: why confident"]
  }},
  "strategic_implications": ["implication 1", "implication 2"],
  "calibration_assessment": "How well-calibrated is this analysis",
  "recommended_evidence": ["What new data would improve these posteriors"],
  "risk_narrative": "3-5 sentence synthesis for prophetic memory integration"
}}"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Bayesian-Fuzzy Engine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BayesianFuzzyEngine:
    """
    Phase 2.92 — Bayesian-Fuzzy Reasoning Engine.

    Hybrid reasoning system:
      - Fuzzy Logic:  Maps qualitative IAEA/financial/geopolitical indicators
                      to fuzzy membership degrees via triangular/trapezoidal functions
      - Bayesian Net:  Updates prior beliefs → posterior probabilities
                      using fuzzy evidence via Jeffrey's conditioning rule
      - LLM-augmented: Indicator extraction and risk synthesis via LLM

    Mathematical Formulation:

      Fuzzy evidence:  μ_A(x) for indicator x in fuzzy set A

      Jeffrey's rule:  P'(H) = Σ_e P(H|E=e) · μ(e)
      where μ(e) = fuzzy membership serving as soft evidence weight

      Bayesian update: P(H|E) ∝ P(E|H) · P(H)

      Combined:
        P_final(H) = w · P_bayesian(H) + (1−w) · P_prior(H)
        where w = mean confidence of fuzzy evidence
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run_chat(
        self,
        problem: str,
        world_context: str = "",
        domain_hint: str = "",
    ) -> BayesianFuzzyResult:
        """Standalone Bayesian-Fuzzy analysis for chat mode — no scenarios needed.

        Works the same as the full pipeline version but uses world_context directly
        instead of requiring Scenario/Tribunal objects.
        """
        logger.info("=" * 60)
        logger.info("[BayesFuzzy CHAT] BAYESIAN-FUZZY ENGINE — CHAT MODE START")
        t0 = time.perf_counter()

        # Create minimal scenario-like objects from world context for internal reuse
        _chat_scenarios = [
            Scenario(
                id="chat_analysis",
                name="Chat Analysis Context",
                source_perspective="chat_direct_analysis",
                narrative=world_context[:2000] if world_context else problem,
                trajectory="Direct chat-mode analysis — no scenario trajectory",
                predicted_outcome=problem,
                confidence=0.5,
                timeline="current",
                falsifiability="N/A — chat mode analysis",
            )
        ]

        # ── Step 1: Detect domain ──
        if domain_hint:
            # Check if hint matches a known template
            custom_templates = _load_custom_templates()
            if domain_hint in DOMAIN_TEMPLATES:
                domain, template = domain_hint, DOMAIN_TEMPLATES[domain_hint]
            elif domain_hint in custom_templates:
                domain, template = domain_hint, custom_templates[domain_hint]
            else:
                domain, template = self._detect_domain(problem, _chat_scenarios, world_context)
        else:
            domain, template = self._detect_domain(problem, _chat_scenarios, world_context)

        logger.info(
            "[BayesFuzzy CHAT] Domain detected: %s (%d variables, %d latent nodes)",
            domain, len(template["variables"]), len(template["latent_nodes"]),
        )

        # ── Step 2: Extract indicators ──
        raw_indicators = self._extract_indicators(domain, template, _chat_scenarios, world_context)

        # ── Step 3: Fuzzify ──
        fuzzy_evidence = self._fuzzify(template, raw_indicators)

        # ── Step 4: Bayesian update ──
        posteriors, prior_posterior_shifts = self._bayesian_update(template, fuzzy_evidence)

        # ── Step 5: Synthesize ──
        synthesis = self._synthesize_risk(
            domain, template, fuzzy_evidence, posteriors, prior_posterior_shifts, _chat_scenarios,
        )

        elapsed = time.perf_counter() - t0

        # Build result (same as full pipeline)
        node_states = []
        for node_name, posterior in posteriors.items():
            prior = template["priors"].get(node_name, {})
            dominant_state = max(posterior, key=posterior.get)
            node_states.append(BayesianNodeState(
                node_name=node_name,
                prior_distribution=prior,
                posterior_distribution=posterior,
                dominant_state=dominant_state,
                dominant_probability=posterior[dominant_state],
                entropy=self._entropy(posterior),
                kl_divergence=self._kl_divergence(prior, posterior),
            ))

        result = BayesianFuzzyResult(
            domain=domain,
            domain_description=template["description"],
            fuzzy_evidence=fuzzy_evidence,
            bayesian_nodes=node_states,
            risk_posteriors=[
                RiskPosterior(
                    risk_variable=ns.node_name,
                    posterior=ns.posterior_distribution,
                    dominant_level=ns.dominant_state,
                    dominant_probability=ns.dominant_probability,
                    prior_shift=prior_posterior_shifts.get(ns.node_name, {}),
                )
                for ns in node_states
            ],
            risk_assessment=synthesis.get("risk_assessment", ""),
            dominant_risk_level=synthesis.get("dominant_risk_level", "medium"),
            causal_chain=synthesis.get("causal_chain", ""),
            key_drivers=synthesis.get("key_drivers", []),
            uncertainty_map=synthesis.get("uncertainty_map", {}),
            strategic_implications=synthesis.get("strategic_implications", []),
            calibration_assessment=synthesis.get("calibration_assessment", ""),
            recommended_evidence=synthesis.get("recommended_evidence", []),
            risk_narrative=synthesis.get("risk_narrative", ""),
            cross_indicator_tensions=raw_indicators.get("cross_indicator_tensions", []),
            missing_data=raw_indicators.get("missing_data", []),
            elapsed_seconds=elapsed,
        )

        logger.info("[BayesFuzzy CHAT] Domain: %s, Risk: %s (%.2fs)", domain, result.dominant_risk_level, elapsed)
        logger.info("[BayesFuzzy CHAT] BAYESIAN-FUZZY ENGINE — CHAT MODE COMPLETE")
        logger.info("=" * 60)

        return result

    def run(
        self,
        problem: str,
        scenarios: list[Scenario],
        tribunal: ScenarioTribunalResult,
        world_context: str = "",
    ) -> BayesianFuzzyResult:
        """
        Full Bayesian-Fuzzy pipeline:
        1. Detect domain and select template
        2. LLM extracts indicator values from context
        3. Fuzzy logic computes membership degrees
        4. Bayesian network updates posteriors from fuzzy evidence
        5. LLM synthesizes risk narrative from posteriors
        """
        logger.info("=" * 60)
        logger.info("[BayesFuzzy 2.92] BAYESIAN-FUZZY ENGINE — START")
        t0 = time.perf_counter()

        # ── Step 1: Detect domain ──
        domain, template = self._detect_domain(problem, scenarios, world_context)
        logger.info(
            "[BayesFuzzy 2.92] Domain detected: %s (%d variables, %d latent nodes)",
            domain, len(template["variables"]), len(template["latent_nodes"]),
        )

        # ── Step 2: Extract indicators via LLM ──
        raw_indicators = self._extract_indicators(domain, template, scenarios, world_context)
        logger.info(
            "[BayesFuzzy 2.92] Indicators extracted: %d values, %d missing",
            len(raw_indicators.get("indicators", {})),
            len(raw_indicators.get("missing_data", [])),
        )

        # ── Step 3: Fuzzify — compute membership degrees ──
        fuzzy_evidence = self._fuzzify(template, raw_indicators)
        for fe in fuzzy_evidence:
            logger.info(
                "[BayesFuzzy 2.92]   %s: value=%.3f → %s (μ=%.3f), confidence=%.2f",
                fe.variable, fe.value, fe.dominant_term, fe.dominant_membership, fe.confidence,
            )

        # ── Step 4: Bayesian update — priors → posteriors ──
        posteriors, prior_posterior_shifts = self._bayesian_update(template, fuzzy_evidence)
        for node_name, posterior in posteriors.items():
            logger.info(
                "[BayesFuzzy 2.92]   P(%s): %s",
                node_name, {k: f"{v:.3f}" for k, v in posterior.items()},
            )

        # ── Step 5: LLM risk synthesis ──
        synthesis = self._synthesize_risk(
            domain, template, fuzzy_evidence, posteriors, prior_posterior_shifts, scenarios,
        )

        elapsed = time.perf_counter() - t0

        # ── Build result ──
        node_states = []
        for node_name, posterior in posteriors.items():
            prior = template["priors"].get(node_name, {})
            dominant_state = max(posterior, key=posterior.get)
            node_states.append(BayesianNodeState(
                node_name=node_name,
                prior_distribution=prior,
                posterior_distribution=posterior,
                dominant_state=dominant_state,
                dominant_probability=posterior[dominant_state],
                entropy=self._entropy(posterior),
                kl_divergence=self._kl_divergence(prior, posterior),
            ))

        result = BayesianFuzzyResult(
            domain=domain,
            domain_description=template["description"],
            fuzzy_evidence=fuzzy_evidence,
            bayesian_nodes=node_states,
            risk_posteriors=[
                RiskPosterior(
                    risk_variable=ns.node_name,
                    posterior=ns.posterior_distribution,
                    dominant_level=ns.dominant_state,
                    dominant_probability=ns.dominant_probability,
                    prior_shift=prior_posterior_shifts.get(ns.node_name, {}),
                )
                for ns in node_states
            ],
            risk_assessment=synthesis.get("risk_assessment", ""),
            dominant_risk_level=synthesis.get("dominant_risk_level", "medium"),
            causal_chain=synthesis.get("causal_chain", ""),
            key_drivers=synthesis.get("key_drivers", []),
            uncertainty_map=synthesis.get("uncertainty_map", {}),
            strategic_implications=synthesis.get("strategic_implications", []),
            calibration_assessment=synthesis.get("calibration_assessment", ""),
            recommended_evidence=synthesis.get("recommended_evidence", []),
            risk_narrative=synthesis.get("risk_narrative", ""),
            cross_indicator_tensions=raw_indicators.get("cross_indicator_tensions", []),
            missing_data=raw_indicators.get("missing_data", []),
            elapsed_seconds=elapsed,
        )

        logger.info("[BayesFuzzy 2.92] RESULT:")
        logger.info("[BayesFuzzy 2.92]   Domain: %s", result.domain)
        logger.info("[BayesFuzzy 2.92]   Dominant risk: %s", result.dominant_risk_level)
        for ns in result.bayesian_nodes:
            logger.info(
                "[BayesFuzzy 2.92]   %s: %s (P=%.3f, H=%.3f, KL=%.4f)",
                ns.node_name, ns.dominant_state, ns.dominant_probability,
                ns.entropy, ns.kl_divergence,
            )
        logger.info("[BayesFuzzy 2.92]   Key drivers: %s", result.key_drivers)
        logger.info("[BayesFuzzy 2.92]   Missing data: %s", result.missing_data)
        logger.info("[BayesFuzzy 2.92] BAYESIAN-FUZZY ENGINE — COMPLETE (%.2fs)", elapsed)
        logger.info("=" * 60)

        return result

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 1: Domain Detection
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _detect_domain(
        self,
        problem: str,
        scenarios: list[Scenario],
        world_context: str,
    ) -> tuple[str, dict]:
        """Detect the most relevant domain template for the analysis.

        Searches both built-in and custom templates using keyword matching.
        """
        combined = (
            problem + " " + world_context + " "
            + " ".join(s.narrative for s in scenarios[:5])
        ).lower()

        # Built-in keyword sets
        nuclear_keywords = [
            "nuclear", "proliferation", "iaea", "enrichment", "uranium",
            "centrifuge", "safeguard", "inspection", "npt", "breakout",
            "weapons", "warhead", "plutonium", "reactor", "nonproliferation",
        ]
        financial_keywords = [
            "financial", "market", "yield", "credit", "spread",
            "currency", "forex", "central bank", "fed", "ecb",
            "recession", "inflation", "rate", "debt", "sovereign",
            "systemic", "stress", "volatility", "capital flow",
        ]

        scores: dict[str, int] = {}
        scores["nuclear_proliferation"] = sum(1 for kw in nuclear_keywords if kw in combined)
        scores["financial_stress"] = sum(1 for kw in financial_keywords if kw in combined)

        # Score custom templates by their keywords
        custom_templates = _load_custom_templates()
        for name, tmpl in custom_templates.items():
            keywords = tmpl.get("keywords", [])
            if keywords:
                scores[name] = sum(1 for kw in keywords if kw.lower() in combined)

        # Find best match (minimum threshold: 2 keyword matches)
        best_name = max(scores, key=scores.get) if scores else "financial_stress"
        best_score = scores.get(best_name, 0)

        if best_score >= 2:
            if best_name in DOMAIN_TEMPLATES:
                return best_name, DOMAIN_TEMPLATES[best_name]
            elif best_name in custom_templates:
                return best_name, custom_templates[best_name]

        # Default: financial (more common analytic context)
        return "financial_stress", DOMAIN_TEMPLATES["financial_stress"]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 2: LLM Indicator Extraction
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _extract_indicators(
        self,
        domain: str,
        template: dict,
        scenarios: list[Scenario],
        world_context: str,
    ) -> dict:
        """Use LLM to extract quantitative indicator values from qualitative context."""
        variables_desc = []
        for var_name, var_def in template["variables"].items():
            terms = ", ".join(var_def["terms"].keys())
            variables_desc.append(
                f"- {var_name}: {var_def['description']}\n"
                f"  Fuzzy terms: {terms}\n"
                f"  Value range: 0.0 (safest / {list(var_def['terms'].keys())[0]}) "
                f"to 1.0 (most alarming / {list(var_def['terms'].keys())[-1]})"
            )

        scenarios_text = "\n".join(
            f"[{s.name}] (confidence={s.confidence:.2f}): {s.narrative[:300]}"
            for s in scenarios[:7]
        )

        prompt = INDICATOR_EXTRACTION_PROMPT.format(
            domain_name=domain,
            domain_description=template["description"],
            variables_description="\n".join(variables_desc),
            scenarios_text=scenarios_text,
            world_context=(world_context or "No world context available")[:2000],
        )

        result = self.llm.call_json(
            system_prompt="You are a Bayesian-Fuzzy evidence extraction engine for XDART-Φ. Respond only in JSON.",
            user_prompt=prompt,
            temperature=0.3,
            thinking=False,
        )

        # Validate and clamp indicator values
        indicators = result.get("indicators", {})
        for var_name in indicators:
            ind = indicators[var_name]
            ind["value"] = max(0.0, min(1.0, float(ind.get("value", 0.5))))
            ind["confidence"] = max(0.0, min(1.0, float(ind.get("confidence", 0.3))))

        return result

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 3: Fuzzification
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _fuzzify(self, template: dict, raw_indicators: dict) -> list[FuzzyEvidence]:
        """Compute fuzzy membership degrees for each indicator."""
        evidence_list = []
        indicators = raw_indicators.get("indicators", {})

        for var_name, var_def in template["variables"].items():
            ind = indicators.get(var_name, {})
            value = max(0.0, min(1.0, float(ind.get("value", 0.5))))
            confidence = max(0.0, min(1.0, float(ind.get("confidence", 0.3))))

            memberships: dict[str, float] = {}
            for term_name, (mf_type, params) in var_def["terms"].items():
                if mf_type == "triangular":
                    memberships[term_name] = triangular_mf(value, *params)
                elif mf_type == "trapezoidal":
                    memberships[term_name] = trapezoidal_mf(value, *params)

            dominant_term = max(memberships, key=memberships.get) if memberships else "unknown"
            dominant_membership = memberships.get(dominant_term, 0.0)

            evidence_list.append(FuzzyEvidence(
                variable=var_name,
                value=value,
                memberships=memberships,
                dominant_term=dominant_term,
                dominant_membership=dominant_membership,
                confidence=confidence,
                evidence_text=ind.get("evidence", ""),
                reasoning=ind.get("reasoning", ""),
            ))

        return evidence_list

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 4: Bayesian Network Update
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _bayesian_update(
        self,
        template: dict,
        fuzzy_evidence: list[FuzzyEvidence],
    ) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
        """
        Update latent node posteriors using fuzzy evidence via Jeffrey's rule.

        For each latent node H with ordered states {s₁, s₂, …, sₙ}:
          P'(H=sᵢ) ∝ P(H=sᵢ) · Π_parent L(parent | H=sᵢ)

        where L(parent | H=sᵢ) is a Gaussian-kernel likelihood centered
        on the fuzzy indicator value, weighted by LLM-estimated confidence.

        Returns: (posteriors, prior_posterior_shifts)
        """
        priors = template.get("priors", {})
        edges = template.get("causal_edges", [])

        # Build parent→child mapping
        parent_map: dict[str, list[str]] = {}
        for parent, child in edges:
            parent_map.setdefault(child, []).append(parent)

        # Index fuzzy evidence by variable name
        evidence_index = {fe.variable: fe for fe in fuzzy_evidence}

        posteriors: dict[str, dict[str, float]] = {}
        shifts: dict[str, dict[str, float]] = {}

        # ── First pass: update from observable evidence ──
        for latent_node in template["latent_nodes"]:
            prior = priors.get(latent_node, {})
            if not prior:
                continue

            parents = parent_map.get(latent_node, [])
            observable_parents = [p for p in parents if p in evidence_index]

            if not observable_parents:
                posteriors[latent_node] = dict(prior)
                shifts[latent_node] = {s: 0.0 for s in prior}
                continue

            states = list(prior.keys())
            n_states = len(states)
            posterior = dict(prior)

            for parent_name in observable_parents:
                fe = evidence_index[parent_name]
                if fe.confidence < 0.1:
                    continue  # Skip very uncertain evidence

                evidence_value = fe.value
                evidence_confidence = fe.confidence

                # Construct soft likelihood: L(evidence | H=state)
                # State positions mapped linearly to [0, 1]:
                #   state[0] → 0.0 (safest), state[-1] → 1.0 (most alarming)
                # Evidence close to state position → high likelihood
                for i, state in enumerate(states):
                    state_position = i / (n_states - 1) if n_states > 1 else 0.5
                    distance = abs(evidence_value - state_position)
                    likelihood = math.exp(-2.0 * distance * distance)

                    update_strength = evidence_confidence * BAYESIAN_FUZZY_PRIOR_WEIGHT
                    posterior[state] *= (1.0 + update_strength * (likelihood - 1.0))

            # Normalize
            total = sum(posterior.values())
            if total > 0:
                posterior = {s: p / total for s, p in posterior.items()}
            else:
                posterior = dict(prior)

            posteriors[latent_node] = posterior
            shifts[latent_node] = {
                s: posterior.get(s, 0.0) - prior.get(s, 0.0) for s in states
            }

        # ── Second pass: propagate between latent nodes ──
        for latent_node in template["latent_nodes"]:
            parents = parent_map.get(latent_node, [])
            latent_parents = [p for p in parents if p in posteriors and p != latent_node]

            if not latent_parents or latent_node not in posteriors:
                continue

            prior = priors.get(latent_node, {})
            states = list(prior.keys())
            n_states = len(states)

            for parent_name in latent_parents:
                parent_posterior = posteriors[parent_name]
                parent_states = list(parent_posterior.keys())
                parent_n = len(parent_states)

                # Effective parent risk level as weighted average position
                parent_risk = sum(
                    parent_posterior[ps] * (j / (parent_n - 1) if parent_n > 1 else 0.5)
                    for j, ps in enumerate(parent_states)
                )

                for i, state in enumerate(states):
                    state_position = i / (n_states - 1) if n_states > 1 else 0.5
                    distance = abs(parent_risk - state_position)
                    likelihood = math.exp(-2.0 * distance * distance)
                    posteriors[latent_node][state] *= (1.0 + 0.5 * (likelihood - 1.0))

            # Re-normalize
            total = sum(posteriors[latent_node].values())
            if total > 0:
                posteriors[latent_node] = {
                    s: p / total for s, p in posteriors[latent_node].items()
                }

            # Update shifts
            shifts[latent_node] = {
                s: posteriors[latent_node].get(s, 0.0) - prior.get(s, 0.0)
                for s in states
            }

        return posteriors, shifts

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 5: LLM Risk Synthesis
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _synthesize_risk(
        self,
        domain: str,
        template: dict,
        fuzzy_evidence: list[FuzzyEvidence],
        posteriors: dict[str, dict[str, float]],
        shifts: dict[str, dict[str, float]],
        scenarios: list[Scenario],
    ) -> dict:
        """LLM synthesis of risk assessment from Bayesian posteriors."""
        fuzzy_text = "\n".join(
            f"  {fe.variable}: value={fe.value:.3f}, "
            f"dominant_term={fe.dominant_term} (μ={fe.dominant_membership:.3f}), "
            f"confidence={fe.confidence:.2f}\n    evidence: {fe.evidence_text[:150]}"
            for fe in fuzzy_evidence
        )

        posteriors_text = "\n".join(
            f"  {node}: {{{', '.join(f'{s}: {p:.3f}' for s, p in dist.items())}}}"
            for node, dist in posteriors.items()
        )

        shift_text = "\n".join(
            f"  {node}: {{{', '.join(f'{s}: {d:+.3f}' for s, d in deltas.items())}}}"
            for node, deltas in shifts.items()
        )

        scenarios_text = "\n".join(
            f"  [{s.name}] (confidence={s.confidence:.2f}): {s.predicted_outcome[:200]}"
            for s in scenarios[:5]
        )

        prompt = RISK_SYNTHESIS_PROMPT.format(
            domain_name=domain,
            fuzzy_evidence_text=fuzzy_text,
            posteriors_text=posteriors_text,
            shift_text=shift_text,
            scenarios_text=scenarios_text,
        )

        result = self.llm.call_json(
            system_prompt="You are a Bayesian-Fuzzy risk synthesizer for XDART-Φ. Respond only in JSON.",
            user_prompt=prompt,
            temperature=0.4,
            thinking=False,
        )
        return result

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Information-Theoretic Utilities
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _entropy(distribution: dict[str, float]) -> float:
        """Shannon entropy H = −Σ p·log₂(p). Higher = more uncertain."""
        h = 0.0
        for p in distribution.values():
            if p > 1e-10:
                h -= p * math.log2(p)
        return h

    @staticmethod
    def _kl_divergence(prior: dict[str, float], posterior: dict[str, float]) -> float:
        """KL divergence D_KL(posterior ‖ prior). Measures information gain from evidence."""
        kl = 0.0
        for s in posterior:
            p = posterior.get(s, 1e-10)
            q = prior.get(s, 1e-10)
            if p > 1e-10 and q > 1e-10:
                kl += p * math.log2(p / q)
        return max(0.0, kl)
