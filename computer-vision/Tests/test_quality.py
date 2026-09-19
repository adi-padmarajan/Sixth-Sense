"""Provisional image-quality boundaries and explicit region mirroring."""
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scene_state import (SceneState, image_quality, detections_from_result,
                         LUMINANCE_FLOOR, LUMINANCE_CEILING, CONTRAST_FLOOR)


def gray_pair(a, b):
    return np.array([[[a] * 3, [b] * 3]], dtype=np.uint8)


@pytest.mark.parametrize('a,b,expected', [
    (LUMINANCE_FLOOR - 9, LUMINANCE_FLOOR + 8, 'too_dark'),
    (LUMINANCE_FLOOR - 8, LUMINANCE_FLOOR + 8, 'ok'),
    (LUMINANCE_FLOOR - 8, LUMINANCE_FLOOR + 9, 'ok'),
    (LUMINANCE_CEILING - 9, LUMINANCE_CEILING + 8, 'ok'),
    (LUMINANCE_CEILING - 8, LUMINANCE_CEILING + 8, 'ok'),
    (LUMINANCE_CEILING - 8, LUMINANCE_CEILING + 9, 'too_bright'),
    (128 - CONTRAST_FLOOR, 128 + CONTRAST_FLOOR - 1, 'low_contrast'),
    (128 - CONTRAST_FLOOR, 128 + CONTRAST_FLOOR, 'ok'),
    (128 - CONTRAST_FLOOR, 128 + CONTRAST_FLOOR + 1, 'ok'),
    (0, 0, 'too_dark'), (255, 255, 'too_bright'), (128, 128, 'low_contrast'),
])
def test_quality_boundaries(a, b, expected):
    frame = gray_pair(a, b)
    assert image_quality(frame) == expected
    state = SceneState(clock=lambda: 10)
    state.update(frame, None, {}, 'simulated')
    snapshot = state.read(0)
    assert snapshot.quality == expected
    assert snapshot.captured_at == 10 and snapshot.detections == []


def test_mirrored_regions_swap_only_labels():
    boxes = SimpleNamespace(xyxy=np.array([[0, 0, 2, 2], [14, 0, 16, 2], [28, 0, 30, 2]]),
                            cls=np.array([0, 0, 0]), conf=np.array([.7, .7, .7]), id=None)
    normal = detections_from_result(boxes, {0: 'person'}, 30)
    mirrored = detections_from_result(boxes, {0: 'person'}, 30, mirrored=True)
    assert [d.region for d in normal] == ['left', 'center', 'right']
    assert [d.region for d in mirrored] == ['right', 'center', 'left']
    assert [d.xyxy for d in normal] == [d.xyxy for d in mirrored]
    assert all(d.mirrored for d in mirrored)
    assert not any(d.mirrored for d in normal)
    state = SceneState()
    state.update(np.zeros((3, 30, 3), dtype=np.uint8), boxes, {0: 'person'}, 'simulated', mirrored=True)
    assert state.read().detections == mirrored


@pytest.mark.parametrize('names', [{0: 'chair'}, ['chair']])
def test_unknown_class_skipped_without_losing_valid_detection(names, caplog):
    boxes = SimpleNamespace(xyxy=np.array([[0, 0, 2, 2]] * 4), cls=np.array([99, 0, -1, .5]),
                            conf=np.array([.7] * 4), id=None)
    detections = detections_from_result(boxes, names, 30)
    assert [d.class_name for d in detections] == ['chair']
    assert 'reason=unknown_class_id' in caplog.text
    assert 'reason=invalid_class_id' in caplog.text
