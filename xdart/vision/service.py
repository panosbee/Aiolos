"""
XDART-Φ — Vision Service (FaceNet + MTCNN + Camera Loop)

Standalone FastAPI microservice that gives Αίολος eyes.
Runs on port 8100, communicates with main XDART via HTTP callbacks.

Features:
  - Real-time camera capture via OpenCV
  - Face detection via MTCNN (Multi-task Cascaded Convolutional Networks)
  - Face recognition via FaceNet (InceptionResnetV1) embeddings
  - Known face registry with cosine similarity matching
  - Human presence detection → callback to XDART proactive engine
  - Scene description (# of people, known/unknown, confidence)

Usage:
  python -m xdart.vision.service

Known faces:
  Place face images in xdart/vision/known_faces/<person_name>/
  e.g. xdart/vision/known_faces/panos/photo1.jpg
  Multiple images per person improve recognition accuracy.

© Panos Skouras — Salimov MON IKE, 2026
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

logger = logging.getLogger("xdart.vision")

# ── Configuration ──
VISION_PORT = int(os.getenv("VISION_PORT", "8100"))
XDART_CALLBACK_URL = os.getenv("XDART_CALLBACK_URL", "http://localhost:8000/xdart/vision/event")
CAMERA_INDEX = int(os.getenv("VISION_CAMERA_INDEX", "0"))
DETECTION_INTERVAL = float(os.getenv("VISION_DETECTION_INTERVAL", "2.0"))  # seconds between frames
RECOGNITION_THRESHOLD = float(os.getenv("VISION_RECOGNITION_THRESHOLD", "0.45"))  # cosine similarity (lowered for webcam JPEG)
PRESENCE_COOLDOWN = float(os.getenv("VISION_PRESENCE_COOLDOWN", "300"))  # 5 min between presence triggers
KNOWN_FACES_DIR = Path(__file__).parent / "known_faces"
ATHENS_TZ = ZoneInfo("Europe/Athens")
# ── Emotion detection settings ──
EMOTION_ENABLED = os.getenv("VISION_EMOTION_ENABLED", "1") == "1"
EMOTION_DETECTOR_BACKEND = os.getenv("VISION_EMOTION_BACKEND", "opencv")  # opencv is fastest


class EmotionEngine:
    """DeepFace-based facial emotion recognition.

    Analyzes facial expressions and returns emotion probabilities:
    happy, sad, angry, fear, disgust, surprise, neutral.

    Uses DeepFace (pretrained CNN) — runs locally, no API calls.
    Lazy-initialized to avoid loading the model at import time.
    """

    EMOTION_LABELS = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]

    def __init__(self):
        self._initialized = False

    def initialize(self):
        """Lazy import DeepFace — heavy dependency, only load when needed."""
        if self._initialized:
            return
        try:
            import tensorflow as tf
            # Suppress TF warnings
            tf.get_logger().setLevel("ERROR")
            self._initialized = True
            logger.info("[Vision] EmotionEngine initialized (DeepFace ready)")
        except ImportError:
            logger.warning(
                "[Vision] EmotionEngine: deepface/tensorflow not installed. "
                "Install with: pip install deepface tensorflow"
            )
            self._initialized = False

    @property
    def available(self) -> bool:
        return self._initialized

    def analyze_frame(self, frame: np.ndarray) -> list[dict]:
        """Detect emotions for all faces in a frame.

        Args:
            frame: BGR numpy array from OpenCV

        Returns:
            List of dicts with 'emotion', 'dominant_emotion', 'region'.
            Empty list if no faces or engine unavailable.
        """
        if not self._initialized:
            return []

        from deepface import DeepFace

        try:
            # Convert BGR (OpenCV) to RGB (DeepFace expects RGB)
            rgb_frame = frame[:, :, ::-1]

            results = DeepFace.analyze(
                img_path=rgb_frame,
                actions=["emotion"],
                detector_backend=EMOTION_DETECTOR_BACKEND,
                enforce_detection=False,
                silent=True,
            )

            if not results:
                return []

            emotions = []
            for r in results:
                region = r.get("region", {})
                emotion_data = r.get("emotion", {})
                if not emotion_data:
                    continue
                dominant = r.get("dominant_emotion", "neutral")
                emotions.append({
                    "emotion": {
                        "angry": round(emotion_data.get("angry", 0.0), 3),
                        "disgust": round(emotion_data.get("disgust", 0.0), 3),
                        "fear": round(emotion_data.get("fear", 0.0), 3),
                        "happy": round(emotion_data.get("happy", 0.0), 3),
                        "sad": round(emotion_data.get("sad", 0.0), 3),
                        "surprise": round(emotion_data.get("surprise", 0.0), 3),
                        "neutral": round(emotion_data.get("neutral", 0.0), 3),
                    },
                    "dominant_emotion": dominant,
                    "region": {
                        "x": int(region.get("x", 0)),
                        "y": int(region.get("y", 0)),
                        "w": int(region.get("w", 0)),
                        "h": int(region.get("h", 0)),
                    },
                })
            return emotions
        except Exception as e:
            logger.debug("[Vision] EmotionEngine analyze_frame error: %s", e)
            return []

    def match_emotions_to_faces(
        self, emotions: list[dict], face_detections: list[dict]
    ) -> None:
        """Match emotion results to FaceNet detections by bounding box overlap.

        Mutates face_detections in-place, adding 'emotion' and 'dominant_emotion'
        fields to each face that has a matching emotion result.
        """
        if not emotions or not face_detections:
            return

        for face in face_detections:
            bb = face.get("bbox", {})
            if not bb:
                continue
            fx1, fy1 = bb.get("x1", 0), bb.get("y1", 0)
            fx2, fy2 = bb.get("x2", 0), bb.get("y2", 0)

            best_overlap = 0.0
            best_emotion = None

            for em in emotions:
                r = em.get("region", {})
                ex1, ey1 = r.get("x", 0), r.get("y", 0)
                ex2, ey2 = ex1 + r.get("w", 0), ey1 + r.get("h", 0)

                # Intersection over Union (IoU)
                ix1 = max(fx1, ex1)
                iy1 = max(fy1, ey1)
                ix2 = min(fx2, ex2)
                iy2 = min(fy2, ey2)
                if ix2 <= ix1 or iy2 <= iy1:
                    continue

                inter_area = (ix2 - ix1) * (iy2 - iy1)
                face_area = (fx2 - fx1) * (fy2 - fy1)
                em_area = (ex2 - ex1) * (ey2 - ey1)
                iou = inter_area / (face_area + em_area - inter_area + 1e-8)

                if iou > best_overlap and iou > 0.20:
                    best_overlap = iou
                    best_emotion = em

            if best_emotion:
                face["emotion"] = best_emotion.get("emotion", {})
                face["dominant_emotion"] = best_emotion.get("dominant_emotion", "neutral")
                face["emotion_confidence"] = round(
                    best_emotion.get("emotion", {}).get(
                        best_emotion.get("dominant_emotion", "neutral"), 0.0
                    ), 3
                )


class FaceRecognitionEngine:
    """FaceNet-based face recognition with known face registry."""

    def __init__(self):
        self._mtcnn = None
        self._facenet = None
        self._device = None
        self._known_embeddings: dict[str, list[np.ndarray]] = {}  # name → [embedding, ...]
        self._initialized = False

    def initialize(self):
        """Lazy initialization — import heavy ML libs only when needed."""
        if self._initialized:
            return

        import torch
        from facenet_pytorch import MTCNN, InceptionResnetV1

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("[Vision] Using device: %s", self._device)

        # MTCNN face detector (returns bounding boxes + landmarks)
        self._mtcnn = MTCNN(
            image_size=160,
            margin=20,
            min_face_size=30,  # lowered for browser face crops (small face regions)
            thresholds=[0.6, 0.7, 0.8],  # relaxed for JPEG-compressed browser crops
            factor=0.709,
            post_process=True,
            device=self._device,
            keep_all=True,  # detect ALL faces in frame
        )

        # FaceNet (InceptionResnetV1) pretrained on VGGFace2
        self._facenet = InceptionResnetV1(pretrained="vggface2").eval().to(self._device)

        # Load known faces
        self._load_known_faces()
        self._initialized = True
        logger.info("[Vision] FaceNet engine initialized — %d known identities",
                    len(self._known_embeddings))

    def _load_known_faces(self):
        """Load face embeddings from known_faces/ (supports both layouts).

        Layout A — subdirectories:  known_faces/<name>/photo1.jpg
        Layout B — flat files:      known_faces/<name>.jpg  (filename = identity)
        """
        import torch
        from PIL import Image

        VALID_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

        if not KNOWN_FACES_DIR.exists():
            KNOWN_FACES_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("[Vision] Created known_faces directory: %s", KNOWN_FACES_DIR)
            return

        def _embed_image(img_path: Path) -> np.ndarray | None:
            """Extract face embedding from a single image file."""
            try:
                img = Image.open(img_path).convert("RGB")
                face_tensor = self._mtcnn(img)
                if face_tensor is None:
                    logger.warning("[Vision] No face detected in %s", img_path.name)
                    return None
                if face_tensor.dim() == 4:
                    face_tensor = face_tensor[0]
                with torch.no_grad():
                    embedding = self._facenet(face_tensor.unsqueeze(0).to(self._device))
                return embedding.cpu().numpy().flatten()
            except Exception as e:
                logger.warning("[Vision] Failed to load %s: %s", img_path, e)
                return None

        # Layout A: subdirectories  known_faces/<name>/*.jpg
        for person_dir in KNOWN_FACES_DIR.iterdir():
            if not person_dir.is_dir():
                continue
            person_name = person_dir.name
            embeddings = []
            for img_path in person_dir.iterdir():
                if img_path.suffix.lower() not in VALID_EXTS:
                    continue
                emb = _embed_image(img_path)
                if emb is not None:
                    embeddings.append(emb)
                    logger.debug("[Vision] Loaded face: %s/%s", person_name, img_path.name)
            if embeddings:
                self._known_embeddings[person_name] = embeddings
                logger.info("[Vision] Registered '%s' with %d face samples",
                            person_name, len(embeddings))

        # Layout B: flat files  known_faces/<name>.jpg  (filename stem = identity)
        for img_path in KNOWN_FACES_DIR.iterdir():
            if img_path.is_dir() or img_path.suffix.lower() not in VALID_EXTS:
                continue
            person_name = img_path.stem  # e.g. "πανος σκουρας"
            emb = _embed_image(img_path)
            if emb is not None:
                if person_name not in self._known_embeddings:
                    self._known_embeddings[person_name] = []
                self._known_embeddings[person_name].append(emb)
                logger.info("[Vision] Registered '%s' from flat file %s",
                            person_name, img_path.name)

    def detect_faces(self, frame: np.ndarray) -> list[dict]:
        """Detect faces in a camera frame.

        Args:
            frame: BGR numpy array from OpenCV

        Returns:
            List of face detections with bounding boxes and embeddings.
        """
        import torch
        from PIL import Image

        if not self._initialized:
            self.initialize()

        # Convert BGR (OpenCV) to RGB (PIL)
        rgb_frame = frame[:, :, ::-1]
        pil_image = Image.fromarray(rgb_frame)

        # Single-pass: detect + align + crop in one call (avoid double MTCNN run)
        boxes, probs = self._mtcnn.detect(pil_image)

        if boxes is None or len(boxes) == 0:
            logger.debug("[Vision] detect_faces: no boxes found by MTCNN")
            return []

        # Filter by confidence BEFORE expensive FaceNet embedding
        MIN_DETECTION_CONF = 0.80  # relaxed from 0.95 — browser JPEG crops have lower quality
        valid_mask = [p >= MIN_DETECTION_CONF for p in probs]
        boxes = boxes[valid_mask]
        probs = probs[valid_mask]
        logger.debug("[Vision] detect_faces: %d boxes passed confidence filter (>=%s)", len(boxes), MIN_DETECTION_CONF)

        if len(boxes) == 0:
            return []

        # NMS dedup — remove overlapping detections of the same face
        boxes, probs = self._nms(boxes, probs, iou_threshold=0.4)

        # Extract aligned face tensors using the filtered boxes
        face_tensors = self._mtcnn.extract(pil_image, boxes, save_path=None)
        if face_tensors is None:
            return []

        # Ensure batch dimension
        if face_tensors.dim() == 3:
            face_tensors = face_tensors.unsqueeze(0)

        results = []
        with torch.no_grad():
            embeddings = self._facenet(face_tensors.to(self._device))

        for i, (box, prob, emb) in enumerate(zip(boxes, probs, embeddings)):
            if prob < MIN_DETECTION_CONF:
                continue

            emb_np = emb.cpu().numpy().flatten()

            # Try to identify against known faces
            identity, similarity = self._identify(emb_np)

            x1, y1, x2, y2 = box.astype(int)
            results.append({
                "face_id": i,
                "bbox": {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)},
                "detection_confidence": float(prob),
                "identity": identity,
                "recognition_confidence": float(similarity) if identity else 0.0,
                "embedding_hash": hash(emb_np.tobytes()) & 0xFFFFFFFF,
            })

        return results

    @staticmethod
    def _nms(boxes: np.ndarray, probs: np.ndarray, iou_threshold: float = 0.4):
        """Non-Maximum Suppression — remove overlapping detections of the same face."""
        if len(boxes) == 0:
            return boxes, probs

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = probs.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            if order.size == 1:
                break
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0, xx2 - xx1)
            h = np.maximum(0, yy2 - yy1)
            intersection = w * h
            iou = intersection / (areas[i] + areas[order[1:]] - intersection + 1e-8)
            remaining = np.where(iou <= iou_threshold)[0]
            order = order[remaining + 1]

        return boxes[keep], probs[keep]

    def _identify(self, embedding: np.ndarray) -> tuple[str | None, float]:
        """Match embedding against known faces using cosine similarity.

        Returns:
            (name, confidence) or (None, 0.0) if no match.
        """
        best_name = None
        best_similarity = 0.0

        for name, known_embs in self._known_embeddings.items():
            for known_emb in known_embs:
                # Cosine similarity
                similarity = float(np.dot(embedding, known_emb) /
                                   (np.linalg.norm(embedding) * np.linalg.norm(known_emb) + 1e-8))

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_name = name

        if best_similarity >= RECOGNITION_THRESHOLD:
            return best_name, best_similarity

        return None, 0.0

    def register_face(self, name: str, image: np.ndarray) -> bool:
        """Register a new face from a camera frame.

        Args:
            name: Person's name
            image: BGR frame from OpenCV

        Returns:
            True if face was successfully registered.
        """
        import torch
        from PIL import Image

        if not self._initialized:
            self.initialize()

        rgb = image[:, :, ::-1]
        pil_img = Image.fromarray(rgb)

        face_tensor = self._mtcnn(pil_img)
        if face_tensor is None:
            return False

        if face_tensor.dim() == 4:
            face_tensor = face_tensor[0]

        with torch.no_grad():
            embedding = self._facenet(face_tensor.unsqueeze(0).to(self._device))

        emb_np = embedding.cpu().numpy().flatten()

        # Save to disk
        person_dir = KNOWN_FACES_DIR / name
        person_dir.mkdir(parents=True, exist_ok=True)
        count = len(list(person_dir.glob("*.jpg")))
        save_path = person_dir / f"registered_{count + 1}.jpg"

        from PIL import Image as PILImage
        PILImage.fromarray(rgb).save(str(save_path), quality=90)

        # Update in-memory registry
        if name not in self._known_embeddings:
            self._known_embeddings[name] = []
        self._known_embeddings[name].append(emb_np)

        logger.info("[Vision] Registered new face for '%s' (total samples: %d)",
                    name, len(self._known_embeddings[name]))
        return True

    @property
    def known_identities(self) -> list[str]:
        """List all registered identity names."""
        return list(self._known_embeddings.keys())


def _summarize_emotions(faces: list[dict]) -> dict:
    """Aggregate emotion data across all faces in a frame.

    Returns a summary dict with dominant moods and per-emotion averages.
    """
    if not faces:
        return {}
    emotion_faces = [f for f in faces if f.get("emotion")]
    if not emotion_faces:
        return {}

    dominants = [f.get("dominant_emotion", "neutral") for f in emotion_faces]

    avg_emotions: dict[str, float] = {}
    for label in EmotionEngine.EMOTION_LABELS:
        values = [f["emotion"].get(label, 0.0) for f in emotion_faces]
        avg_emotions[label] = round(sum(values) / len(values), 3)

    return {
        "faces_with_emotion": len(emotion_faces),
        "dominant_emotions": dominants,
        "overall_mood": max(set(dominants), key=dominants.count) if dominants else "neutral",
        "average_emotions": avg_emotions,
    }


class CameraLoop:
    """Background camera capture with face detection and presence tracking."""

    def __init__(self, engine: FaceRecognitionEngine, callback_url: str, emotion_engine=None):
        self._engine = engine
        self._callback_url = callback_url
        self._emotion_engine = emotion_engine  # optional EmotionEngine
        self._running = False
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._camera = None
        self._last_presence_trigger: float = 0
        self._last_detection_time: float = 0
        self._humans_present = False
        self._current_faces: list[dict] = []
        # Latest annotated JPEG frame for MJPEG streaming
        self._latest_jpeg: bytes | None = None
        self._latest_raw_frame: np.ndarray | None = None
        self._stats = {
            "frames_processed": 0,
            "faces_detected": 0,
            "identities_recognized": 0,
            "presence_triggers": 0,
            "errors": 0,
            "started_at": None,
            "camera_active": False,
        }

    def start(self):
        """Start the camera loop in a background thread."""
        if self._running:
            return

        self._stop_event.clear()
        self._running = True
        self._thread = Thread(target=self._capture_loop, daemon=True, name="vision-camera")
        self._thread.start()
        logger.info("[Vision] Camera loop started (camera=%d, interval=%.1fs)",
                    CAMERA_INDEX, DETECTION_INTERVAL)

    def stop(self):
        """Stop the camera loop."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._camera is not None:
            self._camera.release()
            self._camera = None
        self._stats["camera_active"] = False
        logger.info("[Vision] Camera loop stopped")

    def _capture_loop(self):
        """Main camera capture loop (runs in background thread).

        Streams frames at ~15 fps for the MJPEG feed.
        Runs expensive face detection only every DETECTION_INTERVAL seconds.
        """
        import cv2

        STREAM_INTERVAL = 1.0 / 15  # ~15 fps for MJPEG stream

        try:
            self._camera = cv2.VideoCapture(CAMERA_INDEX)
            if not self._camera.isOpened():
                logger.error("[Vision] Cannot open camera %d", CAMERA_INDEX)
                self._stats["errors"] += 1
                self._running = False
                return

            # Set camera resolution to 640x480 for speed
            self._camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            self._stats["camera_active"] = True
            self._stats["started_at"] = datetime.now(ATHENS_TZ).isoformat()
            logger.info("[Vision] Camera %d opened successfully", CAMERA_INDEX)

            last_detection = 0.0

            while not self._stop_event.is_set():
                ret, frame = self._camera.read()
                if not ret:
                    self._stats["errors"] += 1
                    time.sleep(0.5)
                    continue

                now = time.time()
                run_detection = (now - last_detection) >= DETECTION_INTERVAL

                try:
                    self._process_frame(frame, run_detection=run_detection)
                    if run_detection:
                        last_detection = now
                except Exception as e:
                    logger.warning("[Vision] Frame processing error: %s", e)
                    self._stats["errors"] += 1

                # Sleep only for stream interval (~67ms) — NOT detection interval
                self._stop_event.wait(STREAM_INTERVAL)

        except Exception as e:
            logger.error("[Vision] Camera loop fatal error: %s", e)
            self._stats["errors"] += 1
        finally:
            if self._camera is not None:
                self._camera.release()
                self._camera = None
            self._stats["camera_active"] = False
            self._running = False

    def _process_frame(self, frame: np.ndarray, run_detection: bool = True):
        """Process a single camera frame.

        Args:
            frame: BGR frame from OpenCV
            run_detection: If True, run expensive MTCNN+FaceNet detection.
                          If False, just update the MJPEG stream with cached overlays.
        """
        import cv2

        self._stats["frames_processed"] += 1
        self._latest_raw_frame = frame.copy()

        if run_detection:
            faces = self._engine.detect_faces(frame)
            self._current_faces = faces
            # ── Emotion analysis on detection frames ──
            if self._emotion_engine and self._emotion_engine.available and faces:
                try:
                    emotions = self._emotion_engine.analyze_frame(frame)
                    self._emotion_engine.match_emotions_to_faces(emotions, faces)
                except Exception as e:
                    logger.debug("[Vision] Emotion analysis skipped: %s", e)
        else:
            faces = self._current_faces  # reuse cached detections
        now = time.time()

        # Draw bounding boxes and labels on the frame for MJPEG stream
        annotated = frame.copy()
        for f in faces:
            bb = f["bbox"]
            identity = f["identity"]
            conf = f["recognition_confidence"]
            det_conf = f["detection_confidence"]

            color = (0, 255, 0) if identity else (0, 165, 255)  # green=known, orange=unknown
            cv2.rectangle(annotated, (bb["x1"], bb["y1"]), (bb["x2"], bb["y2"]), color, 2)

            label = f"{identity} ({conf:.0%})" if identity else f"Unknown ({det_conf:.0%})"
            # ── Emotion label ──
            dominant_emotion = f.get("dominant_emotion")
            if dominant_emotion:
                emoji_map = {"happy": "😊", "sad": "😢", "angry": "😠", "fear": "😨",
                             "disgust": "🤢", "surprise": "😮", "neutral": "😐"}
                emoji = emoji_map.get(dominant_emotion, "")
                label += f" {emoji}{dominant_emotion}"
            # Label background
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(annotated, (bb["x1"], bb["y1"] - th - 8),
                          (bb["x1"] + tw + 4, bb["y1"]), color, -1)
            cv2.putText(annotated, label, (bb["x1"] + 2, bb["y1"] - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        # Status overlay
        status_text = f"Faces: {len(faces)} | Frames: {self._stats['frames_processed']}"
        cv2.putText(annotated, status_text, (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)

        # Encode to JPEG for streaming
        _, jpeg_buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
        self._latest_jpeg = jpeg_buf.tobytes()

        # Only update presence/events on detection frames (not every stream frame)
        if not run_detection:
            return

        if faces:
            self._stats["faces_detected"] += len(faces)
            self._last_detection_time = now

            identified = [f for f in faces if f["identity"]]
            self._stats["identities_recognized"] += len(identified)

            was_present = self._humans_present
            self._humans_present = True

            # Trigger presence event if:
            # 1. Humans just appeared (transition from empty → present)
            # 2. Cooldown has passed since last trigger
            if (not was_present or (now - self._last_presence_trigger > PRESENCE_COOLDOWN)):
                self._last_presence_trigger = now
                self._stats["presence_triggers"] += 1
                self._fire_presence_event(faces)

        else:
            # No faces — mark as no humans after 10 seconds of emptiness
            if self._humans_present and (now - self._last_detection_time > 10):
                self._humans_present = False
                self._fire_departure_event()

    def _fire_presence_event(self, faces: list[dict]):
        """Send human-detected event to XDART."""
        identities = [f["identity"] for f in faces if f["identity"]]
        unknown_count = sum(1 for f in faces if not f["identity"])

        event = {
            "event_type": "human_detected",
            "timestamp": datetime.now(ATHENS_TZ).isoformat(),
            "faces_count": len(faces),
            "identified": identities,
            "unknown_count": unknown_count,
            "details": [
                {
                    "identity": f["identity"],
                    "confidence": f["recognition_confidence"],
                    "bbox": f["bbox"],
                    # ── Emotion data ──
                    "dominant_emotion": f.get("dominant_emotion"),
                    "emotion": f.get("emotion", {}),
                    "emotion_confidence": f.get("emotion_confidence"),
                }
                for f in faces
            ],
            # Aggregate emotion summary
            "emotion_summary": _summarize_emotions(faces),
        }

        # Log with emotion info
        emotion_suffix = ""
        emotion_faces = [f for f in faces if f.get("dominant_emotion")]
        if emotion_faces:
            emotion_suffix = " | Emotions: " + ", ".join(
                f"{f.get('identity') or 'unknown'}:{f['dominant_emotion']}"
                for f in emotion_faces
            )

        logger.info("[Vision] 👁 HUMAN DETECTED: %d faces (%s, %d unknown)%s",
                    len(faces),
                    ", ".join(identities) if identities else "all unknown",
                    unknown_count,
                    emotion_suffix)

        self._send_callback(event)

    def _fire_departure_event(self):
        """Send human-departed event to XDART."""
        event = {
            "event_type": "human_departed",
            "timestamp": datetime.now(ATHENS_TZ).isoformat(),
        }
        logger.info("[Vision] 👁 Humans departed from view")
        self._send_callback(event)

    def _send_callback(self, event: dict):
        """Send event to XDART main server via HTTP POST."""
        import httpx

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(self._callback_url, json=event)
                if resp.status_code != 200:
                    logger.warning("[Vision] Callback HTTP %d: %s",
                                   resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("[Vision] Callback failed: %s", e)

    @property
    def status(self) -> dict:
        """Current camera and detection status."""
        return {
            **self._stats,
            "humans_present": self._humans_present,
            "current_faces": len(self._current_faces),
            "known_identities": self._engine.known_identities,
            "detection_interval": DETECTION_INTERVAL,
            "recognition_threshold": RECOGNITION_THRESHOLD,
            "presence_cooldown": PRESENCE_COOLDOWN,
        }


# ── FastAPI Application ──

def create_vision_app():
    """Create the Vision microservice FastAPI app."""
    from fastapi import FastAPI, UploadFile, File, Form
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    engine = FaceRecognitionEngine()
    emotion_engine = EmotionEngine()
    camera_loop = CameraLoop(engine, XDART_CALLBACK_URL, emotion_engine=emotion_engine)

    @asynccontextmanager
    async def lifespan(app):
        # Startup — initialize FaceNet engine, do NOT start camera
        # (camera is now managed by browser via getUserMedia + COCO-SSD)
        logger.info("[Vision] Initializing FaceNet engine...")
        engine.initialize()
        if EMOTION_ENABLED:
            logger.info("[Vision] Initializing EmotionEngine...")
            emotion_engine.initialize()
        yield
        # Shutdown
        camera_loop.stop()

    app = FastAPI(
        title="XDART-Φ Vision Service",
        description="Αίολος' Eyes — Face detection and recognition via FaceNet",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/status")
    async def get_status():
        """Get vision system status."""
        return camera_loop.status

    @app.get("/identities")
    async def list_identities():
        """List all registered face identities."""
        return {
            "identities": engine.known_identities,
            "count": len(engine.known_identities),
        }

    @app.post("/detect")
    async def detect_from_upload(image: UploadFile = File(None), file: UploadFile = File(None)):
        """Detect and identify faces in an uploaded image.

        Accepts either 'image' (from browser COCO-SSD) or 'file' field name.
        Returns face detections with optional emotion analysis.
        """
        import cv2

        upload = image or file
        if not upload:
            return JSONResponse(status_code=400, content={"error": "No image provided. Send as 'image' or 'file' field."})

        contents = await upload.read()
        nparr = np.frombuffer(contents, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            logger.warning("[Vision] /detect: failed to decode uploaded image (%d bytes)", len(contents))
            return JSONResponse(status_code=400, content={"error": "Invalid image"})

        logger.info("[Vision] /detect: image %dx%d (%d bytes)", frame.shape[1], frame.shape[0], len(contents))
        faces = engine.detect_faces(frame)

        # ── Emotion analysis ──
        emotion_results = []
        if EMOTION_ENABLED and emotion_engine.available and faces:
            try:
                emotions = emotion_engine.analyze_frame(frame)
                emotion_engine.match_emotions_to_faces(emotions, faces)
                emotion_results = emotions
                logger.info("[Vision] /detect: emotion analysis done — %d faces with emotions",
                           sum(1 for f in faces if f.get('dominant_emotion')))
            except Exception as e:
                logger.debug("[Vision] /detect: emotion analysis failed (non-critical): %s", e)

        logger.info("[Vision] /detect: found %d face(s) — identities: %s",
                    len(faces), [f.get('identity') for f in faces])
        return {
            "faces_count": len(faces),
            "faces": faces,
            "emotions": emotion_results,
            "timestamp": datetime.now(ATHENS_TZ).isoformat(),
        }

    @app.post("/detect-emotion")
    async def detect_emotion(image: UploadFile = File(None), file: UploadFile = File(None)):
        """Analyze emotions in an uploaded image. Returns per-face emotion probabilities.

        Independent of face recognition — uses DeepFace directly.
        """
        import cv2

        if not EMOTION_ENABLED:
            return JSONResponse(status_code=503, content={"error": "Emotion detection is disabled. Set VISION_EMOTION_ENABLED=1"})

        upload = image or file
        if not upload:
            return JSONResponse(status_code=400, content={"error": "No image provided."})

        contents = await upload.read()
        nparr = np.frombuffer(contents, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return JSONResponse(status_code=400, content={"error": "Invalid image"})

        if not emotion_engine.available:
            emotion_engine.initialize()
            if not emotion_engine.available:
                return JSONResponse(status_code=503, content={"error": "Emotion engine not available. Install deepface: pip install deepface tensorflow"})

        emotions = emotion_engine.analyze_frame(frame)
        logger.info("[Vision] /detect-emotion: %d face(s) analyzed", len(emotions))

        summary = {}
        if emotions:
            all_dominants = [e.get("dominant_emotion", "neutral") for e in emotions]
            summary = {
                "total_faces": len(emotions),
                "dominant_emotions": all_dominants,
                "overall_mood": max(set(all_dominants), key=all_dominants.count) if all_dominants else "neutral",
            }

        return {
            "faces_count": len(emotions),
            "emotions": emotions,
            "summary": summary,
            "timestamp": datetime.now(ATHENS_TZ).isoformat(),
        }

    @app.get("/detect-emotion/status")
    async def emotion_status():
        """Check if emotion detection is available."""
        return {
            "enabled": EMOTION_ENABLED,
            "available": emotion_engine.available,
            "backend": EMOTION_DETECTOR_BACKEND,
            "labels": EmotionEngine.EMOTION_LABELS,
        }

    @app.post("/register")
    async def register_face(
        name: str = Form(...),
        file: UploadFile = File(...),
    ):
        """Register a new face identity from an uploaded image."""
        import cv2

        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return JSONResponse(status_code=400, content={"error": "Invalid image"})

        success = engine.register_face(name, frame)
        if success:
            return {"status": "registered", "name": name,
                    "total_samples": len(engine._known_embeddings.get(name, []))}
        else:
            return JSONResponse(status_code=400,
                                content={"error": "No face detected in image"})

    @app.post("/camera/start")
    async def start_camera():
        """Start the camera capture loop."""
        camera_loop.start()
        return {"status": "started"}

    @app.post("/camera/stop")
    async def stop_camera():
        """Stop the camera capture loop."""
        camera_loop.stop()
        return {"status": "stopped"}

    @app.get("/stream")
    async def mjpeg_stream():
        """MJPEG video stream — annotated camera feed with face bounding boxes.

        Connect from <img src="http://localhost:8100/stream"> or
        an HTML <img> tag to see live annotated video.
        """
        from starlette.responses import StreamingResponse

        async def generate():
            while True:
                jpeg = camera_loop._latest_jpeg
                if jpeg:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + jpeg
                        + b"\r\n"
                    )
                await asyncio.sleep(0.15)  # ~6-7 fps for the stream

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/snapshot")
    async def snapshot():
        """Get the latest annotated JPEG frame as a single image."""
        from fastapi.responses import Response

        jpeg = camera_loop._latest_jpeg
        if not jpeg:
            return JSONResponse(status_code=503, content={"error": "No frame available yet"})
        return Response(content=jpeg, media_type="image/jpeg")

    return app


# ── Standalone runner ──

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    app = create_vision_app()
    uvicorn.run(app, host="0.0.0.0", port=VISION_PORT, log_level="info")
