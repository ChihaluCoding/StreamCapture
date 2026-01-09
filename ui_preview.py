# -*- coding: utf-8 -*-
from __future__ import annotations
import threading
from pathlib import Path
from typing import Optional
from PyQt6 import QtCore, QtGui, QtMultimedia, QtMultimediaWidgets, QtWidgets
from streamlink import Streamlink
from streamlink.exceptions import StreamlinkError
from config import DEFAULT_QUALITY, READ_CHUNK_SIZE
from recording import select_stream
from settings_store import load_setting_value
from streamlink_utils import (
    apply_streamlink_options_for_url,
    restore_streamlink_headers,
    set_streamlink_headers_for_url,
)

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
        self._dragging_slider = False
        self.setWindowTitle("タイムシフト再生")
        self.setMinimumSize(800, 500)
        self._apply_theme()
        self._build_ui()
        self._connect_player_signals()
        self._apply_source_and_play()

    def _apply_theme(self):
        # モダン・ダークテーマ (プレイヤー専用)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a; /* Slate 900 */
                color: #e2e8f0; /* Slate 200 */
                font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
            }
            
            /* コントロールバー背景 */
            QFrame#ControlBar {
                background-color: #1e293b; /* Slate 800 */
                border-top: 1px solid #334155;
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            
            /* ボタン */
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 4px;
                color: #e2e8f0;
                font-weight: bold;
                font-size: 13px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
            QPushButton#PrimaryButton {
                background-color: #0ea5e9; /* Sky 500 */
                color: #ffffff;
            }
            QPushButton#PrimaryButton:hover {
                background-color: #0284c7;
            }
            
            /* ラベル */
            QLabel {
                color: #94a3b8;
                font-family: monospace;
                font-size: 13px;
                font-weight: bold;
            }
            
            /* シークバー */
            QSlider::groove:horizontal {
                border: 1px solid #334155;
                height: 6px;
                background: #1e293b;
                margin: 2px 0;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #0ea5e9;
                border: 1px solid #0ea5e9;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #38bdf8;
            }
            QSlider::sub-page:horizontal {
                background: #0ea5e9;
                border-radius: 3px;
            }
        """)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 映像エリア
        self._video_widget = QtMultimediaWidgets.QVideoWidget(self)
        self._video_widget.setStyleSheet("background-color: #000000;")
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

    def _apply_source_and_play(self) -> None:
        if not self._recording_path.exists():
            QtWidgets.QMessageBox.information(self, "情報", "録画ファイルが見つかりません。")
            return
        file_url = QtCore.QUrl.fromLocalFile(str(self._recording_path))
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
        file_url = QtCore.QUrl.fromLocalFile(str(self._recording_path))
        self._player.setSource(file_url)
        self._player.play()
        QtCore.QTimer.singleShot(
            500,
            lambda: self._player.setPosition(current_pos),
        )

    def _on_slider_pressed(self) -> None:
        self._dragging_slider = True

    def _on_slider_released(self) -> None:
        self._dragging_slider = False
        self._player.setPosition(int(self._position_slider.value()))

    def _on_slider_moved(self, value: int) -> None:
        self._position_label.setText(self._format_position(int(value), int(self._player.duration())))

    def _update_position(self, position: int) -> None:
        if self._dragging_slider:
            return
        self._position_slider.setValue(int(position))
        self._position_label.setText(self._format_position(int(position), int(self._player.duration())))

    def _update_duration(self, duration: int) -> None:
        self._position_slider.setRange(0, max(0, int(duration)))
        self._position_label.setText(self._format_position(int(self._player.position()), int(duration)))

    def _update_play_button_text(self, state: QtMultimedia.QMediaPlayer.PlaybackState) -> None:
        if state == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
            self._play_button.setText("一時停止")
        else:
            self._play_button.setText("再生")

    def _format_position(self, position_ms: int, duration_ms: int) -> str:
        return f"{self._format_time(position_ms)} / {self._format_time(duration_ms)}"

    def _format_time(self, millis: int) -> str:
        safe_millis = max(0, int(millis))
        total_seconds = safe_millis // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._player.stop()
        self._player.setSource(QtCore.QUrl())
        super().closeEvent(event)