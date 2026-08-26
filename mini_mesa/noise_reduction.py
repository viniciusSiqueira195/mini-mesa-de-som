from __future__ import annotations

import ctypes
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import numpy as np


RNNOISE_SAMPLE_RATE = 48_000
RNNOISE_FRAME_SIZE = 480


class NoiseReductionDependencyError(RuntimeError):
    """Raised when the optional native RNNoise engine cannot be loaded."""


class StreamingNoiseReducer:
    """Adapt fixed RNNoise frames to arbitrary real-time callback block sizes."""

    def __init__(
        self,
        process_frame: Callable[[np.ndarray], np.ndarray],
        *,
        frame_size: int = RNNOISE_FRAME_SIZE,
    ) -> None:
        self._process_frame = process_frame
        self._frame_size = frame_size
        self._input = np.empty(0, dtype=np.float32)
        # One delayed frame keeps every callback full while block sizes differ.
        self._output = np.zeros(frame_size, dtype=np.float32)

    def process(self, samples: np.ndarray) -> np.ndarray:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError("A redução de ruído espera áudio mono.")

        self._input = np.concatenate((self._input, samples))
        processed_frames: list[np.ndarray] = []
        while self._input.size >= self._frame_size:
            frame = self._input[: self._frame_size]
            self._input = self._input[self._frame_size :]
            processed_frames.append(self._process_frame(frame))
        if processed_frames:
            self._output = np.concatenate((self._output, *processed_frames))

        requested = samples.size
        result = self._output[:requested].copy()
        self._output = self._output[requested:]
        if result.size < requested:
            result = np.pad(result, (0, requested - result.size))
        return result


class RNNoiseReducer:
    """Thin ctypes wrapper around RNNoise without importing its file utilities."""

    def __init__(self) -> None:
        library_path = self._find_library()
        try:
            self._library = ctypes.CDLL(str(library_path))
        except OSError as exc:
            raise NoiseReductionDependencyError(
                "A biblioteca nativa de redução de ruído não pôde ser carregada."
            ) from exc

        self._library.rnnoise_create.argtypes = [ctypes.c_void_p]
        self._library.rnnoise_create.restype = ctypes.c_void_p
        self._library.rnnoise_destroy.argtypes = [ctypes.c_void_p]
        self._library.rnnoise_process_frame.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
        ]
        self._library.rnnoise_process_frame.restype = ctypes.c_float
        self._library.rnnoise_get_frame_size.restype = ctypes.c_int

        frame_size = int(self._library.rnnoise_get_frame_size())
        if frame_size != RNNOISE_FRAME_SIZE:
            raise NoiseReductionDependencyError(
                f"O RNNoise informou um quadro incompatível de {frame_size} amostras."
            )
        self._state = self._library.rnnoise_create(None)
        if not self._state:
            raise NoiseReductionDependencyError(
                "O RNNoise não conseguiu criar o estado de processamento."
            )
        self._stream = StreamingNoiseReducer(self._process_frame)

    @staticmethod
    def _find_library() -> Path:
        try:
            package = distribution("pyrnnoise")
        except PackageNotFoundError as exc:
            raise NoiseReductionDependencyError(
                "A redução de ruído opcional não está instalada. "
                "Execute: python -m pip install -e ."
            ) from exc
        library_path = Path(package.locate_file("pyrnnoise/rnnoise.dll"))
        if not library_path.is_file():
            raise NoiseReductionDependencyError(
                f"A biblioteca RNNoise não foi encontrada em '{library_path}'."
            )
        return library_path

    def process(self, samples: np.ndarray) -> np.ndarray:
        return self._stream.process(samples)

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        native_frame = np.ascontiguousarray(
            np.clip(frame, -1.0, 1.0) * 32_767.0,
            dtype=np.float32,
        )
        pointer = native_frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._library.rnnoise_process_frame(self._state, pointer, pointer)
        return np.clip(native_frame / 32_767.0, -1.0, 1.0)

    def close(self) -> None:
        state = self._state
        if state:
            self._state = None
            self._library.rnnoise_destroy(state)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
