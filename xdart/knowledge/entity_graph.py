"""
XDART-Φ × XHEART — Entity Knowledge Graph

Palantir-grade entity relationship intelligence for Αίολος.
Tracks entities (people, countries, organizations) extracted from
real-time news headlines, builds co-occurrence relationships, and
provides cascade impact analysis.

Architecture:
  - spaCy NER (en_core_web_sm) for automatic entity extraction
  - Alias resolution for known geopolitical entities spaCy may miss
  - NetworkX directed graph for relationship tracking
  - Co-occurrence edge weights decay over time (7-day half-life)
  - JSON persistence — graph state survives restarts

Integration points:
  - Perception Collector: every headline → ingest() → graph update
  - Proactive Impact Scoring: get_cascade_impact() for pattern severity
  - Chat Mode: Αίολος queries graph via get_entity_brief() / query()
  - Pipeline: context enrichment via get_world_graph_summary()

THIS IS PART OF ΑΙΟΛΟΣ — not a separate module.
"""

import json
import logging
import math
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx

logger = logging.getLogger("xdart.knowledge.entity_graph")

# ── Lazy spaCy loading (avoid startup penalty if not needed) ──
_nlp = None


def _get_nlp():
    """Lazy-load spaCy model. Returns None if unavailable."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer"])
            logger.info("[EntityGraph] spaCy en_core_web_sm loaded")
        except Exception as e:
            logger.warning("[EntityGraph] spaCy unavailable: %s — using alias-only mode", e)
            _nlp = False  # sentinel: tried and failed
    return _nlp if _nlp is not False else None


# ══════════════════════════════════════════════════════════════════════════════
#  ALIAS REGISTRY — known entities that spaCy's small model may miss.
#  These are tier-1 geopolitical entities. The graph LEARNS new entities
#  from headlines via NER — this is just the seed.
# ══════════════════════════════════════════════════════════════════════════════

# format: canonical_name → (type, {aliases})
_KNOWN_ENTITIES: dict[str, tuple[str, set[str]]] = {
    # ── Global Figures ──
    "Donald Trump":     ("PERSON", {"trump", "donald trump", "president trump",
                                    "trump administration", "former president trump"}),
    "Joe Biden":        ("PERSON", {"biden", "joe biden", "president biden",
                                    "biden administration"}),
    "Xi Jinping":       ("PERSON", {"xi jinping", "xi", "president xi", "chairman xi",
                                    "习近平"}),
    "Vladimir Putin":   ("PERSON", {"putin", "vladimir putin", "путин",
                                    "владимир путин", "president putin",
                                    "v. putin", "russian president", "kremlin leader"}),
    "Narendra Modi":    ("PERSON", {"modi", "narendra modi", "pm modi",
                                    "prime minister modi", "indian pm"}),
    "Kim Jong Un":      ("PERSON", {"kim jong un", "kim jong-un", "kim",
                                    "north korean leader", "dprk leader"}),
    "Ali Khamenei":     ("PERSON", {"khamenei", "ayatollah khamenei",
                                    "خامنئی", "supreme leader", "iranian supreme leader"}),
    "Benjamin Netanyahu": ("PERSON", {"netanyahu", "benjamin netanyahu", "bibi",
                                      "pm netanyahu", "israeli pm",
                                      "israeli prime minister"}),
    "Recep Erdogan":    ("PERSON", {"erdogan", "erdoğan", "recep erdogan",
                                    "recep tayyip erdogan", "turkish president",
                                    "president erdogan"}),
    "Emmanuel Macron":  ("PERSON", {"macron", "emmanuel macron", "president macron",
                                    "french president"}),
    "Olaf Scholz":      ("PERSON", {"scholz", "olaf scholz", "chancellor scholz",
                                    "german chancellor"}),
    "Keir Starmer":     ("PERSON", {"starmer", "keir starmer", "pm starmer",
                                    "british pm", "british prime minister"}),
    "Mohammed bin Salman": ("PERSON", {"mbs", "mohammed bin salman", "bin salman",
                                       "crown prince mohammed", "saudi crown prince",
                                       "محمد بن سلمان"}),
    "Volodymyr Zelensky": ("PERSON", {"zelensky", "zelenskyy", "zelenskiy", "zelenski",
                                      "volodymyr zelensky", "зеленський", "зеленский",
                                      "ukrainian president", "president zelensky",
                                      "president zelenskyy"}),
    "Jerome Powell":    ("PERSON", {"powell", "jerome powell", "fed chair powell",
                                    "fed chairman", "chair powell"}),
    "Christine Lagarde": ("PERSON", {"lagarde", "christine lagarde", "ecb president",
                                     "ecb president lagarde"}),
    "Pope Francis":     ("PERSON", {"pope", "pope francis", "pontiff", "holy father"}),

    # ── Key Diplomats & Military Figures ──
    "Sergei Lavrov":    ("PERSON", {"lavrov", "sergei lavrov", "лавров",
                                    "russian foreign minister", "fm lavrov"}),
    "Sergei Shoigu":    ("PERSON", {"shoigu", "sergei shoigu", "шойгу"}),
    "Dmitry Medvedev":  ("PERSON", {"medvedev", "dmitry medvedev", "медведев"}),
    "Antony Blinken":   ("PERSON", {"blinken", "antony blinken", "secretary blinken",
                                    "us secretary of state"}),
    "Lloyd Austin":     ("PERSON", {"austin", "lloyd austin", "defense secretary austin",
                                    "secdef austin"}),
    "Abdel Fattah el-Sisi": ("PERSON", {"sisi", "el-sisi", "al-sisi",
                                         "president sisi", "egyptian president"}),
    "Masoud Pezeshkian": ("PERSON", {"pezeshkian", "masoud pezeshkian",
                                     "iranian president", "president pezeshkian"}),
    "Alexander Lukashenko": ("PERSON", {"lukashenko", "лукашенко",
                                         "belarusian president"}),

    # ── Tech Leaders (AI/job crisis patterns) ──
    "Elon Musk":        ("PERSON", {"musk", "elon musk"}),
    "Dario Amodei":     ("PERSON", {"amodei", "dario amodei", "anthropic ceo"}),
    "Sam Altman":       ("PERSON", {"altman", "sam altman", "openai ceo"}),
    "Jensen Huang":     ("PERSON", {"jensen huang", "huang", "nvidia ceo"}),
    "Mark Zuckerberg":  ("PERSON", {"zuckerberg", "mark zuckerberg", "zuck",
                                    "meta ceo"}),
    "Sundar Pichai":    ("PERSON", {"pichai", "sundar pichai", "google ceo",
                                    "alphabet ceo"}),
    "Satya Nadella":    ("PERSON", {"nadella", "satya nadella", "microsoft ceo"}),
    "Tim Cook":         ("PERSON", {"tim cook", "apple ceo"}),

    # ── Major Powers ──
    "United States":    ("GPE", {"usa", "us", "united states", "america", "american",
                                 "washington", "u.s.", "u.s.a."}),
    "China":            ("GPE", {"china", "chinese", "beijing", "prc",
                                 "people's republic of china"}),
    "Russia":           ("GPE", {"russia", "russian", "moscow", "kremlin",
                                 "russian federation", "россия"}),
    "India":            ("GPE", {"india", "indian", "new delhi", "delhi"}),
    "Japan":            ("GPE", {"japan", "japanese", "tokyo"}),
    "Germany":          ("GPE", {"germany", "german", "berlin"}),
    "France":           ("GPE", {"france", "french", "paris", "élysée"}),
    "United Kingdom":   ("GPE", {"uk", "britain", "british", "london", "england",
                                 "great britain"}),
    "Iran":             ("GPE", {"iran", "iranian", "tehran", "ایران",
                                 "islamic republic"}),
    "Israel":           ("GPE", {"israel", "israeli", "jerusalem", "tel aviv"}),
    "Saudi Arabia":     ("GPE", {"saudi arabia", "saudi", "riyadh",
                                 "kingdom of saudi arabia"}),
    "Turkey":           ("GPE", {"turkey", "turkish", "türkiye", "ankara"}),
    "Brazil":           ("GPE", {"brazil", "brazilian", "brasilia", "brasília"}),
    "South Korea":      ("GPE", {"south korea", "korean", "seoul", "rok"}),
    "North Korea":      ("GPE", {"north korea", "pyongyang", "dprk"}),
    "Pakistan":         ("GPE", {"pakistan", "pakistani", "islamabad"}),
    "Taiwan":           ("GPE", {"taiwan", "taiwanese", "taipei"}),
    "Ukraine":          ("GPE", {"ukraine", "ukrainian", "kyiv", "kiev",
                                 "україна"}),
    "Egypt":            ("GPE", {"egypt", "egyptian", "cairo"}),
    "Greece":           ("GPE", {"greece", "greek", "athens", "ελλαδα", "ελλάδα"}),

    # ── Additional Strategic Countries ──
    "United Arab Emirates": ("GPE", {"uae", "united arab emirates", "emirati",
                                     "abu dhabi", "dubai"}),
    "Qatar":            ("GPE", {"qatar", "qatari", "doha"}),
    "Iraq":             ("GPE", {"iraq", "iraqi", "baghdad"}),
    "Syria":            ("GPE", {"syria", "syrian", "damascus"}),
    "Libya":            ("GPE", {"libya", "libyan", "tripoli"}),
    "Yemen":            ("GPE", {"yemen", "yemeni", "sanaa", "sana'a"}),
    "Afghanistan":      ("GPE", {"afghanistan", "afghan", "kabul"}),
    "Lebanon":          ("GPE", {"lebanon", "lebanese", "beirut"}),
    "Belarus":          ("GPE", {"belarus", "belarusian", "minsk"}),
    "Poland":           ("GPE", {"poland", "polish", "warsaw"}),
    "Indonesia":        ("GPE", {"indonesia", "indonesian", "jakarta"}),
    "Mexico":           ("GPE", {"mexico", "mexican", "mexico city"}),
    "Philippines":      ("GPE", {"philippines", "filipino", "manila"}),
    "Singapore":        ("GPE", {"singapore", "singaporean"}),
    "South Africa":     ("GPE", {"south africa", "pretoria", "johannesburg"}),
    "Nigeria":          ("GPE", {"nigeria", "nigerian", "abuja", "lagos"}),
    "Venezuela":        ("GPE", {"venezuela", "venezuelan", "caracas"}),
    "Argentina":        ("GPE", {"argentina", "argentine", "buenos aires"}),
    "Australia":        ("GPE", {"australia", "australian", "canberra"}),
    "Canada":           ("GPE", {"canada", "canadian", "ottawa"}),

    # ── Key Organizations ──
    "NATO":             ("ORG", {"nato", "north atlantic treaty"}),
    "European Union":   ("ORG", {"eu", "european union", "brussels"}),
    "United Nations":   ("ORG", {"un", "united nations"}),
    "IMF":              ("ORG", {"imf", "international monetary fund"}),
    "World Bank":       ("ORG", {"world bank"}),
    "Federal Reserve":  ("ORG", {"fed", "federal reserve", "fomc"}),
    "ECB":              ("ORG", {"ecb", "european central bank"}),
    "WHO":              ("ORG", {"who", "world health organization"}),
    "WTO":              ("ORG", {"wto", "world trade organization"}),
    "OPEC":             ("ORG", {"opec", "opec+"}),
    "BRICS":            ("ORG", {"brics"}),
    "G7":               ("ORG", {"g7", "g-7"}),
    "G20":              ("ORG", {"g20", "g-20"}),
    "TSMC":             ("ORG", {"tsmc", "taiwan semiconductor"}),
    "Hamas":            ("ORG", {"hamas"}),
    "Hezbollah":        ("ORG", {"hezbollah", "hizballah", "hizbullah"}),
    "Wagner Group":     ("ORG", {"wagner", "wagner group"}),

    # ── Additional Key Organizations ──
    "OpenAI":           ("ORG", {"openai", "open ai"}),
    "Anthropic":        ("ORG", {"anthropic"}),
    "Google":           ("ORG", {"google", "alphabet", "google deepmind", "deepmind"}),
    "Meta":             ("ORG", {"meta", "meta platforms", "facebook"}),
    "Microsoft":        ("ORG", {"microsoft"}),
    "Amazon":           ("ORG", {"amazon", "aws", "amazon web services"}),
    "Nvidia":           ("ORG", {"nvidia"}),
    "Apple":            ("ORG", {"apple"}),
    "Houthis":          ("ORG", {"houthis", "houthi", "ansar allah"}),
    "ISIS":             ("ORG", {"isis", "isil", "islamic state", "daesh"}),
    "Taliban":          ("ORG", {"taliban"}),
    "PKK":              ("ORG", {"pkk", "kurdistan workers party"}),
    "IAEA":             ("ORG", {"iaea", "international atomic energy agency"}),
    "ICC":              ("ORG", {"icc", "international criminal court"}),
    "SWIFT":            ("ORG", {"swift"}),
    "ASEAN":            ("ORG", {"asean"}),
    "SCO":              ("ORG", {"sco", "shanghai cooperation"}),
    "African Union":    ("ORG", {"african union", "au"}),

    # ── Strategic Locations ──
    "Strait of Hormuz": ("LOC", {"hormuz", "strait of hormuz", "hormuz strait"}),
    "Suez Canal":       ("LOC", {"suez", "suez canal"}),
    "South China Sea":  ("LOC", {"south china sea", "scs", "west philippine sea"}),
    "Taiwan Strait":    ("LOC", {"taiwan strait", "formosa strait"}),
    "Black Sea":        ("LOC", {"black sea"}),
    "Red Sea":          ("LOC", {"red sea"}),
    "Baltic Sea":       ("LOC", {"baltic sea", "baltic"}),
    "Arctic":           ("LOC", {"arctic", "arctic ocean", "north pole"}),
    "Gaza":             ("LOC", {"gaza", "gaza strip"}),
    "West Bank":        ("LOC", {"west bank"}),
    "Crimea":           ("LOC", {"crimea", "крым"}),
    "Donbas":           ("LOC", {"donbas", "donbass", "donetsk", "luhansk",
                                 "lugansk"}),
    "Kashmir":          ("LOC", {"kashmir"}),
}

# Build reverse lookup: alias → canonical_name
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for cname, (_, aliases) in _KNOWN_ENTITIES.items():
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias] = cname


# ══════════════════════════════════════════════════════════════════════════════
#  NER QUALITY FILTER — spaCy en_core_web_sm is noisy on headlines.
#  These filters prevent false positives from polluting the entity graph
#  and downstream pattern matching.
# ══════════════════════════════════════════════════════════════════════════════

# Common English words that spaCy en_core_web_sm frequently misclassifies
# as named entities (PERSON/ORG/GPE). This is NOT a full stopword list —
# only words observed as actual false positives in production logs.
_NER_NOISE_WORDS = frozenset({
    # Verbs / common nouns misclassified as entities
    "break", "distance", "returns", "impact", "risk", "threat",
    "gain", "loss", "shift", "push", "strike", "fall", "rise",
    "lead", "power", "reform", "fire", "crash", "deal", "talks",
    "war", "peace", "death", "battle", "control", "crisis",
    "border", "summit", "chief", "state", "attack", "aid",
    "gap", "edge", "base", "watch", "alert", "charge", "order",
    # Food / retail / commercial terms from economic headlines
    "baristas", "buffets", "burgers", "stores", "brands", "foods",
    # Temporal words
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "today", "yesterday", "tomorrow",
    "daily", "weekly", "monthly", "annual",
    # Ordinals / adjectives
    "first", "second", "third", "last", "next", "new", "old",
    "general", "major", "special", "joint", "final",
    # Standalone directional (OK as part of country names handled by alias)
    "north", "south", "east", "west",
    # Media words spaCy tags as ORG
    "daily", "times", "post", "morning", "evening", "express",
    "report", "analysis", "review", "bulletin", "update",
})

# Multi-word phrases that are known false positive entity extractions
_NER_NOISE_PHRASES = frozenset({
    "diminishing returns", "breaking news", "live updates",
    "latest news", "just in", "developing story",
    "holy fire", "holy land", "ceasefire agreement",
    # Headline verb phrases mistaken as entities (e.g., "Hormuz Opens", "Market Drops")
    "hormuz opens", "strait opens", "strait closes", "border opens", "border closes",
    "market drops", "market rises", "stocks fall", "stocks rise",
    "oil falls", "oil rises", "oil soars", "oil plunges",
})


def _is_valid_ner_entity(name: str, label: str) -> bool:
    """Filter out spaCy NER noise. Returns True only if entity looks legitimate.

    Designed for en_core_web_sm which has limited accuracy on news headlines.
    Known entities (alias registry) bypass this filter entirely.
    """
    # Too short — almost always noise
    if len(name) < 2:
        return False

    # Must start with uppercase letter (proper noun indicator)
    # Reject strings starting with digit or special char (e.g., "2.79USD/MMBtu", "123K")
    if not name[0].isalpha() or name[0].islower():
        return False

    # Reject mostly-digit strings ("5.000", "2026", "18", etc.)
    alpha_chars = sum(c.isalpha() for c in name)
    if alpha_chars < max(2, len(name) * 0.4):
        return False

    # Reject strings containing numeric+unit patterns (e.g., "2.79USD", "350K", "Hormuz Opens")
    # These are measurement values or headline fragments, not entity names
    if re.search(r'\d+[./]\d*[A-Za-z]', name):  # e.g., "2.79USD/MMBtu"
        return False
    if re.search(r'\d+[A-Z]{2,}', name):  # e.g., "350K", "123USD"
        return False
    # Reject strings with "/" that are not valid entity names (e.g., "Hormuz/Closure")
    if "/" in name and not any(c.isalpha() for c in name.split("/")[0][-1:]):
        return False

    name_lower = name.lower().strip()

    # Check multi-word noise phrases
    if name_lower in _NER_NOISE_PHRASES:
        return False

    # Single-word entity checks
    if " " not in name_lower:
        # Single word in noise list → reject
        if name_lower in _NER_NOISE_WORDS:
            return False
        # Very short single words (2-3 chars) that aren't GPE are usually noise
        # (e.g., "Gap", "Aid", "BBC" is OK as ORG but it's in alias registry)
        if len(name) <= 3 and label not in ("GPE", "ORG"):
            return False
    else:
        # Multi-word: reject if ALL words are common noise words
        # e.g., "Diminishing Returns", "Breaking News"
        words = name_lower.split()
        if len(words) >= 2 and all(w in _NER_NOISE_WORDS for w in words):
            return False
        # Very long entity names (4+ words) from headlines are usually
        # phrases, not entities (e.g., "Asymmetric Counterair Campaign")
        if len(words) >= 4:
            return False

    return True


# ══════════════════════════════════════════════════════════════════════════════
#  ENTITY RESOLUTION ENGINE — P1 Palantir Upgrade
#
#  Fuzzy deduplication across sources. Resolves:
#    "Putin" = "Путин" = "Vladimir Putin" = "Russian President" = "V. Putin"
#
#  Five-tier resolution (fast → slow):
#    Tier 1: Exact alias match (O(1) dict lookup) — existing _ALIAS_TO_CANONICAL
#    Tier 2: Normalized form match (strip diacritics + transliterate + titles)
#    Tier 3: Token subset match ("Musk" → "Elon Musk" if known)
#    Tier 4: Fuzzy match (Jaro-Winkler ≥ 0.88 against known entities)
#    Tier 5: Fuzzy match against top graph nodes (≥ 0.90 threshold)
#    + Co-occurrence alias learning (auto-discover from headline patterns)
# ══════════════════════════════════════════════════════════════════════════════

# ── Cyrillic → Latin transliteration (BGN/PCGN standard) ──
_CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # Ukrainian-specific letters
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
}

# ── Title/honorific prefixes to strip for matching ──
_TITLE_PREFIXES: tuple[str, ...] = (
    "president", "prime minister", "pm", "chancellor", "king", "queen",
    "prince", "princess", "crown prince", "crown princess",
    "secretary", "minister", "general", "admiral", "commander",
    "supreme leader", "ayatollah", "pope", "pontiff",
    "dr", "dr.", "prof", "prof.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.",
    "senator", "congressman", "representative", "governor",
    "ceo", "chairman", "chair", "director", "chief",
    "foreign minister", "fm", "defense secretary", "secdef",
)


def _transliterate_cyrillic(text: str) -> str:
    """Transliterate Cyrillic characters to Latin equivalents."""
    result: list[str] = []
    for char in text:
        lower_char = char.lower()
        if lower_char in _CYRILLIC_TO_LATIN:
            mapped = _CYRILLIC_TO_LATIN[lower_char]
            # Preserve capitalization of first mapped char
            if char.isupper() and mapped:
                mapped = mapped[0].upper() + mapped[1:]
            result.append(mapped)
        else:
            result.append(char)
    return "".join(result)


def _normalize_entity_name(name: str) -> str:
    """Normalize entity name for resolution matching.

    1. Unicode NFKD decomposition → strip combining marks (ğ→g, ë→e, ö→o)
    2. Transliterate Cyrillic → Latin
    3. Strip title/honorific prefixes
    4. Lowercase + collapse whitespace
    """
    # NFKD normalize — decompose then strip combining diacritics
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))

    # Transliterate Cyrillic
    stripped = _transliterate_cyrillic(stripped)

    # Lowercase and collapse whitespace
    text = " ".join(stripped.lower().split())

    # Strip title prefixes
    for title in _TITLE_PREFIXES:
        if text.startswith(title + " "):
            text = text[len(title) + 1:].strip()
            break  # Only strip one title

    # Remove trailing possessives ("putin's" → "putin")
    if text.endswith("'s"):
        text = text[:-2]
    elif text.endswith("'s"):
        text = text[:-2]

    return text.strip()


def _jaro_similarity(s1: str, s2: str) -> float:
    """Jaro string similarity (0.0 to 1.0)."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    return (
        matches / len1 + matches / len2 + (matches - transpositions / 2) / matches
    ) / 3


def _jaro_winkler(s1: str, s2: str, prefix_weight: float = 0.1) -> float:
    """Jaro-Winkler string similarity (0.0 to 1.0). Optimized for names.

    Gives bonus weight to matching prefixes (up to 4 chars),
    which is ideal for name variants like "Zelensky" vs "Zelenskyy".
    """
    jaro = _jaro_similarity(s1, s2)

    # Common prefix bonus (up to 4 chars)
    prefix_len = 0
    for i in range(min(4, len(s1), len(s2))):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    return jaro + prefix_len * prefix_weight * (1 - jaro)


class EntityResolver:
    """Multi-strategy entity resolution engine.

    Deduplicates entities across sources by resolving variant names
    to a single canonical form. Handles:
      - Transliteration: Путин → putin → Vladimir Putin
      - Diacritics: Erdoğan → erdogan → Recep Erdogan
      - Title stripping: "President Putin" → "putin" → Vladimir Putin
      - Fuzzy matching: "Zelenski" → "Zelensky" → Volodymyr Zelensky
      - Token subset: "Musk" → matches "Elon Musk"
      - Abbreviation: "MBS" → Mohammed bin Salman (via alias registry)
      - Co-occurrence learning: auto-discover aliases from headline patterns
    """

    def __init__(self, graph: "EntityGraph"):
        self._graph = graph
        self._learned_aliases: dict[str, str] = {}      # normalized → canonical
        self._resolution_cache: dict[str, str] = {}     # raw_name → canonical
        self._cooccurrence_tracker: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        # Build normalized alias index for Tier 2 matching
        self._normalized_alias_index: dict[str, str] = {}
        self._rebuild_normalized_index()

        # Stats
        self._resolved_count = 0
        self._fuzzy_resolved_count = 0
        self._learned_count = 0
        self._cache_max = 5000

    def _rebuild_normalized_index(self) -> None:
        """Build normalized form → canonical mapping for all known aliases."""
        self._normalized_alias_index.clear()
        for canonical, (_, aliases) in _KNOWN_ENTITIES.items():
            norm_canonical = _normalize_entity_name(canonical)
            self._normalized_alias_index[norm_canonical] = canonical
            for alias in aliases:
                norm_alias = _normalize_entity_name(alias)
                if norm_alias:
                    self._normalized_alias_index[norm_alias] = canonical

    def resolve(self, name: str, entity_type: str = "") -> str:
        """Resolve an entity name to its canonical form.

        Returns canonical name if resolved, or original name if no match found.
        Called for every NER-extracted entity before graph insertion.
        """
        # Tier 0: Cache hit (most common path after warmup)
        if name in self._resolution_cache:
            return self._resolution_cache[name]

        # Tier 1: Exact alias match (existing system, O(1))
        name_lower = name.lower().strip()
        if name_lower in _ALIAS_TO_CANONICAL:
            canonical = _ALIAS_TO_CANONICAL[name_lower]
            self._cache(name, canonical)
            return canonical

        # Tier 2: Normalized form match (handles diacritics, Cyrillic, titles)
        normalized = _normalize_entity_name(name)
        if normalized in self._normalized_alias_index:
            canonical = self._normalized_alias_index[normalized]
            self._cache(name, canonical)
            return canonical

        # Check learned aliases (from co-occurrence)
        if normalized in self._learned_aliases:
            canonical = self._learned_aliases[normalized]
            self._cache(name, canonical)
            return canonical

        # Tier 3: Token subset match ("Musk" → "Elon Musk")
        canonical = self._token_subset_match(normalized, entity_type)
        if canonical:
            self._cache(name, canonical)
            return canonical

        # Tier 4: Fuzzy match against known entities (Jaro-Winkler ≥ 0.88)
        canonical = self._fuzzy_match_known(normalized, entity_type)
        if canonical:
            self._fuzzy_resolved_count += 1
            self._cache(name, canonical)
            logger.debug(
                "[EntityResolver] Fuzzy resolved '%s' → '%s' (known)", name, canonical
            )
            return canonical

        # Tier 5: Fuzzy match against established graph nodes (≥ 0.90)
        canonical = self._fuzzy_match_graph(normalized, entity_type)
        if canonical:
            self._fuzzy_resolved_count += 1
            self._cache(name, canonical)
            logger.debug(
                "[EntityResolver] Fuzzy resolved '%s' → '%s' (graph)", name, canonical
            )
            return canonical

        # No match — return original
        return name

    def _cache(self, name: str, canonical: str) -> None:
        """Cache a resolution result. Evicts oldest entries when full."""
        self._resolved_count += 1
        self._resolution_cache[name] = canonical
        if len(self._resolution_cache) > self._cache_max:
            # Evict oldest 20%
            keys = list(self._resolution_cache.keys())
            for k in keys[: self._cache_max // 5]:
                del self._resolution_cache[k]

    def _token_subset_match(
        self, normalized: str, entity_type: str
    ) -> str | None:
        """Match if name tokens are a subset of a known entity's name.

        e.g., "Musk" ⊂ {"elon", "musk"} = "Elon Musk"
              "Scholz" ⊂ {"olaf", "scholz"} = "Olaf Scholz"

        Guards against false positives from single common tokens.
        """
        tokens = set(normalized.split())
        if not tokens or len(tokens) > 3:
            return None

        best_canonical: str | None = None
        best_token_ratio = 0.0

        for canonical, (etype, _) in _KNOWN_ENTITIES.items():
            if entity_type and etype != entity_type:
                continue

            canonical_tokens = set(canonical.lower().split())

            # Name tokens must be a non-empty subset of canonical tokens
            if not tokens.issubset(canonical_tokens):
                continue

            # Guard: single-token match only if canonical has ≤ 2 tokens
            # (avoid "bin" matching "Mohammed bin Salman")
            if len(tokens) == 1 and len(canonical_tokens) > 2:
                continue

            # Prefer the match with the highest token coverage ratio
            ratio = len(tokens) / len(canonical_tokens)
            if ratio > best_token_ratio:
                best_token_ratio = ratio
                best_canonical = canonical

        return best_canonical

    def _fuzzy_match_known(
        self, normalized: str, entity_type: str
    ) -> str | None:
        """Fuzzy match against known entity names and aliases.

        Uses Jaro-Winkler similarity with threshold 0.88.
        Scans all canonical names + their aliases.
        """
        if len(normalized) < 3:
            return None  # Too short for reliable fuzzy matching

        best_score = 0.0
        best_match: str | None = None

        for canonical, (etype, aliases) in _KNOWN_ENTITIES.items():
            if entity_type and etype != entity_type:
                continue

            # Compare against normalized canonical name
            canon_norm = _normalize_entity_name(canonical)
            score = _jaro_winkler(normalized, canon_norm)
            if score > best_score:
                best_score = score
                best_match = canonical

            # Compare against all aliases (also normalized)
            for alias in aliases:
                alias_norm = _normalize_entity_name(alias)
                if not alias_norm:
                    continue
                score = _jaro_winkler(normalized, alias_norm)
                if score > best_score:
                    best_score = score
                    best_match = canonical

        if best_score >= 0.88:
            return best_match
        return None

    def _fuzzy_match_graph(
        self, normalized: str, entity_type: str
    ) -> str | None:
        """Fuzzy match against established graph nodes (≥3 mentions).

        Higher threshold (0.90) than known entities since graph nodes
        are less curated. Only checks top-200 nodes for performance.
        """
        graph = self._graph._graph
        if not graph.nodes:
            return None

        # Collect candidates: established nodes not in known registry
        candidates: list[tuple[str, int]] = []
        for node, data in graph.nodes(data=True):
            if node in _KNOWN_ENTITIES:
                continue  # Already checked in Tier 4
            if entity_type and data.get("type", "") != entity_type:
                continue
            mentions = data.get("mention_count", 0)
            if mentions >= 3:
                candidates.append((node, mentions))

        # Sort by mentions descending, cap at 200
        candidates.sort(key=lambda x: x[1], reverse=True)

        best_score = 0.0
        best_match: str | None = None

        for node, _ in candidates[:200]:
            node_norm = _normalize_entity_name(node)
            score = _jaro_winkler(normalized, node_norm)
            if score > best_score:
                best_score = score
                best_match = node

        if best_score >= 0.90:
            return best_match
        return None

    def learn_cooccurrence(
        self, entities: list[tuple[str, str]]
    ) -> None:
        """Track entity co-occurrences for automatic alias learning.

        If an unknown entity frequently co-occurs with a known entity
        of the same type in the same headlines, it's likely an alias.
        e.g., "Russian President" co-occurs with "Vladimir Putin" → alias

        Threshold: 3 co-occurrences triggers alias creation.
        """
        for i, (name_a, type_a) in enumerate(entities):
            for name_b, type_b in entities[i + 1:]:
                if type_a != type_b:
                    continue

                a_known = name_a in _KNOWN_ENTITIES
                b_known = name_b in _KNOWN_ENTITIES

                # Only learn when one is known and one is unknown
                if a_known == b_known:
                    continue

                known = name_a if a_known else name_b
                unknown = name_b if a_known else name_a

                self._cooccurrence_tracker[unknown][known] += 1

                count = self._cooccurrence_tracker[unknown][known]
                if count == 3:
                    norm = _normalize_entity_name(unknown)
                    self._learned_aliases[norm] = known
                    self._learned_count += 1
                    # Also add to the resolution cache for immediate use
                    self._resolution_cache[unknown] = known
                    logger.info(
                        "[EntityResolver] Learned alias via co-occurrence: "
                        "'%s' → '%s' (co-occurred %d times)",
                        unknown, known, count,
                    )

    def invalidate_cache(self) -> None:
        """Clear resolution cache. Called after entity merges."""
        self._resolution_cache.clear()

    def stats(self) -> dict:
        """Resolution engine statistics."""
        return {
            "resolved_total": self._resolved_count,
            "fuzzy_resolved": self._fuzzy_resolved_count,
            "learned_aliases": self._learned_count,
            "learned_alias_map": dict(self._learned_aliases),
            "cache_size": len(self._resolution_cache),
            "normalized_index_size": len(self._normalized_alias_index),
        }


# ── Edge weight decay ──
EDGE_HALF_LIFE = 604800  # 7 days — co-occurrence weight halves weekly
MAX_GRAPH_NODES = 5000   # cap to prevent unbounded growth
PRUNE_BELOW_MENTIONS = 2  # remove nodes with ≤ N mentions during prune

# ══════════════════════════════════════════════════════════════════════════════
#  RELATIONSHIP TYPE CLASSIFICATION (keyword-based, zero-cost)
#
#  Every edge is typed by the headlines that created it. This is NOT just
#  co-occurrence — it captures WHAT the relationship is about.
#  Types are cumulative: an edge can be CONFLICT + DIPLOMACY if both appear.
# ══════════════════════════════════════════════════════════════════════════════

_RELATIONSHIP_KEYWORDS: dict[str, frozenset[str]] = {
    "CONFLICT": frozenset({
        "war", "attack", "strike", "invasion", "retaliation", "missile",
        "bomb", "shell", "kill", "assault", "offensive", "clash",
        "escalation", "hostil", "combat", "battle", "fight",
        "sanctions", "embargo", "blockade", "proxy", "airstrike",
    }),
    "DIPLOMACY": frozenset({
        "meeting", "summit", "treaty", "agreement", "alliance",
        "negotiation", "talks", "dialogue", "visit", "bilateral",
        "diplomatic", "envoy", "ambassador", "accord", "ceasefire",
        "peace", "deal", "pact", "cooperation", "partner",
    }),
    "ECONOMIC_TIE": frozenset({
        "trade", "investment", "tariff", "export", "import",
        "deal", "loan", "debt", "aid", "package", "billion",
        "economic", "commerce", "business", "contract", "supply",
        "pipeline", "energy", "oil", "gas", "lng", "grain",
    }),
    "MILITARY": frozenset({
        "troops", "deploy", "exercise", "military", "defense",
        "arms", "weapon", "navy", "fleet", "aircraft", "base",
        "nato", "battalion", "brigade", "regiment", "drone",
        "missile defense", "nuclear", "warship",
    }),
    "INTELLIGENCE": frozenset({
        "espionage", "spy", "surveillance", "intelligence", "hack",
        "cyber", "intercept", "covert", "classified", "leak",
        "disinformation", "propaganda",
    }),
    "OPPOSITION": frozenset({
        "oppose", "reject", "veto", "condemn", "block", "denounce",
        "protest", "sanction", "expel", "withdraw", "suspend",
        "criticize", "warn", "threaten", "dispute", "tension",
    }),
}


def _classify_relationship(headline: str) -> list[str]:
    """Classify the relationship type(s) expressed in a headline.

    Returns list of relationship type strings (can be multi-typed).
    Zero cost — pure keyword matching.
    """
    text = headline.lower()
    types = []
    for rel_type, keywords in _RELATIONSHIP_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            types.append(rel_type)
    return types or ["CO_OCCURRENCE"]  # fallback: bare co-occurrence


class EntityNode:
    """Metadata stored as node attributes in the NetworkX graph."""

    @staticmethod
    def create(name: str, entity_type: str, timestamp: float) -> dict:
        return {
            "type": entity_type,          # PERSON, GPE, ORG, EVENT, NORP
            "mention_count": 1,
            "first_seen": timestamp,
            "last_seen": timestamp,
            "sources": set(),             # which feeds mentioned this entity
        }


class EntityGraph:
    """Entity Knowledge Graph — Αίολος's relationship intelligence layer.

    Learns entity relationships from every headline in real-time.
    Provides cascade impact analysis for proactive alert scoring.
    Queryable by Αίολος in chat mode.
    """

    def __init__(self, persist_path: str | Path | None = None):
        self._graph = nx.DiGraph()
        self._persist_path = Path(persist_path) if persist_path else None
        self._total_headlines_ingested = 0
        self._total_entities_extracted = 0
        self._mongo = None  # MongoStore — set externally for dual-write

        # P1: Entity Resolution engine — fuzzy dedup across sources
        self._resolver = EntityResolver(self)

        # Load persisted graph if available
        if self._persist_path and self._persist_path.exists():
            self._load()

    # ══════════════════════════════════════════════════════════════
    #  ENTITY EXTRACTION — spaCy NER + alias resolution
    # ══════════════════════════════════════════════════════════════

    def extract_entities(self, text: str) -> list[tuple[str, str]]:
        """Extract named entities from text.

        Returns list of (canonical_name, entity_type) tuples.
        Uses spaCy NER + known alias resolution + fuzzy entity resolution.
        """
        entities: dict[str, str] = {}  # canonical_name → type
        text_lower = text.lower()

        # Phase 1: Known alias matching (catches what spaCy misses)
        for alias, canonical in _ALIAS_TO_CANONICAL.items():
            if alias in text_lower:
                etype = _KNOWN_ENTITIES[canonical][0]
                entities[canonical] = etype

        # Phase 2: spaCy NER (discovers NEW entities not in alias registry)
        nlp = _get_nlp()
        if nlp:
            doc = nlp(text)
            for ent in doc.ents:
                if ent.label_ not in ("PERSON", "GPE", "ORG", "NORP", "LOC", "FAC"):
                    continue
                # Check if already captured via alias
                ent_lower = ent.text.lower()
                if ent_lower in _ALIAS_TO_CANONICAL:
                    canonical = _ALIAS_TO_CANONICAL[ent_lower]
                    entities[canonical] = _KNOWN_ENTITIES[canonical][0]
                elif ent.text not in entities:
                    # Validate NER output — en_core_web_sm is noisy
                    if not _is_valid_ner_entity(ent.text, ent.label_):
                        continue

                    # P1: Entity Resolution — resolve through fuzzy matching
                    # before creating a new graph node
                    resolved = self._resolver.resolve(ent.text, ent.label_)
                    if resolved != ent.text:
                        # Resolved to an existing entity
                        if resolved in _KNOWN_ENTITIES:
                            entities[resolved] = _KNOWN_ENTITIES[resolved][0]
                        elif resolved in self._graph.nodes:
                            entities[resolved] = self._graph.nodes[resolved].get(
                                "type", ent.label_
                            )
                        else:
                            entities[resolved] = ent.label_
                    else:
                        # Genuinely new entity — add as-is
                        entities[ent.text] = ent.label_

        return list(entities.items())

    # ══════════════════════════════════════════════════════════════
    #  HEADLINE INGESTION — updates graph from every data signal
    # ══════════════════════════════════════════════════════════════

    def ingest_headline(
        self,
        headline: str,
        source: str = "",
        timestamp: float | None = None,
    ) -> list[tuple[str, str]]:
        """Ingest a headline: extract entities, update graph.

        Returns the list of extracted (name, type) entities.
        This is called for EVERY headline from collector.
        """
        ts = timestamp or time.time()
        entities = self.extract_entities(headline)

        if not entities:
            return []

        self._total_headlines_ingested += 1
        if self._total_headlines_ingested % 50 == 0:
            logger.info("[EntityGraph] Milestone: %d headlines ingested, %d entities tracked, %d edges",
                        self._total_headlines_ingested, self._graph.number_of_nodes(),
                        self._graph.number_of_edges())
        logger.debug("[EntityGraph] Ingested %d entities from: %.80s → %s",
                     len(entities), headline, [n for n, _ in entities])

        # Update/create nodes
        for name, etype in entities:
            if self._graph.has_node(name):
                node = self._graph.nodes[name]
                node["mention_count"] = node.get("mention_count", 0) + 1
                node["last_seen"] = ts
                if source:
                    sources = node.get("sources", set())
                    if isinstance(sources, list):
                        sources = set(sources)
                    sources.add(source)
                    node["sources"] = sources
            else:
                self._graph.add_node(name, **EntityNode.create(name, etype, ts))
                if source:
                    self._graph.nodes[name]["sources"] = {source}
                self._total_entities_extracted += 1

        # Create/strengthen co-occurrence edges between all entity pairs
        for i, (name_a, _) in enumerate(entities):
            for name_b, _ in entities[i + 1:]:
                self._update_edge(name_a, name_b, ts, headline)

        # Dual-write to MongoDB (non-blocking — failures are silent)
        if self._mongo:
            try:
                for name, etype in entities:
                    self._mongo.upsert_entity(name, etype, source=source, timestamp=ts)
                for i, (name_a, _) in enumerate(entities):
                    for name_b, _ in entities[i + 1:]:
                        self._mongo.upsert_edge(name_a, name_b, timestamp=ts)
                        self._mongo.upsert_edge(name_b, name_a, timestamp=ts)
            except Exception:
                pass  # MongoDB errors never block perception

        # P1: Co-occurrence alias learning — discover aliases from headline patterns
        self._resolver.learn_cooccurrence(entities)

        # Periodic prune + consolidation
        if self._total_headlines_ingested % 500 == 0:
            self._prune()
        if self._total_headlines_ingested % 1000 == 0:
            self.consolidate_entities()

        return entities

    def _update_edge(
        self,
        entity_a: str,
        entity_b: str,
        timestamp: float,
        headline: str,
    ) -> None:
        """Add or strengthen co-occurrence edge between two entities.

        Also classifies the relationship type from the headline text
        and accumulates type counts on the edge.
        """
        rel_types = _classify_relationship(headline)

        # Bidirectional edges
        for src, dst in [(entity_a, entity_b), (entity_b, entity_a)]:
            if self._graph.has_edge(src, dst):
                edge = self._graph[src][dst]
                edge["weight"] = edge.get("weight", 0) + 1.0
                edge["last_seen"] = timestamp
                edge["co_occurrences"] = edge.get("co_occurrences", 0) + 1
                # Keep last 3 headlines as evidence
                headlines = edge.get("recent_headlines", [])
                headlines.append(headline[:120])
                edge["recent_headlines"] = headlines[-3:]
                # Accumulate relationship types
                type_counts = edge.get("relationship_types", {})
                for rt in rel_types:
                    type_counts[rt] = type_counts.get(rt, 0) + 1
                edge["relationship_types"] = type_counts
                edge["latest_relationship"] = rel_types[0] if rel_types else "CO_OCCURRENCE"
            else:
                type_counts = {rt: 1 for rt in rel_types}
                self._graph.add_edge(
                    src, dst,
                    weight=1.0,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    co_occurrences=1,
                    recent_headlines=[headline[:120]],
                    relationship_types=type_counts,
                    latest_relationship=rel_types[0] if rel_types else "CO_OCCURRENCE",
                )

    def _prune(self) -> None:
        """Remove inactive nodes to keep graph manageable."""
        if len(self._graph.nodes) <= MAX_GRAPH_NODES:
            return

        now = time.time()
        remove = []
        for node, data in self._graph.nodes(data=True):
            # Keep known entities always
            if node in _KNOWN_ENTITIES:
                continue
            # Remove if low mentions AND stale
            if (data.get("mention_count", 0) <= PRUNE_BELOW_MENTIONS
                    and (now - data.get("last_seen", 0)) > EDGE_HALF_LIFE):
                remove.append(node)

        for node in remove[:500]:  # batch remove
            self._graph.remove_node(node)

        if remove:
            logger.info("[EntityGraph] Pruned %d stale nodes (remaining: %d)",
                        len(remove[:500]), len(self._graph.nodes))

    # ══════════════════════════════════════════════════════════════
    #  ENTITY MERGE & CONSOLIDATION — P1 fuzzy dedup
    # ══════════════════════════════════════════════════════════════

    def merge_entities(self, keep: str, remove: str) -> bool:
        """Merge entity node `remove` into `keep`.

        All edges, mentions, sources, and relationship data from `remove`
        are transferred to `keep`. The `remove` node is deleted.

        This is the core graph-level dedup operation. Called by
        consolidate_entities() or manually for known duplicates.

        Returns True if merge was performed.
        """
        if keep not in self._graph or remove not in self._graph:
            return False
        if keep == remove:
            return False

        keep_data = self._graph.nodes[keep]
        remove_data = self._graph.nodes[remove]

        # Merge node attributes
        keep_data["mention_count"] = (
            keep_data.get("mention_count", 0) + remove_data.get("mention_count", 0)
        )
        keep_data["first_seen"] = min(
            keep_data.get("first_seen", float("inf")),
            remove_data.get("first_seen", float("inf")),
        )
        keep_data["last_seen"] = max(
            keep_data.get("last_seen", 0), remove_data.get("last_seen", 0)
        )

        # Merge source sets
        keep_sources = keep_data.get("sources", set())
        remove_sources = remove_data.get("sources", set())
        if isinstance(keep_sources, list):
            keep_sources = set(keep_sources)
        if isinstance(remove_sources, list):
            remove_sources = set(remove_sources)
        keep_data["sources"] = keep_sources | remove_sources

        # Transfer incoming edges
        for pred in list(self._graph.predecessors(remove)):
            if pred == keep or pred == remove:
                continue
            edge_data = dict(self._graph[pred][remove])
            if self._graph.has_edge(pred, keep):
                self._merge_edge_data(self._graph[pred][keep], edge_data)
            else:
                self._graph.add_edge(pred, keep, **edge_data)

        # Transfer outgoing edges
        for succ in list(self._graph.successors(remove)):
            if succ == keep or succ == remove:
                continue
            edge_data = dict(self._graph[remove][succ])
            if self._graph.has_edge(keep, succ):
                self._merge_edge_data(self._graph[keep][succ], edge_data)
            else:
                self._graph.add_edge(keep, succ, **edge_data)

        # Remove the merged node
        self._graph.remove_node(remove)
        logger.info("[EntityGraph] Merged entity '%s' → '%s'", remove, keep)
        return True

    @staticmethod
    def _merge_edge_data(existing: dict, incoming: dict) -> None:
        """Merge edge attributes from incoming into existing."""
        existing["weight"] = existing.get("weight", 0) + incoming.get("weight", 0)
        existing["co_occurrences"] = (
            existing.get("co_occurrences", 0) + incoming.get("co_occurrences", 0)
        )
        existing["last_seen"] = max(
            existing.get("last_seen", 0), incoming.get("last_seen", 0)
        )
        # Merge recent headlines (keep last 3)
        old_hl = existing.get("recent_headlines", [])
        new_hl = incoming.get("recent_headlines", [])
        existing["recent_headlines"] = (old_hl + new_hl)[-3:]
        # Merge relationship type counts
        existing_rt = existing.get("relationship_types", {})
        incoming_rt = incoming.get("relationship_types", {})
        for rt, count in incoming_rt.items():
            existing_rt[rt] = existing_rt.get(rt, 0) + count
        existing["relationship_types"] = existing_rt

    def consolidate_entities(self) -> int:
        """Scan for duplicate entities in the graph and merge them.

        Uses normalized name matching + Jaro-Winkler fuzzy matching
        to find nodes that represent the same real-world entity.
        Called periodically (every 1000 headlines) or on demand.

        Returns number of merges performed.
        """
        nodes = list(self._graph.nodes)
        merged_away: set[str] = set()
        merges = 0

        # Phase 1: Normalize-based dedup (fast, high confidence)
        norm_groups: dict[str, list[str]] = defaultdict(list)
        for node in nodes:
            norm = _normalize_entity_name(node)
            if norm:
                norm_groups[norm].append(node)

        for norm, group in norm_groups.items():
            if len(group) < 2:
                continue
            # Pick the "best" name: known entity first, then most mentions
            best = None
            for name in group:
                if name in _KNOWN_ENTITIES:
                    best = name
                    break
            if not best:
                best = max(
                    group,
                    key=lambda n: self._graph.nodes.get(n, {}).get("mention_count", 0),
                )
            for name in group:
                if name == best or name in merged_away:
                    continue
                if self.merge_entities(best, name):
                    merged_away.add(name)
                    merges += 1
                    if merges >= 50:
                        break
            if merges >= 50:
                break

        # Phase 2: Fuzzy-based dedup (slower, for remaining nodes)
        if merges < 50:
            remaining = [
                n for n in self._graph.nodes
                if n not in _KNOWN_ENTITIES and n not in merged_away
            ]
            # Only check nodes with enough mentions to be worth deduping
            remaining = [
                n for n in remaining
                if self._graph.nodes[n].get("mention_count", 0) >= 2
            ]
            remaining.sort(
                key=lambda n: self._graph.nodes[n].get("mention_count", 0),
                reverse=True,
            )

            for i, node_a in enumerate(remaining[:200]):
                if node_a in merged_away or merges >= 50:
                    break
                norm_a = _normalize_entity_name(node_a)
                type_a = self._graph.nodes[node_a].get("type", "")

                for node_b in remaining[i + 1: i + 100]:
                    if node_b in merged_away:
                        continue
                    type_b = self._graph.nodes.get(node_b, {}).get("type", "")
                    if type_a and type_b and type_a != type_b:
                        continue

                    norm_b = _normalize_entity_name(node_b)
                    sim = _jaro_winkler(norm_a, norm_b)
                    if sim < 0.90:
                        continue

                    # Merge into the one with more mentions
                    mentions_a = self._graph.nodes[node_a].get("mention_count", 0)
                    mentions_b = self._graph.nodes[node_b].get("mention_count", 0)
                    if mentions_a >= mentions_b:
                        keep, remove = node_a, node_b
                    else:
                        keep, remove = node_b, node_a

                    if self.merge_entities(keep, remove):
                        merged_away.add(remove)
                        merges += 1
                        if merges >= 50:
                            break

        if merges:
            logger.info(
                "[EntityGraph] Consolidation complete: %d entities merged (remaining: %d)",
                merges, len(self._graph.nodes),
            )
            # Invalidate resolver cache after merges
            self._resolver.invalidate_cache()

        return merges

    # ══════════════════════════════════════════════════════════════
    #  CASCADE IMPACT ANALYSIS — graph-powered impact estimation
    # ══════════════════════════════════════════════════════════════

    def get_cascade_impact(
        self,
        entity_names: list[str],
        depth: int = 2,
    ) -> dict:
        """Estimate cascade impact for a set of entities.

        Traverses graph relationships to find connected entities,
        calculates impact based on:
          - Entity type (PERSON vs GPE vs ORG)
          - Connection strength (decayed co-occurrence weight)
          - Network centrality (highly-connected entities = more impact)
          - Reach depth (direct vs indirect connections)

        Returns:
            {
                "impact_score": 0.0-1.0,
                "affected_entities": [...],
                "cascade_chains": [...],
                "explanation": "..."
            }
        """
        now = time.time()
        resolved = []
        for name in entity_names:
            # Try alias resolution
            name_lower = name.lower()
            if name_lower in _ALIAS_TO_CANONICAL:
                resolved.append(_ALIAS_TO_CANONICAL[name_lower])
            elif name in self._graph:
                resolved.append(name)

        if not resolved:
            return {"impact_score": 0.0, "affected_entities": [], "cascade_chains": [], "explanation": "Unknown entities"}

        # BFS from each entity, collecting affected nodes
        affected: dict[str, float] = {}  # entity → accumulated impact weight
        chains: list[str] = []

        for root in resolved:
            if root not in self._graph:
                continue

            # Start BFS
            visited = {root}
            queue = [(root, 0, 1.0)]  # (node, current_depth, decay_factor)

            while queue:
                current, d, decay = queue.pop(0)
                if d >= depth:
                    continue

                for neighbor in self._graph.successors(current):
                    if neighbor in visited:
                        continue
                    visited.add(neighbor)

                    edge = self._graph[current][neighbor]
                    raw_weight = edge.get("weight", 1.0)
                    age = max(0, now - edge.get("last_seen", now))
                    decayed_weight = raw_weight * math.exp(-0.693 * age / EDGE_HALF_LIFE)

                    # Neighbor impact contribution
                    neighbor_importance = self._node_importance(neighbor)
                    contribution = decayed_weight * neighbor_importance * decay * 0.5

                    affected[neighbor] = affected.get(neighbor, 0) + contribution

                    if d == 0 and contribution > 0.1:
                        chains.append(f"{root} → {neighbor} (weight={decayed_weight:.1f})")

                    queue.append((neighbor, d + 1, decay * 0.5))

        # Calculate aggregate impact
        root_importance = sum(self._node_importance(r) for r in resolved if r in self._graph)
        cascade_boost = min(0.3, sum(affected.values()) * 0.05)  # cap cascade bonus

        impact = min(1.0, root_importance + cascade_boost)

        # Top affected entities (sorted by contribution)
        top_affected = sorted(affected.items(), key=lambda x: x[1], reverse=True)[:10]

        explanation_parts = [f"Root entities: {', '.join(resolved)} (importance={root_importance:.2f})"]
        if top_affected:
            explanation_parts.append(
                f"Cascade reaches: {', '.join(f'{n}({w:.2f})' for n, w in top_affected[:5])}"
            )
        explanation_parts.append(f"Total cascade boost: +{cascade_boost:.2f}")

        return {
            "impact_score": round(impact, 3),
            "affected_entities": [n for n, _ in top_affected],
            "cascade_chains": chains[:10],
            "explanation": " | ".join(explanation_parts),
        }

    def _node_importance(self, name: str) -> float:
        """Calculate importance of a single entity node.

        Based on:
          - Entity type tier (global figure > country > org > other)
          - Mention count (log-scaled)
          - In-degree (how many entities co-occur with this one)
        """
        if name not in self._graph:
            return 0.0

        node = self._graph.nodes[name]
        etype = node.get("type", "")

        # Type-based base importance (aligned with proactive impact scoring)
        type_scores = {
            "PERSON": 0.40,  # base for any person
            "GPE": 0.35,     # base for any country/place
            "ORG": 0.30,     # base for any org
            "NORP": 0.20,    # national/religious/political group
            "LOC": 0.15,     # geographic location
        }
        base = type_scores.get(etype, 0.10)

        # Known entity boost — tier-1 entities get higher base
        if name in _KNOWN_ENTITIES:
            known_type = _KNOWN_ENTITIES[name][0]
            if known_type == "PERSON":
                base = 0.70  # Global figure
            elif known_type == "GPE":
                base = 0.55  # Major power
            elif known_type == "ORG":
                base = 0.45  # Key international org

        # Mention count bonus (log-scaled, max +0.15)
        mentions = node.get("mention_count", 1)
        mention_bonus = min(0.15, math.log2(mentions + 1) * 0.03)

        # Connectivity bonus (in-degree, max +0.10)
        in_degree = self._graph.in_degree(name) if name in self._graph else 0
        connectivity_bonus = min(0.10, in_degree * 0.02)

        return min(1.0, base + mention_bonus + connectivity_bonus)

    # ══════════════════════════════════════════════════════════════
    #  QUERY INTERFACE — for Αίολος chat mode
    # ══════════════════════════════════════════════════════════════

    def get_entity_brief(self, entity_name: str) -> str:
        """Get a human-readable brief about an entity and its relationships.

        Used by Αίολος when user asks about specific actors.
        """
        # Resolve alias
        name_lower = entity_name.lower()
        canonical = _ALIAS_TO_CANONICAL.get(name_lower, entity_name)

        if canonical not in self._graph:
            return f"Entity '{entity_name}' not found in knowledge graph."

        node = self._graph.nodes[canonical]
        etype = node.get("type", "UNKNOWN")
        mentions = node.get("mention_count", 0)
        first_seen = datetime.fromtimestamp(node.get("first_seen", 0), tz=timezone.utc)
        last_seen = datetime.fromtimestamp(node.get("last_seen", 0), tz=timezone.utc)

        # Get connected entities sorted by weight
        connections = []
        for neighbor in self._graph.successors(canonical):
            edge = self._graph[canonical][neighbor]
            connections.append((
                neighbor,
                edge.get("weight", 0),
                edge.get("co_occurrences", 0),
                edge.get("recent_headlines", []),
                edge.get("relationship_types", {}),
            ))
        connections.sort(key=lambda x: x[1], reverse=True)

        lines = [
            f"ENTITY: {canonical} [{etype}]",
            f"Mentions: {mentions} | First seen: {first_seen:%Y-%m-%d} | Last seen: {last_seen:%Y-%m-%d %H:%M}",
            f"Importance: {self._node_importance(canonical):.2f}",
            f"Connections: {len(connections)}",
        ]

        if connections:
            lines.append("\nTop connections:")
            for name, weight, co_occ, headlines, rel_types in connections[:10]:
                neighbor_type = self._graph.nodes[name].get("type", "?")
                # Format relationship types
                if rel_types:
                    sorted_types = sorted(rel_types.items(), key=lambda x: x[1], reverse=True)
                    type_str = "+".join(t for t, _ in sorted_types[:2])
                else:
                    type_str = "co-occur"
                lines.append(f"  → {name} [{neighbor_type}] ({type_str}) weight={weight:.1f} "
                             f"(co-occurred {co_occ}× in news)")
                for h in headlines[-2:]:
                    lines.append(f"      Evidence: \"{h}\"")

        return "\n".join(lines)

    def get_world_graph_summary(self, top_n: int = 20) -> str:
        """Get a rich summary of the most active entities and relationships.

        Includes relationship types, narrative threads, and pattern indicators.
        Used in pipeline context enrichment, chat context, and briefings.
        """
        if not self._graph.nodes:
            return "Entity graph is empty — no headlines ingested yet."

        now = time.time()

        # Top entities by recent mention activity
        entity_scores = []
        for name, data in self._graph.nodes(data=True):
            recency = max(0, now - data.get("last_seen", 0))
            recency_factor = math.exp(-0.693 * recency / 86400)  # 1-day half-life for ranking
            score = data.get("mention_count", 0) * recency_factor
            entity_scores.append((name, data.get("type", "?"), score, data.get("mention_count", 0)))

        entity_scores.sort(key=lambda x: x[2], reverse=True)

        lines = [
            f"ENTITY KNOWLEDGE GRAPH — {len(self._graph.nodes)} entities, "
            f"{len(self._graph.edges)} relationships, "
            f"{self._total_headlines_ingested} headlines processed",
            "",
            "Top active entities:",
        ]

        for name, etype, score, mentions in entity_scores[:top_n]:
            connections = self._graph.out_degree(name)
            lines.append(f"  {name} [{etype}] — {mentions} mentions, "
                         f"{connections} connections, activity={score:.1f}")

        # Top active TYPED edges (most recent strong relationships with types)
        edge_scores = []
        for u, v, data in self._graph.edges(data=True):
            weight = data.get("weight", 0)
            recency = max(0, now - data.get("last_seen", 0))
            recency_factor = math.exp(-0.693 * recency / 86400)
            rel_types = data.get("relationship_types", {})
            edge_scores.append((u, v, weight * recency_factor, data.get("recent_headlines", []),
                                rel_types, data.get("co_occurrences", 0)))

        edge_scores.sort(key=lambda x: x[2], reverse=True)

        lines.append("\nHottest relationships (typed):")
        seen_pairs = set()
        shown = 0
        for u, v, score, headlines, rel_types, co_occ in edge_scores:
            pair = tuple(sorted([u, v]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if shown >= 15:
                break
            shown += 1

            # Format relationship types
            if rel_types:
                sorted_types = sorted(rel_types.items(), key=lambda x: x[1], reverse=True)
                type_str = ", ".join(f"{t}({c})" for t, c in sorted_types[:3])
            else:
                type_str = "CO_OCCURRENCE"

            lines.append(f"  {u} ↔ {v} [{type_str}] (activity={score:.1f}, co-occurred {co_occ}×)")
            if headlines:
                lines.append(f"    Evidence: \"{headlines[-1]}\"")

        # Narrative threads: detect entity chains (A→B→C where A-B and B-C are both hot)
        top_entities = [name for name, _, _, _ in entity_scores[:30]]
        chains = self._detect_narrative_chains(top_entities, now)
        if chains:
            lines.append("\nNarrative chains (connected entity paths):")
            for chain in chains[:5]:
                lines.append(f"  {chain}")

        return "\n".join(lines)

    def _detect_narrative_chains(self, top_entities: list[str], now: float) -> list[str]:
        """Detect meaningful entity chains: A→B→C where relationships are recent.

        Returns formatted chain strings like: 'Putin →[MILITARY]→ Ukraine →[DIPLOMACY]→ NATO'
        """
        chains = []
        for entity_a in top_entities[:15]:
            if entity_a not in self._graph:
                continue
            for entity_b in self._graph.successors(entity_a):
                if entity_b not in self._graph or entity_b == entity_a:
                    continue
                edge_ab = self._graph[entity_a][entity_b]
                age_ab = now - edge_ab.get("last_seen", 0)
                if age_ab > 172800:  # skip if older than 48h
                    continue
                rel_ab = edge_ab.get("latest_relationship", "?")

                for entity_c in self._graph.successors(entity_b):
                    if entity_c == entity_a or entity_c == entity_b:
                        continue
                    if entity_c not in self._graph:
                        continue
                    edge_bc = self._graph[entity_b][entity_c]
                    age_bc = now - edge_bc.get("last_seen", 0)
                    if age_bc > 172800:
                        continue
                    rel_bc = edge_bc.get("latest_relationship", "?")

                    weight = (edge_ab.get("weight", 0) + edge_bc.get("weight", 0))
                    chains.append((
                        weight,
                        f"{entity_a} →[{rel_ab}]→ {entity_b} →[{rel_bc}]→ {entity_c}",
                    ))

        chains.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in chains[:5]]

    def get_top_entities(self, n: int = 5) -> list[tuple[str, float]]:
        """Return the top-N entities by recent activity (weighted degree).

        Used by financial feeds to inject context entity names
        into anomaly headlines so cross-domain clustering works.
        """
        if not self._graph.nodes:
            logger.debug("[EntityGraph] get_top_entities: graph is empty")
            return []

        now = time.time()
        scores: list[tuple[str, float]] = []
        for node in self._graph.nodes:
            degree = 0.0
            for _, _, data in self._graph.edges(node, data=True):
                weight = data.get("weight", 1.0)
                last_seen = data.get("last_seen", now)
                age = now - last_seen
                decay = math.exp(-0.693 * age / EDGE_HALF_LIFE)
                degree += weight * decay
            scores.append((node, degree))
        scores.sort(key=lambda x: x[1], reverse=True)
        result = scores[:n]
        if result:
            logger.debug("[EntityGraph] Top-%d entities: %s",
                         n, [(name, round(sc, 2)) for name, sc in result])
        return result

    def query(self, question: str) -> str:
        """Answer a natural-language entity question.

        Parses the question for entity names and returns graph intelligence.
        Used by Αίολος in chat mode as a callable tool.
        """
        entities = self.extract_entities(question)
        if not entities:
            return self.get_world_graph_summary(top_n=15)

        results = []
        for name, _ in entities[:3]:  # max 3 entities per query
            brief = self.get_entity_brief(name)
            results.append(brief)

        if len(entities) > 1:
            # Also show cascade impact for the combination
            names = [n for n, _ in entities]
            cascade = self.get_cascade_impact(names)
            results.append(
                f"\nCOMBINED IMPACT ANALYSIS: {', '.join(names)}\n"
                f"Combined impact score: {cascade['impact_score']:.2f}\n"
                f"Cascade chains: {'; '.join(cascade['cascade_chains'][:5]) or 'none yet'}\n"
                f"Affected entities: {', '.join(cascade['affected_entities'][:8]) or 'none'}\n"
                f"{cascade['explanation']}"
            )

        return "\n\n".join(results)

    # ══════════════════════════════════════════════════════════════
    #  LLM-BASED DEEP RELATIONSHIP ENRICHMENT
    #  Periodically analyzes the hottest edges for nuanced typing.
    #  Called from ReflectionLoop or pipeline, NOT per-headline.
    # ══════════════════════════════════════════════════════════════

    def enrich_top_edges_with_llm(self, llm_client, top_n: int = 10) -> int:
        """Use LLM to deeply classify the top-N hottest edges.

        Extracts nuanced relationship descriptions beyond keyword matching.
        Returns number of edges enriched.
        """
        now = time.time()

        # Score edges
        edge_scores = []
        seen_pairs = set()
        for u, v, data in self._graph.edges(data=True):
            pair = tuple(sorted([u, v]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            weight = data.get("weight", 0)
            recency = max(0, now - data.get("last_seen", 0))
            if recency > 172800:  # skip edges older than 48h
                continue
            recency_factor = math.exp(-0.693 * recency / 86400)
            score = weight * recency_factor
            headlines = data.get("recent_headlines", [])
            if headlines:
                edge_scores.append((u, v, score, headlines))

        edge_scores.sort(key=lambda x: x[2], reverse=True)
        top_edges = edge_scores[:top_n]

        if not top_edges:
            return 0

        # Build batch prompt
        edge_texts = []
        for i, (u, v, _, headlines) in enumerate(top_edges, 1):
            hl_text = " | ".join(headlines[-3:])
            edge_texts.append(f"{i}. {u} ↔ {v}: {hl_text}")

        prompt = (
            "Classify each entity pair's relationship based on the headlines.\n"
            "For each, output a one-line description of the NATURE of the relationship.\n"
            "Format: NUMBER. RELATIONSHIP_SUMMARY (max 15 words)\n\n"
            + "\n".join(edge_texts)
        )

        try:
            result = llm_client.call(
                "You classify geopolitical/economic entity relationships from headlines. "
                "Be precise and factual. Output only numbered lines.",
                prompt,
                max_tokens=2000,
                temperature=0.2,
                thinking=False,
            )

            # Parse results and store as edge attribute
            enriched = 0
            for line in result.strip().split("\n"):
                line = line.strip()
                if not line or not line[0].isdigit():
                    continue
                try:
                    idx = int(line.split(".")[0]) - 1
                    if 0 <= idx < len(top_edges):
                        summary = line.split(".", 1)[1].strip()[:100]
                        u, v = top_edges[idx][0], top_edges[idx][1]
                        # Store on both directions
                        for src, dst in [(u, v), (v, u)]:
                            if self._graph.has_edge(src, dst):
                                self._graph[src][dst]["llm_relationship"] = summary
                        enriched += 1
                except (ValueError, IndexError):
                    continue

            if enriched:
                logger.info("[EntityGraph] LLM enriched %d/%d top edges", enriched, len(top_edges))
            return enriched

        except Exception as e:
            logger.warning("[EntityGraph] LLM enrichment failed: %s", e)
            return 0

    # ══════════════════════════════════════════════════════════════
    #  STATS
    # ══════════════════════════════════════════════════════════════

    @property
    def node_count(self) -> int:
        return len(self._graph.nodes)

    @property
    def edge_count(self) -> int:
        return len(self._graph.edges)

    @property
    def headlines_ingested(self) -> int:
        return self._total_headlines_ingested

    def stats(self) -> dict:
        resolver_stats = self._resolver.stats() if self._resolver else {}
        return {
            "nodes": self.node_count,
            "edges": self.edge_count,
            "headlines_ingested": self._total_headlines_ingested,
            "entities_extracted": self._total_entities_extracted,
            "resolver": resolver_stats,
        }

    # ══════════════════════════════════════════════════════════════
    #  VISUALIZATION — export graph data for interactive rendering
    # ══════════════════════════════════════════════════════════════

    _TYPE_COLORS: dict[str, str] = {
        "GPE":      "#4A90D9",   # Countries/cities — blue
        "PERSON":   "#E74C3C",   # People — red
        "ORG":      "#2ECC71",   # Organizations — green
        "NORP":     "#F39C12",   # Nationalities/groups — orange
        "EVENT":    "#9B59B6",   # Events — purple
        "LOC":      "#1ABC9C",   # Locations — teal
        "FAC":      "#E91E63",   # Facilities — pink
        "PRODUCT":  "#FF9800",   # Products — amber
        "UNKNOWN":  "#95A5A6",   # Fallback — grey
    }

    def export_vis_data(
        self,
        entity_filter: str = "",
        entity_type: str = "",
        max_nodes: int = 150,
        min_mentions: int = 2,
    ) -> dict[str, Any]:
        """Export graph data in a format suitable for interactive visualization.

        Parameters
        ----------
        entity_filter : str
            If set, only include nodes whose name contains this substring (case-insensitive).
        entity_type : str
            If set, only include nodes of this spaCy NER type (GPE, PERSON, ORG, etc.).
        max_nodes : int
            Maximum number of nodes to include (by activity score).
        min_mentions : int
            Minimum mention count to include a node.

        Returns
        -------
        dict with keys: nodes (list), edges (list), meta (dict)
        """
        now = time.time()

        # Score all nodes by recency-weighted activity
        scored: list[tuple[str, dict, float]] = []
        for name, data in self._graph.nodes(data=True):
            mentions = data.get("mention_count", 0)
            if mentions < min_mentions:
                continue
            if entity_filter and entity_filter.lower() not in name.lower():
                continue
            ntype = data.get("type", "UNKNOWN")
            if entity_type and ntype.upper() != entity_type.upper():
                continue

            last_seen = data.get("last_seen", 0)
            recency = max(0, now - last_seen)
            recency_factor = math.exp(-0.693 * recency / 86400)
            score = mentions * recency_factor
            scored.append((name, data, score))

        scored.sort(key=lambda x: x[2], reverse=True)
        selected = scored[:max_nodes]
        node_set = {name for name, _, _ in selected}

        # Build node list
        vis_nodes = []
        for name, data, score in selected:
            ntype = data.get("type", "UNKNOWN")
            vis_nodes.append({
                "id": name,
                "label": name,
                "type": ntype,
                "color": self._TYPE_COLORS.get(ntype, self._TYPE_COLORS["UNKNOWN"]),
                "size": max(8, min(50, int(data.get("mention_count", 1) ** 0.6 * 5))),
                "mentions": data.get("mention_count", 0),
                "last_seen_iso": datetime.fromtimestamp(
                    data.get("last_seen", 0), tz=timezone.utc
                ).isoformat() if data.get("last_seen") else None,
                "activity_score": round(score, 2),
            })

        # Build edge list (only edges between selected nodes)
        vis_edges = []
        for u, v, data in self._graph.edges(data=True):
            if u not in node_set or v not in node_set:
                continue
            weight = data.get("weight", 1.0)
            vis_edges.append({
                "source": u,
                "target": v,
                "weight": round(weight, 2),
                "co_occurrences": data.get("co_occurrence_count", 0),
                "width": max(1, min(8, int(weight ** 0.5))),
                "recent_headlines": data.get("recent_headlines", [])[-3:],
            })

        meta = {
            "total_nodes": len(self._graph.nodes),
            "total_edges": len(self._graph.edges),
            "displayed_nodes": len(vis_nodes),
            "displayed_edges": len(vis_edges),
            "headlines_ingested": self._total_headlines_ingested,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "type_legend": {k: v for k, v in self._TYPE_COLORS.items()
                           if any(n["type"] == k for n in vis_nodes)},
        }

        return {"nodes": vis_nodes, "edges": vis_edges, "meta": meta}

    # ══════════════════════════════════════════════════════════════
    #  CROSS-PATTERN PATH ANALYSIS — finds entity connections between
    #  different pattern clusters. This is the bridge that connects
    #  isolated patterns into causal chains.
    # ══════════════════════════════════════════════════════════════

    def find_connecting_paths(
        self,
        entities_a: set[str],
        entities_b: set[str],
        max_depth: int = 3,
        max_paths: int = 5,
    ) -> list[dict]:
        """Find shortest graph paths connecting two entity sets.

        Given entities from Pattern A and entities from Pattern B,
        discovers HOW they're connected through the knowledge graph.
        This reveals hidden causal chains:
          e.g. "Iran" → "Oil" → "VIX" → "Fed"
          connecting a geopolitical pattern to a market pattern.

        Returns list of path dicts:
        [
            {
                "source": "Iran",
                "target": "Oil",
                "path": ["Iran", "OPEC", "Oil"],
                "path_edges": [
                    {"from": "Iran", "to": "OPEC", "rel": "ECONOMIC", "weight": 12.0},
                    {"from": "OPEC", "to": "Oil", "rel": "ECONOMIC", "weight": 45.0},
                ],
                "total_weight": 57.0,
                "depth": 2,
            },
            ...
        ]
        """
        now = time.time()
        results: list[dict] = []

        # Resolve aliases
        resolved_a: set[str] = set()
        for name in entities_a:
            canonical = _ALIAS_TO_CANONICAL.get(name.lower(), name)
            if canonical in self._graph:
                resolved_a.add(canonical)

        resolved_b: set[str] = set()
        for name in entities_b:
            canonical = _ALIAS_TO_CANONICAL.get(name.lower(), name)
            if canonical in self._graph:
                resolved_b.add(canonical)

        if not resolved_a or not resolved_b:
            return []

        # Skip if sets overlap (already connected by shared entities)
        shared = resolved_a & resolved_b
        if shared:
            results.append({
                "source": "SHARED",
                "target": "SHARED",
                "path": sorted(shared),
                "path_edges": [],
                "total_weight": 999.0,
                "depth": 0,
                "shared_entities": sorted(shared),
            })

        # BFS from each entity in set A looking for entities in set B
        seen_paths: set[str] = set()

        for src in resolved_a:
            if len(results) >= max_paths:
                break

            # BFS with path tracking
            queue: list[tuple[str, list[str]]] = [(src, [src])]
            visited: set[str] = {src}

            while queue and len(results) < max_paths:
                current, path = queue.pop(0)

                if len(path) > max_depth + 1:
                    continue

                # Check if we reached any entity in set B
                if current in resolved_b and current != src:
                    path_key = "→".join(path)
                    if path_key not in seen_paths:
                        seen_paths.add(path_key)

                        # Build edge details along the path
                        path_edges = []
                        total_weight = 0.0
                        for i in range(len(path) - 1):
                            edge_data = self._graph.get_edge_data(path[i], path[i + 1], default={})
                            raw_w = edge_data.get("weight", 0.0)
                            age = max(0, now - edge_data.get("last_seen", now))
                            decayed_w = raw_w * math.exp(-0.693 * age / EDGE_HALF_LIFE)
                            rel_type = edge_data.get("latest_relationship", "CO_OCCURRENCE")
                            headlines = edge_data.get("recent_headlines", [])
                            path_edges.append({
                                "from": path[i],
                                "to": path[i + 1],
                                "rel": rel_type,
                                "weight": round(decayed_w, 1),
                                "evidence": headlines[:2],
                            })
                            total_weight += decayed_w

                        results.append({
                            "source": src,
                            "target": current,
                            "path": list(path),
                            "path_edges": path_edges,
                            "total_weight": round(total_weight, 1),
                            "depth": len(path) - 1,
                        })

                # Expand neighbors (prefer high-weight edges)
                neighbors = []
                for neighbor in self._graph.successors(current):
                    if neighbor in visited:
                        continue
                    edge_data = self._graph.get_edge_data(current, neighbor, default={})
                    w = edge_data.get("weight", 0.0)
                    neighbors.append((neighbor, w))

                # Sort by weight descending — explore strong connections first
                neighbors.sort(key=lambda x: x[1], reverse=True)

                for neighbor, _ in neighbors[:15]:  # cap branching factor
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, path + [neighbor]))

        # Sort results by total_weight descending (strongest connections first)
        results.sort(key=lambda r: r["total_weight"], reverse=True)
        return results[:max_paths]

    def get_entity_neighborhood(
        self,
        entity_names: list[str],
        max_neighbors: int = 10,
    ) -> dict:
        """Get enriched neighborhood context for a set of entities.

        Returns structured data about each entity's strongest connections,
        relationship types, and recent evidence — optimized for LLM context injection.
        """
        now = time.time()
        context: dict[str, list[dict]] = {}

        for name in entity_names:
            canonical = _ALIAS_TO_CANONICAL.get(name.lower(), name)
            if canonical not in self._graph:
                continue

            neighbors: list[dict] = []
            for neighbor in self._graph.successors(canonical):
                edge = self._graph[canonical][neighbor]
                raw_w = edge.get("weight", 0.0)
                age = max(0, now - edge.get("last_seen", now))
                decayed_w = raw_w * math.exp(-0.693 * age / EDGE_HALF_LIFE)

                if decayed_w < 0.5:
                    continue  # skip very weak/stale connections

                neighbors.append({
                    "entity": neighbor,
                    "type": self._graph.nodes.get(neighbor, {}).get("type", "?"),
                    "relationship": edge.get("latest_relationship", "CO_OCCURRENCE"),
                    "strength": round(decayed_w, 1),
                    "co_occurrences": edge.get("co_occurrences", 0),
                    "evidence": edge.get("recent_headlines", [])[:2],
                })

            # Sort by strength descending
            neighbors.sort(key=lambda n: n["strength"], reverse=True)
            context[canonical] = neighbors[:max_neighbors]

        return context

    # ══════════════════════════════════════════════════════════════
    #  PERSISTENCE — JSON save/load
    # ══════════════════════════════════════════════════════════════

    def save(self) -> None:
        """Persist graph to JSON file."""
        if not self._persist_path:
            return

        self._persist_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert NetworkX graph to serializable format
        nodes = {}
        for name, data in self._graph.nodes(data=True):
            node_data = dict(data)
            # Convert sets to lists for JSON
            if "sources" in node_data:
                node_data["sources"] = list(node_data["sources"])
            nodes[name] = node_data

        edges = []
        for u, v, data in self._graph.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                **data,
            })

        payload = {
            "meta": {
                "saved_at": datetime.now(tz=timezone.utc).isoformat(),
                "nodes": len(nodes),
                "edges": len(edges),
                "headlines_ingested": self._total_headlines_ingested,
                "entities_extracted": self._total_entities_extracted,
            },
            "nodes": nodes,
            "edges": edges,
        }

        self._persist_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        logger.info("[EntityGraph] Saved: %d nodes, %d edges → %s",
                    len(nodes), len(edges), self._persist_path)

    def _load(self) -> None:
        """Load persisted graph from JSON."""
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))

            for name, node_data in data.get("nodes", {}).items():
                if "sources" in node_data:
                    node_data["sources"] = set(node_data["sources"])
                self._graph.add_node(name, **node_data)

            for edge in data.get("edges", []):
                src = edge.pop("source")
                tgt = edge.pop("target")
                self._graph.add_edge(src, tgt, **edge)

            meta = data.get("meta", {})
            self._total_headlines_ingested = meta.get("headlines_ingested", 0)
            self._total_entities_extracted = meta.get("entities_extracted", 0)

            logger.info("[EntityGraph] Loaded: %d nodes, %d edges from %s",
                        len(self._graph.nodes), len(self._graph.edges), self._persist_path)
        except Exception as e:
            logger.warning("[EntityGraph] Failed to load %s: %s", self._persist_path, e)
