import re
from collections import Counter, defaultdict

TOOL_META = {
    "name": "diplomatic_signal_tracker",
    "version": "1.0",
    "purpose": "Extracts and summarizes diplomatic posture, escalation language, and signal coherence from world events to estimate whether the current environment favors de-escalation, coercive bargaining, or fragmentation.",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}


DEESCALATION_PATTERNS = [
    r"\bceasefire\b",
    r"\btruce\b",
    r"\btalks?\b",
    r"\bnegotiat(?:e|ion|ions|ing)\b",
    r"\bdiplomatic\b",
    r"\bmediat(?:e|ion|or)\b",
    r"\bagreement\b",
    r"\bdeal\b",
    r"\bresume dialogue\b",
    r"\bpeace\b",
    r"\bsettlement\b",
    r"\bopen corridor\b",
    r"\breopen\b",
    r"\bhumanitarian pause\b",
    r"\bde-escalat(?:e|ion|ing)\b",
]

ESCALATION_PATTERNS = [
    r"\bstrike(?:s|d|ing)?\b",
    r"\battack(?:s|ed|ing)?\b",
    r"\bbomb(?:s|ed|ing)?\b",
    r"\bmissile(?:s)?\b",
    r"\bdrone(?:s)?\b",
    r"\bretaliat(?:e|ion|ory)\b",
    r"\boffensive\b",
    r"\bmilitary action\b",
    r"\bthreat(?:s)?\b",
    r"\bwarn(?:s|ed|ing)?\b",
    r"\bdeploy(?:s|ed|ment)?\b",
    r"\bblockade\b",
    r"\bclosure\b",
    r"\bban\b",
    r"\bsanction(?:s|ed)?\b",
    r"\bescalat(?:e|ion|ing)\b",
]

COERCIVE_BARGAINING_PATTERNS = [
    r"\bdemand(?:s|ed)?\b",
    r"\bultimatum\b",
    r"\bcondition(?:al|s)?\b",
    r"\bunless\b",
    r"\bpressure\b",
    r"\bleverage\b",
    r"\bred line\b",
    r"\bcomplete end\b",
    r"\bnot rule out\b",
    r"\bdeadline\b",
    r"\binsist(?:s|ed|ing)?\b",
]

FRAGMENTATION_PATTERNS = [
    r"\bdispute(?:s|d)?\b",
    r"\bdivision(?:s)?\b",
    r"\bdeadlock\b",
    r"\bno consensus\b",
    r"\bsplit\b",
    r"\bclash(?:es)?\b",
    r"\brefus(?:e|al|es|ed)\b",
    r"\bwalk(?:ed)? out\b",
    r"\bcollapse(?:d)?\b",
    r"\bgridlock\b",
    r"\buncertain\b",
    r"\bconfusion\b",
]

ACTOR_PATTERNS = {
    "US": [r"\bU\.S\.\b", r"\bUS\b", r"\bUnited States\b", r"\bWashington\b", r"\bWhite House\b", r"\bPentagon\b"],
    "Iran": [r"\bIran\b", r"\bTehran\b", r"\bIranian\b"],
    "Israel": [r"\bIsrael\b", r"\bIsraeli\b", r"\bJerusalem\b"],
    "Lebanon": [r"\bLebanon\b", r"\bLebanese\b", r"\bBeirut\b", r"\bHezbollah\b"],
    "Saudi Arabia": [r"\bSaudi\b", r"\bRiyadh\b"],
    "Turkey": [r"\bTurkey\b", r"\bTurkish\b", r"\bAnkara\b"],
    "Egypt": [r"\bEgypt\b", r"\bCairo\b", r"\bEgyptian\b"],
    "Qatar": [r"\bQatar\b", r"\bDoha\b"],
    "UAE": [r"\bUAE\b", r"\bUnited Arab Emirates\b", r"\bAbu Dhabi\b", r"\bDubai\b"],
    "EU": [r"\bEU\b", r"\bEuropean Union\b", r"\bBrussels\b"],
    "UK": [r"\bUK\b", r"\bBritain\b", r"\bBritish\b", r"\bLondon\b"],
    "Russia": [r"\bRussia\b", r"\bRussian\b", r"\bMoscow\b"],
    "China": [r"\bChina\b", r"\bChinese\b", r"\bBeijing\b"],
    "UN": [r"\bUN\b", r"\bUnited Nations\b"],
    "NATO": [r"\bNATO\b"],
}

CHOKEPOINT_PATTERNS = {
    "Hormuz": [r"\bHormuz\b", r"\bStrait of Hormuz\b"],
    "Red Sea": [r"\bRed Sea\b"],
    "Suez": [r"\bSuez\b"],
    "Eastern Mediterranean": [r"\bEastern Mediterranean\b", r"\bMediterranean\b"],
    "Bab el-Mandeb": [r"\bBab el-Mandeb\b"],
    "Levant": [r"\bLevant\b"],
}


def _text(event):
    headline = str(event.get("headline", "") or "")
    summary = str(event.get("summary", "") or "")
    return (headline + " " + summary).strip()


def _count_matches(text, patterns):
    total = 0
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            total += 1
    return total


def _detect_actors(text):
    found = []
    for actor, patterns in ACTOR_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text, flags=re.IGNORECASE):
                found.append(actor)
                break
    return found


def _detect_chokepoints(text):
    found = []
    for name, patterns in CHOKEPOINT_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text, flags=re.IGNORECASE):
                found.append(name)
                break
    return found


def _classify_event(text):
    de = _count_matches(text, DEESCALATION_PATTERNS)
    es = _count_matches(text, ESCALATION_PATTERNS)
    cb = _count_matches(text, COERCIVE_BARGAINING_PATTERNS)
    fr = _count_matches(text, FRAGMENTATION_PATTERNS)
    return {
        "deescalation": de,
        "escalation": es,
        "coercive_bargaining": cb,
        "fragmentation": fr,
    }


def _score_event(event):
    salience = event.get("salience_score", 1.0)
    try:
        salience = float(salience)
    except Exception:
        salience = 1.0
    if salience < 0:
        salience = 0.0
    return 1.0 + salience


def run(context: dict) -> dict:
    events = context.get("events", []) or []
    indicators = context.get("indicators", []) or []
    problem = str(context.get("problem", "") or "")

    posture_scores = Counter()
    actor_scores = defaultdict(Counter)
    actor_mentions = Counter()
    chokepoint_mentions = Counter()
    domain_counts = Counter()
    source_counts = Counter()
    key_events = []

    for event in events:
        text = _text(event)
        if not text:
            continue

        domain = str(event.get("domain", "unknown") or "unknown")
        source = str(event.get("source_name", "unknown") or "unknown")
        weight = _score_event(event)
        labels = _classify_event(text)
        actors = _detect_actors(text)
        chokepoints = _detect_chokepoints(text)

        domain_counts[domain] += 1
        source_counts[source] += 1

        for label, count in labels.items():
            posture_scores[label] += count * weight

        for actor in actors:
            actor_mentions[actor] += 1
            for label, count in labels.items():
                actor_scores[actor][label] += count * weight

        for cp in chokepoints:
            chokepoint_mentions[cp] += 1

        total_signal = sum(labels.values())
        if total_signal > 0:
            key_events.append({
                "headline": str(event.get("headline", "") or ""),
                "source": source,
                "domain": domain,
                "weight": round(weight, 2),
                "signal_strength": total_signal,
                "labels": labels,
                "actors": actors,
                "chokepoints": chokepoints,
            })

    key_events.sort(key=lambda x: (x["signal_strength"], x["weight"]), reverse=True)
    top_events = key_events[:5]

    escalation = posture_scores["escalation"]
    deescalation = posture_scores["deescalation"]
    coercive = posture_scores["coercive_bargaining"]
    fragmentation = posture_scores["fragmentation"]

    net_pressure = escalation + coercive - deescalation

    if net_pressure > fragmentation * 1.2 and net_pressure > 3:
        posture = "coercive-escalatory"
    elif deescalation > escalation + coercive and deescalation > 3:
        posture = "de-escalatory"
    elif fragmentation >= max(escalation, deescalation, coercive) and fragmentation > 2:
        posture = "fragmented"
    else:
        posture = "contested-mixed"

    coherence_signals = []
    for actor, scores in actor_scores.items():
        total = sum(scores.values())
        if total <= 0:
            continue
        dominant_label, dominant_value = max(scores.items(), key=lambda kv: kv[1])
        share = dominant_value / total if total else 0.0
        coherence_signals.append((actor, dominant_label, share, total))

    coherence_signals.sort(key=lambda x: (x[2], x[3]), reverse=True)
    high_coherence = [c for c in coherence_signals if c[2] >= 0.6 and c[3] >= 2]
    low_coherence = [c for c in coherence_signals if c[2] < 0.45 and c[3] >= 2]

    if len(high_coherence) >= 3 and len(low_coherence) <= 1:
        coherence_assessment = "signals show moderate-to-high actor coherence"
    elif len(low_coherence) >= 2:
        coherence_assessment = "signals show notable actor incoherence"
    else:
        coherence_assessment = "signals are mixed with limited coherence"

    top_actors = actor_mentions.most_common(5)
    top_chokepoints = chokepoint_mentions.most_common(4)

    indicator_summary = []
    important_indicators = {"FEDFUNDS", "CPIAUCSL", "UNRATE", "GDP", "DGS10", "T10YIE"}
    for ind in indicators:
        name = str(ind.get("indicator", "") or "")
        if name in important_indicators:
            change = ind.get("change_pct", None)
            value = ind.get("value", None)
            unit = str(ind.get("unit", "") or "")
            if value is not None:
                if change is None:
                    indicator_summary.append(f"{name}={value}{unit}")
                else:
                    indicator_summary.append(f"{name}={value}{unit} ({change}% change)")

    lines = []
    lines.append("=== DIPLOMATIC SIGNAL TRACKER ===")
    lines.append(f"Problem focus: {problem[:240]}")
    lines.append(
        "Signal balance: "
        f"de-escalation={round(deescalation,1)}, escalation={round(escalation,1)}, "
        f"coercive_bargaining={round(coercive,1)}, fragmentation={round(fragmentation,1)}"
    )
    lines.append(f"Estimated diplomatic posture: {posture}.")
    lines.append(f"Signal coherence assessment: {coherence_assessment}.")

    if top_actors:
        actor_bits = []
        for actor, count in top_actors:
            actor_bits.append(f"{actor}({count})")
        lines.append("Most visible actors in signaling flow: " + ", ".join(actor_bits) + ".")

    if top_chokepoints:
        cp_bits = []
        for cp, count in top_chokepoints:
            cp_bits.append(f"{cp}({count})")
        lines.append("Most referenced chokepoints/regions in diplomatic-security signaling: " + ", ".join(cp_bits) + ".")

    if high_coherence:
        bits = []
        for actor, label, share, total in high_coherence[:4]:
            bits.append(f"{actor}:{label} ({round(share*100)}% of signal, n={round(total,1)})")
        lines.append("Actors with relatively coherent posture signals: " + "; ".join(bits) + ".")

    if low_coherence:
        bits = []
        for actor, label, share, total in low_coherence[:4]:
            bits.append(f"{actor}: fragmented/mixed (dominant {label}, {round(share*100)}%, n={round(total,1)})")
        lines.append("Actors with internally mixed or noisy signaling: " + "; ".join(bits) + ".")

    if top_events:
        lines.append("Highest-signal events shaping diplomatic posture:")
        for item in top_events:
            label_order = sorted(item["labels"].items(), key=lambda kv: kv[1], reverse=True)
            label_text = ", ".join([f"{k}={v}" for k, v in label_order if v > 0])
            actor_text = ", ".join(item["actors"]) if item["actors"] else "no clear actor"
            cp_text = ", ".join(item["chokepoints"]) if item["chokepoints"] else "no chokepoint"
            lines.append(
                f"- {item['headline']} [{item['source']}/{item['domain']}] | labels: {label_text} | actors: {actor_text} | geography: {cp_text}"
            )

    if indicator_summary:
        lines.append("Macro backdrop snapshot: " + "; ".join(indicator_summary[:6]) + ".")

    if posture == "coercive-escalatory":
        lines.append("Interpretation: the environment currently looks less like stable de-escalation and more like bargaining under threat, where diplomatic language may exist but is being carried by force-backed signaling.")
    elif posture == "de-escalatory":
        lines.append("Interpretation: diplomatic language currently outweighs direct threat signaling, suggesting a temporary containment window if bridge actors remain aligned.")
    elif posture == "fragmented":
        lines.append("Interpretation: the main risk is not immediate unified escalation but a fragmented signal field in which misalignment, delay, and local triggers can undo containment.")
    else:
        lines.append("Interpretation: the signal field is mixed; analysts should treat formal de-escalation claims cautiously unless actor coherence improves and chokepoint pressure declines.")

    metadata = {
        "posture": posture,
        "coherence_assessment": coherence_assessment,
        "signal_scores": {
            "deescalation": round(deescalation, 3),
            "escalation": round(escalation, 3),
            "coercive_bargaining": round(coercive, 3),
            "fragmentation": round(fragmentation, 3),
            "net_pressure": round(net_pressure, 3),
        },
        "top_actors": top_actors,
        "top_chokepoints": top_chokepoints,
        "high_coherence_actors": [
            {"actor": a, "dominant_signal": l, "share": round(s, 3), "total": round(t, 3)}
            for a, l, s, t in high_coherence[:6]
        ],
        "low_coherence_actors": [
            {"actor": a, "dominant_signal": l, "share": round(s, 3), "total": round(t, 3)}
            for a, l, s, t in low_coherence[:6]
        ],
        "top_events": top_events,
        "domains_seen": domain_counts.most_common(),
        "sources_seen": source_counts.most_common(),
    }

    return {
        "tool_name": TOOL_META["name"],
        "output": "\n".join(lines),
        "metadata": metadata,
    }
