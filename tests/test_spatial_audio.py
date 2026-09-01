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
        right.update(SpatialSettings(True, x=100, y=0, z=0))
        right._transition_remaining = 0
        right_output = right.process(impulse)

        left = HRTFSpatializer(44_100)
        left.update(SpatialSettings(True, x=-100, y=0, z=0))
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
        spatializer.update(SpatialSettings(True, x=92, y=0, z=39))
        spatializer._transition_remaining = 0

        output = spatializer.process(np.ones(256, dtype=np.float32) * 0.1)

        self.assertEqual(output.shape, (256, 2))
        self.assertTrue(np.isfinite(output).all())

    def test_above_and_below_have_distinct_elevation_cues(self) -> None:
        impulse = np.zeros(512, dtype=np.float32)
        impulse[0] = 1.0

        above = HRTFSpatializer(44_100)
        above.update(SpatialSettings(True, x=0, y=100, z=0))
        above._transition_remaining = 0

        below = HRTFSpatializer(44_100)
        below.update(SpatialSettings(True, x=0, y=-100, z=0))
        below._transition_remaining = 0

        self.assertFalse(np.allclose(above.process(impulse), below.process(impulse)))

    def test_front_and_behind_use_distinct_hrtf_responses(self) -> None:
        impulse = np.zeros(512, dtype=np.float32)
        impulse[0] = 1.0

        front = HRTFSpatializer(44_100)
        front.update(SpatialSettings(True, x=0, y=0, z=100))
        front._transition_remaining = 0

        behind = HRTFSpatializer(44_100)
        behind.update(SpatialSettings(True, x=0, y=0, z=-100))
        behind._transition_remaining = 0

        self.assertFalse(np.allclose(front.process(impulse), behind.process(impulse)))

    def test_automatic_movement_advances_all_three_axes(self) -> None:
        spatializer = HRTFSpatializer(48_000)
        spatializer.update(
            SpatialSettings(enabled=True, automatic=True, speed_percent=100)
        )

        positions = [
            spatializer._next_automatic_position(24_000) for _ in range(12)
        ]

        self.assertGreater(len({x for x, _y, _z in positions}), 1)
        self.assertGreater(len({y for _x, y, _z in positions}), 1)
        self.assertGreater(len({z for _x, _y, z in positions}), 1)
        self.assertLess(min(x for x, _y, _z in positions), 0)
        self.assertGreater(max(x for x, _y, _z in positions), 0)
        self.assertLess(min(y for _x, y, _z in positions), 0)
        self.assertGreater(max(y for _x, y, _z in positions), 0)
        self.assertLess(min(z for _x, _y, z in positions), 0)
        self.assertGreater(max(z for _x, _y, z in positions), 0)


if __name__ == "__main__":
    unittest.main()
