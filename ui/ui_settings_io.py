# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets
from core.config import (
    DEFAULT_ABEMA_ENTRIES,
    DEFAULT_AUTO_CHECK_INTERVAL_SEC,
    DEFAULT_AUTO_COMPRESS_MAX_HEIGHT,
    DEFAULT_AUTO_COMPRESS_FPS,
    DEFAULT_AUTO_ENABLED,
    DEFAULT_BILIBILI_ENTRIES,
    DEFAULT_BIGO_ENTRIES,
    DEFAULT_FUWATCH_ENTRIES,
    DEFAULT_KICK_ENTRIES,
    DEFAULT_LIVE17_ENTRIES,
    DEFAULT_NICONICO_ENTRIES,
    DEFAULT_OPENRECTV_ENTRIES,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_RADIKO_ENTRIES,
    DEFAULT_RECORDING_MAX_SIZE_MB,
    DEFAULT_RECORDING_QUALITY,
    DEFAULT_RECORDING_SIZE_MARGIN_MB,
    DEFAULT_RETRY_COUNT,
    DEFAULT_RETRY_WAIT_SEC,
    DEFAULT_TIKTOK_ENTRIES,
    DEFAULT_TIMESHIFT_SEGMENT_HOURS,
    DEFAULT_TIMESHIFT_SEGMENT_MINUTES,
    DEFAULT_TIMESHIFT_SEGMENT_SECONDS,
    DEFAULT_TWITCASTING_ENTRIES,
    DEFAULT_YOUTUBE_RECORDING_BACKEND,
)
from utils.settings_store import load_bool_setting, load_setting_value, save_setting_value
from utils.theme_utils import (
    get_default_ui_colors,
    get_ui_color_edit_values,
    load_ui_color_presets,
    load_ui_font_files,
    save_ui_color_presets,
    save_ui_font_files,
    register_ui_font_files,
    serialize_ui_colors,
)
from ui.ui_watermark_dialog import WatermarkDialog


class SettingsIOMixin:
    def _capture_ui_color_snapshot(self) -> dict[str, object]:
        return {
            "enabled": load_bool_setting("ui_colors_enabled", False),
            "light": load_setting_value("ui_colors_light", "{}", str),
            "dark": load_setting_value("ui_colors_dark", "{}", str),
        }

    def _capture_ui_font_snapshot(self) -> dict[str, object]:
        return {
            "family": load_setting_value("ui_font_family", "", str),
            "files": load_ui_font_files(),
        }

    def _restore_ui_color_snapshot(self) -> None:
        snapshot = getattr(self, "_ui_color_snapshot", None)
        if not snapshot:
            return
        save_setting_value("ui_colors_enabled", int(snapshot["enabled"]))
        save_setting_value("ui_colors_light", snapshot["light"])
        save_setting_value("ui_colors_dark", snapshot["dark"])
        parent = self.parent()
        if parent is not None and hasattr(parent, "_apply_ui_theme"):
            parent._apply_ui_theme()
        self._apply_global_style()
        self.update()

    def _restore_ui_font_snapshot(self) -> None:
        snapshot = getattr(self, "_ui_font_snapshot", None)
        if not snapshot:
            return
        save_setting_value("ui_font_family", snapshot["family"])
        save_ui_font_files(snapshot["files"])
        self._ui_font_files = list(snapshot["files"])
        register_ui_font_files(self._ui_font_files)
        if hasattr(self, "ui_font_combo"):
            self._load_ui_font_options()
            idx = self.ui_font_combo.findData(snapshot["family"])
            self.ui_font_combo.setCurrentIndex(max(0, idx))
        self._apply_ui_font_to_app()
        parent = self.parent()
        if parent is not None and hasattr(parent, "_apply_ui_theme"):
            parent._apply_ui_theme()
        self._apply_global_style()
        self.update()

    def _update_ui_color_option_state(self, enabled: bool) -> None:
        if hasattr(self, "ui_color_tabs"):
            self.ui_color_tabs.setEnabled(enabled)
        self._apply_live_ui_colors()

    def _current_ui_color_mode(self) -> str:
        return "dark" if self.ui_color_tabs.currentIndex() == 1 else "light"

    def _collect_ui_colors(self, mode: str) -> dict[str, str]:
        colors: dict[str, str] = {}
        for key, picker in self._ui_color_inputs[mode].items():
            color = picker.color()
            if color:
                colors[key] = color
        return colors

    def _apply_ui_colors_to_mode(self, mode: str, colors: dict[str, str]) -> None:
        defaults = get_default_ui_colors(mode == "dark")
        defaults.update(colors)
        for key, picker in self._ui_color_inputs[mode].items():
            picker.setColor(defaults.get(key, ""))

    def _reset_ui_colors_current_tab(self) -> None:
        mode = self._current_ui_color_mode()
        defaults = get_default_ui_colors(mode == "dark")
        for key, picker in self._ui_color_inputs[mode].items():
            picker.setColor(defaults.get(key, ""))
        self._apply_live_ui_colors()

    def _refresh_ui_preset_list(self) -> None:
        if not hasattr(self, "ui_preset_combo"):
            return
        mode = self._current_ui_color_mode()
        presets = load_ui_color_presets(mode)
        self.ui_preset_combo.blockSignals(True)
        self.ui_preset_combo.clear()
        self.ui_preset_combo.addItem("（未選択）")
        for name in sorted(presets.keys()):
            self.ui_preset_combo.addItem(name)
        self.ui_preset_combo.blockSignals(False)

    def _save_ui_preset(self) -> None:
        mode = self._current_ui_color_mode()
        name = self.ui_preset_name_input.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "確認", "プリセット名を入力してください。")
            return
        presets = load_ui_color_presets(mode)
        presets[name] = self._collect_ui_colors(mode)
        save_ui_color_presets(mode, presets)
        self._refresh_ui_preset_list()
        self.ui_preset_name_input.clear()

    def _apply_ui_preset(self) -> None:
        mode = self._current_ui_color_mode()
        name = self.ui_preset_combo.currentText()
        if not name or name == "（未選択）":
            return
        presets = load_ui_color_presets(mode)
        colors = presets.get(name)
        if not colors:
            return
        self._apply_ui_colors_to_mode(mode, colors)
        self._apply_live_ui_colors()

    def _load_ui_font_options(self) -> None:
        if not hasattr(self, "ui_font_combo"):
            return
        current = self.ui_font_combo.currentData()
        self.ui_font_combo.blockSignals(True)
        self.ui_font_combo.clear()
        self.ui_font_combo.addItem("システム既定", "")
        for family in sorted(QtGui.QFontDatabase.families()):
            self.ui_font_combo.addItem(family, family)
        if current:
            idx = self.ui_font_combo.findData(current)
            if idx >= 0:
                self.ui_font_combo.setCurrentIndex(idx)
        self.ui_font_combo.blockSignals(False)

    def _import_ui_font(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "フォントファイルを選択",
            "",
            "Font Files (*.ttf *.otf *.ttc);;All Files (*)",
        )
        if not paths:
            return
        new_paths = [path for path in paths if path not in self._ui_font_files]
        if not new_paths:
            return
        families = register_ui_font_files(new_paths)
        self._ui_font_files.extend(new_paths)
        self._load_ui_font_options()
        if families:
            idx = self.ui_font_combo.findData(families[0])
            if idx >= 0:
                self.ui_font_combo.setCurrentIndex(idx)
        self._apply_live_ui_font()

    def _delete_ui_preset(self) -> None:
        mode = self._current_ui_color_mode()
        name = self.ui_preset_combo.currentText()
        if not name or name == "（未選択）":
            return
        presets = load_ui_color_presets(mode)
        if name in presets:
            del presets[name]
            save_ui_color_presets(mode, presets)
            self._refresh_ui_preset_list()

    def _apply_live_ui_colors(self) -> None:
        if self._suppress_ui_color_preview:
            return
        save_setting_value("ui_colors_enabled", int(self.ui_custom_colors_input.isChecked()))
        for mode in ("light", "dark"):
            colors = self._collect_ui_colors(mode)
            save_setting_value(f"ui_colors_{mode}", serialize_ui_colors(colors))
        parent = self.parent()
        if parent is not None and hasattr(parent, "_apply_ui_theme"):
            parent._apply_ui_theme()
        self._apply_global_style()
        self.update()

    def _apply_ui_font_to_app(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        family = ""
        if hasattr(self, "ui_font_combo"):
            family = str(self.ui_font_combo.currentData() or "")
        if family:
            app.setFont(QtGui.QFont(family))
        else:
            app.setFont(QtGui.QFont())

    def _apply_live_ui_font(self) -> None:
        if self._suppress_ui_font_preview:
            return
        if hasattr(self, "ui_font_combo"):
            save_setting_value("ui_font_family", str(self.ui_font_combo.currentData() or ""))
        save_ui_font_files(self._ui_font_files)
        self._apply_ui_font_to_app()
        parent = self.parent()
        if parent is not None and hasattr(parent, "_apply_ui_theme"):
            parent._apply_ui_theme()
        self._apply_global_style()
        self.update()

    def _on_auto_compress_profile_changed(self) -> None:
        if getattr(self, "_suppress_auto_compress_profile_apply", False):
            return
        profile = str(self.auto_compress_profile_input.currentData() or "custom")
        self._apply_auto_compress_profile(profile)

    def _apply_auto_compress_profile(self, profile: str) -> None:
        presets = {
            "long": {
                "preset": "slow",
                "max_height": 480,
                "video_bitrate": 800,
                "audio_bitrate": 96,
            },
            "medium": {
                "preset": "medium",
                "max_height": 720,
                "video_bitrate": 1500,
                "audio_bitrate": 128,
            },
            "short": {
                "preset": "fast",
                "max_height": 1080,
                "video_bitrate": 3000,
                "audio_bitrate": 160,
            },
        }
        config = presets.get(profile)
        if not config:
            return
        preset_index = self.auto_compress_preset_input.findData(config["preset"])
        if preset_index >= 0:
            self.auto_compress_preset_input.setCurrentIndex(preset_index)
        height_index = self.auto_compress_resolution_input.findData(config["max_height"])
        if height_index >= 0:
            self.auto_compress_resolution_input.setCurrentIndex(height_index)
        self.auto_compress_video_bitrate_input.setValue(int(config["video_bitrate"]))
        self.auto_compress_audio_bitrate_input.setValue(int(config["audio_bitrate"]))

    def reject(self) -> None:
        self._restore_ui_color_snapshot()
        self._restore_ui_font_snapshot()
        QtWidgets.QDialog.reject(self)

    # --- Loading & Saving Logic ---

    def _load_settings(self) -> None:
        self.output_dir_input.setText(load_setting_value("output_dir", "recordings", str))
        
        fmt = load_setting_value("output_format", DEFAULT_OUTPUT_FORMAT, str).lower()
        idx = self.output_format_input.findData(fmt)
        if idx < 0: idx = self.output_format_input.findData(DEFAULT_OUTPUT_FORMAT)
        self.output_format_input.setCurrentIndex(max(0, idx))

        self.output_date_folder_input.setChecked(load_bool_setting("output_date_folder_enabled", False))
        self.output_filename_with_channel_input.setChecked(load_bool_setting("output_filename_with_channel", False))

        self.retry_count_input.setValue(load_setting_value("retry_count", DEFAULT_RETRY_COUNT, int))
        self.retry_wait_input.setValue(load_setting_value("retry_wait", DEFAULT_RETRY_WAIT_SEC, int))
        self.http_timeout_input.setValue(load_setting_value("http_timeout", 20, int))
        self.stream_timeout_input.setValue(load_setting_value("stream_timeout", 60, int))
        self.preview_volume_input.setValue(load_setting_value("preview_volume", 0.5, float))
        self.ui_custom_colors_input.setChecked(load_bool_setting("ui_colors_enabled", False))
        for mode in ("light", "dark"):
            values = get_ui_color_edit_values(mode)
            for key, picker in self._ui_color_inputs[mode].items():
                picker.setColor(values.get(key, ""))
        self._update_ui_color_option_state(bool(self.ui_custom_colors_input.isChecked()))
        self._refresh_ui_preset_list()
        font_family = load_setting_value("ui_font_family", "", str).strip()
        if hasattr(self, "ui_font_combo"):
            idx = self.ui_font_combo.findData(font_family)
            if idx < 0 and font_family:
                self.ui_font_combo.addItem(font_family, font_family)
                idx = self.ui_font_combo.findData(font_family)
            self.ui_font_combo.setCurrentIndex(max(0, idx))
        self.keep_ts_input.setChecked(load_bool_setting("keep_ts_file", False))
        self.recording_max_size_input.setValue(load_setting_value("recording_max_size_mb", DEFAULT_RECORDING_MAX_SIZE_MB, int))
        self.recording_size_margin_input.setValue(load_setting_value("recording_size_margin_mb", DEFAULT_RECORDING_SIZE_MARGIN_MB, int))
        self.auto_compress_enabled_input.setChecked(load_bool_setting("auto_compress_enabled", False))
        profile = load_setting_value("auto_compress_profile", "custom", str).lower()
        profile_index = self.auto_compress_profile_input.findData(profile)
        if profile_index < 0:
            profile_index = self.auto_compress_profile_input.findData("custom")
        self.auto_compress_profile_input.setCurrentIndex(max(0, profile_index))
        codec = load_setting_value("auto_compress_codec", "libx265", str).lower()
        codec_index = self.auto_compress_codec_input.findData(codec)
        if codec_index < 0:
            codec_index = 0
        self.auto_compress_codec_input.setCurrentIndex(codec_index)
        preset = load_setting_value("auto_compress_preset", "medium", str).lower()
        preset_index = self.auto_compress_preset_input.findData(preset)
        if preset_index < 0:
            preset_index = 1
        self.auto_compress_preset_input.setCurrentIndex(preset_index)
        max_height = load_setting_value("auto_compress_max_height", DEFAULT_AUTO_COMPRESS_MAX_HEIGHT, int)
        height_index = self.auto_compress_resolution_input.findData(max_height)
        if height_index < 0:
            height_index = 0
        self.auto_compress_resolution_input.setCurrentIndex(height_index)
        self.auto_compress_fps_input.setValue(load_setting_value("auto_compress_fps", DEFAULT_AUTO_COMPRESS_FPS, int))
        self.auto_compress_video_bitrate_input.setValue(load_setting_value("auto_compress_video_bitrate_kbps", 2500, int))
        self.auto_compress_audio_bitrate_input.setValue(load_setting_value("auto_compress_audio_bitrate_kbps", 128, int))
        self.auto_compress_keep_original_input.setChecked(load_bool_setting("auto_compress_keep_original", True))
        self.watermark_enabled_input.setChecked(load_bool_setting("watermark_enabled", False))
        self.timeshift_segment_hours_input.setValue(
            load_setting_value("timeshift_segment_hours", DEFAULT_TIMESHIFT_SEGMENT_HOURS, int)
        )
        self.timeshift_segment_minutes_input.setValue(
            load_setting_value("timeshift_segment_minutes", DEFAULT_TIMESHIFT_SEGMENT_MINUTES, int)
        )
        self.timeshift_segment_seconds_input.setValue(
            load_setting_value("timeshift_segment_seconds", DEFAULT_TIMESHIFT_SEGMENT_SECONDS, int)
        )
        
        self.tray_enabled_input.setChecked(load_bool_setting("tray_enabled", False))
        self.auto_start_input.setChecked(load_bool_setting("auto_start_enabled", False))
        
        self.auto_enabled_input.setChecked(load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED))
        self.auto_startup_input.setChecked(load_bool_setting("auto_startup_recording", True))
        self.auto_notify_only_input.setChecked(load_bool_setting("auto_notify_only", False))
        self.auto_check_interval_input.setValue(load_setting_value("auto_check_interval", DEFAULT_AUTO_CHECK_INTERVAL_SEC, int))
        self._update_auto_record_option_state(bool(self.auto_enabled_input.isChecked()))

        self.log_panel_visible_input.setChecked(load_bool_setting("log_panel_visible", False))

        self.twitcasting_input.setPlainText(load_setting_value("twitcasting_entries", DEFAULT_TWITCASTING_ENTRIES, str))
        self.niconico_input.setPlainText(load_setting_value("niconico_entries", DEFAULT_NICONICO_ENTRIES, str))
        self.tiktok_input.setPlainText(load_setting_value("tiktok_entries", DEFAULT_TIKTOK_ENTRIES, str))
        self.fuwatch_input.setPlainText(load_setting_value("fuwatch_entries", DEFAULT_FUWATCH_ENTRIES, str))
        self.kick_input.setPlainText(load_setting_value("kick_entries", DEFAULT_KICK_ENTRIES, str))
        self.live17_input.setPlainText(load_setting_value("live17_entries", DEFAULT_LIVE17_ENTRIES, str))
        self.bigo_input.setPlainText(load_setting_value("bigo_entries", DEFAULT_BIGO_ENTRIES, str))
        self.radiko_input.setPlainText(load_setting_value("radiko_entries", DEFAULT_RADIKO_ENTRIES, str))
        self.openrectv_input.setPlainText(load_setting_value("openrectv_entries", DEFAULT_OPENRECTV_ENTRIES, str))
        self.bilibili_input.setPlainText(load_setting_value("bilibili_entries", DEFAULT_BILIBILI_ENTRIES, str))
        self.abema_input.setPlainText(load_setting_value("abema_entries", DEFAULT_ABEMA_ENTRIES, str))
        self.auto_notify_only_entries_input.setPlainText(load_setting_value("auto_notify_only_entries", "", str))
        
        self.youtube_api_key_input.setText(load_setting_value("youtube_api_key", "", str))
        self.youtube_channels_input.setPlainText(load_setting_value("youtube_channels", "", str))
        
        self.twitch_client_id_input.setText(load_setting_value("twitch_client_id", "", str))
        self.twitch_client_secret_input.setText(load_setting_value("twitch_client_secret", "", str))
        self.twitch_channels_input.setPlainText(load_setting_value("twitch_channels", "", str))
        quality = load_setting_value("recording_quality", DEFAULT_RECORDING_QUALITY, str)
        quality_index = self.recording_quality_input.findData(quality)
        if quality_index < 0:
            quality_index = self.recording_quality_input.findData(DEFAULT_RECORDING_QUALITY)
        self.recording_quality_input.setCurrentIndex(max(0, quality_index))
        youtube_backend = load_setting_value(
            "youtube_recording_backend",
            DEFAULT_YOUTUBE_RECORDING_BACKEND,
            str,
        ).lower()
        backend_index = self.youtube_backend_input.findData(youtube_backend)
        if backend_index < 0:
            backend_index = self.youtube_backend_input.findData(DEFAULT_YOUTUBE_RECORDING_BACKEND)
        self.youtube_backend_input.setCurrentIndex(max(0, backend_index))
        self._update_auto_compress_option_state(bool(self.auto_compress_enabled_input.isChecked()))

    def _save_settings(self) -> None:
        save_setting_value("output_dir", self.output_dir_input.text().strip())
        save_setting_value("output_format", str(self.output_format_input.currentData()))
        save_setting_value("output_date_folder_enabled", int(self.output_date_folder_input.isChecked()))
        save_setting_value("output_filename_with_channel", int(self.output_filename_with_channel_input.isChecked()))
        save_setting_value("retry_count", int(self.retry_count_input.value()))
        save_setting_value("retry_wait", int(self.retry_wait_input.value()))
        save_setting_value("http_timeout", int(self.http_timeout_input.value()))
        save_setting_value("stream_timeout", int(self.stream_timeout_input.value()))
        save_setting_value("preview_volume", float(self.preview_volume_input.value()))
        save_setting_value("ui_colors_enabled", int(self.ui_custom_colors_input.isChecked()))
        for mode in ("light", "dark"):
            colors: dict[str, str] = {}
            for key, picker in self._ui_color_inputs[mode].items():
                color = picker.color()
                if color:
                    colors[key] = color
            save_setting_value(f"ui_colors_{mode}", serialize_ui_colors(colors))
        if hasattr(self, "ui_font_combo"):
            save_setting_value("ui_font_family", str(self.ui_font_combo.currentData() or ""))
        save_ui_font_files(self._ui_font_files)
        self._apply_ui_font_to_app()
        self._ui_color_snapshot = self._capture_ui_color_snapshot()
        self._ui_font_snapshot = self._capture_ui_font_snapshot()
        save_setting_value("keep_ts_file", int(self.keep_ts_input.isChecked()))
        save_setting_value("recording_max_size_mb", int(self.recording_max_size_input.value()))
        save_setting_value("recording_size_margin_mb", int(self.recording_size_margin_input.value()))
        save_setting_value("auto_compress_enabled", int(self.auto_compress_enabled_input.isChecked()))
        save_setting_value("auto_compress_profile", str(self.auto_compress_profile_input.currentData()))
        save_setting_value("auto_compress_codec", str(self.auto_compress_codec_input.currentData()))
        save_setting_value("auto_compress_preset", str(self.auto_compress_preset_input.currentData()))
        save_setting_value("auto_compress_max_height", int(self.auto_compress_resolution_input.currentData()))
        save_setting_value("auto_compress_fps", int(self.auto_compress_fps_input.value()))
        save_setting_value("auto_compress_video_bitrate_kbps", int(self.auto_compress_video_bitrate_input.value()))
        save_setting_value("auto_compress_audio_bitrate_kbps", int(self.auto_compress_audio_bitrate_input.value()))
        save_setting_value("auto_compress_keep_original", int(self.auto_compress_keep_original_input.isChecked()))
        save_setting_value("watermark_enabled", int(self.watermark_enabled_input.isChecked()))
        save_setting_value("timeshift_segment_hours", int(self.timeshift_segment_hours_input.value()))
        save_setting_value("timeshift_segment_minutes", int(self.timeshift_segment_minutes_input.value()))
        save_setting_value("timeshift_segment_seconds", int(self.timeshift_segment_seconds_input.value()))
        
        save_setting_value("tray_enabled", int(self.tray_enabled_input.isChecked()))
        save_setting_value("auto_start_enabled", int(self.auto_start_input.isChecked()))
        
        save_setting_value("auto_enabled", int(self.auto_enabled_input.isChecked()))
        save_setting_value("auto_startup_recording", int(self.auto_startup_input.isChecked()))
        save_setting_value("auto_notify_only", int(self.auto_notify_only_input.isChecked()))
        save_setting_value("auto_check_interval", int(self.auto_check_interval_input.value()))
        
        save_setting_value("log_panel_visible", int(self.log_panel_visible_input.isChecked()))
        
        save_setting_value("twitcasting_entries", self.twitcasting_input.toPlainText().strip())
        save_setting_value("niconico_entries", self.niconico_input.toPlainText().strip())
        save_setting_value("tiktok_entries", self.tiktok_input.toPlainText().strip())
        save_setting_value("fuwatch_entries", self.fuwatch_input.toPlainText().strip())
        save_setting_value("kick_entries", self.kick_input.toPlainText().strip())
        save_setting_value("live17_entries", self.live17_input.toPlainText().strip())
        save_setting_value("bigo_entries", self.bigo_input.toPlainText().strip())
        save_setting_value("radiko_entries", self.radiko_input.toPlainText().strip())
        save_setting_value("openrectv_entries", self.openrectv_input.toPlainText().strip())
        save_setting_value("bilibili_entries", self.bilibili_input.toPlainText().strip())
        save_setting_value("abema_entries", self.abema_input.toPlainText().strip())
        save_setting_value("auto_notify_only_entries", self.auto_notify_only_entries_input.toPlainText().strip())
        
        save_setting_value("youtube_api_key", self.youtube_api_key_input.text().strip())
        save_setting_value("youtube_channels", self.youtube_channels_input.toPlainText().strip())
        
        save_setting_value("twitch_client_id", self.twitch_client_id_input.text().strip())
        save_setting_value("twitch_client_secret", self.twitch_client_secret_input.text().strip())
        save_setting_value("twitch_channels", self.twitch_channels_input.toPlainText().strip())
        save_setting_value("recording_quality", str(self.recording_quality_input.currentData()))
        save_setting_value("youtube_recording_backend", str(self.youtube_backend_input.currentData()))
        parent = self.parent()
        if parent is not None:
            if hasattr(parent, "_load_settings_to_ui"):
                parent._load_settings_to_ui()
            if hasattr(parent, "_configure_auto_monitor"):
                parent._configure_auto_monitor()
            if hasattr(parent, "_apply_tray_setting"):
                parent._apply_tray_setting(True)
            if hasattr(parent, "_apply_startup_setting"):
                parent._apply_startup_setting(True)
            if hasattr(parent, "_apply_log_panel_visibility"):
                parent._apply_log_panel_visibility()
            if hasattr(parent, "_apply_ui_theme"):
                parent._apply_ui_theme()
        self._apply_global_style()
        self.update()
        QtWidgets.QMessageBox.information(self, "情報", "設定を保存しました。")

    def _browse_output_dir(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "出力フォルダを選択")
        if directory:
            self.output_dir_input.setText(directory)

    def _browse_watermark_file(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "ロゴ画像を選択",
            "",
            "画像ファイル (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if file_path:
            self.watermark_path_input.setText(file_path)

    def _open_watermark_dialog(self) -> None:
        dialog = WatermarkDialog(self)
        if dialog.exec():
            self._load_settings()

    def _update_auto_record_option_state(self, enabled: bool) -> None:
        self.auto_startup_input.setEnabled(True)

    def _update_auto_compress_option_state(self, enabled: bool) -> None:
        widgets = [
            self.auto_compress_profile_input,
            self.auto_compress_codec_input,
            self.auto_compress_preset_input,
            self.auto_compress_resolution_input,
            self.auto_compress_fps_input,
            self.auto_compress_video_bitrate_input,
            self.auto_compress_audio_bitrate_input,
            self.auto_compress_keep_original_input,
        ]
        for widget in widgets:
            widget.setEnabled(True)
