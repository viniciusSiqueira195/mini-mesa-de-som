from __future__ import annotations

import unittest

import numpy as np

from mini_mesa.settings import SpatialSettings
from mini_mesa.spatial_audio import HRTFSpatializer


class HRTFSpatializerTests(unittest.TestCase):
    def test_disabled_spatializer_preserves_centered_audio(self) -> None:
        spatializer = HRTFSpatializer(48_000)
        samples = np.array([0.25, -0.5, 0.1], dtype=np.float32)

        output = spatializer.process(samples)

        np.testing.assert_array_equal(output[:, 0], samples)
        np.testing.assert_array_equal(output[:, 1], samples)

    def test_right_and_left_positions_exchange_ear_responses(self) -> None:
        impulse = np.zeros(512, dtype=np.float32)
        impulse[0] = 1.0

        right = HRTFSpatializer(44_100)
        right.update(SpatialSettings(True, 90))
        right._transition_remaining = 0
        right_output = right.process(impulse)

        left = HRTFSpatializer(44_100)
        left.update(SpatialSettings(True, -90))
        left._transition_remaining = 0
        left_output = left.process(impulse)

        np.testing.assert_allclose(right_output[:, 0], left_output[:, 1])
        np.testing.assert_allclose(right_output[:, 1], left_output[:, 0])
        self.assertGreater(
            np.linalg.norm(right_output[:, 1]),
            np.linalg.norm(right_output[:, 0]),
        )

    def test_intermediate_angle_is_available_at_runtime(self) -> None:
        spatializer = HRTFSpatializer(48_000)
        spatializer.update(SpatialSettings(True, 67))
        spatializer._transition_remaining = 0

        output = spatializer.process(np.ones(256, dtype=np.float32) * 0.1)

        self.assertEqual(output.shape, (256, 2))
        self.assertTrue(np.isfinite(output).all())


if __name__ == "__main__":
    unittest.main()
