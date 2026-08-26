from __future__ import annotations

import threading
import unittest

import numpy as np

from mini_mesa.audio_engine import (
    AudioEngine,
    _BufferedAudioOutput,
    _normalize_device_label,
)
from mini_mesa.settings import ReverbSettings


class FakeStream:
    def __init__(self, *, run_error: Exception | None = None) -> None:
        self.closed = threading.Event()
        self.started = threading.Event()
        self.run_error = run_error

    def run(self) -> None:
        self.started.set()
        if self.run_error is not None:
            raise self.run_error
        self.closed.wait(timeout=2)

    def close(self) -> None:
        self.closed.set()


class FakeBackend:
    def __init__(self, stream: FakeStream | None = None) -> None:
        self.stream = stream or FakeStream()
        self.created_with: tuple[str, str, ReverbSettings, str | None] | None = None
        self.updated_with: ReverbSettings | None = None

    def input_devices(self) -> tuple[str, ...]:
        return ("FIFINE AM8", "Zeus X")

    def output_devices(self) -> tuple[str, ...]:
        return ("CABLE Input", "Alto-falantes")

    def monitor_devices(self) -> tuple[str, ...]:
        return ("Alto-falantes",)

    def create_stream(
        self,
        input_device: str,
        output_device: str,
        settings: ReverbSettings,
        monitor_output: str | None = None,
    ) -> FakeStream:
        self.created_with = (input_device, output_device, settings, monitor_output)
        return self.stream

    def update_reverb(self, settings: ReverbSettings) -> None:
        self.updated_with = settings


class FakeOutputStream:
    closed = False


class FakeSoundDevice:
    def __init__(self) -> None:
        self.output_arguments: dict[str, object] = {}

    def OutputStream(self, **kwargs) -> FakeOutputStream:
        self.output_arguments = kwargs
        return FakeOutputStream()


class BufferedAudioOutputTests(unittest.TestCase):
    def test_buffer_is_capped_at_four_blocks_to_prevent_growing_delay(self) -> None:
        sounddevice = FakeSoundDevice()
        output = _BufferedAudioOutput(
            sounddevice=sounddevice,
            output_id=7,
            sample_rate=48_000,
            output_channels=2,
            block_size=4,
        )

        for block_number in range(5):
            output.push(np.full(4, block_number, dtype=np.float32))

        self.assertEqual(output._queued_frames, 16)
        self.assertEqual(output._chunks[0][0], 1)
        self.assertEqual(sounddevice.output_arguments["blocksize"], 4)

    def test_mono_processed_audio_is_copied_to_both_return_channels(self) -> None:
        output = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=7,
            sample_rate=48_000,
            output_channels=2,
            block_size=2,
        )
        output.push(np.array([0.25, -0.5], dtype=np.float32))
        destination = np.zeros((2, 2), dtype=np.float32)

        output._on_output(destination, 2, None, None)

        np.testing.assert_array_equal(
            destination,
            np.array([[0.25, 0.25], [-0.5, -0.5]], dtype=np.float32),
        )


class AudioEngineTests(unittest.TestCase):
    def test_windows_instance_prefixes_do_not_duplicate_the_same_microphone(self) -> None:
        self.assertEqual(
            _normalize_device_label("Microfone (5- USB Audio Device)"),
            "Microfone (USB Audio Device)",
        )

    def test_devices_are_not_tied_to_a_microphone_brand(self) -> None:
        engine = AudioEngine(FakeBackend())

        self.assertEqual(engine.input_devices(), ("FIFINE AM8", "Zeus X"))
        self.assertEqual(engine.output_devices()[0], "CABLE Input")
        self.assertEqual(engine.monitor_devices(), ("Alto-falantes",))

    def test_start_and_stop_one_stream(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        settings = ReverbSettings(35)
        engine.update_settings(settings)

        engine.start("FIFINE AM8", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))
        self.assertTrue(engine.is_running)
        self.assertEqual(
            backend.created_with,
            ("FIFINE AM8", "CABLE Input", settings, None),
        )

        engine.stop()
        self.assertTrue(backend.stream.closed.is_set())
        self.assertFalse(engine.is_running)

    def test_optional_monitor_output_reaches_backend(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)

        engine.start("Zeus X", "CABLE Input", "Alto-falantes")
        self.assertTrue(backend.stream.started.wait(timeout=1))

        self.assertEqual(
            backend.created_with,
            ("Zeus X", "CABLE Input", ReverbSettings(), "Alto-falantes"),
        )
        engine.stop()

    def test_monitor_and_virtual_output_must_be_different(self) -> None:
        engine = AudioEngine(FakeBackend())

        with self.assertRaisesRegex(ValueError, "retorno deve ser diferente"):
            engine.start("Zeus X", "CABLE Input", "CABLE Input")

    def test_live_setting_change_reaches_backend(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        engine.start("Zeus X", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))

        settings = ReverbSettings(70)
        engine.update_settings(settings)

        self.assertEqual(backend.updated_with, settings)
        engine.stop()

    def test_same_input_and_output_is_rejected(self) -> None:
        engine = AudioEngine(FakeBackend())

        with self.assertRaisesRegex(ValueError, "microfonia"):
            engine.start("Mesmo dispositivo", "Mesmo dispositivo")

    def test_two_simultaneous_streams_are_rejected(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        engine.start("FIFINE AM8", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))

        with self.assertRaisesRegex(RuntimeError, "já está ativo"):
            engine.start("Zeus X", "CABLE Input")

        engine.stop()

    def test_background_error_is_reported(self) -> None:
        received: list[str] = []
        backend = FakeBackend(FakeStream(run_error=RuntimeError("dispositivo removido")))
        engine = AudioEngine(backend, on_error=received.append)

        engine.start("FIFINE AM8", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))
        engine._thread.join(timeout=1)  # type: ignore[union-attr]

        self.assertEqual(received, ["dispositivo removido"])
        self.assertFalse(engine.is_running)


if __name__ == "__main__":
    unittest.main()
