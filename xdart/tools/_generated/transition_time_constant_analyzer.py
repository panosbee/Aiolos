from collections import Counter, defaultdict
import re
import math

TOOL_META = {
    "name": "transition_time_constant_analyzer",
    "version": "1.0",
    "purpose": "Detects when geopolitical, economic, and institutional change is occurring faster than stabilizing interfaces can adapt, producing a temporal mismatch risk map.",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}


FAST_PATTERNS = [
    r"\bimmediate(?:ly)?\b",
    r"\burgent\b",
    r"\baccelerat(?:e|es|ed|ing|ion)\b",
    r"\bfast(?:er)?\b",
    r"\bquick(?:ly)?\b",
    r"\bswift(?:ly)?\b",
    r"\bsudden(?:ly)?\b",
    r"\bshock\b",
    r"\bescalat(?:e|es|ed|ing|ion)\b",
    r"\bdecoupl(?:e|es|ed|ing)\b",
    r"\bdetach(?:ment|ed|ing)?\b",
    r"\bsever(?:e|ing|ed)?\b",
    r"\bwithdraw(?:al|s|n)?\b",
    r"\bsanction(?:s|ed|ing)?\b",
    r"\btariff(?:s)?\b",
    r"\bban(?:s|ned)?\b",
    r"\bembargo(?:es)?\b",
    r"\bstrike(?:s|d)?\b",
    r"\battack(?:s|ed)?\b",
    r"\bmilitary\b",
    r"\bdeploy(?:ment|s|ed|ing)?\b",
    r"\brealign(?:ment|s|ed|ing)?\b",
    r"\bautonom(?:y|ous)\b",
    r"\bstrategic autonomy\b",
    r"\bde-risk(?:ing)?\b",
    r"\breset\b",
    r"\btransition\b",
]

SLOW_PATTERNS = [
    r"\bcoordination\b",
    r"\bnegotiat(?:e|ion|ions|ed|ing)\b",
    r"\bdialogue\b",
    r"\btalks?\b",
    r"\bframework\b",
    r"\bmechanism\b",
    r"\binstitution(?:s|al)?\b",
    r"\bregulat(?:e|ion|ory)\b",
    r"\bcompliance\b",
    r"\bimplementation\b",
    r"\bdiversif(?:y|ication|ied|ying)\b",
    r"\bcapacity\b",
    r"\binfrastructure\b",
    r"\bbuffer\b",
    r"\breserve(?:s)?\b",
    r"\bstorage\b",
    r"\bresilience\b",
    r"\badapt(?:ation|ive|ing)?\b",
    r"\breform\b",
    r"\bphased\b",
    r"\bgradual\b",
    r"\blong[- ]term\b",
    r"\broadmap\b",
    r"\btransition plan\b",
    r"\bceasefire\b",
    r"\bmonitor(?:ing)?\b",
]

BRIDGE_PATTERNS = {
    "energy": [r"\boil\b", r"\bgas\b", r"\benergy\b", r"\bhormuz\b", r"\blng\b", r"\bopec\+?\b"],
    "finance": [r"\bdollar\b", r"\bpayments?\b", r"\bbank(?:ing)?\b", r"\bswift\b", r"\byield\b", r"\binflation\b", r"\brate\b", r"\bfed\b", r"\becb\b"],
    "logistics": [r"\bshipping\b", r"\bport\b", r"\bcontainer\b", r"\bsupply chain\b", r"\blogistics\b", r"\btrade route\b", r"\bchokepoint\b"],
    "security": [r"\bnato\b", r"\bdeterrence\b", r"\bmilitary\b", r"\bmissile\b", r"\bnaval\b", r"\bdefense\b", r"\bsecurity\b"],
    "technology": [r"\bsemiconductor\b", r"\bchip(?:s)?\b", r"\bai\b", r"\btech(?:nology)?\b", r"\bexport control\b"],
}

PROBLEM_FAST_PATTERNS = [
    r"\bdecoupl(?:e|ing)\b",
    r"\bautonom(?:y|ous)\b",
    r"\btransition\b",
    r"\brealign(?:ment|ing)?\b",
    r"\bsystemic risk\b",
    r"\bsplit[- ]brain\b",
]


def _text(event):
    headline = str(event.get("headline", "") or "")
    domain = str(event.get("domain", "") or "")
    source = str(event.get("source_name", "") or "")
    content_type = str(event.get("content_type", "") or "")
    return " ".join([headline, domain, source, content_type]).lower()



def _count_patterns(text, patterns):
    count = 0
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            count += 1
    return count



def _match_bridges(text):
    hits = []
    for bridge, patterns in BRIDGE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                hits.append(bridge)
                break
    return hits



def _safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default



def run(context: dict) -> dict:
    events = context.get("events", []) or []
    indicators = context.get("indicators", []) or []
    problem = str(context.get("problem", "") or "")

    domain_scores = defaultdict(lambda: {
        "fast": 0.0,
        "slow": 0.0,
        "bridge_hits": Counter(),
        "events": 0,
        "salience": 0.0,
    })
    bridge_scores = defaultdict(lambda: {"fast": 0.0, "slow": 0.0, "events": 0})
    fast_examples = []
    slow_examples = []

    total_fast = 0.0
    total_slow = 0.0
    total_salience = 0.0

    for event in events:
        text = _text(event)
        domain = str(event.get("domain", "unknown") or "unknown").lower()
        salience = _safe_float(event.get("salience_score", 1.0), 1.0)
        weight = max(0.5, salience)

        fast_count = _count_patterns(text, FAST_PATTERNS)
        slow_count = _count_patterns(text, SLOW_PATTERNS)
        bridges = _match_bridges(text)

        fast_score = fast_count * weight
        slow_score = slow_count * weight

        domain_scores[domain]["fast"] += fast_score
        domain_scores[domain]["slow"] += slow_score
        domain_scores[domain]["events"] += 1
        domain_scores[domain]["salience"] += salience

        for b in bridges:
            domain_scores[domain]["bridge_hits"][b] += 1
            bridge_scores[b]["fast"] += fast_score
            bridge_scores[b]["slow"] += slow_score
            bridge_scores[b]["events"] += 1

        total_fast += fast_score
        total_slow += slow_score
        total_salience += salience

        if fast_count > 0 and len(fast_examples) < 5:
            fast_examples.append(str(event.get("headline", "")))
        if slow_count > 0 and len(slow_examples) < 5:
            slow_examples.append(str(event.get("headline", "")))

    indicator_stress = 0.0
    indicator_details = []
    key_indicator_weights = {
        "FEDFUNDS": 1.0,
        "CPIAUCSL": 0.9,
        "UNRATE": 0.8,
        "GDP": 0.8,
        "DGS10": 0.9,
        "T10YIE": 0.8,
    }

    for ind in indicators:
        name = str(ind.get("indicator", "") or "")
        value = _safe_float(ind.get("value", 0.0), 0.0)
        change = _safe_float(ind.get("change_pct", 0.0), 0.0)
        base_weight = key_indicator_weights.get(name, 0.5)
        volatility_signal = min(3.0, abs(change) / 2.0)
        level_signal = 0.0

        if name == "FEDFUNDS" and value >= 4.0:
            level_signal = 1.0
        elif name == "CPIAUCSL" and change > 0:
            level_signal = 0.8
        elif name == "UNRATE" and value >= 4.0:
            level_signal = 0.8
        elif name == "DGS10" and value >= 4.0:
            level_signal = 1.0
        elif name == "T10YIE" and value >= 2.5:
            level_signal = 0.7

        stress = base_weight * (volatility_signal + level_signal)
        indicator_stress += stress
        if stress > 0.6:
            indicator_details.append({
                "indicator": name,
                "value": value,
                "change_pct": change,
                "stress": round(stress, 2),
            })

    problem_fast = _count_patterns(problem.lower(), PROBLEM_FAST_PATTERNS)

    domain_risks = []
    for domain, stats in domain_scores.items():
        mismatch = stats["fast"] - stats["slow"]
        normalized = mismatch / max(1.0, stats["events"])
        dominant_bridges = [b for b, _ in stats["bridge_hits"].most_common(3)]
        domain_risks.append({
            "domain": domain,
            "fast": round(stats["fast"], 2),
            "slow": round(stats["slow"], 2),
            "mismatch": round(mismatch, 2),
            "normalized_mismatch": round(normalized, 2),
            "dominant_bridges": dominant_bridges,
            "events": stats["events"],
        })

    domain_risks.sort(key=lambda x: (x["normalized_mismatch"], x["mismatch"]), reverse=True)

    bridge_risks = []
    for bridge, stats in bridge_scores.items():
        mismatch = stats["fast"] - stats["slow"]
        bridge_risks.append({
            "bridge": bridge,
            "fast": round(stats["fast"], 2),
            "slow": round(stats["slow"], 2),
            "mismatch": round(mismatch, 2),
            "events": stats["events"],
        })
    bridge_risks.sort(key=lambda x: x["mismatch"], reverse=True)

    overall_mismatch = total_fast - total_slow
    denominator = max(1.0, len(events) + len(indicators))
    temporal_mismatch_index = (overall_mismatch + indicator_stress + (problem_fast * 2.0)) / denominator
    temporal_mismatch_index = round(temporal_mismatch_index, 3)

    if temporal_mismatch_index >= 1.2:
        risk_level = "high"
    elif temporal_mismatch_index >= 0.6:
        risk_level = "elevated"
    else:
        risk_level = "moderate"

    top_domains = domain_risks[:3]
    top_bridges = bridge_risks[:3]

    if top_domains:
        domain_text = ", ".join(
            f"{d['domain']} (mismatch {d['normalized_mismatch']})" for d in top_domains
        )
    else:
        domain_text = "no clear domain concentration"

    if top_bridges:
        bridge_text = ", ".join(
            f"{b['bridge']} ({b['mismatch']})" for b in top_bridges
        )
    else:
        bridge_text = "no clear bridge concentration"

    output = (
        f"[Transition Time-Constant Analyzer] Temporal mismatch risk is {risk_level}. "
        f"The event field shows more signals of rapid strategic change than of slow interface adaptation, "
        f"with a temporal mismatch index of {temporal_mismatch_index}. "
        f"Most exposed domains: {domain_text}. "
        f"Most stressed shared bridges: {bridge_text}. "
        f"Interpretation: the system may be reprioritizing alignment, coercion, or decoupling faster than buffers, coordination mechanisms, and diversification capacity can absorb, increasing risk of split-brain behavior, policy lag, and shock amplification across residual interdependence."
    )

    metadata = {
        "temporal_mismatch_index": temporal_mismatch_index,
        "risk_level": risk_level,
        "overall_fast_score": round(total_fast, 2),
        "overall_slow_score": round(total_slow, 2),
        "indicator_stress": round(indicator_stress, 2),
        "problem_fast_signal_count": problem_fast,
        "top_domains": top_domains,
        "top_bridges": top_bridges,
        "indicator_details": indicator_details[:8],
        "fast_examples": fast_examples,
        "slow_examples": slow_examples,
        "event_count": len(events),
        "indicator_count": len(indicators),
    }

    return {
        "tool_name": TOOL_META["name"],
        "output": output,
        "metadata": metadata,
    }
