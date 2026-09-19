"""Offline scene-state tests: no camera, model construction, checkpoint, or network."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import importlib
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import warnings

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scene_state import Detection, SceneState, detections_from_result, to_text


class FakeClock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now


def fake_boxes(xyxy=(), classes=None, conf=None, ids=None):
    """Only the four .tolist()-supporting arrays read by the extractor."""
    count = len(xyxy)
    return SimpleNamespace(
        xyxy=np.asarray(xyxy, dtype=float),
        cls=np.asarray(classes if classes is not None else [7] * count),
        conf=np.asarray(conf if conf is not None else [0.71] * count),
        id=None if ids is None else np.asarray(ids),
    )


class DetectionTests(unittest.TestCase):
    def test_uses_supplied_names_and_preserves_original_float_coordinates(self):
        boxes = fake_boxes([[1.25, 2.5, 9.75, 6.5]], ids=[42])
        detection, = detections_from_result(boxes, {7: "custom checkpoint label"}, 30)
        self.assertEqual(detection.class_name, "custom checkpoint label")
        self.assertEqual(detection.class_id, 7)
        self.assertEqual(detection.xyxy, (1.25, 2.5, 9.75, 6.5))
        self.assertTrue(all(isinstance(value, float) for value in detection.xyxy))
        self.assertEqual(detection.track_id, 42)
        self.assertIsInstance(detection.track_id, int)

    def test_regions_and_exact_boundaries(self):
        centers = [5, 10, 15, 20, 25]
        boxes = fake_boxes([[x - 1, 0, x + 1, 2] for x in centers])
        detections = detections_from_result(boxes, {7: "chair"}, 30)
        self.assertEqual([d.region for d in detections], ["left", "center", "center", "right", "right"])

    def test_missing_ids_are_none(self):
        boxes = fake_boxes([[0, 0, 2, 2], [10, 0, 12, 2]])
        self.assertEqual([d.track_id for d in detections_from_result(boxes, {7: "chair"}, 30)], [None, None])

    def test_none_and_empty_boxes(self):
        self.assertEqual(detections_from_result(None, {}, 30), [])
        self.assertEqual(detections_from_result(fake_boxes(), {}, 30), [])

    def test_invalid_coordinates_skipped_without_losing_valid_boxes(self):
        boxes = fake_boxes([
            [1, 1, 3, 4], [np.nan, 0, 3, 4], [0, 0, np.inf, 4],
            [0, -np.inf, 3, 4], [2, 0, 2, 4], [0, 4, 3, 4],
            [3, 0, 2, 4], [20, 1, 22, 4],
        ], ids=list(range(8)))
        detections = detections_from_result(boxes, {7: "chair"}, 30)
        self.assertEqual([d.track_id for d in detections], [0, 7])

    def test_nonfinite_metadata_never_leaks_into_evidence(self):
        boxes = fake_boxes([[0, 0, 2, 2]] * 3, classes=[np.nan, 7, 7],
                           conf=[0.7, np.inf, 0.8], ids=[1, 2, np.nan])
        detection, = detections_from_result(boxes, {7: "chair"}, 30)
        self.assertIsNone(detection.track_id)
        self.assertEqual(detection.conf, 0.8)

    def test_unknown_class_is_not_given_an_invented_label(self):
        with self.assertLogs("scene_state", level="WARNING") as logs:
            self.assertEqual(detections_from_result(fake_boxes([[0, 0, 2, 2]]), {}, 30), [])
        self.assertIn("reason=unknown_class_id", logs.output[0])

    def test_invalid_width_rejected(self):
        for width in (0, -1, np.nan, np.inf):
            with self.subTest(width=width), self.assertRaises(ValueError):
                detections_from_result(None, {}, width)

    def test_text_for_populated_empty_and_unknown_age(self):
        detections = [
            Detection(7, "chair", 0.71, (0., 0., 2., 2.), None, "left"),
            Detection(99, "person", 0.82, (10., 0., 12., 2.), 5, "center"),
        ]
        self.assertEqual(to_text(detections, 0.08), "Detected (age 80 ms): chair left 0.71, person center 0.82")
        self.assertEqual(to_text([], 0.08), "Detected (age 80 ms): none")
        self.assertEqual(to_text([], None), "Detected (age unknown): none")


class SceneStateTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.state = SceneState(clock=self.clock)
        self.frame = np.zeros((6, 30, 3), dtype=np.uint8)

    def publish(self, boxes=None, mode="simulated"):
        self.state.update(self.frame, boxes, {7: "chair"}, mode)

    def test_empty_before_update_and_after_reset(self):
        self.assertIsNone(self.state.read())
        self.assertIsNone(self.state.age_s())
        self.publish()
        self.state.reset()
        self.assertIsNone(self.state.read())
        self.assertIsNone(self.state.age_s())

    def test_session_generation_changes_on_reset_not_update(self):
        self.publish()
        first = self.state.read()
        self.publish()
        self.assertEqual(self.state.read().session_generation, first.session_generation)
        self.state.reset()
        self.assertNotEqual(self.state.session_generation, first.session_generation)
        self.publish()
        self.assertEqual(self.state.read().session_generation, self.state.session_generation)

    def test_none_and_empty_boxes_still_publish_snapshot(self):
        for boxes in (None, fake_boxes()):
            with self.subTest(boxes=boxes):
                self.publish(boxes)
                snapshot = self.state.read()
                self.assertEqual(snapshot.detections, [])
                self.assertIsInstance(snapshot.detections, list)
                self.assertEqual((snapshot.width, snapshot.height), (30, 6))
                self.assertEqual(snapshot.source_mode, "simulated")
                self.assertEqual(snapshot.captured_at, 10.0)
                np.testing.assert_array_equal(snapshot.frame, self.frame)

    def test_fresh_boundary_and_stale_reads(self):
        self.publish()
        self.assertIsNotNone(self.state.read(max_age_s=0))
        self.clock.now += 0.5
        self.assertEqual(self.state.age_s(), 0.5)
        self.assertIsNotNone(self.state.read(max_age_s=0.5))
        self.clock.now += 0.01
        self.assertIsNone(self.state.read(max_age_s=0.5))
        self.assertIsNotNone(self.state.read())
        self.assertAlmostEqual(self.state.age_s(), 0.51)

    def test_invalid_max_age_rejected(self):
        for limit in (-1, np.nan, np.inf):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.state.read(max_age_s=limit)

    def test_sequence_latest_only_and_session_reset(self):
        self.publish(mode="live")
        first = self.state.read()
        self.frame[:] = 8
        self.clock.now = 11.0
        self.publish(mode="replay")
        second = self.state.read()
        self.assertEqual((first.sequence, second.sequence), (1, 2))
        self.assertEqual(second.captured_at, 11.0)
        self.assertEqual(second.source_mode, "replay")
        self.assertTrue((first.frame == 0).all())
        self.assertTrue((second.frame == 8).all())
        self.state.reset()
        self.publish()
        self.assertEqual(self.state.read().sequence, 1)

    def test_snapshot_isolated_from_source_and_reader_mutations(self):
        boxes = fake_boxes([[0, 0, 2, 2]])
        self.publish(boxes)
        snapshot = self.state.read()
        self.frame[:] = 255
        boxes.xyxy[:] = 99
        with self.assertRaises(FrozenInstanceError):
            snapshot.sequence = 99
        with self.assertRaises(FrozenInstanceError):
            snapshot.detections[0].class_name = "wrong"
        with self.assertRaises(TypeError):
            snapshot.detections.append(snapshot.detections[0])
        with self.assertRaises(TypeError):
            snapshot.detections[0] = snapshot.detections[0]
        with self.assertRaises(ValueError):
            snapshot.frame[0, 0, 0] = 9
        with self.assertRaises(ValueError):
            snapshot.frame.setflags(write=True)
        # Older NumPy allows this silently; newer versions deprecate it. Readers
        # using either version must still be unable to change other views.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            snapshot.frame.shape = (180, 3)
        another = self.state.read()
        self.assertEqual(another.frame.shape, (6, 30, 3))
        self.assertTrue((another.frame == 0).all())
        self.assertEqual(another.detections[0].xyxy, (0., 0., 2., 2.))

    def test_invalid_update_preserves_previous_publication(self):
        self.publish()
        with self.assertRaises(ValueError):
            self.publish(mode="unknown")
        with self.assertRaises(ValueError):
            self.state.update(np.zeros((6, 30)), None, {}, "simulated")
        self.assertEqual(self.state.read().sequence, 1)

    def test_readers_observe_complete_snapshots_during_updates(self):
        start = Event()

        def write():
            start.wait()
            for number in range(1, 81):
                self.frame[:] = number
                self.publish()

        def read():
            start.wait()
            for _ in range(150):
                snapshot = self.state.read()
                if snapshot is not None:
                    self.assertEqual(snapshot.frame.shape, (snapshot.height, snapshot.width, 3))
                    self.assertTrue((snapshot.frame == snapshot.sequence).all())

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(write)] + [pool.submit(read) for _ in range(3)]
            start.set()
            for future in futures:
                future.result(timeout=5)
        self.assertEqual(self.state.read().sequence, 80)

    def test_slow_reader_does_not_block_writer(self):
        self.publish()
        reader_waiting, release_reader = Event(), Event()

        def read():
            snapshot = self.state.read()
            reader_waiting.set()
            release_reader.wait(timeout=5)
            self.assertEqual(snapshot.sequence, 1)

        with ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(read)
            try:
                self.assertTrue(reader_waiting.wait(timeout=5))
                pool.submit(self.publish).result(timeout=5)
                self.assertEqual(self.state.read().sequence, 2)
            finally:
                release_reader.set()
            reader.result(timeout=5)


class WiringTests(unittest.TestCase):
    def test_imports_do_not_construct_model_open_camera_or_window(self):
        with patch("ultralytics.YOLO") as model, patch("cv2.imshow") as show, \
                patch("cv2.namedWindow") as window, patch("cv2.VideoCapture") as capture:
            for name in ("scene_state", "track_distances"):
                # Load a fresh module under an isolated name without disturbing
                # the classes already used by the other tests.
                alias = f"_import_test_{name}"
                spec = importlib.util.spec_from_file_location(alias, Path(__file__).resolve().parents[1] / f"{name}.py")
                module = importlib.util.module_from_spec(spec)
                sys.modules[alias] = module
                try:
                    spec.loader.exec_module(module)
                finally:
                    del sys.modules[alias]
            model.assert_not_called()
            show.assert_not_called()
            window.assert_not_called()
            capture.assert_not_called()

    def test_loop_publishes_original_before_plot_and_resets_on_exit(self):
        import track_distances as tracking

        for source, mode in ((0, "live"), ("recorded.mp4", "replay")):
            with self.subTest(source=source):
                state = SceneState(clock=lambda: 10.0)
                original = np.zeros((6, 30, 3), dtype=np.uint8)
                result = SimpleNamespace(orig_img=original, boxes=None)
                observed = []

                def plot():
                    snapshot = state.read()
                    self.assertIsNotNone(snapshot)
                    self.assertEqual(snapshot.source_mode, mode)
                    self.assertTrue((snapshot.frame == 0).all())
                    observed.append(snapshot)
                    return np.full_like(original, 255)

                result.plot = plot
                model = Mock(names={7: "chair"}, predictor=None)
                model.track.return_value = iter([result])
                with patch.object(tracking, "MODEL_PATH") as path, \
                        patch.object(tracking, "YOLO", return_value=model), \
                        patch.object(tracking, "SOURCE", source), \
                        patch.object(tracking.cv2, "imshow") as show, \
                        patch.object(tracking.cv2, "waitKey", return_value=ord("q")), \
                        patch.object(tracking.cv2, "destroyAllWindows") as cleanup:
                    path.is_file.return_value = True
                    tracking.main(state)
                self.assertEqual(len(observed), 1)
                self.assertTrue((observed[0].frame == 0).all())
                self.assertEqual(show.call_args.args[1].shape, original.shape)
                cleanup.assert_called_once()
                self.assertIsNone(state.read())

    def test_loop_failure_resets_state_and_preserves_cleanup(self):
        import track_distances as tracking

        state = SceneState()
        result = SimpleNamespace(orig_img=np.zeros((6, 30, 3), dtype=np.uint8),
                                 boxes=None, plot=Mock(side_effect=RuntimeError("plot failed")))
        model = Mock(names={}, predictor=None)
        model.track.return_value = iter([result])
        with patch.object(tracking, "MODEL_PATH") as path, \
                patch.object(tracking, "YOLO", return_value=model), \
                patch.object(tracking.cv2, "destroyAllWindows") as cleanup:
            path.is_file.return_value = True
            with self.assertRaisesRegex(RuntimeError, "plot failed"):
                tracking.main(state)
            cleanup.assert_called_once()
        self.assertIsNone(state.read())


if __name__ == "__main__":
    unittest.main()
