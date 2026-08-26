from __future__ import annotations

import unittest

import numpy as np

from mini_mesa.voice_presets import StreamingVoicePreset, VoicePreset


class VoicePresetTests(unittest.TestCase):
    def test_invalid_saved_preset_falls_back_to_natural(self) -> None:
        self.assertIs(VoicePreset.from_value("ET de Varginha"), VoicePreset.NATURAL)

    def test_natural_preset_has_no_latency_or_processing(self) -> None:
        processor = StreamingVoicePreset(VoicePreset.NATURAL, 48_000)
        samples = np.array([0.2, -0.4, 0.1], dtype=np.float32)

        output = processor.process(samples)

        self.assertEqual(processor.latency_frames, 0)
        np.testing.assert_array_equal(output, samples)

    def test_streaming_shifter_always_returns_the_callback_size(self) -> None:
        processor = StreamingVoicePreset(
            VoicePreset.FEMININE,
            48_000,
            window_milliseconds=10,
        )
        blocks = [
            processor.process(np.ones(128, dtype=np.float32) * 0.2)
            for _ in range(8)
        ]

        self.assertTrue(all(block.shape == (128,) for block in blocks))
        self.assertTrue(np.isfinite(np.concatenate(blocks)).all())

    def test_elderly_presets_apply_gentle_tremolo(self) -> None:
        processor = StreamingVoicePreset(
            VoicePreset.ELDERLY_WOMAN,
            48_000,
            window_milliseconds=10,
        )
        output = np.concatenate(
            [processor.process(np.ones(256, dtype=np.float32)) for _ in range(8)]
        )
        audible = output[1024:]

        self.assertGreater(audible.size, 0)
        self.assertLessEqual(float(np.max(audible)), 1.0)
        self.assertGreaterEqual(float(np.min(audible)), 0.88)

    def test_pitch_direction_matches_the_selected_preset(self) -> None:
        sample_rate = 48_000
        frequency = 220.0
        frames = sample_rate
        time = np.arange(frames) / sample_rate
        source = np.sin(2.0 * np.pi * frequency * time).astype(np.float32)

        frequencies = {}
        for preset in (VoicePreset.FEMININE, VoicePreset.MASCULINE):
            processor = StreamingVoicePreset(preset, sample_rate)
            output = np.concatenate(
                [
                    processor.process(source[index : index + 512])
                    for index in range(0, frames, 512)
                ]
            )
            stable = output[4096:]
            spectrum = np.abs(np.fft.rfft(stable * np.hanning(stable.size)))
            frequencies[preset] = np.fft.rfftfreq(stable.size, 1 / sample_rate)[
                int(np.argmax(spectrum))
            ]

        self.assertGreater(frequencies[VoicePreset.FEMININE], frequency)
        self.assertLess(frequencies[VoicePreset.MASCULINE], frequency)


if __name__ == "__main__":
    unittest.main()
