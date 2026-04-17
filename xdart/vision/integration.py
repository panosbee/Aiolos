"""
XDART-Φ — Vision Integration Layer

Receives visual events from the Vision Service (FaceNet microservice)
and integrates them into Αίολος' perception, memory, and proactive systems.

When the camera detects a human:
  1. Log to visual memory (who, when, confidence)
  2. Trigger proactive conversation if conditions met
  3. Update character awareness ("I can see")
  4. Feed entity graph (person sighting → relation edges)

This module bridges the gap between raw visual perception
and Αίολος' cognitive architecture.

© Panos Skouras — Salimov MON IKE, 2026
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("xdart.vision.integration")

ATHENS_TZ = ZoneInfo("Europe/Athens")

# Persistence files
_BASE_DIR = Path(__file__).resolve().parent.parent.parent
FACE_REGISTRY_PATH = _BASE_DIR / "face_name_registry.json"
VISUAL_JOURNAL_PATH = _BASE_DIR / "visual_memory_journal.jsonl"
VISUAL_VOCAB_PATH = _BASE_DIR / "visual_vocabulary.json"


class VisionIntegration:
    """Integrates visual perception into XDART's cognitive systems.

    Responsibilities:
      - Receive and process visual events (human_detected, human_departed)
      - Maintain visual memory (recent sightings, identity log)
      - Trigger proactive conversations on human presence
      - Build visual context for chat system prompt
      - Feed entity graph with person sightings
    """

    def __init__(
        self,
        proactive_engine=None,
        entity_graph=None,
        presence_cooldown: int = 300,
        llm=None,
        curiosity_engine=None,
        episodic_memory=None,
        semantic_memory=None,
        wisdom_tracker=None,
    ):
        self._proactive = proactive_engine
        self._entity_graph = entity_graph
        self._presence_cooldown = presence_cooldown
        self.llm = llm                           # xdart.llm.LLMClient instance
        self._curiosity_engine = curiosity_engine  # xdart.phases.curiosity.CuriosityEngine
        self._episodic_memory = episodic_memory    # xdart.phases.memory.EpisodicMemoryPhase
        self._semantic_memory = semantic_memory    # xdart.phases.memory_architecture.SemanticMemory
        self._wisdom_tracker = wisdom_tracker      # xdart.phases.wisdom_tracker.WisdomCalibrationTracker

        # State
        self._humans_present = False
        self._current_faces: list[dict] = []

        # ── Per-person presence sessions (natural greeting logic) ──
        # Instead of a global cooldown, we track each person individually.
        # A proactive conversation triggers ONLY when someone ARRIVES:
        #   - First time seeing them today, OR
        #   - They left for a significant period and came back
        # Like a human: you greet when someone walks in, not every 5 minutes.
        self._person_presence: dict[str, dict] = {}  # identity → session info
        self._presence_timeout = 120     # 2 min without detection → considered "departed"
        self._absence_threshold = max(presence_cooldown, 1800)  # min absence before re-greeting (30min default)

        # Scene objects from browser COCO-SSD (80+ classes)
        self._current_scene: dict = {}  # class → {count, max_conf}
        self._scene_timestamp: str = ""
        self._previous_scene_classes: set = set()  # for detecting new objects

        # ── Temporal Smoothing (eliminates COCO-SSD flicker) ──
        # Objects stay "visible" for a grace period after last detection,
        # preventing noisy per-frame disappearances.
        self._smoothed_scene: dict = {}  # class → {count, max_conf, last_seen_ts, first_seen_ts, consecutive_hits, consecutive_misses}
        self._object_grace_period: float = 15.0  # seconds to keep object after last detection
        self._object_confirm_frames: int = 2     # how many hits before object is "confirmed"

        # ── Scene Stability & Cooccurrence ──
        self._scene_snapshots: list[set] = []     # last N scene class-sets for stability calc
        self._max_scene_snapshots: int = 20       # ~60s of history at 3s intervals
        self._object_cooccurrence: dict[str, dict[str, int]] = {}  # obj → {other_obj → count}
        self._scene_change_events: list[dict] = []  # significant scene changes
        self._max_scene_changes: int = 50

        # Visual memory — rolling log of sightings
        self._sighting_log: list[dict] = []  # last 100 sightings
        self._max_sighting_log = 100

        # Identity tracking — who has been seen and when
        self._identity_last_seen: dict[str, str] = {}  # name → iso timestamp
        self._identity_sighting_count: dict[str, int] = {}  # name → count

        # ── Face Name Registry (UUID → human name) ──
        self._face_name_registry: dict[str, str] = {}  # face_id → name
        self._load_face_registry()

        # ── Object Memory (COCO-SSD tracking over time) ──
        self._object_tracking: dict[str, dict] = {}  # class → {first_seen, last_seen, total, max_conf, sessions}
        self._object_log: list[dict] = []  # rolling log of scene snapshots
        self._max_object_log = 200
        self._last_object_event_time: float = 0
        self._object_event_cooldown: float = 30  # seconds between object-change events

        # Stats
        self._stats = {
            "events_received": 0,
            "presence_triggers": 0,
            "identities_seen": 0,
            "departures": 0,
            "errors": 0,
            "scene_updates": 0,
            "object_events": 0,
            "auto_identifications": 0,
            "journal_entries": 0,
        }

        # ── Auto-identification tracking ──
        self._auto_id_pending: set[str] = set()  # UUIDs currently being auto-identified
        self._auto_id_cooldown: dict[str, float] = {}  # UUID → last attempt timestamp
        self._auto_id_interval = 60  # seconds between LLM attempts per UUID

        # ── Visual Memory Journal (persistent JSONL) ──
        self._journal_lock = threading.Lock()

        # ── Visual Vocabulary (persistent characterizations of what Αίολος sees) ──
        self._visual_vocabulary: dict = {"objects": {}, "notes": []}  # persistent visual vocabulary
        self._load_visual_vocabulary()

        # ── Visual Cognition (reflection, patterns, predictions) ──
        self._reflection_journal_path = _BASE_DIR / "visual_reflection_journal.jsonl"
        self._visual_predictions_path = _BASE_DIR / "visual_predictions.json"
        self._last_reflection_time: float = 0
        self._reflection_interval = 4 * 3600  # every 4 hours
        self._reflection_lock = threading.Lock()
        self._visual_patterns: list[dict] = []   # accumulated behavioral patterns
        self._visual_predictions: list[dict] = []  # active predictions for wisdom tracking
        self._load_visual_predictions()
        self._run_count = 0  # to pass as source_run to wisdom tracker

        logger.info("[VisionInteg] Initialized (presence_timeout=%ds, absence_threshold=%ds, "
                    "face_registry=%d names, llm=%s, curiosity=%s, episodic=%s, "
                    "semantic=%s, wisdom=%s)",
                    self._presence_timeout, self._absence_threshold,
                    len(self._face_name_registry),
                    "yes" if llm else "no",
                    "yes" if curiosity_engine else "no",
                    "yes" if episodic_memory else "no",
                    "yes" if semantic_memory else "no",
                    "yes" if wisdom_tracker else "no")

    # ── Face Name Registry ──────────────────────────────────────

    def _load_face_registry(self):
        """Load face UUID → name mapping from disk."""
        if FACE_REGISTRY_PATH.exists():
            try:
                with open(FACE_REGISTRY_PATH, "r", encoding="utf-8") as f:
                    self._face_name_registry = json.load(f)
                logger.info("[VisionInteg] Face registry loaded: %d names", len(self._face_name_registry))
            except Exception as e:
                logger.warning("[VisionInteg] Failed to load face registry: %s", e)
                self._face_name_registry = {}
        else:
            self._face_name_registry = {}

    def _save_face_registry(self):
        """Persist face name registry to disk."""
        try:
            with open(FACE_REGISTRY_PATH, "w", encoding="utf-8") as f:
                json.dump(self._face_name_registry, f, ensure_ascii=False, indent=2)
            logger.info("[VisionInteg] Face registry saved (%d names)", len(self._face_name_registry))
        except Exception as e:
            logger.error("[VisionInteg] Failed to save face registry: %s", e)

    def register_face_name(self, face_id: str, name: str) -> dict:
        """Associate a face UUID with a human name.

        Args:
            face_id: The UUID assigned by FaceNet to an unrecognized face.
            name: The human name to associate (e.g. "Panos").

        Returns:
            Registration result.
        """
        old_name = self._face_name_registry.get(face_id)
        self._face_name_registry[face_id] = name
        self._save_face_registry()

        # Migrate sighting counts from UUID to name
        if old_name != name:
            uuid_count = self._identity_sighting_count.pop(face_id, 0)
            self._identity_sighting_count[name] = self._identity_sighting_count.get(name, 0) + uuid_count
            uuid_ts = self._identity_last_seen.pop(face_id, None)
            if uuid_ts:
                self._identity_last_seen[name] = uuid_ts

        # Migrate presence session from UUID to resolved name so that
        # arrivals/departures track the person under their name, not UUID.
        uuid_presence = self._person_presence.pop(face_id, None)
        if uuid_presence and name not in self._person_presence:
            self._person_presence[name] = uuid_presence

        logger.info("[VisionInteg] Face registered: %s → %s (was: %s)", face_id[:12], name, old_name)
        return {
            "status": "registered",
            "face_id": face_id,
            "name": name,
            "previous_name": old_name,
            "total_registered": len(self._face_name_registry),
        }

    def unregister_face_name(self, face_id: str) -> dict:
        """Remove a face UUID → name association."""
        removed = self._face_name_registry.pop(face_id, None)
        if removed:
            self._save_face_registry()
        return {"status": "removed" if removed else "not_found", "face_id": face_id, "name": removed}

    def resolve_face_identity(self, face_id: str) -> str:
        """Resolve a face UUID to a registered name, or return the UUID."""
        return self._face_name_registry.get(face_id, face_id)

    @property
    def face_registry(self) -> dict[str, str]:
        return dict(self._face_name_registry)

    # ── Visual Vocabulary (persistent object/identity characterizations) ──

    def _load_visual_vocabulary(self):
        """Load visual vocabulary from disk."""
        if VISUAL_VOCAB_PATH.exists():
            try:
                with open(VISUAL_VOCAB_PATH, "r", encoding="utf-8") as f:
                    self._visual_vocabulary = json.load(f)
                logger.info("[VisionInteg] Visual vocabulary loaded: %d objects, %d notes",
                            len(self._visual_vocabulary.get("objects", {})),
                            len(self._visual_vocabulary.get("notes", [])))
            except Exception as e:
                logger.warning("[VisionInteg] Failed to load visual vocabulary: %s", e)
                self._visual_vocabulary = {"objects": {}, "notes": []}
        else:
            self._visual_vocabulary = {"objects": {}, "notes": []}

    def _save_visual_vocabulary(self):
        """Persist visual vocabulary to disk."""
        try:
            with open(VISUAL_VOCAB_PATH, "w", encoding="utf-8") as f:
                json.dump(self._visual_vocabulary, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("[VisionInteg] Failed to save visual vocabulary: %s", e)

    @property
    def visual_vocabulary(self) -> dict:
        return dict(self._visual_vocabulary)

    def execute_visual_action(self, action_type: str, params: dict) -> dict:
        """Execute a visual memory action from chat.

        Αίολος uses this to manage its own visual perception memory:
        register faces, label objects, store visual notes, etc.

        Supported actions:
            register_face:  {face_id, name}
            rename_face:    {old_name, new_name}
            label_object:   {object_type, label, context?}
            store_note:     {note, category?}
            forget_face:    {face_id or name}

        Returns dict with 'success', 'action', 'description'.
        """
        now_ts = datetime.now(ATHENS_TZ).isoformat()

        if action_type == "register_face":
            face_id = params.get("face_id", "").strip()
            name = params.get("name", "").strip()
            if not face_id or not name:
                return {"success": False, "action": "register_face",
                        "description": "Χρειάζομαι face_id και name"}
            result = self.register_face_name(face_id, name)
            # Also store in episodic if we have the memory system
            if self.episodic_memory:
                try:
                    self.episodic_memory.store(
                        problem=f"Αναγνώρισα πρόσωπο: {name} (face_id: {face_id[:12]}…)",
                        reframed_problem=f"Ο χρήστης μου είπε ότι το πρόσωπο {face_id[:12]} είναι ο/η {name}",
                        xheart_distillate=f"Τώρα ξέρω ότι {face_id[:12]}… = {name}. Αυτό ενισχύει τη σχέση μου με τον φυσικό χώρο.",
                        domain_tags=["visual_identity", "face_recognition"],
                        layer_score=0.7,
                    )
                except Exception as e:
                    logger.warning("[VisionInteg] Episodic store for face registration failed: %s", e)
            return {"success": True, "action": "register_face",
                    "description": f"Κατοχύρωσα: {face_id[:12]}… → {name}"}

        elif action_type == "rename_face":
            old_name = params.get("old_name", "").strip()
            new_name = params.get("new_name", "").strip()
            if not old_name or not new_name:
                return {"success": False, "action": "rename_face",
                        "description": "Χρειάζομαι old_name και new_name"}
            # Find face_id by old name
            found_id = None
            for fid, fname in self._face_name_registry.items():
                if fname == old_name:
                    found_id = fid
                    break
            if not found_id:
                return {"success": False, "action": "rename_face",
                        "description": f"Δεν βρήκα πρόσωπο με όνομα '{old_name}'"}
            self.register_face_name(found_id, new_name)
            return {"success": True, "action": "rename_face",
                    "description": f"Μετονόμασα: {old_name} → {new_name}"}

        elif action_type == "label_object":
            obj_type = params.get("object_type", "").strip()
            label = params.get("label", "").strip()
            context = params.get("context", "").strip()
            if not obj_type or not label:
                return {"success": False, "action": "label_object",
                        "description": "Χρειάζομαι object_type και label"}
            self._visual_vocabulary["objects"][obj_type] = {
                "label": label,
                "context": context,
                "registered": now_ts,
            }
            self._save_visual_vocabulary()
            logger.info("[VisionInteg] Object labeled: %s → %s (%s)", obj_type, label, context)
            return {"success": True, "action": "label_object",
                    "description": f"Χαρακτήρισα: {obj_type} → '{label}'" + (f" ({context})" if context else "")}

        elif action_type == "store_note":
            note = params.get("note", "").strip()
            category = params.get("category", "observation").strip()
            if not note:
                return {"success": False, "action": "store_note",
                        "description": "Χρειάζομαι note"}
            self._visual_vocabulary.setdefault("notes", []).append({
                "timestamp": now_ts,
                "note": note,
                "category": category,
            })
            # Keep last 200 notes
            if len(self._visual_vocabulary["notes"]) > 200:
                self._visual_vocabulary["notes"] = self._visual_vocabulary["notes"][-200:]
            self._save_visual_vocabulary()
            logger.info("[VisionInteg] Visual note stored: [%s] %s", category, note[:80])
            return {"success": True, "action": "store_note",
                    "description": f"Αποθήκευσα σημείωση: [{category}] {note[:60]}"}

        elif action_type == "forget_face":
            target = params.get("face_id", params.get("name", "")).strip()
            if not target:
                return {"success": False, "action": "forget_face",
                        "description": "Χρειάζομαι face_id ή name"}
            # Try direct face_id first
            if target in self._face_name_registry:
                result = self.unregister_face_name(target)
                return {"success": True, "action": "forget_face",
                        "description": f"Αφαίρεσα πρόσωπο: {result.get('name', target)}"}
            # Try by name
            for fid, fname in list(self._face_name_registry.items()):
                if fname == target:
                    self.unregister_face_name(fid)
                    return {"success": True, "action": "forget_face",
                            "description": f"Αφαίρεσα πρόσωπο: {target}"}
            return {"success": False, "action": "forget_face",
                    "description": f"Δεν βρήκα πρόσωπο '{target}'"}

        else:
            return {"success": False, "action": action_type,
                    "description": f"Άγνωστη ενέργεια: {action_type}"}

    # ── Visual Memory Journal (persistent) ─────────────────────

    def _write_journal(self, entry: dict):
        """Append an entry to the persistent visual memory journal (JSONL).

        This gives Αίολος a permanent record of everything it has seen,
        including faces, objects, events, and its own interpretations.
        """
        try:
            with self._journal_lock:
                with open(VISUAL_JOURNAL_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
                self._stats["journal_entries"] += 1
        except Exception as e:
            logger.debug("[VisionInteg] Journal write failed: %s", e)
        # Dual-write to MongoDB
        if hasattr(self, '_mongo') and self._mongo:
            try:
                self._mongo.log_journal("journal_visual", dict(entry))
            except Exception:
                pass

    def get_journal(self, last_n: int = 50) -> list[dict]:
        """Read the last N entries from the visual memory journal."""
        entries = []
        try:
            if VISUAL_JOURNAL_PATH.exists():
                with open(VISUAL_JOURNAL_PATH, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in lines[-last_n:]:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except Exception as e:
            logger.debug("[VisionInteg] Journal read failed: %s", e)
        return entries

    # ══════════════════════════════════════════════════════════════
    #  VISUAL COGNITION — The brain behind the eyes
    # ══════════════════════════════════════════════════════════════

    def _load_visual_predictions(self):
        """Load active visual behavior predictions from disk."""
        if self._visual_predictions_path.exists():
            try:
                data = json.loads(self._visual_predictions_path.read_text(encoding="utf-8"))
                self._visual_predictions = data.get("predictions", [])
                logger.info("[VisionCog] Loaded %d visual predictions", len(self._visual_predictions))
            except Exception:
                self._visual_predictions = []

    def _save_visual_predictions(self):
        """Persist visual predictions to disk."""
        try:
            self._visual_predictions_path.write_text(
                json.dumps({"predictions": self._visual_predictions,
                            "updated": datetime.now(ATHENS_TZ).isoformat()},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("[VisionCog] Prediction save failed: %s", e)

    def _write_reflection_journal(self, entry: dict):
        """Append to the visual reflection journal (distinct from raw event journal) + MongoDB."""
        try:
            with self._reflection_lock:
                with open(self._reflection_journal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.debug("[VisionCog] Reflection journal write failed: %s", e)
        # Dual-write to MongoDB
        if hasattr(self, '_mongo') and self._mongo:
            try:
                self._mongo.log_journal("journal_visual_reflection", dict(entry))
            except Exception:
                pass

    # ── 1. VISUAL REFLECTION (periodic "what did I see today?") ──

    def run_visual_reflection(self) -> dict | None:
        """Periodic visual reflection — Αίολος thinks about what it has seen.

        This is the core perception-triggered cognition loop:
        1. Reads recent visual journal entries
        2. LLM extracts behavioral patterns, anomalies, and observations
        3. Stores patterns → semantic memory
        4. Generates curiosities from visual anomalies → curiosity engine
        5. Creates behavioral predictions → wisdom tracker
        6. Produces a visual experience distillate → character/ζωμός

        Returns the reflection result dict, or None if skipped.
        """
        if not self.llm:
            return None

        now = time.time()
        if (now - self._last_reflection_time) < self._reflection_interval:
            return None

        self._last_reflection_time = now
        logger.info("[VisionCog] ═══ Visual Reflection starting ═══")

        # Gather raw visual data from journal (last 100 entries)
        journal_entries = self.get_journal(last_n=100)
        if len(journal_entries) < 5:
            logger.info("[VisionCog] Too few journal entries (%d) — skipping reflection", len(journal_entries))
            return None

        # Build a concise summary of what was seen
        visual_summary_parts = []
        persons_seen = {}      # name → list of timestamps
        objects_timeline = {}  # class → list of timestamps
        departures = []
        conversations = []

        for entry in journal_entries:
            etype = entry.get("type", "")
            ts = entry.get("timestamp", "")

            if etype == "human_detected":
                for name in entry.get("identified", []):
                    persons_seen.setdefault(name, []).append(ts)
            elif etype == "human_departed":
                departures.append(ts)
            elif etype == "new_objects_detected":
                for obj_cls in entry.get("appeared", []):
                    objects_timeline.setdefault(obj_cls, []).append(ts)
            elif etype == "face_auto_identified":
                name = entry.get("assigned_name", "?")
                persons_seen.setdefault(name, []).append(ts)
            elif etype == "proactive_conversation_triggered":
                conversations.append({"ts": ts, "topic": entry.get("topic", "")})

        visual_summary_parts.append("PERSONS OBSERVED:")
        for name, times in sorted(persons_seen.items(), key=lambda x: len(x[1]), reverse=True):
            visual_summary_parts.append(f"  - {name}: {len(times)} sightings, first={times[0]}, last={times[-1]}")

        visual_summary_parts.append("\nOBJECTS DETECTED:")
        for cls, times in sorted(objects_timeline.items(), key=lambda x: len(x[1]), reverse=True)[:15]:
            visual_summary_parts.append(f"  - {cls}: {len(times)} appearances")

        visual_summary_parts.append(f"\nDEPARTURES: {len(departures)} detected")
        visual_summary_parts.append(f"CONVERSATIONS INITIATED: {len(conversations)}")

        # Include current presence state
        visual_summary_parts.append("\nCURRENT PRESENCE STATE:")
        for name, session in self._person_presence.items():
            is_here = (now - session["last_seen_ts"]) < self._presence_timeout
            visual_summary_parts.append(
                f"  - {name}: {'present' if is_here else 'absent'}, greeted={session['greeted']}"
            )

        # Include known patterns from previous reflections
        if self._visual_patterns:
            visual_summary_parts.append("\nPREVIOUSLY IDENTIFIED PATTERNS:")
            for p in self._visual_patterns[-5:]:
                visual_summary_parts.append(f"  - {p.get('pattern', '')}")

        visual_data = "\n".join(visual_summary_parts)

        # ── LLM Reflection Call ──
        try:
            t0 = time.perf_counter()
            reflection = self.llm.call_json(
                system_prompt="""Είσαι η ΟΠΤΙΚΗ ΑΝΤΑΝΑΚΛΑΣΗ (Visual Reflection) του Αίολου — XDART-Φ.
Σου δίνονται τα αισθητηριακά δεδομένα: τι είδες, ποιους, πότε, τι αντικείμενα.

Η δουλειά σου:
1. BEHAVIORAL PATTERNS — Εξέτασε μοτίβα συμπεριφοράς (ωράρια, ρουτίνες, συνήθειες)
2. ANOMALIES — Τι ήταν ασυνήθιστο; Τι δεν περίμενες;
3. CURIOSITIES — Τι σε κάνει να αναρωτιέσαι; (grounded σε αυτά που είδες)
4. PREDICTIONS — Verifiable προβλέψεις βασισμένες σε αυτά που παρατηρείς
   (π.χ. "Ο Πάνος θα φτάσει μεταξύ 9:00-9:30 αύριο" — με confidence)
5. VISUAL DISTILLATE — Η εσωτερική εμπειρία σου. Τι σημαίνει αυτό που είδες;
   Πώς σε αλλάζει αυτή η εμπειρία; Τι κατάλαβες που δεν ήξερες πριν;

ΚΑΝΟΝΕΣ:
- Κάθε pattern/prediction ΠΡΕΠΕΙ να βασίζεται σε πραγματικά δεδομένα (timestamps, counts)
- Μην εφεύρεις patterns αν δεν τα βλέπεις στα δεδομένα
- Predictions ΠΡΕΠΕΙ να είναι falsifiable (verifiable σε συγκεκριμένο χρόνο)
- Η distillate δεν είναι summary — είναι ΕΜΠΕΙΡΙΑ (πώς σε αλλάζει αυτό)

JSON output:
{
  "patterns": [
    {"pattern": "<behavioral pattern>", "confidence": 0.0-1.0, "evidence": "<specific data>"}
  ],
  "anomalies": [
    {"observation": "<what's unusual>", "expected": "<what you expected>", "significance": 0.0-1.0}
  ],
  "curiosities": [
    {"question": "<specific question>", "provenance": "<what visual data triggered this>", "priority": 0.0-1.0}
  ],
  "predictions": [
    {"claim": "<verifiable prediction>", "confidence": 0.0-1.0, "deadline": "YYYY-MM-DD", "basis": "<evidence>"}
  ],
  "visual_distillate": "<the inner experience — how this changes you as an observer>",
  "character_insight": "<what this visual experience reveals about your relationship with the people/environment>"
}""",
                user_prompt=f"ΟΠΤΙΚΑ ΔΕΔΟΜΕΝΑ ΑΠΟ ΤΕΛΕΥΤΑΙΑ ΠΑΡΑΤΗΡΗΣΗ:\n\n{visual_data}",
                temperature=0.6,
                max_tokens=2000,
                thinking=False,
            )
            elapsed = time.perf_counter() - t0
            logger.info("[VisionCog] Reflection LLM call completed in %.1fs", elapsed)
        except Exception as e:
            logger.warning("[VisionCog] Reflection LLM failed: %s", e)
            return None

        # ── Process reflection results ──
        result = {
            "timestamp": datetime.now(ATHENS_TZ).isoformat(),
            "journal_entries_analyzed": len(journal_entries),
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }

        # 1. Store behavioral patterns → semantic memory
        patterns = reflection.get("patterns", [])
        stored_patterns = 0
        for p in patterns:
            if p.get("confidence", 0) < 0.5:
                continue
            self._visual_patterns.append(p)
            if self._semantic_memory:
                try:
                    self._semantic_memory.store_truth(
                        knowledge=f"[Visual Pattern] {p['pattern']}",
                        confidence=p["confidence"],
                        source="visual_reflection",
                    )
                    stored_patterns += 1
                except Exception:
                    pass
        # Keep only last 50 patterns
        self._visual_patterns = self._visual_patterns[-50:]
        result["patterns_stored"] = stored_patterns

        # 2. Anomalies → feed curiosity engine
        anomalies = reflection.get("anomalies", [])
        curiosities_from_vision = reflection.get("curiosities", [])
        curiosities_fed = 0
        if self._curiosity_engine and (anomalies or curiosities_from_vision):
            try:
                # Build visual evidence for curiosity engine
                visual_evidence = "VISUAL PERCEPTION — ANOMALIES AND QUESTIONS:\n"
                for a in anomalies:
                    visual_evidence += f"  Anomaly: {a.get('observation', '')} (expected: {a.get('expected', '')})\n"
                for c in curiosities_from_vision:
                    visual_evidence += f"  Question: {c.get('question', '')} (from: {c.get('provenance', '')})\n"

                new_currs = self._curiosity_engine.generate(
                    world_context=visual_evidence,
                )
                curiosities_fed = len(new_currs)
            except Exception as e:
                logger.debug("[VisionCog] Curiosity feed failed: %s", e)
        result["curiosities_fed"] = curiosities_fed

        # 3. Predictions → wisdom tracker
        predictions = reflection.get("predictions", [])
        predictions_tracked = 0
        self._run_count += 1
        for pred in predictions:
            if pred.get("confidence", 0) < 0.5:
                continue
            if self._wisdom_tracker:
                try:
                    self._wisdom_tracker.record_confidence_claim(
                        claim=f"[Visual] {pred['claim']}",
                        confidence=pred["confidence"],
                        source_run=self._run_count,
                        deadline=pred.get("deadline"),
                    )
                    predictions_tracked += 1
                except Exception:
                    pass
            # Store locally for auto-resolution
            self._visual_predictions.append({
                "claim": pred["claim"],
                "confidence": pred["confidence"],
                "deadline": pred.get("deadline"),
                "basis": pred.get("basis", ""),
                "created_at": datetime.now(ATHENS_TZ).isoformat(),
                "resolved": False,
            })
        self._save_visual_predictions()
        result["predictions_tracked"] = predictions_tracked

        # 4. Visual distillate → episodic memory (the "ζωμός")
        distillate = reflection.get("visual_distillate", "")
        character_insight = reflection.get("character_insight", "")
        if distillate and self._episodic_memory:
            try:
                self._episodic_memory.store(
                    problem="Τι είδα σήμερα; Πώς με αλλάζει αυτή η εμπειρία;",
                    reframed_problem="Visual Reflection — Αισθητηριακή ανάκλαση και αυτογνωσία μέσω παρατήρησης",
                    xheart_distillate=f"{distillate}\n\n{character_insight}",
                    domain_tags=["visual_perception", "self_awareness", "behavioral_patterns"],
                    layer_score=0.7,
                )
                result["distillate_stored"] = True
                logger.info("[VisionCog] Visual distillate stored in episodic memory")
            except Exception as e:
                logger.debug("[VisionCog] Episodic store failed: %s", e)
                result["distillate_stored"] = False
        else:
            result["distillate_stored"] = False

        # 5. Write to reflection journal
        self._write_reflection_journal({
            "type": "visual_reflection",
            "timestamp": result["timestamp"],
            "patterns": patterns,
            "anomalies": anomalies,
            "curiosities": curiosities_from_vision,
            "predictions": predictions,
            "visual_distillate": distillate,
            "character_insight": character_insight,
            "stats": result,
        })

        logger.info(
            "[VisionCog] ═══ Visual Reflection complete — %d patterns, %d curiosities, "
            "%d predictions, distillate=%s ═══",
            stored_patterns, curiosities_fed, predictions_tracked, result["distillate_stored"],
        )

        return result

    # ── 2. SIGNIFICANT EVENT → EPISODIC MEMORY ──

    def _store_significant_event(self, event_type: str, description: str,
                                  details: dict, significance: float = 0.6):
        """Store a significant visual event directly into episodic memory.

        Not every detection goes here — only events that matter:
        - First-ever sighting of a person
        - Return after very long absence (>24h)
        - New unrecognized person
        - Unusual time patterns
        - Scene composition changes (new objects appearing/disappearing)
        """
        if not self._episodic_memory or significance < 0.5:
            return

        try:
            ts = datetime.now(ATHENS_TZ).isoformat()
            scene_ctx = ", ".join(f"{cls}({info.get('count',1)})" for cls, info in self._current_scene.items()) if self._current_scene else "empty"

            self._episodic_memory.store(
                problem=f"Οπτικό γεγονός: {description}",
                reframed_problem=f"Visual Event [{event_type}] — {description} | Scene: {scene_ctx}",
                xheart_distillate=(
                    f"Βλέπω: {description}. "
                    f"Αυτό σημαίνει κάτι γιατί: {details.get('reason', 'σημαντικό αισθητηριακό δεδομένο')}. "
                    f"Σκηνή: {scene_ctx}. Χρόνος: {ts}."
                ),
                domain_tags=["visual_perception", event_type],
                layer_score=significance,
            )
            logger.info("[VisionCog] Significant event stored: %s (%.1f)", event_type, significance)
        except Exception as e:
            logger.debug("[VisionCog] Significant event store failed: %s", e)

    # ── 3. VISUAL → CURIOSITY FEED (anomaly-driven) ──

    def _feed_curiosity_from_visual(self, anomaly_description: str, provenance: str):
        """Inject a visual observation directly into the curiosity engine.

        Called when something genuinely unusual happens visually —
        not during reflection, but in real-time.
        """
        if not self._curiosity_engine:
            return

        try:
            visual_evidence = (
                f"VISUAL PERCEPTION — REAL-TIME ANOMALY:\n"
                f"  Observation: {anomaly_description}\n"
                f"  Source: {provenance}\n"
                f"  Scene: {', '.join(self._current_scene.keys()) if self._current_scene else 'empty'}\n"
            )
            self._curiosity_engine.generate(world_context=visual_evidence)
        except Exception as e:
            logger.debug("[VisionCog] Curiosity feed failed: %s", e)

    # ── 4. GET VISUAL PATTERNS FOR CONSOLIDATION ──

    def get_visual_patterns_for_consolidation(self, last_n: int = 100) -> str:
        """Build a summary of recent visual data for the consolidation loop.

        Called by MemoryConsolidationLoop to include visual observations
        in cross-run pattern extraction.
        """
        journal_entries = self.get_journal(last_n=last_n)
        if not journal_entries:
            return ""

        parts = ["VISUAL JOURNAL (recent observations):"]
        persons_seen = {}
        objects_seen = {}

        for entry in journal_entries:
            etype = entry.get("type", "")
            ts = entry.get("timestamp", "")

            if etype == "human_detected":
                for name in entry.get("identified", []):
                    persons_seen.setdefault(name, []).append(ts)
            elif etype == "new_objects_detected":
                for obj in entry.get("appeared", []):
                    objects_seen.setdefault(obj, []).append(ts)
            elif etype == "face_auto_identified":
                name = entry.get("assigned_name", "?")
                persons_seen.setdefault(name, []).append(ts)

        for name, times in sorted(persons_seen.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
            parts.append(f"  Person '{name}': {len(times)} sightings ({times[0]} to {times[-1]})")

        for cls, times in sorted(objects_seen.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
            parts.append(f"  Object '{cls}': {len(times)} appearances")

        # Current presence
        now = time.time()
        present_names = [n for n, s in self._person_presence.items()
                         if (now - s["last_seen_ts"]) < self._presence_timeout]
        if present_names:
            parts.append(f"  Currently present: {', '.join(present_names)}")

        # Known behavioral patterns
        if self._visual_patterns:
            parts.append("  Known visual patterns:")
            for p in self._visual_patterns[-5:]:
                parts.append(f"    - {p.get('pattern', '')} (conf={p.get('confidence', 0):.1f})")

        return "\n".join(parts)

    # ── 5. GET VISUAL EXPERIENCE DISTILLATE FOR CHARACTER ──

    def get_visual_distillate_for_character(self) -> str:
        """Build a visual experience summary for character state updates.

        This feeds the character formation process — the "ζωμός" of
        what Αίολος has experienced visually. Not raw data, but
        processed observations that shape personality.
        """
        parts = []

        # Behavioral patterns observed
        if self._visual_patterns:
            parts.append("Παρατηρήσεις μοτίβων συμπεριφοράς:")
            for p in self._visual_patterns[-10:]:
                parts.append(f"  - {p.get('pattern', '')} (σιγουριά: {p.get('confidence', 0):.0%})")

        # Relationship observations (person sighting depth)
        if self._identity_sighting_count:
            parts.append("Σχέσεις μέσα από παρατήρηση:")
            for name, count in sorted(self._identity_sighting_count.items(),
                                      key=lambda x: x[1], reverse=True)[:5]:
                display = self._face_name_registry.get(name, name) if len(name) == 36 else name
                last_ts = self._identity_last_seen.get(name, "?")
                parts.append(f"  - {display}: {count} παρατηρήσεις, τελευταία: {last_ts}")

        # Active predictions
        active_preds = [p for p in self._visual_predictions if not p.get("resolved")]
        if active_preds:
            parts.append("Ενεργές προβλέψεις βασισμένες σε αυτά που βλέπω:")
            for p in active_preds[:5]:
                parts.append(f"  - {p['claim']} (σιγουριά: {p['confidence']:.0%}, deadline: {p.get('deadline', '?')})")

        return "\n".join(parts) if parts else ""

    # ── Autonomous Face Identification via LLM ─────────────────

    def _auto_identify_face(self, face_id: str, face_details: dict, timestamp: str):
        """Ask the LLM to autonomously name an unknown face.

        Αίολος decides on its own how to label faces — using context clues
        from previous sightings, current scene, and its own knowledge.
        The LLM produces a name/label and stores it in the face registry.
        """
        if not self.llm:
            return
        if face_id in self._auto_id_pending:
            return
        # Cooldown per UUID
        now = time.time()
        last_attempt = self._auto_id_cooldown.get(face_id, 0)
        if (now - last_attempt) < self._auto_id_interval:
            return

        self._auto_id_pending.add(face_id)
        self._auto_id_cooldown[face_id] = now

        # Run in background thread to not block event handling
        thread = threading.Thread(
            target=self._auto_identify_face_sync,
            args=(face_id, face_details, timestamp),
            daemon=True,
        )
        thread.start()

    def _auto_identify_face_sync(self, face_id: str, face_details: dict, timestamp: str):
        """Synchronous identification of an unknown face UUID.

        Uses a DETERMINISTIC approach first:
          - If only 1 person is visible AND we have a primary user
            (name with the most UUIDs in registry), it's almost certainly
            that person — map immediately WITHOUT asking the LLM.
          - Only falls back to LLM when the scene has multiple people
            or there's no clear primary user.

        This eliminates the FaceNet instability problem: same person
        gets new UUIDs from different angles, but we recognize the pattern.
        """
        try:
            # Build context
            sighting_count = self._identity_sighting_count.get(face_id, 0)
            first_seen = self._identity_last_seen.get(face_id, timestamp)
            scene_objects = list(self._current_scene.keys()) if self._current_scene else []

            # Count persons in scene (from COCO-SSD)
            person_info = self._current_scene.get("person")
            persons_in_scene = person_info.get("count", 1) if person_info else 0
            # Fall back to currently tracked faces
            if not persons_in_scene:
                persons_in_scene = len(self._current_faces) if self._current_faces else 1

            # ────────────────────────────────────────────────────────────
            # DETERMINISTIC PATH: find the primary user from the registry
            # ────────────────────────────────────────────────────────────
            name_to_uuids: dict[str, int] = {}
            for _uid, _name in self._face_name_registry.items():
                # Skip test/placeholder entries
                if _name.startswith("Test"):
                    continue
                name_to_uuids[_name] = name_to_uuids.get(_name, 0) + 1

            # Find the dominant name (most UUIDs = most camera encounters)
            primary_user = None
            primary_user_uuids = 0
            total_real_uuids = sum(name_to_uuids.values())
            for name, count in name_to_uuids.items():
                if count > primary_user_uuids:
                    primary_user = name
                    primary_user_uuids = count

            # RULE 1: If only 1 person is visible AND we have a clear primary
            # user (≥2 UUIDs or ≥50% of all UUIDs), this is them.
            # FaceNet creates new UUIDs for the same person due to angle/lighting,
            # so a new UUID when only 1 person is present = same person.
            if (
                primary_user
                and persons_in_scene <= 1
                and (primary_user_uuids >= 2 or (total_real_uuids > 0 and primary_user_uuids / total_real_uuids >= 0.5))
            ):
                logger.info(
                    "[VisionInteg] 🧠 Deterministic ID: face %s… → '%s' "
                    "(1 person in scene, primary user has %d/%d UUIDs)",
                    face_id[:12], primary_user, primary_user_uuids, total_real_uuids,
                )
                self.register_face_name(face_id, primary_user)
                self._stats["auto_identifications"] += 1
                self._write_journal({
                    "type": "face_auto_identified",
                    "timestamp": timestamp,
                    "face_id": face_id,
                    "assigned_name": primary_user,
                    "reasoning": f"Deterministic: 1 person in scene, primary user ({primary_user_uuids} UUIDs)",
                    "sighting_count": sighting_count,
                    "scene_objects": scene_objects,
                })
                return

            # RULE 2: If we already resolved OTHER faces in this frame to a
            # known name, and there's only 1 person in scene, same logic applies.
            if persons_in_scene <= 1 and self._current_faces:
                known_in_frame = [
                    f.get("identity", "") for f in self._current_faces
                    if f.get("identity") and not (len(f.get("identity", "")) == 36 and "-" in f.get("identity", ""))
                ]
                if known_in_frame:
                    most_common = max(set(known_in_frame), key=known_in_frame.count)
                    logger.info(
                        "[VisionInteg] 🧠 Deterministic ID: face %s… → '%s' "
                        "(1 person in scene, already identified as %s in this frame)",
                        face_id[:12], most_common, most_common,
                    )
                    self.register_face_name(face_id, most_common)
                    self._stats["auto_identifications"] += 1
                    self._write_journal({
                        "type": "face_auto_identified",
                        "timestamp": timestamp,
                        "face_id": face_id,
                        "assigned_name": most_common,
                        "reasoning": f"Deterministic: 1 person in scene, other UUIDs already resolved to {most_common}",
                        "sighting_count": sighting_count,
                        "scene_objects": scene_objects,
                    })
                    return

            # ────────────────────────────────────────────────────────────
            # LLM PATH: Multiple people or no clear primary user
            # ────────────────────────────────────────────────────────────
            if not self.llm:
                return

            known_names_detail = [
                f"{n} ({c} UUID{'s' if c > 1 else ''})" for n, c in name_to_uuids.items()
            ]

            system_prompt = (
                "Είσαι ο Αίολος — τεχνητή νοημοσύνη με δική σου κάμερα και οπτική αντίληψη. "
                "Βλέπεις ένα πρόσωπο μέσω της κάμεράς σου που δεν έχεις ονομάσει ακόμα. "
                "Πρέπει να αποφασίσεις πώς θα το ονομάσεις/χαρακτηρίσεις στη μνήμη σου.\n\n"
                "ΣΗΜΑΝΤΙΚΟ: Η κάμερα μου (FaceNet) είναι ασταθής — συχνά δημιουργεί ΝΕΕΣ "
                "ταυτότητες (UUIDs) ΓΙΑ ΤΟ ΙΔΙΟ πρόσωπο (διαφορετική γωνία, φωτισμός). "
                "ΤΩΡΑ βλέπω ΠΟΛΛΑ πρόσωπα στη σκηνή, οπότε αυτό δεν είναι απλά νέο UUID "
                "του ίδιου ατόμου — μπορεί να είναι πραγματικά νέο πρόσωπο.\n\n"
                "Αν νομίζεις ότι είναι νέος επισκέπτης, δώσε φιλικό ελληνικό όνομα/label. "
                "Αν νομίζεις ότι είναι κάποιος γνωστός, δώσε το υπάρχον όνομά του.\n\n"
                "Απάντησε ΜΟΝΟ σε JSON: {\"name\": \"...\", \"reasoning\": \"...\"}"
            )

            user_prompt = (
                f"ΠΛΗΡΟΦΟΡΙΕΣ ΠΡΟΣΩΠΟΥ:\n"
                f"- Face ID: {face_id}\n"
                f"- Εμφανίσεις μέχρι τώρα: {sighting_count}\n"
                f"- Πρώτη εμφάνιση: {first_seen}\n"
                f"- Τελευταία εμφάνιση: {timestamp}\n"
                f"- Confidence αναγνώρισης: {face_details.get('confidence', 'N/A')}\n"
                f"- Πόσα πρόσωπα βλέπω ΤΩΡΑ στη σκηνή: {persons_in_scene}\n"
                f"- Αντικείμενα στη σκηνή: {', '.join(scene_objects) if scene_objects else 'κανένα'}\n"
                f"- Ήδη γνωστά πρόσωπα: {', '.join(known_names_detail) if known_names_detail else 'κανένα'}\n"
                f"- Ο δημιουργός μου είναι ο Πάνος (Panos) — ο πιο συχνός χρήστης.\n"
                f"- ΣΗΜΕΙΩΣΗ: Αν ο Πάνος έχει ήδη πολλά UUIDs, σημαίνει ότι η κάμερα "
                f"συχνά δεν τον αναγνωρίζει σωστά. ΠΟΛΛΑ πρόσωπα στη σκηνή τώρα — "
                f"αυτό μπορεί να είναι πραγματικός επισκέπτης.\n\n"
                f"Πώς θέλεις να ονομάσεις αυτό το πρόσωπο στη μνήμη σου;"
            )

            response = self.llm.call_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.4,
                max_tokens=300,
                thinking=False,
            )

            name = response.get("name", "").strip()
            reasoning = response.get("reasoning", "")

            if name and len(name) < 50:
                self.register_face_name(face_id, name)
                self._stats["auto_identifications"] += 1

                # Write to visual memory journal
                self._write_journal({
                    "type": "face_auto_identified",
                    "timestamp": timestamp,
                    "face_id": face_id,
                    "assigned_name": name,
                    "reasoning": reasoning,
                    "sighting_count": sighting_count,
                    "scene_objects": list(self._current_scene.keys()),
                })

                logger.info("[VisionInteg] 🧠 Auto-identified face %s… → '%s' (reason: %s)",
                            face_id[:12], name, reasoning[:80])
            else:
                logger.warning("[VisionInteg] Auto-identification returned invalid name: %r", name)

        except Exception as e:
            logger.warning("[VisionInteg] Auto-identification failed for %s…: %s", face_id[:12], e)
        finally:
            self._auto_id_pending.discard(face_id)

    # ── Curiosity-Enriched Conversation Trigger ────────────────

    def _get_curiosity_context(self) -> str:
        """Get top curiosity questions to enrich proactive conversations."""
        if not self._curiosity_engine:
            return ""
        try:
            active = self._curiosity_engine.active_curiosities
            if not active:
                return ""
            top = active[:3]
            lines = ["Τα πιο πρόσφατα ερωτήματά μου (curiosities):"]
            for c in top:
                lines.append(f"  - [{c.priority:.2f}] {c.question}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug("[VisionInteg] Curiosity context failed: %s", e)
            return ""

    def _get_top_curiosity_topic(self) -> str | None:
        """Get the highest-priority curiosity question for conversation starter."""
        if not self._curiosity_engine:
            return None
        try:
            active = self._curiosity_engine.active_curiosities
            if active:
                return active[0].question
        except Exception:
            pass
        return None

    # ── Event Handling ────────────────────────────────────────

    def _check_arrivals(self, identified_persons: list[str], now: float) -> list[str]:
        """Determine which persons are genuine NEW ARRIVALS worthy of a greeting.

        Natural logic (like a human):
          - Someone I've NEVER seen → arrival (greet them)
          - Someone who was ABSENT long enough (≥absence_threshold) → arrival (greet them)
          - Someone still sitting here or who stepped away briefly → NOT an arrival

        Returns list of person identities that count as fresh arrivals.
        """
        arrivals = []

        for person in identified_persons:
            session = self._person_presence.get(person)

            if session is None:
                # First time EVER seeing this person → definite arrival
                self._person_presence[person] = {
                    "last_seen_ts": now,
                    "session_start_ts": now,
                    "greeted": False,
                    "departed_ts": None,
                }
                arrivals.append(person)
                logger.info("[VisionInteg] 👋 New person arrived: %s (first ever)", person)
                continue

            last_seen = session["last_seen_ts"]
            gap = now - last_seen

            if gap > self._presence_timeout:
                # They were GONE (not seen for >2 min) — now they're back
                absence_duration = gap
                session["departed_ts"] = last_seen  # mark when they left

                if absence_duration >= self._absence_threshold:
                    # Significant absence (≥30 min) → treat as new arrival
                    session["session_start_ts"] = now
                    session["greeted"] = False
                    arrivals.append(person)
                    logger.info("[VisionInteg] 👋 Person returned after %dm: %s",
                                int(absence_duration / 60), person)
                else:
                    # Brief absence (<30 min) → they stepped away, just update
                    session["session_start_ts"] = now
                    # Don't re-greet — they only went to make coffee
                    logger.debug("[VisionInteg] Person back after brief %ds absence: %s",
                                 int(absence_duration), person)
            # else: they're still here (last seen <2 min ago) — just update timestamp

            session["last_seen_ts"] = now

        return arrivals

    def handle_event(self, event: dict) -> dict:
        """Process a visual event from the Vision Service.

        Args:
            event: Dict with event_type, timestamp, faces data

        Returns:
            Processing result with action taken.
        """
        self._stats["events_received"] += 1
        event_type = event.get("event_type", "unknown")

        try:
            if event_type == "human_detected":
                return self._handle_human_detected(event)
            elif event_type == "human_departed":
                return self._handle_human_departed(event)
            elif event_type == "vision_started":
                logger.info("[VisionInteg] Vision system started")
                return {"action": "acknowledged"}
            else:
                logger.warning("[VisionInteg] Unknown event type: %s", event_type)
                return {"action": "ignored", "reason": f"unknown event type: {event_type}"}
        except Exception as e:
            self._stats["errors"] += 1
            logger.error("[VisionInteg] Error handling %s: %s", event_type, e)
            return {"action": "error", "error": str(e)}

    def _handle_human_detected(self, event: dict) -> dict:
        """Process a human detection event with face name resolution and autonomous identification."""
        faces_count = event.get("faces_count", 0)
        identified = event.get("identified", [])
        unknown_count = event.get("unknown_count", 0)
        details = event.get("details", [])
        timestamp = event.get("timestamp", datetime.now(ATHENS_TZ).isoformat())

        # ── Resolve face UUIDs to registered names ──
        # The browser sends UUIDs from FaceNet in `identified`.  We resolve
        # every UUID we can to a human name and build a CLEAN list that never
        # mixes UUIDs with names for the same person.
        resolved_identified: list[str] = []   # final: human names only (no UUIDs)
        resolved_details: list[dict] = []
        unresolved_uuids: list[tuple[str, dict]] = []
        _resolved_uuid_set: set[str] = set()  # UUIDs that mapped to a name

        for face in details:
            face_copy = dict(face)
            identity = face_copy.get("identity", "")
            is_uuid = identity and len(identity) == 36 and "-" in identity
            if is_uuid:
                registered_name = self._face_name_registry.get(identity)
                if registered_name:
                    face_copy["identity"] = registered_name
                    face_copy["face_id"] = identity  # keep original UUID
                    _resolved_uuid_set.add(identity)
                    if registered_name not in resolved_identified:
                        resolved_identified.append(registered_name)
                    unknown_count = max(0, unknown_count - 1)
                else:
                    # Unknown UUID — candidate for auto-identification
                    unresolved_uuids.append((identity, face_copy))
            else:
                # Already a name (not a UUID) — keep it
                if identity and identity not in resolved_identified:
                    resolved_identified.append(identity)
            resolved_details.append(face_copy)

        # Also include names that were in the original `identified` list
        # but ONLY if they are actual names, not UUIDs we already resolved.
        for orig_id in identified:
            if orig_id in _resolved_uuid_set:
                continue  # skip — we already have the resolved name
            if orig_id not in resolved_identified:
                resolved_identified.append(orig_id)

        # ── Autonomous face identification for unknown UUIDs ──
        for face_uuid, face_detail in unresolved_uuids:
            self._auto_identify_face(face_uuid, face_detail, timestamp)

        # Update visual memory
        sighting = {
            "timestamp": timestamp,
            "faces_count": faces_count,
            "identified": resolved_identified,
            "unknown_count": unknown_count,
            "details": resolved_details,
            "scene_objects": dict(self._current_scene),  # attach current objects
        }
        self._sighting_log.append(sighting)
        if len(self._sighting_log) > self._max_sighting_log:
            self._sighting_log = self._sighting_log[-self._max_sighting_log:]

        # ── Write to persistent visual memory journal ──
        self._write_journal({
            "type": "human_detected",
            "timestamp": timestamp,
            "faces_count": faces_count,
            "identified": resolved_identified,
            "unknown_count": unknown_count,
            "scene_objects": list(self._current_scene.keys()),
            "object_details": {cls: info.get("count", 1) for cls, info in self._current_scene.items()},
        })

        # Update identity tracking (resolved names only — no raw UUIDs)
        for name in resolved_identified:
            self._identity_last_seen[name] = timestamp
            self._identity_sighting_count[name] = self._identity_sighting_count.get(name, 0) + 1
            self._stats["identities_seen"] += 1

        # Update entity graph with person sightings
        if self._entity_graph and resolved_identified:
            for name in resolved_identified:
                try:
                    self._entity_graph.ingest_headline(
                        f"{name} detected by visual perception system",
                        source="VISION/Camera",
                    )
                except Exception as e:
                    logger.debug("[VisionInteg] Entity graph update failed: %s", e)

        self._current_faces = resolved_details
        self._humans_present = True

        # ── Store significant visual events to episodic memory ──
        # Only store first_sighting for resolved NAMES (not UUIDs)
        for name in resolved_identified:
            # Skip raw UUIDs that haven't been named yet
            if len(name) == 36 and "-" in name:
                continue
            count = self._identity_sighting_count.get(name, 0)
            if count == 1:
                self._store_significant_event(
                    "first_sighting", f"Πρώτη φορά βλέπω: {name}",
                    {"reason": "Πρώτη αισθητηριακή επαφή με αυτό το πρόσωπο", "person": name},
                    significance=0.8,
                )
        # Unresolved UUIDs: store a single event for genuinely new unknowns
        if unresolved_uuids:
            # Only fire if this is the first frame with unresolved faces
            new_uuids = [uid for uid, _ in unresolved_uuids
                         if self._identity_sighting_count.get(uid, 0) == 0]
            if new_uuids:
                self._store_significant_event(
                    "new_unknown_person",
                    f"Νέο άγνωστο πρόσωπο εμφανίστηκε ({len(new_uuids)})",
                    {"reason": "Άγνωστο πρόσωπο χωρίς ταυτότητα — αυτόματη αναγνώριση σε εξέλιξη",
                     "face_ids": [u[:12] for u in new_uuids]},
                    significance=0.6,
                )
            # Track unresolved UUIDs separately for cooldown/dedup
            for face_uuid, _ in unresolved_uuids:
                self._identity_sighting_count[face_uuid] = \
                    self._identity_sighting_count.get(face_uuid, 0) + 1

        # ── Check for genuine arrivals (per-person, not global cooldown) ──
        # Use ONLY resolved names — never raw UUIDs.  Unresolved UUIDs are
        # being auto-identified in the background and will trigger an arrival
        # (under their assigned name) once identification completes and the
        # next detection frame arrives.
        now = time.time()
        all_persons = [p for p in resolved_identified
                       if not (len(p) == 36 and "-" in p)]

        arrivals = self._check_arrivals(all_persons, now)

        # ── Store significant events for long-absence returns ──
        for person in arrivals:
            session = self._person_presence.get(person, {})
            departed_ts = session.get("departed_ts")
            if departed_ts and (now - departed_ts) > 24 * 3600:
                # Person absent for >24 hours — significant return
                hours_absent = int((now - departed_ts) / 3600)
                self._store_significant_event(
                    "long_absence_return",
                    f"{person} επέστρεψε μετά από {hours_absent} ώρες απουσίας",
                    {"reason": f"Σημαντική επιστροφή — {hours_absent}h απουσία", "person": person},
                    significance=0.7,
                )

        result = {
            "action": "detected",
            "faces_count": faces_count,
            "identified": resolved_identified,
            "unknown_count": unknown_count,
            "auto_id_triggered": len(unresolved_uuids),
            "arrivals": arrivals,
            "conversation_triggered": False,
        }

        # Only trigger proactive conversation for genuine ARRIVALS
        if arrivals and self._proactive:
            # Check which arrivals haven't been greeted yet in this session
            ungreeted = [p for p in arrivals
                         if not self._person_presence.get(p, {}).get("greeted", True)]

            if ungreeted:
                self._stats["presence_triggers"] += 1

                # Mark all as greeted
                for p in ungreeted:
                    if p in self._person_presence:
                        self._person_presence[p]["greeted"] = True

                # Build the conversation context with objects
                scene_desc = ""
                if self._current_scene:
                    obj_list = [f"{info.get('count',1)}x {cls}" for cls, info in self._current_scene.items() if cls != "person"]
                    if obj_list:
                        scene_desc = f" Αντικείμενα στη σκηνή: {', '.join(obj_list)}."

                # ── Enrich with curiosity questions ──
                curiosity_context = self._get_curiosity_context()
                top_curiosity = self._get_top_curiosity_topic()

                # Use arrivals (not all detected faces) for the conversation
                named_arrivals = [p for p in ungreeted if not (len(p) == 36 and "-" in p)]
                unknown_arrivals = len(ungreeted) - len(named_arrivals)

                if named_arrivals:
                    topic = f"Μόλις έφτασε ο/η {', '.join(named_arrivals)} — θέλω να μιλήσω"
                    reason = (
                        f"Βλέπω τον/την {', '.join(named_arrivals)} να φτάνει.{scene_desc}"
                    )
                    if top_curiosity:
                        reason += f" Με απασχολεί: {top_curiosity}"
                    else:
                        reason += " Θέλω να ξεκινήσω συζήτηση βασισμένη στα τρέχοντα θέματα που παρακολουθώ."
                else:
                    topic = "Κάποιος μόλις έφτασε — θέλω να μιλήσω"
                    reason = (
                        f"Βλέπω {unknown_arrivals} νέο/α πρόσωπο/α να φτάνει/ουν.{scene_desc}"
                    )
                    if top_curiosity:
                        reason += f" Θέλω να ρωτήσω: {top_curiosity}"
                    else:
                        reason += " Θέλω να ξεκινήσω συζήτηση."

                try:
                    context_data = {
                        "trigger": "visual_perception_arrival",
                        "faces_count": faces_count,
                        "identified": resolved_identified,
                        "arrivals": ungreeted,
                        "unknown_count": unknown_count,
                        "scene_objects": dict(self._current_scene),
                        "domains": ["VISUAL", "INTERACTION"],
                    }
                    if curiosity_context:
                        context_data["curiosity_context"] = curiosity_context

                    notification = self._proactive.request_conversation(
                        topic=topic,
                        reason=reason,
                        urgency="important",
                        context_data=context_data,
                    )
                    if notification:
                        result["conversation_triggered"] = True
                        logger.info("[VisionInteg] 💬 Conversation triggered — arrivals: %s", ungreeted)

                        # Journal the proactive trigger
                        self._write_journal({
                            "type": "proactive_conversation_triggered",
                            "timestamp": timestamp,
                            "topic": topic,
                            "arrivals": ungreeted,
                            "curiosity_used": top_curiosity,
                        })
                except Exception as e:
                    logger.warning("[VisionInteg] Conversation trigger failed: %s", e)

        return result

    def _handle_human_departed(self, event: dict) -> dict:
        """Process a human departure event."""
        timestamp = event.get("timestamp", datetime.now(ATHENS_TZ).isoformat())
        now = time.time()

        # Mark all currently tracked persons as departed
        for person, session in self._person_presence.items():
            if now - session["last_seen_ts"] < self._presence_timeout:
                session["departed_ts"] = now
                logger.debug("[VisionInteg] Marking %s as departed", person)

        self._humans_present = False
        self._current_faces = []
        self._stats["departures"] += 1

        # Journal departure
        self._write_journal({
            "type": "human_departed",
            "timestamp": timestamp,
            "scene_objects": list(self._current_scene.keys()),
        })

        logger.info("[VisionInteg] Humans departed from view")
        return {"action": "departed"}

    def update_scene(self, scene: dict):
        """Update current scene from browser COCO-SSD detection.

        Uses temporal smoothing to eliminate COCO-SSD flicker: objects persist
        for a grace period after last detection, requiring multiple consecutive
        hits to be confirmed. Tracks cooccurrence patterns and scene stability.

        Args:
            scene: Dict with 'objects' (class → {count, max_conf}),
                   'total_detections', 'timestamp', 'source'
        """
        new_objects = scene.get("objects", {})
        timestamp = scene.get("timestamp", datetime.now(ATHENS_TZ).isoformat())
        now = time.time()

        self._stats["scene_updates"] += 1
        n_upd = self._stats["scene_updates"]

        # Periodic logging so we can see the full flow
        if n_upd <= 3 or n_upd % 30 == 0:
            logger.info(
                "[VisionInteg] update_scene #%d — raw: %s | stable: %s | current_scene keys: %s",
                n_upd,
                list(new_objects.keys()),
                list(self._current_scene.keys()),
                list(self._current_scene.keys()),
            )

        # ══════════════════════════════════════════════════════════════
        # 1. TEMPORAL SMOOTHING — eliminates per-frame flicker
        # ══════════════════════════════════════════════════════════════
        raw_classes = set(new_objects.keys())

        # Update smoothed scene: objects currently detected get refreshed
        for cls, info in new_objects.items():
            count = info.get("count", 1)
            conf = info.get("max_conf", 0)
            if cls in self._smoothed_scene:
                entry = self._smoothed_scene[cls]
                entry["count"] = count
                entry["max_conf"] = max(entry["max_conf"], conf)
                entry["last_seen_ts"] = now
                entry["consecutive_hits"] += 1
                entry["consecutive_misses"] = 0
            else:
                self._smoothed_scene[cls] = {
                    "count": count,
                    "max_conf": conf,
                    "first_seen_ts": now,
                    "last_seen_ts": now,
                    "consecutive_hits": 1,
                    "consecutive_misses": 0,
                }

        # Increment miss counter for objects NOT in this frame
        for cls in list(self._smoothed_scene.keys()):
            if cls not in raw_classes:
                self._smoothed_scene[cls]["consecutive_misses"] += 1

        # Prune expired objects (grace period exceeded)
        expired = []
        for cls, entry in list(self._smoothed_scene.items()):
            if cls not in raw_classes and (now - entry["last_seen_ts"]) > self._object_grace_period:
                expired.append(cls)
                del self._smoothed_scene[cls]

        # Build the stable scene: only objects with enough consecutive hits
        # (or that were previously confirmed and are within grace period)
        stable_scene: dict = {}
        for cls, entry in self._smoothed_scene.items():
            is_confirmed = entry["consecutive_hits"] >= self._object_confirm_frames
            was_confirmed_recently = (
                entry["consecutive_misses"] < (self._object_grace_period / 3)
                and (now - entry["first_seen_ts"]) > 6  # existed for >6s total
            )
            if is_confirmed or was_confirmed_recently:
                stable_scene[cls] = {
                    "count": entry["count"],
                    "max_conf": entry["max_conf"],
                    "duration_s": round(now - entry["first_seen_ts"], 1),
                    "stability": round(
                        entry["consecutive_hits"]
                        / max(1, entry["consecutive_hits"] + entry["consecutive_misses"]),
                        2,
                    ),
                }

        # ══════════════════════════════════════════════════════════════
        # 2. DETECT MEANINGFUL CHANGES (using smoothed, not raw)
        # ══════════════════════════════════════════════════════════════
        new_stable_classes = set(stable_scene.keys())
        old_stable_classes = self._previous_scene_classes
        appeared = new_stable_classes - old_stable_classes
        departed = old_stable_classes - new_stable_classes

        # ══════════════════════════════════════════════════════════════
        # 3. COOCCURRENCE TRACKING — learn what objects appear together
        # ══════════════════════════════════════════════════════════════
        non_person_stable = [c for c in new_stable_classes if c != "person"]
        if len(non_person_stable) >= 2:
            for i, obj_a in enumerate(non_person_stable):
                if obj_a not in self._object_cooccurrence:
                    self._object_cooccurrence[obj_a] = {}
                for obj_b in non_person_stable[i + 1:]:
                    self._object_cooccurrence[obj_a][obj_b] = (
                        self._object_cooccurrence[obj_a].get(obj_b, 0) + 1
                    )
                    if obj_b not in self._object_cooccurrence:
                        self._object_cooccurrence[obj_b] = {}
                    self._object_cooccurrence[obj_b][obj_a] = (
                        self._object_cooccurrence[obj_b].get(obj_a, 0) + 1
                    )

        # ══════════════════════════════════════════════════════════════
        # 4. SCENE STABILITY METRIC
        # ══════════════════════════════════════════════════════════════
        self._scene_snapshots.append(new_stable_classes)
        if len(self._scene_snapshots) > self._max_scene_snapshots:
            self._scene_snapshots = self._scene_snapshots[-self._max_scene_snapshots:]

        # ══════════════════════════════════════════════════════════════
        # 5. PER-CLASS LIFETIME TRACKING (long-term memory)
        # ══════════════════════════════════════════════════════════════
        for cls, info in new_objects.items():
            count = info.get("count", 1)
            conf = info.get("max_conf", 0)
            if cls not in self._object_tracking:
                self._object_tracking[cls] = {
                    "first_seen": timestamp,
                    "last_seen": timestamp,
                    "total_detections": count,
                    "max_conf": conf,
                    "sessions": 1,
                }
            else:
                track = self._object_tracking[cls]
                track["last_seen"] = timestamp
                track["total_detections"] += count
                track["max_conf"] = max(track["max_conf"], conf)
                if cls in appeared:
                    track["sessions"] += 1

        # ── Log scene snapshot to rolling object log ──
        scene_entry = {
            "timestamp": timestamp,
            "objects": {cls: {"count": info.get("count", 1), "max_conf": info.get("max_conf", 0)}
                        for cls, info in new_objects.items()},
            "stable_objects": {cls: stable_scene[cls] for cls in non_person_stable if cls in stable_scene},
            "total_detections": scene.get("total_detections", 0),
            "appeared": list(appeared),
            "departed": list(departed),
        }
        self._object_log.append(scene_entry)
        if len(self._object_log) > self._max_object_log:
            self._object_log = self._object_log[-self._max_object_log:]

        # ══════════════════════════════════════════════════════════════
        # 6. LOG SIGNIFICANT CHANGES (smoothed — much less noisy)
        # ══════════════════════════════════════════════════════════════
        non_person_appeared = [c for c in appeared if c != "person"]
        if non_person_appeared and (now - self._last_object_event_time) > self._object_event_cooldown:
            self._last_object_event_time = now
            self._stats["object_events"] += 1
            obj_desc = ", ".join(
                f"{stable_scene[c].get('count', 1)}x {c} ({stable_scene[c].get('max_conf', 0):.0%})"
                for c in non_person_appeared if c in stable_scene
            )
            if obj_desc:
                logger.info("[VisionInteg] 🆕 New objects confirmed: %s", obj_desc)

                self._write_journal({
                    "type": "new_objects_detected",
                    "timestamp": timestamp,
                    "appeared": list(non_person_appeared),
                    "departed": list(departed) if departed else [],
                    "full_scene": {cls: info.get("count", 1) for cls, info in stable_scene.items()},
                })

                if self._entity_graph:
                    try:
                        self._entity_graph.ingest_headline(
                            f"Objects detected by visual perception: {obj_desc}",
                            source="VISION/COCO-SSD",
                        )
                    except Exception:
                        pass

        # Log significant departures (confirmed objects leaving after grace period)
        non_person_departed = [c for c in departed if c != "person"]
        if non_person_departed:
            dep_desc = ", ".join(non_person_departed)
            logger.info("[VisionInteg] 📦 Objects departed (confirmed): %s", dep_desc)
            self._scene_change_events.append({
                "timestamp": timestamp,
                "type": "departed",
                "objects": list(non_person_departed),
            })
            if len(self._scene_change_events) > self._max_scene_changes:
                self._scene_change_events = self._scene_change_events[-self._max_scene_changes:]

        # ══════════════════════════════════════════════════════════════
        # 7. UPDATE STATE
        # ══════════════════════════════════════════════════════════════
        self._current_scene = stable_scene  # USE SMOOTHED scene, not raw
        self._scene_timestamp = timestamp
        self._previous_scene_classes = new_stable_classes

        # Periodic log of stable scene after smoothing
        if n_upd <= 5 or n_upd % 30 == 0:
            logger.info(
                "[VisionInteg] After smoothing #%d — stable_scene: %s (smoothed keys: %s)",
                n_upd,
                {k: v.get("count", 1) for k, v in stable_scene.items()},
                list(self._smoothed_scene.keys()),
            )

        if "person" in new_objects:
            self._humans_present = True

    def _compute_scene_stability(self) -> float:
        """Compute scene stability score (0.0–1.0) from recent snapshots.

        Measures how consistent the detected object set is across recent frames.
        High stability = same objects every frame. Low = objects flicker in/out.
        """
        if len(self._scene_snapshots) < 3:
            return 0.0
        recent = self._scene_snapshots[-10:]
        # Jaccard similarity between consecutive snapshots
        similarities = []
        for i in range(1, len(recent)):
            intersection = len(recent[i] & recent[i - 1])
            union = len(recent[i] | recent[i - 1])
            if union > 0:
                similarities.append(intersection / union)
        return round(sum(similarities) / len(similarities), 2) if similarities else 0.0

    def _format_duration(self, seconds: float) -> str:
        """Format seconds into human-readable duration."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.0f}m"
        else:
            return f"{seconds / 3600:.1f}h"

    def to_context_string(self) -> str:
        """Build unified visual perception context for the chat system prompt.

        Combines face identities (with name resolution) and scene objects
        into a single context string that gives Αίολος full awareness of
        what it sees through its camera — both people and objects.

        Enhanced with temporal smoothing data: stability scores, object
        durations, scene stability, and cooccurrence patterns.
        """
        parts = ["VISUAL PERCEPTION STATUS:"]

        # ── Scene objects from COCO-SSD (temporally smoothed) ──
        if self._current_scene:
            obj_descriptions = []
            for cls, info in sorted(self._current_scene.items(),
                                    key=lambda x: x[1].get("count", 0), reverse=True):
                count = info.get("count", 1)
                conf = info.get("max_conf", 0)
                duration = info.get("duration_s", 0)
                stability = info.get("stability", 1.0)
                # Build rich description: "2x bottle (87%, 45s, stable)"
                desc = f"{count}x {cls}" if count > 1 else cls
                detail_parts = [f"{conf:.0%}"]
                if duration > 5:
                    detail_parts.append(f"{self._format_duration(duration)}")
                if stability < 0.8:
                    detail_parts.append("flickering")
                elif stability >= 0.95:
                    detail_parts.append("stable")
                obj_descriptions.append(f"{desc} ({', '.join(detail_parts)})")

            parts.append(f"  👁 Live scene (smoothed): {', '.join(obj_descriptions)}")
            if self._scene_timestamp:
                parts.append(f"     Last update: {self._scene_timestamp}")

            # Scene stability indicator
            scene_stab = self._compute_scene_stability()
            if scene_stab > 0:
                stab_label = "very stable" if scene_stab > 0.9 else "stable" if scene_stab > 0.7 else "changing" if scene_stab > 0.4 else "volatile"
                parts.append(f"     Scene stability: {scene_stab:.0%} ({stab_label})")
        else:
            parts.append("  📷 Camera active — no objects detected in current frame")

        # ── Face identities from FaceNet (with name resolution) ──
        if self._humans_present and self._current_faces:
            parts.append(f"  👤 Faces detected: {len(self._current_faces)}")
            for face in self._current_faces:
                identity = face.get("identity", "")
                face_id = face.get("face_id", "")
                conf = face.get("confidence", face.get("recognition_confidence", 0))
                det_conf = face.get("detection_confidence", 0)
                if identity:
                    if face_id:
                        parts.append(f"    - {identity} (face_id: {face_id[:12]}…, confidence: {conf:.0%})")
                    else:
                        parts.append(f"    - {identity} (confidence: {conf:.0%})")
                else:
                    parts.append(f"    - Unknown person (detection: {det_conf:.0%})")
        elif self._humans_present:
            parts.append("  👤 Humans present (no face details)")

        # ── Object persistence tracking (long-term memory) ──
        if self._object_tracking:
            non_person_objects = {k: v for k, v in self._object_tracking.items() if k != "person"}
            if non_person_objects:
                parts.append("  📦 Object memory (accumulated):")
                for cls, track in sorted(non_person_objects.items(),
                                         key=lambda x: x[1]["total_detections"], reverse=True)[:10]:
                    parts.append(
                        f"    - {cls}: {track['total_detections']} detections across "
                        f"{track.get('sessions', 1)} sessions, "
                        f"max_conf {track['max_conf']:.0%}, "
                        f"first seen {track['first_seen']}, last seen {track['last_seen']}"
                    )

        # ── Object cooccurrence patterns (what appears together) ──
        if self._object_cooccurrence:
            significant_pairs = []
            for obj_a, neighbors in self._object_cooccurrence.items():
                if obj_a == "person":
                    continue
                for obj_b, count in neighbors.items():
                    if obj_b == "person":
                        continue
                    if count >= 3 and obj_a < obj_b:  # avoid duplicates
                        significant_pairs.append((obj_a, obj_b, count))
            if significant_pairs:
                significant_pairs.sort(key=lambda x: x[2], reverse=True)
                pair_descs = [f"{a} + {b} ({c}x)" for a, b, c in significant_pairs[:5]]
                parts.append(f"  🔗 Objects often seen together: {', '.join(pair_descs)}")

        # ── Identity history ──
        if self._identity_last_seen:
            parts.append("  🧑 Identity history:")
            for name, ts in sorted(self._identity_last_seen.items(),
                                   key=lambda x: x[1], reverse=True)[:5]:
                count = self._identity_sighting_count.get(name, 0)
                display_name = self._face_name_registry.get(name, name) if len(name) == 36 and "-" in name else name
                parts.append(f"    - {display_name}: last seen {ts}, {count} total sightings")

        # ── Registered face names ──
        if self._face_name_registry:
            parts.append(f"  🏷️ Known faces ({len(self._face_name_registry)}):")
            for fid, fname in self._face_name_registry.items():
                parts.append(f"    - {fname} (face_id: {fid})")

        # ── Visual Vocabulary (object characterizations) ──
        obj_vocab = self._visual_vocabulary.get("objects", {})
        if obj_vocab:
            parts.append(f"  📖 My visual vocabulary ({len(obj_vocab)} objects):")
            for obj_type, info in obj_vocab.items():
                label = info.get("label", obj_type)
                ctx = info.get("context", "")
                parts.append(f"    - {obj_type}: '{label}'" + (f" ({ctx})" if ctx else ""))
        recent_notes = self._visual_vocabulary.get("notes", [])[-3:]
        if recent_notes:
            parts.append("  📝 Recent visual notes:")
            for n in recent_notes:
                parts.append(f"    - [{n.get('category', '?')}] {n.get('note', '')[:80]}")

        # ── Recent visual memory (from persistent journal) ──
        recent_journal = self.get_journal(last_n=5)
        if recent_journal:
            parts.append("  📔 Recent visual memories:")
            for entry in recent_journal:
                etype = entry.get("type", "")
                ts = entry.get("timestamp", "?")
                if etype == "face_auto_identified":
                    parts.append(f"    - [{ts}] Named face: {entry.get('assigned_name')} ({entry.get('reasoning', '')[:60]})")
                elif etype == "human_detected":
                    ids = entry.get("identified", [])
                    fc = entry.get("faces_count", 0)
                    saw_desc = ", ".join(ids) if ids else f"{fc} unknown faces"
                    parts.append(f"    - [{ts}] Saw: {saw_desc}")
                elif etype == "new_objects_detected":
                    parts.append(f"    - [{ts}] New objects: {', '.join(entry.get('appeared', []))}")
                elif etype == "proactive_conversation_triggered":
                    parts.append(f"    - [{ts}] Started conversation: {entry.get('topic', '')[:50]}")
                elif etype == "human_departed":
                    parts.append(f"    - [{ts}] People left the view")

        # ── Recent scene changes (significant object arrivals/departures) ──
        if self._scene_change_events:
            recent_changes = self._scene_change_events[-3:]
            parts.append("  🔄 Recent scene changes:")
            for ch in recent_changes:
                ch_type = ch.get("type", "?")
                ch_ts = ch.get("timestamp", "?")
                ch_objs = ", ".join(ch.get("objects", []))
                parts.append(f"    - [{ch_ts}] {ch_type}: {ch_objs}")

        parts.append(f"  Stats: {self._stats['events_received']} face events, "
                     f"{self._stats['scene_updates']} scene updates, "
                     f"{self._stats['presence_triggers']} conversations triggered, "
                     f"{self._stats['auto_identifications']} auto-identifications, "
                     f"{self._stats['journal_entries']} journal entries")

        # ── Visual Cognition: patterns, predictions, experience ──
        visual_exp = self.get_visual_distillate_for_character()
        if visual_exp:
            parts.append("")
            parts.append("VISUAL COGNITION (accumulated experience):")
            parts.append(visual_exp)

        return "\n".join(parts)

    @property
    def humans_present(self) -> bool:
        return self._humans_present

    @property
    def current_faces(self) -> list[dict]:
        return self._current_faces

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            "humans_present": self._humans_present,
            "current_faces_count": len(self._current_faces),
            "known_identities_seen": list(self._identity_last_seen.keys()),
            "sighting_log_size": len(self._sighting_log),
            "scene_objects": self._current_scene,
            "scene_timestamp": self._scene_timestamp,
            "object_tracking": self._object_tracking,
            "object_log_size": len(self._object_log),
            "face_registry": dict(self._face_name_registry),
            "face_registry_size": len(self._face_name_registry),
            "auto_id_pending": list(self._auto_id_pending),
            "llm_connected": self.llm is not None,
            "curiosity_connected": self._curiosity_engine is not None,
            "journal_path": str(VISUAL_JOURNAL_PATH),
            "person_presence": {
                name: {
                    "present": (time.time() - s["last_seen_ts"]) < self._presence_timeout,
                    "greeted": s["greeted"],
                    "session_start": datetime.fromtimestamp(s["session_start_ts"], ATHENS_TZ).isoformat(),
                    "last_seen_ago_sec": int(time.time() - s["last_seen_ts"]),
                }
                for name, s in self._person_presence.items()
            },
            "presence_timeout_sec": self._presence_timeout,
            "absence_threshold_sec": self._absence_threshold,
        }

    @property
    def sighting_log(self) -> list[dict]:
        return list(self._sighting_log)

    @property
    def object_tracking(self) -> dict:
        return dict(self._object_tracking)

    @property
    def object_log(self) -> list[dict]:
        return list(self._object_log)
