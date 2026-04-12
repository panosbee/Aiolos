from collections import Counter, defaultdict
import re
import math

TOOL_META = {
    "name": "coordination_interface_gap_mapper",
    "version": "1.0",
    "purpose": "Detects fragmentation between strategic blocs and the remaining coordination interfaces that still carry shared systemic risk.",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}


def _text(event):
    parts = [
        str(event.get("headline", "") or ""),
        str(event.get("source_name", "") or ""),
        str(event.get("domain", "") or ""),
        str(event.get("content_type", "") or ""),
    ]
    return " ".join(parts).lower()


BLOC_PATTERNS = {
    "us": [
        r"\bu\.s\.\b", r"\bus\b", r"\busa\b", r"\bunited states\b", r"\bwashington\b",
        r"\bamerica\b", r"\bamerican\b",
    ],
    "china": [
        r"\bchina\b", r"\bchinese\b", r"\bbeijing\b", r"\bprc\b",
    ],
    "europe": [
        r"\beu\b", r"\beurope\b", r"\beuropean union\b", r"\beuropean\b",
        r"\bbrussels\b", r"\bgermany\b", r"\bfrance\b", r"\bitaly\b", r"\becb\b",
    ],
    "russia": [
        r"\brussia\b", r"\brussian\b", r"\bmoscow\b", r"\bkremlin\b",
    ],
    "middle_east": [
        r"\biran\b", r"\bisrael\b", r"\bsaudi\b", r"\bgulf\b", r"\bhormuz\b",
        r"\byemen\b", r"\bhouthis?\b", r"\buae\b", r"\bqatar\b",
    ],
    "indo_pacific": [
        r"\btaiwan\b", r"\bsouth china sea\b", r"\bjapan\b", r"\bkorea\b",
        r"\bphilippines\b", r"\bindo-pacific\b",
    ],
}

INTERFACE_PATTERNS = {
    "payments_finance": [
        r"\bdollar\b", r"\bswift\b", r"\bsettlement\b", r"\bpayments?\b", r"\bclearing\b",
        r"\bsanctions?\b", r"\btariffs?\b", r"\btrade\b", r"\bexport controls?\b", r"\bchips?\b",
        r"\bsemiconductors?\b", r"\bcurrency\b", r"\beur/usd\b", r"\bfx\b",
    ],
    "shipping_logistics": [
        r"\bshipping\b", r"\bmaritime\b", r"\bport\b", r"\bcontainer\b", r"\bsupply chain\b",
        r"\bfreight\b", r"\bred sea\b", r"\bhormuz\b", r"\bchokepoint\b", r"\bsea lane\b",
        r"\bstrait\b", r"\bcanal\b",
    ],
    "energy": [
        r"\boil\b", r"\bgas\b", r"\blng\b", r"\benergy\b", r"\bopec\+?\b",
        r"\bcrude\b", r"\bpipeline\b", r"\belectricity\b",
    ],
    "security_deterrence": [
        r"\bnato\b", r"\bdeterrence\b", r"\bmilitary\b", r"\bmissile\b", r"\bnavy\b",
        r"\bair defense\b", r"\bexercise\b", r"\bdrill\b", r"\bcarrier\b", r"\bstrike\b",
        r"\bceasefire\b", r"\battack\b", r"\bdefense\b",
    ],
    "crisis_communication": [
        r"\btalks?\b", r"\bnegotiat\w*\b", r"\bdiplomat\w*\b", r"\bhotline\b", r"\bmediat\w*\b",
        r"\bceasefire\b", r"\bmeeting\b", r"\bsummit\b", r"\bcoordination\b", r"\bde-escalat\w*\b",
    ],
    "standards_technology": [
        r"\bai\b", r"\b5g\b", r"\btechnology\b", r"\bstandard\b", r"\bplatform\b",
        r"\bsemiconductors?\b", r"\bchip\b", r"\bdigital\b", r"\bcyber\b",
    ],
}

FRAGMENTATION_PATTERNS = [
    r"\bdecoupl\w*\b", r"\bde-risk\w*\b", r"\bseparat\w*\b", r"\bsplit\b", r"\bautonom\w*\b",
    r"\bstrategic autonomy\b", r"\bexport controls?\b", r"\bsanctions?\b", r"\btariffs?\b",
    r"\brestrict\w*\b", r"\bban\w*\b", r"\bbloc\w*\b", r"\brealignment\b", r"\breshor\w*\b",
]

COORDINATION_PATTERNS = [
    r"\bcoordination\b", r"\bmechanism\b", r"\bchannel\b", r"\binterface\b", r"\bhotline\b",
    r"\bnegotiat\w*\b", r"\bmediat\w*\b", r"\bceasefire\b", r"\bsummit\b", r"\bmeeting\b",
    r"\bagreement\b", r"\bframework\b", r"\bverification\b", r"\bmonitor\w*\b",
]

STRESS_PATTERNS = [
    r"\bdisrupt\w*\b", r"\bshock\b", r"\bdelay\b", r"\bshortage\b", r"\bcrisis\b",
    r"\bescalat\w*\b", r"\bthreat\w*\b", r"\battack\b", r"\bparaly\w*\b", r"\bstrain\w*\b",
    r"\bvolatil\w*\b", r"\bfreeze\b", r"\bhalt\b", r"\bcut off\b",
]


def _matches_any(text, patterns):
    for p in patterns:
        if re.search(p, text):
            return True
    return False


def _count_matches(text, patterns):
    count = 0
    for p in patterns:
        if re.search(p, text):
            count += 1
    return count


def _detect_blocs(text):
    found = []
    for bloc, patterns in BLOC_PATTERNS.items():
        if _matches_any(text, patterns):
            found.append(bloc)
    return found


def _detect_interfaces(text):
    found = []
    for interface, patterns in INTERFACE_PATTERNS.items():
        if _matches_any(text, patterns):
            found.append(interface)
    return found


def _safe_change(ind):
    value = ind.get("change_pct")
    if value is None:
        return 0.0
    try:
        return abs(float(value))
    except Exception:
        return 0.0


def run(context: dict) -> dict:
    events = context.get("events", []) or []
    indicators = context.get("indicators", []) or []
    problem = str(context.get("problem", "") or "")
    problem_text = problem.lower()

    interface_stats = {}
    for name in INTERFACE_PATTERNS:
        interface_stats[name] = {
            "events": 0,
            "cross_bloc_events": 0,
            "fragmentation_events": 0,
            "coordination_events": 0,
            "stress_events": 0,
            "bloc_counter": Counter(),
            "source_counter": Counter(),
        }

    total_fragmentation_events = 0
    total_coordination_events = 0
    total_stress_events = 0
    cross_bloc_total = 0
    bloc_pair_counter = Counter()

    for event in events:
        text = _text(event)
        blocs = _detect_blocs(text)
        interfaces = _detect_interfaces(text)
        fragmentation = _matches_any(text, FRAGMENTATION_PATTERNS)
        coordination = _matches_any(text, COORDINATION_PATTERNS)
        stress = _matches_any(text, STRESS_PATTERNS)

        if fragmentation:
            total_fragmentation_events += 1
        if coordination:
            total_coordination_events += 1
        if stress:
            total_stress_events += 1
        if len(blocs) >= 2:
            cross_bloc_total += 1
            pair = tuple(sorted(blocs))
            bloc_pair_counter[pair] += 1

        for interface in interfaces:
            stats = interface_stats[interface]
            stats["events"] += 1
            if len(blocs) >= 2:
                stats["cross_bloc_events"] += 1
            if fragmentation:
                stats["fragmentation_events"] += 1
            if coordination:
                stats["coordination_events"] += 1
            if stress:
                stats["stress_events"] += 1
            stats["source_counter"][str(event.get("source_name", "unknown"))] += 1
            for bloc in blocs:
                stats["bloc_counter"][bloc] += 1

    indicator_stress = 0.0
    indicator_hits = []
    for ind in indicators:
        name = str(ind.get("indicator", "") or "").upper()
        chg = _safe_change(ind)
        if name in {"DGS10", "T10YIE", "FEDFUNDS", "CPIAUCSL", "UNRATE", "GDP"}:
            indicator_stress += min(chg, 10.0)
            if chg > 0:
                indicator_hits.append({"indicator": name, "change_pct": chg})
        elif "HICP" in name or "EUR" in name or "USD" in name or "FDI" in name:
            indicator_stress += min(chg, 10.0)
            if chg > 0:
                indicator_hits.append({"indicator": name, "change_pct": chg})

    scored = []
    for interface, stats in interface_stats.items():
        if stats["events"] == 0:
            continue
        e = float(stats["events"])
        cross_ratio = stats["cross_bloc_events"] / e
        frag_ratio = stats["fragmentation_events"] / e
        coord_ratio = stats["coordination_events"] / e
        stress_ratio = stats["stress_events"] / e
        gap_score = (0.35 * cross_ratio) + (0.30 * frag_ratio) + (0.25 * stress_ratio) - (0.20 * coord_ratio)
        gap_score = max(0.0, min(1.0, gap_score))
        scored.append({
            "interface": interface,
            "gap_score": round(gap_score, 3),
            "cross_ratio": round(cross_ratio, 3),
            "fragmentation_ratio": round(frag_ratio, 3),
            "coordination_ratio": round(coord_ratio, 3),
            "stress_ratio": round(stress_ratio, 3),
            "events": stats["events"],
            "top_blocs": [b for b, _ in stats["bloc_counter"].most_common(3)],
            "top_sources": [s for s, _ in stats["source_counter"].most_common(3)],
        })

    scored.sort(key=lambda x: (-x["gap_score"], -x["events"], x["interface"]))
    top_interfaces = scored[:3]

    problem_fragmented = _matches_any(problem_text, FRAGMENTATION_PATTERNS)
    problem_coordination = _matches_any(problem_text, COORDINATION_PATTERNS + [r"\bsystemic risk\b", r"\bautonomy\b"])

    if top_interfaces:
        summary_bits = []
        for item in top_interfaces:
            summary_bits.append(
                "%s gap_score=%s (cross-bloc=%s, fragmentation=%s, coordination=%s, stress=%s)" % (
                    item["interface"],
                    item["gap_score"],
                    item["cross_ratio"],
                    item["fragmentation_ratio"],
                    item["coordination_ratio"],
                    item["stress_ratio"],
                )
            )
        interface_summary = "; ".join(summary_bits)
    else:
        interface_summary = "No strong coordination-interface signal detected in current event set."

    dominant_pairs = ["-".join(pair) for pair, _ in bloc_pair_counter.most_common(5)]
    pair_text = ", ".join(dominant_pairs) if dominant_pairs else "none"

    overall_fragmentation_pressure = 0.0
    if events:
        overall_fragmentation_pressure = min(
            1.0,
            (0.4 * (total_fragmentation_events / float(len(events)))) +
            (0.25 * (cross_bloc_total / float(len(events)))) +
            (0.2 * (total_stress_events / float(len(events)))) +
            (0.15 * min(indicator_stress / 25.0, 1.0))
        )

    diagnosis = "balanced"
    if overall_fragmentation_pressure >= 0.6:
        diagnosis = "split_brain_risk_high"
    elif overall_fragmentation_pressure >= 0.4:
        diagnosis = "interface_strain_rising"
    elif overall_fragmentation_pressure < 0.2:
        diagnosis = "fragmentation_signal_weak"

    output = (
        "[coordination_interface_gap_mapper] Governance-interface fragmentation scan: "
        "diagnosis=%s; overall_fragmentation_pressure=%.3f. "
        "This tool looks for places where blocs are separating politically while shared interfaces still carry joint exposure. "
        "Top interface gaps: %s. "
        "Dominant cross-bloc pairings in the event stream: %s. "
        "Interpretation: high gap scores suggest residual interfaces that are still systemically load-bearing but are not matched by equally dense coordination mechanisms; these zones are where partial decoupling can compress risk into chokepoints rather than remove it." % (
            diagnosis,
            round(overall_fragmentation_pressure, 3),
            interface_summary,
            pair_text,
        )
    )

    if problem_fragmented or problem_coordination:
        output += " Problem relevance: the user query itself contains fragmentation/coordination language, so this mapping is likely directly decision-relevant."

    return {
        "tool_name": TOOL_META["name"],
        "output": output,
        "metadata": {
            "diagnosis": diagnosis,
            "overall_fragmentation_pressure": round(overall_fragmentation_pressure, 3),
            "top_interface_gaps": top_interfaces,
            "cross_bloc_event_count": cross_bloc_total,
            "fragmentation_event_count": total_fragmentation_events,
            "coordination_event_count": total_coordination_events,
            "stress_event_count": total_stress_events,
            "dominant_bloc_pairs": [
                {"pair": list(pair), "count": count} for pair, count in bloc_pair_counter.most_common(5)
            ],
            "indicator_stress_score": round(indicator_stress, 3),
            "indicator_hits": indicator_hits[:10],
            "problem_fragmentation_relevant": problem_fragmented,
            "problem_coordination_relevant": problem_coordination,
        },
    }
