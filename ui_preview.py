# -*- coding: utf-8 -*-
from __future__ import annotations
import subprocess
import threading
from pathlib import Path
from typing import Optional
from PyQt6 import QtCore, QtGui, QtMultimedia, QtMultimediaWidgets, QtWidgets
from streamlink import Streamlink
from streamlink.exceptions import StreamlinkError
from config import (
    DEFAULT_QUALITY,
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
        self._dragging_slider = False
        self._clips: list[tuple[int, int]] = []
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
        clip_layout.setSpacing(8)

        clip_row = QtWidgets.QHBoxLayout()
        clip_row.setSpacing(8)

        self._clip_start_input = QtWidgets.QLineEdit()
        self._clip_start_input.setPlaceholderText("開始 MM:SS")
        self._clip_start_input.setFixedWidth(120)

        self._clip_end_input = QtWidgets.QLineEdit()
        self._clip_end_input.setPlaceholderText("終了 MM:SS")
        self._clip_end_input.setFixedWidth(120)

        self._clip_start_btn = QtWidgets.QPushButton("開始")
        self._clip_start_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_start_btn.clicked.connect(self._set_clip_start_from_current)

        self._clip_end_btn = QtWidgets.QPushButton("終了")
        self._clip_end_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_end_btn.clicked.connect(self._set_clip_end_from_current)

        self._clip_add_btn = QtWidgets.QPushButton("追加")
        self._clip_add_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_add_btn.clicked.connect(self._add_clip)

        clip_row.addWidget(self._clip_start_btn)
        clip_row.addWidget(self._clip_start_input)
        clip_row.addWidget(self._clip_end_btn)
        clip_row.addWidget(self._clip_end_input)
        clip_row.addWidget(self._clip_add_btn)
        clip_row.addStretch(1)

        format_row = QtWidgets.QHBoxLayout()
        format_row.setSpacing(8)
        format_label = QtWidgets.QLabel("保存形式")
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

        self._clip_save_all = QtWidgets.QPushButton("すべて保存")
        self._clip_save_all.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_save_all.clicked.connect(self._export_all_clips)

        self._clip_remove_btn = QtWidgets.QPushButton("削除")
        self._clip_remove_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._clip_remove_btn.clicked.connect(self._remove_selected_clips)

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

    def _apply_source_and_play(self) -> None:
        if not self._recording_path.exists():
            QtWidgets.QMessageBox.information(self, "情報", "録画ファイルが見つかりません。")
            return
        if self._recording_path.stat().st_size < 188 * 10:
            QtWidgets.QMessageBox.information(self, "情報", "録画ファイルがまだ作成中です。")
            return
        playback_path = self._prepare_timeshift_source(self._recording_path, force=True)
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
        file_url = QtCore.QUrl.fromLocalFile(str(playback_path))
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

    def _on_player_error(self, error: QtMultimedia.QMediaPlayer.Error) -> None:
        if error == QtMultimedia.QMediaPlayer.Error.NoError:
            return
        details = self._player.errorString() or "不明なエラー"
        QtWidgets.QMessageBox.information(self, "情報", f"タイムシフト再生に失敗しました: {details}")

    def _prepare_timeshift_source(self, input_path: Path, force: bool = False) -> Path:
        if input_path.suffix.lower() != ".ts":
            return input_path
        ffmpeg_path = find_ffmpeg_path()
        if not ffmpeg_path:
            return input_path
        output_path = input_path.with_name(f"{input_path.stem}_timeshift.mp4")
        if not force and output_path.exists():
            try:
                if output_path.stat().st_mtime >= input_path.stat().st_mtime:
                    return output_path
            except OSError:
                pass
        transcode_command = [
            ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
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
            transcode_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode == 0:
            return output_path
        stderr_text = "\n".join(result.stderr.splitlines()[-5:]) if result.stderr else "詳細不明"
        QtWidgets.QMessageBox.information(self, "情報", f"タイムシフト用変換に失敗しました: {stderr_text}")
        return input_path

    def _format_position(self, position_ms: int, duration_ms: int) -> str:
        return f"{self._format_time(position_ms)} / {self._format_time(duration_ms)}"

    def _format_time(self, millis: int) -> str:
        safe_millis = max(0, int(millis))
        total_seconds = safe_millis // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

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
        ffmpeg_path = find_ffmpeg_path()
        if not ffmpeg_path:
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

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._player.stop()
        self._player.setSource(QtCore.QUrl())
        super().closeEvent(event)
