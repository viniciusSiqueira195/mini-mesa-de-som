from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import Mock, patch

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
    _RealtimeTransform,
    _StreamingPitchShifter,
    _stream_block_sizes,
)
from mini_mesa.settings import (
    CreativeEffectSettings,
    ProAudioSettings,
    ReverbSettings,
    SoundboardSettings,
    SpatialSettings,
    VALID_AMBIENCES,
    VALID_CREATIVE_PRESETS,
    VALID_MODULATIONS,
    VALID_VOICE_PRESETS,
    VoiceSettings,
)
from mini_mesa.soundboard import SoundEffectInfo


class FakeStream:
    def set_monitor_voice(self, enabled: bool) -> None:
        self.monitor_voice = enabled

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
        self.voice_settings = VoiceSettings()
        self.creative_settings = CreativeEffectSettings()
        self.pro_audio_settings = ProAudioSettings()
        self.soundboard_settings = SoundboardSettings()
        self.played_sounds: list[str] = []
        self.previewed_sounds: list[tuple[str, str]] = []
        self.preview_stops = 0
        self.deactivate_calls = 0

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
        *, monitor_voice: bool = True,
    ) -> FakeStream:
        self.stream.set_monitor_voice(monitor_voice)
        self.created_with = (input_device, output_device, settings, monitor_output)
        return self.stream

    def update_reverb(self, settings: ReverbSettings) -> None:
        self.updated_with = settings

    def update_voice_effect(self, settings: VoiceSettings) -> None:
        self.voice_settings = settings

    def update_creative_effects(self, settings: CreativeEffectSettings) -> None:
        self.creative_settings = settings

    def update_pro_audio(self, settings: ProAudioSettings) -> None:
        self.pro_audio_settings = settings

    def update_soundboard(self, settings: SoundboardSettings) -> None:
        self.soundboard_settings = settings

    def play_sound(self, sound_id_or_path: str) -> bool:
        self.played_sounds.append(sound_id_or_path)
        return True

    def preview_sound(self, path: str, output_device: str) -> None:
        self.previewed_sounds.append((path, output_device))

    def stop_preview(self) -> None:
        self.preview_stops += 1

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

    def deactivate(self) -> None:
        self.deactivate_calls += 1


class FakeOutputStream:
    def __init__(self) -> None:
        self.active = False
        self.closed = False
        self.start_calls = 0
        self.started = threading.Event()
        self.abort_calls = 0
        self.close_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        self.active = True
        self.started.set()

    def abort(self) -> None:
        self.abort_calls += 1
        self.active = False

    def close(self) -> None:
        self.close_calls += 1
        self.active = False
        self.closed = True


class FakeSoundDevice:
    def __init__(self) -> None:
        self.output_arguments: dict[str, object] = {}
        self.streams: list[FakeOutputStream] = []

    def OutputStream(self, **kwargs) -> FakeOutputStream:
        self.output_arguments = kwargs
        stream = FakeOutputStream()
        self.streams.append(stream)
        return stream

    def InputStream(self, **_kwargs) -> FakeOutputStream:
        stream = FakeOutputStream()
        self.streams.append(stream)
        return stream


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
            sounddevice=FakeSoundDevice(), input_id=1, outputs=[(2, 2)],
            sample_rate=48_000, input_channels=1, block_size=4,
            processor=lambda samples, _frames: samples,
        )
        stream.close()
        stream.close()
        self.assertEqual(stream._input.close_calls, 1)
        self.assertEqual(stream._primary_output.stream.close_calls, 1)

    def test_audio_thread_is_the_only_owner_of_native_stream_teardown(self) -> None:
        sounddevice = FakeSoundDevice()
        stream = _MultiOutputSoundDeviceStream(
            sounddevice=sounddevice, input_id=1, outputs=[(2, 2), (3, 2)],
            sample_rate=48_000, input_channels=1, block_size=512,
            processor=lambda samples, _frames: samples,
        )
        thread = threading.Thread(target=stream.run)
        thread.start()
        self.assertTrue(stream._input.started.wait(timeout=1))
        stream.close()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(all(native.closed for native in sounddevice.streams))
        self.assertTrue(all(native.close_calls == 1 for native in sounddevice.streams))

    def test_close_before_run_disposes_streams_without_reopening_them(self) -> None:
        sounddevice = FakeSoundDevice()
        stream = _MultiOutputSoundDeviceStream(
            sounddevice=sounddevice, input_id=1, outputs=[(2, 2)],
            sample_rate=48_000, input_channels=1, block_size=512,
            processor=lambda samples, _frames: samples,
        )
        stream.close()
        stream.run()
        self.assertTrue(all(native.closed for native in sounddevice.streams))
        self.assertTrue(all(native.close_calls == 1 for native in sounddevice.streams))

    def test_monitor_uses_blocks_large_enough_for_the_effects_chain(self) -> None:
        self.assertEqual(_stream_block_sizes(True), (512, 1024))
        self.assertEqual(_stream_block_sizes(False), (512, 256))

    def test_validated_stream_is_reused_without_restarting_devices(self) -> None:
        stream = _MultiOutputSoundDeviceStream(
            sounddevice=FakeSoundDevice(), input_id=1, outputs=[(2, 2)],
            sample_rate=48_000, input_channels=1, block_size=4,
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
    @staticmethod
    def _backend_with_dry_reverb() -> PedalboardBackend:
        backend = PedalboardBackend()
        settings = ReverbSettings(enabled=False)
        backend._reverb = backend._Reverb(
            wet_level=settings.wet_level,
            dry_level=settings.dry_level,
        )
        return backend

    @staticmethod
    def _render_preset(backend, samples, preset: str):
        backend.update_creative_effects(CreativeEffectSettings(preset=preset))
        return np.asarray(
            backend._effects.process(samples[None, :], 48_000, reset=True)
        ).reshape(-1)

    @staticmethod
    def _render_streaming_preset(samples, preset: str, block_size: int = 512):
        backend = PedalboardProcessingTests._backend_with_dry_reverb()
        backend.update_creative_effects(CreativeEffectSettings(preset=preset))
        blocks = []
        for start in range(0, samples.size, block_size):
            block = samples[start : start + block_size]
            blocks.append(
                np.asarray(
                    backend._effects.process(
                        block[None, :],
                        48_000,
                        buffer_size=block.size,
                        reset=False,
                    )
                ).reshape(-1)
            )
        return np.concatenate(blocks)

    def test_creative_presets_do_not_depend_on_a_volume_boost(self) -> None:
        sample_rate = 48_000
        time = np.arange(sample_rate * 2, dtype=np.float32) / sample_rate
        envelope = 0.45 + 0.35 * np.sin(2 * np.pi * 2.7 * time)
        speech_like = (
            0.10 * np.sin(2 * np.pi * 115 * time)
            + 0.06 * np.sin(2 * np.pi * 230 * time)
            + 0.035 * np.sin(2 * np.pi * 690 * time)
            + 0.025 * np.sin(2 * np.pi * 2100 * time)
        ).astype(np.float32) * envelope
        backend = self._backend_with_dry_reverb()
        clean = self._render_preset(backend, speech_like, "none")
        clean_rms = float(np.sqrt(np.mean(clean * clean)))

        for preset in ("telephone", "megaphone", "robot"):
            processed = self._render_preset(backend, speech_like, preset)
            processed_rms = float(np.sqrt(np.mean(processed * processed)))
            self.assertGreater(processed_rms, clean_rms * 0.65, preset)
            self.assertLess(processed_rms, clean_rms * 1.05, preset)

    def test_disabled_reverb_keeps_ninety_percent_headroom_in_pedalboard(self) -> None:
        backend = self._backend_with_dry_reverb()
        samples = np.full(2048, 0.1, dtype=np.float32)

        processed = self._render_preset(backend, samples, "none")

        np.testing.assert_allclose(processed, 0.09, atol=1e-6)

    def test_walkie_talkie_has_a_narrow_radio_band(self) -> None:
        sample_rate = 48_000
        noise = np.random.default_rng(42).normal(
            0.0, 0.05, sample_rate * 2
        ).astype(np.float32)
        backend = self._backend_with_dry_reverb()
        walkie = self._render_preset(backend, noise, "telephone")
        frequencies = np.fft.rfftfreq(walkie.size, 1.0 / sample_rate)
        power = np.abs(np.fft.rfft(walkie)) ** 2
        low = float(np.mean(power[(frequencies > 40) & (frequencies < 200)]))
        voice_band = float(
            np.mean(power[(frequencies > 400) & (frequencies < 2800)])
        )
        high = float(
            np.mean(power[(frequencies > 4000) & (frequencies < 10000)])
        )

        self.assertLess(low / voice_band, 0.20)
        self.assertLess(high / voice_band, 0.05)

    def test_walkie_talkie_remains_audible_in_realtime_blocks(self) -> None:
        sample_rate = 48_000
        sample_count = 512 * 180
        time = np.arange(sample_count, dtype=np.float32) / sample_rate
        envelope = 0.45 + 0.35 * np.sin(2 * np.pi * 2.7 * time)
        speech_like = (
            0.10 * np.sin(2 * np.pi * 115 * time)
            + 0.06 * np.sin(2 * np.pi * 230 * time)
            + 0.035 * np.sin(2 * np.pi * 690 * time)
            + 0.025 * np.sin(2 * np.pi * 2100 * time)
        ).astype(np.float32) * envelope

        clean = self._render_streaming_preset(speech_like, "none")
        walkie = self._render_streaming_preset(speech_like, "telephone")
        warmup = 4096
        clean_rms = float(np.sqrt(np.mean(clean[warmup:] ** 2)))
        walkie_rms = float(np.sqrt(np.mean(walkie[warmup:] ** 2)))

        self.assertGreater(walkie_rms, clean_rms * 0.65)
        self.assertLess(walkie_rms, clean_rms * 1.10)

    def test_walkie_radio_texture_follows_voice_without_idle_hiss(self) -> None:
        transform = _RealtimeTransform(
            np,
            sample_rate=48_000,
            voice_preset="none",
            style_preset="telephone",
            modulation="none",
        )
        silence = np.zeros(512, dtype=np.float32)
        np.testing.assert_array_equal(transform.process_mono(silence), silence)

        timeline = np.arange(512, dtype=np.float32) / 48_000
        voice = (0.08 * np.sin(2 * np.pi * 440 * timeline)).astype(np.float32)
        textured = transform.process_mono(voice)
        clipped_only = np.tanh(voice * 1.8) / np.tanh(1.8)
        radio_texture = textured - clipped_only

        self.assertGreater(
            float(np.sqrt(np.mean(radio_texture * radio_texture))),
            0.002,
        )

    def test_radio_beeps_mark_the_start_and_end_of_transmission(self) -> None:
        transform = _RealtimeTransform(
            np,
            sample_rate=48_000,
            voice_preset="none",
            style_preset="walkie_police",
            modulation="none",
            roger_beep=True,
        )
        voice = np.full(512, 0.05, dtype=np.float32)
        start = transform.process_mono(voice)
        silence_blocks = [
            transform.process_mono(np.zeros(512, dtype=np.float32))
            for _ in range(30)
        ]

        self.assertGreater(float(np.std(start - voice)), 0.005)
        self.assertGreater(
            max(float(np.sqrt(np.mean(block * block))) for block in silence_blocks),
            0.01,
        )

    def test_convolution_and_stereo_widener_keep_streaming_state(self) -> None:
        convolution = _RealtimeTransform(
            np, 48_000, "none", "none", "none", "convolution_room"
        )
        impulse = np.zeros(512, dtype=np.float32)
        impulse[0] = 0.5
        convolution.process_mono(impulse)
        tail = convolution.process_mono(np.zeros(512, dtype=np.float32))
        self.assertGreater(float(np.max(np.abs(tail))), 0.01)

        widener = _RealtimeTransform(
            np, 48_000, "none", "none", "stereo_widener"
        )
        mono = np.column_stack((np.ones(1024), np.ones(1024))).astype(np.float32)
        widened = widener.process_stereo(mono)
        self.assertGreater(
            float(np.max(np.abs(widened[:, 0] - widened[:, 1]))),
            0.1,
        )

    def test_block_based_styles_smooth_callback_boundaries(self) -> None:
        block_size = 512
        timeline = np.arange(block_size * 14, dtype=np.float32) / 48_000
        source = (0.10 * np.sin(2 * np.pi * 237.0 * timeline)).astype(np.float32)

        for preset in (
            "reverse",
            "glitch",
            "stutter",
            "spectral_freeze",
            "granular",
        ):
            transform = _RealtimeTransform(
                np, 48_000, "none", preset, "none", style_intensity=0.70
            )
            rendered = np.concatenate(
                [
                    transform.process_mono(source[start : start + block_size])
                    for start in range(0, source.size, block_size)
                ]
            )
            boundary_jumps = np.abs(
                rendered[block_size::block_size]
                - rendered[block_size - 1 :: block_size][:-1]
            )

            self.assertLess(float(np.max(boundary_jumps)), 0.012, preset)

    def test_granular_style_bridges_reordered_grain_edges(self) -> None:
        block_size = 512
        timeline = np.arange(block_size, dtype=np.float32) / 48_000
        source = (0.10 * np.sin(2 * np.pi * 237.0 * timeline)).astype(np.float32)
        transform = _RealtimeTransform(
            np, 48_000, "none", "granular", "none", style_intensity=1.0
        )

        rendered = transform.process_mono(source)
        grain_jumps = [
            abs(float(rendered[index] - rendered[index - 1]))
            for index in range(64, block_size, 64)
        ]

        self.assertLess(max(grain_jumps), 0.012)

    def test_radio_interference_ramps_its_intentional_dropouts(self) -> None:
        transform = _RealtimeTransform(
            np, 48_000, "none", "radio_interference", "none",
            style_intensity=1.0,
        )
        source = np.full(512, 0.10, dtype=np.float32)
        blocks = [transform.process_mono(source) for _ in range(14)]

        entering_dropout = blocks[11]

        self.assertGreater(float(entering_dropout[0]), 0.075)
        self.assertLess(float(np.mean(entering_dropout[-64:])), 0.055)

    def test_soundboard_ducking_reduces_vinyl_under_the_voice(self) -> None:
        def render(ducking: bool):
            backend = self._backend_with_dry_reverb()
            backend.update_creative_effects(CreativeEffectSettings())
            backend._soundboard._builtins["steady"] = np.full(
                512, 0.10, dtype=np.float32
            )
            backend.update_soundboard(
                SoundboardSettings(
                    volume_percent=100,
                    ducking_enabled=ducking,
                    ducking_percent=75,
                )
            )
            backend.play_sound("steady")
            microphone = np.full((512, 2), 0.06, dtype=np.float32)
            return backend._process_audio(microphone, 512)[:, 0]

        without_ducking = render(False)
        with_ducking = render(True)
        self.assertLess(float(np.mean(with_ducking)), float(np.mean(without_ducking)))

    def test_voice_presets_shift_pitch_in_realtime_blocks(self) -> None:
        sample_rate = 48_000
        block_size = 512
        sample_count = block_size * 72
        timeline = np.arange(sample_count, dtype=np.float32) / sample_rate
        source = (0.10 * np.sin(2 * np.pi * 220 * timeline)).astype(np.float32)

        for semitones, minimum_hz, maximum_hz in (
            (-4.0, 155.0, 195.0),
            (4.0, 255.0, 300.0),
        ):
            backend = self._backend_with_dry_reverb()
            backend.update_voice_effect(
                VoiceSettings(enabled=True, pitch_semitones=semitones)
            )
            rendered_blocks = []
            for block_index, start in enumerate(
                range(0, sample_count, block_size), start=1
            ):
                block = source[start : start + block_size]
                stereo_input = np.column_stack((block, block))
                rendered_blocks.append(
                    backend._process_audio(stereo_input, block_size)[:, 0]
                )
                if block_index % 6 == 0:
                    time.sleep(0.05)

            backend._pitch_shifter.close()
            rendered = np.concatenate(rendered_blocks)[8192:-2048]
            rms = float(np.sqrt(np.mean(rendered * rendered)))
            frequencies = np.fft.rfftfreq(rendered.size, 1.0 / sample_rate)
            peak_hz = float(
                frequencies[np.argmax(np.abs(np.fft.rfft(rendered)))]
            )

            self.assertGreater(rms, 0.02, semitones)
            self.assertGreater(peak_hz, minimum_hz, semitones)
            self.assertLess(peak_hz, maximum_hz, semitones)

    def test_low_eq_uses_the_pedalboard_low_shelf_filter(self) -> None:
        backend = PedalboardBackend()
        backend._reverb = backend._Reverb()

        backend.update_pro_audio(ProAudioSettings(eq_enabled=True, eq_low_db=3.0))

        self.assertIsNotNone(backend._effects)

    def test_advanced_pro_audio_effects_are_added_to_the_main_chain(self) -> None:
        backend = self._backend_with_dry_reverb()
        backend.update_pro_audio(
            ProAudioSettings(
                noise_gate_enabled=True,
                deesser_enabled=True,
                expander_enabled=True,
                auto_gain_enabled=True,
                plosive_filter_enabled=True,
            )
        )

        effect_names = [type(effect).__name__ for effect in backend._effects]
        self.assertEqual(effect_names.count("NoiseGate"), 2)
        self.assertGreaterEqual(effect_names.count("HighpassFilter"), 2)
        self.assertIn("HighShelfFilter", effect_names)
        self.assertIn("Gain", effect_names)

    def test_eq_updates_preserve_running_effects_and_delay_tail(self) -> None:
        backend = self._backend_with_dry_reverb()
        backend.update_creative_effects(CreativeEffectSettings(
            delay_enabled=True, delay_level_percent=60,
        ))
        chain = backend._effects
        transform = backend._realtime_transform
        impulse = np.zeros((1, 256), dtype=np.float32)
        impulse[0, 0] = 0.5
        chain.process(impulse, 48000, reset=False)
        with patch.object(backend, "_rebuild_effects_chain", wraps=backend._rebuild_effects_chain) as rebuild:
            for enabled, gain in ((True, 0.0), (True, 6.0), (False, 6.0)):
                backend.update_pro_audio(ProAudioSettings(eq_enabled=enabled, eq_low_db=gain))
            rebuild.assert_not_called()
        self.assertIs(backend._effects, chain)
        self.assertIs(backend._realtime_transform, transform)
        tail = np.concatenate([
            chain.process(np.zeros((1, 256), dtype=np.float32), 48000,
                          buffer_size=256, reset=False)
            for _ in range(200)
        ], axis=1)
        self.assertGreater(float(np.max(abs(tail))), 0.01)

    def test_eq_gain_ramps_without_gaps_and_returns_to_neutral(self) -> None:
        backend = self._backend_with_dry_reverb()
        eq = backend._equalizer
        source = np.full((1, 4800), 0.05, dtype=np.float32)
        eq.process(source, 48000, reset=False)
        backend.update_pro_audio(ProAudioSettings(eq_enabled=True, eq_low_db=12.0))
        first = eq.process(source[:, :64], 48000, reset=False)
        self.assertGreater(eq._gains[0], 0)
        self.assertLess(eq._gains[0], 12)
        rest = eq.process(source, 48000, reset=False)
        combined = np.concatenate((first, rest), axis=1)
        self.assertTrue(np.isfinite(combined).all())
        self.assertGreater(float(combined.min()), 0.04)
        self.assertLess(float(np.max(abs(np.diff(combined)))), 0.01)
        self.assertAlmostEqual(float(rest[0, -1]), 0.05 * 10 ** (12 / 20), delta=0.002)
        backend.update_pro_audio(ProAudioSettings(eq_enabled=False, eq_low_db=12.0))
        neutral = eq.process(source, 48000, reset=False)
        self.assertAlmostEqual(float(neutral[0, -1]), 0.05, delta=0.001)

    def test_non_eq_pro_settings_still_update_chain(self) -> None:
        backend = self._backend_with_dry_reverb()
        backend.update_pro_audio(ProAudioSettings())
        backend.update_pro_audio(ProAudioSettings(compressor_enabled=True, eq_enabled=True, eq_mid_db=3.0))
        self.assertIn("Compressor", [type(effect).__name__ for effect in backend._effects])

        backend.update_voice_effect(VoiceSettings(enabled=True, preset="female"))
        self.assertIsNotNone(backend._pitch_shifter)
        backend.deactivate()

    def test_negotiated_sample_rate_rebuilds_realtime_effect_state(self) -> None:
        backend = PedalboardBackend()
        backend._input_ids = {"Microfone": [(1, "Windows WASAPI")]}
        backend._output_ids = {"Cabo": [(2, "Windows WASAPI")]}
        backend.update_creative_effects(
            CreativeEffectSettings(modulation="haas")
        )

        class FakeCreatedStream:
            @staticmethod
            def validate_start() -> None:
                return None

            @staticmethod
            def close() -> None:
                return None

        device_info = {
            1: {
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 44_100.0,
            },
            2: {
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 44_100.0,
            },
        }
        created_stream = FakeCreatedStream()
        with (
            patch.object(backend, "_refresh_devices"),
            patch.object(
                backend._sd,
                "query_devices",
                side_effect=lambda device: device_info[device],
            ),
            patch.object(
                backend, "_find_common_sample_rate", return_value=44_100.0
            ),
            patch(
                "mini_mesa.audio_engine._MultiOutputSoundDeviceStream",
                return_value=created_stream,
            ),
        ):
            stream = backend.create_stream(
                "Microfone", "Cabo", ReverbSettings(enabled=False)
            )

        self.assertIs(stream, created_stream)
        self.assertEqual(backend._realtime_transform._sample_rate, 44_100.0)
        self.assertEqual(
            backend._realtime_transform._haas_delay.size,
            round(44_100.0 * 0.018),
        )
        backend.deactivate()

    def test_zero_intensity_bypasses_style_modulation_and_ambience(self) -> None:
        timeline = np.arange(512, dtype=np.float32) / 48_000
        mono = (0.10 * np.sin(2 * np.pi * 440.0 * timeline)).astype(np.float32)
        stereo = np.column_stack((mono, mono))

        def render(settings: CreativeEffectSettings, blocks: int = 1) -> np.ndarray:
            backend = self._backend_with_dry_reverb()
            backend._limiter = None
            backend._spatializer = None
            backend.update_creative_effects(settings)
            return np.concatenate(
                [backend._process_audio(stereo, 512)[:, 0] for _ in range(blocks)]
            )

        dry = render(CreativeEffectSettings(), blocks=50)
        telephone = render(
            CreativeEffectSettings(preset="telephone", style_intensity_percent=0),
            blocks=50,
        )
        tremolo = render(
            CreativeEffectSettings(
                modulation="tremolo", modulation_intensity_percent=0
            ),
            blocks=50,
        )
        mountain = render(
            CreativeEffectSettings(
                ambience="mountain", ambience_intensity_percent=0
            ),
            blocks=50,
        )

        np.testing.assert_allclose(telephone, dry, atol=1e-6)
        np.testing.assert_allclose(tremolo, dry, atol=1e-6)
        np.testing.assert_allclose(mountain, dry, atol=1e-6)

    def test_pitch_worker_reports_processor_failures(self) -> None:
        class FailingProcessor:
            @staticmethod
            def process(*_args, **_kwargs):
                raise RuntimeError("falha nativa")

        shifter = _StreamingPitchShifter(
            np, FailingProcessor(), 48_000, window_size=4, overlap=1
        )
        shifter.process(np.ones(4, dtype=np.float32))
        for _ in range(100):
            if shifter._error is not None:
                break
            time.sleep(0.005)

        with self.assertRaisesRegex(RuntimeError, "modificador de voz"):
            shifter.process(np.ones(4, dtype=np.float32))
        shifter.close()

    def test_all_new_effect_presets_build_successfully(self) -> None:
        backend = self._backend_with_dry_reverb()
        for preset in VALID_CREATIVE_PRESETS:
            backend.update_creative_effects(CreativeEffectSettings(preset=preset))
            self.assertIsNotNone(backend._effects, preset)
        for modulation in VALID_MODULATIONS:
            backend.update_creative_effects(
                CreativeEffectSettings(modulation=modulation)
            )
            self.assertIsNotNone(backend._effects, modulation)
        for ambience in VALID_AMBIENCES:
            backend.update_creative_effects(CreativeEffectSettings(ambience=ambience))
            self.assertIsNotNone(backend._effects, ambience)
        backend.update_pro_audio(
            ProAudioSettings(
                noise_gate_enabled=True,
                deesser_enabled=True,
                expander_enabled=True,
                auto_gain_enabled=True,
                plosive_filter_enabled=True,
            )
        )
        self.assertIsNotNone(backend._effects)

    def test_all_creative_options_remain_audible_in_realtime_blocks(self) -> None:
        sample_rate = 48_000
        block_size = 512
        sample_count = block_size * 24
        timeline = np.arange(sample_count, dtype=np.float32) / sample_rate
        source = (
            0.08 * np.sin(2 * np.pi * 220 * timeline)
            + 0.04 * np.sin(2 * np.pi * 880 * timeline)
        ).astype(np.float32)
        stereo = np.column_stack((source, source))

        configurations = [
            CreativeEffectSettings(preset=value)
            for value in VALID_CREATIVE_PRESETS
        ]
        configurations.extend(
            CreativeEffectSettings(modulation=value) for value in VALID_MODULATIONS
        )
        configurations.extend(
            CreativeEffectSettings(ambience=value) for value in VALID_AMBIENCES
        )
        for settings in configurations:
            backend = self._backend_with_dry_reverb()
            backend.update_creative_effects(settings)
            rendered = np.concatenate(
                [
                    backend._process_audio(stereo[start : start + block_size], block_size)[
                        :, 0
                    ]
                    for start in range(0, sample_count, block_size)
                ]
            )
            rms = float(np.sqrt(np.mean(rendered * rendered)))
            self.assertGreater(rms, 0.002, settings)

    def test_all_voice_presets_configure_a_realtime_processor(self) -> None:
        backend = self._backend_with_dry_reverb()
        for preset in VALID_VOICE_PRESETS:
            backend.update_voice_effect(VoiceSettings(enabled=True, preset=preset))
            if preset == "custom":
                self.assertIsNotNone(backend._pitch_shifter)
            else:
                self.assertIsNotNone(backend._pitch_shifter, preset)
        if backend._pitch_shifter is not None:
            backend._pitch_shifter.close()

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
        backend._soundboard_settings = SoundboardSettings(volume_percent=100)

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
        backend._soundboard_settings = SoundboardSettings(volume_percent=100)

        output = backend._process_audio(
            np.full((4, 1), 0.20, dtype=np.float32),
            4,
        )

        np.testing.assert_allclose(reverb.received, np.full((1, 4), 0.45))
        np.testing.assert_allclose(spatializer.received, np.full(4, 0.90))
        np.testing.assert_allclose(output[:, 0], np.full(4, 0.90))
        np.testing.assert_allclose(output[:, 1], np.full(4, 2.70))


class AudioEngineTests(unittest.TestCase):
    def test_soundboard_only_plays_while_the_route_is_active(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)

        self.assertFalse(engine.play_sound("horn"))
        self.assertEqual(backend.played_sounds, [])

        engine.start("Zeus X", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))
        self.assertTrue(engine.play_sound("horn"))
        self.assertEqual(backend.played_sounds, ["horn"])
        engine.stop()

    def test_failed_live_update_keeps_the_previous_engine_settings(self) -> None:
        class FailingBackend(FakeBackend):
            def update_voice_effect(self, settings: VoiceSettings) -> None:
                if settings.enabled:
                    raise RuntimeError("plugin indisponível")
                super().update_voice_effect(settings)

        backend = FailingBackend()
        engine = AudioEngine(backend)
        engine.start("Zeus X", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))

        with self.assertRaisesRegex(RuntimeError, "plugin indisponível"):
            engine.update_voice_settings(VoiceSettings(enabled=True))

        self.assertEqual(engine.voice_settings, VoiceSettings())
        engine.stop()

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

    def test_timed_out_stop_keeps_old_route_registered_until_it_exits(self) -> None:
        class SlowStopStream(FakeStream):
            def __init__(self) -> None:
                super().__init__()
                self.release = threading.Event()

            def run(self) -> None:
                self.started.set()
                self.release.wait(timeout=1)

            def close(self) -> None:
                return None

        stream = SlowStopStream()
        engine = AudioEngine(FakeBackend(stream))
        engine.start("FIFINE AM8", "CABLE Input")
        self.assertTrue(stream.started.wait(timeout=1))

        with self.assertRaisesRegex(RuntimeError, "não encerrou a tempo"):
            engine.stop(timeout=0.01)

        self.assertTrue(engine.is_running)
        stream.release.set()
        engine._thread.join(timeout=1)  # type: ignore[union-attr]
        self.assertFalse(engine.is_running)

    def test_settings_staged_before_start_reach_the_backend(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        voice = VoiceSettings(enabled=True, pitch_semitones=-4.0)
        creative = CreativeEffectSettings(
            preset="telephone", delay_enabled=True, delay_level_percent=45
        )
        pro_audio = ProAudioSettings(
            compressor_enabled=True,
            eq_enabled=True,
            eq_low_db=3.0,
            eq_mid_db=-2.0,
            eq_high_db=1.0,
        )
        soundboard = SoundboardSettings(volume_percent=55)

        engine.update_voice_settings(voice)
        engine.update_creative_settings(creative)
        engine.update_pro_audio_settings(pro_audio)
        engine.update_soundboard_settings(soundboard)
        engine.start("FIFINE AM8", "CABLE Input")

        self.assertEqual(backend.voice_settings, voice)
        self.assertEqual(backend.creative_settings, creative)
        self.assertEqual(backend.pro_audio_settings, pro_audio)
        self.assertEqual(backend.soundboard_settings, soundboard)
        engine.stop()

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

    def test_all_live_effect_changes_reach_the_backend(self) -> None:
        backend = FakeBackend()
        engine = AudioEngine(backend)
        engine.start("Zeus X", "CABLE Input")
        self.assertTrue(backend.stream.started.wait(timeout=1))
        voice = VoiceSettings(enabled=True, pitch_semitones=6.0)
        creative = CreativeEffectSettings(
            preset="robot", delay_enabled=True, delay_level_percent=60
        )
        pro_audio = ProAudioSettings(
            compressor_enabled=True,
            eq_enabled=True,
            eq_low_db=2.0,
            eq_mid_db=-1.0,
            eq_high_db=3.0,
        )
        soundboard = SoundboardSettings(volume_percent=40)

        engine.update_voice_settings(voice)
        engine.update_creative_settings(creative)
        engine.update_pro_audio_settings(pro_audio)
        engine.update_soundboard_settings(soundboard)

        self.assertEqual(backend.voice_settings, voice)
        self.assertEqual(backend.creative_settings, creative)
        self.assertEqual(backend.pro_audio_settings, pro_audio)
        self.assertEqual(backend.soundboard_settings, soundboard)
        self.assertTrue(engine.is_running)
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

    def test_pedalboard_backend_initialization(self) -> None:
        backend = PedalboardBackend()
        self.assertEqual(backend._sample_rate, 48_000.0)
        self.assertIsNotNone(backend._soundboard)


if __name__ == "__main__":
    unittest.main()


class EffectsOnlyMonitoringTests(unittest.TestCase):
    def test_backend_preview_resamples_and_uses_selected_physical_output(self):
        backend = PedalboardBackend()
        fake_sd = Mock()
        fake_sd.query_devices.return_value = {"default_samplerate": 48_000}
        backend._sd = fake_sd
        backend._output_ids = {"Fones": [(7, "Windows WASAPI")]}
        source = np.full((24, 2), 0.25, dtype=np.float32)
        with (
            patch.object(backend, "_refresh_devices"),
            patch("mini_mesa.audio_engine._read_custom_audio", return_value=(source, 24_000)),
        ):
            backend.preview_sound("efeito.flac", "Fones")
        played = fake_sd.play.call_args
        self.assertEqual(played.kwargs["samplerate"], 48_000)
        self.assertEqual(played.kwargs["device"], 7)
        self.assertEqual(played.args[0].shape, (48, 2))
        backend.stop_preview()
        fake_sd.stop.assert_called_once()

    def test_preview_uses_output_only_while_stopped_and_soundboard_while_running(self):
        backend = FakeBackend()
        engine = AudioEngine(backend)
        engine.preview_sound("preview.wav", "Fones")
        self.assertEqual(backend.previewed_sounds, [("preview.wav", "Fones")])
        engine.stop_preview()
        self.assertEqual(backend.preview_stops, 1)
        try:
            engine.start("FIFINE AM8", "CABLE Input", effects_output="Alto-falantes")
            engine.preview_sound("live.wav", "Fones")
            self.assertEqual(backend.played_sounds, ["live.wav"])
            engine.stop_preview()
            self.assertEqual(backend.effects_stopped, 1)
        finally:
            engine.stop()

    def test_real_sound_reaches_both_routes_but_microphone_only_reaches_recording(self):
        import tempfile
        from pathlib import Path
        import soundfile as sf
        backend = PedalboardProcessingTests._backend_with_dry_reverb()
        backend.update_creative_effects(CreativeEffectSettings())
        backend.update_soundboard(SoundboardSettings(volume_percent=100))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "effect.wav"
            sf.write(path, np.full(1536, 0.2, dtype=np.float32), 48000)
            self.assertTrue(backend.play_sound(str(path)))
        stream = _MultiOutputSoundDeviceStream(
            sounddevice=FakeSoundDevice(), input_id=1, outputs=[(2, 2), (3, 2)],
            sample_rate=48000, input_channels=1, block_size=512,
            processor=backend._process_audio,
            effects_processor=lambda: backend._effects_monitor_audio,
            monitor_voice=False,
        )
        try:
            microphone = np.full((512, 1), 0.1, dtype=np.float32)
            stream._on_input(microphone, 512, None, None)
            primary, monitor = stream._outputs
            np.testing.assert_allclose(monitor._chunks[-1], 0.2, atol=0.0001)
            self.assertGreater(float(np.mean(primary._chunks[-1])), 0.2)
            stream.set_monitor_voice(True)
            self.assertEqual(monitor._queued_frames, 0)
            stream._on_input(microphone, 512, None, None)
            np.testing.assert_array_equal(primary._chunks[-1], monitor._chunks[-1])
            stream.set_monitor_voice(False)
            self.assertEqual(monitor._queued_frames, 0)
            stream._on_input(microphone, 512, None, None)
            np.testing.assert_allclose(monitor._chunks[-1], 0.2, atol=0.0001)
            stream._on_input(microphone, 512, None, None)
            self.assertFalse(np.any(monitor._chunks[-1]))
            self.assertTrue(np.any(primary._chunks[-1]))
        finally:
            stream.close()
            backend.deactivate()

    def test_engine_keeps_local_device_open_when_voice_return_is_toggled(self):
        backend = FakeBackend()
        engine = AudioEngine(backend)
        try:
            engine.start("FIFINE AM8", "CABLE Input", effects_output="Alto-falantes")
            self.assertEqual(backend.created_with[3], "Alto-falantes")
            self.assertFalse(backend.stream.monitor_voice)
            engine.update_monitor("Alto-falantes")
            self.assertTrue(backend.stream.monitor_voice)
            engine.update_monitor(None)
            self.assertFalse(backend.stream.monitor_voice)
            self.assertEqual(backend.updated_monitors, [])
            engine.update_monitor(None, effects_output="Fones")
            self.assertEqual(backend.updated_monitors, ["Fones"])
        finally:
            engine.stop()

    def test_effects_cannot_be_routed_back_to_virtual_cable(self):
        engine = AudioEngine(FakeBackend())
        with self.assertRaisesRegex(ValueError, "diferente da saída virtual"):
            engine.start("FIFINE AM8", "CABLE Input", effects_output="CABLE Input")
