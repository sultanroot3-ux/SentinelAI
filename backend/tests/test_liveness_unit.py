"""Unit tests: LivenessMonitor temporal anti-spoofing signals.

Uses synthetic face objects — no camera or insightface model needed.
"""
import numpy as np
import pytest

from app.services.face_service import (
    LivenessMonitor,
    _LEFT_EYE_IDX,
    _RIGHT_EYE_IDX,
    _eye_openness,
)

rng = np.random.default_rng(42)


class FakeFace:
    def __init__(self, kps, lmk, pose, bbox=(100, 100, 300, 340)):
        self.kps = kps
        self.landmark_2d_106 = lmk
        self.pose = pose
        self.bbox = np.array(bbox, dtype=np.float32)


BASE_KPS = np.array(
    [[160, 170], [240, 170], [200, 220], [170, 270], [230, 270]], dtype=np.float32
)
BASE_POSE = np.array([2.0, -1.0, 0.5], dtype=np.float32)


def base_landmarks():
    lmk = rng.uniform(120, 320, size=(106, 2)).astype(np.float32)
    for idx, cx, cy in ((_LEFT_EYE_IDX, 160, 170), (_RIGHT_EYE_IDX, 240, 170)):
        t = np.linspace(0, 2 * np.pi, len(idx), endpoint=False)
        lmk[idx, 0] = cx + 15 * np.cos(t)
        lmk[idx, 1] = cy + 6 * np.sin(t)
    return lmk


BASE_LMK = base_landmarks()


def eyes_closed(lmk):
    out = lmk.copy()
    for idx in (_LEFT_EYE_IDX, _RIGHT_EYE_IDX):
        cy = out[idx, 1].mean()
        out[idx, 1] = cy + (out[idx, 1] - cy) * 0.12
    return out


def run_frames(frames):
    m = LivenessMonitor()
    verdict = None
    for f in frames:
        verdict = m.update(f)
    return verdict


def test_eye_openness_drops_when_closed():
    open_ratio = _eye_openness(BASE_LMK, _LEFT_EYE_IDX)
    closed_ratio = _eye_openness(eyes_closed(BASE_LMK), _LEFT_EYE_IDX)
    assert closed_ratio < 0.5 * open_ratio


def test_static_photo_fails():
    frames = [FakeFace(BASE_KPS, BASE_LMK, BASE_POSE) for _ in range(30)]
    assert run_frames(frames)["passed"] is False


def test_handheld_photo_fails():
    """Rigid translation/scale jitter must not count as liveness."""
    frames = []
    for _ in range(30):
        dx, dy = rng.normal(0, 4, 2)
        s = 1 + rng.normal(0, 0.01)
        frames.append(
            FakeFace(
                BASE_KPS * s + [dx, dy],
                BASE_LMK * s + [dx, dy],
                BASE_POSE + rng.normal(0, 0.05, 3).astype(np.float32),
            )
        )
    assert run_frames(frames)["passed"] is False


def test_live_face_with_blink_passes():
    frames = []
    for i in range(30):
        kps = BASE_KPS + rng.normal(0, 1.2, BASE_KPS.shape).astype(np.float32)
        lmk = BASE_LMK + rng.normal(0, 1.0, BASE_LMK.shape).astype(np.float32)
        if 14 <= i <= 16:
            lmk = eyes_closed(lmk)
        pose = BASE_POSE + rng.normal(0, 1.0, 3).astype(np.float32)
        frames.append(FakeFace(kps, lmk, pose))
    verdict = run_frames(frames)
    assert verdict["passed"] is True
    assert verdict["blinks"] >= 1


def test_collecting_phase_returns_none():
    m = LivenessMonitor(min_samples=8)
    verdict = m.update(FakeFace(BASE_KPS, BASE_LMK, BASE_POSE))
    assert verdict["passed"] is None


def test_invalid_box_fails():
    m = LivenessMonitor()
    verdict = m.update(FakeFace(BASE_KPS, BASE_LMK, BASE_POSE, bbox=(10, 10, 10, 10)))
    assert verdict["passed"] is False
