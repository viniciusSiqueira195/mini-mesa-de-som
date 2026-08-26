from __future__ import annotations

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from .audio_engine import AudioDependencyError, AudioEngine
from .preferences import AppPreferences, PreferencesStore
from .settings import ReverbSettings, SpatialSettings
from .voice_presets import VoicePreset


_VOICE_PRESETS = tuple(VoicePreset)


class MainFrame(wx.Frame):
    def __init__(
        self,
        engine: AudioEngine,
        preferences_store: PreferencesStore | None = None,
    ) -> None:
        super().__init__(None, title="Mini Mesa de Som Teste", size=(640, 720))
        self.engine = engine
        self.engine.set_error_handler(self._on_audio_error)
        self.preferences_store = preferences_store or PreferencesStore()
        self.preferences = self.preferences_store.load()

        panel = ScrolledPanel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(
            panel,
            label=(
                "Escolha o microfone físico e a saída do cabo virtual. "
                "O Discord ou TeamTalk deve usar a outra ponta do cabo como microfone."
            ),
        )
        intro.Wrap(540)
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 12)

        devices = wx.StaticBoxSizer(wx.VERTICAL, panel, "Dispositivos de áudio")

        input_label = wx.StaticText(panel, label="&Microfone de entrada:")
        self.input_choice = wx.Choice(panel)
        self.input_choice.SetName("Microfone de entrada")
        self.input_choice.Bind(wx.EVT_CHOICE, self._on_preference_changed)
        devices.Add(input_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        devices.Add(self.input_choice, 0, wx.ALL | wx.EXPAND, 8)

        output_label = wx.StaticText(panel, label="&Saída virtual:")
        self.output_choice = wx.Choice(panel)
        self.output_choice.SetName("Saída virtual para Discord ou TeamTalk")
        self.output_choice.Bind(wx.EVT_CHOICE, self._on_preference_changed)
        devices.Add(output_label, 0, wx.LEFT | wx.RIGHT, 8)
        devices.Add(self.output_choice, 0, wx.ALL | wx.EXPAND, 8)

        self.monitor_checkbox = wx.CheckBox(panel, label="&Ouvir retorno")
        self.monitor_checkbox.SetName("Ouvir retorno do microfone processado")
        self.monitor_checkbox.SetValue(self.preferences.monitor_enabled)
        self.monitor_checkbox.Bind(wx.EVT_CHECKBOX, self._on_monitor_toggled)
        devices.Add(self.monitor_checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        monitor_label = wx.StaticText(panel, label="Dispositivo de re&torno:")
        self.monitor_choice = wx.Choice(panel)
        self.monitor_choice.SetName("Dispositivo para ouvir o retorno")
        self.monitor_choice.Enable(self.preferences.monitor_enabled)
        self.monitor_choice.Bind(wx.EVT_CHOICE, self._on_preference_changed)
        devices.Add(monitor_label, 0, wx.LEFT | wx.RIGHT, 8)
        devices.Add(self.monitor_choice, 0, wx.ALL | wx.EXPAND, 8)

        self.refresh_button = wx.Button(panel, label="Atualizar dispositivos (F5)")
        self.refresh_button.Bind(wx.EVT_BUTTON, self._on_refresh)
        devices.Add(self.refresh_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(devices, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        effect = wx.StaticBoxSizer(wx.VERTICAL, panel, "Reverb")
        self.reverb_checkbox = wx.CheckBox(panel, label="Ativar &efeito de reverb")
        self.reverb_checkbox.SetName("Ativar efeito de reverb")
        self.reverb_checkbox.SetValue(self.preferences.reverb_enabled)
        self.reverb_checkbox.Bind(wx.EVT_CHECKBOX, self._on_settings_changed)
        level_label = wx.StaticText(panel, label="Nível de &reverb (0 a 100):")
        self.reverb_level = wx.Slider(
            panel,
            value=self.preferences.reverb_level,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self.reverb_level.SetName("Nível de reverb")
        self.reverb_level.Enable(self.preferences.reverb_enabled)
        self.reverb_level.Bind(wx.EVT_SLIDER, self._on_settings_changed)
        effect.Add(self.reverb_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        effect.Add(level_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        effect.Add(self.reverb_level, 0, wx.ALL | wx.EXPAND, 8)
        root.Add(effect, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        voice = wx.StaticBoxSizer(wx.VERTICAL, panel, "Preset de voz")
        voice_label = wx.StaticText(panel, label="Preset de &voz:")
        self.voice_preset_choice = wx.Choice(
            panel, choices=[preset.label for preset in _VOICE_PRESETS]
        )
        self.voice_preset_choice.SetName("Preset de transformação da voz")
        selected_preset = VoicePreset.from_value(self.preferences.voice_preset)
        self.voice_preset_choice.SetSelection(_VOICE_PRESETS.index(selected_preset))
        self.voice_preset_choice.Bind(
            wx.EVT_CHOICE, self._on_voice_preset_changed
        )
        voice.Add(voice_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        voice.Add(self.voice_preset_choice, 0, wx.ALL | wx.EXPAND, 8)
        root.Add(voice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        noise_reduction = wx.StaticBoxSizer(
            wx.VERTICAL, panel, "Redução de ruído"
        )
        self.noise_reduction_checkbox = wx.CheckBox(
            panel, label="Ativar redução de ruí&do profissional"
        )
        self.noise_reduction_checkbox.SetName(
            "Ativar redução de ruído profissional no microfone"
        )
        self.noise_reduction_checkbox.SetValue(
            self.preferences.noise_reduction_enabled
        )
        self.noise_reduction_checkbox.Bind(
            wx.EVT_CHECKBOX, self._on_noise_reduction_toggled
        )
        noise_reduction.Add(
            self.noise_reduction_checkbox,
            0,
            wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
            8,
        )
        root.Add(
            noise_reduction,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
            12,
        )

        spatial = wx.StaticBoxSizer(wx.VERTICAL, panel, "Áudio espacial binaural")
        self.spatial_checkbox = wx.CheckBox(
            panel, label="Ativar áudio es&pacial 3D com HRTF"
        )
        self.spatial_checkbox.SetName("Ativar áudio espacial binaural com HRTF")
        self.spatial_checkbox.SetValue(self.preferences.spatial_enabled)
        self.spatial_checkbox.Bind(wx.EVT_CHECKBOX, self._on_spatial_changed)
        spatial_label = wx.StaticText(
            panel,
            label="Pos&ição da voz em graus: -180 atrás, 0 frente, 180 atrás",
        )
        self.spatial_angle = wx.Slider(
            panel,
            value=self.preferences.spatial_angle,
            minValue=-180,
            maxValue=180,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self.spatial_angle.SetName(
            "Posição espacial da voz; valores negativos ficam à esquerda e "
            "positivos à direita"
        )
        self.spatial_angle.Enable(self.preferences.spatial_enabled)
        self.spatial_angle.Bind(wx.EVT_SLIDER, self._on_spatial_changed)
        spatial.Add(self.spatial_checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        spatial.Add(spatial_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        spatial.Add(self.spatial_angle, 0, wx.ALL | wx.EXPAND, 8)
        root.Add(spatial, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.toggle_button = wx.Button(panel, label="&Ativar mesa")
        self.toggle_button.SetDefault()
        self.toggle_button.Bind(wx.EVT_BUTTON, self._on_toggle)
        actions.Add(self.toggle_button, 1, wx.RIGHT | wx.EXPAND, 6)

        self.exit_button = wx.Button(panel, label="En&cerrar programa")
        self.exit_button.SetName("Encerrar a Mini Mesa de Som")
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

        panel.SetSizer(root)
        panel.SetupScrolling(scroll_x=False)
        self.CreateStatusBar()
        self.SetStatusText("F5 atualiza a lista de dispositivos.")

        accelerator = wx.AcceleratorTable([(wx.ACCEL_NORMAL, wx.WXK_F5, wx.ID_REFRESH)])
        self.SetAcceleratorTable(accelerator)
        self.Bind(wx.EVT_MENU, self._on_refresh, id=wx.ID_REFRESH)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._refresh_devices()
        self.Centre()
        self.input_choice.SetFocus()

    def _on_refresh(self, _event: wx.Event) -> None:
        self._refresh_devices()

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
        if previous and previous in values:
            choice.SetStringSelection(previous)
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

    def _current_preferences(self) -> AppPreferences:
        return AppPreferences(
            input_device=self.input_choice.GetStringSelection(),
            output_device=self.output_choice.GetStringSelection(),
            monitor_enabled=self.monitor_checkbox.GetValue(),
            monitor_device=self.monitor_choice.GetStringSelection(),
            reverb_enabled=self.reverb_checkbox.GetValue(),
            reverb_level=self.reverb_level.GetValue(),
            noise_reduction_enabled=self.noise_reduction_checkbox.GetValue(),
            spatial_enabled=self.spatial_checkbox.GetValue(),
            spatial_angle=self.spatial_angle.GetValue(),
            voice_preset=self._current_voice_preset().value,
        )

    def _current_voice_preset(self) -> VoicePreset:
        selection = self.voice_preset_choice.GetSelection()
        if selection == wx.NOT_FOUND:
            return VoicePreset.NATURAL
        return _VOICE_PRESETS[selection]

    def _current_spatial_settings(self) -> SpatialSettings:
        return SpatialSettings(
            enabled=self.spatial_checkbox.GetValue(),
            angle_degrees=self.spatial_angle.GetValue(),
        )

    def _save_preferences(self) -> None:
        self.preferences = self._current_preferences()
        try:
            self.preferences_store.save(self.preferences)
        except OSError as exc:
            self.SetStatusText(f"Não foi possível salvar as preferências: {exc}")

    def _on_preference_changed(self, event: wx.Event) -> None:
        previous_monitor = self._saved_monitor_output()
        self._save_preferences()
        if event.GetEventObject() is self.monitor_choice and self.engine.is_running:
            self._update_running_monitor(previous_monitor)
        event.Skip()

    def _on_monitor_toggled(self, _event: wx.Event) -> None:
        previous_monitor = self._saved_monitor_output()
        enabled = self.monitor_checkbox.GetValue()
        self.monitor_choice.Enable(enabled)
        self._save_preferences()
        if self.engine.is_running:
            self._update_running_monitor(previous_monitor)
            return
        self.SetStatusText(
            "Retorno ativado; escolha onde deseja ouvir sua voz."
            if enabled
            else "Retorno desativado."
        )

    def _set_routing_controls_enabled(self, enabled: bool) -> None:
        self.input_choice.Enable(enabled)
        self.output_choice.Enable(enabled)
        self.monitor_checkbox.Enable()
        self.monitor_choice.Enable(self.monitor_checkbox.GetValue())
        self.refresh_button.Enable(enabled)
        self.noise_reduction_checkbox.Enable(enabled)
        self.voice_preset_choice.Enable(enabled)

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

    def _start_route(self, monitor_output: str | None) -> None:
        self.engine.update_noise_reduction(
            self.noise_reduction_checkbox.GetValue()
        )
        self.engine.update_voice_preset(self._current_voice_preset())
        self.engine.update_settings(self._current_settings())
        self.engine.update_spatial(self._current_spatial_settings())
        self.engine.start(
            self.input_choice.GetStringSelection(),
            self.output_choice.GetStringSelection(),
            monitor_output,
        )

    def _start_selected_route(self) -> None:
        self._start_route(self._selected_monitor_output())

    def _show_running_state(self) -> None:
        monitoring = self.monitor_checkbox.GetValue()
        effects = []
        if self.noise_reduction_checkbox.GetValue():
            effects.append("redução de ruído")
        voice_preset = self._current_voice_preset()
        if voice_preset is not VoicePreset.NATURAL:
            effects.append(f"voz {voice_preset.label.casefold()}")
        if self.reverb_checkbox.GetValue():
            effects.append("reverb")
        if self.spatial_checkbox.GetValue():
            effects.append(
                f"áudio espacial em {self.spatial_angle.GetValue()} graus"
            )
        effect_description = " e ".join(effects) if effects else "nenhum efeito"
        self.status.ChangeValue(
            "Mesa ativa. O áudio está sendo enviado para a saída virtual"
            + (" e para o retorno." if monitoring else ".")
            + f" Efeitos ativos: {effect_description}."
        )
        self.SetStatusText(
            f"Mesa ativa com {effect_description}."
            if effects
            else "Mesa ativa sem efeitos."
        )

    def _update_running_monitor(self, previous_monitor: str | None) -> None:
        self.SetStatusText("Atualizando a rota de retorno...")
        try:
            self.engine.update_monitor(self._selected_monitor_output())
        except Exception as exc:
            self.monitor_checkbox.SetValue(previous_monitor is not None)
            if previous_monitor is not None:
                self.monitor_choice.SetStringSelection(previous_monitor)
            self.monitor_choice.Enable(previous_monitor is not None)
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
        except (TypeError, ValueError):
            pass
        event.Skip()

    def _on_noise_reduction_toggled(self, event: wx.Event) -> None:
        self._save_preferences()
        self.SetStatusText(
            "Redução de ruído será ativada junto com a mesa."
            if self.noise_reduction_checkbox.GetValue()
            else "Redução de ruído desativada."
        )
        event.Skip()

    def _on_voice_preset_changed(self, event: wx.Event) -> None:
        preset = self._current_voice_preset()
        self._save_preferences()
        self.SetStatusText(
            "Voz natural selecionada."
            if preset is VoicePreset.NATURAL
            else f"Preset {preset.label} será aplicado ao ativar a mesa."
        )
        event.Skip()

    def _on_spatial_changed(self, event: wx.Event) -> None:
        try:
            enabled = self.spatial_checkbox.GetValue()
            self.spatial_angle.Enable(enabled)
            settings = self._current_spatial_settings()
            self.engine.update_spatial(settings)
            self._save_preferences()
            if self.engine.is_running:
                self._show_running_state()
            elif enabled:
                self.SetStatusText(
                    f"Áudio espacial preparado em {settings.angle_degrees} graus."
                )
            else:
                self.SetStatusText("Áudio espacial desativado.")
        except (TypeError, ValueError):
            pass
        event.Skip()

    def _on_toggle(self, _event: wx.Event) -> None:
        if self.engine.is_running:
            self.engine.stop()
            self._set_routing_controls_enabled(True)
            self.toggle_button.SetLabel("&Ativar mesa")
            self.status.ChangeValue("Desativado.")
            self.SetStatusText("Mesa desativada.")
            return

        try:
            self._start_selected_route()
        except Exception as exc:
            self._show_error(str(exc))
            return

        self._save_preferences()
        self._set_routing_controls_enabled(False)
        self.toggle_button.SetLabel("Des&ativar mesa")
        self._show_running_state()

    def _on_exit(self, _event: wx.Event) -> None:
        self.Close()

    def _on_audio_error(self, message: str) -> None:
        wx.CallAfter(self._handle_audio_error, message)

    def _handle_audio_error(self, message: str) -> None:
        if self.IsBeingDeleted():
            return
        self._set_routing_controls_enabled(True)
        self.toggle_button.SetLabel("&Ativar mesa")
        self.status.ChangeValue("Desativado após uma falha no dispositivo.")
        self._show_error(f"O processamento de áudio foi interrompido.\n\n{message}")

    def _show_error(self, message: str) -> None:
        wx.MessageBox(message, "Mini Mesa de Som Teste", wx.OK | wx.ICON_ERROR, self)

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._save_preferences()
        self.engine.stop()
        event.Skip()


def run() -> int:
    app = wx.App(False)
    app.SetAppName("Mini Mesa de Som Teste")
    try:
        engine = AudioEngine()
    except AudioDependencyError as exc:
        wx.MessageBox(str(exc), "Mini Mesa de Som Teste", wx.OK | wx.ICON_ERROR)
        return 1

    frame = MainFrame(engine)
    frame.Show()
    app.MainLoop()
    return 0
