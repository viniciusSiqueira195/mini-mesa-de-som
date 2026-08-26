from __future__ import annotations

import wx

from .audio_engine import AudioDependencyError, AudioEngine
from .settings import ReverbSettings


class MainFrame(wx.Frame):
    def __init__(self, engine: AudioEngine) -> None:
        super().__init__(None, title="Mini Mesa de Som Teste", size=(590, 500))
        self.engine = engine
        self.engine.set_error_handler(self._on_audio_error)

        panel = wx.Panel(self)
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
        devices.Add(input_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        devices.Add(self.input_choice, 0, wx.ALL | wx.EXPAND, 8)

        output_label = wx.StaticText(panel, label="&Saída virtual:")
        self.output_choice = wx.Choice(panel)
        self.output_choice.SetName("Saída virtual para Discord ou TeamTalk")
        devices.Add(output_label, 0, wx.LEFT | wx.RIGHT, 8)
        devices.Add(self.output_choice, 0, wx.ALL | wx.EXPAND, 8)

        self.monitor_checkbox = wx.CheckBox(panel, label="&Ouvir retorno")
        self.monitor_checkbox.SetName("Ouvir retorno do microfone processado")
        self.monitor_checkbox.Bind(wx.EVT_CHECKBOX, self._on_monitor_toggled)
        devices.Add(self.monitor_checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        monitor_label = wx.StaticText(panel, label="Dispositivo de re&torno:")
        self.monitor_choice = wx.Choice(panel)
        self.monitor_choice.SetName("Dispositivo para ouvir o retorno")
        self.monitor_choice.Disable()
        devices.Add(monitor_label, 0, wx.LEFT | wx.RIGHT, 8)
        devices.Add(self.monitor_choice, 0, wx.ALL | wx.EXPAND, 8)

        self.refresh_button = wx.Button(panel, label="Atualizar dispositivos (F5)")
        self.refresh_button.Bind(wx.EVT_BUTTON, self._on_refresh)
        devices.Add(self.refresh_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(devices, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        effect = wx.StaticBoxSizer(wx.VERTICAL, panel, "Reverb")
        level_label = wx.StaticText(panel, label="Nível de &reverb (0 a 100):")
        self.reverb_level = wx.Slider(
            panel,
            value=25,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self.reverb_level.SetName("Nível de reverb")
        self.reverb_level.Bind(wx.EVT_SLIDER, self._on_settings_changed)
        effect.Add(level_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        effect.Add(self.reverb_level, 0, wx.ALL | wx.EXPAND, 8)
        root.Add(effect, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.toggle_button = wx.Button(panel, label="&Ativar reverb")
        self.toggle_button.SetDefault()
        self.toggle_button.Bind(wx.EVT_BUTTON, self._on_toggle)
        root.Add(self.toggle_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

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
        selected_input = self.input_choice.GetStringSelection()
        selected_output = self.output_choice.GetStringSelection()
        selected_monitor = self.monitor_choice.GetStringSelection()
        try:
            inputs = self.engine.input_devices()
            outputs = self.engine.output_devices()
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
            outputs,
            selected_monitor,
            prefer_physical_output=True,
        )
        self.SetStatusText(
            f"{len(inputs)} entradas e {len(outputs)} saídas encontradas."
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
        return ReverbSettings(level_percent=self.reverb_level.GetValue())

    def _on_monitor_toggled(self, _event: wx.Event) -> None:
        enabled = self.monitor_checkbox.GetValue()
        self.monitor_choice.Enable(enabled)
        self.SetStatusText(
            "Retorno ativado; escolha onde deseja ouvir sua voz."
            if enabled
            else "Retorno desativado."
        )

    def _set_routing_controls_enabled(self, enabled: bool) -> None:
        self.input_choice.Enable(enabled)
        self.output_choice.Enable(enabled)
        self.monitor_checkbox.Enable(enabled)
        self.monitor_choice.Enable(enabled and self.monitor_checkbox.GetValue())
        self.refresh_button.Enable(enabled)

    def _on_settings_changed(self, event: wx.Event) -> None:
        try:
            self.engine.update_settings(self._current_settings())
            self.SetStatusText(
                f"Nível de reverb: {self.reverb_level.GetValue()} por cento."
            )
        except (TypeError, ValueError):
            pass
        event.Skip()

    def _on_toggle(self, _event: wx.Event) -> None:
        if self.engine.is_running:
            self.engine.stop()
            self._set_routing_controls_enabled(True)
            self.toggle_button.SetLabel("&Ativar reverb")
            self.status.ChangeValue("Desativado.")
            self.SetStatusText("Processamento desativado.")
            return

        try:
            self.engine.update_settings(self._current_settings())
            self.engine.start(
                self.input_choice.GetStringSelection(),
                self.output_choice.GetStringSelection(),
                (
                    self.monitor_choice.GetStringSelection()
                    if self.monitor_checkbox.GetValue()
                    else None
                ),
            )
        except Exception as exc:
            self._show_error(str(exc))
            return

        self._set_routing_controls_enabled(False)
        self.toggle_button.SetLabel("Des&ativar reverb")
        self.status.ChangeValue(
            "Ativo. O áudio processado está sendo enviado para a saída virtual"
            + (" e para o retorno." if self.monitor_checkbox.GetValue() else ".")
        )
        self.SetStatusText("Reverb ativo.")

    def _on_audio_error(self, message: str) -> None:
        wx.CallAfter(self._handle_audio_error, message)

    def _handle_audio_error(self, message: str) -> None:
        if self.IsBeingDeleted():
            return
        self._set_routing_controls_enabled(True)
        self.toggle_button.SetLabel("&Ativar reverb")
        self.status.ChangeValue("Desativado após uma falha no dispositivo.")
        self._show_error(f"O processamento de áudio foi interrompido.\n\n{message}")

    def _show_error(self, message: str) -> None:
        wx.MessageBox(message, "Mini Mesa de Som Teste", wx.OK | wx.ICON_ERROR, self)

    def _on_close(self, event: wx.CloseEvent) -> None:
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
