from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from mini_mesa.__main__ import main


def _self_test(result_path: Path) -> int:
    result: dict[str, object] = {"ok": False}
    reducer = None
    try:
        from mini_mesa.audio_engine import PedalboardBackend
        from mini_mesa.noise_reduction import RNNOISE_FRAME_SIZE, RNNoiseReducer
        from mini_mesa.settings import SpatialSettings
        from mini_mesa.spatial_audio import HRTFSpatializer

        backend = PedalboardBackend()
        input_devices = backend.input_devices()
        output_devices = backend.output_devices()

        reducer = RNNoiseReducer()
        denoised = reducer.process(np.zeros(RNNOISE_FRAME_SIZE, dtype=np.float32))
        if denoised.shape != (RNNOISE_FRAME_SIZE,):
            raise RuntimeError("O RNNoise retornou um bloco com tamanho inválido.")

        spatializer = HRTFSpatializer(48_000)
        spatializer.update(SpatialSettings(enabled=True, angle_degrees=45))
        spatial = spatializer.process(np.zeros(480, dtype=np.float32))
        if spatial.shape != (480, 2):
            raise RuntimeError("O HRTF retornou um bloco com formato inválido.")

        result.update(
            ok=True,
            input_devices=len(input_devices),
            output_devices=len(output_devices),
            pedalboard=True,
            rnnoise=True,
            hrtf=True,
        )
        return_code = 0
    except Exception as exc:
        result.update(error=f"{type(exc).__name__}: {exc}")
        return_code = 1
    finally:
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
