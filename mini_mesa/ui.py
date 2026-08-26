from __future__ import annotations

import wx

from .audio_engine import AudioDependencyError, AudioEngine
from .settings import ReverbSettings


class MainFrame(wx.Frame):
    def __init__(self, engine: AudioEngine) -> None:
        super().__init__(None, title="Mini Mesa de Som Teste", size=(590, 470))
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

        self.refresh_button = wx.Button(panel, label="Atualizar dispositivos (F5)")
        self.refresh_button.Bind(wx.EVT_BUTTON, self._on_refresh)
        devices.Add(self.refresh_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(devices, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        effect = wx.StaticBoxSizer(wx.VERTICAL, panel, "Reverb")
        self.amount = self._add_percent_control(
            panel, effect, "Quantidade de &reverb (%):", 25, "Quantidade de reverb"
        )
        self.room_size = self._add_percent_control(
            panel, effect, "&Tamanho da sala (%):", 40, "Tamanho da sala"
        )
        self.damping = self._add_percent_control(
            panel, effect, "Amortecimento (%):", 50, "Amortecimento do reverb"
        )
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

    def _add_percent_control(
        self,
        panel: wx.Panel,
        sizer: wx.StaticBoxSizer,
        label: str,
        initial: int,
        accessible_name: str,
    ) -> wx.SpinCtrl:
        text = wx.StaticText(panel, label=label)
        control = wx.SpinCtrl(panel, min=0, max=100, initial=initial)
        control.SetName(f"{accessible_name}, porcentagem")
        control.Bind(wx.EVT_SPINCTRL, self._on_settings_changed)
        control.Bind(wx.EVT_TEXT, self._on_settings_changed)
        sizer.Add(text, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        sizer.Add(control, 0, wx.ALL | wx.EXPAND, 8)
        return control

    def _on_refresh(self, _event: wx.Event) -> None:
        self._refresh_devices()

    def _refresh_devices(self) -> None:
        selected_input = self.input_choice.GetStringSelection()
        selected_output = self.output_choice.GetStringSelection()
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
            amount_percent=self.amount.GetValue(),
            room_size_percent=self.room_size.GetValue(),
            damping_percent=self.damping.GetValue(),
        )

    def _on_settings_changed(self, event: wx.Event) -> None:
        try:
            self.engine.update_settings(self._current_settings())
        except (TypeError, ValueError):
            pass
        event.Skip()

    def _on_toggle(self, _event: wx.Event) -> None:
        if self.engine.is_running:
            self.engine.stop()
            self.toggle_button.SetLabel("&Ativar reverb")
            self.status.ChangeValue("Desativado.")
            self.SetStatusText("Processamento desativado.")
            return

        try:
            self.engine.update_settings(self._current_settings())
            self.engine.start(
                self.input_choice.GetStringSelection(),
                self.output_choice.GetStringSelection(),
            )
        except Exception as exc:
            self._show_error(str(exc))
            return

        self.toggle_button.SetLabel("Des&ativar reverb")
        self.status.ChangeValue(
            "Ativo. O áudio processado está sendo enviado para a saída selecionada."
        )
        self.SetStatusText("Reverb ativo.")

    def _on_audio_error(self, message: str) -> None:
        wx.CallAfter(self._handle_audio_error, message)

    def _handle_audio_error(self, message: str) -> None:
        if self.IsBeingDeleted():
            return
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
