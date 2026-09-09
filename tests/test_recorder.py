from datetime import datetime
from pathlib import Path
import tempfile
import unittest
import numpy as np

from mini_mesa.recorder import AudioRecorder, generate_default_filename, default_recordings_directory
from mini_mesa.settings import RecordingSettings
from mini_mesa.audio_engine import AudioEngine, PedalboardBackend


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generate_default_filename(self):
        dt = datetime(2026, 9, 9, 16, 41, 0)
        self.assertEqual(generate_default_filename("mp3", dt), "Gravação 2026-09-09_16-41-00.mp3")
        self.assertEqual(generate_default_filename("wav", dt), "Gravação 2026-09-09_16-41-00.wav")
        self.assertEqual(generate_default_filename("ogg", dt), "Gravação 2026-09-09_16-41-00.ogg")

    def test_record_wav(self):
        settings = RecordingSettings(
            format="wav",
            mode="both",
            custom_filename="test_rec.wav",
            folder=str(self.folder),
        )
        recorder = AudioRecorder(settings, sample_rate=48000, channels=2)
        self.assertTrue(recorder.is_recording)

        frame = (np.sin(2 * np.pi * 440 * np.linspace(0, 0.1, 4800)).astype(np.float32))
        data = np.column_stack([frame, frame])
        recorder.push(data)

        path, duration = recorder.stop()
        self.assertFalse(recorder.is_recording)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 0)
        self.assertGreaterEqual(duration, 0.0)

    def test_record_mp3(self):
        settings = RecordingSettings(
            format="mp3",
            bitrate_kbps=192,
            mode="voice",
            custom_filename="test_rec.mp3",
            folder=str(self.folder),
        )
        recorder = AudioRecorder(settings, sample_rate=48000, channels=2)
        self.assertTrue(recorder.is_recording)

        frame = (np.sin(2 * np.pi * 440 * np.linspace(0, 0.1, 4800)).astype(np.float32))
        data = np.column_stack([frame, frame])
        recorder.push(data)

        path, duration = recorder.stop()
        self.assertFalse(recorder.is_recording)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 0)

    def test_record_ogg(self):
        settings = RecordingSettings(
            format="ogg",
            bitrate_kbps=160,
            mode="processes",
            custom_filename="test_rec.ogg",
            folder=str(self.folder),
        )
        recorder = AudioRecorder(settings, sample_rate=48000, channels=2)
        self.assertTrue(recorder.is_recording)

        frame = (np.sin(2 * np.pi * 440 * np.linspace(0, 0.1, 4800)).astype(np.float32))
        data = np.column_stack([frame, frame])
        recorder.push(data)

        path, duration = recorder.stop()
        self.assertFalse(recorder.is_recording)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 0)

    def test_engine_recording_lifecycle(self):
        backend = PedalboardBackend()
        engine = AudioEngine(backend=backend)

        settings = RecordingSettings(
            format="wav",
            mode="both",
            custom_filename="engine_rec.wav",
            folder=str(self.folder),
        )
        self.assertFalse(engine.is_recording)
        path = engine.start_recording(settings)
        self.assertTrue(engine.is_recording)
        self.assertEqual(path.name, "engine_rec.wav")

        rec_path, duration = engine.stop_recording()
        self.assertFalse(engine.is_recording)
        self.assertTrue(rec_path.exists())


if __name__ == "__main__":
    unittest.main()
