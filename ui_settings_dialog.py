# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6 import QtWidgets
from theme_utils import load_ui_font_files, register_ui_font_files
from ui_settings_io import SettingsIOMixin
from ui_settings_pages import SettingsPagesMixin
from ui_settings_styles import SettingsStylesMixin
from ui_settings_widgets import ColorPickerWidget


class SettingsDialog(QtWidgets.QDialog, SettingsStylesMixin, SettingsPagesMixin, SettingsIOMixin):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.resize(950, 700)
        self._ui_color_inputs: dict[str, dict[str, ColorPickerWidget]] = {"light": {}, "dark": {}}
        self._suppress_ui_color_preview = True
        self._ui_color_snapshot = self._capture_ui_color_snapshot()
        self._ui_font_files = load_ui_font_files()
        if self._ui_font_files:
            register_ui_font_files(self._ui_font_files)
        self._suppress_ui_font_preview = True
        self._ui_font_snapshot = self._capture_ui_font_snapshot()
        self._apply_global_style()
        self._init_ui()
        self._suppress_gdrive_confirm = True
        try:
            self._load_settings()
        finally:
            self._suppress_gdrive_confirm = False
            self._suppress_ui_color_preview = False
            self._suppress_ui_font_preview = False
