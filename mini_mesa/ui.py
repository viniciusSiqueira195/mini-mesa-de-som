from __future__ import annotations

import re
import threading
from dataclasses import replace
from pathlib import Path

import wx
import wx.adv
import wx.html2
from markdown import markdown as render_markdown

from . import __version__
from .global_hotkeys import GlobalHotkeyManager, modifier_label
from .release_notes import load_release_notes
from .audio_engine import AudioDependencyError, AudioEngine, match_device_label
from .preferences import AppPreferences, PersonalSound, PreferencesStore
from .process_audio import list_candidate_processes
from .soundboard import SoundEffectError, validate_custom_audio
from .user_features import ProfileStore, diagnostic_text, export_backup, import_backup
from .settings import (
    CreativeEffectSettings,
    ProAudioSettings,
    RecordingSettings,
    ReverbSettings,
    SoundboardSettings,
    SpatialSettings,
    VoiceSettings,
)
from .recorder import default_recordings_directory
from .updater import (
    UpdateCancelled,
    UpdateError,
    UpdateInfo,
    can_self_update,
    check_for_update,
    download_installer,
    launch_installer,
)

_PROJECT_URL = "https://github.com/viniciusSiqueira195/mini-mesa-de-som"
_PAULO_URL = "https://github.com/paulosantesso1"
_HELP_FALLBACK = (
    "Mini Mesa de Som\n\n"
    "A documentação completa não foi encontrada. Pressione F1 novamente após "
    "reinstalar o programa ou consulte o projeto em:\n"
    f"{_PROJECT_URL}"
)


def _markdown_to_accessible_text(markdown: str) -> str:
    """Remove visual Markdown markers while retaining labels and destinations."""

    text = re.sub(r"\[([^\]]+)]\(([^)]+)\)", r"\1 — \2", markdown)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*>\s?", "", line)
        line = re.sub(r"^\s*-\s+", "• ", line)
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def _load_project_help(readme_path: Path | None = None) -> str:
    """Load the README used by source runs and bundled Windows builds."""

    markdown = _load_project_markdown(readme_path)
    if markdown is None:
        return _HELP_FALLBACK
    return _markdown_to_accessible_text(markdown) or _HELP_FALLBACK


def _load_project_markdown(readme_path: Path | None = None) -> str | None:
    """Return the canonical README without maintaining a second help document."""

    path = readme_path or Path(__file__).resolve().parent.parent / "README.md"
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _markdown_to_help_html(markdown: str) -> str:
    """Render trusted project Markdown with real headings for browse mode."""

    body = render_markdown(
        markdown,
        extensions=("fenced_code", "sane_lists", "toc"),
        output_format="html5",
    )
    return (
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<style>"
        ":root{color-scheme:light dark}"
        "body{font-family:Segoe UI,sans-serif;line-height:1.55;max-width:70rem;"
        "margin:1.5rem auto;padding:0 1rem}"
        "a{color:#0674c4}code,pre{font-family:Consolas,monospace}"
        "pre{overflow:auto;padding:.75rem;border:1px solid currentColor}"
        "</style></head><body>"
        f"{body}</body></html>"
    )

_VOICE_PRESETS = (
    ("female", "Voz feminina (+4 semitons)", 4),
    ("female_soft", "Voz feminina suave (+3)", 3),
    ("female_thin", "Voz feminina fina (+6)", 6),
    ("male", "Voz masculina grave (-4)", -4),
    ("monster", "Monstro / Demônio", -7),
    ("helium", "Esquilo / Hélio", 9),
    ("double", "Voz dupla", 0),
    ("harmony_third", "Harmonizador: terça", 4),
    ("harmony_fifth", "Harmonizador: quinta", 7),
    ("harmony_octave", "Harmonizador: oitava", 12),
    ("custom", "Personalizado", None),
)
_STYLE_PRESETS = (
    ("none", "Nenhum"),
    ("telephone", "Telefone / Walkie-Talkie"),
    ("megaphone", "Rádio policial / Megafone"),
    ("robot", "Robô / Alien"),
    ("old_radio", "Rádio antigo AM"),
    ("intercom", "Interfone / Alto-falante"),
    ("space_helmet", "Capacete espacial"),
    ("ghost", "Voz fantasma"),
    ("underwater", "Voz subaquática"),
    ("reverse", "Voz reversa parcial"),
    ("glitch", "Glitch digital"),
    ("arcade", "8-bit / Arcade"),
    ("walkie_police", "Walkie policial"),
    ("walkie_military", "Walkie militar"),
    ("walkie_toy", "Walkie barato / brinquedo"),
    ("tape", "Fita cassete"),
    ("vinyl", "Disco de vinil"),
    ("vhs", "Áudio de VHS"),
    ("broken_speaker", "Alto-falante quebrado"),
    ("radio_interference", "Rádio com interferência"),
    ("stutter", "Stutter rítmico"),
    ("spectral_freeze", "Congelamento espectral"),
    ("granular", "Efeito granular"),
    ("octave_fuzz", "Octave fuzz"),
)
_MODULATIONS = (
    ("none", "Nenhuma"),
    ("flanger", "Flanger"),
    ("phaser", "Phaser"),
    ("tremolo", "Tremolo"),
    ("chorus", "Chorus"),
    ("ring", "Ring modulator"),
    ("ping_pong", "Delay ping-pong estéreo"),
    ("doppler", "Doppler"),
    ("leslie", "Caixa Leslie rotativa"),
    ("stereo_widener", "Stereo widener"),
    ("haas", "Efeito Haas"),
)
_AMBIENCES = (
    ("none", "Nenhum"),
    ("small_room", "Sala pequena"),
    ("auditorium", "Auditório"),
    ("cathedral", "Catedral"),
    ("cave", "Caverna"),
    ("bathroom", "Banheiro"),
    ("mountain", "Eco de montanha"),
    ("convolution_room", "Convolução FIR: sala"),
    ("convolution_hall", "Convolução FIR: salão"),
)


class _NamedControlAccessible(wx.Accessible):
    """Expose a stable MSAA name for a native Windows control."""

    def __init__(self, control: wx.Window, name: str) -> None:
        super().__init__(control)
        self._name = name

    def GetName(self, _child_id: int) -> tuple[wx.AccStatus, str]:
        return wx.ACC_OK, self._name

    def update_name(self, name: str) -> None:
        self._name = name


class _NamedSliderAccessible(_NamedControlAccessible):
    """Expose a stable MSAA name for a native Windows slider and its thumb."""


def _set_slider_accessible_name(slider: wx.Slider, name: str) -> wx.Accessible:
    """Set both wx/native labels and the name returned directly to readers."""

    slider.SetName(name)
    slider.SetLabel(name)
    accessible = _NamedSliderAccessible(slider, name)
    slider.SetAccessible(accessible)
    return accessible


def _set_control_accessible_name(
    control: wx.Window, name: str
) -> _NamedControlAccessible:
    """Attach a real MSAA name to controls whose native wrapper has none."""

    control.SetName(name)
    accessible = _NamedControlAccessible(control, name)
    control.SetAccessible(accessible)
    return accessible


def _set_spin_accessible_name(spin: wx.SpinCtrl, name: str) -> None:
    """Give a native spin control both its wx label and accessible name."""

    spin.SetName(name)
    spin.SetLabel(name)


def _set_choice_accessible_name(choice: wx.Choice, name: str) -> None:
    """Set a Choice label before selection so wx keeps its selected item."""

    choice.SetLabel(name)
    choice.SetName(name)


def _set_button_accessible_name(button: wx.Button, name: str | None = None) -> None:
    """Keep a button's native accessible name meaningful instead of ``button``."""

    button.SetName(name or button.GetLabel().replace("&", ""))


def _set_search_accessible_name(
    search: wx.SearchCtrl, name: str
) -> tuple[_NamedControlAccessible, ...]:
    """Name the composite search control and the native children receiving focus."""

    search.SetName(name)
    search.SetLabel(name)
    accessibilities = [_set_control_accessible_name(search, name)]
    auxiliary_children = []
    for child in search.GetChildren():
        if isinstance(child, wx.TextCtrl):
            child.SetName(name)
            accessibilities.append(_set_control_accessible_name(child, name))
        else:
            auxiliary_children.append(child)
    if auxiliary_children:
        accessibilities.append(
            _set_control_accessible_name(auxiliary_children[0], "Buscar efeito")
        )
    if len(auxiliary_children) > 1:
        # SearchCtrl creates an unlabeled clear button when it is enabled.
        accessibilities.append(
            _set_control_accessible_name(auxiliary_children[-1], "Limpar busca")
        )
    return tuple(accessibilities)


class SystemTrayIcon(wx.adv.TaskBarIcon):
    """Keep the mixer reachable after Windows minimizes the main window."""

    def __init__(self, frame: MainFrame) -> None:
        super().__init__()
        self._frame = frame
        self._restore_id = wx.NewIdRef()
        self._exit_id = wx.NewIdRef()
        icon = wx.ArtProvider.GetIcon(wx.ART_EXECUTABLE_FILE, wx.ART_OTHER, (16, 16))
        self._available = bool(self.SetIcon(icon, "Mini Mesa de Som"))
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, self._on_restore)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self._on_restore)
        self.Bind(wx.EVT_MENU, self._on_restore, id=self._restore_id)
        self.Bind(wx.EVT_MENU, self._on_exit, id=self._exit_id)

    def CreatePopupMenu(self) -> wx.Menu:
        menu = wx.Menu()
        menu.Append(self._restore_id, "&Abrir Mini Mesa de Som")
        menu.AppendSeparator()
        menu.Append(self._exit_id, "En&cerrar programa")
        return menu

    @property
    def is_available(self) -> bool:
        return self._available and self.IsIconInstalled()

    def notify_minimized(self) -> None:
        if not self.is_available:
            return
        try:
            self.ShowBalloon(
                "Mini Mesa minimizada",
                "A Mini Mesa está minimizada. Você pode restaurá-la pela bandeja do sistema.",
                5000,
                wx.ICON_INFORMATION,
            )
        except (AttributeError, wx.wxAssertionError):
            pass

    def _on_restore(self, _event: wx.Event) -> None:
        self._frame.restore_from_tray()

    def _on_exit(self, _event: wx.Event) -> None:
        self._frame.exit_from_tray()


class EffectToggleButton(wx.ToggleButton):
    """Native toggle with an explicit action and an accessible on/off state."""

    def __init__(self, parent: wx.Window, *, label: str) -> None:
        self._effect_label = label.removeprefix("Ativar ")
        super().__init__(parent, label=label)
        self._refresh_label()

    def _refresh_label(self) -> None:
        enabled = self.GetValue()
        action = "Desativar" if enabled else "Ativar"
        self.SetLabel(f"{action} {self._effect_label}")
        self.SetName(self.GetLabel().replace("&", ""))

    def SetValue(self, value: bool) -> None:
        super().SetValue(value)
        self._refresh_label()

    def BindToggle(self, handler) -> None:
        def on_toggle(event: wx.CommandEvent) -> None:
            self._refresh_label()
            handler(event)

        self.Bind(wx.EVT_TOGGLEBUTTON, on_toggle)

    def Activate(self) -> None:
        if self.IsEnabled():
            self.SetValue(not self.GetValue())
            event = wx.CommandEvent(wx.EVT_TOGGLEBUTTON.typeId, self.GetId())
            event.SetEventObject(self)
            event.SetInt(int(self.GetValue()))
            self.GetEventHandler().ProcessEvent(event)


class SoundboardPanel(wx.ScrolledWindow):
    """Keyboard-first effect picker embedded in the mixer notebook."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.SetScrollRate(0, 12)
        self.SetMinSize((1, 1))
        self._frame = frame
        self._all_effects = list(frame.preferences.personal_sounds)
        self._page = frame.preferences.selected_sound_page
        self._page_names = list(frame.preferences.sound_page_names)
        self._effects = [effect for effect in self._all_effects if effect.page == self._page]

        root = wx.BoxSizer(wx.VERTICAL)
        instructions = wx.StaticText(
            self,
            label=(
                "Escolha a página e adicione seus sons. "
                "Na lista, a tecla Aplicações ou Shift+F10 abre as ações do efeito."
            ),
        )
        instructions.Wrap(430)
        root.Add(instructions, 0, wx.ALL | wx.EXPAND, 12)

        root.Add(wx.StaticText(self, label="Página de efeitos:"), 0, wx.LEFT | wx.RIGHT, 12)
        self.page_choice = wx.Choice(self, choices=self._page_names)
        _set_choice_accessible_name(self.page_choice, "Página de efeitos")
        self.page_choice.SetSelection(self._page)
        self.page_choice.Bind(wx.EVT_CHOICE, self._on_page_changed)
        root.Add(self.page_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        rename_page = wx.Button(self, label="Renomear página...")
        _set_button_accessible_name(rename_page, "Renomear página")
        rename_page.Bind(wx.EVT_BUTTON, self._on_rename_page)
        root.Add(rename_page, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        custom_button = wx.Button(self, label="&Adicionar efeito de áudio... (F6)")
        self.add_button = custom_button
        custom_button.Bind(wx.EVT_BUTTON, frame._on_browse_soundboard_file)
        root.Add(custom_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        root.Add(wx.StaticText(self, label="&Buscar efeito nesta página:"), 0, wx.LEFT | wx.RIGHT, 12)
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.ShowCancelButton(True)
        self._search_accessibilities = _set_search_accessible_name(
            self.search, "Buscar efeito na página atual"
        )
        self.search.Bind(wx.EVT_TEXT, self._on_search)
        root.Add(self.search, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.effect_list = wx.ListBox(
            self,
            choices=[
                self._effect_label(index, effect)
                for index, effect in enumerate(self._effects)
            ],
        )
        self.effect_list.SetLabel("Lista de efeitos sonoros")
        self.effect_list.SetName("Lista de efeitos sonoros")
        self._effect_list_accessible = _set_control_accessible_name(
            self.effect_list, "Lista de efeitos sonoros"
        )
        if self._effects:
            self.effect_list.SetSelection(0)
        self.effect_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_play)
        self.effect_list.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.effect_list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        root.Add(self.effect_list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.actions_button = wx.Button(self, label="Ações do efeito...")
        _set_button_accessible_name(self.actions_button, "Ações do efeito")
        self.actions_button.Bind(wx.EVT_BUTTON, self._show_effect_menu)
        root.Add(self.actions_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        play_button = wx.Button(self, label="&Reproduzir")
        self.play_button = play_button
        _set_button_accessible_name(play_button, "Reproduzir efeito selecionado")
        play_button.Bind(wx.EVT_BUTTON, self._on_play)
        actions.Add(play_button, 1, wx.RIGHT | wx.EXPAND, 5)
        stop_button = wx.Button(self, label="&Parar todos")
        _set_button_accessible_name(stop_button, "Parar todos os efeitos")
        stop_button.Bind(wx.EVT_BUTTON, self._on_stop)
        actions.Add(stop_button, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 5)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        settings = frame.soundboard_settings
        volume_label = wx.StaticText(self, label="&Volume dos efeitos, de 0 a 100:")
        root.Add(volume_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self.volume = wx.Slider(
            self,
            value=settings.volume_percent,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self._volume_accessible = _set_slider_accessible_name(
            self.volume, "Volume dos efeitos sonoros"
        )
        self.volume.Bind(wx.EVT_SLIDER, self._on_settings_changed)
        root.Add(self.volume, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.ducking = EffectToggleButton(
            self, label="Ativar redução dos efeitos enquanto eu &falo"
        )
        self.ducking.SetValue(settings.ducking_enabled)
        self.ducking.BindToggle(self._on_settings_changed)
        root.Add(self.ducking, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        ducking_label = wx.StaticText(self, label="&Intensidade do ducking:")
        root.Add(ducking_label, 0, wx.LEFT | wx.RIGHT, 12)
        self.ducking_amount = wx.Slider(
            self,
            value=settings.ducking_percent,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self._ducking_amount_accessible = _set_slider_accessible_name(
            self.ducking_amount, "Intensidade do ducking dos efeitos"
        )
        self.ducking_amount.Enable(settings.ducking_enabled)
        self.ducking_amount.Bind(wx.EVT_SLIDER, self._on_settings_changed)
        root.Add(
            self.ducking_amount,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
            12,
        )

        self.SetSizer(root)
        self.FitInside()
        self._refresh_effects()

    @staticmethod
    def _effect_label(index: int, effect: PersonalSound) -> str:
        shortcut = f"; Ctrl+{(index + 1) % 10}" if index < 10 else ""
        return f"{effect.name}{shortcut}"

    def _refresh_effects(self, selection: int = 0) -> None:
        query = self.search.GetValue().strip().casefold()
        self._visible_effects = [
            (index, effect) for index, effect in enumerate(self._effects)
            if not query or query in effect.name.casefold()
        ]
        self.effect_list.Set([
            self._effect_label(index, effect) for index, effect in self._visible_effects
        ])
        if self._visible_effects:
            visible_selection = next(
                (index for index, (real, _) in enumerate(self._visible_effects) if real == selection),
                0,
            )
            self.effect_list.SetSelection(visible_selection)
        for button in (self.actions_button, self.play_button):
            button.Enable(bool(self._visible_effects))
        page_name = self._page_names[self._page]
        self.add_button.SetLabel(f"&Adicionar efeitos, {page_name}... (F6)")
        self.add_button.SetName(f"Adicionar efeitos, {page_name}")
        self.add_button.Enable(len(self._effects) < 10)
        list_name = (
            f"{page_name}. Lista de efeitos sonoros"
            + ("" if self._visible_effects else (
                " sem resultados." if query else " vazia. Pressione F6 para adicionar."
            ))
        )
        self.effect_list.SetName(list_name)
        self._effect_list_accessible.update_name(list_name)

    def _commit_effects(self, effects: list[PersonalSound], selection: int) -> bool:
        all_effects = [effect for effect in self._all_effects if effect.page != self._page]
        all_effects.extend(effects)
        preferences = replace(
            self._frame._current_preferences(),
            personal_sounds=tuple(all_effects),
            sound_page_names=tuple(self._page_names),
        )
        try:
            self._frame.preferences_store.save(preferences)
        except OSError as exc:
            self._frame._show_error(f"Não foi possível salvar os efeitos.\n\n{exc}")
            return False
        self._frame.preferences = preferences
        self._all_effects = all_effects
        self._effects = effects
        self._refresh_effects(selection)
        (self.effect_list if effects else self.add_button).SetFocus()
        return True

    def _on_page_changed(self, _event: wx.Event) -> None:
        self.select_page(self.page_choice.GetSelection(), focus=False)

    def _on_search(self, _event: wx.Event) -> None:
        self._refresh_effects()

    def _selected_index(self) -> int:
        selection = self.effect_list.GetSelection()
        if selection == wx.NOT_FOUND or not 0 <= selection < len(self._visible_effects):
            return wx.NOT_FOUND
        return self._visible_effects[selection][0]

    def _on_rename_page(self, _event: wx.Event) -> None:
        with wx.TextEntryDialog(
            self, "Nome da página:", "Renomear página", self._page_names[self._page]
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.GetValue().strip()
        if not name:
            self._frame._show_error("Digite um nome para a página.")
            return
        previous = self._page_names[self._page]
        self._page_names[self._page] = name
        if not self._commit_effects(self._effects.copy(), self._selected_index()):
            self._page_names[self._page] = previous
            return
        self.page_choice.Set(self._page_names)
        self.page_choice.SetSelection(self._page)
        self._frame._update_page_menu_labels()
        self._frame.SetStatusText(f"Página renomeada para {name}.")

    def select_page(self, page: int, *, focus: bool = True) -> None:
        if not 0 <= page < 10:
            return
        preferences = replace(self._frame._current_preferences(), selected_sound_page=page)
        try:
            self._frame.preferences_store.save(preferences)
        except OSError as exc:
            self.page_choice.SetSelection(self._page)
            self._frame._show_error(f"Não foi possível salvar a página escolhida.\n\n{exc}")
            return
        self._frame.preferences = preferences
        self._page = page
        self.page_choice.SetSelection(page)
        self.search.ChangeValue("")
        self._effects = [effect for effect in self._all_effects if effect.page == page]
        self._refresh_effects()
        if focus:
            self._frame._focus_control(self.effect_list if self._effects else self.add_button)
        self._frame.SetStatusText(
            f"{self._page_names[page]}, página {page + 1} de 10; {len(self._effects)} efeitos."
        )
        self._frame._play_feedback("page")

    def _choose_files(self, *, multiple: bool = False) -> list[str]:
        style = wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        if multiple:
            style |= wx.FD_MULTIPLE
        with wx.FileDialog(
            self, "Escolha um arquivo para o painel de efeitos",
            wildcard="Arquivos de áudio (*.wav;*.mp3;*.flac;*.ogg)|*.wav;*.mp3;*.flac;*.ogg",
            style=style,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return []
            selected = dialog.GetPaths() if multiple else [dialog.GetPath()]

        paths: list[str] = []
        seen: set[str] = set()
        for selected_path in selected:
            path = Path(selected_path).resolve()
            key = str(path).casefold()
            if key in seen:
                continue
            seen.add(key)
            try:
                validate_custom_audio(path)
            except (OSError, SoundEffectError) as exc:
                self._frame._show_error(str(exc))
                return []
            paths.append(str(path))
        return paths

    def _choose_file(self) -> str | None:
        paths = self._choose_files()
        return paths[0] if paths else None

    def _on_add(self, _event: wx.Event) -> None:
        if len(self._effects) >= 10:
            self._frame._show_error("Esta página já tem dez efeitos. Escolha outra página ou remova um efeito.")
            return
        paths = self._choose_files(multiple=True)
        available = 10 - len(self._effects)
        if len(paths) > available:
            slot_word = "vaga" if available == 1 else "vagas"
            self._frame._show_error(
                f"Esta página tem espaço para apenas {available} {slot_word}, "
                f"mas você selecionou {len(paths)} arquivos."
            )
            return
        if not paths:
            return

        approved_paths: list[str] = []
        for path in paths:
            preview = SoundPreviewDialog(self._frame, path, self._page)
            try:
                if preview.ShowModal() != wx.ID_OK:
                    return
            finally:
                if not self._frame.engine.is_running:
                    try:
                        self._frame.engine.stop_preview()
                    except Exception:
                        pass
                preview.Destroy()
            approved_paths.append(path)

        effects = [
            *self._effects,
            *(PersonalSound(Path(path).stem, path, self._page) for path in approved_paths),
        ]
        if self._commit_effects(effects, len(effects) - 1):
            if len(approved_paths) == 1:
                message = f"Efeito adicionado: {effects[-1].name}."
            else:
                message = f"{len(approved_paths)} efeitos adicionados."
            self._frame.SetStatusText(message)

    def _on_rename(self, _event: wx.Event) -> None:
        index = self._selected_index()
        if index == wx.NOT_FOUND:
            return
        with wx.TextEntryDialog(self, "Nome do efeito:", "Renomear efeito", self._effects[index].name) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.GetValue().strip()
        if not name:
            self._frame._show_error("Digite um nome para o efeito.")
            return
        effects = self._effects.copy()
        effects[index] = replace(effects[index], name=name)
        if self._commit_effects(effects, index):
            self._frame.SetStatusText(f"Efeito renomeado: {name}.")

    def _on_replace(self, _event: wx.Event) -> None:
        index = self._selected_index()
        if index == wx.NOT_FOUND:
            return
        path = self._choose_file()
        if path is not None:
            effects = self._effects.copy()
            effects[index] = replace(effects[index], path=path)
            if self._commit_effects(effects, index):
                self._frame.SetStatusText(f"Arquivo substituído: {effects[index].name}.")

    def _on_remove(self, _event: wx.Event) -> None:
        index = self._selected_index()
        if index == wx.NOT_FOUND:
            return
        sound = self._effects[index]
        answer = wx.MessageBox(
            f"Excluir '{sound.name}' do painel?\n\nO arquivo original será preservado.",
            "Excluir efeito",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES:
            return
        effects = self._effects.copy()
        removed = effects.pop(index)
        if self._commit_effects(effects, index):
            self._frame.SetStatusText(f"Efeito removido do painel: {removed.name}. Arquivo original preservado.")

    def play_index(self, index: int) -> None:
        if not 0 <= index < len(self._effects):
            self._frame.SetStatusText("Nenhum efeito configurado nessa posição. Use F6 para adicionar.")
            return
        self._frame.play_personal_sound(self._effects[index])

    def _create_effect_menu(self) -> wx.Menu:
        menu = wx.Menu()
        for label, handler in (
            ("&Tocar", self._on_play),
            ("&Renomear...", self._on_rename),
            ("&Substituir arquivo...", self._on_replace),
            ("Mover para &cima", lambda _event: self._move_selected(-1)),
            ("Mover para &baixo", lambda _event: self._move_selected(1)),
            ("Mover para outra &página...", self._on_move_to_page),
            ("&Excluir do painel", self._on_remove),
            ("&Parar todos os efeitos", self._on_stop),
        ):
            item = menu.Append(wx.ID_ANY, label)
            menu.Bind(wx.EVT_MENU, handler, id=item.GetId())
        return menu

    def _move_selected(self, step: int) -> None:
        index = self._selected_index()
        target = index + step
        if index == wx.NOT_FOUND or not 0 <= target < len(self._effects):
            self._frame.SetStatusText("O efeito já está no limite desta página.")
            return
        effects = self._effects.copy()
        effects[index], effects[target] = effects[target], effects[index]
        if self._commit_effects(effects, target):
            self._frame.SetStatusText(
                f"{effects[target].name} movido para a posição {target + 1}; "
                f"atalho Ctrl+{(target + 1) % 10}."
            )

    def _on_move_to_page(self, _event: wx.Event) -> None:
        index = self._selected_index()
        if index == wx.NOT_FOUND:
            return
        choices = [
            f"{name}; {sum(sound.page == page for sound in self._all_effects)} de 10 efeitos"
            for page, name in enumerate(self._page_names)
            if page != self._page
        ]
        target_pages = [page for page in range(10) if page != self._page]
        with wx.SingleChoiceDialog(
            self, "Escolha a página de destino:", "Mover efeito", choices
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            target_page = target_pages[dialog.GetSelection()]
        if sum(sound.page == target_page for sound in self._all_effects) >= 10:
            self._frame._show_error("A página de destino já tem dez efeitos.")
            return
        moved = replace(self._effects[index], page=target_page)
        effects = self._effects.copy()
        effects.pop(index)
        all_effects = [sound for sound in self._all_effects if sound is not self._effects[index]]
        all_effects.append(moved)
        previous_all = self._all_effects
        self._all_effects = all_effects
        if not self._commit_effects(effects, index):
            self._all_effects = previous_all
            return
        self._frame.SetStatusText(
            f"{moved.name} movido para {self._page_names[target_page]}."
        )

    def _show_effect_menu(self, _event: wx.Event = None, *, position=None) -> None:
        if self.effect_list.GetSelection() == wx.NOT_FOUND:
            return
        menu = self._create_effect_menu()
        try:
            self.effect_list.PopupMenu(menu, position if position is not None else wx.Point(0, 0))
        finally:
            menu.Destroy()
        (self.effect_list if self._effects else self.add_button).SetFocus()

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            self._show_effect_menu()
            return
        position = self.effect_list.ScreenToClient(position)
        selection = self.effect_list.HitTest(position)
        if selection == wx.NOT_FOUND:
            return
        self.effect_list.SetSelection(selection)
        self._show_effect_menu(position=position)

    def _on_play(self, _event: wx.Event) -> None:
        selection = self._selected_index()
        if selection != wx.NOT_FOUND:
            self.play_index(selection)

    def _on_stop(self, _event: wx.Event) -> None:
        self._frame.stop_sound_effects()

    def _on_settings_changed(self, event: wx.Event) -> None:
        self.ducking_amount.Enable(self.ducking.GetValue())
        self._frame.update_soundboard_settings(
            SoundboardSettings(
                volume_percent=self.volume.GetValue(),
                ducking_enabled=self.ducking.GetValue(),
                ducking_percent=self.ducking_amount.GetValue(),
            )
        )
        event.Skip()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_WINDOWS_MENU or (
            event.GetKeyCode() == wx.WXK_F10 and event.ShiftDown()
        ):
            self._show_effect_menu()
            return
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._on_play(event)
            return
        if event.GetKeyCode() == wx.WXK_SPACE:
            self._on_stop(event)
            return
        event.Skip()



class RecordingPanel(wx.ScrolledWindow):
    """Recording tab for audio capture settings and live recording."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.SetScrollRate(0, 12)
        self.SetMinSize((1, 1))
        self._frame = frame

        root = wx.BoxSizer(wx.VERTICAL)

        instructions = wx.StaticText(
            self,
            label=(
                "Escolha o formato de áudio, qualidade, modo de captura e pasta de destino para gravar. "
                "Pressione F8 ou use o botão para iniciar ou parar a gravação."
            ),
        )
        instructions.Wrap(540)
        root.Add(instructions, 0, wx.ALL | wx.EXPAND, 12)

        box_settings = wx.StaticBoxSizer(wx.VERTICAL, self, "Configurações de gravação")
        box_panel = box_settings.GetStaticBox()

        box_settings.Add(wx.StaticText(box_panel, label="&Formato de áudio:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.format_choice = wx.Choice(box_panel, choices=[
            "MP3 (*.mp3)",
            "WAV (*.wav)",
            "OGG Vorbis (*.ogg)",
        ])
        _set_choice_accessible_name(self.format_choice, "Formato do arquivo de áudio")
        fmt_index = {"mp3": 0, "wav": 1, "ogg": 2}.get(frame.preferences.recording_format, 0)
        self.format_choice.SetSelection(fmt_index)
        self.format_choice.Bind(wx.EVT_CHOICE, self._on_settings_changed)
        box_settings.Add(self.format_choice, 0, wx.ALL | wx.EXPAND, 8)

        box_settings.Add(wx.StaticText(box_panel, label="&Qualidade / Taxa de bits (para MP3 e OGG):"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.bitrate_choice = wx.Choice(box_panel, choices=[
            "128 kbps",
            "160 kbps",
            "192 kbps (Recomendado)",
            "256 kbps",
            "320 kbps (Máxima)",
        ])
        _set_choice_accessible_name(self.bitrate_choice, "Qualidade e taxa de bits")
        bitrate_index = {128: 0, 160: 1, 192: 2, 256: 3, 320: 4}.get(frame.preferences.recording_bitrate_kbps, 2)
        self.bitrate_choice.SetSelection(bitrate_index)
        self.bitrate_choice.Bind(wx.EVT_CHOICE, self._on_settings_changed)
        box_settings.Add(self.bitrate_choice, 0, wx.ALL | wx.EXPAND, 8)

        box_settings.Add(wx.StaticText(box_panel, label="&Modo de captura de áudio:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.mode_choice = wx.Choice(box_panel, choices=[
            "Ambos (Voz + Programas transmitidos)",
            "Apenas a sua voz (com todos os efeitos)",
            "Apenas os programas transmitidos",
        ])
        _set_choice_accessible_name(self.mode_choice, "Modo de captura de áudio")
        mode_index = {"both": 0, "voice": 1, "processes": 2}.get(frame.preferences.recording_mode, 0)
        self.mode_choice.SetSelection(mode_index)
        self.mode_choice.Bind(wx.EVT_CHOICE, self._on_settings_changed)
        box_settings.Add(self.mode_choice, 0, wx.ALL | wx.EXPAND, 8)

        box_settings.Add(wx.StaticText(box_panel, label="&Nome do arquivo (opcional; deixe em branco para automático com data e hora):"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.filename_ctrl = wx.TextCtrl(box_panel, value=frame.preferences.recording_custom_filename)
        _set_control_accessible_name(self.filename_ctrl, "Nome do arquivo para gravação")
        self.filename_ctrl.Bind(wx.EVT_TEXT, self._on_settings_changed)
        box_settings.Add(self.filename_ctrl, 0, wx.ALL | wx.EXPAND, 8)

        box_settings.Add(wx.StaticText(box_panel, label="&Pasta de destino das gravações:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        folder_sizer = wx.BoxSizer(wx.HORIZONTAL)
        initial_folder = frame.preferences.recording_folder or str(default_recordings_directory())
        self.folder_ctrl = wx.TextCtrl(box_panel, value=initial_folder)
        _set_control_accessible_name(self.folder_ctrl, "Pasta de destino das gravações")
        self.folder_ctrl.Bind(wx.EVT_TEXT, self._on_settings_changed)
        folder_sizer.Add(self.folder_ctrl, 1, wx.RIGHT | wx.EXPAND, 6)

        self.browse_folder_button = wx.Button(box_panel, label="&Procurar pasta...")
        _set_button_accessible_name(self.browse_folder_button, "Procurar pasta de gravação")
        self.browse_folder_button.Bind(wx.EVT_BUTTON, self._on_browse_folder)
        folder_sizer.Add(self.browse_folder_button, 0)
        box_settings.Add(folder_sizer, 0, wx.ALL | wx.EXPAND, 8)

        root.Add(box_settings, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        box_action = wx.StaticBoxSizer(wx.VERTICAL, self, "Gravação ao vivo")
        action_panel = box_action.GetStaticBox()

        self.record_button = wx.Button(action_panel, label="&Iniciar gravação (F8)")
        _set_button_accessible_name(self.record_button, "Iniciar gravação de áudio")
        self.record_button.Bind(wx.EVT_BUTTON, self._on_toggle_record)
        box_action.Add(self.record_button, 0, wx.ALL | wx.EXPAND, 8)

        self.record_status = wx.TextCtrl(action_panel, value="Gravação parada.", style=wx.TE_READONLY)
        _set_control_accessible_name(self.record_status, "Estado da gravação")
        box_action.Add(self.record_status, 0, wx.ALL | wx.EXPAND, 8)

        root.Add(box_action, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self.timer)

        self.SetSizer(root)
        self.FitInside()
        self._update_bitrate_enabled_state()

    def _update_bitrate_enabled_state(self) -> None:
        fmt = ("mp3", "wav", "ogg")[self.format_choice.GetSelection()]
        self.bitrate_choice.Enable(fmt != "wav")

    def _current_settings(self) -> RecordingSettings:
        fmt = ("mp3", "wav", "ogg")[self.format_choice.GetSelection()]
        bitrate = (128, 160, 192, 256, 320)[self.bitrate_choice.GetSelection()]
        mode = ("both", "voice", "processes")[self.mode_choice.GetSelection()]
        return RecordingSettings(
            format=fmt,
            bitrate_kbps=bitrate,
            mode=mode,
            custom_filename=self.filename_ctrl.GetValue().strip(),
            folder=self.folder_ctrl.GetValue().strip(),
        )

    def _on_settings_changed(self, _event: wx.Event = None) -> None:
        self._update_bitrate_enabled_state()
        settings = self._current_settings()
        preferences = replace(
            self._frame._current_preferences(),
            recording_format=settings.format,
            recording_bitrate_kbps=settings.bitrate_kbps,
            recording_mode=settings.mode,
            recording_custom_filename=settings.custom_filename,
            recording_folder=settings.folder,
        )
        try:
            self._frame.preferences_store.save(preferences)
        except OSError as exc:
            self._frame.SetStatusText(f"Não foi possível salvar as preferências de gravação: {exc}")
            return
        self._frame.preferences = preferences
        self._frame.engine.update_recording_settings(settings)

    def _on_browse_folder(self, _event: wx.Event) -> None:
        with wx.DirDialog(
            self,
            "Escolha a pasta para salvar as gravações",
            defaultPath=self.folder_ctrl.GetValue().strip() or str(default_recordings_directory()),
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.folder_ctrl.SetValue(dialog.GetPath())
                self._on_settings_changed()

    def _on_toggle_record(self, _event: wx.Event = None) -> None:
        if self._frame.engine.is_recording:
            try:
                path, duration = self._frame.engine.stop_recording()
                self.timer.Stop()
                self.record_button.SetLabel("&Iniciar gravação (F8)")
                _set_button_accessible_name(self.record_button, "Iniciar gravação de áudio")
                mins = int(duration // 60)
                secs = int(duration % 60)
                msg = f"Gravação salva ({mins:02d}:{secs:02d}): {path.name}"
                self.record_status.SetValue(msg)
                self.record_status.SetName(f"Estado da gravação: {msg}")
                self._frame.SetStatusText(msg)
                self._frame._play_feedback("toggle_off")
            except Exception as exc:
                self._frame._show_error(f"Erro ao encerrar a gravação.\n\n{exc}")
        else:
            if not self._frame.engine.is_running:
                self._frame._show_error("Inicie a mesa de som antes de iniciar a gravação.")
                return
            settings = self._current_settings()
            try:
                path = self._frame.engine.start_recording(settings)
                self.timer.Start(1000)
                self.record_button.SetLabel("&Parar gravação (F8)")
                _set_button_accessible_name(self.record_button, "Parar gravação de áudio")
                msg = f"Gravando ({path.name})..."
                self.record_status.SetValue(msg)
                self.record_status.SetName(f"Estado da gravação: {msg}")
                self._frame.SetStatusText(msg)
                self._frame._play_feedback("toggle_on")
            except Exception as exc:
                self._frame._show_error(f"Não foi possível iniciar a gravação.\n\n{exc}")

    def _on_timer(self, _event: wx.Event) -> None:
        if self._frame.engine.is_recording:
            elapsed = self._frame.engine.recording_elapsed_seconds
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            msg = f"Gravando: {mins:02d}:{secs:02d}"
            self.record_status.SetValue(msg)
            self.record_status.SetName(f"Estado da gravação: {msg}")



class ReleaseNotesDialog(wx.Dialog):
    """Native read-only text, immediately focused for screen-reader navigation."""

    def __init__(self, parent: wx.Window, text: str) -> None:
        super().__init__(parent, title=f"Novidades da Mini Mesa — {__version__}", size=(650, 550))
        root = wx.BoxSizer(wx.VERTICAL)
        self.news_text = wx.TextCtrl(
            self, value=text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self.news_text.SetName(f"Novidades da versão {__version__}")
        self.news_text.SetInsertionPoint(0)
        root.Add(self.news_text, 1, wx.ALL | wx.EXPAND, 12)
        close_button = wx.Button(self, wx.ID_OK, "&Fechar novidades")
        _set_button_accessible_name(close_button, "Fechar novidades")
        close_button.SetDefault()
        self.SetEscapeId(wx.ID_OK)
        root.Add(close_button, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizer(root)
        self.CentreOnParent()
        self.news_text.SetFocus()


class HelpDialog(wx.Dialog):
    """README help with semantic web headings and a continuous-text fallback."""

    def __init__(self, parent: MainFrame) -> None:
        super().__init__(parent, title="Ajuda da Mini Mesa de Som", size=(700, 620))
        root = wx.BoxSizer(wx.VERTICAL)
        self.instructions = wx.StaticText(
            self,
            label=(
                "Modo página web. Use H e Shift+H para navegar pelos cabeçalhos, "
                "os números de 1 a 6 para escolher o nível e as setas para ler."
            ),
        )
        root.Add(self.instructions, 0, wx.ALL | wx.EXPAND, 10)
        markdown = _load_project_markdown()
        self.help_text = wx.TextCtrl(
            self,
            value=(
                _markdown_to_accessible_text(markdown)
                if markdown is not None
                else _HELP_FALLBACK
            ),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self.help_text.SetName("Documentação da Mini Mesa de Som")
        self.help_text.SetInsertionPoint(0)
        self.web_help: wx.html2.WebView | None = None
        try:
            if markdown is not None:
                web_help = wx.html2.WebView.New(self)
                web_help.SetName("Documentação web da Mini Mesa de Som")
                web_help.SetPage(_markdown_to_help_html(markdown), _PROJECT_URL)
                self.web_help = web_help
                root.Add(
                    web_help,
                    1,
                    wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                    10,
                )
        except Exception:
            self.web_help = None
        root.Add(
            self.help_text,
            1,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
            10,
        )
        if self.web_help is not None:
            self.help_text.Hide()
            self._web_mode = True
        else:
            self._web_mode = False
            self.instructions.SetLabel(
                "Modo texto contínuo. Use as setas, Page Up, Page Down, Home e End."
            )

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.mode_button = wx.Button(self, label="Usar modo de &texto contínuo")
        _set_button_accessible_name(self.mode_button, "Usar modo de texto contínuo")
        self.mode_button.Bind(wx.EVT_BUTTON, self._on_toggle_reading_mode)
        self.mode_button.Enable(self.web_help is not None)
        actions.Add(self.mode_button, 1, wx.RIGHT | wx.EXPAND, 5)
        project_button = wx.Button(self, label="Abrir &projeto no GitHub")
        _set_button_accessible_name(project_button, "Abrir projeto no GitHub")
        project_button.Bind(
            wx.EVT_BUTTON, lambda _event: wx.LaunchDefaultBrowser(_PROJECT_URL)
        )
        actions.Add(project_button, 1, wx.RIGHT | wx.EXPAND, 5)
        paulo_button = wx.Button(self, label="Abrir GitHub de P&aulo Santesso")
        _set_button_accessible_name(paulo_button, "Abrir GitHub de Paulo Santesso")
        paulo_button.Bind(
            wx.EVT_BUTTON, lambda _event: wx.LaunchDefaultBrowser(_PAULO_URL)
        )
        actions.Add(paulo_button, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 5)
        close_button = wx.Button(self, wx.ID_CANCEL, "&Fechar")
        _set_button_accessible_name(close_button, "Fechar")
        actions.Add(close_button, 1, wx.LEFT | wx.EXPAND, 5)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.SetSizer(root)
        if self.web_help is not None:
            wx.CallAfter(self.web_help.SetFocus)
        else:
            self.help_text.SetFocus()

    def _on_toggle_reading_mode(self, _event: wx.Event) -> None:
        if self.web_help is None:
            return
        self._web_mode = not self._web_mode
        self.web_help.Show(self._web_mode)
        self.help_text.Show(not self._web_mode)
        if self._web_mode:
            self.instructions.SetLabel(
                "Modo página web. Use H e Shift+H para navegar pelos cabeçalhos, "
                "os números de 1 a 6 para escolher o nível e as setas para ler."
            )
            self.mode_button.SetLabel("Usar modo de &texto contínuo")
            _set_button_accessible_name(
                self.mode_button, "Usar modo de texto contínuo"
            )
            self.web_help.SetFocus()
        else:
            self.instructions.SetLabel(
                "Modo texto contínuo. Use as setas, Page Up, Page Down, Home e End."
            )
            self.mode_button.SetLabel("Usar navegação por &cabeçalhos")
            _set_button_accessible_name(
                self.mode_button, "Usar navegação por cabeçalhos"
            )
            self.help_text.SetFocus()
        self.Layout()


class SoundPreviewDialog(wx.Dialog):
    def __init__(self, parent: MainFrame, path: str, page: int) -> None:
        super().__init__(parent, title="Conferir efeito antes de adicionar")
        self._frame = parent
        self._sound = PersonalSound(Path(path).stem, path, page)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            wx.StaticText(
                self,
                label=f"Arquivo: {Path(path).name}\nUse Ouvir para conferir e depois escolha Adicionar.",
            ),
            0,
            wx.ALL | wx.EXPAND,
            12,
        )
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        preview = wx.Button(self, label="&Ouvir prévia")
        preview_available = bool(parent.monitor_choice.GetStringSelection())
        preview.Enable(preview_available)
        preview.SetName(
            "Ouvir prévia" if preview_available
            else "Ouvir prévia indisponível; escolha um dispositivo de retorno"
        )
        preview.Bind(wx.EVT_BUTTON, lambda _event: parent.preview_personal_sound(self._sound))
        buttons.Add(preview, 1, wx.RIGHT, 6)
        add = wx.Button(self, wx.ID_OK, "&Adicionar")
        _set_button_accessible_name(add, "Adicionar")
        add.SetDefault()
        buttons.Add(add, 1, wx.RIGHT, 6)
        cancel = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
        _set_button_accessible_name(cancel, "Cancelar")
        buttons.Add(cancel, 1)
        root.Add(buttons, 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizerAndFit(root)
        self.SetEscapeId(wx.ID_CANCEL)


class DiagnosticDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, report: str) -> None:
        super().__init__(parent, title="Diagnóstico da Mini Mesa", size=(700, 600))
        root = wx.BoxSizer(wx.VERTICAL)
        self.report = wx.TextCtrl(
            self, value=report, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        self.report.SetName("Relatório de diagnóstico")
        self.report.SetInsertionPoint(0)
        root.Add(self.report, 1, wx.ALL | wx.EXPAND, 12)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        copy_button = wx.Button(self, label="&Copiar diagnóstico")
        _set_button_accessible_name(copy_button, "Copiar diagnóstico")
        copy_button.Bind(wx.EVT_BUTTON, self._on_copy)
        buttons.Add(copy_button, 1, wx.RIGHT, 6)
        close_button = wx.Button(self, wx.ID_OK, "&Fechar")
        _set_button_accessible_name(close_button, "Fechar")
        buttons.Add(close_button, 1)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.SetSizer(root)
        self.report.SetFocus()

    def _on_copy(self, _event: wx.Event) -> None:
        if not wx.TheClipboard.Open():
            wx.MessageBox("Não foi possível acessar a área de transferência.")
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(self.report.GetValue()))
        finally:
            wx.TheClipboard.Close()


class HotkeySettingsDialog(wx.Dialog):
    _EFFECT_VALUES = ("control", "control_alt")
    _PAGE_VALUES = ("alt", "alt_shift")

    def __init__(self, parent: wx.Window, preferences: AppPreferences) -> None:
        super().__init__(parent, title="Atalhos globais")
        root = wx.BoxSizer(wx.VERTICAL)
        self.enabled = wx.CheckBox(
            self, label="&Ativar atalhos mesmo quando outro programa estiver em foco"
        )
        self.enabled.SetValue(preferences.global_shortcuts_enabled)
        root.Add(self.enabled, 0, wx.ALL | wx.EXPAND, 12)
        root.Add(wx.StaticText(self, label="Modificador para &tocar efeitos:"), 0, wx.LEFT | wx.RIGHT, 12)
        self.effect_modifier = wx.Choice(
            self, choices=[modifier_label(value) for value in self._EFFECT_VALUES]
        )
        _set_choice_accessible_name(
            self.effect_modifier, "Modificador para tocar efeitos"
        )
        self.effect_modifier.SetSelection(self._EFFECT_VALUES.index(preferences.global_effect_modifier))
        root.Add(self.effect_modifier, 0, wx.ALL | wx.EXPAND, 12)
        root.Add(wx.StaticText(self, label="Modificador para trocar &páginas:"), 0, wx.LEFT | wx.RIGHT, 12)
        self.page_modifier = wx.Choice(
            self, choices=[modifier_label(value) for value in self._PAGE_VALUES]
        )
        _set_choice_accessible_name(
            self.page_modifier, "Modificador para trocar páginas"
        )
        self.page_modifier.SetSelection(self._PAGE_VALUES.index(preferences.global_page_modifier))
        root.Add(self.page_modifier, 0, wx.ALL | wx.EXPAND, 12)
        root.Add(
            wx.StaticText(
                self,
                label="Os atalhos podem deixar de funcionar em outro programa que já use a mesma combinação.",
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
            12,
        )
        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        ok_button = self.FindWindow(wx.ID_OK)
        if ok_button is not None:
            _set_button_accessible_name(ok_button, "OK")
        cancel_button = self.FindWindow(wx.ID_CANCEL)
        if cancel_button is not None:
            _set_button_accessible_name(cancel_button, "Cancelar")
        root.Add(buttons, 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizerAndFit(root)

    @property
    def values(self) -> tuple[bool, str, str]:
        return (
            self.enabled.GetValue(),
            self._EFFECT_VALUES[self.effect_modifier.GetSelection()],
            self._PAGE_VALUES[self.page_modifier.GetSelection()],
        )


class MainFrame(wx.Frame):
    def __init__(
        self,
        engine: AudioEngine,
        preferences_store: PreferencesStore | None = None,
    ) -> None:
        display_area = wx.GetClientDisplayRect()
        frame_size = (
            min(620, max(400, display_area.GetWidth() - 40)),
            min(800, max(480, display_area.GetHeight() - 80)),
        )
        super().__init__(None, title="Mini Mesa de Som", size=frame_size)
        self.engine = engine
        self.engine.set_error_handler(self._on_audio_error)
        self.preferences_store = preferences_store or PreferencesStore()
        self.preferences = self.preferences_store.load()
        self.profile_store = ProfileStore(
            self.preferences_store.path.with_name("profiles.json")
        )
        self._global_hotkeys = GlobalHotkeyManager(self)
        self._last_level_state = ""
        self._pending_level_state = ""
        self._pending_level_count = 0
        self._soundboard_settings = SoundboardSettings(
            volume_percent=self.preferences.soundboard_volume_percent,
            ducking_enabled=self.preferences.soundboard_ducking_enabled,
            ducking_percent=self.preferences.soundboard_ducking_percent,
        )
        self._tray_icon: SystemTrayIcon | None = None
        self._last_focused_control: wx.Window | None = None
        self._minimize_generation = 0
        self._update_check_in_progress = False
        self._update_progress_dialog: wx.ProgressDialog | None = None
        self._update_cancel_event: threading.Event | None = None
        self._creative_update_queued = False
        self._process_items = ()

        panel = wx.Panel(self)
        self.notebook = wx.Notebook(panel, style=wx.NB_TOP | wx.NB_MULTILINE)
        self.notebook.SetLabel("Guias da mesa de som")
        self.notebook.SetName("Guias da mesa de som")
        self.notebook.SetMinSize((1, 1))
        pages = []
        page_sizers = []
        for title in ("Dispositivos", "Voz e efeitos", "Limpeza da voz", "Áudio 3D"):
            page = wx.ScrolledWindow(
                self.notebook, style=wx.VSCROLL | wx.TAB_TRAVERSAL
            )
            page.SetName(title)
            page.SetScrollRate(0, 12)
            page.SetMinSize((1, 1))
            sizer = wx.BoxSizer(wx.VERTICAL)
            page.SetSizer(sizer)
            self.notebook.AddPage(page, title)
            pages.append(page)
            page_sizers.append(sizer)
        devices_page, voice_page, cleanup_page, spatial_page = pages
        devices_root, voice_root, cleanup_root, spatial_root = page_sizers
        root = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(
            devices_page,
            label=(
                "Escolha o microfone físico e a saída do cabo virtual. "
                "O Discord ou TeamTalk deve usar a outra ponta do cabo como microfone."
            ),
        )
        intro.Wrap(540)
        devices_root.Add(intro, 0, wx.ALL | wx.EXPAND, 12)

        devices = wx.StaticBoxSizer(wx.VERTICAL, devices_page, "Dispositivos de áudio")
        box_devices = devices.GetStaticBox()

        input_label = wx.StaticText(box_devices, label="&Microfone de entrada:")
        self.input_choice = wx.Choice(box_devices)
        _set_choice_accessible_name(self.input_choice, "Microfone de entrada")
        self.input_choice.Bind(wx.EVT_CHOICE, self._on_preference_changed)
        devices.Add(input_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        devices.Add(self.input_choice, 0, wx.ALL | wx.EXPAND, 8)

        output_label = wx.StaticText(box_devices, label="&Saída virtual:")
        self.output_choice = wx.Choice(box_devices)
        _set_choice_accessible_name(
            self.output_choice, "Saída virtual para Discord ou TeamTalk"
        )
        self.output_choice.Bind(wx.EVT_CHOICE, self._on_preference_changed)
        devices.Add(output_label, 0, wx.LEFT | wx.RIGHT, 8)
        devices.Add(self.output_choice, 0, wx.ALL | wx.EXPAND, 8)

        # A native checkbox exposes its checked state to screen readers without
        # replacing the control name with the confusing "Ativar/Desativar"
        # action wording used by effect toggle buttons.
        self.monitor_checkbox = wx.CheckBox(box_devices, label="&Ouvir retorno")
        self.monitor_checkbox.SetName("Ouvir retorno")
        self.monitor_checkbox.SetValue(self.preferences.monitor_enabled)
        self.monitor_checkbox.Bind(wx.EVT_CHECKBOX, self._on_monitor_toggled)
        devices.Add(self.monitor_checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        monitor_label = wx.StaticText(box_devices, label="Dispositivo de re&torno:")
        self.monitor_choice = wx.Choice(box_devices)
        _set_choice_accessible_name(
            self.monitor_choice,
            "Dispositivo para ouvir os efeitos e o retorno da voz",
        )
        self.monitor_choice.Enable()
        self.monitor_choice.Bind(wx.EVT_CHOICE, self._on_preference_changed)
        devices.Add(monitor_label, 0, wx.LEFT | wx.RIGHT, 8)
        devices.Add(self.monitor_choice, 0, wx.ALL | wx.EXPAND, 8)

        self.refresh_button = wx.Button(box_devices, label="Atualizar dispositivos (F5)")
        _set_button_accessible_name(self.refresh_button, "Atualizar dispositivos")
        self.refresh_button.Bind(wx.EVT_BUTTON, self._on_refresh)
        devices.Add(self.refresh_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        devices_root.Add(devices, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        process_box = wx.StaticBoxSizer(
            wx.VERTICAL, devices_page, "Programas enviados na transmissão"
        )
        process_panel = process_box.GetStaticBox()
        process_help = wx.StaticText(
            process_panel,
            label=("Marque os programas cujo áudio será misturado ao microfone. "
                   "A alteração é aplicada na próxima ativação da mesa."),
        )
        process_help.Wrap(540)
        self.process_list = wx.CheckListBox(process_panel)
        self.process_list.SetName("Programas para transmitir")
        self.process_list.SetMinSize((-1, 150))
        self.process_list.Bind(
            wx.EVT_CHECKLISTBOX, self._on_process_selection_changed
        )
        self.refresh_processes_button = wx.Button(
            process_panel, label="Atualizar programas"
        )
        _set_button_accessible_name(
            self.refresh_processes_button, "Atualizar programas em execução"
        )
        self.refresh_processes_button.Bind(wx.EVT_BUTTON, self._on_refresh_processes)
        process_box.Add(process_help, 0, wx.ALL | wx.EXPAND, 8)
        process_box.Add(self.process_list, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)
        process_box.Add(self.refresh_processes_button, 0, wx.ALL, 8)
        devices_root.Add(process_box, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        volumes = wx.StaticBoxSizer(wx.VERTICAL, devices_page, "Volumes")
        volume_panel = volumes.GetStaticBox()
        self.microphone_volume = wx.Slider(
            volume_panel, value=self.preferences.microphone_volume_percent,
            minValue=0, maxValue=200, style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self.process_volume = wx.Slider(
            volume_panel, value=self.preferences.process_volume_percent,
            minValue=0, maxValue=200, style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        _set_slider_accessible_name(self.microphone_volume, "Volume do microfone")
        _set_slider_accessible_name(self.process_volume, "Volume dos programas")
        self.microphone_volume.Bind(wx.EVT_SLIDER, self._on_native_volume_changed)
        self.process_volume.Bind(wx.EVT_SLIDER, self._on_native_volume_changed)
        volumes.Add(wx.StaticText(volume_panel, label="Volume do &microfone:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        volumes.Add(self.microphone_volume, 0, wx.ALL | wx.EXPAND, 8)
        volumes.Add(wx.StaticText(volume_panel, label="Volume dos &programas:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        volumes.Add(self.process_volume, 0, wx.ALL | wx.EXPAND, 8)
        devices_root.Add(volumes, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        effect = wx.StaticBoxSizer(wx.VERTICAL, voice_page, "Reverb")
        box_effect = effect.GetStaticBox()
        self.reverb_checkbox = EffectToggleButton(box_effect, label="Ativar &efeito de reverb")
        self.reverb_checkbox.SetName("Ativar efeito de reverb")
        self.reverb_checkbox.SetValue(self.preferences.reverb_enabled)
        self.reverb_checkbox.BindToggle(self._on_settings_changed)
        level_label = wx.StaticText(box_effect, label="Nível de &reverb (0 a 100):")
        self.reverb_level = wx.Slider(
            box_effect,
            value=self.preferences.reverb_level,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self._reverb_level_accessible = _set_slider_accessible_name(
            self.reverb_level, "Nível de reverb"
        )
        self.reverb_level.Enable(self.preferences.reverb_enabled)
        self.reverb_level.Bind(wx.EVT_SLIDER, self._on_settings_changed)
        effect.Add(self.reverb_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        effect.Add(level_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        effect.Add(self.reverb_level, 0, wx.ALL | wx.EXPAND, 8)
        voice_root.Add(effect, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        voice_box = wx.StaticBoxSizer(
            wx.VERTICAL, voice_page, "Efeitos de voz (Modulador de tom / Pitch)"
        )
        box_voice = voice_box.GetStaticBox()
        self.voice_checkbox = EffectToggleButton(
            box_voice, label="Ativar &modificador de voz"
        )
        self.voice_checkbox.SetName("Ativar modificador de voz")
        self.voice_checkbox.SetValue(self.preferences.voice_enabled)
        self.voice_checkbox.BindToggle(self._on_voice_changed)

        voice_preset_label = wx.StaticText(box_voice, label="P&reset de voz:")
        self.voice_preset_choice = wx.Choice(
            box_voice,
            choices=[label for _value, label, _pitch in _VOICE_PRESETS],
        )
        _set_choice_accessible_name(
            self.voice_preset_choice, "Preset de modulação de voz"
        )
        self.voice_preset_choice.Enable(self.preferences.voice_enabled)
        self.voice_preset_choice.Bind(wx.EVT_CHOICE, self._on_voice_preset_selected)

        voice_pitch_label = wx.StaticText(
            box_voice, label="Ajuste de &tom em semitons (-12 a +12):"
        )
        self.voice_pitch = wx.Slider(
            box_voice,
            value=int(self.preferences.voice_pitch_semitones),
            minValue=-12,
            maxValue=12,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self._voice_pitch_accessible = _set_slider_accessible_name(
            self.voice_pitch, "Ajuste de tom da voz em semitons"
        )
        self.voice_pitch.Enable(self.preferences.voice_enabled)
        self.voice_pitch.Bind(wx.EVT_SLIDER, self._on_voice_changed)

        voice_box.Add(self.voice_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        voice_box.Add(voice_preset_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        voice_box.Add(self.voice_preset_choice, 0, wx.ALL | wx.EXPAND, 8)
        voice_box.Add(voice_pitch_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        voice_box.Add(self.voice_pitch, 0, wx.ALL | wx.EXPAND, 8)
        voice_root.Add(voice_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.voice_preset_choice.SetSelection(
            next(
                (
                    index
                    for index, (value, _label, _pitch) in enumerate(_VOICE_PRESETS)
                    if value == self.preferences.voice_preset
                ),
                0,
            )
        )
        self._update_voice_controls()

        creative_box = wx.StaticBoxSizer(
            wx.VERTICAL,
            voice_page,
            "Efeitos de estilo & Eco (Telefone, Megafone, Robô, Delay)",
        )
        box_creative = creative_box.GetStaticBox()
        creative_label = wx.StaticText(box_creative, label="Es&tilo de voz especial:")
        self.creative_choice = wx.Choice(
            box_creative,
            choices=[label for _value, label in _STYLE_PRESETS],
        )
        _set_choice_accessible_name(
            self.creative_choice, "Estilo de voz especial"
        )
        self.creative_choice.SetSelection(
            next(
                (i for i, item in enumerate(_STYLE_PRESETS) if item[0] == self.preferences.creative_effect_preset),
                0,
            )
        )
        self.creative_choice.Bind(wx.EVT_CHOICE, self._on_creative_choice_changed)
        self.creative_choice.Bind(wx.EVT_KEY_UP, self._on_creative_choice_key_up)

        modulation_label = wx.StaticText(box_creative, label="&Modulação:")
        self.modulation_choice = wx.Choice(
            box_creative, choices=[label for _value, label in _MODULATIONS]
        )
        _set_choice_accessible_name(self.modulation_choice, "Modulação")
        self.modulation_choice.SetSelection(
            next(
                (i for i, item in enumerate(_MODULATIONS) if item[0] == self.preferences.modulation_effect),
                0,
            )
        )
        self.modulation_choice.Bind(wx.EVT_CHOICE, self._on_creative_choice_changed)
        self.modulation_choice.Bind(wx.EVT_KEY_UP, self._on_creative_choice_key_up)

        ambience_label = wx.StaticText(box_creative, label="&Ambiente:")
        self.ambience_choice = wx.Choice(
            box_creative, choices=[label for _value, label in _AMBIENCES]
        )
        _set_choice_accessible_name(self.ambience_choice, "Ambiente")
        self.ambience_choice.SetSelection(
            next(
                (i for i, item in enumerate(_AMBIENCES) if item[0] == self.preferences.ambience_preset),
                0,
            )
        )
        self.ambience_choice.Bind(wx.EVT_CHOICE, self._on_creative_choice_changed)
        self.ambience_choice.Bind(wx.EVT_KEY_UP, self._on_creative_choice_key_up)

        style_intensity_label = wx.StaticText(
            box_creative, label="Intensidade do e&stilo:"
        )
        self.style_intensity = wx.Slider(
            box_creative,
            value=self.preferences.style_intensity_percent,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
            name="Intensidade do estilo de voz especial",
        )
        self._style_intensity_accessible = _set_slider_accessible_name(
            self.style_intensity, "Intensidade do estilo de voz especial"
        )
        self.style_intensity.Bind(wx.EVT_SLIDER, self._on_creative_changed)
        modulation_intensity_label = wx.StaticText(
            box_creative, label="Intensidade da mod&ulação:"
        )
        self.modulation_intensity = wx.Slider(
            box_creative,
            value=self.preferences.modulation_intensity_percent,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
            name="Intensidade da modulação da voz",
        )
        self._modulation_intensity_accessible = _set_slider_accessible_name(
            self.modulation_intensity, "Intensidade da modulação da voz"
        )
        self.modulation_intensity.Bind(wx.EVT_SLIDER, self._on_creative_changed)
        ambience_intensity_label = wx.StaticText(
            box_creative, label="Intensidade do amb&iente:"
        )
        self.ambience_intensity = wx.Slider(
            box_creative,
            value=self.preferences.ambience_intensity_percent,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
            name="Intensidade do ambiente da voz",
        )
        self._ambience_intensity_accessible = _set_slider_accessible_name(
            self.ambience_intensity, "Intensidade do ambiente da voz"
        )
        self.ambience_intensity.Bind(wx.EVT_SLIDER, self._on_creative_changed)
        self.roger_beep_checkbox = EffectToggleButton(
            box_creative, label="Ativar bipes de rádio no &início e no fim da fala"
        )
        self.roger_beep_checkbox.SetValue(self.preferences.roger_beep_enabled)
        self.roger_beep_checkbox.BindToggle(self._on_creative_changed)

        self.delay_checkbox = EffectToggleButton(
            box_creative, label="Ativar &eco / delay de estádio"
        )
        self.delay_checkbox.SetName("Ativar eco de estádio")
        self.delay_checkbox.SetValue(self.preferences.delay_enabled)
        self.delay_checkbox.BindToggle(self._on_creative_changed)

        delay_label = wx.StaticText(box_creative, label="Nível de &eco (0 a 100):")
        self.delay_level = wx.Slider(
            box_creative,
            value=self.preferences.delay_level_percent,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self._delay_level_accessible = _set_slider_accessible_name(
            self.delay_level, "Nível de eco"
        )
        self.delay_level.Enable(self.preferences.delay_enabled)
        self.delay_level.Bind(wx.EVT_SLIDER, self._on_creative_changed)

        creative_box.Add(creative_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        creative_box.Add(self.creative_choice, 0, wx.ALL | wx.EXPAND, 8)
        creative_box.Add(modulation_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        creative_box.Add(self.modulation_choice, 0, wx.ALL | wx.EXPAND, 8)
        creative_box.Add(ambience_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        creative_box.Add(self.ambience_choice, 0, wx.ALL | wx.EXPAND, 8)
        creative_box.Add(style_intensity_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        creative_box.Add(self.style_intensity, 0, wx.ALL | wx.EXPAND, 8)
        creative_box.Add(modulation_intensity_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        creative_box.Add(self.modulation_intensity, 0, wx.ALL | wx.EXPAND, 8)
        creative_box.Add(ambience_intensity_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        creative_box.Add(self.ambience_intensity, 0, wx.ALL | wx.EXPAND, 8)
        creative_box.Add(self.roger_beep_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        creative_box.Add(self.delay_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        creative_box.Add(delay_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        creative_box.Add(self.delay_level, 0, wx.ALL | wx.EXPAND, 8)
        voice_root.Add(creative_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        pro_box = wx.StaticBoxSizer(
            wx.VERTICAL, cleanup_page, "Efeitos profissionais & Equalizador de voz"
        )
        box_pro = pro_box.GetStaticBox()
        self.compressor_checkbox = EffectToggleButton(
            box_pro, label="Ativar &compressor de voz de rádio (Podcast)"
        )
        self.compressor_checkbox.SetName("Ativar compressor de voz de rádio")
        self.compressor_checkbox.SetValue(self.preferences.compressor_enabled)
        self.compressor_checkbox.BindToggle(self._on_pro_audio_changed)

        self.eq_checkbox = EffectToggleButton(
            box_pro, label="Ativar &equalizador de 3 bandas (EQ)"
        )
        self.eq_checkbox.SetName("Ativar equalizador de 3 bandas")
        self.eq_checkbox.SetValue(self.preferences.eq_enabled)
        self.eq_checkbox.BindToggle(self._on_pro_audio_changed)

        pro_toggles = (
            ("noise_gate_checkbox", "Ativar noise &gate", self.preferences.noise_gate_enabled),
            ("deesser_checkbox", "Ativar &de-esser", self.preferences.deesser_enabled),
            ("expander_checkbox", "Ativar e&xpander", self.preferences.expander_enabled),
            ("auto_gain_checkbox", "Ativar ganho &automático", self.preferences.auto_gain_enabled),
            ("plosive_checkbox", "Ativar filtro de sons explosivos &P/B", self.preferences.plosive_filter_enabled),
        )
        for attribute, label, checked in pro_toggles:
            checkbox = EffectToggleButton(box_pro, label=label)
            checkbox.SetValue(checked)
            checkbox.BindToggle(self._on_pro_audio_changed)
            setattr(self, attribute, checkbox)

        eq_low_label = wx.StaticText(box_pro, label="G&raves (Bass) em dB (-12 a +12):")
        self.eq_low = wx.Slider(
            box_pro,
            value=int(self.preferences.eq_low_db),
            minValue=-12,
            maxValue=12,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
            name="Intensidade de graves do equalizador, em decibéis",
        )
        self._eq_low_accessible = _set_slider_accessible_name(
            self.eq_low, "Intensidade de graves do equalizador, em decibéis"
        )
        self.eq_low.Enable(self.preferences.eq_enabled)
        self.eq_low.Bind(wx.EVT_SLIDER, self._on_pro_audio_changed)

        eq_mid_label = wx.StaticText(box_pro, label="M&édios (Mids) em dB (-12 a +12):")
        self.eq_mid = wx.Slider(
            box_pro,
            value=int(self.preferences.eq_mid_db),
            minValue=-12,
            maxValue=12,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
            name="Intensidade de médios do equalizador, em decibéis",
        )
        self._eq_mid_accessible = _set_slider_accessible_name(
            self.eq_mid, "Intensidade de médios do equalizador, em decibéis"
        )
        self.eq_mid.Enable(self.preferences.eq_enabled)
        self.eq_mid.Bind(wx.EVT_SLIDER, self._on_pro_audio_changed)

        eq_high_label = wx.StaticText(box_pro, label="A&gudos (Treble) em dB (-12 a +12):")
        self.eq_high = wx.Slider(
            box_pro,
            value=int(self.preferences.eq_high_db),
            minValue=-12,
            maxValue=12,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
            name="Intensidade de agudos do equalizador, em decibéis",
        )
        self._eq_high_accessible = _set_slider_accessible_name(
            self.eq_high, "Intensidade de agudos do equalizador, em decibéis"
        )
        self.eq_high.Enable(self.preferences.eq_enabled)
        self.eq_high.Bind(wx.EVT_SLIDER, self._on_pro_audio_changed)

        pro_box.Add(self.compressor_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(self.eq_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(self.noise_gate_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(self.deesser_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(self.expander_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(self.auto_gain_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(self.plosive_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(eq_low_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(self.eq_low, 0, wx.ALL | wx.EXPAND, 8)
        pro_box.Add(eq_mid_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(self.eq_mid, 0, wx.ALL | wx.EXPAND, 8)
        pro_box.Add(eq_high_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        pro_box.Add(self.eq_high, 0, wx.ALL | wx.EXPAND, 8)
        cleanup_root.Add(pro_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        noise_reduction = wx.StaticBoxSizer(
            wx.VERTICAL, cleanup_page, "Redução de ruído"
        )
        box_noise = noise_reduction.GetStaticBox()
        self.noise_reduction_checkbox = EffectToggleButton(
            box_noise, label="Ativar redução de ruí&do profissional"
        )
        self.noise_reduction_checkbox.SetName(
            "Ativar redução de ruído profissional no microfone"
        )
        self.noise_reduction_checkbox.SetValue(
            self.preferences.noise_reduction_enabled
        )
        self.noise_reduction_checkbox.BindToggle(self._on_noise_reduction_toggled)
        noise_reduction.Add(
            self.noise_reduction_checkbox,
            0,
            wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
            8,
        )
        cleanup_root.Add(
            noise_reduction,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
            12,
        )

        spatial = wx.StaticBoxSizer(wx.VERTICAL, spatial_page, "Áudio espacial binaural")
        box_spatial = spatial.GetStaticBox()
        self.spatial_checkbox = EffectToggleButton(
            box_spatial, label="Ativar áudio es&pacial 3D com HRTF"
        )
        self.spatial_checkbox.SetName("Ativar áudio espacial binaural com HRTF")
        self.spatial_checkbox.SetValue(self.preferences.spatial_enabled)
        self.spatial_checkbox.BindToggle(self._on_spatial_changed)
        spatial.Add(self.spatial_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        coordinates = wx.FlexGridSizer(cols=2, vgap=5, hgap=8)
        coordinates.AddGrowableCol(1)
        coordinate_specs = (
            (
                "&X, esquerda menos 100 e direita mais 100:",
                "spatial_x",
                self.preferences.spatial_x,
            ),
            (
                "&Y, baixo menos 100 e cima mais 100:",
                "spatial_y",
                self.preferences.spatial_y,
            ),
            (
                "&Z, trás menos 100 e frente mais 100:",
                "spatial_z",
                self.preferences.spatial_z,
            ),
        )
        for label, attribute, value in coordinate_specs:
            coordinates.Add(
                wx.StaticText(box_spatial, label=label),
                0,
                wx.ALIGN_CENTER_VERTICAL,
            )
            control = wx.SpinCtrl(
                box_spatial, min=-100, max=100, initial=value
            )
            _set_spin_accessible_name(control, label.replace("&", "").rstrip(":"))
            setattr(self, attribute, control)
            coordinates.Add(control, 1, wx.EXPAND)
        spatial.Add(coordinates, 0, wx.ALL | wx.EXPAND, 8)

        self.spatial_automatic = EffectToggleButton(
            box_spatial,
            label="Ativar movimento a&utomático pelos três eixos",
        )
        self.spatial_automatic.SetName("Movimento espacial automático em X, Y e Z")
        self.spatial_automatic.SetValue(self.preferences.spatial_automatic)
        spatial.Add(self.spatial_automatic, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        speed_row = wx.BoxSizer(wx.HORIZONTAL)
        speed_row.Add(
            wx.StaticText(box_spatial, label="&Velocidade automática, 1 a 100:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.spatial_speed = wx.SpinCtrl(
            box_spatial,
            min=1,
            max=100,
            initial=self.preferences.spatial_speed,
        )
        _set_spin_accessible_name(
            self.spatial_speed, "Velocidade do movimento espacial automático"
        )
        speed_row.Add(self.spatial_speed, 1, wx.EXPAND)
        spatial.Add(speed_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        for control in (
            self.spatial_x,
            self.spatial_y,
            self.spatial_z,
            self.spatial_speed,
        ):
            control.Bind(wx.EVT_SPINCTRL, self._on_spatial_changed)
        self.spatial_automatic.BindToggle(self._on_spatial_changed)
        self._set_spatial_controls_enabled()
        spatial_root.Add(spatial, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.soundboard_panel = SoundboardPanel(self.notebook, self)
        self.notebook.AddPage(self.soundboard_panel, "Painel de efeitos")
        self.recording_panel = RecordingPanel(self.notebook, self)
        self.notebook.AddPage(self.recording_panel, "Gravar")
        for page in pages:
            page.FitInside()
        root.Add(self.notebook, 1, wx.ALL | wx.EXPAND, 8)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.toggle_button = wx.Button(panel, label="&Ativar mesa")
        _set_button_accessible_name(self.toggle_button, "Ativar mesa")
        self.toggle_button.SetDefault()
        self.toggle_button.Bind(wx.EVT_BUTTON, self._on_toggle)
        actions.Add(self.toggle_button, 1, wx.RIGHT | wx.EXPAND, 6)

        self.exit_button = wx.Button(panel, label="En&cerrar programa")
        _set_button_accessible_name(self.exit_button, "Encerrar a Mini Mesa de Som")
        self.exit_button.Bind(wx.EVT_BUTTON, self._on_exit)
        actions.Add(self.exit_button, 1, wx.LEFT | wx.EXPAND, 6)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        status_label = wx.StaticText(panel, label="Estado do processamento:")
        self.status = wx.TextCtrl(
            panel,
            value="Desativado.",
            style=wx.TE_READONLY,
        )
        self.status.SetName("Estado do processamento")
        root.Add(status_label, 0, wx.LEFT | wx.RIGHT, 12)
        root.Add(self.status, 0, wx.ALL | wx.EXPAND, 12)

        level_label = wx.StaticText(panel, label="Nível do microfone:")
        self.input_level_status = wx.TextCtrl(
            panel, value="Mesa desativada.", style=wx.TE_READONLY
        )
        self.input_level_status.SetName("Nível do microfone: mesa desativada")
        root.Add(level_label, 0, wx.LEFT | wx.RIGHT, 12)
        root.Add(self.input_level_status, 0, wx.ALL | wx.EXPAND, 12)

        panel.SetSizer(root)
        frame_root = wx.BoxSizer(wx.VERTICAL)
        frame_root.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame_root)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_navigation_key)
        self.CreateStatusBar()
        self.SetStatusText("F5 atualiza a lista de dispositivos.")

        menu_bar = wx.MenuBar()
        effects_menu = wx.Menu()
        self._open_soundboard_id = wx.NewIdRef()
        self._stop_effects_id = wx.NewIdRef()
        effects_menu.Append(
            self._open_soundboard_id,
            "&Abrir painel de efeitos\tCtrl+Shift+E",
        )
        effects_menu.AppendSeparator()
        self._effect_menu_ids: dict[int, int] = {}
        for number in range(1, 11):
            menu_id = wx.NewIdRef()
            effects_menu.Append(menu_id, f"Reproduzir efeito {number} da página atual\tCtrl+{number % 10}")
            self._effect_menu_ids[int(menu_id)] = number - 1
            self.Bind(
                wx.EVT_MENU,
                lambda _event, index=number - 1: self.soundboard_panel.play_index(index),
                id=menu_id,
            )
        effects_menu.AppendSeparator()
        effects_menu.Append(self._stop_effects_id, "&Parar todos\tCtrl+Shift+0")
        pages_menu = wx.Menu()
        self._page_menu_ids: dict[int, int] = {}
        for page in range(10):
            menu_id = wx.NewIdRef()
            self._page_menu_ids[int(menu_id)] = page
            pages_menu.Append(menu_id, f"Página {page + 1}\tAlt+{(page + 1) % 10}")
            self.Bind(wx.EVT_MENU,
                      lambda _event, page=page: self.soundboard_panel.select_page(page),
                      id=menu_id)
        effects_menu.AppendSubMenu(pages_menu, "Páginas de efeitos")
        menu_bar.Append(effects_menu, "E&feitos")

        tools_menu = wx.Menu()
        self._hotkeys_id = wx.NewIdRef()
        self._save_profile_id = wx.NewIdRef()
        self._load_profile_id = wx.NewIdRef()
        self._delete_profile_id = wx.NewIdRef()
        self._export_id = wx.NewIdRef()
        self._import_id = wx.NewIdRef()
        self._diagnostic_id = wx.NewIdRef()
        self._feedback_id = wx.NewIdRef()
        tools_menu.Append(self._hotkeys_id, "Configurar atalhos &globais...")
        tools_menu.AppendSeparator()
        tools_menu.Append(self._save_profile_id, "&Salvar perfil atual...")
        tools_menu.Append(self._load_profile_id, "&Carregar perfil...")
        tools_menu.Append(self._delete_profile_id, "&Excluir perfil...")
        tools_menu.AppendSeparator()
        tools_menu.Append(self._export_id, "Exportar &backup...")
        tools_menu.Append(self._import_id, "&Importar backup...")
        tools_menu.AppendSeparator()
        feedback_item = tools_menu.AppendCheckItem(
            self._feedback_id, "Avisos sonoros &locais"
        )
        feedback_item.Check(self.preferences.feedback_sounds_enabled)
        self._feedback_item = feedback_item
        tools_menu.Append(self._diagnostic_id, "Abrir &diagnóstico...")
        menu_bar.Append(tools_menu, "&Ferramentas")

        help_menu = wx.Menu()
        self._news_id = wx.NewIdRef()
        help_menu.Append(self._news_id, "&Novidades desta versão")
        self.Bind(wx.EVT_MENU, self._on_release_notes, id=self._news_id)
        self._project_help_id = wx.NewIdRef()
        self._check_updates_id = wx.NewIdRef()
        help_menu.Append(self._project_help_id, "&Ajuda do projeto\tF1")
        help_menu.AppendSeparator()
        help_menu.Append(self._check_updates_id, "Verificar &atualizações")
        menu_bar.Append(help_menu, "A&juda")
        self.SetMenuBar(menu_bar)

        self._id_f2 = wx.NewIdRef()
        self._id_f3 = wx.NewIdRef()
        self._id_f4 = wx.NewIdRef()
        self._id_f6 = wx.NewIdRef()
        self._id_f8 = wx.NewIdRef()
        accelerators = [
            (wx.ACCEL_NORMAL, wx.WXK_F5, wx.ID_REFRESH),
            (wx.ACCEL_NORMAL, wx.WXK_F1, self._project_help_id),
            (wx.ACCEL_NORMAL, wx.WXK_F2, self._id_f2),
            (wx.ACCEL_NORMAL, wx.WXK_F3, self._id_f3),
            (wx.ACCEL_NORMAL, wx.WXK_F4, self._id_f4),
            (wx.ACCEL_NORMAL, wx.WXK_F6, self._id_f6),
            (wx.ACCEL_NORMAL, wx.WXK_F8, self._id_f8),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("E"), self._open_soundboard_id),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("0"), self._stop_effects_id),
        ]
        accelerators.extend(
            (wx.ACCEL_CTRL, ord(str(number % 10)), menu_id)
            for number, menu_id in enumerate(self._effect_menu_ids, start=1)
        )
        accelerators.extend(
            (wx.ACCEL_ALT, ord(str((page + 1) % 10)), menu_id)
            for menu_id, page in self._page_menu_ids.items()
        )
        accelerator = wx.AcceleratorTable(accelerators)
        self.SetAcceleratorTable(accelerator)
        self.Bind(wx.EVT_MENU, self._on_refresh, id=wx.ID_REFRESH)
        self.Bind(wx.EVT_MENU, lambda _e: self.soundboard_panel.play_index(0), id=self._id_f2)
        self.Bind(wx.EVT_MENU, lambda _e: self.soundboard_panel.play_index(1), id=self._id_f3)
        self.Bind(wx.EVT_MENU, lambda _e: self.soundboard_panel.play_index(2), id=self._id_f4)
        self.Bind(wx.EVT_MENU, self._on_browse_soundboard_file, id=self._id_f6)
        self.Bind(wx.EVT_MENU, lambda _e: self.recording_panel._on_toggle_record(), id=self._id_f8)
        self.Bind(
            wx.EVT_MENU,
            self._on_open_soundboard,
            id=self._open_soundboard_id,
        )
        self.Bind(wx.EVT_MENU, self._on_stop_effects, id=self._stop_effects_id)
        self.Bind(wx.EVT_MENU, self._on_project_help, id=self._project_help_id)
        self.Bind(wx.EVT_MENU, self._on_hotkey_settings, id=self._hotkeys_id)
        self.Bind(wx.EVT_MENU, self._on_save_profile, id=self._save_profile_id)
        self.Bind(wx.EVT_MENU, self._on_load_profile, id=self._load_profile_id)
        self.Bind(wx.EVT_MENU, self._on_delete_profile, id=self._delete_profile_id)
        self.Bind(wx.EVT_MENU, self._on_export_backup, id=self._export_id)
        self.Bind(wx.EVT_MENU, self._on_import_backup, id=self._import_id)
        self.Bind(wx.EVT_MENU, self._on_feedback_toggle, id=self._feedback_id)
        self.Bind(wx.EVT_MENU, self._on_diagnostic, id=self._diagnostic_id)
        self.Bind(
            wx.EVT_MENU,
            self._on_check_for_updates,
            id=self._check_updates_id,
        )
        self.Bind(wx.EVT_ICONIZE, self._on_iconize)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._tray_icon = SystemTrayIcon(self)

        self._level_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_level_timer, self._level_timer)
        self._level_timer.Start(300)
        self._apply_global_hotkeys(show_error=False)

        self._refresh_devices()
        self._refresh_processes()
        self.Centre()
        self.input_choice.SetFocus()
        if not self.preferences.welcome_shown or self.preferences.last_seen_news_version != __version__:
            wx.CallAfter(self._show_startup_information)
        elif can_self_update():
            wx.CallLater(3000, self._start_update_check, False)

    def _focus_control(self, control: wx.Window) -> None:
        """Reveal a shortcut's page before focusing its native control."""
        for index in range(self.notebook.GetPageCount()):
            page = self.notebook.GetPage(index)
            if page is control or page.IsDescendant(control):
                self.notebook.SetSelection(index)
                break
        if control.IsEnabled():
            control.SetFocus()
        else:
            self.notebook.SetFocus()

    def _on_navigation_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if event.ControlDown() and not event.AltDown() and key == wx.WXK_TAB:
            step = -1 if event.ShiftDown() else 1
            index = (self.notebook.GetSelection() + step) % self.notebook.GetPageCount()
            self.notebook.SetSelection(index)
            self.notebook.SetFocus()
            return
        if event.AltDown() and not event.ControlDown() and not event.ShiftDown():
            shortcuts = {
                ord("M"): self.input_choice,
                ord("S"): self.output_choice,
                ord("O"): self.monitor_checkbox,
                ord("T"): self.monitor_choice,
                ord("E"): self.reverb_checkbox,
                ord("R"): self.reverb_level,
                ord("D"): self.noise_reduction_checkbox,
                ord("P"): self.spatial_checkbox,
                ord("X"): self.spatial_x,
                ord("Y"): self.spatial_y,
                ord("Z"): self.spatial_z,
                ord("U"): self.spatial_automatic,
                ord("V"): self.spatial_speed,
            }
            control = shortcuts.get(key)
            if control is not None:
                self._focus_control(control)
                if isinstance(control, EffectToggleButton):
                    control.Activate()
                return
            if key == ord("A"):
                self._on_toggle(event)
                return
            if key == ord("C"):
                self._on_exit(event)
                return
        event.Skip()

    def _on_check_for_updates(self, _event: wx.Event) -> None:
        self._start_update_check(True)

    def _on_project_help(self, _event: wx.Event) -> None:
        dialog = HelpDialog(self)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()

    def _on_open_soundboard(self, _event: wx.Event) -> None:
        self._focus_control(self.soundboard_panel.page_choice)

    def _update_page_menu_labels(self) -> None:
        for identifier, page in self._page_menu_ids.items():
            item = self.GetMenuBar().FindItemById(identifier)
            if item is not None:
                item.SetItemLabel(
                    f"{self.soundboard_panel._page_names[page]}\tAlt+{(page + 1) % 10}"
                )

    def stop_sound_effects(self) -> None:
        self.engine.stop_sound_effects()
        self.SetStatusText("Todos os efeitos sonoros foram interrompidos.")

    def _on_stop_effects(self, _event: wx.Event) -> None:
        self.stop_sound_effects()

    def _apply_global_hotkeys(self, *, show_error: bool = True) -> bool:
        try:
            self._global_hotkeys.apply(
                enabled=self.preferences.global_shortcuts_enabled,
                effect_modifier=self.preferences.global_effect_modifier,
                page_modifier=self.preferences.global_page_modifier,
                play=self.soundboard_panel.play_index,
                select_page=lambda page: self.soundboard_panel.select_page(page, focus=False),
                stop=self.stop_sound_effects,
            )
            return True
        except RuntimeError as exc:
            self.preferences = replace(self.preferences, global_shortcuts_enabled=False)
            try:
                self.preferences_store.save(self.preferences)
            except OSError:
                pass
            self.SetStatusText(f"Atalhos globais desativados: {exc}")
            if show_error:
                self._show_error(f"Não foi possível ativar todos os atalhos globais.\n\n{exc}")
            return False

    def _on_hotkey_settings(self, _event: wx.Event) -> None:
        dialog = HotkeySettingsDialog(self, self.preferences)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            enabled, effect_modifier, page_modifier = dialog.values
        finally:
            dialog.Destroy()
        previous = self.preferences
        self.preferences = replace(
            self._current_preferences(),
            global_shortcuts_enabled=enabled,
            global_effect_modifier=effect_modifier,
            global_page_modifier=page_modifier,
        )
        if not self._apply_global_hotkeys():
            return
        try:
            self.preferences_store.save(self.preferences)
        except OSError as exc:
            self.preferences = previous
            self._apply_global_hotkeys(show_error=False)
            self._show_error(f"Não foi possível salvar os atalhos globais.\n\n{exc}")
            return
        self.SetStatusText(
            "Atalhos globais ativados."
            if enabled else "Atalhos globais desativados."
        )

    def _on_save_profile(self, _event: wx.Event) -> None:
        with wx.TextEntryDialog(self, "Nome do perfil:", "Salvar perfil") as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.GetValue().strip()
        if name in self.profile_store.names() and wx.MessageBox(
            f"O perfil '{name}' já existe. Deseja substituí-lo?",
            "Substituir perfil",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        ) != wx.YES:
            return
        try:
            self.profile_store.save(name, self._current_preferences())
        except (OSError, ValueError) as exc:
            self._show_error(f"Não foi possível salvar o perfil.\n\n{exc}")
            return
        self.SetStatusText(f"Perfil salvo: {name}.")

    def _choose_profile(self, title: str) -> str | None:
        names = self.profile_store.names()
        if not names:
            self._show_error("Ainda não há perfis salvos.")
            return None
        with wx.SingleChoiceDialog(self, "Escolha o perfil:", title, names) as dialog:
            return dialog.GetStringSelection() if dialog.ShowModal() == wx.ID_OK else None

    def _on_load_profile(self, _event: wx.Event) -> None:
        name = self._choose_profile("Carregar perfil")
        if name is None:
            return
        try:
            preferences = self.profile_store.load(name, self._current_preferences())
            self._apply_loaded_preferences(preferences)
        except (OSError, KeyError, ValueError) as exc:
            self._show_error(f"Não foi possível carregar o perfil.\n\n{exc}")
            return
        self.SetStatusText(f"Perfil carregado: {name}. Ative a mesa para usar a nova rota.")

    def _on_delete_profile(self, _event: wx.Event) -> None:
        name = self._choose_profile("Excluir perfil")
        if name is None:
            return
        if wx.MessageBox(
            f"Excluir o perfil '{name}'?", "Excluir perfil",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        try:
            self.profile_store.delete(name)
        except (OSError, KeyError) as exc:
            self._show_error(f"Não foi possível excluir o perfil.\n\n{exc}")
            return
        self.SetStatusText(f"Perfil excluído: {name}.")

    def _on_export_backup(self, _event: wx.Event) -> None:
        answer = wx.MessageBox(
            "Deseja incluir cópias dos arquivos de áudio no backup?\n\n"
            "Sim cria um backup portátil. Não salva somente configurações e caminhos.",
            "Exportar backup", wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION, self,
        )
        if answer == wx.CANCEL:
            return
        with wx.FileDialog(
            self, "Salvar backup da Mini Mesa", wildcard="Backup da Mini Mesa (*.mmb)|*.mmb",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            destination = Path(dialog.GetPath()).with_suffix(".mmb")
        try:
            export_backup(self._current_preferences(), destination, include_audio=answer == wx.YES)
        except (OSError, ValueError) as exc:
            self._show_error(f"Não foi possível exportar o backup.\n\n{exc}")
            return
        self.SetStatusText(f"Backup exportado para {destination}.")

    def _on_import_backup(self, _event: wx.Event) -> None:
        with wx.FileDialog(
            self, "Abrir backup da Mini Mesa", wildcard="Backup da Mini Mesa (*.mmb)|*.mmb",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            source = Path(dialog.GetPath())
        try:
            preferences = import_backup(
                source, self.preferences_store.path.parent / "imported-sounds" / source.stem
            )
            preferences = replace(
                preferences,
                welcome_shown=self.preferences.welcome_shown,
                last_seen_news_version=self.preferences.last_seen_news_version,
            )
            self._apply_loaded_preferences(preferences)
        except (OSError, ValueError, KeyError) as exc:
            self._show_error(f"Não foi possível importar o backup.\n\n{exc}")
            return
        self.SetStatusText("Backup importado. Ative a mesa para usar a nova rota.")

    def _on_diagnostic(self, _event: wx.Event) -> None:
        try:
            report = diagnostic_text(self.engine, self._current_preferences())
        except Exception as exc:
            self._show_error(f"Não foi possível gerar o diagnóstico.\n\n{exc}")
            return
        dialog = DiagnosticDialog(self, report)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()

    def _on_feedback_toggle(self, event: wx.CommandEvent) -> None:
        previous = self.preferences
        self.preferences = replace(
            self._current_preferences(), feedback_sounds_enabled=event.IsChecked()
        )
        try:
            self.preferences_store.save(self.preferences)
        except OSError as exc:
            self.preferences = previous
            self._feedback_item.Check(previous.feedback_sounds_enabled)
            self.SetStatusText(f"Não foi possível salvar os avisos sonoros: {exc}")
            return
        self._play_feedback("page")

    def _play_feedback(self, kind: str) -> None:
        if not self.preferences.feedback_sounds_enabled:
            return
        try:
            import winsound
            sound = winsound.MB_OK if kind in {"start", "page"} else winsound.MB_ICONASTERISK
            winsound.MessageBeep(sound)
        except (ImportError, RuntimeError):
            pass

    def _on_level_timer(self, _event: wx.TimerEvent) -> None:
        if not self.engine.is_running:
            state, text = "off", "Mesa desativada."
        else:
            try:
                level = float(self.engine.input_level)
            except (TypeError, ValueError):
                level = 0.0
            if level < 0.006:
                state, text = "silent", "Sem sinal ou muito baixo."
            elif level < 0.04:
                state, text = "low", "Microfone baixo."
            elif level < 0.75:
                state, text = "good", "Nível adequado."
            else:
                state, text = "clip", "Saturando; reduza o ganho do microfone."
        self.input_level_status.ChangeValue(text)
        if state == self._last_level_state:
            self._pending_level_state = ""
            self._pending_level_count = 0
        elif state == self._pending_level_state:
            self._pending_level_count += 1
        else:
            self._pending_level_state = state
            self._pending_level_count = 1
        if self._pending_level_count >= 3:
            self.input_level_status.SetName(f"Nível do microfone: {text}")
            self._last_level_state = state
            self._pending_level_state = ""
            self._pending_level_count = 0
            wx.Accessible.NotifyEvent(
                wx.ACC_EVENT_OBJECT_NAMECHANGE,
                self.input_level_status,
                wx.OBJID_CLIENT,
                0,
            )

    def _start_update_check(self, manual: bool) -> None:
        if self._update_check_in_progress:
            if manual:
                wx.MessageBox(
                    "A verificação já está em andamento.",
                    "Atualizações",
                    wx.OK | wx.ICON_INFORMATION,
                    self,
                )
            return
        self._update_check_in_progress = True
        if manual:
            self.SetStatusText("Verificando atualizações...")
        threading.Thread(
            target=self._update_check_worker,
            args=(manual,),
            name="mini-mesa-update-check",
            daemon=True,
        ).start()

    def _update_check_worker(self, manual: bool) -> None:
        try:
            update = check_for_update()
        except UpdateError as exc:
            wx.CallAfter(self._finish_update_check, manual, None, str(exc))
            return
        except Exception:
            wx.CallAfter(
                self._finish_update_check,
                manual,
                None,
                "Não foi possível verificar as atualizações.",
            )
            return
        wx.CallAfter(self._finish_update_check, manual, update, "")

    def _finish_update_check(
        self,
        manual: bool,
        update: UpdateInfo | None,
        error_message: str,
    ) -> None:
        self._update_check_in_progress = False
        if self.IsBeingDeleted():
            return
        if error_message:
            if manual:
                wx.MessageBox(
                    error_message,
                    "Atualizações",
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                self.SetStatusText("Não foi possível verificar atualizações.")
            return
        if update is None:
            if manual:
                wx.MessageBox(
                    "Você já está usando a versão mais recente.",
                    "Atualizações",
                    wx.OK | wx.ICON_INFORMATION,
                    self,
                )
            self.SetStatusText("A Mini Mesa está atualizada.")
            return

        notes = update.release_notes.strip() or "Consulte as notas da release no GitHub."
        if len(notes) > 1200:
            notes = notes[:1200].rstrip() + "..."
        answer = wx.MessageBox(
            f"A versão {update.latest_version} está disponível.\n\n"
            f"Versão instalada: {update.current_version}.\n\n"
            f"Novidades:\n{notes}\n\n"
            "Deseja baixar e instalar agora?",
            "Atualização disponível",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION,
            self,
        )
        if answer == wx.YES:
            self._start_update_download(update)

    def _start_update_download(self, update: UpdateInfo) -> None:
        self._update_cancel_event = threading.Event()
        self._update_progress_dialog = wx.ProgressDialog(
            "Baixando atualização",
            f"Preparando a versão {update.latest_version}...",
            maximum=1000,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME,
        )
        threading.Thread(
            target=self._update_download_worker,
            args=(update,),
            name="mini-mesa-update-download",
            daemon=True,
        ).start()

    def _update_download_worker(self, update: UpdateInfo) -> None:
        try:
            installer = download_installer(
                update,
                progress_callback=lambda downloaded, total: wx.CallAfter(
                    self._apply_update_progress,
                    downloaded,
                    total,
                ),
                cancel_event=self._update_cancel_event,
            )
        except UpdateCancelled:
            wx.CallAfter(self._finish_update_download, None, "")
            return
        except UpdateError as exc:
            wx.CallAfter(self._finish_update_download, None, str(exc))
            return
        except Exception:
            wx.CallAfter(
                self._finish_update_download,
                None,
                "Não foi possível baixar a atualização.",
            )
            return
        wx.CallAfter(self._finish_update_download, installer, "")

    def _apply_update_progress(self, downloaded: int, total: int) -> None:
        dialog = self._update_progress_dialog
        if dialog is None:
            return
        if total > 0:
            value = max(0, min(1000, int(downloaded * 1000 / total)))
            message = (
                f"Baixando atualização: {downloaded / 1048576:.1f} de "
                f"{total / 1048576:.1f} MB."
            )
            keep_going, _skip = dialog.Update(value, message)
        else:
            keep_going, _skip = dialog.Pulse(
                f"Baixando atualização: {downloaded / 1048576:.1f} MB."
            )
        if not keep_going and self._update_cancel_event is not None:
            self._update_cancel_event.set()

    def _finish_update_download(
        self,
        installer,
        error_message: str,
    ) -> None:
        dialog = self._update_progress_dialog
        self._update_progress_dialog = None
        self._update_cancel_event = None
        if dialog is not None:
            dialog.Destroy()
        if self.IsBeingDeleted():
            return
        if error_message:
            wx.MessageBox(
                error_message,
                "Atualizações",
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return
        if installer is None:
            self.SetStatusText("Download da atualização cancelado.")
            return
        try:
            self._save_preferences()
            self.engine.stop()
            launch_installer(installer)
        except Exception as exc:
            wx.MessageBox(str(exc), "Atualizações", wx.OK | wx.ICON_ERROR, self)
            return
        self.SetStatusText("Atualização baixada; instalando a nova versão...")
        self.Close()

    def _show_startup_information(self) -> None:
        if self.IsBeingDeleted():
            return
        if not self.preferences.welcome_shown:
            self._show_welcome()
        if not self.IsBeingDeleted() and self.preferences.last_seen_news_version != __version__:
            self._on_release_notes(None)
        if not self.IsBeingDeleted() and can_self_update():
            wx.CallLater(3000, self._start_update_check, False)

    def _on_release_notes(self, _event: wx.Event) -> None:
        try:
            text = load_release_notes()
        except (OSError, UnicodeError) as exc:
            self._show_error(f"Não foi possível abrir as novidades desta versão.\n\n{exc}")
            return
        dialog = ReleaseNotesDialog(self, text)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()
        preferences = replace(self._current_preferences(), last_seen_news_version=__version__)
        try:
            self.preferences_store.save(preferences)
        except OSError as exc:
            self.SetStatusText(f"Não foi possível registrar a leitura das novidades: {exc}")
            return
        self.preferences = preferences

    def _show_welcome(self) -> None:
        if self.IsBeingDeleted() or self.preferences.welcome_shown:
            return
        wx.MessageBox(
            "Bem-vindo à Mini Mesa de Som!\n\n"
            "Este programa recebe o áudio do seu microfone, aplica efeitos em "
            "tempo real e envia o resultado para um cabo de áudio virtual. "
            "Assim, você pode usar reverb no TeamTalk, Discord, WhatsApp ou em "
            "outro aplicativo de conversa.\n\n"
            "Para começar:\n"
            "1. Escolha seu microfone físico.\n"
            "2. Escolha a reprodução do cabo como saída virtual, por exemplo "
            "CABLE Input ou Line 1.\n"
            "3. No aplicativo de conversa, escolha a gravação do mesmo cabo "
            "como microfone, por exemplo CABLE Output ou Line 1.\n"
            "4. Ajuste os efeitos e pressione Ativar mesa.\n\n"
            "Para ouvir sua própria voz, ative Ouvir retorno e use fones de "
            "ouvido para evitar microfonia. Faça um teste de gravação no "
            "aplicativo de conversa antes de entrar em uma chamada. Todos os "
            "controles podem ser operados pelo teclado e são compatíveis com "
            "leitores de tela.\n\n"
            "A qualquer momento, pressione F1 para conhecer melhor o projeto, "
            "consultar todos os atalhos e ler os créditos do programa.",
            "Bem-vindo à Mini Mesa de Som",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )
        self.preferences = replace(self._current_preferences(), welcome_shown=True)
        try:
            self.preferences_store.save(self.preferences)
        except OSError as exc:
            self.SetStatusText(f"Não foi possível salvar as preferências: {exc}")

    def _on_refresh(self, _event: wx.Event) -> None:
        self._refresh_devices()
        self._refresh_processes()

    @staticmethod
    def _format_process_item_label(item: ProcessItem, is_checked: bool) -> str:
        state = "marcado" if is_checked else "desmarcado"
        return f"{item.label}, {state}"

    def _on_refresh_processes(self, _event: wx.Event) -> None:
        self._refresh_processes()

    def _on_process_selection_changed(self, event: wx.Event) -> None:
        self._save_preferences()
        index = event.GetSelection()
        if 0 <= index < len(self._process_items):
            item = self._process_items[index]
            is_checked = self.process_list.IsChecked(index)
            new_label = self._format_process_item_label(item, is_checked)
            set_string = getattr(self.process_list, "SetString", None)
            if set_string is not None:
                set_string(index, new_label)
            check = getattr(self.process_list, "Check", None)
            if check is not None:
                check(index, is_checked)
            state = "marcado" if is_checked else "desmarcado"
            message = f"{item.label}: {state} para transmissão."
        else:
            message = "A seleção de programas foi atualizada."
        if self.engine.is_running:
            updater = getattr(self.engine, "update_transmitted_processes", None)
            if updater is None:
                message += " A alteração será aplicada ao reativar a mesa."
            else:
                try:
                    updater(self._selected_process_pids())
                except Exception as exc:
                    message += f" Não foi possível aplicar agora: {exc}"
                else:
                    message += " Alteração aplicada agora."
        self.SetStatusText(message)
        event.Skip()

    def _on_native_volume_changed(self, event: wx.Event) -> None:
        setter = getattr(self.engine, "set_volumes", None)
        if setter is not None:
            setter(self.microphone_volume.GetValue() / 100.0, self.process_volume.GetValue() / 100.0)
        self._save_preferences()
        event.Skip()

    def _refresh_processes(self) -> None:
        selected = (
            set(self._selected_process_pids())
            or set(self.preferences.transmitted_processes)
        )
        self._process_items = list_candidate_processes()
        labels = [
            self._format_process_item_label(item, item.pid in selected)
            for item in self._process_items
        ]
        self.process_list.Set(labels)
        for index, item in enumerate(self._process_items):
            self.process_list.Check(index, item.pid in selected)

    def _selected_process_pids(self) -> tuple[int, ...]:
        return tuple(
            self._process_items[index].pid
            for index in self.process_list.GetCheckedItems()
            if 0 <= index < len(self._process_items)
        )

    def _refresh_devices(self) -> None:
        selected_input = (
            self.input_choice.GetStringSelection() or self.preferences.input_device
        )
        selected_output = (
            self.output_choice.GetStringSelection() or self.preferences.output_device
        )
        selected_monitor = (
            self.monitor_choice.GetStringSelection() or self.preferences.monitor_device
        )
        try:
            inputs = self.engine.input_devices()
            outputs = self.engine.output_devices()
            monitor_outputs = self.engine.monitor_devices()
        except Exception as exc:
            self._show_error(f"Não foi possível listar os dispositivos de áudio.\n\n{exc}")
            return

        self._replace_choices(
            self.input_choice,
            inputs,
            selected_input,
            prefer_physical_input=True,
        )
        self._replace_choices(
            self.output_choice,
            outputs,
            selected_output,
            prefer_virtual=True,
        )
        self._replace_choices(
            self.monitor_choice,
            monitor_outputs,
            selected_monitor,
            prefer_physical_output=True,
        )
        self.SetStatusText(
            f"{len(inputs)} entradas, {len(outputs)} saídas e "
            f"{len(monitor_outputs)} retornos compatíveis encontrados."
        )

    @staticmethod
    def _replace_choices(
        choice: wx.Choice,
        values: tuple[str, ...],
        previous: str,
        *,
        prefer_physical_input: bool = False,
        prefer_physical_output: bool = False,
        prefer_virtual: bool = False,
    ) -> None:
        choice.Set(values)
        matched_previous = match_device_label(
            previous,
            values,
            output=prefer_virtual or prefer_physical_output,
        )
        if matched_previous is not None:
            choice.SetStringSelection(matched_previous)
        elif prefer_physical_input:
            preferred = next(
                (
                    value
                    for value in values
                    if "microfone" in value.casefold()
                    and "virtual" not in value.casefold()
                ),
                None,
            )
            if preferred is not None:
                choice.SetStringSelection(preferred)
            elif values:
                choice.SetSelection(0)
        elif prefer_physical_output:
            preferred = next(
                (
                    value
                    for value in values
                    if "virtual" not in value.casefold()
                    and (
                        "alto-falantes" in value.casefold()
                        or "fone" in value.casefold()
                        or "headphone" in value.casefold()
                    )
                ),
                None,
            )
            if preferred is not None:
                choice.SetStringSelection(preferred)
            elif values:
                choice.SetSelection(0)
        elif prefer_virtual:
            preferred = next(
                (
                    value
                    for value in values
                    if "virtual cable" in value.casefold()
                    or "virtual audio cable" in value.casefold()
                ),
                None,
            )
            if preferred is not None:
                choice.SetStringSelection(preferred)
            elif values:
                choice.SetSelection(0)
        elif values:
            choice.SetSelection(0)

    def _current_settings(self) -> ReverbSettings:
        return ReverbSettings(
            level_percent=self.reverb_level.GetValue(),
            enabled=self.reverb_checkbox.GetValue(),
        )

    @property
    def soundboard_settings(self) -> SoundboardSettings:
        return self._soundboard_settings

    def _current_preferences(self) -> AppPreferences:
        voice_preset = _VOICE_PRESETS[self.voice_preset_choice.GetSelection()][0]
        preset = _STYLE_PRESETS[self.creative_choice.GetSelection()][0]
        return AppPreferences(
            welcome_shown=self.preferences.welcome_shown,
            last_seen_news_version=self.preferences.last_seen_news_version,
            input_device=self.input_choice.GetStringSelection(),
            output_device=self.output_choice.GetStringSelection(),
            transmitted_processes=self._selected_process_pids(),
            microphone_volume_percent=self.microphone_volume.GetValue(),
            process_volume_percent=self.process_volume.GetValue(),
            monitor_enabled=self.monitor_checkbox.GetValue(),
            monitor_device=self.monitor_choice.GetStringSelection(),
            reverb_enabled=self.reverb_checkbox.GetValue(),
            reverb_level=self.reverb_level.GetValue(),
            noise_reduction_enabled=self.noise_reduction_checkbox.GetValue(),
            spatial_enabled=self.spatial_checkbox.GetValue(),
            spatial_x=self.spatial_x.GetValue(),
            spatial_y=self.spatial_y.GetValue(),
            spatial_z=self.spatial_z.GetValue(),
            spatial_automatic=self.spatial_automatic.GetValue(),
            spatial_speed=self.spatial_speed.GetValue(),
            voice_enabled=self.voice_checkbox.GetValue(),
            voice_preset=voice_preset,
            voice_pitch_semitones=float(self.voice_pitch.GetValue()),
            creative_effect_preset=preset,
            modulation_effect=_MODULATIONS[self.modulation_choice.GetSelection()][0],
            ambience_preset=_AMBIENCES[self.ambience_choice.GetSelection()][0],
            delay_enabled=self.delay_checkbox.GetValue(),
            delay_level_percent=self.delay_level.GetValue(),
            style_intensity_percent=self.style_intensity.GetValue(),
            modulation_intensity_percent=self.modulation_intensity.GetValue(),
            ambience_intensity_percent=self.ambience_intensity.GetValue(),
            roger_beep_enabled=self.roger_beep_checkbox.GetValue(),
            compressor_enabled=self.compressor_checkbox.GetValue(),
            eq_enabled=self.eq_checkbox.GetValue(),
            eq_low_db=float(self.eq_low.GetValue()),
            eq_mid_db=float(self.eq_mid.GetValue()),
            eq_high_db=float(self.eq_high.GetValue()),
            noise_gate_enabled=self.noise_gate_checkbox.GetValue(),
            deesser_enabled=self.deesser_checkbox.GetValue(),
            expander_enabled=self.expander_checkbox.GetValue(),
            auto_gain_enabled=self.auto_gain_checkbox.GetValue(),
            plosive_filter_enabled=self.plosive_checkbox.GetValue(),
            personal_sounds=tuple(self.soundboard_panel._all_effects),
            selected_sound_page=self.soundboard_panel._page,
            sound_page_names=tuple(self.soundboard_panel._page_names),
            global_shortcuts_enabled=self.preferences.global_shortcuts_enabled,
            global_effect_modifier=self.preferences.global_effect_modifier,
            global_page_modifier=self.preferences.global_page_modifier,
            feedback_sounds_enabled=self.preferences.feedback_sounds_enabled,
            soundboard_volume_percent=self._soundboard_settings.volume_percent,
            soundboard_ducking_enabled=self._soundboard_settings.ducking_enabled,
            soundboard_ducking_percent=self._soundboard_settings.ducking_percent,
            recording_format=self.recording_panel._current_settings().format,
            recording_bitrate_kbps=self.recording_panel._current_settings().bitrate_kbps,
            recording_mode=self.recording_panel._current_settings().mode,
            recording_custom_filename=self.recording_panel.filename_ctrl.GetValue().strip(),
            recording_folder=self.recording_panel.folder_ctrl.GetValue().strip(),
        )

    def _apply_loaded_preferences(self, preferences: AppPreferences) -> None:
        if self.engine.is_running:
            self.engine.stop()
        self.preferences = preferences
        self._refresh_devices()
        self._refresh_processes()
        self.monitor_checkbox.SetValue(preferences.monitor_enabled)
        self.microphone_volume.SetValue(preferences.microphone_volume_percent)
        self.process_volume.SetValue(preferences.process_volume_percent)
        self.reverb_checkbox.SetValue(preferences.reverb_enabled)
        self.reverb_level.SetValue(preferences.reverb_level)
        self.reverb_level.Enable(preferences.reverb_enabled)
        self.noise_reduction_checkbox.SetValue(preferences.noise_reduction_enabled)
        self.spatial_checkbox.SetValue(preferences.spatial_enabled)
        self.spatial_x.SetValue(preferences.spatial_x)
        self.spatial_y.SetValue(preferences.spatial_y)
        self.spatial_z.SetValue(preferences.spatial_z)
        self.spatial_automatic.SetValue(preferences.spatial_automatic)
        self.spatial_speed.SetValue(preferences.spatial_speed)
        self._set_spatial_controls_enabled()
        self.voice_checkbox.SetValue(preferences.voice_enabled)
        self.voice_preset_choice.SetSelection(next(
            index for index, item in enumerate(_VOICE_PRESETS) if item[0] == preferences.voice_preset
        ))
        self.voice_pitch.SetValue(round(preferences.voice_pitch_semitones))
        self._update_voice_controls()
        self.creative_choice.SetSelection(next(
            index for index, item in enumerate(_STYLE_PRESETS)
            if item[0] == preferences.creative_effect_preset
        ))
        self.modulation_choice.SetSelection(next(
            index for index, item in enumerate(_MODULATIONS)
            if item[0] == preferences.modulation_effect
        ))
        self.ambience_choice.SetSelection(next(
            index for index, item in enumerate(_AMBIENCES)
            if item[0] == preferences.ambience_preset
        ))
        self.delay_checkbox.SetValue(preferences.delay_enabled)
        self.delay_level.SetValue(preferences.delay_level_percent)
        self.style_intensity.SetValue(preferences.style_intensity_percent)
        self.modulation_intensity.SetValue(preferences.modulation_intensity_percent)
        self.ambience_intensity.SetValue(preferences.ambience_intensity_percent)
        self.roger_beep_checkbox.SetValue(preferences.roger_beep_enabled)
        self._update_creative_controls()
        for control, value in (
            (self.compressor_checkbox, preferences.compressor_enabled),
            (self.eq_checkbox, preferences.eq_enabled),
            (self.noise_gate_checkbox, preferences.noise_gate_enabled),
            (self.deesser_checkbox, preferences.deesser_enabled),
            (self.expander_checkbox, preferences.expander_enabled),
            (self.auto_gain_checkbox, preferences.auto_gain_enabled),
            (self.plosive_checkbox, preferences.plosive_filter_enabled),
        ):
            control.SetValue(value)
        self.eq_low.SetValue(round(preferences.eq_low_db))
        self.eq_mid.SetValue(round(preferences.eq_mid_db))
        self.eq_high.SetValue(round(preferences.eq_high_db))
        for control in (self.eq_low, self.eq_mid, self.eq_high):
            control.Enable(preferences.eq_enabled)
        self._soundboard_settings = SoundboardSettings(
            volume_percent=preferences.soundboard_volume_percent,
            ducking_enabled=preferences.soundboard_ducking_enabled,
            ducking_percent=preferences.soundboard_ducking_percent,
        )
        soundboard = self.soundboard_panel
        soundboard._all_effects = list(preferences.personal_sounds)
        soundboard._page_names = list(preferences.sound_page_names)
        soundboard.page_choice.Set(soundboard._page_names)
        soundboard._page = preferences.selected_sound_page
        soundboard.page_choice.SetSelection(soundboard._page)
        soundboard._effects = [
            sound for sound in soundboard._all_effects if sound.page == soundboard._page
        ]
        soundboard.search.ChangeValue("")
        soundboard.volume.SetValue(preferences.soundboard_volume_percent)
        soundboard.ducking.SetValue(preferences.soundboard_ducking_enabled)
        soundboard.ducking_amount.SetValue(preferences.soundboard_ducking_percent)
        soundboard.ducking_amount.Enable(preferences.soundboard_ducking_enabled)
        soundboard._refresh_effects()
        self._update_page_menu_labels()
        self._feedback_item.Check(preferences.feedback_sounds_enabled)
        rec_fmt_index = {"mp3": 0, "wav": 1, "ogg": 2}.get(preferences.recording_format, 0)
        self.recording_panel.format_choice.SetSelection(rec_fmt_index)
        rec_bitrate_index = {128: 0, 160: 1, 192: 2, 256: 3, 320: 4}.get(preferences.recording_bitrate_kbps, 2)
        self.recording_panel.bitrate_choice.SetSelection(rec_bitrate_index)
        rec_mode_index = {"both": 0, "voice": 1, "processes": 2}.get(preferences.recording_mode, 0)
        self.recording_panel.mode_choice.SetSelection(rec_mode_index)
        self.recording_panel.filename_ctrl.ChangeValue(preferences.recording_custom_filename)
        self.recording_panel.folder_ctrl.ChangeValue(
            preferences.recording_folder or str(default_recordings_directory())
        )
        self.recording_panel._update_bitrate_enabled_state()
        self.preferences_store.save(preferences)
        self._apply_global_hotkeys()
        self._set_routing_controls_enabled(True)
        self._set_toggle_button_label("&Ativar mesa")
        self.status.ChangeValue("Desativado. Perfil ou backup aplicado.")

    def _current_pro_audio_settings(self) -> ProAudioSettings:
        return ProAudioSettings(
            compressor_enabled=self.compressor_checkbox.GetValue(),
            eq_enabled=self.eq_checkbox.GetValue(),
            eq_low_db=float(self.eq_low.GetValue()),
            eq_mid_db=float(self.eq_mid.GetValue()),
            eq_high_db=float(self.eq_high.GetValue()),
            noise_gate_enabled=self.noise_gate_checkbox.GetValue(),
            deesser_enabled=self.deesser_checkbox.GetValue(),
            expander_enabled=self.expander_checkbox.GetValue(),
            auto_gain_enabled=self.auto_gain_checkbox.GetValue(),
            plosive_filter_enabled=self.plosive_checkbox.GetValue(),
        )

    def _current_voice_settings(self) -> VoiceSettings:
        return VoiceSettings(
            enabled=self.voice_checkbox.GetValue(),
            preset=_VOICE_PRESETS[self.voice_preset_choice.GetSelection()][0],
            pitch_semitones=float(self.voice_pitch.GetValue()),
        )

    def _current_creative_settings(self) -> CreativeEffectSettings:
        return CreativeEffectSettings(
            preset=_STYLE_PRESETS[self.creative_choice.GetSelection()][0],
            modulation=_MODULATIONS[self.modulation_choice.GetSelection()][0],
            ambience=_AMBIENCES[self.ambience_choice.GetSelection()][0],
            delay_enabled=self.delay_checkbox.GetValue(),
            delay_level_percent=self.delay_level.GetValue(),
            style_intensity_percent=self.style_intensity.GetValue(),
            modulation_intensity_percent=self.modulation_intensity.GetValue(),
            ambience_intensity_percent=self.ambience_intensity.GetValue(),
            roger_beep_enabled=self.roger_beep_checkbox.GetValue(),
        )

    def _current_spatial_settings(self) -> SpatialSettings:
        return SpatialSettings(
            enabled=self.spatial_checkbox.GetValue(),
            x=self.spatial_x.GetValue(),
            y=self.spatial_y.GetValue(),
            z=self.spatial_z.GetValue(),
            automatic=self.spatial_automatic.GetValue(),
            speed_percent=self.spatial_speed.GetValue(),
        )

    def _save_preferences(self) -> None:
        self.preferences = self._current_preferences()
        try:
            self.preferences_store.save(self.preferences)
        except OSError as exc:
            self.SetStatusText(f"Não foi possível salvar as preferências: {exc}")

    def _on_preference_changed(self, event: wx.Event) -> None:
        previous_monitor = self._saved_monitor_output()
        previous_effects_output = self.preferences.monitor_device
        self._save_preferences()
        if event.GetEventObject() is self.monitor_choice and self.engine.is_running:
            self._update_running_monitor(previous_monitor, previous_effects_output)
        event.Skip()

    def _on_voice_changed(self, event: wx.Event) -> None:
        if event.GetEventObject() is self.voice_pitch:
            self.voice_preset_choice.SetSelection(len(_VOICE_PRESETS) - 1)
        self._update_voice_controls()
        try:
            if self.engine.is_running:
                self.engine.update_voice_settings(self._current_voice_settings())
                self._show_running_state()
            self._save_preferences()
        except Exception as exc:
            self._show_error(f"Não foi possível alterar o efeito de voz.\n\n{exc}")

    def _update_voice_controls(self) -> None:
        enabled = self.voice_checkbox.GetValue()
        self.voice_preset_choice.Enable(enabled)
        self.voice_pitch.Enable(enabled)

    def _update_creative_controls(self) -> None:
        self.delay_level.Enable(self.delay_checkbox.GetValue())

    def _on_voice_preset_selected(self, _event: wx.Event) -> None:
        selection = self.voice_preset_choice.GetSelection()
        pitch = _VOICE_PRESETS[selection][2]
        if pitch is not None:
            self.voice_pitch.SetValue(pitch)
        self._on_voice_changed(_event)

    def _apply_creative_settings(self) -> None:
        self._update_creative_controls()
        try:
            if self.engine.is_running:
                self.engine.update_creative_settings(
                    self._current_creative_settings()
                )
                self._show_running_state()
            self._save_preferences()
        except Exception as exc:
            self._show_error(f"Não foi possível alterar os efeitos.\n\n{exc}")

    def _queue_creative_update(self) -> None:
        """Read native Choice values after Windows commits their selection."""

        if self._creative_update_queued:
            return
        self._creative_update_queued = True
        wx.CallAfter(self._apply_queued_creative_settings)

    def _apply_queued_creative_settings(self) -> None:
        self._creative_update_queued = False
        self._apply_creative_settings()

    def _on_creative_choice_changed(self, event: wx.Event) -> None:
        event.Skip()
        self._queue_creative_update()

    def _on_creative_choice_key_up(self, event: wx.KeyEvent) -> None:
        # wx.Choice can postpone EVT_CHOICE while its native popup remains open.
        # A deferred keyboard preview makes arrows immediately audible and the
        # regular choice event coalesces into the same update.
        event.Skip()
        if event.GetKeyCode() in {
            wx.WXK_UP,
            wx.WXK_DOWN,
            wx.WXK_HOME,
            wx.WXK_END,
            wx.WXK_PAGEUP,
            wx.WXK_PAGEDOWN,
            wx.WXK_RETURN,
            wx.WXK_NUMPAD_ENTER,
        }:
            self._queue_creative_update()

    def _on_creative_changed(self, event: wx.Event) -> None:
        self._apply_creative_settings()
        event.Skip()

    def _on_pro_audio_changed(self, _event: wx.Event) -> None:
        eq_enabled = self.eq_checkbox.GetValue()
        self.eq_low.Enable(eq_enabled)
        self.eq_mid.Enable(eq_enabled)
        self.eq_high.Enable(eq_enabled)
        try:
            if self.engine.is_running:
                self.engine.update_pro_audio_settings(
                    self._current_pro_audio_settings()
                )
                self._show_running_state()
            self._save_preferences()
        except Exception as exc:
            self._show_error(
                f"Não foi possível alterar os efeitos profissionais.\n\n{exc}"
            )

    def update_soundboard_settings(self, settings: SoundboardSettings) -> None:
        try:
            self.engine.update_soundboard_settings(settings)
            self._soundboard_settings = settings
            self._save_preferences()
        except Exception as exc:
            self._show_error(
                f"Não foi possível alterar o volume das vinhetas.\n\n{exc}"
            )
            return
        if self.engine.is_running:
            self.SetStatusText(
                f"Volume das vinhetas atualizado para "
                f"{settings.volume_percent} por cento."
            )

    def _on_browse_soundboard_file(self, event: wx.Event) -> None:
        self._focus_control(self.soundboard_panel.add_button)
        self.soundboard_panel._on_add(event)

    def play_personal_sound(self, sound: PersonalSound) -> None:
        if not self.engine.is_running:
            self._show_error("Ative a mesa antes de reproduzir os efeitos.")
            return
        self.SetStatusText(f"Carregando efeito: {sound.name}.")
        threading.Thread(
            target=self._custom_sound_worker,
            args=(sound,),
            name="mini-mesa-soundboard-load",
            daemon=True,
        ).start()

    def preview_personal_sound(self, sound: PersonalSound) -> None:
        output = self.monitor_choice.GetStringSelection()
        if not output:
            self._show_error("Escolha um dispositivo de retorno para ouvir a prévia.")
            return
        self.SetStatusText(f"Carregando prévia: {sound.name}.")

        def worker() -> None:
            try:
                self.engine.preview_sound(sound.path, output)
            except Exception as exc:
                wx.CallAfter(self._show_error, f"Não foi possível ouvir a prévia.\n\n{exc}")
                return
            wx.CallAfter(self.SetStatusText, f"Reproduzindo prévia: {sound.name}.")

        threading.Thread(
            target=worker,
            name="mini-mesa-sound-preview",
            daemon=True,
        ).start()

    def _custom_sound_worker(self, sound: PersonalSound) -> None:
        try:
            played = self.engine.play_sound(sound.path)
        except Exception:
            played = False
        wx.CallAfter(self._finish_custom_sound, sound, played)

    def _finish_custom_sound(self, sound: PersonalSound, played: bool) -> None:
        if self.IsBeingDeleted():
            return
        if played:
            self.SetStatusText(f"Reproduzindo efeito: {sound.name}.")
        else:
            self._show_error(
                f"Não foi possível reproduzir '{sound.name}'. "
                "Verifique se a mesa está ativa e se o arquivo ainda existe e é válido. "
                "Use Substituir arquivo para escolher outro áudio.\n\n"
                f"Arquivo: {sound.path}"
            )

    def _on_monitor_toggled(self, _event: wx.Event) -> None:
        previous_monitor = self._saved_monitor_output()
        previous_effects_output = self.preferences.monitor_device
        enabled = self.monitor_checkbox.GetValue()
        self.monitor_choice.Enable()
        self._save_preferences()
        if self.engine.is_running:
            self._update_running_monitor(previous_monitor, previous_effects_output)
            return
        self.SetStatusText(
            "Retorno experimental ativado; a saída virtual permanece isolada."
            if enabled
            else "Retorno da voz desativado. Os efeitos continuam audíveis no dispositivo de retorno."
        )

    def _set_routing_controls_enabled(self, enabled: bool) -> None:
        self.input_choice.Enable(enabled)
        self.output_choice.Enable(enabled)
        self.monitor_checkbox.Enable()
        self.monitor_choice.Enable()
        self.refresh_button.Enable(enabled)
        # Process capture can be replaced while the route is active, so keep
        # this list available to add or remove transmitted programs live.
        self.process_list.Enable()
        self.refresh_processes_button.Enable()
        self.noise_reduction_checkbox.Enable()

    def _selected_monitor_output(self) -> str | None:
        if not self.monitor_checkbox.GetValue():
            return None
        selected = self.monitor_choice.GetStringSelection()
        if not selected:
            raise ValueError("Selecione um dispositivo para ouvir o retorno.")
        return selected

    def _saved_monitor_output(self) -> str | None:
        if not self.preferences.monitor_enabled:
            return None
        return self.preferences.monitor_device or None

    def _start_selected_route(self) -> None:
        setter = getattr(self.engine, "set_volumes", None)
        if setter is not None:
            setter(self.microphone_volume.GetValue() / 100.0, self.process_volume.GetValue() / 100.0)
        self.engine.update_noise_reduction(
            self.noise_reduction_checkbox.GetValue()
        )
        self.engine.update_settings(self._current_settings())
        self.engine.update_voice_settings(self._current_voice_settings())
        self.engine.update_creative_settings(self._current_creative_settings())
        self.engine.update_pro_audio_settings(self._current_pro_audio_settings())
        self.engine.update_soundboard_settings(self._soundboard_settings)
        self.engine.update_spatial(self._current_spatial_settings())
        process_pids = self._selected_process_pids()
        start_options = {
            "effects_output": self.monitor_choice.GetStringSelection() or None,
        }
        if process_pids:
            start_options["process_pids"] = process_pids
        self.engine.start(
            self.input_choice.GetStringSelection(),
            self.output_choice.GetStringSelection(),
            self._selected_monitor_output(),
            **start_options,
        )

    def _show_running_state(self) -> None:
        monitoring = self.monitor_checkbox.GetValue()
        effects = []
        if self.noise_reduction_checkbox.GetValue():
            effects.append("redução de ruído")
        if self.reverb_checkbox.GetValue():
            effects.append("reverb")
        if self.spatial_checkbox.GetValue():
            if self.spatial_automatic.GetValue():
                effects.append(
                    f"áudio espacial automático em velocidade "
                    f"{self.spatial_speed.GetValue()}"
                )
            else:
                effects.append(
                    "áudio espacial em "
                    f"X {self.spatial_x.GetValue()}, Y {self.spatial_y.GetValue()}, "
                    f"Z {self.spatial_z.GetValue()}"
                )
        if self.voice_checkbox.GetValue():
            effects.append(self.voice_preset_choice.GetStringSelection())
        if self.creative_choice.GetSelection() > 0:
            effects.append(self.creative_choice.GetStringSelection())
        if self.modulation_choice.GetSelection() > 0:
            effects.append(self.modulation_choice.GetStringSelection())
        if self.ambience_choice.GetSelection() > 0:
            effects.append(self.ambience_choice.GetStringSelection())
        if self.delay_checkbox.GetValue():
            effects.append("eco")
        if self.compressor_checkbox.GetValue():
            effects.append("compressor")
        if self.eq_checkbox.GetValue():
            effects.append("equalizador")
        for checkbox, name in (
            (self.noise_gate_checkbox, "noise gate"),
            (self.deesser_checkbox, "de-esser"),
            (self.expander_checkbox, "expander"),
            (self.auto_gain_checkbox, "ganho automático"),
            (self.plosive_checkbox, "filtro de plosivas"),
        ):
            if checkbox.GetValue():
                effects.append(name)
        effect_description = " e ".join(effects) if effects else "nenhum efeito"
        self.status.ChangeValue(
            "Mesa ativa. O áudio está sendo enviado para a saída virtual"
            + (" e para o retorno experimental." if monitoring else ".")
            + f" Efeitos ativos: {effect_description}."
        )
        self.SetStatusText(
            f"Mesa ativa com {effect_description}."
            if effects
            else "Mesa ativa sem efeitos."
        )

    def _update_running_monitor(self, previous_monitor: str | None, previous_effects_output: str = "") -> None:
        self.SetStatusText("Atualizando a rota de retorno experimental...")
        try:
            self.engine.update_monitor(
                self._selected_monitor_output(),
                effects_output=self.monitor_choice.GetStringSelection() or None,
            )
        except Exception as exc:
            self.monitor_checkbox.SetValue(previous_monitor is not None)
            if previous_monitor or previous_effects_output:
                self.monitor_choice.SetStringSelection(previous_monitor or previous_effects_output)
            self.monitor_choice.Enable()
            self._save_preferences()
            self._set_routing_controls_enabled(False)
            self._show_running_state()
            self._show_error(
                "Não foi possível alterar o retorno. A mesa e a rota anterior "
                f"continuam funcionando.\n\n{exc}"
            )
            return

        self._set_routing_controls_enabled(False)
        self._show_running_state()

    def _on_settings_changed(self, event: wx.Event) -> None:
        try:
            reverb_enabled = self.reverb_checkbox.GetValue()
            self.reverb_level.Enable(reverb_enabled)
            self.engine.update_settings(self._current_settings())
            self._save_preferences()
            if self.engine.is_running:
                self._show_running_state()
            elif reverb_enabled:
                self.SetStatusText(
                    f"Reverb ativo em {self.reverb_level.GetValue()} por cento."
                )
            else:
                self.SetStatusText("Reverb desativado; a mesa continua funcionando.")
        except Exception as exc:
            self._show_error(f"Não foi possível alterar o reverb.\n\n{exc}")
        event.Skip()

    def _on_noise_reduction_toggled(self, event: wx.Event) -> None:
        enabled = self.noise_reduction_checkbox.GetValue()
        previous_enabled = self.preferences.noise_reduction_enabled
        if not self.engine.is_running:
            self._save_preferences()
            self.SetStatusText(
                "Redução de ruído será ativada junto com a mesa."
                if enabled
                else "Redução de ruído desativada."
            )
            event.Skip()
            return

        self.SetStatusText("Atualizando a redução de ruído...")
        try:
            self.engine.stop()
            self._start_selected_route()
        except Exception as update_error:
            self.noise_reduction_checkbox.SetValue(previous_enabled)
            try:
                self.engine.stop()
                self._start_selected_route()
            except Exception as restore_error:
                self._save_preferences()
                self._set_routing_controls_enabled(True)
                self._set_toggle_button_label("&Ativar mesa")
                self.status.ChangeValue("Desativado após falha ao atualizar efeitos.")
                self._show_error(
                    "Não foi possível alterar a redução de ruído nem restaurar "
                    "a rota anterior.\n\n"
                    f"Falha da alteração: {update_error}\n\n"
                    f"Falha da restauração: {restore_error}"
                )
                event.Skip()
                return

            self._save_preferences()
            self._set_routing_controls_enabled(False)
            self._set_toggle_button_label("Des&ativar mesa")
            self._show_running_state()
            self._show_error(
                "Não foi possível alterar a redução de ruído. "
                "A configuração anterior foi restaurada.\n\n"
                f"{update_error}"
            )
            event.Skip()
            return

        self._save_preferences()
        self._set_routing_controls_enabled(False)
        self._set_toggle_button_label("Des&ativar mesa")
        self._show_running_state()
        event.Skip()

    def _on_spatial_changed(self, event: wx.Event) -> None:
        try:
            enabled = self.spatial_checkbox.GetValue()
            self._set_spatial_controls_enabled()
            settings = self._current_spatial_settings()
            self.engine.update_spatial(settings)
            self._save_preferences()
            if self.engine.is_running:
                self._show_running_state()
            elif enabled:
                if settings.automatic:
                    self.SetStatusText(
                        "Movimento espacial automático preparado em velocidade "
                        f"{settings.speed_percent}."
                    )
                else:
                    self.SetStatusText(
                        f"Áudio espacial preparado em X {settings.x}, "
                        f"Y {settings.y}, Z {settings.z}."
                    )
            else:
                self.SetStatusText("Áudio espacial desativado.")
        except Exception as exc:
            self._show_error(f"Não foi possível alterar o áudio espacial.\n\n{exc}")
        event.Skip()

    def _set_spatial_controls_enabled(self) -> None:
        enabled = self.spatial_checkbox.GetValue()
        automatic = enabled and self.spatial_automatic.GetValue()
        self.spatial_automatic.Enable(enabled)
        self.spatial_speed.Enable(automatic)
        for control in (self.spatial_x, self.spatial_y, self.spatial_z):
            control.Enable(enabled and not automatic)

    def _set_toggle_button_label(self, label: str) -> None:
        self.toggle_button.SetLabel(label)
        _set_button_accessible_name(self.toggle_button)

    def _on_toggle(self, _event: wx.Event) -> None:
        if self.engine.is_running:
            try:
                self.engine.stop()
            except Exception as exc:
                self._show_error(f"Não foi possível desativar a mesa.\n\n{exc}")
                return
            self._set_routing_controls_enabled(True)
            self._set_toggle_button_label("&Ativar mesa")
            self.status.ChangeValue("Desativado.")
            self.SetStatusText("Mesa desativada.")
            self._play_feedback("stop")
            return

        try:
            self._start_selected_route()
        except Exception as exc:
            self._show_error(str(exc))
            return

        self._save_preferences()
        self._set_routing_controls_enabled(False)
        self._set_toggle_button_label("Des&ativar mesa")
        self._show_running_state()
        self._play_feedback("start")

    def _on_exit(self, _event: wx.Event) -> None:
        self.Close()

    def _on_iconize(self, event: wx.IconizeEvent) -> None:
        self._minimize_generation += 1
        if event.IsIconized():
            focused = wx.Window.FindFocus()
            if focused is not None and self.IsDescendant(focused):
                self._last_focused_control = focused
            if self._tray_icon is not None and self._tray_icon.is_available:
                wx.CallAfter(self._hide_to_tray, self._minimize_generation)
        event.Skip()

    def _hide_to_tray(self, generation: int) -> None:
        # An older minimize callback must never hide a newly restored window.
        if (
            self.IsBeingDeleted()
            or generation != self._minimize_generation
            or not self.IsIconized()
            or not self.IsShown()
            or self._tray_icon is None
            or not self._tray_icon.is_available
        ):
            return
        self.Hide()
        self._tray_icon.notify_minimized()

    def restore_from_tray(self) -> None:
        if self.IsBeingDeleted():
            return
        self._minimize_generation += 1
        self.Show()
        self.Iconize(False)
        self.Raise()
        wx.CallAfter(self._restore_focus)

    def _restore_focus(self) -> None:
        if self.IsBeingDeleted() or self.IsIconized() or not self.IsShown():
            return
        focused = self._last_focused_control
        if focused is not None and not focused.IsBeingDeleted():
            focused.SetFocus()
        else:
            self.input_choice.SetFocus()

    def exit_from_tray(self) -> None:
        if not self.IsBeingDeleted():
            self.Close()

    def _on_audio_error(self, message: str) -> None:
        wx.CallAfter(self._handle_audio_error, message)

    def _handle_audio_error(self, message: str) -> None:
        if self.IsBeingDeleted():
            return
        if not self.IsShown() or self.IsIconized():
            self.restore_from_tray()
        self._set_routing_controls_enabled(True)
        self._set_toggle_button_label("&Ativar mesa")
        self._refresh_devices()
        self.status.ChangeValue("Desativado após uma falha no dispositivo.")
        self.SetStatusText(
            "Mesa desativada; os dispositivos foram detectados novamente."
        )
        self._show_error(f"O processamento de áudio foi interrompido.\n\n{message}")

    def _show_error(self, message: str) -> None:
        wx.MessageBox(message, "Mini Mesa de Som", wx.OK | wx.ICON_ERROR, self)

    def _on_close(self, event: wx.CloseEvent) -> None:
        if self._update_cancel_event is not None:
            self._update_cancel_event.set()
        self._save_preferences()
        self._level_timer.Stop()
        self._global_hotkeys.close()
        try:
            self.engine.stop()
        except Exception:
            # The stream has already received its stop signal. Do not trap the
            # user in a window that can no longer shut down cleanly.
            pass
        if self._tray_icon is not None:
            self._tray_icon.RemoveIcon()
            self._tray_icon.Destroy()
            self._tray_icon = None
        event.Skip()


def run() -> int:
    app = wx.App(False)
    app.SetAppName("Mini Mesa de Som")
    try:
        engine = AudioEngine()
    except AudioDependencyError as exc:
        wx.MessageBox(str(exc), "Mini Mesa de Som", wx.OK | wx.ICON_ERROR)
        return 1

    frame = MainFrame(engine)
    frame.Show()
    app.MainLoop()
    return 0
