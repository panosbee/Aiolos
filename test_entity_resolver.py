"""P1 Entity Resolution — comprehensive test suite."""

from xdart.knowledge.entity_graph import EntityGraph, _jaro_winkler, _normalize_entity_name

g = EntityGraph()
r = g._resolver

# ── Token subset matching ──
assert r.resolve("Scholz", "PERSON") == "Olaf Scholz"
assert r.resolve("Lavrov", "PERSON") == "Sergei Lavrov"
assert r.resolve("Netanyahu") == "Benjamin Netanyahu"
assert r.resolve("Blinken", "PERSON") == "Antony Blinken"
assert r.resolve("Huang", "PERSON") == "Jensen Huang"
print("✓ Token subset matching works")

# ── Fuzzy matching ──
sim = _jaro_winkler("zelenski", "zelensky")
print(f"  zelenski vs zelensky Jaro-Winkler = {sim:.3f}")
assert sim >= 0.88, f"Expected >= 0.88, got {sim}"
print("✓ Fuzzy matching Jaro-Winkler works")

# ── Title stripping ──
assert r.resolve("PM Modi") == "Narendra Modi"
assert r.resolve("Chancellor Scholz") == "Olaf Scholz"
assert r.resolve("President Putin") == "Vladimir Putin"
assert r.resolve("CEO Altman") == "Sam Altman"
print("✓ Title stripping works")

# ── Cyrillic transliteration ──
assert r.resolve("Путин") == "Vladimir Putin"
assert r.resolve("Владимир Путин") == "Vladimir Putin"
assert r.resolve("Зеленський") == "Volodymyr Zelensky"
assert r.resolve("Лавров") == "Sergei Lavrov"
assert r.resolve("Медведев") == "Dmitry Medvedev"
print("✓ Cyrillic transliteration works")

# ── Diacritics normalization ──
assert r.resolve("Erdoğan") == "Recep Erdogan"
assert _normalize_entity_name("Erdoğan") == "erdogan"
assert _normalize_entity_name("Brasília") == "brasilia"
print("✓ Diacritics normalization works")

# ── Co-occurrence learning ──
entities = [("V Putin", "PERSON"), ("Vladimir Putin", "PERSON")]
r.learn_cooccurrence(entities)
r.learn_cooccurrence(entities)
r.learn_cooccurrence(entities)  # 3rd time triggers alias
learned = r.stats()["learned_aliases"]
print(f"  Learned {learned} alias(es) from co-occurrence")
assert learned >= 1, f"Expected >= 1 learned alias, got {learned}"
# Verify the learned alias works
assert r.resolve("V Putin") == "Vladimir Putin"
print("✓ Co-occurrence alias learning works")

# ── User's exact example entities ──
assert r.resolve("Elon Musk") == "Elon Musk"
assert r.resolve("Musk") == "Elon Musk"
assert r.resolve("Dario Amodei") == "Dario Amodei"
assert r.resolve("Amodei") == "Dario Amodei"
assert r.resolve("Sam Altman") == "Sam Altman"
assert r.resolve("Altman") == "Sam Altman"
print("✓ User example entities (Musk, Amodei, Altman) resolve correctly")

# ── Unknown entities pass through ──
assert r.resolve("RandomUnknownPerson") == "RandomUnknownPerson"
assert r.resolve("Xyzzy Corp") == "Xyzzy Corp"
print("✓ Unknown entities pass through unchanged")

# ── New entities: strategic locations ──
assert r.resolve("Hormuz") == "Strait of Hormuz"
assert r.resolve("Suez") == "Suez Canal"
assert r.resolve("Gaza") == "Gaza"  # LOC type
print("✓ Strategic location resolution works")

# ── Stats ──
stats = r.stats()
print(f"\nResolver Stats:")
print(f"  Resolved total: {stats['resolved_total']}")
print(f"  Fuzzy resolved: {stats['fuzzy_resolved']}")
print(f"  Learned aliases: {stats['learned_aliases']}")
print(f"  Cache size: {stats['cache_size']}")
print(f"  Normalized index: {stats['normalized_index_size']}")

print("\n" + "=" * 50)
print("ALL P1 ENTITY RESOLUTION TESTS PASSED")
print("=" * 50)
