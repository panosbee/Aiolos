"""
XDART-Φ × XHEART — Sanctions Cross-Reference Engine (Palantir P0)

Auto-downloads and cross-references international sanctions lists against
the EntityGraph. Flags any entity that appears in both our intelligence
and an active sanctions list.

"Αν δεν ξέρεις ποιος είναι κυρωμένος, δεν ξέρεις τίποτα."

Data Sources (all FREE, no authentication):
  1. OFAC SDN List (US Treasury) — CSV
  2. EU Consolidated Financial Sanctions — XML
  3. UN Security Council Consolidated List — XML

Architecture:
  - Downloads lists on startup + every 24 hours (auto-refresh)
  - Parses into unified SanctionEntry format
  - Fuzzy-matches against EntityGraph entities
  - Caches matches for injection into LLM context
  - Produces PatternSignals when new matches discovered
"""

import csv
import io
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("xdart.knowledge.sanctions")

# ── Lazy imports ──
_httpx = None


def _get_httpx():
    global _httpx
    if _httpx is None:
        try:
            import httpx
            _httpx = httpx
        except ImportError:
            logger.warning("[Sanctions] httpx not installed")
            _httpx = False
    return _httpx if _httpx is not False else None


# ══════════════════════════════════════════════════════════════════════════════
#  DATA SOURCES
# ══════════════════════════════════════════════════════════════════════════════

OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_SDN_ALT_URL = "https://www.treasury.gov/ofac/downloads/sdnlist.txt"
EU_SANCTIONS_URL = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/"
    "xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"
)
UN_SANCTIONS_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"

# Refresh interval: 24 hours
REFRESH_INTERVAL = 86400


@dataclass
class SanctionEntry:
    """Unified sanctions entry across all lists."""
    name: str
    entity_type: str          # "individual", "entity", "vessel", "aircraft"
    source: str               # "OFAC", "EU", "UN"
    program: str = ""         # Sanctions program (e.g., "UKRAINE-EO13662")
    aliases: list[str] = field(default_factory=list)
    nationality: str = ""
    id_numbers: list[str] = field(default_factory=list)  # Passport, MMSI, IMO, etc.
    remarks: str = ""
    list_date: str = ""


def _normalize_name(name: str) -> str:
    """Normalize entity name for fuzzy matching."""
    name = name.lower().strip()
    # Remove common suffixes/prefixes
    for suffix in [" ltd", " llc", " inc", " corp", " co.", " plc", " gmbh",
                   " s.a.", " jsc", " ojsc", " pjsc"]:
        name = name.replace(suffix, "")
    # Remove punctuation
    name = re.sub(r"[^\w\s]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _name_similarity(a: str, b: str) -> float:
    """Simple name similarity score (0-1) using token overlap.

    More robust than exact match for international name variations.
    """
    tokens_a = set(_normalize_name(a).split())
    tokens_b = set(_normalize_name(b).split())
    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    if not union:
        return 0.0

    # Jaccard similarity with length bonus for longer name matches
    jaccard = len(intersection) / len(union)
    # Bonus: if all tokens of shorter name match
    shorter = tokens_a if len(tokens_a) <= len(tokens_b) else tokens_b
    if shorter and intersection == shorter and len(shorter) >= 2:
        jaccard = max(jaccard, 0.85)

    return jaccard


# ══════════════════════════════════════════════════════════════════════════════
#  SANCTIONS REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

class SanctionsRegistry:
    """Downloads, parses, and cross-references international sanctions lists.

    Cross-references against EntityGraph entities to identify sanctioned
    actors in our intelligence data.
    """

    def __init__(self):
        self._entries: list[SanctionEntry] = []
        self._by_name: dict[str, list[SanctionEntry]] = {}  # normalized_name → entries
        self._entity_matches: dict[str, list[dict]] = {}     # entity_name → match details
        self._last_refresh_ts: float = 0.0
        self._refresh_count: int = 0
        self._stats = {
            "ofac_entries": 0,
            "eu_entries": 0,
            "un_entries": 0,
            "total_entries": 0,
            "entity_matches": 0,
            "last_refresh": None,
        }

    async def refresh(self):
        """Download and parse all sanctions lists."""
        httpx = _get_httpx()
        if not httpx:
            return

        now = time.time()
        if now - self._last_refresh_ts < REFRESH_INTERVAL:
            return

        logger.info("[Sanctions] Refreshing sanctions lists...")
        new_entries: list[SanctionEntry] = []

        # ── OFAC SDN List ──
        try:
            ofac_entries = await self._download_ofac(httpx)
            new_entries.extend(ofac_entries)
            self._stats["ofac_entries"] = len(ofac_entries)
            logger.info("[Sanctions] OFAC SDN: %d entries", len(ofac_entries))
        except Exception as e:
            logger.warning("[Sanctions] OFAC download failed: %s", e)

        # ── EU Sanctions ──
        try:
            eu_entries = await self._download_eu(httpx)
            new_entries.extend(eu_entries)
            self._stats["eu_entries"] = len(eu_entries)
            logger.info("[Sanctions] EU: %d entries", len(eu_entries))
        except Exception as e:
            logger.warning("[Sanctions] EU download failed: %s", e)

        # ── UN Sanctions ──
        try:
            un_entries = await self._download_un(httpx)
            new_entries.extend(un_entries)
            self._stats["un_entries"] = len(un_entries)
            logger.info("[Sanctions] UN: %d entries", len(un_entries))
        except Exception as e:
            logger.warning("[Sanctions] UN download failed: %s", e)

        self._entries = new_entries
        self._stats["total_entries"] = len(new_entries)

        # Build name index
        self._by_name.clear()
        for entry in new_entries:
            key = _normalize_name(entry.name)
            self._by_name.setdefault(key, []).append(entry)
            for alias in entry.aliases:
                alias_key = _normalize_name(alias)
                if alias_key:
                    self._by_name.setdefault(alias_key, []).append(entry)

        self._last_refresh_ts = now
        self._refresh_count += 1
        self._stats["last_refresh"] = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

        logger.info("[Sanctions] Refresh complete: %d total entries, %d unique names",
                    len(new_entries), len(self._by_name))

    async def _download_ofac(self, httpx) -> list[SanctionEntry]:
        """Download and parse OFAC SDN CSV."""
        entries = []
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(OFAC_SDN_URL)
            if resp.status_code != 200:
                logger.warning("[Sanctions] OFAC SDN returned %d", resp.status_code)
                return entries

            text = resp.text
            reader = csv.reader(io.StringIO(text))

            for row in reader:
                if len(row) < 12:
                    continue

                uid = row[0].strip()
                name = row[1].strip()
                entity_type_raw = row[2].strip().lower()
                program = row[3].strip()
                remarks = row[11].strip() if len(row) > 11 else ""

                if not name:
                    continue

                if "individual" in entity_type_raw:
                    entity_type = "individual"
                elif "vessel" in entity_type_raw:
                    entity_type = "vessel"
                elif "aircraft" in entity_type_raw:
                    entity_type = "aircraft"
                else:
                    entity_type = "entity"

                # Extract aliases from remarks
                aliases = []
                alias_match = re.findall(r'a\.k\.a\.\s*["\']?([^;"\']+)', remarks, re.I)
                aliases.extend(a.strip() for a in alias_match if a.strip())

                # Extract ID numbers (MMSI, IMO, passport, etc.)
                id_numbers = []
                id_match = re.findall(
                    r'(?:MMSI|IMO|Passport|ID)\s*(?:No\.?\s*)?[:=]?\s*(\S+)',
                    remarks, re.I
                )
                id_numbers.extend(id_match)

                entries.append(SanctionEntry(
                    name=name,
                    entity_type=entity_type,
                    source="OFAC",
                    program=program,
                    aliases=aliases,
                    id_numbers=id_numbers,
                    remarks=remarks[:500],
                ))

        return entries

    async def _download_eu(self, httpx) -> list[SanctionEntry]:
        """Download and parse EU Consolidated Sanctions XML."""
        entries = []
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(EU_SANCTIONS_URL)
            if resp.status_code != 200:
                logger.warning("[Sanctions] EU returned %d", resp.status_code)
                return entries

            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError as e:
                logger.warning("[Sanctions] EU XML parse error: %s", e)
                return entries

            # EU XML uses namespaces
            ns = {"": root.tag.split("}")[0] + "}" if "}" in root.tag else ""}
            ns_prefix = ns.get("", "")

            for entity_elem in root.iter():
                tag_name = entity_elem.tag.split("}")[-1] if "}" in entity_elem.tag else entity_elem.tag

                if tag_name not in ("sanctionEntity", "SubjectType"):
                    continue

                # Try to extract name
                name_parts = []
                for name_elem in entity_elem.iter():
                    ntag = name_elem.tag.split("}")[-1] if "}" in name_elem.tag else name_elem.tag
                    if ntag in ("wholeName", "lastName", "firstName", "name"):
                        text = (name_elem.text or "").strip()
                        if text:
                            name_parts.append(text)

                if not name_parts:
                    continue

                name = " ".join(name_parts[:3])

                # Determine type
                entity_type = "entity"
                for child in entity_elem.iter():
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag == "subjectType":
                        type_text = (child.text or "").lower()
                        if "person" in type_text:
                            entity_type = "individual"
                        elif "enterprise" in type_text or "entity" in type_text:
                            entity_type = "entity"

                entries.append(SanctionEntry(
                    name=name,
                    entity_type=entity_type,
                    source="EU",
                ))

        return entries

    async def _download_un(self, httpx) -> list[SanctionEntry]:
        """Download and parse UN Security Council Consolidated List XML."""
        entries = []
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(UN_SANCTIONS_URL)
            if resp.status_code != 200:
                logger.warning("[Sanctions] UN returned %d", resp.status_code)
                return entries

            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError as e:
                logger.warning("[Sanctions] UN XML parse error: %s", e)
                return entries

            for individual in root.iter("INDIVIDUAL"):
                first = ""
                second = ""
                for child in individual:
                    if child.tag == "FIRST_NAME":
                        first = (child.text or "").strip()
                    elif child.tag == "SECOND_NAME":
                        second = (child.text or "").strip()

                name = f"{first} {second}".strip()
                if not name:
                    continue

                # Get aliases
                aliases = []
                for alias_elem in individual.iter("ALIAS"):
                    for child in alias_elem:
                        if child.tag == "ALIAS_NAME":
                            alias_text = (child.text or "").strip()
                            if alias_text:
                                aliases.append(alias_text)

                # Get nationality
                nationality = ""
                for nat_elem in individual.iter("NATIONALITY"):
                    for child in nat_elem:
                        if child.tag == "VALUE":
                            nationality = (child.text or "").strip()

                entries.append(SanctionEntry(
                    name=name,
                    entity_type="individual",
                    source="UN",
                    aliases=aliases[:10],
                    nationality=nationality,
                ))

            # Also parse ENTITY entries
            for entity in root.iter("ENTITY"):
                name = ""
                for child in entity:
                    if child.tag == "FIRST_NAME":
                        name = (child.text or "").strip()

                if not name:
                    continue

                aliases = []
                for alias_elem in entity.iter("ALIAS"):
                    for child in alias_elem:
                        if child.tag == "ALIAS_NAME":
                            alias_text = (child.text or "").strip()
                            if alias_text:
                                aliases.append(alias_text)

                entries.append(SanctionEntry(
                    name=name,
                    entity_type="entity",
                    source="UN",
                    aliases=aliases[:10],
                ))

        return entries

    def cross_reference_entities(self, entity_names: list[str]) -> list[dict]:
        """Cross-reference a list of entity names against sanctions lists.

        Args:
            entity_names: List of entity names from EntityGraph.

        Returns:
            List of match dicts: {entity, sanctioned_name, source, program, score}
        """
        if not self._entries:
            return []

        new_matches: list[dict] = []

        for entity_name in entity_names:
            if entity_name in self._entity_matches:
                continue  # Already matched

            normalized = _normalize_name(entity_name)
            if len(normalized) < 3:
                continue  # Too short to match reliably

            best_matches: list[dict] = []

            # Exact normalized match
            if normalized in self._by_name:
                for entry in self._by_name[normalized]:
                    best_matches.append({
                        "entity": entity_name,
                        "sanctioned_name": entry.name,
                        "source": entry.source,
                        "program": entry.program,
                        "entity_type": entry.entity_type,
                        "score": 1.0,
                        "match_type": "exact",
                    })

            # Fuzzy match (only for entities not already exactly matched)
            if not best_matches:
                entity_tokens = set(normalized.split())
                if len(entity_tokens) < 2:
                    continue  # Single-word names generate too many false positives

                for sanctioned_name, entries in self._by_name.items():
                    sim = _name_similarity(entity_name, sanctioned_name)
                    if sim >= 0.70:
                        for entry in entries:
                            best_matches.append({
                                "entity": entity_name,
                                "sanctioned_name": entry.name,
                                "source": entry.source,
                                "program": entry.program,
                                "entity_type": entry.entity_type,
                                "score": round(sim, 3),
                                "match_type": "fuzzy",
                            })

            if best_matches:
                # Keep top 3 matches per entity
                best_matches.sort(key=lambda m: m["score"], reverse=True)
                self._entity_matches[entity_name] = best_matches[:3]
                new_matches.extend(best_matches[:3])

        self._stats["entity_matches"] = len(self._entity_matches)
        return new_matches

    def get_sanctions_digest(self) -> str:
        """Formatted sanctions intelligence for LLM context injection.

        Shows:
        1. Active sanctions matches against known entities
        2. Sanctions list statistics
        """
        if not self._entries:
            return ""

        lines = []

        if self._entity_matches:
            lines.append("▸ SANCTIONS CROSS-REFERENCE (OFAC + EU + UN)")
            lines.append(f"  Lists loaded: OFAC={self._stats['ofac_entries']}, "
                         f"EU={self._stats['eu_entries']}, UN={self._stats['un_entries']}")

            # Group matches by source
            by_source: dict[str, list[dict]] = {}
            for entity_name, matches in self._entity_matches.items():
                for m in matches:
                    by_source.setdefault(m["source"], []).append(m)

            flagged_count = len(self._entity_matches)
            lines.append(f"  ⚠ {flagged_count} entities flagged across intelligence data:")

            # Show top matches (limit to 10 to not overwhelm)
            shown = 0
            for entity_name, matches in sorted(
                self._entity_matches.items(),
                key=lambda x: max(m["score"] for m in x[1]),
                reverse=True,
            ):
                if shown >= 10:
                    remaining = flagged_count - shown
                    if remaining > 0:
                        lines.append(f"  ... and {remaining} more flagged entities")
                    break

                top_match = matches[0]
                score_pct = int(top_match["score"] * 100)
                program_str = f" [{top_match['program'][:30]}]" if top_match["program"] else ""
                lines.append(
                    f"  🔴 {entity_name} → {top_match['source']}{program_str} "
                    f"({score_pct}% match, {top_match['match_type']})"
                )
                shown += 1

            lines.append("")
        else:
            lines.append("▸ SANCTIONS: Lists loaded "
                         f"({self._stats['total_entries']} entries), "
                         "no entity matches detected")
            lines.append("")

        return "\n".join(lines)

    def get_match_signals(self) -> list[dict]:
        """Generate PatternAccumulator signals for newly discovered matches."""
        signals = []
        for entity_name, matches in self._entity_matches.items():
            top = matches[0]
            if top["score"] >= 0.85:
                signals.append({
                    "type": "sanctions_match",
                    "headline": (
                        f"SANCTIONS HIT: {entity_name} matches {top['source']} list "
                        f"({top['sanctioned_name']}, {top['program'] or 'no program'})"
                    ),
                    "region": "GLOBAL",
                    "domain": "SECURITY",
                    "salience": min(0.9, 0.6 + top["score"] * 0.3),
                    "data": top,
                })
        return signals

    def stats(self) -> dict:
        return {
            **self._stats,
            "refresh_count": self._refresh_count,
        }
