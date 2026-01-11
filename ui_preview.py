# -*- coding: utf-8 -*-
from __future__ import annotations
import datetime as dt
import subprocess
import tempfile
import threading
import hashlib
from pathlib import Path
from typing import Optional
from PyQt6 import QtCore, QtGui, QtMultimedia, QtMultimediaWidgets, QtWidgets
from streamlink import Streamlink
from streamlink.exceptions import StreamlinkError
from config import (
    DEFAULT_QUALITY,
    DEFAULT_TIMESHIFT_SEGMENT_HOURS,
    DEFAULT_TIMESHIFT_SEGMENT_MINUTES,
    DEFAULT_TIMESHIFT_SEGMENT_SECONDS,
    OUTPUT_FORMAT_FLV,
    OUTPUT_FORMAT_MKV,
    OUTPUT_FORMAT_MOV,
    OUTPUT_FORMAT_MP3,
    OUTPUT_FORMAT_MP4_COPY,
    OUTPUT_FORMAT_MP4_LIGHT,
    OUTPUT_FORMAT_TS,
    OUTPUT_FORMAT_WAV,
    READ_CHUNK_SIZE,
)
from recording import find_ffmpeg_path, select_stream
from settings_store import load_setting_value
from streamlink_utils import (
    apply_streamlink_options_for_url,
    restore_streamlink_headers,
    set_streamlink_headers_for_url,
)
from url_utils import ensure_unique_path

class PreviewPipeProxy(QtCore.QObject):
    def __init__(self, process: QtCore.QProcess) -> None:
        super().__init__()
        self._process = process
        self._closed = False
    @QtCore.pyqtSlot(bytes)
    def write_data(self, data: bytes) -> None:
        if self._closed:
            return
        if self._process.state() != QtCore.QProcess.ProcessState.Running:
            return
        if self._process.write(data) == -1:
            return
        self._process.waitForBytesWritten(100)
    @QtCore.pyqtSlot()
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._process.closeWriteChannel()

class StreamlinkPreviewWorker(QtCore.QObject):
    data_signal = QtCore.pyqtSignal(bytes)
    log_signal = QtCore.pyqtSignal(str)
    finished_signal = QtCore.pyqtSignal()
    def __init__(self, url: str, stop_event: threading.Event) -> None:
        super().__init__()
        self._url = url
        self._stop_event = stop_event
    def run(self) -> None:
        stream_io = None
        session = Streamlink()
        http_timeout = load_setting_value("http_timeout", 20, int)
        stream_timeout = load_setting_value("stream_timeout", 60, int)
        session.set_option("http-timeout", int(http_timeout))
        session.set_option("stream-timeout", int(stream_timeout))
        apply_streamlink_options_for_url(session, self._url)
        original_headers = dict(session.http.headers)
        try:
            original_headers = set_streamlink_headers_for_url(session, self._url)
            streams = session.streams(self._url)
            if not streams:
                self.log_signal.emit("プレビュー用ストリームが見つかりませんでした。")
                return
            stream = select_stream(streams, DEFAULT_QUALITY)
            stream_io = stream.open()
            while not self._stop_event.is_set():
                data = stream_io.read(READ_CHUNK_SIZE)
                if not data:
                    break
                self.data_signal.emit(data)
        except StreamlinkError as exc:
            self.log_signal.emit(f"プレビュー用ストリーム取得に失敗しました: {exc}")
        except Exception as exc:
            self.log_signal.emit(f"プレビュー用ストリーム読み込みに失敗しました: {exc}")
        finally:
            restore_streamlink_headers(session, original_headers)
            if stream_io is not None and hasattr(stream_io, "close"):
                try:
                    stream_io.close()
                except Exception:
                    pass
            self.finished_signal.emit()

class TimeShiftWindow(QtWidgets.QDialog):
    def __init__(self, recording_path: Path, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._recording_path = Path(recording_path)
        self._playback_path: Path | None = None
        self._temp_mp4_path: Path | None = None
        self._use_temp_mp4 = False
        self._temp_mp4_offset_ms = 0
        self._temp_mp4_range: tuple[int, int] | None = None
        self._temp_mp4_is_copy = False
        self._temp_mp4_retry = False
        self._was_playing_before_seek = False
        self._proxy_process: QtCore.QProcess | None = None
        self._proxy_target_range: tuple[int, int] | None = None
        self._proxy_mp4_path: Path | None = None
        self._temp_files: set[Path] = set()
        self._dragging_slider = False
        self._clips: list[tuple[int, int]] = []
        self._segment_ranges: list[tuple[int, int]] = []
        self._segment_playback: tuple[int, int] | None = None
        self._last_duration_ms = 0
        self._recording_duration_ms = 0
        self._mp4_converted_segments: set[tuple[int, int]] = set()
        self._mp4_converted_all = False
        self._segment_hours = load_setting_value(
            "timeshift_segment_hours",
            DEFAULT_TIMESHIFT_SEGMENT_HOURS,
            int,
        )
        self._segment_minutes = load_setting_value(
            "timeshift_segment_minutes",
            DEFAULT_TIMESHIFT_SEGMENT_MINUTES,
            int,
        )
        self._segment_seconds = load_setting_value(
            "timeshift_segment_seconds",
            DEFAULT_TIMESHIFT_SEGMENT_SECONDS,
            int,
        )
        self._segment_duration_ms = self._resolve_segment_duration_ms()
        self.setWindowTitle("クリップ作成ツール")
        self.setMinimumSize(800, 500)
        self._apply_theme()
        self._build_ui()
        self._connect_player_signals()
        self._apply_source_and_play()

    def _apply_theme(self):
        palette = QtGui.QGuiApplication.palette()
        is_dark = palette.color(QtGui.QPalette.ColorRole.Window).lightness() < 128
        if is_dark:
            dialog_bg = "#0f172a"
            control_bg = "#1e293b"
            control_border = "#334155"
            base_text = "#e2e8f0"
            muted_text = "#94a3b8"
            primary = "#0ea5e9"
            primary_hover = "#0284c7"
            ghost_bg = "#1e293b"
            ghost_hover = "#334155"
            danger_bg = "#3f1d1d"
            danger_hover = "#7f1d1d"
            panel_bg = "#0b1220"
            panel_border = "#1f2a44"
            input_bg = "#111827"
            input_border = "#334155"
            list_bg = "#0f172a"
            list_item_bg = "#111827"
            list_item_border = "#1f2a44"
            list_item_selected = "#0b2a3a"
        else:
            dialog_bg = "#f8fafc"
            control_bg = "#ffffff"
            control_border = "#e2e8f0"
            base_text = "#1e293b"
            muted_text = "#64748b"
            primary = "#0ea5e9"
            primary_hover = "#0284c7"
            ghost_bg = "#e2e8f0"
            ghost_hover = "#cbd5e1"
            danger_bg = "#fee2e2"
            danger_hover = "#fecaca"
            panel_bg = "#ffffff"
            panel_border = "#e2e8f0"
            input_bg = "#ffffff"
            input_border = "#cbd5e1"
            list_bg = "#f8fafc"
            list_item_bg = "#ffffff"
            list_item_border = "#e2e8f0"
            list_item_selected = "#e0f2fe"
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {dialog_bg};
                color: {base_text};
                font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
            }}
            QFrame#ControlBar {{
                background-color: {control_bg};
                border-top: 1px solid {control_border};
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                color: {base_text};
                font-weight: bold;
                font-size: 13px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {control_border};
                color: {base_text};
            }}
            QPushButton#PrimaryButton {{
                background-color: {primary};
                color: #ffffff;
            }}
            QPushButton#PrimaryButton:hover {{
                background-color: {primary_hover};
            }}
            QPushButton#GhostButton {{
                background-color: {ghost_bg};
                color: {base_text};
            }}
            QPushButton#GhostButton:hover {{
                background-color: {ghost_hover};
            }}
            QPushButton#DangerButton {{
                background-color: {danger_bg};
                color: {base_text};
            }}
            QPushButton#DangerButton:hover {{
                background-color: {danger_hover};
                color: {base_text};
            }}
            QLabel {{
                color: {muted_text};
                font-family: monospace;
                font-size: 13px;
                font-weight: bold;
            }}
            QLabel#SectionTitle {{
                color: {base_text};
                font-size: 13px;
                font-weight: bold;
                letter-spacing: 0.5px;
            }}
            QSlider::groove:horizontal {{
                border: 1px solid {control_border};
                height: 6px;
                background: {control_bg};
                margin: 2px 0;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {primary};
                border: 1px solid {primary};
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {primary_hover};
            }}
            QSlider::sub-page:horizontal {{
                background: {primary};
                border-radius: 3px;
            }}
            QFrame#ClipPanel {{
                background-color: {panel_bg};
                border-top: 1px solid {panel_border};
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }}
            QLineEdit, QComboBox {{
                background-color: {input_bg};
                color: {base_text};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 2px solid {primary};
                padding: 5px 9px;
            }}
            QListWidget {{
                background-color: {list_bg};
                border: none;
                border-radius: 8px;
                padding: 6px;
                outline: none;
            }}
            QListWidget::item {{
                background-color: {list_item_bg};
                border: 1px solid {list_item_border};
                border-radius: 6px;
                padding: 8px;
                margin-bottom: 6px;
                color: {base_text};
            }}
            QListWidget::item:selected {{
                border: 1px solid {primary};
                background-color: {list_item_selected};
                color: {primary};
                font-weight: bold;
            }}
            QListWidget::item:focus {{
                outline: none;
            }}
        """)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 映像エリア
        self._video_widget = QtMultimediaWidgets.QVideoWidget(self)
        self._video_widget.setStyleSheet("background-color: #000000;")
        self._video_widget.setMinimumHeight(220)
        self._video_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(self._video_widget)
        
        # コントロールバー
        controls = QtWidgets.QFrame()
        controls.setObjectName("ControlBar")
        controls.setFixedHeight(80) # 高さを確保
        c_layout = QtWidgets.QVBoxLayout(controls)
        c_layout.setContentsMargins(20, 10, 20, 10)
        c_layout.setSpacing(4)
        
        # 上段：シークバー
        self._position_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
        self._position_slider.setRange(0, 0)
        self._position_slider.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        c_layout.addWidget(self._position_slider)
        
        # 下段：ボタンと時間
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(12)
        
        self._play_button = QtWidgets.QPushButton("一時停止")
        self._play_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._play_button.setMinimumWidth(80)
        
        self._reload_button = QtWidgets.QPushButton("最新に更新")
        self._reload_button.setObjectName("PrimaryButton")
        self._reload_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        self._position_label = QtWidgets.QLabel("00:00 / 00:00")
        self._position_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        
        btn_row.addWidget(self._play_button)
        btn_row.addWidget(self._reload_button)
        btn_row.addStretch(1)
        btn_row.addWidget(self._position_label)
        
        c_layout.addLayout(btn_row)
        layout.addWidget(controls)

        # クリップ操作パネル
        clip_panel = QtWidgets.QFrame()
        clip_panel.setObjectName("ClipPanel")
        clip_layout = QtWidgets.QVBoxLayout(clip_panel)
        clip_layout.setContentsMargins(20, 12, 20, 12)
        clip_layout.setSpacing(10)

        segment_title = QtWidgets.QLabel(self._segment_label_text())
        segment_title.setObjectName("SectionTitle")
        clip_layout.addWidget(segment_title)

        segment_row = QtWidgets.QHBoxLayout()
        segment_row.setSpacing(10)
        self._segment_list = QtWidgets.QListWidget()
        self._segment_list.setMinimumHeight(180)
        self._segment_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self._segment_list.itemSelectionChanged.connect(self._apply_selected_segment)
        self._segment_mp4_btn = QtWidgets.QPushButton("選択をMP4変換")
        self._segment_mp4_btn.setToolTip("選択した区間を一時MP4に変換して再生します。")
        self._segment_mp4_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._segment_mp4_btn.setObjectName("GhostButton")
        self._segment_mp4_btn.clicked.connect(self._convert_to_temp_mp4)
        segment_btns = QtWidgets.QVBoxLayout()
        segment_btns.setSpacing(8)
        segment_btns.addWidget(self._segment_mp4_btn)
        segment_btns.addStretch(1)
        segment_row.addWidget(self._segment_list, 1)
        segment_row.addLayout(segment_btns)
        clip_layout.addLayout(segment_row)

        clip_title = QtWidgets.QLabel("クリップ作成")
        clip_title.setObjectName("SectionTitle")
        clip_layout.addWidget(clip_title)

        version_label = QtWidgets.QLabel("v1.0.0 beta")
        version_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        version_label.setStyleSheet("font-weight: normal;")
        clip_layout.addWidget(version_label)

        clip_row = QtWidgets.QHBoxLayout()
        clip_row.setSpacing(10)

        self._clip_start_input = QtWidgets.QLineEdit()
        self._clip_start_input.setPlaceholderText("開始 MM:SS")
        self._clip_start_input.setFixedWidth(140)

        self._clip_end_input = QtWidgets.QLineEdit()
        self._clip_end_input.setPlaceholderText("終了 MM:SS")
        self._clip_end_input.setFixedWidth(140)

        self._clip_start_btn = QtWidgets.QPushButton("開始")
        self._clip_start_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_start_btn.clicked.connect(self._set_clip_start_from_current)
        self._clip_start_btn.setObjectName("GhostButton")

        self._clip_end_btn = QtWidgets.QPushButton("終了")
        self._clip_end_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_end_btn.clicked.connect(self._set_clip_end_from_current)
        self._clip_end_btn.setObjectName("GhostButton")

        self._clip_add_btn = QtWidgets.QPushButton("追加")
        self._clip_add_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_add_btn.clicked.connect(self._add_clip)
        self._clip_add_btn.setObjectName("PrimaryButton")

        clip_row.addWidget(self._clip_start_btn)
        clip_row.addWidget(self._clip_start_input)
        clip_row.addWidget(self._clip_end_btn)
        clip_row.addWidget(self._clip_end_input)
        clip_row.addWidget(self._clip_add_btn)
        clip_row.addStretch(1)

        format_row = QtWidgets.QHBoxLayout()
        format_row.setSpacing(10)
        format_label = QtWidgets.QLabel("保存形式")
        format_label.setObjectName("SectionTitle")
        self._clip_format = QtWidgets.QComboBox()
        self._clip_format.addItems([
            "TS",
            "MP4 (高速コピー)",
            "MP4 (再エンコード・軽量)",
            "MOV",
            "FLV",
            "MKV",
            "MP3",
            "WAV",
        ])
        self._clip_format.setItemData(0, OUTPUT_FORMAT_TS)
        self._clip_format.setItemData(1, OUTPUT_FORMAT_MP4_COPY)
        self._clip_format.setItemData(2, OUTPUT_FORMAT_MP4_LIGHT)
        self._clip_format.setItemData(3, OUTPUT_FORMAT_MOV)
        self._clip_format.setItemData(4, OUTPUT_FORMAT_FLV)
        self._clip_format.setItemData(5, OUTPUT_FORMAT_MKV)
        self._clip_format.setItemData(6, OUTPUT_FORMAT_MP3)
        self._clip_format.setItemData(7, OUTPUT_FORMAT_WAV)
        current_format = load_setting_value("output_format", OUTPUT_FORMAT_MP4_COPY, str)
        idx = self._clip_format.findData(str(current_format))
        if idx >= 0:
            self._clip_format.setCurrentIndex(idx)

        self._clip_save_selected = QtWidgets.QPushButton("選択を保存")
        self._clip_save_selected.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_save_selected.clicked.connect(self._export_selected_clips)
        self._clip_save_selected.setObjectName("GhostButton")

        self._clip_save_all = QtWidgets.QPushButton("すべて保存")
        self._clip_save_all.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_save_all.clicked.connect(self._export_all_clips)
        self._clip_save_all.setObjectName("PrimaryButton")

        self._clip_remove_btn = QtWidgets.QPushButton("削除")
        self._clip_remove_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_remove_btn.clicked.connect(self._remove_selected_clips)
        self._clip_remove_btn.setObjectName("DangerButton")

        format_row.addWidget(format_label)
        format_row.addWidget(self._clip_format, 1)
        format_row.addWidget(self._clip_save_selected)
        format_row.addWidget(self._clip_save_all)
        format_row.addWidget(self._clip_remove_btn)

        self._clip_list = QtWidgets.QListWidget()
        self._clip_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)

        clip_layout.addLayout(clip_row)
        clip_layout.addLayout(format_row)
        clip_layout.addWidget(self._clip_list)
        layout.addWidget(clip_panel)
        layout.setStretch(0, 3)
        layout.setStretch(1, 0)
        layout.setStretch(2, 2)
        
        # プレイヤー設定
        self._audio_output = QtMultimedia.QAudioOutput(self)
        self._player = QtMultimedia.QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video_widget)
        
        # イベント接続
        self._play_button.clicked.connect(self._toggle_playback)
        self._reload_button.clicked.connect(self._reload_media)
        self._position_slider.sliderPressed.connect(self._on_slider_pressed)
        self._position_slider.sliderReleased.connect(self._on_slider_released)
        self._position_slider.sliderMoved.connect(self._on_slider_moved)

    def _connect_player_signals(self) -> None:
        self._player.positionChanged.connect(self._update_position)
        self._player.durationChanged.connect(self._update_duration)
        self._player.playbackStateChanged.connect(self._update_play_button_text)
        self._player.errorOccurred.connect(self._on_player_error)
        self._player.mediaStatusChanged.connect(self._on_media_status)

    def _apply_source_and_play(self) -> None:
        if not self._recording_path.exists():
            QtWidgets.QMessageBox.information(self, "情報", "録画ファイルが見つかりません。")
            return
        if self._recording_path.stat().st_size <= 0:
            QtWidgets.QMessageBox.information(self, "情報", "録画ファイルがまだ作成中です。")
            return
        playback_path = self._prepare_timeshift_source(self._recording_path, force=True)
        self._playback_path = playback_path
        file_url = QtCore.QUrl.fromLocalFile(str(playback_path))
        self._player.setSource(file_url)
        self._player.play()

    def _toggle_playback(self) -> None:
        state = self._player.playbackState()
        if state == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _reload_media(self) -> None:
        if not self._recording_path.exists():
            QtWidgets.QMessageBox.information(self, "情報", "録画ファイルが見つかりません。")
            return
        current_pos = int(self._player.position())
        playback_path = self._prepare_timeshift_source(self._recording_path, force=True)
        self._playback_path = playback_path
        file_url = QtCore.QUrl.fromLocalFile(str(playback_path))
        self._player.setSource(file_url)
        self._player.play()
        QtCore.QTimer.singleShot(
            500,
            lambda: self._player.setPosition(current_pos),
        )

    def _on_slider_pressed(self) -> None:
        self._dragging_slider = True
        self._was_playing_before_seek = (
            self._player.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState
        )

    def _on_slider_released(self) -> None:
        self._dragging_slider = False
        self._player.setPosition(int(self._position_slider.value()))
        if self._was_playing_before_seek and (
            self._player.playbackState() != QtMultimedia.QMediaPlayer.PlaybackState.PlayingState
        ):
            self._player.play()

    def _on_slider_moved(self, value: int) -> None:
        position = int(value)
        self._position_label.setText(self._format_position(position, int(self._player.duration())))
        if self._dragging_slider:
            self._player.setPosition(position)
            if self._was_playing_before_seek and (
                self._player.playbackState() != QtMultimedia.QMediaPlayer.PlaybackState.PlayingState
            ):
                self._player.play()

    def _update_position(self, position: int) -> None:
        if self._dragging_slider:
            return
        self._position_slider.setValue(int(position))
        segment = None if self._use_temp_mp4 else self._segment_playback
        if segment:
            start_ms, end_ms = segment
            total_ms = max(0, end_ms - start_ms)
            current_ms = max(0, min(total_ms, int(position) - start_ms))
            self._position_label.setText(self._format_position(current_ms, total_ms))
        else:
            self._position_label.setText(self._format_position(int(position), int(self._player.duration())))
        if position >= self._position_slider.maximum():
            self._player.pause()

    def _update_duration(self, duration: int) -> None:
        duration_ms = max(0, int(duration))
        if self._temp_mp4_path is None and duration_ms > 0:
            self._recording_duration_ms = duration_ms
        base_duration_ms = duration_ms
        if self._temp_mp4_path and self._recording_duration_ms > 0:
            base_duration_ms = self._recording_duration_ms
        if self._segment_playback is None:
            self._position_slider.setRange(0, duration_ms)
            self._position_label.setText(self._format_position(int(self._player.position()), duration_ms))
        self._maybe_refresh_segments(base_duration_ms)

    def _update_play_button_text(self, state: QtMultimedia.QMediaPlayer.PlaybackState) -> None:
        if state == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
            self._play_button.setText("一時停止")
        else:
            self._play_button.setText("再生")

    def _on_player_error(self, error: QtMultimedia.QMediaPlayer.Error) -> None:
        if error == QtMultimedia.QMediaPlayer.Error.NoError:
            return
        details = self._player.errorString() or "不明なエラー"
        if self._use_temp_mp4 and self._temp_mp4_is_copy and not self._temp_mp4_retry:
            self._temp_mp4_retry = True
            self._player.stop()
            self._player.setSource(QtCore.QUrl())
            if self._reencode_temp_mp4():
                return
        self._temp_mp4_retry = False
        QtWidgets.QMessageBox.information(self, "情報", f"クリップ作成ツールでの再生に失敗しました: {details}")

    def _on_media_status(self, status: QtMultimedia.QMediaPlayer.MediaStatus) -> None:
        if status == QtMultimedia.QMediaPlayer.MediaStatus.EndOfMedia:
            self._player.pause()

    def _prepare_timeshift_source(self, input_path: Path, force: bool = False) -> Path:
        if self._use_temp_mp4 and self._temp_mp4_path and self._temp_mp4_path.exists():
            return self._temp_mp4_path
        self._use_temp_mp4 = False
        return input_path

    def _register_temp_path(self, path: Path) -> None:
        self._temp_files.add(path)

    def _build_proxy_path(self, start_ms: int, end_ms: int) -> Path:
        temp_dir = Path(tempfile.gettempdir())
        base_name = self._recording_path.with_suffix("").name
        digest = hashlib.md5(str(self._recording_path).encode("utf-8")).hexdigest()[:8]
        name = f"{base_name}_proxy_{digest}_{start_ms}_{end_ms}.mp4"
        return temp_dir / name

    def _stop_proxy_process(self) -> None:
        if self._proxy_process is None:
            return
        if self._proxy_process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self._proxy_process.kill()
            self._proxy_process.waitForFinished(1000)
        self._proxy_process = None
        self._proxy_target_range = None

    def _start_proxy_for_range(self, start_ms: int, end_ms: int) -> None:
        ffmpeg_path = find_ffmpeg_path()
        if not ffmpeg_path:
            return
        duration_sec = max(0.0, (end_ms - start_ms) / 1000.0)
        if duration_sec <= 0:
            return
        proxy_path = self._build_proxy_path(start_ms, end_ms)
        self._proxy_target_range = (int(start_ms), int(end_ms))
        self._proxy_mp4_path = proxy_path
        self._register_temp_path(proxy_path)
        if proxy_path.exists():
            self._switch_to_proxy(proxy_path, start_ms, end_ms)
            return
        self._stop_proxy_process()
        process = QtCore.QProcess(self)
        self._proxy_process = process
        process.finished.connect(self._on_proxy_finished)
        args = [
            "-y",
            "-ss",
            f"{max(0.0, start_ms / 1000.0):.3f}",
            "-i",
            str(self._recording_path),
            "-t",
            f"{duration_sec:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "32",
            "-vf",
            "scale=-2:480",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(proxy_path),
        ]
        process.start(ffmpeg_path, args)

    def _on_proxy_finished(self) -> None:
        process = self._proxy_process
        target = self._proxy_target_range
        proxy_path = self._proxy_mp4_path
        self._proxy_process = None
        if process is None or target is None or proxy_path is None:
            return
        if process.exitStatus() != QtCore.QProcess.ExitStatus.NormalExit:
            return
        if process.exitCode() != 0:
            return
        selected = self._segment_list.selectedItems()
        if not selected:
            return
        start_ms, end_ms = selected[0].data(QtCore.Qt.ItemDataRole.UserRole)
        if (int(start_ms), int(end_ms)) != target:
            return
        if not proxy_path.exists():
            return
        self._switch_to_proxy(proxy_path, int(start_ms), int(end_ms))

    def _switch_to_proxy(self, proxy_path: Path, start_ms: int, end_ms: int) -> None:
        current_pos = int(self._player.position())
        relative_pos = max(0, current_pos - int(start_ms))
        self._temp_mp4_path = proxy_path
        self._use_temp_mp4 = True
        self._temp_mp4_offset_ms = int(start_ms)
        self._temp_mp4_range = (int(start_ms), int(end_ms))
        self._temp_mp4_is_copy = False
        self._temp_mp4_retry = False
        self._segment_playback = None
        file_url = QtCore.QUrl.fromLocalFile(str(proxy_path))
        self._player.setSource(file_url)
        self._player.play()
        QtCore.QTimer.singleShot(
            300,
            lambda: self._player.setPosition(relative_pos),
        )

    def _format_position(self, position_ms: int, duration_ms: int) -> str:
        return f"{self._format_time(position_ms)} / {self._format_time(duration_ms)}"

    def _format_time(self, millis: int) -> str:
        safe_millis = max(0, int(millis))
        total_seconds = safe_millis // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def _format_clock_time(self, timestamp: dt.datetime) -> str:
        return timestamp.strftime("%H:%M:%S")

    def _resolve_segment_duration_ms(self) -> int:
        hours = max(0, int(self._segment_hours))
        minutes = max(0, int(self._segment_minutes))
        seconds = max(0, int(self._segment_seconds))
        total_seconds = hours * 3600 + minutes * 60 + seconds
        if total_seconds <= 0:
            total_seconds = max(
                1,
                DEFAULT_TIMESHIFT_SEGMENT_HOURS * 3600
                + DEFAULT_TIMESHIFT_SEGMENT_MINUTES * 60
                + DEFAULT_TIMESHIFT_SEGMENT_SECONDS,
            )
        return int(total_seconds) * 1000

    def _segment_label_text(self) -> str:
        total_seconds = max(1, int(self._segment_duration_ms // 1000))
        hours, rem = divmod(total_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours}時間")
        if minutes:
            parts.append(f"{minutes}分")
        if seconds:
            parts.append(f"{seconds}秒")
        if not parts:
            parts.append("1秒")
        return f"{''.join(parts)}ごとの分割"
        return f"{seconds}秒ごとの分割"

    def _parse_time_text(self, text: str) -> Optional[int]:
        raw = text.strip()
        if not raw:
            return None
        parts = raw.split(":")
        try:
            if len(parts) == 2:
                minutes = int(parts[0])
                seconds = int(parts[1])
            elif len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1]) + hours * 60
                seconds = int(parts[2])
            else:
                return None
        except ValueError:
            return None
        if minutes < 0 or seconds < 0 or seconds >= 60:
            return None
        return (minutes * 60 + seconds) * 1000

    def _set_clip_start_from_current(self) -> None:
        current = int(self._player.position())
        self._clip_start_input.setText(self._format_time(current))

    def _set_clip_end_from_current(self) -> None:
        current = int(self._player.position())
        self._clip_end_input.setText(self._format_time(current))

    def _add_clip(self) -> None:
        start_ms = self._parse_time_text(self._clip_start_input.text())
        end_ms = self._parse_time_text(self._clip_end_input.text())
        if start_ms is None or end_ms is None:
            QtWidgets.QMessageBox.information(self, "情報", "開始/終了時刻を正しく入力してください。")
            return
        if end_ms <= start_ms:
            QtWidgets.QMessageBox.information(self, "情報", "終了は開始より後にしてください。")
            return
        self._clips.append((start_ms, end_ms))
        self._refresh_clip_list()

    def _refresh_clip_list(self) -> None:
        self._clip_list.clear()
        if not self._clips:
            placeholder = QtWidgets.QListWidgetItem("#1 00:01 → 00:08 (00:07)")
            placeholder.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            placeholder.setForeground(QtGui.QColor("#94a3b8"))
            self._clip_list.addItem(placeholder)
            return
        for index, (start_ms, end_ms) in enumerate(self._clips, start=1):
            duration_ms = max(0, end_ms - start_ms)
            item_text = (
                f"#{index} {self._format_time(start_ms)} → {self._format_time(end_ms)} "
                f"({self._format_time(duration_ms)})"
            )
            item = QtWidgets.QListWidgetItem(item_text)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, (start_ms, end_ms))
            self._clip_list.addItem(item)

    def _remove_selected_clips(self) -> None:
        selected = self._clip_list.selectedItems()
        if not selected:
            return
        indices = [self._clip_list.row(item) for item in selected]
        for index in sorted(indices, reverse=True):
            if 0 <= index < len(self._clips):
                self._clips.pop(index)
        self._refresh_clip_list()

    def _export_selected_clips(self) -> None:
        selected = self._clip_list.selectedItems()
        if not selected:
            QtWidgets.QMessageBox.information(self, "情報", "保存するクリップを選択してください。")
            return
        clips = [item.data(QtCore.Qt.ItemDataRole.UserRole) for item in selected]
        self._export_clips(clips)

    def _export_all_clips(self) -> None:
        if not self._clips:
            QtWidgets.QMessageBox.information(self, "情報", "保存するクリップがありません。")
            return
        self._export_clips(list(self._clips))

    def _export_clips(self, clips: list[tuple[int, int]]) -> None:
        if not find_ffmpeg_path():
            QtWidgets.QMessageBox.information(self, "情報", "ffmpegが見つかりません。")
            return
        if not self._recording_path.exists():
            QtWidgets.QMessageBox.information(self, "情報", "録画ファイルが見つかりません。")
            return
        output_format = self._clip_format.currentData()
        success = 0
        for idx, (start_ms, end_ms) in enumerate(clips, start=1):
            output_path = self._build_clip_output_path(idx, str(output_format))
            if self._run_ffmpeg_clip(ffmpeg_path, start_ms, end_ms, output_path, str(output_format)):
                success += 1
        QtWidgets.QMessageBox.information(
            self,
            "情報",
            f"クリップ保存完了: {success} / {len(clips)}",
        )

    def _build_clip_output_path(self, index: int, output_format: str) -> Path:
        base = self._recording_path.with_suffix("")
        suffix = self._format_to_suffix(output_format)
        candidate = base.with_name(f"{base.name}_clip_{index}").with_suffix(suffix)
        return ensure_unique_path(candidate)

    def _format_to_suffix(self, output_format: str) -> str:
        mapping = {
            OUTPUT_FORMAT_TS: ".ts",
            OUTPUT_FORMAT_MP4_COPY: ".mp4",
            OUTPUT_FORMAT_MP4_LIGHT: ".mp4",
            OUTPUT_FORMAT_MOV: ".mov",
            OUTPUT_FORMAT_FLV: ".flv",
            OUTPUT_FORMAT_MKV: ".mkv",
            OUTPUT_FORMAT_MP3: ".mp3",
            OUTPUT_FORMAT_WAV: ".wav",
        }
        return mapping.get(output_format, ".mp4")

    def _run_ffmpeg_clip(
        self,
        ffmpeg_path: str,
        start_ms: int,
        end_ms: int,
        output_path: Path,
        output_format: str,
    ) -> bool:
        duration_sec = max(0.0, (end_ms - start_ms) / 1000.0)
        if duration_sec <= 0:
            return False
        start_sec = max(0.0, start_ms / 1000.0)
        command = [ffmpeg_path, "-y", "-ss", f"{start_sec:.3f}", "-i", str(self._recording_path), "-t", f"{duration_sec:.3f}"]
        if output_format == OUTPUT_FORMAT_MP4_LIGHT:
            command += [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
        elif output_format == OUTPUT_FORMAT_MP3:
            command += ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"]
        elif output_format == OUTPUT_FORMAT_WAV:
            command += ["-vn", "-c:a", "pcm_s16le"]
        else:
            command += ["-c", "copy"]
        command.append(str(output_path))
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return result.returncode == 0

    def _maybe_refresh_segments(self, duration_ms: int) -> None:
        if duration_ms <= 0 or duration_ms == self._last_duration_ms:
            return
        self._last_duration_ms = duration_ms
        self._segment_ranges = self._build_segment_ranges(duration_ms)
        self._refresh_segment_list()

    def _build_segment_ranges(self, duration_ms: int) -> list[tuple[int, int]]:
        segment_ms = max(1000, int(self._segment_duration_ms))
        ranges: list[tuple[int, int]] = []
        start = 0
        while start < duration_ms:
            end = min(duration_ms, start + segment_ms)
            ranges.append((start, end))
            start = end
        return ranges

    def _recording_start_time(self) -> Optional[dt.datetime]:
        name = self._recording_path.stem
        match = QtCore.QRegularExpression(r"(\d{4})年(\d{2})月(\d{2})日-(\d{2})時(\d{2})分(\d{2})秒").match(name)
        if not match.hasMatch():
            return None
        try:
            return dt.datetime(
                int(match.captured(1)),
                int(match.captured(2)),
                int(match.captured(3)),
                int(match.captured(4)),
                int(match.captured(5)),
                int(match.captured(6)),
            )
        except ValueError:
            return None

    def _refresh_segment_list(self) -> None:
        self._segment_list.clear()
        if not self._segment_ranges:
            placeholder_end = self._format_time(self._segment_duration_ms)
            placeholder = QtWidgets.QListWidgetItem(f"00:00～{placeholder_end}")
            placeholder.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            placeholder.setForeground(QtGui.QColor("#94a3b8"))
            self._segment_list.addItem(placeholder)
            return
        start_time = self._recording_start_time()
        for index, (start_ms, end_ms) in enumerate(self._segment_ranges, start=1):
            if start_time:
                start_clock = start_time + dt.timedelta(milliseconds=start_ms)
                end_clock = start_time + dt.timedelta(milliseconds=end_ms)
                label = (
                    f"{start_clock.hour}時{start_clock.minute}分{start_clock.second}秒～"
                    f"{end_clock.hour}時{end_clock.minute}分{end_clock.second}秒"
                )
            else:
                label = f"{self._format_time(start_ms)}～{self._format_time(end_ms)}"
            if self._mp4_converted_all or (start_ms, end_ms) in self._mp4_converted_segments:
                label = f"{label} (mp4)"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, (start_ms, end_ms))
            self._segment_list.addItem(item)

    def _apply_selected_segment(self) -> None:
        selected = self._segment_list.selectedItems()
        if not selected:
            self._clip_start_input.setText("")
            self._clip_end_input.setText("")
            self._segment_playback = None
            self._use_temp_mp4 = False
            self._temp_mp4_range = None
            self._stop_proxy_process()
            self._seek_segment_range(0, self._player.duration())
            return
        start_ms, end_ms = selected[0].data(QtCore.Qt.ItemDataRole.UserRole)
        self._clip_start_input.setText(self._format_time(start_ms))
        self._clip_end_input.setText(self._format_time(end_ms))
        if self._use_temp_mp4 and self._temp_mp4_range == (int(start_ms), int(end_ms)):
            self._segment_playback = None
            self._position_slider.setRange(0, max(0, int(self._player.duration())))
            return
        self._use_temp_mp4 = False
        self._temp_mp4_range = None
        self._segment_playback = (int(start_ms), int(end_ms))
        self._seek_segment_range(start_ms, end_ms)
        self._start_proxy_for_range(int(start_ms), int(end_ms))

    def _convert_to_temp_mp4(self) -> None:
        selected = self._segment_list.selectedItems()
        ffmpeg_path = find_ffmpeg_path()
        if not ffmpeg_path:
            QtWidgets.QMessageBox.information(self, "情報", "ffmpegが見つかりません。")
            return
        if not self._recording_path.exists():
            QtWidgets.QMessageBox.information(self, "情報", "録画ファイルが見つかりません。")
            return
        position_offset_ms = 0
        if selected:
            start_ms, end_ms = selected[0].data(QtCore.Qt.ItemDataRole.UserRole)
            duration_sec = max(0.0, (end_ms - start_ms) / 1000.0)
            if duration_sec <= 0:
                QtWidgets.QMessageBox.information(self, "情報", "変換する区間が不正です。")
                return
            position_offset_ms = int(start_ms)
            self._temp_mp4_range = (int(start_ms), int(end_ms))
        else:
            self._temp_mp4_offset_ms = 0
            self._temp_mp4_range = None
        self._temp_mp4_offset_ms = int(position_offset_ms)
        if not self._reencode_temp_mp4():
            QtWidgets.QMessageBox.information(self, "情報", "MP4変換に失敗しました。")
            return
        if selected:
            start_ms, end_ms = selected[0].data(QtCore.Qt.ItemDataRole.UserRole)
            self._mp4_converted_all = False
            self._mp4_converted_segments.add((int(start_ms), int(end_ms)))
        else:
            self._mp4_converted_all = True
            self._mp4_converted_segments.clear()
        self._refresh_segment_list()

    def _reencode_temp_mp4(self) -> bool:
        ffmpeg_path = find_ffmpeg_path()
        if not ffmpeg_path:
            return False
        start_sec = None
        duration_sec = None
        position_offset_ms = 0
        if self._temp_mp4_range:
            start_ms, end_ms = self._temp_mp4_range
            duration_sec = max(0.0, (end_ms - start_ms) / 1000.0)
            if duration_sec <= 0:
                return False
            start_sec = max(0.0, start_ms / 1000.0)
            position_offset_ms = int(start_ms)
        current_pos = max(0, int(self._player.position()) - position_offset_ms)
        temp_dir = Path(tempfile.gettempdir())
        base_name = self._recording_path.with_suffix("").name
        output_path = ensure_unique_path(temp_dir / f"{base_name}_clip_preview_reencode.mp4")
        self._register_temp_path(output_path)
        command = [ffmpeg_path, "-y"]
        if start_sec is not None:
            command += ["-ss", f"{start_sec:.3f}"]
        command += ["-i", str(self._recording_path)]
        if duration_sec is not None:
            command += ["-t", f"{duration_sec:.3f}"]
        command += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            return False
        if not output_path.exists() or output_path.stat().st_size == 0:
            return False
        self._temp_mp4_path = output_path
        self._use_temp_mp4 = True
        self._temp_mp4_offset_ms = int(position_offset_ms)
        self._temp_mp4_is_copy = False
        self._temp_mp4_retry = False
        self._segment_playback = None
        self._playback_path = output_path
        file_url = QtCore.QUrl.fromLocalFile(str(output_path))
        self._player.setSource(file_url)
        self._player.play()
        QtCore.QTimer.singleShot(
            500,
            lambda: self._player.setPosition(current_pos),
        )
        return True

    def _seek_segment_range(self, start_ms: int, end_ms: int) -> None:
        duration = int(self._player.duration())
        if duration <= 0:
            return
        if start_ms < 0:
            start_ms = 0
        if end_ms <= 0 or end_ms > duration:
            end_ms = duration
        self._position_slider.setRange(int(start_ms), int(end_ms))
        self._player.setPosition(int(start_ms))
        self._update_position(int(start_ms))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._player.stop()
        self._player.setSource(QtCore.QUrl())
        self._stop_proxy_process()
        for path in list(self._temp_files):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
        super().closeEvent(event)
