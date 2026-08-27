from __future__ import annotations

import threading
from dataclasses import replace

import wx
import wx.adv

from .audio_engine import AudioDependencyError, AudioEngine
from .preferences import AppPreferences, PreferencesStore
from .settings import ReverbSettings, SpatialSettings
from .updater import (
    UpdateCancelled,
    UpdateError,
    UpdateInfo,
    can_self_update,
    check_for_update,
    download_installer,
    launch_installer,
)


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

    def notify_minimized(self, running: bool) -> None:
        if not self.is_available:
            return
        state = "A mesa continua ativa." if running else "O programa continua aberto."
        try:
            self.ShowBalloon(
                "Mini Mesa de Som",
                f"Janela minimizada para a bandeja. {state}",
                3000,
                wx.ICON_INFORMATION,
            )
        except (AttributeError, wx.wxAssertionError):
            pass

    def _on_restore(self, _event: wx.Event) -> None:
        self._frame.restore_from_tray()

    def _on_exit(self, _event: wx.Event) -> None:
        self._frame.exit_from_tray()


class MainFrame(wx.Frame):
    def __init__(
        self,
        engine: AudioEngine,
        preferences_store: PreferencesStore | None = None,
    ) -> None:
        super().__init__(None, title="Mini Mesa de Som Teste", size=(620, 750))
        self.engine = engine
        self.engine.set_error_handler(self._on_audio_error)
        self.preferences_store = preferences_store or PreferencesStore()
        self.preferences = self.preferences_store.load()
        self._tray_icon: SystemTrayIcon | None = None
        self._last_focused_control: wx.Window | None = None
        self._tray_notification_shown = False
        self._update_check_in_progress = False
        self._update_progress_dialog: wx.ProgressDialog | None = None
        self._update_cancel_event: threading.Event | None = None

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
        self.CreateStatusBar()
        self.SetStatusText("F5 atualiza a lista de dispositivos.")

        menu_bar = wx.MenuBar()
        help_menu = wx.Menu()
        self._check_updates_id = wx.NewIdRef()
        help_menu.Append(self._check_updates_id, "Verificar &atualizações")
        menu_bar.Append(help_menu, "A&juda")
        self.SetMenuBar(menu_bar)

        accelerator = wx.AcceleratorTable([(wx.ACCEL_NORMAL, wx.WXK_F5, wx.ID_REFRESH)])
        self.SetAcceleratorTable(accelerator)
        self.Bind(wx.EVT_MENU, self._on_refresh, id=wx.ID_REFRESH)
        self.Bind(
            wx.EVT_MENU,
            self._on_check_for_updates,
            id=self._check_updates_id,
        )
        self.Bind(wx.EVT_ICONIZE, self._on_iconize)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._tray_icon = SystemTrayIcon(self)

        self._refresh_devices()
        self.Centre()
        self.input_choice.SetFocus()
        if not self.preferences.welcome_shown:
            wx.CallAfter(self._show_welcome)
        if can_self_update():
            wx.CallLater(3000, self._start_update_check, False)

    def _on_check_for_updates(self, _event: wx.Event) -> None:
        self._start_update_check(True)

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
        except UpdateError as exc:
            wx.MessageBox(str(exc), "Atualizações", wx.OK | wx.ICON_ERROR, self)
            return
        self.SetStatusText("Atualização baixada; instalando a nova versão...")
        self.Close()

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
            "2. Escolha o CABLE Input como saída virtual.\n"
            "3. No aplicativo de conversa, escolha CABLE Output como microfone.\n"
            "4. Ajuste os efeitos e pressione Ativar mesa.\n\n"
            "Para ouvir sua própria voz, marque Ouvir retorno e use fones de "
            "ouvido para evitar microfonia. Faça um teste de gravação no "
            "aplicativo de conversa antes de entrar em uma chamada. Todos os "
            "controles podem ser operados pelo teclado e são compatíveis com "
            "leitores de tela.",
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
            welcome_shown=self.preferences.welcome_shown,
            input_device=self.input_choice.GetStringSelection(),
            output_device=self.output_choice.GetStringSelection(),
            monitor_enabled=self.monitor_checkbox.GetValue(),
            monitor_device=self.monitor_choice.GetStringSelection(),
            reverb_enabled=self.reverb_checkbox.GetValue(),
            reverb_level=self.reverb_level.GetValue(),
            noise_reduction_enabled=self.noise_reduction_checkbox.GetValue(),
            spatial_enabled=self.spatial_checkbox.GetValue(),
            spatial_angle=self.spatial_angle.GetValue(),
        )

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
            "Retorno experimental ativado; a saída virtual permanece isolada."
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
        self.engine.update_noise_reduction(
            self.noise_reduction_checkbox.GetValue()
        )
        self.engine.update_settings(self._current_settings())
        self.engine.update_spatial(self._current_spatial_settings())
        self.engine.start(
            self.input_choice.GetStringSelection(),
            self.output_choice.GetStringSelection(),
            self._selected_monitor_output(),
        )

    def _show_running_state(self) -> None:
        monitoring = self.monitor_checkbox.GetValue()
        effects = []
        if self.noise_reduction_checkbox.GetValue():
            effects.append("redução de ruído")
        if self.reverb_checkbox.GetValue():
            effects.append("reverb")
        if self.spatial_checkbox.GetValue():
            effects.append(
                f"áudio espacial em {self.spatial_angle.GetValue()} graus"
            )
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

    def _update_running_monitor(self, previous_monitor: str | None) -> None:
        self.SetStatusText("Atualizando a rota de retorno experimental...")
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

    def _on_iconize(self, event: wx.IconizeEvent) -> None:
        if (
            event.IsIconized()
            and self._tray_icon is not None
            and self._tray_icon.is_available
        ):
            wx.CallAfter(self._hide_to_tray)
        event.Skip()

    def _hide_to_tray(self) -> None:
        if self.IsBeingDeleted() or not self.IsShown():
            return
        focused = wx.Window.FindFocus()
        if focused is not None and self.IsDescendant(focused):
            self._last_focused_control = focused
        self.Hide()
        if self._tray_icon is not None and not self._tray_notification_shown:
            self._tray_icon.notify_minimized(self.engine.is_running)
            self._tray_notification_shown = True

    def restore_from_tray(self) -> None:
        if self.IsBeingDeleted():
            return
        self.Show()
        self.Iconize(False)
        self.Raise()
        focused = self._last_focused_control
        if focused is not None and not focused.IsBeingDeleted():
            wx.CallAfter(focused.SetFocus)
        else:
            wx.CallAfter(self.input_choice.SetFocus)

    def exit_from_tray(self) -> None:
        if not self.IsBeingDeleted():
            self.Close()

    def _on_audio_error(self, message: str) -> None:
        wx.CallAfter(self._handle_audio_error, message)

    def _handle_audio_error(self, message: str) -> None:
        if self.IsBeingDeleted():
            return
        if not self.IsShown():
            self.restore_from_tray()
        self._set_routing_controls_enabled(True)
        self.toggle_button.SetLabel("&Ativar mesa")
        self.status.ChangeValue("Desativado após uma falha no dispositivo.")
        self._show_error(f"O processamento de áudio foi interrompido.\n\n{message}")

    def _show_error(self, message: str) -> None:
        wx.MessageBox(message, "Mini Mesa de Som Teste", wx.OK | wx.ICON_ERROR, self)

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._save_preferences()
        self.engine.stop()
        if self._tray_icon is not None:
            self._tray_icon.RemoveIcon()
            self._tray_icon.Destroy()
            self._tray_icon = None
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
