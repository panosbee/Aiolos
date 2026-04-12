from collections import Counter, defaultdict
import re
import math

TOOL_META = {
    "name": "strategic_dependency_bridge_mapper",
    "version": "1.0",
    "purpose": "Maps residual cross-domain dependency bridges and chokepoint concentration from world events and indicators to reveal where partial decoupling can still propagate systemic shocks.",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}


def _text(event):
    headline = str(event.get("headline", "") or "")
    summary = str(event.get("summary", "") or "")
    domain = str(event.get("domain", "") or "")
    source = str(event.get("source_name", "") or "")
    return " ".join([headline, summary, domain, source]).lower()


INTERFACE_PATTERNS = {
    "energy": [
        r"\boil\b", r"\bgas\b", r"\blng\b", r"\benergy\b", r"\bpetroleum\b",
        r"\bcrude\b", r"\brefin", r"\bopec\b", r"\bhormuz\b", r"\bpipeline\b"
    ],
    "shipping_logistics": [
        r"\bshipping\b", r"\bmaritime\b", r"\bport\b", r"\bfreight\b", r"\blogistics\b",
        r"\bcontainer\b", r"\bsea lane\b", r"\bmerchant vessel\b", r"\bred sea\b",
        r"\bchokepoint\b", r"\bsuez\b", r"\bstrait\b"
    ],
    "finance_payments": [
        r"\bdollar\b", r"\bswift\b", r"\bpayment\b", r"\bbank\b", r"\bsanction\b",
        r"\bsettlement\b", r"\breserve currency\b", r"\btreasury\b", r"\bcapital flow\b",
        r"\bexchange rate\b", r"\beur/usd\b", r"\bfinancial\b"
    ],
    "semiconductors": [
        r"\bsemiconductor", r"\bchip\b", r"\bwafer\b", r"\bfoundry\b", r"\blithography\b",
        r"\badvanced node\b", r"\bexport control\b", r"\bdual-use\b"
    ],
    "industrial_supply_chain": [
        r"\bsupply chain\b", r"\bmanufactur", r"\bassembly\b", r"\brare earth\b",
        r"\bcritical mineral\b", r"\binputs\b", r"\bintermediate goods\b", r"\bindustrial\b"
    ],
    "digital_infrastructure": [
        r"\btelecom\b", r"\b5g\b", r"\bcloud\b", r"\bdata center\b", r"\bcable\b",
        r"\bplatform\b", r"\bai infrastructure\b", r"\bcyber\b"
    ],
    "security_deterrence": [
        r"\bnato\b", r"\bdeterrence\b", r"\bmissile\b", r"\bnaval\b", r"\bmilitary\b",
        r"\bdefense\b", r"\bsecurity guarantee\b", r"\balliance\b"
    ],
}


CHOKEPOINT_PATTERNS = {
    "hormuz": [r"\bhormuz\b", r"\bstrait of hormuz\b"],
    "suez_red_sea": [r"\bsuez\b", r"\bred sea\b", r"\bbab el-mandeb\b"],
    "taiwan_semiconductor": [r"\btaiwan\b", r"\btsmc\b", r"\bfoundry\b", r"\blithography\b"],
    "dollar_settlement": [r"\bdollar\b", r"\bswift\b", r"\bsettlement\b", r"\breserve currency\b"],
    "export_control_regime": [r"\bexport control\b", r"\bdual-use\b", r"\bsanction\b", r"\bentity list\b"],
    "ports_shipping": [r"\bport\b", r"\bshipping\b", r"\bcontainer\b", r"\bmaritime\b"]
}


def _matches_any(text, patterns):
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    return False


def _event_interfaces(text):
    hits = []
    for interface, patterns in INTERFACE_PATTERNS.items():
        if _matches_any(text, patterns):
            hits.append(interface)
    return hits


def _event_chokepoints(text):
    hits = []
    for chokepoint, patterns in CHOKEPOINT_PATTERNS.items():
        if _matches_any(text, patterns):
            hits.append(chokepoint)
    return hits


def _normalize_domain(value):
    value = str(value or "").strip().lower()
    if not value:
        return "unknown"
    value = re.sub(r"[^a-z0-9_\-/ ]+", "", value)
    value = value.replace(" ", "_")
    return value


def _normalize_source(value):
    value = str(value or "").strip()
    return value if value else "unknown"


def _indicator_interface(ind):
    name = str(ind.get("indicator", "") or "").lower()
    source = str(ind.get("source", "") or "").lower()
    blob = name + " " + source

    if any(k in blob for k in ["fedfunds", "dgs10", "t10yie", "cpi", "hicp", "eur/usd", "exchange", "inflation", "unrate", "gdp"]):
        return "finance_payments"
    if any(k in blob for k in ["fdi", "foreign direct investment"]):
        return "industrial_supply_chain"
    return None


def run(context: dict) -> dict:
    events = context.get("events", []) or []
    indicators = context.get("indicators", []) or []
    problem = str(context.get("problem", "") or "")

    interface_counts = Counter()
    chokepoint_counts = Counter()
    interface_domains = defaultdict(Counter)
    interface_sources = defaultdict(Counter)
    bridge_pairs = Counter()
    event_examples = defaultdict(list)
    risk_flags = []

    total_scored_events = 0.0

    for event in events:
        text = _text(event)
        if not text.strip():
            continue

        salience = event.get("salience_score", 1.0)
        try:
            salience = float(salience)
        except Exception:
            salience = 1.0
        if salience <= 0:
            salience = 1.0

        interfaces = _event_interfaces(text)
        chokepoints = _event_chokepoints(text)
        domain = _normalize_domain(event.get("domain", "unknown"))
        source = _normalize_source(event.get("source_name", "unknown"))

        if interfaces:
            total_scored_events += salience

        for interface in interfaces:
            interface_counts[interface] += salience
            interface_domains[interface][domain] += salience
            interface_sources[interface][source] += salience
            if len(event_examples[interface]) < 3:
                event_examples[interface].append(str(event.get("headline", "") or "").strip())

        for chokepoint in chokepoints:
            chokepoint_counts[chokepoint] += salience

        if len(interfaces) >= 2:
            ordered = sorted(set(interfaces))
            for i in range(len(ordered)):
                for j in range(i + 1, len(ordered)):
                    bridge_pairs[(ordered[i], ordered[j])] += salience

    indicator_hits = Counter()
    for ind in indicators:
        iface = _indicator_interface(ind)
        if iface:
            indicator_hits[iface] += 1

    bridge_scores = []
    for interface, count in interface_counts.items():
        domain_spread = len(interface_domains[interface])
        source_spread = len(interface_sources[interface])
        indicator_support = indicator_hits.get(interface, 0)
        concentration = 0.0
        if count > 0:
            shares = []
            for _, v in interface_domains[interface].items():
                shares.append(v / count)
            concentration = sum(s * s for s in shares)
        bridge_score = count * (1.0 + 0.15 * max(0, domain_spread - 1) + 0.1 * max(0, source_spread - 1) + 0.12 * indicator_support)
        bridge_scores.append((interface, bridge_score, domain_spread, source_spread, concentration))

    bridge_scores.sort(key=lambda x: x[1], reverse=True)
    top_interfaces = bridge_scores[:4]
    top_pairs = sorted(bridge_pairs.items(), key=lambda x: x[1], reverse=True)[:5]
    top_chokepoints = chokepoint_counts.most_common(4)

    for interface, score, domain_spread, source_spread, concentration in top_interfaces:
        if concentration >= 0.7 and domain_spread <= 2:
            risk_flags.append(interface + " is highly concentrated in a narrow domain cluster")
        elif domain_spread >= 3 and source_spread >= 3:
            risk_flags.append(interface + " is a broad residual bridge across sectors and sources")

    problem_lower = problem.lower()
    if any(term in problem_lower for term in ["china", "ηπα", "ευρώπ", "autonomy", "decoupl", "αποσύνδε"]):
        if "semiconductors" not in [x[0] for x in top_interfaces]:
            risk_flags.append("semiconductors may be strategically important even if current event density is lower than energy or shipping")
        if "finance_payments" not in [x[0] for x in top_interfaces]:
            risk_flags.append("financial settlement remains a latent bridge even when headlines are dominated by military or energy shocks")

    summary_parts = []
    summary_parts.append("Dependency bridge scan identifies which shared interfaces still bind partially decoupling systems and therefore can transmit shocks across blocs.")

    if top_interfaces:
        iface_lines = []
        for interface, score, domain_spread, source_spread, concentration in top_interfaces:
            iface_lines.append(
                f"{interface}: score={round(score, 2)}, domains={domain_spread}, sources={source_spread}, concentration={round(concentration, 2)}"
            )
        summary_parts.append("Top residual interfaces -> " + "; ".join(iface_lines) + ".")

    if top_pairs:
        pair_lines = []
        for (a, b), score in top_pairs[:3]:
            pair_lines.append(f"{a}<->{b} ({round(score, 2)})")
        summary_parts.append("Strongest interface couplings -> " + "; ".join(pair_lines) + ".")

    if top_chokepoints:
        chokepoint_lines = []
        for chokepoint, score in top_chokepoints:
            chokepoint_lines.append(f"{chokepoint} ({round(score, 2)})")
        summary_parts.append("Observed chokepoint concentration -> " + "; ".join(chokepoint_lines) + ".")

    if risk_flags:
        summary_parts.append("Risk interpretation -> " + "; ".join(risk_flags[:4]) + ".")

    if event_examples:
        example_lines = []
        for interface, _, _, _, _ in top_interfaces[:3]:
            examples = [e for e in event_examples.get(interface, []) if e]
            if examples:
                example_lines.append(interface + ": " + " | ".join(examples[:2]))
        if example_lines:
            summary_parts.append("Representative event anchors -> " + "; ".join(example_lines) + ".")

    output = " ".join(summary_parts)

    metadata = {
        "top_interfaces": [
            {
                "interface": interface,
                "score": round(score, 3),
                "domain_spread": domain_spread,
                "source_spread": source_spread,
                "concentration": round(concentration, 3),
                "indicator_support": indicator_hits.get(interface, 0),
            }
            for interface, score, domain_spread, source_spread, concentration in top_interfaces
        ],
        "top_bridge_pairs": [
            {"pair": [a, b], "score": round(score, 3)}
            for (a, b), score in top_pairs
        ],
        "top_chokepoints": [
            {"chokepoint": name, "score": round(score, 3)}
            for name, score in top_chokepoints
        ],
        "risk_flags": risk_flags[:6],
        "interfaces_detected": dict((k, round(v, 3)) for k, v in interface_counts.items()),
        "indicator_hits": dict(indicator_hits),
    }

    return {
        "tool_name": TOOL_META["name"],
        "output": output,
        "metadata": metadata,
    }
