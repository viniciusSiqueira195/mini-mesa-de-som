from __future__ import annotations

import threading
import unittest

import numpy as np

from mini_mesa.noise_reduction import RNNoiseReducer, StreamingNoiseReducer


class StreamingNoiseReducerTests(unittest.TestCase):
    def test_arbitrary_callback_sizes_keep_a_continuous_fixed_delay(self) -> None:
        reducer = StreamingNoiseReducer(lambda frame: frame.copy(), frame_size=480)
        source = np.linspace(-0.8, 0.8, 2_560, dtype=np.float32)

        output = np.concatenate(
            [
                reducer.process(source[start : start + 256])
                for start in range(0, 2_560, 256)
            ]
        )

        np.testing.assert_array_equal(output[:480], np.zeros(480, dtype=np.float32))
        np.testing.assert_allclose(output[480:], source[:-480])

    def test_processed_frames_are_used_instead_of_the_dry_signal(self) -> None:
        reducer = StreamingNoiseReducer(lambda frame: frame * 0.25, frame_size=4)
        source = np.ones(12, dtype=np.float32)

        output = np.concatenate(
            (reducer.process(source[:5]), reducer.process(source[5:]))
        )

        np.testing.assert_array_equal(output[:4], np.zeros(4, dtype=np.float32))
        np.testing.assert_allclose(output[4:], np.full(8, 0.25, dtype=np.float32))

    def test_partial_reduction_aligns_dry_and_clean_audio_before_mixing(self) -> None:
        previous = np.zeros(4, dtype=np.float32)

        def native_rnnoise_delay(frame: np.ndarray) -> np.ndarray:
            nonlocal previous
            result = previous * 0.5
            previous = frame.copy()
            return result

        clean = StreamingNoiseReducer(native_rnnoise_delay, frame_size=4)
        dry = StreamingNoiseReducer(
            lambda frame: frame.copy(), frame_size=4, initial_delay_frames=8
        )
        source = np.arange(12, dtype=np.float32)

        mixed = np.concatenate([
            dry.process(source[:5]) * 0.5 + clean.process(source[:5]) * 0.5,
            dry.process(source[5:]) * 0.5 + clean.process(source[5:]) * 0.5,
        ])

        np.testing.assert_array_equal(mixed[:8], np.zeros(8, dtype=np.float32))
        np.testing.assert_allclose(mixed[8:], source[:-8] * 0.75)


class RNNoiseLifecycleTests(unittest.TestCase):
    def test_close_waits_for_an_in_progress_native_frame(self) -> None:
        processing = threading.Event()
        release_processing = threading.Event()
        destroyed = threading.Event()

        class FakeLibrary:
            @staticmethod
            def rnnoise_process_frame(_state, _output, _input) -> float:
                processing.set()
                release_processing.wait(timeout=1)
                return 0.0

            @staticmethod
            def rnnoise_destroy(_state) -> None:
                destroyed.set()

        reducer = object.__new__(RNNoiseReducer)
        reducer._library = FakeLibrary()
        reducer._state = 123
        reducer._state_lock = threading.Lock()
        errors: list[Exception] = []

        def process_frame() -> None:
            try:
                reducer._process_frame(np.zeros(480, dtype=np.float32))
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=process_frame)
        worker.start()
        self.assertTrue(processing.wait(timeout=1))
        closer = threading.Thread(target=reducer.close)
        closer.start()

        self.assertFalse(destroyed.wait(timeout=0.05))
        release_processing.set()
        worker.join(timeout=1)
        closer.join(timeout=1)

        self.assertEqual(errors, [])
        self.assertTrue(destroyed.is_set())
        self.assertIsNone(reducer._state)

    def test_processing_after_close_is_a_python_error(self) -> None:
        class FakeLibrary:
            @staticmethod
            def rnnoise_destroy(_state) -> None:
                return None

        reducer = object.__new__(RNNoiseReducer)
        reducer._library = FakeLibrary()
        reducer._state = 123
        reducer._state_lock = threading.Lock()
        reducer.close()

        with self.assertRaisesRegex(RuntimeError, "já foi encerrada"):
            reducer._process_frame(np.zeros(480, dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
