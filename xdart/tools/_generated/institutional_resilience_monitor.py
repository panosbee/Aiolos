import re
from collections import Counter, defaultdict

TOOL_META = {
    "name": "institutional_resilience_monitor",
    "version": "1.0",
    "purpose": "Detects cross-domain signals of institutional strain, legitimacy erosion, and adaptive resilience from world events and indicators.",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}


def _text(event):
    parts = [
        str(event.get("headline", "") or ""),
        str(event.get("domain", "") or ""),
        str(event.get("content_type", "") or ""),
        str(event.get("source_name", "") or ""),
    ]
    return " ".join(parts).lower()


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _clip(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def run(context: dict) -> dict:
    events = context.get("events", []) or []
    indicators = context.get("indicators", []) or []
    problem = str(context.get("problem", "") or "")

    categories = {
        "legitimacy_strain": [
            r"protest", r"demonstrat", r"riot", r"crackdown", r"curfew", r"emergency",
            r"censorship", r"arrest", r"detain", r"ban", r"election", r"fraud",
            r"corruption", r"rights?", r"court", r"constitution", r"parliament",
            r"martial law", r"authoritarian", r"repression", r"police"
        ],
        "information_disorder": [
            r"conflicting", r"contradict", r"misinformation", r"disinformation",
            r"propaganda", r"fake", r"unverified", r"claims", r"narrative",
            r"cyber", r"hack", r"deepfake", r"platform", r"media", r"signal"
        ],
        "economic_stress": [
            r"inflation", r"unemployment", r"layoffs?", r"stagnat", r"recession",
            r"debt", r"default", r"shortage", r"poverty", r"housing", r"wages?",
            r"cost of living", r"tariff", r"trade", r"sanction", r"exports?", r"imports?"
        ],
        "energy_supply_stress": [
            r"oil", r"gas", r"lng", r"energy", r"hormuz", r"shipping", r"strait",
            r"chokepoint", r"blackout", r"power", r"electricity", r"fuel", r"refinery"
        ],
        "conflict_security": [
            r"war", r"missile", r"strike", r"attack", r"troops?", r"ceasefire",
            r"military", r"nuclear", r"drone", r"navy", r"border", r"terror",
            r"hostage", r"evacuation"
        ],
        "adaptive_response": [
            r"agreement", r"ceasefire", r"reform", r"recovery", r"aid", r"cooperation",
            r"negotiation", r"de-escalat", r"investment", r"stabiliz", r"resilience",
            r"support package", r"safeguard", r"oversight", r"regulation", r"transition"
        ],
    }

    category_counts = Counter()
    category_salience = defaultdict(float)
    category_examples = defaultdict(list)
    source_diversity = defaultdict(set)
    event_hits = []

    for event in events:
        text = _text(event)
        salience = _safe_float(event.get("salience_score"), 0.5)
        matched = []
        for category, patterns in categories.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    category_counts[category] += 1
                    category_salience[category] += salience
                    source_diversity[category].add(str(event.get("source_name", "") or "unknown"))
                    if len(category_examples[category]) < 3:
                        category_examples[category].append(str(event.get("headline", "") or ""))
                    matched.append(category)
                    break
        if matched:
            event_hits.append({
                "headline": str(event.get("headline", "") or ""),
                "matched_categories": matched,
                "salience": salience,
            })

    indicator_map = {}
    for ind in indicators:
        name = str(ind.get("indicator", "") or "").upper()
        indicator_map[name] = ind

    indicator_signals = []
    econ_risk = 0.0
    resilience_credit = 0.0

    if "UNRATE" in indicator_map:
        unrate = _safe_float(indicator_map["UNRATE"].get("value"))
        chg = indicator_map["UNRATE"].get("change_pct")
        if unrate >= 5.0:
            econ_risk += 0.18
            indicator_signals.append(f"UNRATE elevated at {unrate:.2f}")
        if chg is not None and _safe_float(chg) > 2.0:
            econ_risk += 0.08
            indicator_signals.append(f"UNRATE rising ({_safe_float(chg):.2f}% change)")

    if "CPIAUCSL" in indicator_map:
        cpi_chg = indicator_map["CPIAUCSL"].get("change_pct")
        if cpi_chg is not None and _safe_float(cpi_chg) > 3.0:
            econ_risk += 0.15
            indicator_signals.append(f"CPI pressure present ({_safe_float(cpi_chg):.2f}% change)")
        elif cpi_chg is not None and _safe_float(cpi_chg) < 2.0:
            resilience_credit += 0.05

    if "FEDFUNDS" in indicator_map and "DGS10" in indicator_map:
        fed = _safe_float(indicator_map["FEDFUNDS"].get("value"))
        dgs10 = _safe_float(indicator_map["DGS10"].get("value"))
        if fed > 4.5 and dgs10 > 4.0:
            econ_risk += 0.10
            indicator_signals.append(f"Tight monetary-financial conditions (FEDFUNDS {fed:.2f}, DGS10 {dgs10:.2f})")

    if "T10YIE" in indicator_map:
        breakeven = _safe_float(indicator_map["T10YIE"].get("value"))
        if breakeven >= 2.5:
            econ_risk += 0.06
            indicator_signals.append(f"Inflation expectations not fully anchored (T10YIE {breakeven:.2f})")
        elif 1.8 <= breakeven <= 2.4:
            resilience_credit += 0.04

    if "GDP" in indicator_map:
        gdp_chg = indicator_map["GDP"].get("change_pct")
        if gdp_chg is not None and _safe_float(gdp_chg) < 0:
            econ_risk += 0.12
            indicator_signals.append(f"GDP weakening ({_safe_float(gdp_chg):.2f}% change)")
        elif gdp_chg is not None and _safe_float(gdp_chg) > 1.5:
            resilience_credit += 0.06

    if "EURUSD" in indicator_map:
        fx_chg = indicator_map["EURUSD"].get("change_pct")
        if fx_chg is not None and abs(_safe_float(fx_chg)) > 3.0:
            econ_risk += 0.05
            indicator_signals.append(f"FX volatility signal in EUR/USD ({_safe_float(fx_chg):.2f}% change)")

    total_events = max(len(events), 1)

    def norm_count(cat):
        return category_counts[cat] / total_events

    def norm_salience(cat):
        return category_salience[cat] / total_events

    legitimacy_score = _clip(norm_count("legitimacy_strain") * 3.0 + norm_salience("legitimacy_strain") * 0.6)
    info_score = _clip(norm_count("information_disorder") * 3.5 + norm_salience("information_disorder") * 0.6)
    economic_score = _clip(norm_count("economic_stress") * 2.8 + norm_salience("economic_stress") * 0.5 + econ_risk)
    energy_score = _clip(norm_count("energy_supply_stress") * 3.2 + norm_salience("energy_supply_stress") * 0.6)
    conflict_score = _clip(norm_count("conflict_security") * 2.8 + norm_salience("conflict_security") * 0.5)
    adaptive_score = _clip(norm_count("adaptive_response") * 2.5 + norm_salience("adaptive_response") * 0.5 + resilience_credit)

    strain_components = {
        "legitimacy": legitimacy_score,
        "information": info_score,
        "economic": economic_score,
        "energy": energy_score,
        "conflict": conflict_score,
    }

    strain_index = _clip(
        legitimacy_score * 0.24 +
        info_score * 0.20 +
        economic_score * 0.22 +
        energy_score * 0.14 +
        conflict_score * 0.20
    )

    resilience_index = _clip(adaptive_score * 0.7 + max(0.0, 1.0 - strain_index) * 0.3)
    displacement_risk = _clip(strain_index * 0.72 + info_score * 0.18 - adaptive_score * 0.20)

    if strain_index >= 0.72:
        regime = "high institutional strain"
    elif strain_index >= 0.45:
        regime = "elevated institutional strain"
    else:
        regime = "mixed or manageable strain"

    top_pressures = sorted(strain_components.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_pressure_text = ", ".join([f"{k}={v:.2f}" for k, v in top_pressures])

    example_lines = []
    for cat in ["legitimacy_strain", "information_disorder", "economic_stress", "energy_supply_stress", "adaptive_response"]:
        if category_examples[cat]:
            label = cat.replace("_", " ")
            example_lines.append(f"- {label}: " + "; ".join(category_examples[cat][:2]))

    source_lines = []
    for cat, sources in source_diversity.items():
        if len(sources) >= 2:
            source_lines.append(f"{cat} seen across {len(sources)} sources")

    output_parts = []
    output_parts.append("=== INSTITUTIONAL RESILIENCE MONITOR ===")
    output_parts.append(
        f"System reading: {regime}. Strain index={strain_index:.2f}, resilience index={resilience_index:.2f}, institutional self-displacement risk={displacement_risk:.2f}."
    )
    output_parts.append(
        f"Primary pressure pattern: {top_pressure_text}. This estimates whether governance systems are losing adaptive coherence faster than they are restoring legitimacy and coordination."
    )

    if indicator_signals:
        output_parts.append("Indicator stress signals: " + " | ".join(indicator_signals[:5]))

    if source_lines:
        output_parts.append("Cross-source spread: " + "; ".join(source_lines[:5]))

    if example_lines:
        output_parts.append("Event examples:\n" + "\n".join(example_lines[:5]))

    if displacement_risk >= 0.68:
        output_parts.append(
            "Interpretation: conditions favor institutional self-displacement risk — under multi-domain stress, systems may increasingly offload judgment, truth arbitration, and coordination authority to rigid technical or algorithmic processes because they appear calmer than contested human institutions."
        )
    elif resilience_index >= 0.58:
        output_parts.append(
            "Interpretation: despite visible strain, adaptive capacity remains present; the key question is whether reforms, de-escalation, and institutional learning can scale faster than crisis coupling."
        )
    else:
        output_parts.append(
            "Interpretation: strain is meaningful but not yet decisively one-way; watch whether information disorder and legitimacy erosion begin reinforcing each other across multiple domains."
        )

    if re.search(r"ai|τεχνητ|ανθρωπ|human|civilization|civilisation|governance|institution", problem.lower()):
        output_parts.append(
            "Problem relevance: for questions about humanity, AI, or civilizational survival, the key variable is not only capability growth but whether institutions remain trusted enough to govern high-complexity systems without surrendering agency."
        )

    metadata = {
        "strain_index": round(strain_index, 4),
        "resilience_index": round(resilience_index, 4),
        "institutional_self_displacement_risk": round(displacement_risk, 4),
        "regime": regime,
        "category_counts": dict(category_counts),
        "top_pressures": [{"category": k, "score": round(v, 4)} for k, v in top_pressures],
        "indicator_signals": indicator_signals[:8],
        "matched_event_count": len(event_hits),
    }

    return {
        "tool_name": TOOL_META["name"],
        "output": "\n".join(output_parts),
        "metadata": metadata,
    }
