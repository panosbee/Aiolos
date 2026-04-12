"""
XDART-Φ × XHEART — System Self-Knowledge

Gives the Evolution Core complete awareness of its own architecture.
Reads the codebase, understands the pipeline, knows what tools exist.

"Γνῶθι σεαυτόν" — Know thyself.
Without self-knowledge, evolution is blind mutation.
With it, evolution is directed improvement.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("xdart.evolution.self_knowledge")

BASE_DIR = Path(__file__).parent.parent.parent


class SystemSelfKnowledge:
    """Builds a complete map of the system for the Evolution Core."""

    def __init__(self):
        self.xdart_dir = BASE_DIR / "xdart"
        self.tools_dir = self.xdart_dir / "tools" / "_generated"
        self.evolution_log_path = self.xdart_dir / "evolution" / "evolution_log.json"

    def get_full_knowledge(self) -> str:
        """Build complete self-knowledge string for the Evolution Core LLM prompt."""
        sections = [
            self._architecture_overview(),
            self._file_structure(),
            self._pipeline_phases(),
            self._data_sources(),
            self._existing_tools(),
            self._evolution_history(),
            self._constraints(),
        ]
        return "\n\n".join(sections)

    def _architecture_overview(self) -> str:
        return """=== SYSTEM ARCHITECTURE ===
XDART-Φ × XHEART: Epistemological reasoning framework.
Model: GPT-5.4 (128K context window)
Language: Python 3.12
Storage: SQLite (perception.db) + Qdrant (vector memories/concepts)
Server: FastAPI + SSE streaming

Pipeline flow:
  [0.0] Wakeup (identity/character load)
  [0.05] Self-Awareness Brief
  [0.1] Episodic Memory retrieval (Qdrant vector search)
  [0.2] Concept Registry retrieval (Qdrant vector search)
  [0.35] World Context (ALL events + indicators from perception DB)
  [0.36] Run Evolution Tools (your creations run HERE)
  Phase 0: Ontological Grounding — reframes the problem
  Phase 1: Cross-Domain Reasoning — 4-6 domain analogies
  Phase 2: Multiple Views — 18 views in 3 parallel groups
  Phase 2.92: Bayesian-Fuzzy Engine — fuzzy logic + Bayesian network risk quantification
  Phase 3: XHEART Distillation — thesis/antithesis/synthesis + final output
  Phase 4: Episodic Memory Store
  Phase 5: Character update + Self-awareness brief update
  Phase 5c.5: Logic Sandbox — auto-analyze pipeline for self-modification proposals
  Phase 5c.6: Principle Registry — discover dynamic principles from experience

Self-Modification Systems:
  Logic Sandbox: Can propose modifications to 4 algorithmic functions
    (scenario scoring, confidence weights, salience scoring, ontological reframing).
    Proposals require human approval. Supports test/approve/reject/rollback.
  Principle Registry: Dynamic principles born from experience/mistakes.
    Lifecycle: proposed → active → strengthened/weakened → retired.
    Distinct from static axioms — these evolve with use.
  Bayesian-Fuzzy Custom Templates: Users can create domain-specific templates
    for the BF Engine (variables, fuzzy terms, causal edges, priors, keywords).
    Built-in templates (nuclear_proliferation, financial_stress) are immutable.

EVERY phase sees the FULL world context (all events + indicators).
Tool outputs are APPENDED to world context and flow through all phases."""

    def _file_structure(self) -> str:
        lines = ["=== FILE STRUCTURE ==="]
        for py_file in sorted(self.xdart_dir.rglob("*.py")):
            if "__pycache__" in str(py_file):
                continue
            rel = py_file.relative_to(self.xdart_dir)
            # Read first line for module docstring hint
            try:
                first_lines = py_file.read_text(encoding="utf-8").split("\n")[:5]
                doc_hint = ""
                for line in first_lines:
                    line = line.strip().strip('"').strip("'")
                    if line and not line.startswith("#") and not line.startswith("import"):
                        doc_hint = line[:80]
                        break
                lines.append(f"  xdart/{rel} — {doc_hint}")
            except Exception:
                lines.append(f"  xdart/{rel}")
        return "\n".join(lines)

    def _pipeline_phases(self) -> str:
        return """=== PIPELINE PHASES — WHAT EACH DOES ===
Phase 0 (ontology.py): Takes problem + identity + memory + world context.
  → Outputs: ontological_nature, teleological_purpose, causal_analysis,
             epistemological_check, reframed_problem
  → The reframed_problem determines what Phase 1 sees.

Phase 1 (cross_domain.py): Takes reframed_problem + original_problem + world_context.
  → Outputs: domains_analyzed (4-6), strongest_analogy, layer_3_hypothesis,
             layer classification, structural_formula
  → High domain_distance = better. Layer-3 = breakthrough.

Phase 2 (views.py): Takes problem + reframed + cross_domain_summary + world_context.
  → 3 parallel LLM calls, each with 6 views (18 total):
    - structure group: Systems, Vulnerability, Combinatorial, Domain-Agnostic, Failure, Solution
    - blindspots_meta: Hidden, Assumption, Scale, First Principles, Inverse, Causal
    - epistemic_temporal: Teleological, Phenomenological, Dialectical, Pragmatic, Macro, Evolutionary
  → Then synthesis call merges all 18 views.

Phase 3 (xheart.py): Takes all phase outputs + world_context.
  → Stage A: Internal distillation (thesis/antithesis/synthesis, distillate_core)
  → Gap detection: Checks if distillate has unexplored gaps
  → Self-generated layer: If gap found, creates new analytical layer
  → Stage B: Final output (3-5 sentences born from the ζωμός)

Phase 2.92 (bayesian_fuzzy.py): Bayesian-Fuzzy reasoning engine.
  → Domain detection (keyword scoring across built-in + custom templates)
  → LLM extracts indicator values from world context
  → Fuzzification (triangular/trapezoidal membership functions)
  → Bayesian network update (Jeffrey's conditioning, 2-pass)
  → LLM risk synthesis with quantified posteriors
  → Supports custom templates (API: /xdart/bayesian-fuzzy/templates)

Phase 5c.5 (logic_sandbox.py): Logic Sandbox auto-analysis.
  → Analyzes pipeline output for potential algorithmic improvements
  → Creates proposals for 4 modifiable functions
  → Human approves/rejects proposals via API
  → Approved changes applied with rollback capability

Phase 5c.6 (principle_registry.py): Dynamic Principle Discovery.
  → Discovers operational principles from pipeline experience
  → New principles start as 'proposed', require human approval
  → Active principles are tracked: success strengthens, failure weakens
  → Auto-retires principles that consistently underperform

IMPORTANT: Your tools run at step [0.36], BEFORE all phases.
Your output becomes part of world_context that ALL phases see."""

    def _data_sources(self) -> str:
        return """=== DATA SOURCES AVAILABLE ===
RSS Feeds (Tier 2): Xinhua, Al Jazeera, TASS, NHK World, Deutsche Welle
  → Headlines + summaries, refreshed every 5 minutes
  → Typically 87+ events in the DB

FRED (Tier 1): Federal Reserve Economic Data
  → FEDFUNDS (Fed rate), CPIAUCSL (CPI), UNRATE (unemployment),
    GDP, DGS10 (10Y yield), T10YIE (breakeven inflation)
  → Refreshed hourly

ECB (Tier 1): Euro Area HICP Inflation, EUR/USD Exchange Rate
World Bank (Tier 1): Foreign Direct Investment data

All data stored in SQLite perception.db with:
  world_events: id, headline, summary, source_name, domain, content_type, salience_score
  economic_data: id, indicator, value, unit, period, source, change_pct"""

    def _existing_tools(self) -> str:
        lines = ["=== EXISTING EVOLUTION TOOLS ==="]
        if not self.tools_dir.exists():
            lines.append("  No tools created yet. You are starting from zero.")
            return "\n".join(lines)

        tool_files = list(self.tools_dir.glob("*.py"))
        tool_files = [f for f in tool_files if f.name != "__init__.py"]

        if not tool_files:
            lines.append("  No tools created yet. You are starting from zero.")
            return "\n".join(lines)

        for tf in sorted(tool_files):
            try:
                content = tf.read_text(encoding="utf-8")
                # Extract TOOL_META
                if "TOOL_META" in content:
                    # Find the dict
                    start = content.index("TOOL_META")
                    chunk = content[start:start + 500]
                    lines.append(f"  Tool: {tf.stem}")
                    lines.append(f"    {chunk[:200]}")
                else:
                    lines.append(f"  Tool: {tf.stem} (no TOOL_META found)")
            except Exception:
                lines.append(f"  Tool: {tf.stem} (unreadable)")

        return "\n".join(lines)

    def _evolution_history(self) -> str:
        lines = ["=== EVOLUTION HISTORY ==="]
        if not self.evolution_log_path.exists():
            lines.append("  No evolution history. This is the first run.")
            return "\n".join(lines)

        try:
            log_data = json.loads(self.evolution_log_path.read_text(encoding="utf-8"))
            entries = log_data.get("entries", [])
            if not entries:
                lines.append("  No evolution history yet.")
                return "\n".join(lines)

            lines.append(f"  Total evolutions: {len(entries)}")
            # Show last 5
            for entry in entries[-5:]:
                status = entry.get("status", "?")
                name = entry.get("tool_name", "?")
                reason = entry.get("gap_description", "?")[:80]
                lines.append(f"  [{status}] {name} — {reason}")
        except Exception:
            lines.append("  Evolution log exists but unreadable.")

        return "\n".join(lines)

    def _constraints(self) -> str:
        return """=== TOOL CONSTRAINTS ===
Your generated tools MUST follow this exact interface:

```python
TOOL_META = {
    "name": "tool_name",           # snake_case, unique
    "version": "1.0",
    "purpose": "What this tool does",
    "trigger": "always",           # "always" runs every pipeline run
    "inputs": ["events", "indicators", "problem"],
}

def run(context: dict) -> dict:
    '''
    context keys available:
        "problem": str          — the user's question
        "events": list[dict]    — all world events (headline, source_name, domain, content_type)
        "indicators": list[dict] — all economic data (indicator, value, unit, source, change_pct)
    
    Must return:
        {
            "tool_name": str,
            "output": str,      — text injected into pipeline context
            "metadata": dict,   — any structured data (optional)
        }
    '''
```

SAFE IMPORTS ONLY:
  json, math, statistics, collections, re, datetime, itertools, functools, operator
  
FORBIDDEN:
  os, sys, subprocess, shutil, pathlib — no filesystem access
  requests, httpx, urllib — no network access  
  sqlite3 — no direct DB access
  importlib, exec, eval, compile — no code execution
  
Keep tools focused. One tool = one capability.
If a tool fails in sandbox, analyze why and fix the code."""
