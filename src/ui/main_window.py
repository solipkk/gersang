from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import keyboard
from PySide6 import QtCore, QtGui, QtWidgets

from utils.notifier import Notifier

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
class AppSettings:
    targets: list[TargetSetting]
    start_hotkey: str = "F9"
    stop_hotkey: str = "F10"
    webhook_url: str = ""


class ConfigManager:
    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings(targets=[])

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return AppSettings(targets=[])

        targets: list[TargetSetting] = []
        for entry in raw.get("targets", []):
            try:
                targets.append(TargetSetting.from_dict(entry))
            except (KeyError, TypeError, ValueError):
                continue

        hotkeys = raw.get("hotkeys", {})
        start_hotkey = hotkeys.get("start", "F9")
        stop_hotkey = hotkeys.get("stop", "F10")

        webhook_url = raw.get("webhook_url", "")

        return AppSettings(
            targets=targets, start_hotkey=start_hotkey, stop_hotkey=stop_hotkey, webhook_url=webhook_url
        )

    def save(self, settings: AppSettings) -> None:
        payload = {
            "targets": [target.to_dict() for target in settings.targets],
            "hotkeys": {
                "start": settings.start_hotkey,
                "stop": settings.stop_hotkey,
            },
            "webhook_url": settings.webhook_url,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class TargetListWidget(QtWidgets.QListWidget):
    def sizeHint(self) -> QtCore.QSize:  # pragma: no cover - Qt layout helper
        base = super().sizeHint()
        return QtCore.QSize(max(base.width(), 280), base.height())


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PyRPA – Target Manager")
        self.resize(900, 620)

        self.config_manager = ConfigManager()
        settings = self.config_manager.load()
        self.targets: list[TargetSetting] = list(settings.targets)
        self.start_hotkey = settings.start_hotkey
        self.stop_hotkey = settings.stop_hotkey
        self.webhook_url = settings.webhook_url
        self.hotkey_handles: list[str] = []
        self.is_running = False

        self._build_ui()
        self._load_targets_into_list()
        self._register_hotkeys()

    # UI construction -----------------------------------------------------
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        layout.addLayout(self._build_target_section())
        layout.addWidget(self._build_settings_section())
        layout.addWidget(self._build_control_section())
        layout.addWidget(self._build_notification_section())
        layout.addWidget(self._build_log_section())

        self.setCentralWidget(central)

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

    # Target list helpers --------------------------------------------------
    def _load_targets_into_list(self) -> None:
        self.target_list.clear()
        for target in self.targets:
            item = QtWidgets.QListWidgetItem(self._format_target_label(target))
            item.setData(QtCore.Qt.UserRole, target)
            self.target_list.addItem(item)

        if self.targets:
            self.target_list.setCurrentRow(0)

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
            self._persist_settings()
            self._append_log(f"Added target: {target.image_path}")

    def _remove_target(self) -> None:
        selected = self._selected_index()
        if selected is None:
            return
        removed = self.targets.pop(selected)
        self.target_list.takeItem(selected)
        self._persist_settings()
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
        self._persist_settings()
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
        self._persist_settings()

    def _on_threshold_changed(self, value: int) -> None:
        selection = self._selected_target()
        if selection is None:
            return
        target_index, target = selection
        target.threshold = round(value / 100.0, 2)
        self.threshold_label.setText(f"{target.threshold:.2f}")
        self._refresh_item_text(target_index)
        self._persist_settings()

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

    # Macro control --------------------------------------------------------
    def _handle_start(self) -> None:
        if self.is_running:
            return
        if not self.targets:
            self._append_log("No targets configured; cannot start.")
            return
        self.is_running = True
        self.status_label.setText("Status: running")
        self._append_log("Macro started.")

    def _handle_stop(self) -> None:
        if not self.is_running:
            return
        self.is_running = False
        self.status_label.setText("Status: idle")
        self._append_log("Macro stopped.")

    # Persistence ----------------------------------------------------------
    def _persist_settings(self) -> None:
        self.config_manager.save(self._current_settings())

    def _current_settings(self) -> AppSettings:
        return AppSettings(
            targets=list(self.targets),
            start_hotkey=self.start_hotkey,
            stop_hotkey=self.stop_hotkey,
            webhook_url=self.webhook_url,
        )

    # Logging --------------------------------------------------------------
    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_console.appendPlainText(f"[{timestamp}] {message}")
        self.log_console.verticalScrollBar().setValue(self.log_console.verticalScrollBar().maximum())

    def _on_webhook_changed(self) -> None:
        self.webhook_url = self.webhook_field.text().strip()
        self._persist_settings()
        if self.webhook_url:
            self._append_log("Webhook URL saved.")
        else:
            self._append_log("Webhook URL cleared.")

    def _send_test_webhook(self) -> None:
        notifier = Notifier(self.webhook_url)
        notifier.send_message("PyRPA test message: webhook configured")
        self._append_log("Test webhook sent (check Discord).")

    # Utility --------------------------------------------------------------
    def _format_target_label(self, target: TargetSetting) -> str:
        action_label = ACTION_CHOICES.get(target.action, target.action)
        return f"{target.image_path.name} • {action_label} • {target.threshold:.2f}"

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # pragma: no cover - Qt hook
        self._persist_settings()
        self._unregister_hotkeys()
        super().closeEvent(event)


def run() -> None:
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    run()
