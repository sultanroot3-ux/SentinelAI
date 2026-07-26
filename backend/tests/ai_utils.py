"""Shared helpers for the real-AI-engine test suite (B1).

Fixture images come from the `insightface` package itself
(`insightface/data/images/`), so the suite needs no biometric data committed
to this repository and runs identically anywhere insightface is installed.

`t1.jpg` is the upstream group photo containing six distinct people; cropping
it gives six independent identities to enroll and match against, which is what
makes a real accuracy/discrimination assertion possible.

Skip policy
-----------
When insightface is not installed these tests skip. That is correct for the
lightweight CI job, but it must NOT be able to happen silently in the job whose
entire purpose is exercising the AI engine — a skipped suite there would
reproduce exactly the regression this suite exists to prevent (CI green while
the recognition path is never executed). Setting SENTINEL_REQUIRE_AI=1 turns
the skip into a hard failure.
"""
import os
from pathlib import Path

import pytest

REQUIRE_AI = os.environ.get("SENTINEL_REQUIRE_AI") == "1"


def _ai_unavailable_reason() -> str | None:
    """Return None when the full AI engine is importable, else why it is not."""
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as exc:
        return f"OpenCV/numpy unavailable: {exc}"
    try:
        import insightface  # noqa: F401
        from insightface.app import FaceAnalysis  # noqa: F401
    except ImportError as exc:
        return f"insightface unavailable: {exc}"
    return None


def require_ai() -> None:
    """Skip the calling test unless the real AI engine is importable.

    With SENTINEL_REQUIRE_AI=1 a missing engine fails instead of skipping.
    """
    reason = _ai_unavailable_reason()
    if reason is None:
        return
    if REQUIRE_AI:
        pytest.fail(
            f"SENTINEL_REQUIRE_AI=1 but the AI engine is not usable: {reason}. "
            "This job must exercise insightface, not the Haar fallback."
        )
    pytest.skip(reason)


def sample_images_dir() -> Path:
    """Directory of face images bundled with the installed insightface."""
    import insightface

    return Path(insightface.__file__).parent / "data" / "images"


def group_photo_path() -> Path:
    return sample_images_dir() / "t1.jpg"


def crop_faces_as_jpeg(min_faces: int = 6) -> list[bytes]:
    """Detect every face in the upstream group photo; return one JPEG per face.

    Ordered left-to-right by bounding box so indices are stable across runs.
    Each crop is padded by 35% of the face size, which is what the detector
    needs to re-detect the face in the standalone image.
    """
    import cv2

    from app.services import face_service

    img = cv2.imread(str(group_photo_path()))
    assert img is not None, f"could not read {group_photo_path()}"

    faces = face_service._get_insightface_app().get(img)
    assert len(faces) >= min_faces, (
        f"expected >= {min_faces} faces in the insightface sample photo, "
        f"got {len(faces)} — the bundled fixture image may have changed"
    )
    faces = sorted(faces, key=lambda f: f.bbox[0])

    crops: list[bytes] = []
    for face in faces:
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        pad = int(0.35 * max(x2 - x1, y2 - y1))
        crop = img[
            max(0, y1 - pad): min(img.shape[0], y2 + pad),
            max(0, x1 - pad): min(img.shape[1], x2 + pad),
        ]
        ok, buf = cv2.imencode(".jpg", crop)
        assert ok, "failed to encode face crop"
        crops.append(buf.tobytes())
    assert len(crops) >= min_faces
    return crops


def not_a_face_jpeg() -> bytes:
    """A valid JPEG containing no face (deterministic gradient)."""
    import cv2
    import numpy as np

    img = np.zeros((240, 320, 3), dtype=np.uint8)
    img[:, :, 0] = np.linspace(0, 255, 320, dtype=np.uint8)[None, :]
    img[:, :, 1] = np.linspace(0, 255, 240, dtype=np.uint8)[:, None]
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()
