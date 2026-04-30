"""
XDART-Φ × Dark Whisper Intelligence — LLM Triage Engine
=========================================================

Every dark signal from the dirty pool must pass through triage before
it can influence any synthesis, analysis, or report. This is the
mandatory challenge layer — signals are not believed until they are
evaluated.

TRIAGE PROCESS:
  1. Batch signals from DirtyPool (up to DARKWEB_TRIAGE_BATCH_SIZE at once)
  2. Single LLM call with structured JSON output per signal:
       • credibility_score  (0–1): Operational plausibility
       • false_flag_risk    (0–1): Likelihood of adversarial disinformation
       • source_attribution : "russia_apt" | "iran_mois" | "iran_irgc" |
                              "hacktivist_pro_russia" | "hacktivist_pro_hamas" |
                              "criminal_ransomware" | "unknown" | "false_flag"
       • language_origin    : ISO-639-1 code + context notes
       • tactical_relevance (0–1): Touches domains Αίολος monitors?
       • verdict            : "YES" | "NO" | "MAYBE"
       • rejection_reason   : Non-empty only when verdict == "NO"
       • sanitized_summary  : Clean 1-2 sentence summary (only for YES/MAYBE)
  3. Update DirtyPool records with triage metadata
  4. Return list of TriagedSignal objects for DarkWhisperEngine

VERDICT SEMANTICS:
  YES   → High credibility, operationally relevant, credibility chain clean.
          Ready for synthesis with clean patterns.
  NO    → Discarded. Could be: fabricated, purely propaganda, zero relevance,
          unverifiable false flag, or simply noise.
  MAYBE → Partial credibility, notable but unverified, or relevant but
          suspicious enough to require corroboration before full integration.
          Parked in dormant memory. Re-evaluated when corroborating signals arrive.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from xdart import config

logger = logging.getLogger(__name__)

# Minimum credibility for a YES verdict
_YES_MIN_CREDIBILITY = 0.40
# Maximum false_flag_risk for a YES verdict
_YES_MAX_FALSE_FLAG = 0.60


# ══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TriagedSignal:
    """A dark signal that has passed through LLM triage.

    Contains the original raw signal data PLUS the triage metadata.
    The credibility_chain is the audit trail from raw collection → triage → synthesis.
    """

    # Original raw signal fields (copied from DirtyPool document)
    text: str
    source_url: str
    source_type: str
    channel_name: str
    collected_at: str
    published_at: str
    raw_credibility: float
    appeared_in_n_channels: int
    content_hash: str

    # Triage metadata
    triaged_at: str
    credibility_score: float       # 0–1: LLM-assessed operational credibility
    false_flag_risk: float         # 0–1: Likelihood of adversarial deception
    source_attribution: str        # Who likely produced this signal
    language_origin: str           # ISO-639-1 + context notes
    tactical_relevance: float      # 0–1: Relevance to monitored domains
    verdict: str                   # "YES" | "NO" | "MAYBE"
    rejection_reason: str          # Non-empty for NO verdicts
    sanitized_summary: str         # Clean summary for YES/MAYBE

    # Credibility chain (full provenance)
    credibility_chain: dict        # Structured audit trail

    # MongoDB reference
    mongo_id: Any = None           # ObjectId from dirty pool document

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mongo_id"] = str(d["mongo_id"]) if d["mongo_id"] else None
        return d

    @property
    def is_yes(self) -> bool:
        return self.verdict == "YES"

    @property
    def is_maybe(self) -> bool:
        return self.verdict == "MAYBE"

    @property
    def is_no(self) -> bool:
        return self.verdict == "NO"


# ══════════════════════════════════════════════════════════════════════════════
#  TRIAGE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

# The triage prompt — LLM acts as a skeptical intelligence analyst
_TRIAGE_SYSTEM_PROMPT = """\
You are a skeptical intelligence analyst specializing in threat actor behavior, \
cyberwarfare, disinformation campaigns, and dark web OSINT. \
Your job is to triage raw dark web signals for credibility, attribution, and relevance.

You are NOT here to amplify threats. You are here to challenge signals rigorously.
False positive reduction is more important than recall.

Your analytical priors:
- Most hacktivist Telegram posts are psychological operations, not operational disclosures.
- Killnet, NoName057, and similar groups have ~80% propaganda, ~20% actual operational content.
- APT-linked channels (Predatory Sparrow, CyberArmy) have higher operational signal density.
- Paste site data is extremely noisy — most is script kiddie content, credential dumps for minor sites, or outright fake.
- Ahmia.fi results reference .onion content — treat with extra skepticism; dark web content has no editorial standards.
- False flags are common: groups impersonate each other; state actors use cutouts.
- "Critical infrastructure attack" claims without corroborating evidence from clean sources = MAYBE at most.

Output ONLY a valid JSON array. Each element corresponds to one input signal IN ORDER.
Each element must have these exact keys:
  "credibility_score": float 0-1,
  "false_flag_risk": float 0-1,
  "source_attribution": string (one of: "russia_apt","russia_hacktivist","iran_mois","iran_irgc","iran_hacktivist","china_apt","dprk_apt","hacktivist_pro_russia","hacktivist_pro_hamas","hacktivist_pro_ukraine","criminal_ransomware","criminal_broker","unknown","false_flag","disinformation"),
  "language_origin": string (ISO-639-1 code + brief notes e.g. "ru — Cyrillic keyboard, machine-translated to EN"),
  "tactical_relevance": float 0-1,
  "verdict": string (exactly "YES", "NO", or "MAYBE"),
  "rejection_reason": string (empty string if verdict is not NO),
  "sanitized_summary": string (1-2 sentences for YES/MAYBE; empty string for NO)

Verdict rules:
  YES   = credibility_score >= 0.40 AND false_flag_risk <= 0.60 AND tactical_relevance >= 0.30
  NO    = credibility_score < 0.15 OR tactical_relevance < 0.10 OR (false_flag_risk > 0.80 AND corroboration <= 1)
  MAYBE = everything else

Do NOT add any text outside the JSON array. Do NOT wrap in markdown code blocks."""


def _build_triage_user_message(raw_docs: list[dict]) -> str:
    """Build the user message for the triage LLM call."""
    lines = [f"Triage the following {len(raw_docs)} dark signal(s):\n"]
    for i, doc in enumerate(raw_docs, 1):
        channel = doc.get("channel_name", "unknown")
        src_type = doc.get("source_type", "unknown")
        text = doc.get("text", "")[:800]  # cap at 800 chars per signal
        corroboration = doc.get("appeared_in_n_channels", 1)
        lines.append(
            f"[{i}] SOURCE: {src_type}/{channel} | CORROBORATED_IN: {corroboration} channels\n"
            f"TEXT: {text}\n"
        )
    return "\n".join(lines)


def _parse_triage_response(raw: str, count: int) -> list[dict]:
    """Parse the LLM triage JSON response.

    Returns a list of triage dicts (one per signal). Falls back to a
    safe default dict (verdict=NO) for any element that fails to parse.
    """
    # Strip accidental markdown code fences if LLM adds them
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()

    default = {
        "credibility_score": 0.0,
        "false_flag_risk": 1.0,
        "source_attribution": "unknown",
        "language_origin": "unknown",
        "tactical_relevance": 0.0,
        "verdict": "NO",
        "rejection_reason": "triage_parse_failure",
        "sanitized_summary": "",
    }

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[DarkTriage] Failed to parse LLM response as JSON")
        return [dict(default) for _ in range(count)]

    if not isinstance(parsed, list):
        logger.warning("[DarkTriage] LLM response is not a list")
        return [dict(default) for _ in range(count)]

    results = []
    for item in parsed[:count]:
        if not isinstance(item, dict):
            results.append(dict(default))
            continue
        # Validate and clamp numeric fields
        merged = dict(default)
        merged.update({k: v for k, v in item.items() if k in default})
        merged["credibility_score"] = max(0.0, min(1.0, float(merged.get("credibility_score", 0))))
        merged["false_flag_risk"] = max(0.0, min(1.0, float(merged.get("false_flag_risk", 1.0))))
        merged["tactical_relevance"] = max(0.0, min(1.0, float(merged.get("tactical_relevance", 0))))
        verdict = str(merged.get("verdict", "NO")).upper().strip()
        if verdict not in ("YES", "NO", "MAYBE"):
            verdict = "NO"
        merged["verdict"] = verdict
        results.append(merged)

    # Pad if LLM returned fewer elements than expected
    while len(results) < count:
        results.append(dict(default))

    return results


import re  # needed for _parse_triage_response


class DarkSignalTriage:
    """LLM-powered triage engine for raw dark signals.

    Reads untriaged signals from DirtyPool, evaluates them in batches via
    LLM, marks them as triaged in the pool, and returns TriagedSignal objects.
    """

    def __init__(self, dirty_pool: "DirtyPool", llm: Any) -> None:
        self.pool = dirty_pool
        self.llm = llm
        self._total_triaged = 0
        self._total_yes = 0
        self._total_maybe = 0
        self._total_no = 0

    def run_triage_batch(self) -> list[TriagedSignal]:
        """Process one batch of untriaged signals from the dirty pool.

        Returns list of TriagedSignal objects with verdicts.
        Marks processed signals as triaged in the pool regardless of verdict.
        """
        batch_size = config.DARKWEB_TRIAGE_BATCH_SIZE
        raw_docs = self.pool.get_untriaged(limit=batch_size)
        if not raw_docs:
            logger.debug("[DarkTriage] No untriaged signals in dirty pool")
            return []

        logger.info("[DarkTriage] Processing batch of %d signals", len(raw_docs))

        # Build LLM prompt
        user_msg = _build_triage_user_message(raw_docs)

        # LLM call — no thinking needed (fast analytical task)
        try:
            llm_response = self.llm.call(
                system_prompt=_TRIAGE_SYSTEM_PROMPT,
                user_prompt=user_msg,
                max_tokens=2048,
                temperature=0.1,  # low temperature = consistent judgments
                thinking=False,
            )
        except Exception as exc:
            logger.error("[DarkTriage] LLM call failed: %s", exc)
            # Mark all as triaged with NO to prevent infinite retry
            for doc in raw_docs:
                self.pool.mark_triaged(
                    doc.get("_id"),
                    {"verdict": "NO", "rejection_reason": "llm_failure"},
                )
            return []

        triage_results = _parse_triage_response(llm_response, len(raw_docs))
        triaged_signals: list[TriagedSignal] = []
        now = datetime.now(timezone.utc).isoformat()

        for raw_doc, triage in zip(raw_docs, triage_results):
            verdict = triage["verdict"]
            credibility_score = triage["credibility_score"]

            # Build credibility chain — full provenance audit trail
            credibility_chain = {
                "collection": {
                    "source_type": raw_doc.get("source_type"),
                    "channel": raw_doc.get("channel_name"),
                    "raw_credibility": raw_doc.get("raw_credibility"),
                    "appeared_in_n_channels": raw_doc.get("appeared_in_n_channels", 1),
                    "collected_at": raw_doc.get("collected_at"),
                },
                "triage": {
                    "credibility_score": credibility_score,
                    "false_flag_risk": triage["false_flag_risk"],
                    "source_attribution": triage["source_attribution"],
                    "language_origin": triage["language_origin"],
                    "tactical_relevance": triage["tactical_relevance"],
                    "verdict": verdict,
                    "triaged_at": now,
                },
                "synthesis": None,  # filled by DarkWhisperEngine
            }

            ts = TriagedSignal(
                text=raw_doc.get("text", ""),
                source_url=raw_doc.get("source_url", ""),
                source_type=raw_doc.get("source_type", ""),
                channel_name=raw_doc.get("channel_name", ""),
                collected_at=raw_doc.get("collected_at", now),
                published_at=raw_doc.get("published_at", now),
                raw_credibility=raw_doc.get("raw_credibility", 0.0),
                appeared_in_n_channels=raw_doc.get("appeared_in_n_channels", 1),
                content_hash=raw_doc.get("content_hash", ""),
                triaged_at=now,
                credibility_score=credibility_score,
                false_flag_risk=triage["false_flag_risk"],
                source_attribution=triage["source_attribution"],
                language_origin=triage["language_origin"],
                tactical_relevance=triage["tactical_relevance"],
                verdict=verdict,
                rejection_reason=triage.get("rejection_reason", ""),
                sanitized_summary=triage.get("sanitized_summary", ""),
                credibility_chain=credibility_chain,
                mongo_id=raw_doc.get("_id"),
            )

            # Update dirty pool
            self.pool.mark_triaged(raw_doc.get("_id"), triage)

            # Update stats
            self._total_triaged += 1
            if verdict == "YES":
                self._total_yes += 1
            elif verdict == "MAYBE":
                self._total_maybe += 1
            else:
                self._total_no += 1

            triaged_signals.append(ts)

            if verdict == "NO":
                logger.debug(
                    "[DarkTriage] NO: %.60s (reason: %s)",
                    ts.text, ts.rejection_reason,
                )
            else:
                logger.info(
                    "[DarkTriage] %s: %.60s (cred=%.2f, ff_risk=%.2f, attr=%s)",
                    verdict, ts.text, ts.credibility_score,
                    ts.false_flag_risk, ts.source_attribution,
                )

        logger.info(
            "[DarkTriage] Batch done — YES:%d MAYBE:%d NO:%d (total: YES=%d MAYBE=%d NO=%d)",
            sum(1 for s in triaged_signals if s.is_yes),
            sum(1 for s in triaged_signals if s.is_maybe),
            sum(1 for s in triaged_signals if s.is_no),
            self._total_yes, self._total_maybe, self._total_no,
        )

        # Return only YES and MAYBE signals to synthesis engine
        return [s for s in triaged_signals if not s.is_no]

    def stats(self) -> dict:
        return {
            "total_triaged": self._total_triaged,
            "total_yes": self._total_yes,
            "total_maybe": self._total_maybe,
            "total_no": self._total_no,
            "yes_rate": round(self._total_yes / self._total_triaged, 3) if self._total_triaged else 0,
            "maybe_rate": round(self._total_maybe / self._total_triaged, 3) if self._total_triaged else 0,
        }
