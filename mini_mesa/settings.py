from __future__ import annotations

from dataclasses import dataclass


_MIX_HEADROOM = 0.90
_MAX_WET_SHARE = 0.80


def _validate_percent(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} deve ser um número inteiro")
    if not 0 <= value <= 100:
        raise ValueError(f"{name} deve estar entre 0 e 100")


@dataclass(frozen=True, slots=True)
class ReverbSettings:
    """A single user-facing level mapped to the internal reverb parameters."""

    level_percent: int = 25
    enabled: bool = True

    def __post_init__(self) -> None:
        _validate_percent("Nível de reverb", self.level_percent)
        if not isinstance(self.enabled, bool):
            raise TypeError("Estado do reverb deve ser verdadeiro ou falso")

    @property
    def normalized_level(self) -> float:
        return self.level_percent / 100.0

    @property
    def wet_level(self) -> float:
        if not self.enabled:
            return 0.0
        return _MIX_HEADROOM * _MAX_WET_SHARE * self.normalized_level

    @property
    def dry_level(self) -> float:
        if not self.enabled:
            return _MIX_HEADROOM / 2.0
        # Pedalboard's FreeVerb dry control has an effective 2x gain.
        return (_MIX_HEADROOM - self.wet_level) / 2.0

    @property
    def room_size(self) -> float:
        return 0.25 + (0.60 * self.normalized_level)

    @property
    def damping(self) -> float:
        return 0.55 - (0.20 * self.normalized_level)


@dataclass(frozen=True, slots=True)
class SpatialSettings:
    """User-facing horizontal position for binaural HRTF processing."""

    enabled: bool = False
    angle_degrees: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("Estado do áudio espacial deve ser verdadeiro ou falso")
        if isinstance(self.angle_degrees, bool) or not isinstance(
            self.angle_degrees, int
        ):
            raise TypeError("Posição espacial deve ser um número inteiro")
        if not -180 <= self.angle_degrees <= 180:
            raise ValueError("Posição espacial deve estar entre -180 e 180 graus")


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    """Settings for real-time voice pitch modification and formant/frequency filtering."""

    enabled: bool = False
    preset: str = "custom"
    pitch_semitones: float = 4.0
    highpass_cutoff: float = 120.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("Estado do efeito de voz deve ser verdadeiro ou falso")
        if self.preset not in VALID_VOICE_PRESETS:
            raise ValueError(f"Preset de voz deve ser um de: {VALID_VOICE_PRESETS}")
        if isinstance(self.pitch_semitones, bool) or not isinstance(
            self.pitch_semitones, (int, float)
        ):
            raise TypeError("Ajuste de tom (pitch) deve ser um número")
        if not -12.0 <= float(self.pitch_semitones) <= 12.0:
            raise ValueError("Ajuste de tom deve estar entre -12.0 e 12.0 semitons")
        if isinstance(self.highpass_cutoff, bool) or not isinstance(
            self.highpass_cutoff, (int, float)
        ):
            raise TypeError("Frequência de corte do filtro deve ser um número")
        if not 20.0 <= float(self.highpass_cutoff) <= 500.0:
            raise ValueError("Frequência do filtro deve estar entre 20.0 e 500.0 Hz")


VALID_VOICE_PRESETS = (
    "female",
    "female_soft",
    "female_thin",
    "male",
    "custom",
    "monster",
    "helium",
    "double",
    "harmony_third",
    "harmony_fifth",
    "harmony_octave",
    "autotune",
    "vocoder",
)

VALID_CREATIVE_PRESETS = (
    "none",
    "telephone",
    "megaphone",
    "robot",
    "old_radio",
    "intercom",
    "space_helmet",
    "ghost",
    "underwater",
    "reverse",
    "glitch",
    "arcade",
    "walkie_police",
    "walkie_military",
    "walkie_toy",
    "tape",
    "vinyl",
    "vhs",
    "broken_speaker",
    "radio_interference",
    "stutter",
    "spectral_freeze",
    "granular",
    "octave_fuzz",
)
VALID_MODULATIONS = (
    "none",
    "flanger",
    "phaser",
    "tremolo",
    "chorus",
    "ring",
    "ping_pong",
    "doppler",
    "leslie",
    "stereo_widener",
    "haas",
)
VALID_AMBIENCES = (
    "none",
    "small_room",
    "auditorium",
    "cathedral",
    "cave",
    "bathroom",
    "mountain",
    "convolution_room",
    "convolution_hall",
)


@dataclass(frozen=True, slots=True)
class CreativeEffectSettings:
    """Settings for style presets (telephone, megaphone, robot) and stadium delay/echo."""

    preset: str = "none"
    modulation: str = "none"
    ambience: str = "none"
    delay_enabled: bool = False
    delay_level_percent: int = 30
    style_intensity_percent: int = 70
    modulation_intensity_percent: int = 60
    ambience_intensity_percent: int = 50
    roger_beep_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.preset, str) or self.preset not in VALID_CREATIVE_PRESETS:
            raise ValueError(f"Preset de efeito deve ser um de: {VALID_CREATIVE_PRESETS}")
        if self.modulation not in VALID_MODULATIONS:
            raise ValueError(f"Modulação deve ser uma de: {VALID_MODULATIONS}")
        if self.ambience not in VALID_AMBIENCES:
            raise ValueError(f"Ambiente deve ser um de: {VALID_AMBIENCES}")
        if not isinstance(self.delay_enabled, bool):
            raise TypeError("Estado do eco/delay deve ser verdadeiro ou falso")
        _validate_percent("Nível de eco", self.delay_level_percent)
        _validate_percent("Intensidade do estilo", self.style_intensity_percent)
        _validate_percent("Intensidade da modulação", self.modulation_intensity_percent)
        _validate_percent("Intensidade do ambiente", self.ambience_intensity_percent)
        if not isinstance(self.roger_beep_enabled, bool):
            raise TypeError("Estado do roger beep deve ser verdadeiro ou falso")

    @property
    def delay_seconds(self) -> float:
        return 0.15 + (0.35 * (self.delay_level_percent / 100.0))

    @property
    def delay_feedback(self) -> float:
        return 0.20 + (0.40 * (self.delay_level_percent / 100.0))

    @property
    def delay_mix(self) -> float:
        if not self.delay_enabled:
            return 0.0
        return 0.10 + (0.40 * (self.delay_level_percent / 100.0))


@dataclass(frozen=True, slots=True)
class ProAudioSettings:
    """Settings for broadcast dynamic compressor and 3-band equalizer."""

    compressor_enabled: bool = False
    eq_enabled: bool = False
    eq_low_db: float = 0.0
    eq_mid_db: float = 0.0
    eq_high_db: float = 0.0
    noise_gate_enabled: bool = False
    deesser_enabled: bool = False
    expander_enabled: bool = False
    auto_gain_enabled: bool = False
    plosive_filter_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.compressor_enabled, bool):
            raise TypeError("Estado do compressor deve ser verdadeiro ou falso")
        if not isinstance(self.eq_enabled, bool):
            raise TypeError("Estado do equalizador deve ser verdadeiro ou falso")
        for name, value in (
            ("noise gate", self.noise_gate_enabled),
            ("de-esser", self.deesser_enabled),
            ("expander", self.expander_enabled),
            ("ganho automático", self.auto_gain_enabled),
            ("filtro de plosivas", self.plosive_filter_enabled),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"Estado de {name} deve ser verdadeiro ou falso")
        for name, value in (
            ("Graves (Low)", self.eq_low_db),
            ("Médios (Mid)", self.eq_mid_db),
            ("Agudos (High)", self.eq_high_db),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"Ajuste de {name} deve ser um número")
            if not -12.0 <= float(value) <= 12.0:
                raise ValueError(f"Ajuste de {name} deve estar entre -12.0 e 12.0 dB")


@dataclass(frozen=True, slots=True)
class SoundboardSettings:
    """Settings for soundboard volume level."""

    volume_percent: int = 80
    ducking_enabled: bool = False
    ducking_percent: int = 60

    def __post_init__(self) -> None:
        _validate_percent("Volume do soundboard", self.volume_percent)
        _validate_percent("Ducking do soundboard", self.ducking_percent)
        if not isinstance(self.ducking_enabled, bool):
            raise TypeError("Estado do ducking deve ser verdadeiro ou falso")
