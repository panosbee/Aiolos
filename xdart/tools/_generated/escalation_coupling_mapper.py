from collections import Counter, defaultdict
import re
import json

TOOL_META = {
    "name": "escalation_coupling_mapper",
    "version": "1.0",
    "purpose": "Builds a lightweight cross-theater escalation and chokepoint coupling map from world events and indicators.",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}


STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "from", "with", "by", "at", "as",
    "is", "are", "was", "were", "be", "been", "being", "that", "this", "it", "its", "their", "his", "her",
    "after", "before", "into", "over", "under", "amid", "through", "during", "about", "what", "why", "how",
    "new", "says", "say", "report", "reports", "reported", "live", "update", "updates"
}

THEATER_PATTERNS = {
    "middle_east": [
        r"\biran\b", r"\bisrael\b", r"\bgaza\b", r"\bhamas\b", r"\bhezbollah\b", r"\bhouthi",
        r"\bhouthis\b", r"\byemen\b", r"\btehran\b", r"\bsaudi\b", r"\buae\b", r"\bbahrain\b",
        r"\bkuwait\b", r"\bqatar\b", r"\bgulf\b", r"\bpersian gulf\b", r"\bhormuz\b", r"\bred sea\b",
        r"\bbab al mandeb\b", r"\bsyria\b", r"\biraq\b"
    ],
    "russia_ukraine": [
        r"\brussia\b", r"\bukraine\b", r"\bmoscow\b", r"\bkyiv\b", r"\bkremlin\b", r"\bdonetsk\b",
        r"\bluhansk\b", r"\bcrimea\b", r"\bblack sea\b", r"\bnato\b"
    ],
    "east_asia": [
        r"\bchina\b", r"\btaiwan\b", r"\bxi\b", r"\bbeijing\b", r"\bsouth china sea\b", r"\beast china sea\b",
        r"\bjapan\b", r"\bkorea\b", r"\bnorth korea\b", r"\bsouth korea\b"
    ],
    "south_asia": [
        r"\bindia\b", r"\bpakistan\b", r"\bkashmir\b", r"\bbangladesh\b"
    ],
    "europe": [
        r"\beu\b", r"\beurope\b", r"\bbrussels\b", r"\bgermany\b", r"\bfrance\b", r"\bpoland\b", r"\bbaltic\b"
    ],
    "global_maritime": [
        r"\bshipping\b", r"\bmaritime\b", r"\bport\b", r"\btanker\b", r"\bcontainer\b", r"\bsea lane\b",
        r"\bchokepoint\b", r"\btrade route\b", r"\bmerchant vessel\b"
    ]
}

ACTOR_PATTERNS = {
    "us": [r"\bus\b", r"\bu\.s\.\b", r"\bunited states\b", r"\bwashington\b", r"\bpentagon\b"],
    "iran": [r"\biran\b", r"\btehran\b", r"\bircg\b", r"\birgc\b"],
    "israel": [r"\bisrael\b", r"\bisraeli\b"],
    "russia": [r"\brussia\b", r"\bmoscow\b", r"\bkremlin\b"],
    "ukraine": [r"\bukraine\b", r"\bkyiv\b"],
    "china": [r"\bchina\b", r"\bbeijing\b"],
    "nato": [r"\bnato\b"],
    "houthis": [r"\bhouthi\b", r"\bhouthis\b"],
    "hamas": [r"\bhamas\b"],
    "hezbollah": [r"\bhezbollah\b"],
    "uae": [r"\buae\b", r"\bunited arab emirates\b"],
    "bahrain": [r"\bbahrain\b"],
    "kuwait": [r"\bkuwait\b"],
    "g7": [r"\bg7\b"],
    "eu": [r"\beu\b", r"\beuropean union\b"],
    "japan": [r"\bjapan\b"],
    "india": [r"\bindia\b"],
    "pakistan": [r"\bpakistan\b"]
}

RISK_PATTERNS = {
    "kinetic": [
        r"\battack\b", r"\battacks\b", r"\bstrike\b", r"\bstrikes\b", r"\bmissile\b", r"\bdrone\b",
        r"\bbomb\b", r"\bintercept\b", r"\braid\b", r"\bshelling\b", r"\bexplosion\b", r"\bairstrike\b"
    ],
    "mobilization": [
        r"\bdeploy\b", r"\bdeployment\b", r"\bmission\b", r"\bcarrier\b", r"\bexercise\b", r"\bdrill\b",
        r"\bairspace closed\b", r"\bbase\b", r"\btroops\b"
    ],
    "maritime": [
        r"\bhormuz\b", r"\bbab al mandeb\b", r"\bred sea\b", r"\bshipping\b", r"\btanker\b", r"\bport\b",
        r"\bmaritime\b", r"\bmerchant vessel\b", r"\btrade route\b", r"\bchokepoint\b"
    ],
    "informational": [
        r"\bfake\b", r"\bdisinformation\b", r"\bmisinformation\b", r"\bdeepfake\b", r"\bfalse image\b",
        r"\bpropaganda\b", r"\bcontradictory\b"
    ],
    "diplomatic": [
        r"\bceasefire\b", r"\btalks\b", r"\bnegotiation\b", r"\bsanction\b", r"\bwarning\b", r"\brequest\b",
        r"\bstatement\b", r"\bcondemn\b"
    ],
    "economic": [
        r"\boil\b", r"\bgas\b", r"\binflation\b", r"\btrade\b", r"\bmarket\b", r"\bsupply\b", r"\bfdi\b",
        r"\byield\b", r"\brate\b"
    ]
}

CHOKEPOINT_PATTERNS = {
    "strait_of_hormuz": [r"\bhormuz\b", r"\bstrait of hormuz\b"],
    "bab_al_mandeb": [r"\bbab al mandeb\b"],
    "red_sea": [r"\bred sea\b"],
    "black_sea": [r"\bblack sea\b"],
    "taiwan_strait": [r"\btaiwan strait\b"],
    "airspace_closure": [r"\bairspace closed\b", r"\bairspace closure\b", r"\bclosed airspace\b"]
}

INDICATOR_LINKS = {
    "FEDFUNDS": "global_financial_conditions",
    "DGS10": "global_financial_conditions",
    "T10YIE": "inflation_expectations",
    "CPIAUCSL": "inflation_pressure",
    "UNRATE": "labor_market_stress",
    "GDP": "growth_signal",
    "EURUSD": "currency_stress",
    "HICP": "euro_inflation_pressure",
    "FDI": "cross_border_capital_flow"
}


def _text(event):
    headline = str(event.get("headline", "") or "")
    summary = str(event.get("summary", "") or "")
    return (headline + " " + summary).strip().lower()


def _matches_any(text, patterns):
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False


def _extract_labels(text, pattern_map):
    labels = []
    for label, patterns in pattern_map.items():
        if _matches_any(text, patterns):
            labels.append(label)
    return labels


def _event_weight(event):
    salience = event.get("salience_score", 0.5)
    try:
        salience = float(salience)
    except Exception:
        salience = 0.5
    if salience < 0:
        salience = 0.0
    if salience > 1:
        salience = 1.0
    return 1.0 + salience


def _normalize_indicator_name(name):
    raw = str(name or "").strip()
    upper = raw.upper()
    compact = re.sub(r"[^A-Z0-9]", "", upper)
    aliases = {
        "EUR/USD": "EURUSD",
        "EURUSD": "EURUSD",
        "EUROAREAHICP": "HICP",
        "HICP": "HICP",
        "FOREIGNDIRECTINVESTMENT": "FDI",
        "FDI": "FDI"
    }
    if upper in aliases:
        return aliases[upper]
    if compact in aliases:
        return aliases[compact]
    return upper if upper else raw


def _summarize_problem(problem):
    text = str(problem or "").lower()
    themes = []
    if re.search(r"πολεμ|war|world war|παγκοσμ", text):
        themes.append("war_escalation")
    if re.search(r"econom|inflation|trade|ύφεσ|πληθωρισ", text):
        themes.append("economic_stress")
    if re.search(r"china|taiwan|iran|israel|russia|ukraine|nato", text):
        themes.append("geopolitical_focus")
    if re.search(r"risk|κίνδυν|probab|chance|πιθαν", text):
        themes.append("risk_assessment")
    return themes


def _top_terms(events, n=8):
    counter = Counter()
    for event in events:
        text = _text(event)
        words = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", text)
        for w in words:
            wl = w.lower()
            if wl not in STOPWORDS:
                counter[wl] += 1
    return [term for term, _ in counter.most_common(n)]


def run(context: dict) -> dict:
    events = context.get("events", []) or []
    indicators = context.get("indicators", []) or []
    problem = context.get("problem", "") or ""

    theater_counts = Counter()
    actor_counts = Counter()
    risk_counts = Counter()
    chokepoint_counts = Counter()
    theater_links = Counter()
    actor_links = Counter()
    bridge_events = []

    for idx, event in enumerate(events):
        text = _text(event)
        if not text:
            continue
        weight = _event_weight(event)
        theaters = _extract_labels(text, THEATER_PATTERNS)
        actors = _extract_labels(text, ACTOR_PATTERNS)
        risks = _extract_labels(text, RISK_PATTERNS)
        chokepoints = _extract_labels(text, CHOKEPOINT_PATTERNS)

        for t in theaters:
            theater_counts[t] += weight
        for a in actors:
            actor_counts[a] += weight
        for r in risks:
            risk_counts[r] += weight
        for c in chokepoints:
            chokepoint_counts[c] += weight

        unique_theaters = sorted(set(theaters))
        unique_actors = sorted(set(actors))

        if len(unique_theaters) >= 2:
            for i in range(len(unique_theaters)):
                for j in range(i + 1, len(unique_theaters)):
                    theater_links[(unique_theaters[i], unique_theaters[j])] += weight

        if len(unique_actors) >= 2:
            for i in range(len(unique_actors)):
                for j in range(i + 1, len(unique_actors)):
                    actor_links[(unique_actors[i], unique_actors[j])] += weight

        coupling_score = (max(0, len(unique_theaters) - 1) * 2.0) + (1.2 * len(chokepoints)) + (0.8 * len(risks))
        coupling_score *= weight

        if coupling_score >= 4.0:
            bridge_events.append({
                "headline": str(event.get("headline", "") or ""),
                "source_name": str(event.get("source_name", "") or ""),
                "theaters": unique_theaters,
                "actors": unique_actors,
                "risks": sorted(set(risks)),
                "chokepoints": sorted(set(chokepoints)),
                "coupling_score": round(coupling_score, 2)
            })

    bridge_events = sorted(bridge_events, key=lambda x: x["coupling_score"], reverse=True)[:6]
    top_theater_links = [
        {"pair": list(pair), "weight": round(weight, 2)}
        for pair, weight in theater_links.most_common(6)
    ]
    top_actor_links = [
        {"pair": list(pair), "weight": round(weight, 2)}
        for pair, weight in actor_links.most_common(6)
    ]

    indicator_summary = []
    indicator_channels = Counter()
    for ind in indicators:
        name = _normalize_indicator_name(ind.get("indicator", ""))
        channel = INDICATOR_LINKS.get(name)
        if not channel:
            continue
        change = ind.get("change_pct", None)
        try:
            change_val = float(change) if change is not None else None
        except Exception:
            change_val = None
        indicator_channels[channel] += 1
        indicator_summary.append({
            "indicator": name,
            "value": ind.get("value"),
            "unit": ind.get("unit"),
            "change_pct": change_val,
            "channel": channel,
            "source": ind.get("source")
        })

    problem_themes = _summarize_problem(problem)
    top_terms = _top_terms(events, n=10)

    total_coupling = sum(item["coupling_score"] for item in bridge_events)
    if total_coupling >= 28:
        coupling_level = "high"
    elif total_coupling >= 12:
        coupling_level = "moderate"
    else:
        coupling_level = "low"

    dominant_theaters = [name for name, _ in theater_counts.most_common(4)]
    dominant_risks = [name for name, _ in risk_counts.most_common(4)]
    dominant_chokepoints = [name for name, _ in chokepoint_counts.most_common(4)]

    lines = []
    lines.append("=== EVOLUTION TOOL: ESCALATION COUPLING MAPPER ===")
    lines.append(f"Problem themes detected: {', '.join(problem_themes) if problem_themes else 'none explicit'}.")
    lines.append(f"Coupling level from current event field: {coupling_level}.")
    lines.append(f"Dominant theaters: {', '.join(dominant_theaters) if dominant_theaters else 'none detected'}.")
    lines.append(f"Dominant risk modes: {', '.join(dominant_risks) if dominant_risks else 'none detected'}.")
    lines.append(f"Key chokepoints/signals: {', '.join(dominant_chokepoints) if dominant_chokepoints else 'none detected'}.")

    if top_theater_links:
        rendered = [f"{item['pair'][0]} ↔ {item['pair'][1]} ({item['weight']})" for item in top_theater_links[:4]]
        lines.append("Strongest cross-theater couplings: " + "; ".join(rendered) + ".")

    if bridge_events:
        lines.append("Highest-coupling bridge events:")
        for item in bridge_events[:4]:
            headline = item["headline"] or "Untitled event"
            source = item["source_name"] or "unknown source"
            theaters_txt = ", ".join(item["theaters"]) if item["theaters"] else "none"
            risks_txt = ", ".join(item["risks"]) if item["risks"] else "none"
            choke_txt = ", ".join(item["chokepoints"]) if item["chokepoints"] else "none"
            lines.append(
                f"- [{source}] {headline} | theaters: {theaters_txt} | risks: {risks_txt} | chokepoints: {choke_txt} | coupling_score: {item['coupling_score']}"
            )

    if indicator_channels:
        rendered_channels = [f"{k}({v})" for k, v in indicator_channels.most_common()]
        lines.append("Economic transmission channels present in indicators: " + ", ".join(rendered_channels) + ".")

    if top_terms:
        lines.append("Recurring event vocabulary: " + ", ".join(top_terms[:8]) + ".")

    lines.append(
        "Interpretive note: elevated risk comes less from one declared total war than from bridge events that connect theaters, chokepoints, actors, and information stress into a shared escalation graph."
    )

    metadata = {
        "problem_themes": problem_themes,
        "coupling_level": coupling_level,
        "dominant_theaters": dominant_theaters,
        "dominant_risks": dominant_risks,
        "dominant_chokepoints": dominant_chokepoints,
        "top_theater_links": top_theater_links,
        "top_actor_links": top_actor_links,
        "bridge_events": bridge_events,
        "indicator_channels": dict(indicator_channels),
        "indicator_summary": indicator_summary[:12],
        "top_terms": top_terms,
        "event_count": len(events),
        "indicator_count": len(indicators)
    }

    return {
        "tool_name": TOOL_META["name"],
        "output": "\n".join(lines),
        "metadata": metadata,
    }
