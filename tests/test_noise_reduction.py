from __future__ import annotations

import unittest

import numpy as np

from mini_mesa.noise_reduction import StreamingNoiseReducer


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


if __name__ == "__main__":
    unittest.main()
