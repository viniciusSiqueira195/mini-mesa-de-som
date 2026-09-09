from __future__ import annotations

import json
import sys
from pathlib import Path

from mini_mesa.__main__ import main


def _self_test(result_path: Path) -> int:
    result: dict[str, object] = {"ok": False}
    reducer = None
    backend = None
    frame = None
    try:
        import tempfile
        import numpy as np
        import soundfile as sf
        import sounddevice as sd
        import wx
        from mini_mesa import ui
        from mini_mesa.preferences import AppPreferences, PersonalSound, PreferencesStore
        from mini_mesa.soundboard import SoundboardMixer
        from mini_mesa.recorder import AudioRecorder
        from mini_mesa.settings import RecordingSettings
        from mini_mesa.audio_engine import AudioEngine, PedalboardBackend
        from mini_mesa.noise_reduction import RNNOISE_FRAME_SIZE, RNNoiseReducer
        from mini_mesa.settings import SpatialSettings
        from mini_mesa.spatial_audio import HRTFSpatializer
        from mini_mesa.user_features import (
            ProfileStore,
            diagnostic_text,
            export_backup,
            import_backup,
        )

        backend = PedalboardBackend()
        input_devices = backend.input_devices()
        output_devices = backend.output_devices()

        reducer = RNNoiseReducer()
        denoised = reducer.process(np.zeros(RNNOISE_FRAME_SIZE, dtype=np.float32))
        if denoised.shape != (RNNOISE_FRAME_SIZE,):
            raise RuntimeError("O RNNoise retornou um bloco com tamanho inválido.")

        spatializer = HRTFSpatializer(48_000)
        spatializer.update(SpatialSettings(enabled=True, x=71, z=71))
        spatial = spatializer.process(np.zeros(480, dtype=np.float32))
        if spatial.shape != (480, 2):
            raise RuntimeError("O HRTF retornou um bloco com formato inválido.")

        from mini_mesa.release_notes import load_release_notes
        if not load_release_notes().strip():
            raise RuntimeError("O arquivo de novidades está vazio.")
        document = ui._load_project_markdown()
        if not document or "<h1" not in ui._markdown_to_help_html(document):
            raise RuntimeError("A ajuda ou suas extensões Markdown não foram empacotadas.")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for extension in ("wav", "mp3", "ogg"):
                recorder = AudioRecorder(RecordingSettings(
                    format=extension, folder=str(root), custom_filename=f"recording.{extension}",
                ))
                samples = np.column_stack([
                    np.sin(np.arange(4800) * 0.1).astype(np.float32) * 0.1,
                ] * 2)
                recorder.push(samples)
                path, duration = recorder.stop()
                recorded, rate = sf.read(path)
                if rate != 48000 or duration <= 0 or not np.any(recorded):
                    raise RuntimeError(f"A gravação {extension} não funciona no pacote.")
            beep = Path(ui.__file__).parent / "assets" / "feedback" / "recording_start.wav"
            beep_audio, beep_rate = sf.read(beep)
            if beep_rate != 44100 or not np.any(beep_audio):
                raise RuntimeError("O beep de gravação não foi empacotado corretamente.")
            for extension in ("wav", "flac", "ogg", "mp3"):
                path = root / f"probe.{extension}"
                sf.write(path, np.sin(np.arange(4800) * 0.1).astype(np.float32) * 0.1, 48000)
                mixer = SoundboardMixer()
                if not mixer.play(str(path)) or not np.any(mixer.mix(4800)):
                    raise RuntimeError(f"O codec {extension} não funciona no pacote.")
            preferences = AppPreferences(
                welcome_shown=True,
                last_seen_news_version=ui.__version__,
                personal_sounds=(PersonalSound("Teste", str(root / "probe.wav")),),
            )
            store = PreferencesStore(root / "preferences.json")
            store.save(preferences)
            profiles = ProfileStore(root / "profiles.json")
            profiles.save("Teste", preferences)
            if profiles.load("Teste", preferences).personal_sounds != preferences.personal_sounds:
                raise RuntimeError("Os perfis não funcionam no pacote.")
            backup = root / "teste.mmb"
            export_backup(preferences, backup, include_audio=True)
            restored = import_backup(backup, root / "restored-audio")
            if not Path(restored.personal_sounds[0].path).is_file():
                raise RuntimeError("O backup portátil não restaurou o áudio.")
            engine = AudioEngine(backend)
            if "Entradas encontradas" not in diagnostic_text(engine, preferences):
                raise RuntimeError("O diagnóstico acessível não funciona no pacote.")
            app = wx.App.Get() or wx.App(False)
            original_tray, original_update = ui.SystemTrayIcon, ui.can_self_update
            try:
                ui.SystemTrayIcon = lambda _frame: None
                ui.can_self_update = lambda: False
                frame = ui.MainFrame(engine, preferences_store=store)
                frame.Destroy()
                frame = None
                app.ProcessPendingEvents()
            finally:
                ui.SystemTrayIcon, ui.can_self_update = original_tray, original_update

        result.update(
            ok=True,
            input_devices=len(input_devices),
            output_devices=len(output_devices),
            pedalboard=True,
            rnnoise=True,
            hrtf=True,
            interface=True,
            help=True,
            release_notes=True,
            recording=True,
            recording_beep=True,
            user_features=True,
            codecs=["wav", "mp3", "flac", "ogg"],
            device_inventory=[dict(device) for device in sd.query_devices()],
            host_apis=[dict(api) for api in sd.query_hostapis()],
            monitor_devices=list(backend.monitor_devices()),
        )
        return_code = 0
    except Exception as exc:
        result.update(error=f"{type(exc).__name__}: {exc}")
        return_code = 1
    finally:
        if frame is not None:
            frame.Destroy()
        if backend is not None:
            backend.deactivate()
        if reducer is not None:
            reducer.close()
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return return_code


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        raise SystemExit(_self_test(Path(sys.argv[2])))
    raise SystemExit(main())
