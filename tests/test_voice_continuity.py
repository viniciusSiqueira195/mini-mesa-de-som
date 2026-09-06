import unittest

import numpy as np

from mini_mesa.audio_engine import _StreamingPitchShifter


class VoiceContinuityTests(unittest.TestCase):
    def test_synchronous_adapter_preserves_every_sample_with_irregular_blocks(self):
        class Identity:
            def process(self, samples, *args, **kwargs):
                return samples
        adapter = _StreamingPitchShifter(np, Identity(), 48000, 3072, 1536, synchronous=True)
        source = np.random.default_rng(12).normal(0, 0.1, 48000).astype(np.float32)
        output = []
        start = 0
        sizes = (128, 480, 1024, 256, 2048, 512)
        while start < source.size:
            count = sizes[len(output) % len(sizes)]
            output.append(adapter.process(source[start:start + count]))
            start += count
        rendered = np.concatenate(output)
        np.testing.assert_allclose(rendered[3072:], source[:-3072], atol=3e-8)
        adapter.close(timeout=0.1)
