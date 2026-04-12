from collections import Counter, defaultdict
import re
import math

TOOL_META = {
    "name": "trigger_incident_pathway_analyzer",
    "version": "1.0",
    "purpose": "Detects high-risk trigger incidents and maps the most plausible accidental-escalation pathways they could activate.",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}

TRIGGER_PATTERNS = {
    "shipping_attack": [
        r"hormuz", r"strait", r"shipping", r"tanker", r"merchant vessel", r"vessel",
        r"maritime", r"sea lane", r"waterway", r"escort", r"naval convoy", r"insurance"
    ],
    "base_strike": [
        r"base", r"airbase", r"military facility", r"troops", r"garrison", r"force protection",
        r"deployment", r"missile defense", r"basing"
    ],
    "mass_casualty": [
        r"killed", r"dead", r"casualties", r"mass casualty", r"civilian deaths", r"wounded",
        r"fatalities", r"injured"
    ],
    "leadership_targeting": [
        r"leader", r"supreme leader", r"president", r"prime minister", r"regime", r"assassination",
        r"decapitation", r"finish the job", r"eliminate", r"targeted killing"
    ],
    "retaliation_signal": [
        r"retaliat", r"revenge", r"response", r"counterattack", r"reprisal", r"will respond",
        r"warned", r"threat", r"vowed"
    ],
    "nuclear_signal": [
        r"nuclear", r"atomic", r"uranium", r"enrichment", r"reactor"
    ],
    "closure_disruption": [
        r"close", r"closure", r"blockade", r"shutdown", r"disrupt", r"halt", r"suspend",
        r"reopen", r"traffic", r"exports slowing", r"exports are slowing"
    ],
    "diplomatic_channel": [
        r"talks", r"negotiat", r"ceasefire", r"de-escalat", r"diplomatic", r"un", r"mediat",
        r"channel", r"dialogue", r"coordination"
    ]
}

ACTOR_PATTERNS = {
    "US": [r"\bu\.s\.\b", r"\bus\b", r"united states", r"america", r"american", r"trump", r"washington"],
    "Iran": [r"iran", r"iranian", r"tehran"],
    "Israel": [r"israel", r"israeli", r"jerusalem"],
    "Gulf": [r"gcc", r"saudi", r"uae", r"qatar", r"bahrain", r"kuwait", r"gulf"],
    "Russia": [r"russia", r"russian", r"moscow", r"kremlin"],
    "China": [r"china", r"chinese", r"beijing"],
    "Europe": [r"eu", r"europe", r"britain", r"uk", r"france", r"germany"]
}

ESCALATORY_WORDS = [
    r"attack", r"strike", r"missile", r"drone", r"bomb", r"intercept", r"threat", r"warn",
    r"retaliat", r"finish the job", r"destroy", r"escalat", r"military"
]

DECONFLICTION_WORDS = [
    r"ceasefire", r"talks", r"de-escalat", r"mediat", r"dialogue", r"coordination", r"reopen",
    r"protect waterways", r"un", r"diplomatic"
]

ENERGY_INDICATORS = {"DGS10", "FEDFUNDS", "CPIAUCSL", "T10YIE", "GDP", "UNRATE"}


def _text(event):
    parts = [
        str(event.get("headline", "") or ""),
        str(event.get("summary", "") or ""),
        str(event.get("source_name", "") or ""),
        str(event.get("domain", "") or "")
    ]
    return " ".join(parts).lower()


def _count_matches(text, patterns):
    count = 0
    for pat in patterns:
        if re.search(pat, text):
            count += 1
    return count


def _detect_actors(text):
    found = []
    for actor, patterns in ACTOR_PATTERNS.items():
        if any(re.search(p, text) for p in patterns):
            found.append(actor)
    return found


def _event_score(event):
    text = _text(event)
    salience = event.get("salience_score", 0.0) or 0.0
    trigger_hits = {k: _count_matches(text, v) for k, v in TRIGGER_PATTERNS.items()}
    escalatory = _count_matches(text, ESCALATORY_WORDS)
    deconfliction = _count_matches(text, DECONFLICTION_WORDS)
    actors = _detect_actors(text)

    score = 0.0
    score += trigger_hits["shipping_attack"] * 2.2
    score += trigger_hits["base_strike"] * 2.0
    score += trigger_hits["mass_casualty"] * 2.4
    score += trigger_hits["leadership_targeting"] * 2.3
    score += trigger_hits["retaliation_signal"] * 1.5
    score += trigger_hits["nuclear_signal"] * 1.8
    score += trigger_hits["closure_disruption"] * 1.7
    score += escalatory * 1.2
    score -= deconfliction * 0.8
    score += min(float(salience), 10.0) * 0.35

    if len(actors) >= 2:
        score += 1.0
    if {"US", "Iran", "Israel"}.intersection(set(actors)) and len(actors) >= 2:
        score += 1.2

    return {
        "headline": event.get("headline", ""),
        "source_name": event.get("source_name", ""),
        "domain": event.get("domain", ""),
        "actors": actors,
        "trigger_hits": trigger_hits,
        "escalatory_hits": escalatory,
        "deconfliction_hits": deconfliction,
        "risk_score": round(score, 2),
    }


def _pathway_from_event(scored_event):
    hits = scored_event["trigger_hits"]
    pathways = []

    if hits["shipping_attack"] or hits["closure_disruption"]:
        pathways.append("shipping incident -> escort/protection deployment -> misidentification or interception -> wider maritime confrontation -> energy/logistics shock")
    if hits["base_strike"]:
        pathways.append("base strike -> force-protection surge -> retaliatory strike cycle -> alliance pull-in risk")
    if hits["mass_casualty"]:
        pathways.append("mass-casualty event -> domestic pressure for visible retaliation -> compressed decision time -> overreaction risk")
    if hits["leadership_targeting"]:
        pathways.append("leadership-targeting rhetoric/event -> regime survival framing -> reduced compromise space -> asymmetric retaliation")
    if hits["nuclear_signal"]:
        pathways.append("nuclear signaling -> worst-case assumptions -> preemption pressure -> strategic escalation")
    if hits["retaliation_signal"] and not pathways:
        pathways.append("retaliatory signaling -> credibility contest -> action-reaction loop -> accidental regional widening")

    return pathways[:3]


def _indicator_stress(indicators):
    stress = []
    total = 0.0
    for ind in indicators:
        name = str(ind.get("indicator", "") or "")
        change = ind.get("change_pct", None)
        if name in ENERGY_INDICATORS and change is not None:
            magnitude = abs(float(change))
            total += magnitude
            if magnitude >= 1.0:
                stress.append({"indicator": name, "change_pct": round(float(change), 2)})
    return round(total, 2), stress[:8]


def run(context: dict) -> dict:
    events = context.get("events", []) or []
    indicators = context.get("indicators", []) or []
    problem = str(context.get("problem", "") or "")

    scored = []
    category_counter = Counter()
    actor_counter = Counter()

    for event in events:
        s = _event_score(event)
        if s["risk_score"] > 0:
            scored.append(s)
            for k, v in s["trigger_hits"].items():
                if v > 0:
                    category_counter[k] += 1
            for actor in s["actors"]:
                actor_counter[actor] += 1

    scored.sort(key=lambda x: x["risk_score"], reverse=True)
    top_events = scored[:5]

    pathway_counter = Counter()
    for ev in top_events:
        for p in _pathway_from_event(ev):
            pathway_counter[p] += 1

    indicator_total_stress, stressed_indicators = _indicator_stress(indicators)

    problem_lower = problem.lower()
    ww3_focus = any(term in problem_lower for term in ["3", "wwiii", "world war", "παγκοσ", "3ουππ", "3ο ππ"])

    overall_risk = sum(e["risk_score"] for e in top_events)
    if ww3_focus:
        overall_risk += 2.0
    overall_risk += min(indicator_total_stress / 5.0, 3.0)

    if overall_risk >= 32:
        risk_band = "high"
    elif overall_risk >= 20:
        risk_band = "elevated"
    else:
        risk_band = "guarded"

    dominant_categories = [k for k, _ in category_counter.most_common(4)]
    dominant_actors = [k for k, _ in actor_counter.most_common(5)]
    top_pathways = [p for p, _ in pathway_counter.most_common(3)]

    lines = []
    lines.append("Trigger Incident Pathway Analyzer:")
    lines.append(f"Accidental-escalation risk band: {risk_band}.")
    if dominant_categories:
        lines.append("Most active trigger classes: " + ", ".join(dominant_categories) + ".")
    if dominant_actors:
        lines.append("Most exposed actors in trigger reporting: " + ", ".join(dominant_actors) + ".")
    if top_pathways:
        lines.append("Most plausible escalation pathways: " + " | ".join(top_pathways) + ".")
    if top_events:
        event_bits = []
        for ev in top_events[:3]:
            event_bits.append(f"[{ev['source_name']}] {ev['headline']} (risk {ev['risk_score']})")
        lines.append("Top trigger-bearing events: " + " ; ".join(event_bits) + ".")
    if stressed_indicators:
        ind_bits = [f"{x['indicator']} {x['change_pct']}%" for x in stressed_indicators[:4]]
        lines.append("Background macro stress amplifiers: " + ", ".join(ind_bits) + ".")
    lines.append("Interpretation: the key danger is not automatic world war declaration but a trigger incident that compresses verification time and forces rapid retaliation decisions across already-coupled theaters.")

    return {
        "tool_name": TOOL_META["name"],
        "output": "\n".join(lines),
        "metadata": {
            "risk_band": risk_band,
            "top_events": top_events,
            "dominant_categories": dominant_categories,
            "dominant_actors": dominant_actors,
            "top_pathways": top_pathways,
            "indicator_stress_total": indicator_total_stress,
            "stressed_indicators": stressed_indicators,
            "events_analyzed": len(events),
            "indicators_analyzed": len(indicators)
        }
    }
