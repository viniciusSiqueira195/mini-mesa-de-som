from __future__ import annotations

import threading
import unittest

import numpy as np

from mini_mesa.audio_engine import (
    AudioEngine,
    PedalboardBackend,
    _BufferedAudioOutput,
    _HOST_API_RANKS,
    _MONITOR_API_RANKS,
    _MultiOutputSoundDeviceStream,
    _is_windows_default_alias,
    _merge_mme_truncated_labels,
    _normalize_device_label,
    _normalize_output_device_label,
    _resolve_device_label,
    match_device_label,
)
from mini_mesa.settings import ReverbSettings, SpatialSettings
from mini_mesa.soundboard import SoundEffectInfo


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


class SilentSoundboard:
    @staticmethod
    def mix(frames: int) -> np.ndarray:
        return np.zeros((frames, 2), dtype=np.float32)


class ConstantSoundboard:
    @staticmethod
    def mix(frames: int) -> np.ndarray:
        return np.full((frames, 2), 0.25, dtype=np.float32)


class FakeBackend:
    def __init__(self, stream: FakeStream | None = None) -> None:
        self.stream = stream or FakeStream()
        self.created_with: tuple[str, str, ReverbSettings, str | None] | None = None
        self.updated_with: ReverbSettings | None = None
        self.updated_monitors: list[str | None] = []
        self.noise_reduction_enabled = False
        self.spatial_settings = SpatialSettings()
        self.played_effects: list[str] = []
        self.effects_stopped = 0

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

    def update_monitor(self, monitor_output: str | None) -> None:
        self.updated_monitors.append(monitor_output)

    def update_noise_reduction(self, enabled: bool) -> None:
        self.noise_reduction_enabled = enabled

    def update_spatial(self, settings: SpatialSettings) -> None:
        self.spatial_settings = settings

    def sound_effects(self) -> tuple[SoundEffectInfo, ...]:
        return (SoundEffectInfo("horn", "Buzina", "Ctrl+1", "Buzina curta"),)

    def play_sound_effect(self, effect_id: str) -> SoundEffectInfo:
        self.played_effects.append(effect_id)
        return self.sound_effects()[0]

    def stop_sound_effects(self) -> None:
        self.effects_stopped += 1


class FakeOutputStream:
    def __init__(self) -> None:
        self.active = False
        self.closed = False
        self.start_calls = 0
        self.close_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        self.active = True

    def abort(self) -> None:
        self.active = False

    def close(self) -> None:
        self.close_calls += 1
        self.active = False
        self.closed = True


class FakeSoundDevice:
    def __init__(self) -> None:
        self.output_arguments: dict[str, object] = {}

    def OutputStream(self, **kwargs) -> FakeOutputStream:
        self.output_arguments = kwargs
        return FakeOutputStream()

    def InputStream(self, **_kwargs) -> FakeOutputStream:
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
        self.assertEqual(output._dropped_block_count, 1)
        self.assertTrue(output._needs_crossfade)
        self.assertEqual(sounddevice.output_arguments["blocksize"], 4)

    def test_mono_processed_audio_is_copied_to_both_return_channels(self) -> None:
        output = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=7,
            sample_rate=48_000,
            output_channels=2,
            block_size=2,
        )
        output._underrun = False
        output.push(np.array([0.25, -0.5], dtype=np.float32))
        destination = np.zeros((2, 2), dtype=np.float32)

        output._on_output(destination, 2, None, None)

        np.testing.assert_array_equal(
            destination,
            np.array([[0.25, 0.25], [-0.5, -0.5]], dtype=np.float32),
        )

    def test_underrun_fades_to_silence_instead_of_cutting_abruptly(self) -> None:
        output = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=7,
            sample_rate=48_000,
            output_channels=2,
            block_size=4,
        )
        output._underrun = False
        output._last_sample = 1.0
        destination = np.zeros((4, 2), dtype=np.float32)

        output._on_output(destination, 4, None, None)

        np.testing.assert_allclose(
            destination[:, 0],
            np.array([0.75, 0.5, 0.25, 0.0], dtype=np.float32),
        )
        np.testing.assert_array_equal(destination[:, 0], destination[:, 1])
        self.assertEqual(output._underrun_count, 1)

    def test_stereo_processed_audio_keeps_its_binaural_channels(self) -> None:
        output = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=7,
            sample_rate=48_000,
            output_channels=2,
            block_size=2,
        )
        output._underrun = False
        output.push(
            np.array([[0.25, -0.25], [0.5, -0.5]], dtype=np.float32)
        )
        destination = np.zeros((2, 2), dtype=np.float32)

        output._on_output(destination, 2, None, None)

        np.testing.assert_array_equal(
            destination,
            np.array([[0.25, -0.25], [0.5, -0.5]], dtype=np.float32),
        )

    def test_stereo_is_safely_downmixed_for_a_mono_output(self) -> None:
        output = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=7,
            sample_rate=48_000,
            output_channels=1,
            block_size=2,
        )
        output._underrun = False
        output.push(np.array([[0.8, 0.2], [-0.4, 0.2]], dtype=np.float32))
        destination = np.zeros((2, 1), dtype=np.float32)

        output._on_output(destination, 2, None, None)

        np.testing.assert_allclose(destination[:, 0], np.array([0.5, -0.1]))

    def test_monitor_gain_leaves_headroom_and_caps_unexpected_peaks(self) -> None:
        output = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=7,
            sample_rate=48_000,
            output_channels=2,
            block_size=2,
            gain=0.72,
            peak_limit=0.95,
        )
        output._underrun = False
        output.push(np.array([[1.0, -1.0], [2.0, -2.0]], dtype=np.float32))
        destination = np.zeros((2, 2), dtype=np.float32)

        output._on_output(destination, 2, None, None)

        np.testing.assert_allclose(
            destination,
            np.array([[0.72, -0.72], [0.95, -0.95]], dtype=np.float32),
        )

    def test_primary_output_preserves_the_processed_signal(self) -> None:
        output = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=7,
            sample_rate=48_000,
            output_channels=2,
            block_size=2,
        )
        output._underrun = False
        output.push(np.array([1.2, -1.2], dtype=np.float32))
        destination = np.zeros((2, 2), dtype=np.float32)

        output._on_output(destination, 2, None, None)

        np.testing.assert_array_equal(
            destination,
            np.array([[1.2, 1.2], [-1.2, -1.2]], dtype=np.float32),
        )

    def test_experimental_monitor_drops_instead_of_blocking_when_busy(self) -> None:
        output = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=7,
            sample_rate=48_000,
            output_channels=2,
            block_size=2,
            drop_when_busy=True,
        )
        output._queue_lock.acquire()
        try:
            accepted = output.push(np.array([0.25, -0.25], dtype=np.float32))
        finally:
            output._queue_lock.release()

        self.assertFalse(accepted)
        self.assertEqual(output._queued_frames, 0)
        self.assertEqual(output._dropped_block_count, 1)

class MultiOutputStreamTests(unittest.TestCase):
    def test_closing_stream_twice_closes_native_devices_once(self) -> None:
        stream = _MultiOutputSoundDeviceStream(
            sounddevice=FakeSoundDevice(),
            input_id=1,
            outputs=[(2, 2)],
            sample_rate=48_000,
            input_channels=1,
            block_size=4,
            processor=lambda samples, _frames: samples,
        )

        stream.close()
        stream.close()

        self.assertEqual(stream._input.close_calls, 1)
        self.assertEqual(stream._primary_output.stream.close_calls, 1)

    def test_validated_stream_is_reused_without_restarting_devices(self) -> None:
        stream = _MultiOutputSoundDeviceStream(
            sounddevice=FakeSoundDevice(),
            input_id=1,
            outputs=[(2, 2)],
            sample_rate=48_000,
            input_channels=1,
            block_size=4,
            processor=lambda samples, _frames: samples,
        )

        stream.validate_start()
        self.assertTrue(stream._input.active)
        self.assertTrue(stream._primary_output.stream.active)

        stream._stop_event.set()
        stream.run()

        self.assertEqual(stream._input.start_calls, 1)
        self.assertEqual(stream._primary_output.stream.start_calls, 1)

    def test_only_monitor_output_receives_monitor_protections(self) -> None:
        stream = _MultiOutputSoundDeviceStream(
            sounddevice=FakeSoundDevice(),
            input_id=1,
            outputs=[(2, 2), (3, 2)],
            sample_rate=48_000,
            input_channels=1,
            block_size=256,
            processor=lambda samples, _frames: samples,
        )

        primary, monitor = stream._outputs
        self.assertEqual(primary._gain, 1.0)
        self.assertIsNone(primary._peak_limit)
        self.assertEqual(monitor._gain, 0.72)
        self.assertEqual(monitor._peak_limit, 0.95)
        self.assertFalse(primary._drop_when_busy)
        self.assertTrue(monitor._drop_when_busy)
        self.assertEqual(stream._prefill_blocks, 3)
        self.assertEqual(stream._sd.output_arguments["blocksize"], 0)
        self.assertEqual(stream._sd.output_arguments["latency"], 0.02)
        stream.close()

    def test_busy_monitor_cannot_delay_or_drop_the_recording_block(self) -> None:
        stream = _MultiOutputSoundDeviceStream(
            sounddevice=FakeSoundDevice(),
            input_id=1,
            outputs=[(2, 2), (3, 2)],
            sample_rate=48_000,
            input_channels=1,
            block_size=4,
            processor=lambda samples, _frames: samples,
        )
        primary, monitor = stream._outputs
        monitor._queue_lock.acquire()
        try:
            stream._on_input(np.ones((4, 1), dtype=np.float32), 4, None, None)
        finally:
            monitor._queue_lock.release()

        self.assertEqual(primary._queued_frames, 4)
        self.assertEqual(monitor._queued_frames, 0)
        self.assertEqual(monitor._dropped_block_count, 1)
        stream.close()

    def test_removing_monitor_closes_only_the_monitor_output(self) -> None:
        primary = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=1,
            sample_rate=48_000,
            output_channels=2,
            block_size=4,
        )
        monitor = _BufferedAudioOutput(
            sounddevice=FakeSoundDevice(),
            output_id=2,
            sample_rate=48_000,
            output_channels=2,
            block_size=4,
        )
        stream = object.__new__(_MultiOutputSoundDeviceStream)
        stream._outputs_lock = threading.Lock()
        stream._outputs = [primary, monitor]
        stream._monitor_output = monitor

        stream.replace_monitor(None, 0)

        self.assertEqual(stream._outputs, [primary])
        self.assertIsNone(stream._monitor_output)
        self.assertFalse(primary.stream.closed)
        self.assertTrue(monitor.stream.closed)


class PedalboardProcessingTests(unittest.TestCase):
    def test_noise_reduction_runs_before_reverb_effects(self) -> None:
        class FakeNoiseReducer:
            @staticmethod
            def process(samples):
                return samples * 0.5

        class RecordingEffects:
            received = None

            def process(self, samples, _sample_rate, **_kwargs):
                self.received = samples.copy()
                return samples

        effects = RecordingEffects()
        backend = object.__new__(PedalboardBackend)
        backend._np = np
        backend._effects = effects
        backend._noise_reducer = FakeNoiseReducer()
        backend._spatializer = None
        backend._limiter = None
        backend._sample_rate = 48_000.0
        backend._processing_lock = threading.Lock()
        backend._soundboard = SilentSoundboard()
        microphone = np.full((4, 1), 0.8, dtype=np.float32)

        output = backend._process_audio(microphone, 4)

        np.testing.assert_allclose(effects.received, np.full((1, 4), 0.4))
        np.testing.assert_allclose(output, np.full((4, 2), 0.4))

    def test_soundboard_is_mixed_with_processed_microphone_audio(self) -> None:
        class PassthroughEffects:
            @staticmethod
            def process(samples, _sample_rate, **_kwargs):
                return samples

        backend = object.__new__(PedalboardBackend)
        backend._np = np
        backend._effects = PassthroughEffects()
        backend._noise_reducer = None
        backend._spatializer = None
        backend._limiter = None
        backend._sample_rate = 48_000.0
        backend._processing_lock = threading.Lock()
        backend._soundboard = ConstantSoundboard()

        output = backend._process_audio(
            np.full((4, 1), 0.20, dtype=np.float32),
            4,
        )

        np.testing.assert_allclose(output, np.full((4, 2), 0.45))

    def test_soundboard_follows_reverb_and_spatial_processing(self) -> None:
        class RecordingReverb:
            received = None

            def process(self, samples, _sample_rate, **_kwargs):
                self.received = samples.copy()
                return samples * 2.0

        class RecordingSpatializer:
            received = None

            def process(self, samples):
                self.received = samples.copy()
                return np.column_stack((samples, samples * 3.0))

        reverb = RecordingReverb()
        spatializer = RecordingSpatializer()
        backend = object.__new__(PedalboardBackend)
        backend._np = np
        backend._effects = reverb
        backend._noise_reducer = None
        backend._spatializer = spatializer
        backend._limiter = None
        backend._sample_rate = 48_000.0
        backend._processing_lock = threading.Lock()
        backend._soundboard = ConstantSoundboard()

        output = backend._process_audio(
            np.full((4, 1), 0.20, dtype=np.float32),
            4,
        )

        np.testing.assert_allclose(reverb.received, np.full((1, 4), 0.45))
        np.testing.assert_allclose(spatializer.received, np.full(4, 0.90))
        np.testing.assert_allclose(output[:, 0], np.full(4, 0.90))
        np.testing.assert_allclose(output[:, 1], np.full(4, 2.70))


class AudioEngineTests(unittest.TestCase):
    def test_primary_and_experimental_monitor_use_independent_api_priorities(self) -> None:
        self.assertLess(
            _HOST_API_RANKS["Windows WASAPI"],
            _HOST_API_RANKS["Windows WDM-KS"],
        )
        self.assertEqual(_MONITOR_API_RANKS["Windows WASAPI"], 0)
        self.assertNotIn("Windows WDM-KS", _MONITOR_API_RANKS)

    def test_virtual_audio_cable_output_names_are_grouped_across_apis(self) -> None:
        self.assertEqual(
            _normalize_output_device_label("Line Out (Virtual Cable 1)"),
            "Line 1 (Virtual Audio Cable)",
        )

    def test_windows_instance_prefixes_do_not_duplicate_the_same_microphone(self) -> None:
        self.assertEqual(
            _normalize_device_label("Microfone (5- USB Audio Device)"),
            "Microfone (USB Audio Device)",
        )

    def test_saved_microphone_survives_windows_instance_renumbering(self) -> None:
        available = ("Microfone (USB Audio Device)", "Microfone (Webcam)")

        resolved = _resolve_device_label(
            "Microfone (7- USB Audio Device)",
            available,
        )

        self.assertEqual(resolved, "Microfone (USB Audio Device)")

    def test_saved_virtual_cable_name_survives_api_name_change(self) -> None:
        resolved = _resolve_device_label(
            "Line Out (Virtual Cable 1)",
            ("Line 1 (Virtual Audio Cable)", "Alto-falantes"),
            output=True,
        )

        self.assertEqual(resolved, "Line 1 (Virtual Audio Cable)")

    def test_virtual_cable_input_is_grouped_across_windows_apis(self) -> None:
        self.assertEqual(
            _normalize_device_label("Line 1 (Virtual Cable 1)"),
            "Line 1 (Virtual Audio Cable)",
        )

    def test_device_matching_is_case_insensitive(self) -> None:
        resolved = _resolve_device_label(
            "microfone (usb audio device)",
            ("Microfone (USB Audio Device)",),
        )

        self.assertEqual(resolved, "Microfone (USB Audio Device)")

    def test_missing_saved_device_has_no_false_match(self) -> None:
        self.assertIsNone(
            match_device_label("Microfone removido", ("Microfone USB",))
        )

    def test_mme_truncated_name_is_merged_with_complete_device_name(self) -> None:
        devices = {
            "Alto-falantes (USB Audio Dev": [(5, "MME")],
            "Alto-falantes (USB Audio Device)": [(22, "Windows WASAPI")],
        }

        _merge_mme_truncated_labels(devices)

        self.assertEqual(
            devices,
            {
                "Alto-falantes (USB Audio Device)": [
                    (22, "Windows WASAPI"),
                    (5, "MME"),
                ]
            },
        )

    def test_ambiguous_mme_prefix_is_not_merged(self) -> None:
        devices = {
            "Dispositivo de áudio USB": [(5, "MME")],
            "Dispositivo de áudio USB A": [(22, "Windows WASAPI")],
            "Dispositivo de áudio USB B": [(23, "Windows WASAPI")],
        }

        _merge_mme_truncated_labels(devices)

        self.assertEqual(len(devices), 3)

    def test_generic_windows_audio_aliases_are_hidden(self) -> None:
        self.assertTrue(_is_windows_default_alias("Mapeador de som da Microsoft"))
        self.assertTrue(_is_windows_default_alias("Primary Sound Driver"))
        self.assertFalse(_is_windows_default_alias("Microfone USB"))

    def test_route_resolution_discards_cached_portaudio_ids(self) -> None:
        backend = object.__new__(PedalboardBackend)
        backend._input_ids = {
            "Microfone (USB Audio Device)": [(4, "Windows WASAPI")]
        }
        backend._output_ids = {"CABLE Input": [(8, "Windows WASAPI")]}
        refresh_count = 0

        def simulate_windows_renumbering() -> None:
            nonlocal refresh_count
            refresh_count += 1
            backend._input_ids = {
                "Microfone (USB Audio Device)": [(31, "Windows WDM-KS")]
            }
            backend._output_ids = {
                "CABLE Input": [(44, "Windows WDM-KS")]
            }

        backend._refresh_devices = simulate_windows_renumbering  # type: ignore[method-assign]

        inputs, outputs, monitors = backend._resolve_current_routes(
            "Microfone (9- USB Audio Device)",
            "CABLE Input",
            None,
        )

        self.assertEqual(refresh_count, 1)
        self.assertEqual(inputs, [(31, "Windows WDM-KS")])
        self.assertEqual(outputs, [(44, "Windows WDM-KS")])
        self.assertEqual(monitors, [(None, "")])

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

    def test_monitor_can_be_removed_without_stopping_the_audio_stream(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        engine.start("Zeus X", "CABLE Input", "Alto-falantes")
        self.assertTrue(backend.stream.started.wait(timeout=1))

        engine.update_monitor(None)

        self.assertEqual(backend.updated_monitors, [None])
        self.assertTrue(engine.is_running)
        self.assertFalse(backend.stream.closed.is_set())
        engine.stop()

    def test_monitor_can_be_added_without_recreating_the_audio_stream(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        engine.start("Zeus X", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))

        engine.update_monitor("Alto-falantes")

        self.assertEqual(backend.updated_monitors, ["Alto-falantes"])
        self.assertTrue(engine.is_running)
        self.assertFalse(backend.stream.closed.is_set())
        engine.stop()

    def test_noise_reduction_is_configured_before_starting(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)

        engine.update_noise_reduction(True)

        self.assertTrue(backend.noise_reduction_enabled)

    def test_noise_reduction_cannot_change_while_audio_is_running(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        engine.start("Zeus X", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))

        with self.assertRaisesRegex(RuntimeError, "Desative a mesa"):
            engine.update_noise_reduction(True)

        self.assertFalse(backend.noise_reduction_enabled)
        self.assertTrue(engine.is_running)
        engine.stop()

    def test_spatial_position_can_change_while_audio_is_running(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        engine.start("Zeus X", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))

        settings = SpatialSettings(enabled=True, x=-100, y=25, z=0)
        engine.update_spatial(settings)

        self.assertEqual(backend.spatial_settings, settings)
        self.assertTrue(engine.is_running)
        engine.stop()

    def test_sound_effect_requires_an_active_audio_route(self) -> None:
        engine = AudioEngine(FakeBackend())

        with self.assertRaisesRegex(RuntimeError, "Ative a mesa"):
            engine.play_sound_effect("horn")

    def test_sound_effect_reaches_backend_and_stops_with_the_route(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        engine.start("Zeus X", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))

        effect = engine.play_sound_effect("horn")
        engine.stop()

        self.assertEqual(effect.name, "Buzina")
        self.assertEqual(backend.played_effects, ["horn"])
        self.assertGreaterEqual(backend.effects_stopped, 1)

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
