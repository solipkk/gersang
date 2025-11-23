from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
import time
from pathlib import Path

import keyboard
from PySide6 import QtCore, QtGui, QtWidgets

from core import window_manager
from core.scheduler import SchedulerSettings, SchedulerThread
from core.watchdog import WatchdogConfig, WatchdogThread
from utils.notifier import Notifier
from ui.overlay import OverlayWidget

CONFIG_PATH = Path("config.json")
DEFAULT_THRESHOLD = 0.85
ACTION_CHOICES = {
    "click": "Left click",
    "double_click": "Double click",
    "right_click": "Right click",
}


@dataclass
class TargetSetting:
    image_path: Path
    action: str = "click"
    threshold: float = DEFAULT_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "image_path": str(self.image_path),
            "action": self.action,
            "threshold": self.threshold,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TargetSetting":
        path = Path(data["image_path"])
        action = data.get("action", "click")
        threshold = float(data.get("threshold", DEFAULT_THRESHOLD))
        return cls(image_path=path, action=action, threshold=threshold)


@dataclass
class OverlaySettings:
    enabled: bool = False
    position: str = "top_right"

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "position": self.position}

    @classmethod
    def from_dict(cls, data: dict) -> "OverlaySettings":
        if not isinstance(data, dict):
            return cls()
        return cls(enabled=bool(data.get("enabled", False)), position=data.get("position", "top_right"))


@dataclass
class AppSettings:
    targets: list[TargetSetting] = field(default_factory=list)
    start_hotkey: str = "F9"
    stop_hotkey: str = "F10"
    webhook_url: str = ""
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    window_keyword: str = "game"
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)

    def to_dict(self) -> dict:
        return {
            "targets": [target.to_dict() for target in self.targets],
            "hotkeys": {
                "start": self.start_hotkey,
                "stop": self.stop_hotkey,
            },
            "webhook_url": self.webhook_url,
            "watchdog": self.watchdog.__dict__,
            "overlay": self.overlay.to_dict(),
            "window_manager": {"keyword": self.window_keyword},
            "scheduler": {
                "switch_delay": self.scheduler.switch_delay,
                "action_delay": self.scheduler.action_delay,
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        if not isinstance(data, dict):
            return cls()

        targets: list[TargetSetting] = []
        for entry in data.get("targets", []):
            try:
                targets.append(TargetSetting.from_dict(entry))
            except (KeyError, TypeError, ValueError):
                continue

        hotkeys = data.get("hotkeys", {})
        watchdog_data = data.get("watchdog", {}) or {}
        overlay_data = data.get("overlay", {}) or {}
        window_manager_data = data.get("window_manager", {}) or {}
        scheduler_data = data.get("scheduler", {}) or {}

        return cls(
            targets=targets,
            start_hotkey=hotkeys.get("start", "F9"),
            stop_hotkey=hotkeys.get("stop", "F10"),
            webhook_url=data.get("webhook_url", ""),
            watchdog=WatchdogConfig(
                process_name=watchdog_data.get("process_name", ""),
                process_path=watchdog_data.get("process_path", ""),
                hang_timeout_minutes=int(watchdog_data.get("hang_timeout_minutes", 5)),
            ),
            overlay=OverlaySettings.from_dict(overlay_data),
            window_keyword=window_manager_data.get("keyword", "game"),
            scheduler=SchedulerSettings(
                switch_delay=float(scheduler_data.get("switch_delay", 0.2)),
                action_delay=float(scheduler_data.get("action_delay", 0.5)),
            ),
        )


class ConfigManager:
    def __init__(self, path: Path = CONFIG_PATH, profiles_dir: Path = Path("profiles")) -> None:
        self.path = path
        self.profiles_dir = profiles_dir
        self.profiles_dir.mkdir(exist_ok=True)

    def load_metadata(self) -> tuple[str, bool]:
        if not self.path.exists():
            return "default", False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "default", False
        return raw.get("active_profile", "default"), bool(raw.get("auto_save", False))

    def save_metadata(self, active_profile: str, auto_save: bool) -> None:
        payload = {"active_profile": active_profile, "auto_save": auto_save}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def available_profiles(self) -> list[str]:
        return sorted([p.stem for p in self.profiles_dir.glob("*.json")])

    def _profile_path(self, name: str) -> Path:
        return self.profiles_dir / f"{name}.json"

    def load_profile(self, name: str) -> AppSettings:
        profile_path = self._profile_path(name)
        if not profile_path.exists():
            return AppSettings()
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return AppSettings()
        return AppSettings.from_dict(data)

    def save_profile(self, name: str, settings: AppSettings) -> None:
        payload = settings.to_dict()
        self._profile_path(name).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def delete_profile(self, name: str) -> None:
        profile_path = self._profile_path(name)
        if profile_path.exists():
            profile_path.unlink()


class TargetListWidget(QtWidgets.QListWidget):
    def sizeHint(self) -> QtCore.QSize:  # pragma: no cover - Qt layout helper
        base = super().sizeHint()
        return QtCore.QSize(max(base.width(), 280), base.height())


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PyRPA – Target Manager")
        self.resize(980, 700)

        self.config_manager = ConfigManager()
        self.active_profile, self.auto_save = self.config_manager.load_metadata()
        settings = self.config_manager.load_profile(self.active_profile)
        # Ensure the active profile exists on disk for discoverability
        self.config_manager.save_profile(self.active_profile, settings)

        self.targets: list[TargetSetting] = list(settings.targets)
        self.start_hotkey = settings.start_hotkey
        self.stop_hotkey = settings.stop_hotkey
        self.webhook_url = settings.webhook_url
        self.watchdog_settings = settings.watchdog
        self.overlay_settings = settings.overlay
        self.window_keyword = settings.window_keyword
        self.scheduler_settings = settings.scheduler
        self.window_keyword = settings.window_keyword
        self.scheduler_settings = settings.scheduler

        self.hotkey_handles: list[str] = []
        self.is_running = False
        self.settings_dirty = False
        self.run_start_time: float | None = None
        self.last_log_line = ""
        self.loading_profile = False

        self.watchdog_thread: WatchdogThread | None = None
        self.overlay_widget: OverlayWidget | None = None
        self.scheduler_thread: SchedulerThread | None = None

        self._build_ui()
        self._load_targets_into_list()
        self._apply_settings_to_ui(settings)
        self._register_hotkeys()
        self._refresh_watchdog_thread()
        self._ensure_overlay()

    # UI construction -----------------------------------------------------
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        layout.addLayout(self._build_profile_section())
        layout.addWidget(self._build_window_panel())
        layout.addLayout(self._build_target_section())
        layout.addWidget(self._build_settings_section())
        layout.addWidget(self._build_control_section())
        layout.addWidget(self._build_watchdog_section())
        layout.addWidget(self._build_notification_section())
        layout.addWidget(self._build_log_section())

        self.setCentralWidget(central)

    def _build_profile_section(self) -> QtWidgets.QLayout:
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(QtWidgets.QLabel("Profile:"))

        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        layout.addWidget(self.profile_combo, 2)

        new_btn = QtWidgets.QPushButton("New")
        new_btn.clicked.connect(self._create_profile)
        delete_btn = QtWidgets.QPushButton("Delete")
        delete_btn.clicked.connect(self._delete_profile)
        save_btn = QtWidgets.QPushButton("Save")
        save_btn.clicked.connect(self._save_profile)
        self.auto_save_box = QtWidgets.QCheckBox("Auto-save changes")
        self.auto_save_box.stateChanged.connect(self._toggle_auto_save)

        for widget in (new_btn, delete_btn, save_btn, self.auto_save_box):
            layout.addWidget(widget)

        return layout

    def _build_window_panel(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Window targets")
        vbox = QtWidgets.QVBoxLayout(group)

        header = QtWidgets.QHBoxLayout()
        self.window_keyword_field = QtWidgets.QLineEdit(self.window_keyword)
        self.window_keyword_field.setPlaceholderText("Title keyword (e.g. Maple)")
        self.window_keyword_field.editingFinished.connect(self._on_window_keyword_changed)
        refresh_button = QtWidgets.QPushButton("Refresh")
        refresh_button.clicked.connect(self._scan_windows)
        header.addWidget(QtWidgets.QLabel("Keyword"))
        header.addWidget(self.window_keyword_field)
        header.addWidget(refresh_button)
        vbox.addLayout(header)

        self.window_list = QtWidgets.QListWidget()
        self.window_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.window_list.setAlternatingRowColors(True)
        vbox.addWidget(self.window_list)

        controls = QtWidgets.QHBoxLayout()
        select_all = QtWidgets.QPushButton("Select all")
        select_all.clicked.connect(lambda: self._toggle_all_windows(True))
        deselect_all = QtWidgets.QPushButton("Deselect all")
        deselect_all.clicked.connect(lambda: self._toggle_all_windows(False))

        self.switch_delay_spin = QtWidgets.QDoubleSpinBox()
        self.switch_delay_spin.setRange(0.0, 5.0)
        self.switch_delay_spin.setSingleStep(0.05)
        self.switch_delay_spin.setSuffix(" s switch")
        self.switch_delay_spin.valueChanged.connect(self._on_scheduler_changed)
        self.action_delay_spin = QtWidgets.QDoubleSpinBox()
        self.action_delay_spin.setRange(0.0, 5.0)
        self.action_delay_spin.setSingleStep(0.05)
        self.action_delay_spin.setSuffix(" s action")
        self.action_delay_spin.valueChanged.connect(self._on_scheduler_changed)

        for widget in (select_all, deselect_all, self.switch_delay_spin, self.action_delay_spin):
            controls.addWidget(widget)
        controls.addStretch(1)
        vbox.addLayout(controls)

        return group

    def _build_target_section(self) -> QtWidgets.QLayout:
        container = QtWidgets.QHBoxLayout()

        self.target_list = TargetListWidget()
        self.target_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.target_list.currentItemChanged.connect(self._on_target_selected)
        container.addWidget(self.target_list, 2)

        button_column = QtWidgets.QVBoxLayout()
        add_button = QtWidgets.QPushButton("Add image…")
        add_button.clicked.connect(self._add_target)
        remove_button = QtWidgets.QPushButton("Remove")
        remove_button.clicked.connect(self._remove_target)
        up_button = QtWidgets.QPushButton("Move up")
        up_button.clicked.connect(lambda: self._move_target(-1))
        down_button = QtWidgets.QPushButton("Move down")
        down_button.clicked.connect(lambda: self._move_target(1))

        for btn in (add_button, remove_button, up_button, down_button):
            btn.setMinimumWidth(140)
            button_column.addWidget(btn)

        button_column.addStretch(1)
        container.addLayout(button_column, 0)

        return container

    def _build_settings_section(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Target settings")
        form = QtWidgets.QFormLayout(group)

        self.image_path_field = QtWidgets.QLineEdit()
        self.image_path_field.setReadOnly(True)
        form.addRow("Image", self.image_path_field)

        self.action_combo = QtWidgets.QComboBox()
        for key, label in ACTION_CHOICES.items():
            self.action_combo.addItem(label, userData=key)
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)
        form.addRow("Action", self.action_combo)

        slider_row = QtWidgets.QHBoxLayout()
        self.threshold_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.threshold_slider.setRange(50, 100)
        self.threshold_slider.setTickInterval(5)
        self.threshold_slider.valueChanged.connect(self._on_threshold_changed)
        self.threshold_label = QtWidgets.QLabel("0.85")
        slider_row.addWidget(self.threshold_slider)
        slider_row.addWidget(self.threshold_label)
        form.addRow("Threshold", slider_row)

        self._set_settings_enabled(False)
        return group

    def _build_control_section(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        info_layout = QtWidgets.QVBoxLayout()
        self.status_label = QtWidgets.QLabel("Status: idle")
        self.hotkey_label = QtWidgets.QLabel(
            f"Start: {self.start_hotkey}  |  Stop: {self.stop_hotkey} (global)"
        )
        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.hotkey_label)

        action_layout = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start (F9)")
        self.stop_button = QtWidgets.QPushButton("Stop (F10)")
        self.start_button.clicked.connect(self._handle_start)
        self.stop_button.clicked.connect(self._handle_stop)
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.stop_button)

        layout.addLayout(info_layout, 1)
        layout.addLayout(action_layout, 0)
        layout.addStretch(1)
        return panel

    def _build_watchdog_section(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Watchdog & Overlay")
        form = QtWidgets.QFormLayout(group)

        self.process_name_field = QtWidgets.QLineEdit()
        self.process_name_field.setPlaceholderText("game.exe")
        self.process_name_field.editingFinished.connect(self._on_watchdog_changed)
        form.addRow("Process name", self.process_name_field)

        path_row = QtWidgets.QHBoxLayout()
        self.process_path_field = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self._browse_process_path)
        path_row.addWidget(self.process_path_field)
        path_row.addWidget(browse)
        form.addRow("Executable path", path_row)

        self.hang_timeout_spin = QtWidgets.QSpinBox()
        self.hang_timeout_spin.setRange(1, 120)
        self.hang_timeout_spin.setSuffix(" min")
        self.hang_timeout_spin.valueChanged.connect(self._on_watchdog_changed)
        form.addRow("Hang timeout", self.hang_timeout_spin)

        overlay_row = QtWidgets.QHBoxLayout()
        self.overlay_checkbox = QtWidgets.QCheckBox("Show overlay HUD")
        self.overlay_checkbox.stateChanged.connect(self._toggle_overlay)
        self.overlay_position = QtWidgets.QComboBox()
        self.overlay_position.addItems(["top_right", "top_left"])
        self.overlay_position.currentTextChanged.connect(self._on_overlay_position_changed)
        overlay_row.addWidget(self.overlay_checkbox)
        overlay_row.addWidget(QtWidgets.QLabel("Position"))
        overlay_row.addWidget(self.overlay_position)
        overlay_row.addStretch(1)
        form.addRow("Overlay", overlay_row)

        return group

    def _build_notification_section(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Notifications")
        form = QtWidgets.QFormLayout(group)

        self.webhook_field = QtWidgets.QLineEdit(self.webhook_url)
        self.webhook_field.setPlaceholderText("Discord webhook URL")
        self.webhook_field.editingFinished.connect(self._on_webhook_changed)
        form.addRow("Webhook URL", self.webhook_field)

        test_button = QtWidgets.QPushButton("Send test message")
        test_button.clicked.connect(self._send_test_webhook)
        form.addRow("", test_button)

        return group

    def _build_log_section(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Log console")
        vbox = QtWidgets.QVBoxLayout(group)
        self.log_console = QtWidgets.QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        vbox.addWidget(self.log_console)
        return group

    # Settings hydration --------------------------------------------------
    def _populate_profiles(self) -> None:
        profiles = self.config_manager.available_profiles()
        if self.active_profile not in profiles:
            profiles.insert(0, self.active_profile)
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(profiles)
        current_index = self.profile_combo.findText(self.active_profile)
        self.profile_combo.setCurrentIndex(max(0, current_index))
        self.profile_combo.blockSignals(False)

    def _apply_settings_to_ui(self, settings: AppSettings) -> None:
        self._populate_profiles()
        self.loading_profile = True
        self.targets = list(settings.targets)
        self._load_targets_into_list()

        self.start_hotkey = settings.start_hotkey
        self.stop_hotkey = settings.stop_hotkey
        self.webhook_url = settings.webhook_url
        self.watchdog_settings = settings.watchdog
        self.overlay_settings = settings.overlay

        self.is_running = False
        self.run_start_time = None
        self.last_log_line = ""

        self.status_label.setText("Status: idle")
        self.hotkey_label.setText(f"Start: {self.start_hotkey}  |  Stop: {self.stop_hotkey} (global)")
        self.start_button.setText(f"Start ({self.start_hotkey})")
        self.stop_button.setText(f"Stop ({self.stop_hotkey})")
        self.webhook_field.setText(self.webhook_url)

        self.process_name_field.setText(self.watchdog_settings.process_name)
        self.process_path_field.setText(self.watchdog_settings.process_path)
        self.hang_timeout_spin.blockSignals(True)
        self.hang_timeout_spin.setValue(int(self.watchdog_settings.hang_timeout_minutes))
        self.hang_timeout_spin.blockSignals(False)

        self.window_keyword_field.setText(self.window_keyword)
        self.switch_delay_spin.blockSignals(True)
        self.switch_delay_spin.setValue(float(self.scheduler_settings.switch_delay))
        self.switch_delay_spin.blockSignals(False)
        self.action_delay_spin.blockSignals(True)
        self.action_delay_spin.setValue(float(self.scheduler_settings.action_delay))
        self.action_delay_spin.blockSignals(False)
        self._scan_windows()

        self.overlay_checkbox.blockSignals(True)
        self.overlay_checkbox.setChecked(self.overlay_settings.enabled)
        self.overlay_checkbox.blockSignals(False)
        position_index = self.overlay_position.findText(self.overlay_settings.position)
        self.overlay_position.blockSignals(True)
        self.overlay_position.setCurrentIndex(max(0, position_index))
        self.overlay_position.blockSignals(False)

        self.auto_save_box.blockSignals(True)
        self.auto_save_box.setChecked(self.auto_save)
        self.auto_save_box.blockSignals(False)

        self.settings_dirty = False
        self._update_title_dirty()
        self.loading_profile = False

    # Target list helpers --------------------------------------------------
    def _load_targets_into_list(self) -> None:
        self.target_list.clear()
        for target in self.targets:
            item = QtWidgets.QListWidgetItem(self._format_target_label(target))
            item.setData(QtCore.Qt.UserRole, target)
            self.target_list.addItem(item)

        if self.targets:
            self.target_list.setCurrentRow(0)

    # Window discovery ----------------------------------------------------
    def _scan_windows(self) -> None:
        keyword = self.window_keyword_field.text().strip()
        windows = window_manager.find_all_windows(keyword) if keyword else []
        self.window_list.clear()
        for info in windows:
            item = QtWidgets.QListWidgetItem(f"{info.title} ({info.hwnd})")
            item.setData(QtCore.Qt.UserRole, info)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            self.window_list.addItem(item)
        self._append_log(f"Found {len(windows)} window(s) matching '{keyword}'.")

    def _toggle_all_windows(self, checked: bool) -> None:
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        for i in range(self.window_list.count()):
            item = self.window_list.item(i)
            item.setCheckState(state)

    def _selected_windows(self) -> list[window_manager.WindowInfo]:
        selected: list[window_manager.WindowInfo] = []
        for i in range(self.window_list.count()):
            item = self.window_list.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                info = item.data(QtCore.Qt.UserRole)
                if isinstance(info, window_manager.WindowInfo):
                    selected.append(info)
        return window_manager.filter_windows(selected)

    def _refresh_item_text(self, index: int) -> None:
        item = self.target_list.item(index)
        if item:
            target = self.targets[index]
            item.setText(self._format_target_label(target))

    def _set_settings_enabled(self, enabled: bool) -> None:
        for widget in (self.image_path_field, self.action_combo, self.threshold_slider):
            widget.setEnabled(enabled)

    def _selected_index(self) -> int | None:
        row = self.target_list.currentRow()
        return row if row >= 0 else None

    def _selected_target(self) -> tuple[int, TargetSetting] | None:
        index = self._selected_index()
        if index is None:
            return None
        return index, self.targets[index]

    # Actions --------------------------------------------------------------
    def _add_target(self) -> None:
        dialog = QtWidgets.QFileDialog(self, "Select target image")
        dialog.setNameFilter("PNG Images (*.png)")
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            path_str = dialog.selectedFiles()[0]
            target = TargetSetting(image_path=Path(path_str))
            self.targets.append(target)
            item = QtWidgets.QListWidgetItem(self._format_target_label(target))
            item.setData(QtCore.Qt.UserRole, target)
            self.target_list.addItem(item)
            self.target_list.setCurrentItem(item)
            self._mark_dirty()
            self._append_log(f"Added target: {target.image_path}")

    def _remove_target(self) -> None:
        selected = self._selected_index()
        if selected is None:
            return
        removed = self.targets.pop(selected)
        self.target_list.takeItem(selected)
        self._mark_dirty()
        self._append_log(f"Removed target: {removed.image_path}")
        if self.targets:
            self.target_list.setCurrentRow(max(0, selected - 1))
        else:
            self._clear_settings_panel()

    def _move_target(self, delta: int) -> None:
        selected = self._selected_index()
        if selected is None:
            return
        new_index = selected + delta
        if not 0 <= new_index < len(self.targets):
            return
        self.targets.insert(new_index, self.targets.pop(selected))
        item = self.target_list.takeItem(selected)
        self.target_list.insertItem(new_index, item)
        self.target_list.setCurrentRow(new_index)
        self._mark_dirty()
        self._append_log("Reordered targets")

    def _on_target_selected(
        self, current: QtWidgets.QListWidgetItem | None, previous: QtWidgets.QListWidgetItem | None
    ) -> None:
        del previous
        if current is None:
            self._clear_settings_panel()
            return
        target: TargetSetting = current.data(QtCore.Qt.UserRole)
        self._set_settings_enabled(True)
        self.image_path_field.setText(str(target.image_path))
        action_index = self.action_combo.findData(target.action)
        self.action_combo.setCurrentIndex(max(0, action_index))
        slider_value = int(round(max(0.5, min(1.0, target.threshold)) * 100))
        self.threshold_slider.blockSignals(True)
        self.threshold_slider.setValue(slider_value)
        self.threshold_slider.blockSignals(False)
        self.threshold_label.setText(f"{target.threshold:.2f}")

    def _on_action_changed(self, index: int) -> None:
        selection = self._selected_target()
        if selection is None:
            return
        target_index, target = selection
        target.action = self.action_combo.itemData(index)
        self._refresh_item_text(target_index)
        self._mark_dirty()

    def _on_threshold_changed(self, value: int) -> None:
        selection = self._selected_target()
        if selection is None:
            return
        target_index, target = selection
        target.threshold = round(value / 100.0, 2)
        self.threshold_label.setText(f"{target.threshold:.2f}")
        self._refresh_item_text(target_index)
        self._mark_dirty()

    def _clear_settings_panel(self) -> None:
        self._set_settings_enabled(False)
        self.image_path_field.clear()
        self.threshold_label.setText("0.00")
        self.threshold_slider.setValue(int(DEFAULT_THRESHOLD * 100))

    # Hotkeys --------------------------------------------------------------
    def _register_hotkeys(self) -> None:
        try:
            self.hotkey_handles.append(keyboard.add_hotkey(self.start_hotkey, self._handle_start))
            self.hotkey_handles.append(keyboard.add_hotkey(self.stop_hotkey, self._handle_stop))
        except keyboard.KeyboardException:
            self._append_log("Global hotkeys unavailable; keyboard hook failed.")

    def _unregister_hotkeys(self) -> None:
        for handle in self.hotkey_handles:
            keyboard.remove_hotkey(handle)
        self.hotkey_handles.clear()

    def _reset_hotkeys(self) -> None:
        self._unregister_hotkeys()
        self._register_hotkeys()

    # Macro control --------------------------------------------------------
    def _handle_start(self) -> None:
        if self.is_running:
            return
        if not self.targets:
            self._append_log("No targets configured; cannot start.")
            return
        windows = self._selected_windows()
        if not windows:
            self._append_log("No windows selected; refresh and choose targets to control.")
            return
        self.is_running = True
        self.status_label.setText("Status: running")
        self.run_start_time = time.monotonic()
        self._update_overlay_content("running")
        self._append_log("Macro started.")
        self._start_scheduler(windows)

    def _handle_stop(self) -> None:
        if not self.is_running:
            return
        self.is_running = False
        self.status_label.setText("Status: idle")
        self.run_start_time = None
        self._update_overlay_content("idle")
        self._append_log("Macro stopped.")
        self._stop_scheduler()

    # Scheduler orchestration --------------------------------------------
    def _start_scheduler(self, windows: list[window_manager.WindowInfo]) -> None:
        self._stop_scheduler()
        self.scheduler_thread = SchedulerThread(windows, self.scheduler_settings, action_callback=self._perform_action)
        self.scheduler_thread.window_started.connect(
            lambda idx, title: self._append_log(f"Switched to '{title}'", prefix=self._client_prefix(idx))
        )
        self.scheduler_thread.render_timeout.connect(
            lambda idx, title: self._append_log("Skipped due to blank frame after switch.", prefix=self._client_prefix(idx))
        )
        self.scheduler_thread.window_removed.connect(
            lambda idx, title: self._append_log(f"Window closed: {title}", prefix=self._client_prefix(idx))
        )
        self.scheduler_thread.log.connect(self._append_log)
        self.scheduler_thread.finished.connect(self._on_scheduler_finished)
        self.scheduler_thread.start()

    def _stop_scheduler(self) -> None:
        if self.scheduler_thread:
            self.scheduler_thread.stop()
            self.scheduler_thread.wait()
            self.scheduler_thread = None

    def _perform_action(self, info: window_manager.WindowInfo, idx: int) -> None:
        del info
        self._append_log("Analyzing frame and dispatching actions…", prefix=self._client_prefix(idx))

    def _client_prefix(self, index: int) -> str:
        return f"[Client {index + 1}] "

    def _on_scheduler_finished(self) -> None:
        if self.scheduler_thread:
            self.scheduler_thread = None
        if not self.is_running:
            return
        self.is_running = False
        self.status_label.setText("Status: idle")
        self.run_start_time = None
        self._update_overlay_content("idle")
        self._append_log("Scheduler finished.")

    # Persistence ----------------------------------------------------------
    def _current_settings(self) -> AppSettings:
        return AppSettings(
            targets=list(self.targets),
            start_hotkey=self.start_hotkey,
            stop_hotkey=self.stop_hotkey,
            webhook_url=self.webhook_url,
            watchdog=self.watchdog_settings,
            overlay=self.overlay_settings,
            window_keyword=self.window_keyword,
            scheduler=self.scheduler_settings,
        )

    def _save_profile(self) -> None:
        settings = self._current_settings()
        self.config_manager.save_profile(self.active_profile, settings)
        self.config_manager.save_metadata(self.active_profile, self.auto_save)
        self.settings_dirty = False
        self._update_title_dirty()
        self._append_log(f"Profile '{self.active_profile}' saved.")

    def _mark_dirty(self) -> None:
        if getattr(self, "loading_profile", False):
            return
        self.settings_dirty = True
        self._update_title_dirty()
        if self.auto_save:
            self._save_profile()

    # Logging --------------------------------------------------------------
    def _append_log(self, message: str, prefix: str = "") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {prefix}{message}"
        self.last_log_line = f"{prefix}{message}".strip()
        self.log_console.appendPlainText(line)
        self.log_console.verticalScrollBar().setValue(self.log_console.verticalScrollBar().maximum())
        if self.watchdog_thread:
            self.watchdog_thread.report_activity()
        self._update_overlay_content(state=None)

    def _on_webhook_changed(self) -> None:
        self.webhook_url = self.webhook_field.text().strip()
        self._mark_dirty()
        self._append_log("Webhook URL updated.")

    def _send_test_webhook(self) -> None:
        notifier = Notifier(self.webhook_url)
        notifier.send_message("PyRPA test message: webhook configured")
        self._append_log("Test webhook sent (check Discord).")

    # Utility --------------------------------------------------------------
    def _format_target_label(self, target: TargetSetting) -> str:
        action_label = ACTION_CHOICES.get(target.action, target.action)
        return f"{target.image_path.name} • {action_label} • {target.threshold:.2f}"

    def _update_title_dirty(self) -> None:
        suffix = " *" if self.settings_dirty and not self.auto_save else ""
        self.setWindowTitle(f"PyRPA – Target Manager{suffix}")

    def _update_overlay_content(self, state: str | None) -> None:
        if not self.overlay_settings.enabled:
            return
        self._ensure_overlay()
        if not self.overlay_widget:
            return
        overlay_state = state or ("running" if self.is_running else "idle")
        self.overlay_widget.set_state(overlay_state.title())
        self.overlay_widget.set_start_time(self.run_start_time if self.run_start_time else time.monotonic())
        self.overlay_widget.set_last_log(self.last_log_line or "Ready")

    def _ensure_overlay(self) -> None:
        if not self.overlay_settings.enabled:
            if self.overlay_widget:
                self.overlay_widget.hide()
            return
        if self.overlay_widget is None:
            self.overlay_widget = OverlayWidget(self.overlay_settings.position)
        else:
            self.overlay_widget.set_position(self.overlay_settings.position)
        self.overlay_widget.set_state("Running" if self.is_running else "Idle")
        if self.run_start_time:
            self.overlay_widget.set_start_time(self.run_start_time)
        self.overlay_widget.set_last_log(self.last_log_line or "Ready")
        self.overlay_widget.show()

    def _refresh_watchdog_thread(self) -> None:
        if self.watchdog_thread:
            self.watchdog_thread.stop()
            self.watchdog_thread.wait()
            self.watchdog_thread = None
        if not (self.watchdog_settings.process_name or self.watchdog_settings.process_path):
            return
        self.watchdog_thread = WatchdogThread(self.watchdog_settings)
        self.watchdog_thread.status.connect(self._append_log)
        self.watchdog_thread.restarted.connect(lambda path: self._append_log(f"Restarted: {path}"))
        self.watchdog_thread.killed.connect(lambda name: self._append_log(f"Killed hung process: {name}"))
        self.watchdog_thread.start()

    # Window & scheduler handlers ----------------------------------------
    def _on_window_keyword_changed(self) -> None:
        if getattr(self, "loading_profile", False):
            return
        self.window_keyword = self.window_keyword_field.text().strip()
        self._mark_dirty()
        self._scan_windows()

    def _on_scheduler_changed(self) -> None:
        if getattr(self, "loading_profile", False):
            return
        self.scheduler_settings = SchedulerSettings(
            switch_delay=float(self.switch_delay_spin.value()),
            action_delay=float(self.action_delay_spin.value()),
        )
        self._mark_dirty()

    # Watchdog / overlay handlers ----------------------------------------
    def _on_watchdog_changed(self) -> None:
        if getattr(self, "loading_profile", False):
            return
        self.watchdog_settings = WatchdogConfig(
            process_name=self.process_name_field.text().strip(),
            process_path=self.process_path_field.text().strip(),
            hang_timeout_minutes=int(self.hang_timeout_spin.value()),
        )
        self._mark_dirty()
        self._refresh_watchdog_thread()

    def _browse_process_path(self) -> None:
        dialog = QtWidgets.QFileDialog(self, "Select executable")
        dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            selected = dialog.selectedFiles()[0]
            self.process_path_field.setText(selected)
            self._on_watchdog_changed()

    def _toggle_overlay(self) -> None:
        if getattr(self, "loading_profile", False):
            return
        self.overlay_settings.enabled = self.overlay_checkbox.isChecked()
        self._mark_dirty()
        self._ensure_overlay()

    def _on_overlay_position_changed(self, value: str) -> None:
        if getattr(self, "loading_profile", False):
            return
        self.overlay_settings.position = value
        if self.overlay_widget:
            self.overlay_widget.set_position(value)
        self._mark_dirty()

    # Profile management ---------------------------------------------------
    def _toggle_auto_save(self, state: int) -> None:
        if getattr(self, "loading_profile", False):
            return
        self.auto_save = state == QtCore.Qt.Checked
        self.config_manager.save_metadata(self.active_profile, self.auto_save)
        if self.auto_save and self.settings_dirty:
            self._save_profile()
        self._update_title_dirty()

    def _on_profile_changed(self, profile: str) -> None:
        if not profile or profile == self.active_profile:
            return
        if self.settings_dirty and not self.auto_save:
            # keep unsaved changes by staying on current profile
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentText(self.active_profile)
            self.profile_combo.blockSignals(False)
            return
        self.active_profile = profile
        settings = self.config_manager.load_profile(profile)
        self.config_manager.save_metadata(self.active_profile, self.auto_save)
        self._apply_settings_to_ui(settings)
        self._reset_hotkeys()
        self._refresh_watchdog_thread()
        self._ensure_overlay()

    def _create_profile(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New profile", "Profile name")
        if not ok or not name.strip():
            return
        profile_name = name.strip()
        self.active_profile = profile_name
        default_settings = AppSettings()
        self.config_manager.save_profile(profile_name, default_settings)
        self.config_manager.save_metadata(self.active_profile, self.auto_save)
        self._apply_settings_to_ui(default_settings)
        self._reset_hotkeys()
        self._refresh_watchdog_thread()
        self._ensure_overlay()

    def _delete_profile(self) -> None:
        if self.profile_combo.count() <= 1:
            self._append_log("Cannot delete the last profile.")
            return
        name = self.profile_combo.currentText()
        if not name:
            return
        self.config_manager.delete_profile(name)
        remaining = [p for p in self.config_manager.available_profiles() if p != name]
        self.active_profile = remaining[0] if remaining else "default"
        settings = self.config_manager.load_profile(self.active_profile)
        self.config_manager.save_metadata(self.active_profile, self.auto_save)
        self._apply_settings_to_ui(settings)
        self._reset_hotkeys()
        self._refresh_watchdog_thread()
        self._ensure_overlay()

    # Lifecycle ------------------------------------------------------------
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # pragma: no cover - Qt hook
        if self.auto_save:
            self._save_profile()
        self._unregister_hotkeys()
        self._stop_scheduler()
        if self.watchdog_thread:
            self.watchdog_thread.stop()
            self.watchdog_thread.wait()
        super().closeEvent(event)


def run() -> None:
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    run()
