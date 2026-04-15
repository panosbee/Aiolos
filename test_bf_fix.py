"""Quick test for BFE tag post-processor + sandbox auto-deploy fixes."""
import re
import inspect

print("=" * 60)
print("TEST 1: BFE Tag Regex Pattern")
print("=" * 60)

bf_pattern = re.compile(
    r'<BAYESIAN_FUZZY_ENGINE\s+((?:[^">/]|"[^"]*")*)\s*/?>',
    re.IGNORECASE | re.DOTALL,
)

tests = [
    '<BAYESIAN_FUZZY_ENGINE domain="geopolitical_escalation" variables="us_iran_tension, hormuz_closure, oil_price" target="china_strategic_gain" />',
    '<BAYESIAN_FUZZY_ENGINE domain="financial_stress" />',
    "Normal text without any tags.",
    'Some text <BAYESIAN_FUZZY_ENGINE domain="test" /> more text after',
]

for i, txt in enumerate(tests):
    matches = list(bf_pattern.finditer(txt))
    if matches:
        for m in matches:
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            print(f"  Test {i+1}: MATCHED -> domain={attrs.get('domain', '?')}")
    else:
        print(f"  Test {i+1}: no match {'(expected)' if 'Normal' in txt else '(UNEXPECTED!)'}")

print()
print("=" * 60)
print("TEST 2: Import Checks")
print("=" * 60)

from xdart.core import XDARTFramework
print("  XDARTFramework import: OK")

from xdart.phases.logic_sandbox import LogicSandbox
print("  LogicSandbox import: OK")

# Check auto_deploy parameter
sig = inspect.signature(LogicSandbox.auto_analyze)
params = list(sig.parameters.keys())
print(f"  auto_analyze params: {params}")
assert "auto_deploy" in params, "MISSING auto_deploy parameter!"
print("  auto_deploy param: PRESENT")

# Check deploy_pending_proposals
assert hasattr(LogicSandbox, "deploy_pending_proposals"), "MISSING!"
print("  deploy_pending_proposals: EXISTS")

print()
print("=" * 60)
print("TEST 3: _process_bf_directives exists on XDARTFramework")
print("=" * 60)
assert hasattr(XDARTFramework, "_process_bf_directives"), "MISSING _process_bf_directives!"
print("  _process_bf_directives: EXISTS")

print()
print("=" * 60)
print("TEST 4: Fake BF text cleanup regex")
print("=" * 60)
fake = "*Θα τρέξει η μηχανή και θα δώσει ποσοτικοποιημένη εκτίμηση για το πόσο κερδίζει η Κίνα.*"
cleaned = re.sub(r"\*Θα τρέξει η μηχανή[^*]*\*", "", fake)
print(f"  Original: {fake[:60]}...")
print(f"  Cleaned:  '{cleaned.strip()}'")
assert not cleaned.strip(), "Should be empty after stripping!"
print("  Fake text stripped: YES")

print()
print("=" * 60)
print("TEST 5: System prompt BFE anti-simulation text")
print("=" * 60)
# Read core.py source to verify the prompt changes
import pathlib
core_src = pathlib.Path("xdart/core.py").read_text(encoding="utf-8")
checks = [
    "Do NOT write <BAYESIAN_FUZZY_ENGINE> XML tags in your response",
    "The engine runs AUTOMATICALLY",
    "NEVER simulate BF output",
    "<BAYESIAN_FUZZY_ENGINE> XML tags",
]
for check in checks:
    found = check in core_src
    print(f"  '{check[:50]}...': {'FOUND' if found else 'MISSING!'}")
    assert found, f"Missing: {check}"

print()
print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
