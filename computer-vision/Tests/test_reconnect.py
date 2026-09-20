"""Camera failures and display controls, with no checkpoint, camera or GUI."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import track_distances as tracking
from scene_state import SceneState


@pytest.fixture
def camera(monkeypatch):
    tracker = Mock()
    dataset = SimpleNamespace(close=Mock())
    predictor = SimpleNamespace(trackers=[tracker], dataset=dataset, vid_path=['old'], _feats='old')
    model = SimpleNamespace(names={}, predictor=predictor, track=Mock())
    monkeypatch.setattr(tracking, 'YOLO', lambda _: model)
    monkeypatch.setattr(tracking, 'MODEL_PATH', SimpleNamespace(is_file=lambda: True))
    monkeypatch.setattr(tracking, 'SOURCE', 0)
    show = Mock()
    monkeypatch.setattr(tracking.cv2, 'imshow', show)
    monkeypatch.setattr(tracking.cv2, 'destroyAllWindows', Mock())
    frame = np.tile(np.arange(120, dtype=np.uint8), (80, 1))[..., None].repeat(3, axis=2)
    result = SimpleNamespace(orig_img=frame, boxes=None, plot=lambda: frame.copy())
    return SimpleNamespace(model=model, tracker=tracker, show=show, result=result)


@pytest.mark.parametrize('raises', [False, True])
def test_live_loss_resets_and_reopens(camera, monkeypatch, raises, caplog):
    state = SceneState()
    observed = []

    def first():
        yield camera.result
        observed.append(state.session_generation)
        if raises:
            raise RuntimeError('private backend details')

    camera.model.track.side_effect = [first(), iter([camera.result])]

    def reconnect(delay, attempt, status, **_kwargs):
        assert state.read(0.5) is None
        assert state.session_generation == observed[0] + 1
        camera.tracker.reset.assert_called_once()
        assert delay == 0.5 and attempt == 1
        return True

    monkeypatch.setattr(tracking, 'wait_to_reconnect', reconnect)
    monkeypatch.setattr(tracking.cv2, 'waitKey', Mock(side_effect=[-1, ord('q')]))
    tracking.main(state)
    assert camera.model.track.call_count == 2
    assert state.read() is None
    assert 'live_stream_failed' in caplog.text if raises else 'live_stream_ended' in caplog.text
    assert 'private backend details' not in caplog.text


def test_replay_exhaustion_is_normal(camera, monkeypatch):
    monkeypatch.setattr(tracking, 'SOURCE', 'local.mp4')
    camera.model.track.return_value = iter([camera.result])
    retry = Mock()
    monkeypatch.setattr(tracking, 'wait_to_reconnect', retry)
    monkeypatch.setattr(tracking.cv2, 'waitKey', lambda _: -1)
    tracking.main()
    camera.model.track.assert_called_once()
    retry.assert_not_called()


def test_q_exits_placeholder_after_failed_open(camera, monkeypatch):
    camera.model.track.side_effect = OSError('camera gone')
    monkeypatch.setattr(tracking.cv2, 'waitKey', lambda _: ord('q'))
    text = Mock(wraps=tracking.cv2.putText)
    monkeypatch.setattr(tracking.cv2, 'putText', text)
    tracking.main(preview_status=lambda: 'fake')
    camera.model.track.assert_called_once()
    assert camera.show.call_args.args[1].shape == tracking.UNAVAILABLE_FRAME_SHAPE
    captions = [c.args[1] for c in text.call_args_list]
    assert 'CAMERA UNAVAILABLE' in captions
    assert 'cloud fake | camera unavailable' in captions
    assert any('attempt 1' in s for s in captions)


def test_backoff_doubles_caps_and_keeps_retrying(camera, monkeypatch):
    camera.model.track.side_effect = OSError('offline')
    delays = []

    def retry(delay, attempt, _, **_kwargs):
        delays.append(delay)
        return attempt < 7

    monkeypatch.setattr(tracking, 'wait_to_reconnect', retry)
    tracking.main()
    assert delays == [0.5, 1, 2, 4, 5, 5, 5]


def test_placeholder_pumps_gui_through_delay(camera, monkeypatch):
    monkeypatch.setattr(tracking.cv2, 'waitKey', lambda _: -1)
    clock = iter([0, 0.1, 0.3, 0.5])
    assert tracking.wait_to_reconnect(.5, 2, lambda: 'off', clock=lambda: next(clock))
    assert camera.show.call_count == 3


def test_headless_mode_never_touches_gui(camera, monkeypatch):
    """show_preview=False must not call imshow/waitKey/destroyAllWindows,
    since those crash without a display (Qt "xcb" platform plugin)."""
    camera.model.track.return_value = iter([camera.result])
    waitkey = Mock(return_value=-1)
    destroy = Mock()
    reconnect = Mock(return_value=False)  # quit after the (mocked) one reconnect wait
    monkeypatch.setattr(tracking.cv2, 'waitKey', waitkey)
    monkeypatch.setattr(tracking.cv2, 'destroyAllWindows', destroy)
    monkeypatch.setattr(tracking, 'wait_to_reconnect', reconnect)
    tracking.main(show_preview=False)
    camera.show.assert_not_called()
    waitkey.assert_not_called()
    destroy.assert_not_called()
    assert reconnect.call_args.kwargs.get('show_preview') is False


def test_headless_reconnect_waits_without_gui(monkeypatch):
    clock = iter([0, 0.2, 0.6])
    show = Mock()
    monkeypatch.setattr(tracking.cv2, 'imshow', show)
    monkeypatch.setattr(tracking.time, 'sleep', Mock())
    assert tracking.wait_to_reconnect(.5, 1, lambda: 'off', clock=lambda: next(clock), show_preview=False)
    show.assert_not_called()


def test_reset_hook_clears_scene_and_tracker_together(camera):
    state = SceneState()
    state.update(camera.result.orig_img, None, {}, 'live')
    before = state.session_generation
    tracking.reset_session(camera.model, state)
    assert state.read() is None and state.session_generation == before + 1
    camera.tracker.reset.assert_called_once()
    assert camera.model.predictor._feats is None
    assert camera.model.predictor.vid_path == [None]


def test_mirror_changes_only_display(camera, monkeypatch):
    camera.model.track.return_value = iter([camera.result])
    monkeypatch.setattr(tracking, 'MIRROR_PREVIEW', True)
    monkeypatch.setattr(tracking.cv2, 'waitKey', lambda _: ord('q'))
    monkeypatch.setattr(tracking, 'overlay_status', lambda *args: None)
    state = SceneState()
    snapshots = []
    camera.result.plot = lambda: (snapshots.append(state.read()) or camera.result.orig_img.copy())
    tracking.main(state)
    np.testing.assert_array_equal(snapshots[0].frame, camera.result.orig_img)
    np.testing.assert_array_equal(camera.show.call_args.args[1], camera.result.orig_img[:, ::-1])


def test_unknown_label_does_not_reach_ultralytics_plot(camera, monkeypatch):
    camera.result.boxes = SimpleNamespace(xyxy=np.array([[0, 0, 2, 2]]), cls=np.array([99]),
                                         conf=np.array([.8]), id=None)
    camera.result.plot = Mock(side_effect=KeyError(99))
    camera.model.track.return_value = iter([camera.result])
    monkeypatch.setattr(tracking.cv2, 'waitKey', lambda _: ord('q'))
    tracking.main()
    camera.result.plot.assert_not_called()
    camera.show.assert_called_once()


@pytest.mark.parametrize('kind', ['byte', 'bot'])
def test_reset_hook_resets_installed_tracker_ids_without_weights(kind):
    from ultralytics.trackers.byte_tracker import BYTETracker, STrack
    from ultralytics.trackers.bot_sort import BOTSORT
    args = SimpleNamespace(track_buffer=30, gmc_method=None, proximity_thresh=.5,
                           appearance_thresh=.8, with_reid=False, model='auto')
    tracker = (BYTETracker if kind == 'byte' else BOTSORT)(args)
    state = SceneState()
    tracker.frame_id = 42
    tracker.tracked_stracks = [object()]
    tracker.lost_stracks = [object()]
    tracker.removed_stracks = [object()]
    assert STrack.next_id() == 1
    assert STrack.next_id() == 2
    model = SimpleNamespace(predictor=SimpleNamespace(trackers=[tracker]))
    tracking.reset_session(model, state)
    assert tracker.frame_id == 0
    assert tracker.tracked_stracks == tracker.lost_stracks == tracker.removed_stracks == []
    assert STrack.next_id() == 1
    tracker.reset()
