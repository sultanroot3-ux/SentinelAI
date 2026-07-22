"""Local webcam MJPEG streaming via OpenCV.

Two stream flavours:
- mjpeg_generator: raw camera frames.
- analyzed_mjpeg_generator: runs the SentinelAI face pipeline on every Nth
  frame and draws recognition overlays (green = recognized, red = unknown,
  amber = liveness pending/failed) onto the stream.
"""
import logging
import time

logger = logging.getLogger("sentinelai.camera")

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def _parse_source(source: str):
    """Camera source '0' -> device index 0; anything else is a URL/path."""
    try:
        return int(source)
    except (TypeError, ValueError):
        return source


def camera_available(source: str = "0") -> bool:
    """Check whether the camera can be opened right now."""
    if cv2 is None:
        return False
    cap = cv2.VideoCapture(_parse_source(source))
    try:
        if not cap.isOpened():
            return False
        ok, _ = cap.read()
        return bool(ok)
    finally:
        cap.release()


def mjpeg_generator(source: str = "0", fps: float = 15.0):
    """Yield multipart/x-mixed-replace JPEG frames from the camera.

    If the camera is unavailable (or cv2 missing) the generator simply stops,
    so the HTTP response ends gracefully instead of erroring.
    """
    if cv2 is None:
        logger.warning("OpenCV not installed - cannot stream camera.")
        return

    cap = cv2.VideoCapture(_parse_source(source))
    if not cap.isOpened():
        logger.warning("Camera source %r unavailable.", source)
        cap.release()
        return

    frame_interval = 1.0 / max(fps, 1.0)
    try:
        while True:
            start = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                logger.warning("Camera read failed - stopping stream.")
                break
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
            )
            # Throttle to target FPS
            elapsed = time.monotonic() - start
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)
    except GeneratorExit:
        pass
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# AI-analyzed stream
# ---------------------------------------------------------------------------
_COLOR_RECOGNIZED = (80, 200, 80)    # BGR green
_COLOR_UNKNOWN = (60, 60, 230)       # BGR red
_COLOR_PENDING = (60, 190, 240)      # BGR amber


def _draw_overlays(frame, overlays) -> None:
    """Draw cached face boxes + labels onto a frame, in place."""
    for ov in overlays:
        x, y, w, h = ov["box"]
        color = ov["color"]
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        label = ov["label"]
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        ty = y - 8 if y - 8 > th else y + h + th + 8
        cv2.rectangle(frame, (x, ty - th - 4), (x + tw + 6, ty + 4), color, -1)
        cv2.putText(frame, label, (x + 3, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (255, 255, 255), 1, cv2.LINE_AA)


def analyzed_mjpeg_generator(source: str = "0", fps: float = 12.0,
                             analyze_every: int = 4, camera_name: str = "webcam"):
    """MJPEG stream with live face recognition overlays.

    Runs the full pipeline (detect -> liveness -> recognize -> log) on every
    `analyze_every`-th frame; intermediate frames reuse the last overlays so
    the stream stays smooth while inference runs at a lower rate.
    """
    # Local imports avoid a circular import at module load time
    from app.db.database import SessionLocal
    from app.services import face_service

    if cv2 is None:
        logger.warning("OpenCV not installed - cannot stream camera.")
        return

    cap = cv2.VideoCapture(_parse_source(source))
    if not cap.isOpened():
        logger.warning("Camera source %r unavailable.", source)
        cap.release()
        return

    monitor = (
        face_service.LivenessMonitor()
        if face_service.insightface_available()
        else None
    )
    overlays: list[dict] = []
    frame_idx = 0
    frame_interval = 1.0 / max(fps, 1.0)

    try:
        while True:
            start = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                logger.warning("Camera read failed - stopping analyzed stream.")
                break

            if frame_idx % max(analyze_every, 1) == 0:
                db = SessionLocal()
                try:
                    results = face_service.process_image(
                        frame.copy(), db, camera=camera_name,
                        liveness_monitor=monitor,
                    )
                    # Reduce to plain drawing data BEFORE the session closes
                    # (User ORM objects detach once the session is gone).
                    overlays = []
                    for r in results:
                        live = r.get("liveness") or {}
                        if r["match"] is not None and not r.get("note"):
                            label = f"{r['match'].name} {r['score']:.2f}"
                            color = _COLOR_RECOGNIZED
                        elif live.get("passed") is None or r.get("note"):
                            label = r.get("note", "Checking...")[:32] or "Checking..."
                            color = _COLOR_PENDING
                        else:
                            label = "UNKNOWN"
                            color = _COLOR_UNKNOWN
                        overlays.append(
                            {"box": r["box"], "label": label, "color": color}
                        )
                except Exception:
                    logger.exception("Frame analysis failed")
                finally:
                    db.close()
            frame_idx += 1

            _draw_overlays(frame, overlays)
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
            )
            elapsed = time.monotonic() - start
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)
    except GeneratorExit:
        pass
    finally:
        cap.release()
