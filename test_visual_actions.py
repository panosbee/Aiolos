"""Test suite for Visual Action system — execute_visual_action + _process_visual_directives."""
import json
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))


def test_execute_visual_action():
    """Test VisionIntegration.execute_visual_action() for all 5 action types."""
    # Patch heavy imports and create a minimal VisionIntegration
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
        from xdart.vision.integration import VisionIntegration, VISUAL_VOCAB_PATH

    # Use a temp dir for file persistence
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_vocab = Path(tmpdir) / "visual_vocabulary.json"
        tmp_registry = Path(tmpdir) / "face_name_registry.json"
        tmp_journal = Path(tmpdir) / "visual_memory_journal.jsonl"

        # Patch file paths
        with patch("xdart.vision.integration.VISUAL_VOCAB_PATH", tmp_vocab), \
             patch("xdart.vision.integration.FACE_REGISTRY_PATH", tmp_registry), \
             patch("xdart.vision.integration.VISUAL_JOURNAL_PATH", tmp_journal):

            vi = VisionIntegration.__new__(VisionIntegration)
            # Minimal init
            vi._face_name_registry = {}
            vi._visual_vocabulary = {"objects": {}, "notes": []}
            vi._identity_last_seen = {}
            vi._identity_sighting_count = {}
            vi._stats = {"journal_entries": 0}
            vi._journal_lock = __import__("threading").Lock()
            vi.episodic_memory = None  # No episodic for test

            passed = 0
            failed = 0

            # 1. register_face
            result = vi.execute_visual_action("register_face", {"face_id": "test-uuid-1234", "name": "TestUser"})
            if result["success"] and "TestUser" in result["description"]:
                print("  ✓ register_face — OK")
                passed += 1
            else:
                print(f"  ✗ register_face — FAIL: {result}")
                failed += 1

            # Verify registry was updated
            if vi._face_name_registry.get("test-uuid-1234") == "TestUser":
                print("  ✓ register_face persisted in registry — OK")
                passed += 1
            else:
                print(f"  ✗ register_face persisted — FAIL: {vi._face_name_registry}")
                failed += 1

            # 2. rename_face
            result = vi.execute_visual_action("rename_face", {"old_name": "TestUser", "new_name": "Πάνος"})
            if result["success"] and "Πάνος" in result["description"]:
                print("  ✓ rename_face — OK")
                passed += 1
            else:
                print(f"  ✗ rename_face — FAIL: {result}")
                failed += 1

            if vi._face_name_registry.get("test-uuid-1234") == "Πάνος":
                print("  ✓ rename_face updated registry — OK")
                passed += 1
            else:
                print(f"  ✗ rename_face updated — FAIL: {vi._face_name_registry}")
                failed += 1

            # 3. label_object
            result = vi.execute_visual_action("label_object", {
                "object_type": "tv", "label": "Samsung TV", "context": "σαλόνι"
            })
            if result["success"] and "Samsung" in result["description"]:
                print("  ✓ label_object — OK")
                passed += 1
            else:
                print(f"  ✗ label_object — FAIL: {result}")
                failed += 1

            if "tv" in vi._visual_vocabulary["objects"]:
                print("  ✓ label_object stored in vocabulary — OK")
                passed += 1
            else:
                print(f"  ✗ label_object stored — FAIL")
                failed += 1

            # 4. store_note
            result = vi.execute_visual_action("store_note", {
                "note": "Ο Πάνος φοράει πάντα γυαλιά", "category": "pattern"
            })
            if result["success"] and "pattern" in result["description"]:
                print("  ✓ store_note — OK")
                passed += 1
            else:
                print(f"  ✗ store_note — FAIL: {result}")
                failed += 1

            if len(vi._visual_vocabulary["notes"]) == 1:
                print("  ✓ store_note appended to notes — OK")
                passed += 1
            else:
                print(f"  ✗ store_note appended — FAIL: {len(vi._visual_vocabulary['notes'])} notes")
                failed += 1

            # 5. forget_face (by name)
            result = vi.execute_visual_action("forget_face", {"name": "Πάνος"})
            if result["success"] and "Πάνος" in result["description"]:
                print("  ✓ forget_face — OK")
                passed += 1
            else:
                print(f"  ✗ forget_face — FAIL: {result}")
                failed += 1

            if "test-uuid-1234" not in vi._face_name_registry:
                print("  ✓ forget_face removed from registry — OK")
                passed += 1
            else:
                print(f"  ✗ forget_face removed — FAIL: {vi._face_name_registry}")
                failed += 1

            # 6. Error cases
            result = vi.execute_visual_action("register_face", {"face_id": "", "name": ""})
            if not result["success"]:
                print("  ✓ register_face (empty params) — correctly rejected")
                passed += 1
            else:
                print(f"  ✗ register_face (empty params) — should have failed")
                failed += 1

            result = vi.execute_visual_action("unknown_action", {})
            if not result["success"] and "Άγνωστη" in result["description"]:
                print("  ✓ unknown_action — correctly rejected")
                passed += 1
            else:
                print(f"  ✗ unknown_action — should have failed")
                failed += 1

    return passed, failed


def test_process_visual_directives():
    """Test _process_visual_directives regex parsing."""
    import re

    # Simulate the regex from core.py
    pattern = re.compile(
        r'<VISUAL_ACTION\s+((?:[^">/]|"[^"]*")*)\s*/?>',
        re.IGNORECASE | re.DOTALL,
    )

    passed = 0
    failed = 0

    # Test 1: Single directive
    text = 'Γεια σου! <VISUAL_ACTION action="register_face" face_id="abc-123" name="Πάνος" /> Χαίρομαι!'
    matches = list(pattern.finditer(text))
    if len(matches) == 1:
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', matches[0].group(1)))
        if attrs.get("action") == "register_face" and attrs.get("name") == "Πάνος":
            print("  ✓ Single directive parsed — OK")
            passed += 1
        else:
            print(f"  ✗ Single directive attrs — FAIL: {attrs}")
            failed += 1
    else:
        print(f"  ✗ Single directive — FAIL: {len(matches)} matches")
        failed += 1

    # Test 2: Multiple directives
    text = (
        'Ας δούμε...\n'
        '<VISUAL_ACTION action="label_object" object_type="laptop" label="MacBook Pro" context="γραφείο" />\n'
        '<VISUAL_ACTION action="store_note" note="Laptop πάντα ανοιχτό" category="pattern" />\n'
        'Τέλεια!'
    )
    matches = list(pattern.finditer(text))
    if len(matches) == 2:
        print("  ✓ Multiple directives parsed — OK")
        passed += 1
    else:
        print(f"  ✗ Multiple directives — FAIL: {len(matches)} matches")
        failed += 1

    # Test 3: No directives
    text = "Απλό μήνυμα χωρίς directives."
    matches = list(pattern.finditer(text))
    if len(matches) == 0:
        print("  ✓ No directives — OK")
        passed += 1
    else:
        print(f"  ✗ No directives — FAIL: {len(matches)} matches")
        failed += 1

    # Test 4: Directive stripping
    text = 'Γεια! <VISUAL_ACTION action="register_face" face_id="x" name="Y" /> Πώς είσαι;'
    clean = pattern.sub("", text).strip()
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    if "<VISUAL_ACTION" not in clean and "Γεια!" in clean and "Πώς είσαι;" in clean:
        print("  ✓ Directive stripping — OK")
        passed += 1
    else:
        print(f"  ✗ Directive stripping — FAIL: '{clean}'")
        failed += 1

    return passed, failed


if __name__ == "__main__":
    print("\n=== Test 1: execute_visual_action ===")
    p1, f1 = test_execute_visual_action()

    print("\n=== Test 2: _process_visual_directives regex ===")
    p2, f2 = test_process_visual_directives()

    total_passed = p1 + p2
    total_failed = f1 + f2
    print(f"\n{'='*40}")
    print(f"TOTAL: {total_passed} passed, {total_failed} failed")

    if total_failed > 0:
        sys.exit(1)
    else:
        print("ALL TESTS PASSED ✓")
        sys.exit(0)
