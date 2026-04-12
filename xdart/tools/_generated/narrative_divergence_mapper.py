from collections import Counter, defaultdict
import re
import math

TOOL_META = {
    "name": "narrative_divergence_mapper",
    "version": "1.0",
    "purpose": "Detects cross-source convergence, divergence, and framing asymmetry across world events to improve epistemic calibration.",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those",
    "of", "in", "on", "at", "to", "for", "from", "with", "without", "by", "as", "is", "are", "was", "were",
    "be", "been", "being", "it", "its", "into", "about", "over", "after", "before", "amid", "during",
    "under", "between", "through", "across", "up", "down", "out", "off", "all", "new", "how", "why",
    "what", "when", "where", "who", "whom", "their", "they", "them", "he", "she", "his", "her", "we",
    "our", "you", "your", "i", "me", "my"
}

FRAME_LEXICON = {
    "conflict_security": [
        "war", "attack", "strike", "missile", "troops", "military", "defense", "drone", "ceasefire",
        "escalation", "security", "battle", "conflict", "nuclear", "border", "armed", "hostage"
    ],
    "diplomatic_negotiation": [
        "talks", "meeting", "summit", "negotiation", "diplomacy", "diplomatic", "envoy", "agreement",
        "deal", "truce", "mediator", "dialogue", "relations", "minister", "delegation"
    ],
    "economic_market": [
        "trade", "tariff", "inflation", "market", "economy", "economic", "exports", "imports", "oil",
        "gas", "jobs", "growth", "rate", "yield", "currency", "investment", "recession", "supply"
    ],
    "humanitarian_social": [
        "refugee", "aid", "civilian", "children", "hunger", "hospital", "displaced", "rights", "protest",
        "humanitarian", "casualties", "families", "victims", "schools", "health", "famine"
    ],
    "institutional_legal": [
        "court", "law", "legal", "parliament", "election", "constitution", "sanctions", "policy",
        "regulation", "government", "minister", "president", "authority", "institution", "legitimacy"
    ]
}

INTENSIFIERS = {
    "urgent", "severe", "major", "massive", "critical", "dramatic", "sharp", "historic", "unprecedented",
    "immediate", "grave", "extreme", "serious", "emergency", "collapse", "crisis"
}

HEDGE_WORDS = {
    "may", "might", "could", "appears", "suggests", "reportedly", "alleged", "allegedly", "possible",
    "possibly", "unclear", "seems"
}


def normalize_text(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text):
    text = normalize_text(text)
    tokens = [t for t in text.split() if len(t) > 2 and t not in STOPWORDS and not t.isdigit()]
    return tokens


def event_text(event):
    parts = [
        event.get("headline", "") or "",
        event.get("summary", "") or "",
        event.get("domain", "") or "",
        event.get("content_type", "") or "",
    ]
    return " ".join(parts).strip()


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def extract_frames(tokens):
    found = []
    token_set = set(tokens)
    for frame, words in FRAME_LEXICON.items():
        score = sum(1 for w in words if w in token_set)
        if score > 0:
            found.append((frame, score))
    found.sort(key=lambda x: (-x[1], x[0]))
    return [f for f, _ in found[:2]]


def tone_score(tokens):
    token_set = set(tokens)
    intense = sum(1 for w in INTENSIFIERS if w in token_set)
    hedged = sum(1 for w in HEDGE_WORDS if w in token_set)
    return intense - hedged


def cluster_events(events, threshold=0.22):
    prepared = []
    for idx, event in enumerate(events):
        text = event_text(event)
        tokens = tokenize(text)
        prepared.append({
            "idx": idx,
            "event": event,
            "tokens": set(tokens),
            "source": event.get("source_name", "Unknown") or "Unknown",
            "domain": event.get("domain", "unknown") or "unknown",
            "headline": event.get("headline", "") or "",
            "salience": float(event.get("salience_score", 0.0) or 0.0),
            "frames": extract_frames(tokens),
            "tone": tone_score(tokens),
        })

    clusters = []
    used = set()

    for item in prepared:
        if item["idx"] in used:
            continue
        cluster = [item]
        used.add(item["idx"])
        changed = True
        while changed:
            changed = False
            for other in prepared:
                if other["idx"] in used:
                    continue
                sims = [jaccard(other["tokens"], member["tokens"]) for member in cluster]
                if sims and max(sims) >= threshold:
                    cluster.append(other)
                    used.add(other["idx"])
                    changed = True
        clusters.append(cluster)
    return clusters


def summarize_cluster(cluster):
    sources = [c["source"] for c in cluster]
    source_counts = Counter(sources)
    domains = Counter(c["domain"] for c in cluster)
    all_frames = Counter(f for c in cluster for f in c["frames"])
    tones = [c["tone"] for c in cluster]
    saliences = [c["salience"] for c in cluster]
    token_counts = Counter()
    for c in cluster:
        token_counts.update(c["tokens"])

    common_tokens = [w for w, n in token_counts.most_common(8) if len(w) > 3][:5]
    representative = sorted(cluster, key=lambda x: (-x["salience"], x["headline"]))[0]

    if len(set(sources)) <= 1:
        divergence = "single-source"
    else:
        frame_variety = len(all_frames)
        tone_spread = (max(tones) - min(tones)) if tones else 0
        if frame_variety >= 4 or tone_spread >= 3:
            divergence = "high"
        elif frame_variety >= 2 or tone_spread >= 1:
            divergence = "medium"
        else:
            divergence = "low"

    return {
        "headline": representative["headline"],
        "sources": dict(source_counts),
        "source_count": len(set(sources)),
        "event_count": len(cluster),
        "top_domain": domains.most_common(1)[0][0] if domains else "unknown",
        "frames": [f for f, _ in all_frames.most_common(3)],
        "tone_range": [min(tones) if tones else 0, max(tones) if tones else 0],
        "avg_salience": round(sum(saliences) / len(saliences), 3) if saliences else 0.0,
        "common_tokens": common_tokens,
        "divergence": divergence,
    }


def build_output(cluster_summaries, source_totals):
    multi_source = [c for c in cluster_summaries if c["source_count"] >= 2]
    high_div = [c for c in multi_source if c["divergence"] == "high"]
    med_div = [c for c in multi_source if c["divergence"] == "medium"]
    low_div = [c for c in multi_source if c["divergence"] == "low"]
    single_source = [c for c in cluster_summaries if c["divergence"] == "single-source"]

    lines = []
    lines.append("=== NARRATIVE DIVERGENCE MAP ===")
    lines.append(
        "Cross-source clustering of world events to identify consensus, framing splits, and epistemic asymmetry."
    )
    lines.append(
        f"Detected {len(cluster_summaries)} topic clusters: {len(multi_source)} multi-source, {len(single_source)} single-source."
    )
    lines.append(
        f"Divergence profile among multi-source clusters: high={len(high_div)}, medium={len(med_div)}, low={len(low_div)}."
    )

    if source_totals:
        top_sources = ", ".join(f"{src}:{cnt}" for src, cnt in source_totals.most_common(5))
        lines.append(f"Source volume: {top_sources}.")

    focus = sorted(
        multi_source,
        key=lambda c: (
            {"high": 3, "medium": 2, "low": 1}.get(c["divergence"], 0),
            c["source_count"],
            c["avg_salience"],
            c["event_count"],
        ),
        reverse=True,
    )[:5]

    if focus:
        lines.append("Key multi-source clusters:")
        for i, c in enumerate(focus, 1):
            srcs = ", ".join(sorted(c["sources"].keys())[:6])
            frames = ", ".join(c["frames"]) if c["frames"] else "unclear"
            tokens = ", ".join(c["common_tokens"][:4]) if c["common_tokens"] else "n/a"
            lines.append(
                f"  {i}. [{c['divergence']}] '{c['headline'][:140]}' | sources={c['source_count']} ({srcs}) | frames={frames} | cues={tokens} | tone_range={c['tone_range']}"
            )
    else:
        lines.append("No meaningful multi-source overlap detected; world context is currently fragmented across distinct topics.")

    if high_div:
        lines.append("Epistemic warning: high-divergence clusters likely contain framing asymmetry rather than stable consensus; downstream reasoning should treat them as contested narratives.")
    elif med_div:
        lines.append("Epistemic note: several medium-divergence clusters show partial agreement on facts but differing interpretive emphasis across sources.")
    else:
        lines.append("Epistemic note: overlapping coverage is mostly convergent; source disagreement appears limited in current context.")

    if single_source:
        lines.append("Coverage gap note: a substantial share of topics are single-source and should be treated as weakly corroborated until echoed elsewhere.")

    return "\n".join(lines)


def run(context: dict) -> dict:
    events = context.get("events", []) or []
    indicators = context.get("indicators", []) or []
    problem = context.get("problem", "") or ""

    source_totals = Counter((e.get("source_name", "Unknown") or "Unknown") for e in events)

    if not events:
        output = "=== NARRATIVE DIVERGENCE MAP ===\nNo events available, so no cross-source convergence/divergence analysis could be performed."
        return {
            "tool_name": TOOL_META["name"],
            "output": output,
            "metadata": {
                "clusters": 0,
                "multi_source_clusters": 0,
                "single_source_clusters": 0,
                "problem_length": len(problem),
                "indicator_count": len(indicators),
            },
        }

    clusters = cluster_events(events)
    summaries = [summarize_cluster(c) for c in clusters]
    output = build_output(summaries, source_totals)

    metadata = {
        "clusters": len(summaries),
        "multi_source_clusters": sum(1 for s in summaries if s["source_count"] >= 2),
        "single_source_clusters": sum(1 for s in summaries if s["source_count"] < 2),
        "high_divergence_clusters": sum(1 for s in summaries if s["divergence"] == "high"),
        "medium_divergence_clusters": sum(1 for s in summaries if s["divergence"] == "medium"),
        "low_divergence_clusters": sum(1 for s in summaries if s["divergence"] == "low"),
        "top_sources": dict(source_totals.most_common(7)),
        "indicator_count": len(indicators),
        "problem_length": len(problem),
    }

    return {
        "tool_name": TOOL_META["name"],
        "output": output,
        "metadata": metadata,
    }
