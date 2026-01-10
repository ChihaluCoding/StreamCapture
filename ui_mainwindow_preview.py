# -*- coding: utf-8 -*-
from __future__ import annotations
import socket
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from PyQt6 import QtCore, QtGui, QtMultimedia, QtMultimediaWidgets, QtWidgets
from streamlink import Streamlink
from streamlink.exceptions import StreamlinkError
from api_fuwatch import fetch_fuwatch_display_name_by_scraping
from api_niconico import fetch_niconico_display_name_by_scraping
from api_17live import fetch_17live_display_name_by_scraping
from api_bigo import fetch_bigo_display_name_by_scraping
from api_tiktok import fetch_tiktok_display_name
from api_twitch import (
    fetch_twitch_display_name,
    fetch_twitch_live_urls,
)
from api_twitcasting import fetch_twitcasting_display_name_by_scraping
from api_youtube import (
    build_youtube_live_page_url,
    fetch_youtube_channel_title_by_id,
    fetch_youtube_channel_title_by_video,
    fetch_youtube_oembed_author_name,
    resolve_youtube_channel_id,
)
from config import (
    DEFAULT_QUALITY,
    READ_CHUNK_SIZE,
)
from platform_utils import (
    derive_platform_label_for_folder,
    is_twitcasting_url,
    normalize_twitch_login,
    normalize_youtube_entry,
)
from recording import find_ffmpeg_path, resolve_output_path, select_stream
from settings_store import load_setting_value
from streamlink_utils import (
    apply_streamlink_options_for_url,
    restore_streamlink_headers,
    set_streamlink_headers_for_url,
)
from ytdlp_utils import fetch_stream_url_with_ytdlp, is_ytdlp_available
from url_utils import derive_channel_label, safe_filename_component
from ui_preview import PreviewPipeProxy, StreamlinkPreviewWorker, TimeShiftWindow


class MainWindowPreviewMixin:
    def _set_preview_button_text(self, text: str) -> None:
        button = getattr(self, "preview_button", None)
        if isinstance(button, QtWidgets.QPushButton):
            button.setText(text)

    def _is_preview_button_stop(self) -> bool:
        button = getattr(self, "preview_button", None)
        if isinstance(button, QtWidgets.QPushButton):
            return button.text() == "プレビュー停止"
        return False

    def _resolve_stream_url(self, url: str) -> Optional[str]:
        quality = DEFAULT_QUALITY
        http_timeout = load_setting_value("http_timeout", 20, int)
        stream_timeout = load_setting_value("stream_timeout", 60, int)
        session = Streamlink()
        session.set_option("http-timeout", int(http_timeout))
        session.set_option("stream-timeout", int(stream_timeout))
        apply_streamlink_options_for_url(session, url)
        original_headers = dict(session.http.headers)
        try:
            original_headers = set_streamlink_headers_for_url(session, url)
            streams = session.streams(url)
        except StreamlinkError as exc:
            self._append_log(f"プレビュー用ストリーム取得に失敗しました: {exc}")
            return None
        finally:
            restore_streamlink_headers(session, original_headers)
        if not streams:
            self._append_log("プレビュー用ストリームが見つかりませんでした。")
            return None
        stream = select_stream(streams, quality)
        if hasattr(stream, "to_url"):
            try:
                return stream.to_url()
            except TypeError as exc:
                self._append_log(f"プレビュー用ストリームURLの取得に失敗しました: {exc}")
        if hasattr(stream, "url"):
            return getattr(stream, "url")
        self._append_log("プレビューに対応したストリームURLを取得できませんでした。")
        return None

    def _is_twitch_live_for_preview(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "twitch" not in host and "twitch" not in url:
            return True
        login = normalize_twitch_login(url)
        if not login:
            return True
        client_id = load_setting_value("twitch_client_id", "", str).strip()
        client_secret = load_setting_value("twitch_client_secret", "", str).strip()
        if not client_id or not client_secret:
            self._append_log("Twitch APIキーが未設定のためライブ判定をスキップします。")
            return True
        live_urls = fetch_twitch_live_urls(
            client_id=client_id,
            client_secret=client_secret,
            entries=[login],
            log_cb=self._append_log,
        )
        for live_url in live_urls:
            live_login = normalize_twitch_login(live_url)
            if live_login == login:
                return True
        self._append_log("Twitch配信がオフラインのためプレビューを開始しません。")
        self._show_info("Twitch配信がオフラインのためプレビューを開始しません。")
        return False

    def _is_twitch_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "twitch" in host:
            return True
        return "twitch" in url

    def _should_use_ffmpeg_preview(self, url: str) -> bool:
        return is_twitcasting_url(url)

    def _allocate_preview_tcp_port(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return int(port)

    def _allocate_preview_udp_port(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return int(port)

    def _create_ffmpeg_preview_process(self, output_url: str) -> Optional[QtCore.QProcess]:
        ffmpeg_path = find_ffmpeg_path()
        if not ffmpeg_path:
            self._append_log("プレビューにffmpegが必要です。PATHにffmpegを追加してください。")
            return None
        args = [
            "-loglevel", "error",
            "-fflags", "+genpts",
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-c:a", "aac",
            "-b:a", "192k",
            "-f", "mpegts",
            output_url,
        ]
        process = QtCore.QProcess(self)
        process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardError.connect(
            lambda: self._log_ffmpeg_preview_error(process)
        )
        process.setProgram(ffmpeg_path)
        process.setArguments(args)
        process.start()
        if not process.waitForStarted(2000):
            self._append_log("プレビュー用ffmpegの起動に失敗しました。")
            process.deleteLater()
            return None
        return process

    def _create_ffmpeg_preview_process_for_url(self, input_url: str, output_url: str) -> Optional[QtCore.QProcess]:
        ffmpeg_path = find_ffmpeg_path()
        if not ffmpeg_path:
            self._append_log("プレビューにffmpegが必要です。PATHにffmpegを追加してください。")
            return None
        args = [
            "-loglevel", "error",
            "-fflags", "+genpts",
        ]
        if input_url.startswith("http"):
            args.extend(["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"])
        args.extend([
            "-i", input_url,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-c:a", "aac",
            "-b:a", "192k",
            "-f", "mpegts",
            output_url,
        ])
        process = QtCore.QProcess(self)
        process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardError.connect(
            lambda: self._log_ffmpeg_preview_error(process)
        )
        process.setProgram(ffmpeg_path)
        process.setArguments(args)
        process.start()
        if not process.waitForStarted(2000):
            self._append_log("プレビュー用ffmpegの起動に失敗しました。")
            process.deleteLater()
            return None
        return process

    def _resolve_channel_display_name(self, url: str) -> Optional[str]:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "youtube" in host or "youtu.be" in host:
            api_key = load_setting_value("youtube_api_key", "", str).strip()
            if not api_key:
                if parsed.scheme and parsed.netloc:
                    return fetch_youtube_oembed_author_name(url, self._append_log)
                return None
            kind, value = normalize_youtube_entry(url)
            if kind == "video" and value:
                title = fetch_youtube_channel_title_by_video(api_key, value, self._append_log)
                if title:
                    return title
            channel_id = resolve_youtube_channel_id(api_key, url, self._append_log)
            if channel_id:
                title = fetch_youtube_channel_title_by_id(api_key, channel_id, self._append_log)
                if title:
                    return title
            if parsed.scheme and parsed.netloc:
                return fetch_youtube_oembed_author_name(url, self._append_log)
            return None
        if "twitch" in host or "twitch" in url:
            login = normalize_twitch_login(url)
            if not login:
                return None
            client_id = load_setting_value("twitch_client_id", "", str).strip()
            client_secret = load_setting_value("twitch_client_secret", "", str).strip()
            if not client_id or not client_secret:
                return None
            title = fetch_twitch_display_name(client_id, client_secret, login, self._append_log)
            return title if title else None
        if "twitcasting.tv" in host or "twitcasting" in url:
            title = fetch_twitcasting_display_name_by_scraping(url, self._append_log)
            return title if title else None
        if "nicovideo.jp" in host or "nicovideo" in url:
            title = fetch_niconico_display_name_by_scraping(url, self._append_log)
            return title if title else None
        if "tiktok" in host or "tiktok" in url:
            title = fetch_tiktok_display_name(url, self._append_log)
            return title if title else None
        if "17.live" in host or "17.live" in url:
            title = fetch_17live_display_name_by_scraping(url, self._append_log)
            return title if title else None
        if "bigo.tv" in host or "bigo.live" in host or "bigo" in url:
            title = fetch_bigo_display_name_by_scraping(url, self._append_log)
            return title if title else None
        if "whowatch.tv" in host or "whowatch" in url:
            title = fetch_fuwatch_display_name_by_scraping(url, self._append_log)
            return title if title else None
        return None

    def _resolve_channel_folder_label(self, url: str) -> str:
        cached = self.channel_name_cache.get(url)
        if cached:
            return cached
        display_name = self._resolve_channel_display_name(url)
        if display_name:
            label = safe_filename_component(display_name)
            self.channel_name_cache[url] = label
            return label
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "twitch" in host or "twitch" in url:
            login = normalize_twitch_login(url)
            if login:
                fallback = safe_filename_component(login)
                self.channel_name_cache[url] = fallback
                return fallback
        if "youtube" in host or "youtu.be" in host:
            kind, value = normalize_youtube_entry(url)
            if value:
                fallback = safe_filename_component(value)
                self.channel_name_cache[url] = fallback
                return fallback
        platform_label = derive_platform_label_for_folder(url)
        if platform_label:
            fallback = safe_filename_component(platform_label)
            self.channel_name_cache[url] = fallback
            return fallback
        fallback = derive_channel_label(url)
        self.channel_name_cache[url] = fallback
        return fallback

    def _get_current_preview_url(self) -> Optional[str]:
        current_widget = self.preview_tabs.currentWidget()
        if current_widget is None:
            return None
        value = current_widget.property("preview_url")
        return str(value) if value else None

    def _on_preview_tab_close(self, index: int) -> None:
        widget = self.preview_tabs.widget(index)
        if widget is None:
            return
        url = widget.property("preview_url")
        if isinstance(url, str) and url:
            self._stop_preview_for_url(url, remove_tab=True)
        else:
            self.preview_tabs.removeTab(index)

    def _start_preview(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            preview_urls = self._collect_preview_urls_from_settings()
            if not preview_urls:
                self._show_info("設定にプレビュー対象の配信URLがありません。")
                return
            self._append_log("設定に登録された配信URLのプレビューを開始します。")
            for preview_url in preview_urls:
                self._start_preview_for_url(
                    preview_url,
                    update_input=False,
                    reason="設定",
                    select_tab=False,
                )
            return
        self._start_preview_for_url(url, update_input=False, reason="手動", select_tab=True)

    def _is_recording_active_for_url(self, url: str) -> bool:
        if self.manual_recording_url == url:
            thread = self.worker_thread
            if isinstance(thread, QtCore.QThread) and thread.isRunning():
                return True
        session = self.auto_sessions.get(url)
        if isinstance(session, dict):
            thread = session.get("thread")
            if isinstance(thread, QtCore.QThread) and thread.isRunning():
                return True
        return False

    def _start_recording_preview_from_file(self, url: str, output_path: Path, reason: str, select_tab: bool) -> None:
        if not self._is_twitch_url(url):
            self._start_preview_for_url(url, update_input=False, reason=reason, select_tab=select_tab)
            return
        if not self._is_recording_active_for_url(url):
            return
        if not output_path.exists():
            QtCore.QTimer.singleShot(
                500,
                lambda target_url=url, path=output_path: self._start_recording_preview_from_file(
                    target_url, path, reason, select_tab
                ),
            )
            return
        if output_path.stat().st_size < 188 * 10:
            QtCore.QTimer.singleShot(
                500,
                lambda target_url=url, path=output_path: self._start_recording_preview_from_file(
                    target_url, path, reason, select_tab
                ),
            )
            return
        file_url = QtCore.QUrl.fromLocalFile(str(output_path))
        if url in self.preview_sessions:
            session = self.preview_sessions[url]
            player = session.get("player")
            if not isinstance(player, QtMultimedia.QMediaPlayer):
                return
            # ... (既存のクリーンアップ処理はそのまま維持) ...
            refresh_timer = session.get("refresh_timer")
            if isinstance(refresh_timer, QtCore.QTimer):
                refresh_timer.stop()
                refresh_timer.deleteLater()
                session["refresh_timer"] = None
            stall_timer = session.get("stall_timer")
            if isinstance(stall_timer, QtCore.QTimer):
                stall_timer.stop()
                stall_timer.deleteLater()
                session["stall_timer"] = None
            process = session.get("process")
            if isinstance(process, QtCore.QProcess):
                process.terminate()
                process.waitForFinished(2000)
                if process.state() == QtCore.QProcess.ProcessState.Running:
                    process.kill()
                process.deleteLater()
            stop_event = session.get("pipe_stop_event")
            if isinstance(stop_event, threading.Event):
                stop_event.set()
            pipe_thread = session.get("pipe_thread")
            if isinstance(pipe_thread, QtCore.QThread):
                pipe_thread.quit()
                pipe_thread.wait(2000)
                pipe_thread.deleteLater()
            pipe_proxy = session.get("pipe_proxy")
            if isinstance(pipe_proxy, PreviewPipeProxy):
                pipe_proxy.close()
                pipe_proxy.deleteLater()
            
            player.stop()
            player.setSource(file_url)
            player.play()
            
            session["process"] = None
            session["pipe_stop_event"] = None
            session["pipe_thread"] = None
            session["pipe_worker"] = None
            session["pipe_proxy"] = None
            session["preview_url"] = None
            session["use_ffmpeg"] = False
            session["recording_path"] = str(output_path)
            session["seek_to_tail"] = True
            session["last_position"] = 0
            session["last_position_at"] = time.monotonic()
            session["recording_last_size"] = output_path.stat().st_size
            session["recording_reload_at"] = time.monotonic()
            
            self._setup_preview_stall_watchdog(url)
            self._setup_recording_refresh_timer(url)
            
            if select_tab:
                widget = session.get("widget")
                if isinstance(widget, QtWidgets.QWidget):
                    self.preview_tabs.setCurrentWidget(widget)
            self._set_preview_button_text("プレビュー停止")
            self._append_log(f"プレビューを更新しました（{reason}: 録画ファイル）。")
            return

        audio = QtMultimedia.QAudioOutput(self)
        audio.setVolume(float(self.preview_volume))
        player = QtMultimedia.QMediaPlayer(self)
        player.setAudioOutput(audio)
        video = QtMultimediaWidgets.QVideoWidget()
        player.setVideoOutput(video)
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.addWidget(video)
        label = derive_channel_label(url)
        tab_index = self.preview_tabs.addTab(container, label)
        container.setProperty("preview_url", url)
        self.preview_sessions[url] = {
            "player": player,
            "audio": audio,
            "video": video,
            "widget": container,
            "tab_index": tab_index,
            "process": None,
            "pipe_stop_event": None,
            "pipe_thread": None,
            "pipe_worker": None,
            "pipe_proxy": None,
            "preview_url": None,
            "use_ffmpeg": False,
            "retry_pending": False,
            "retry_count": 0,
            "last_retry_at": 0.0,
            "refresh_timer": None,
            "stall_timer": None,
            "recording_path": str(output_path),
            "seek_to_tail": True,
            "recording_refresh_timer": None,
            "recording_last_size": output_path.stat().st_size,
            "recording_reload_at": time.monotonic(),
            "last_position": 0,
            "last_position_at": 0.0,
        }
        player.setSource(file_url)
        player.play()
        self._setup_preview_stall_watchdog(url)
        self._setup_recording_refresh_timer(url)
        if select_tab or self.preview_tabs.count() == 1:
            self.preview_tabs.setCurrentWidget(container)
        self._set_preview_button_text("プレビュー停止")
        self._append_log(f"プレビューを開始しました（{reason}: 録画ファイル）。")
        player.errorOccurred.connect(
            lambda _, __, target_url=url: self._handle_preview_error(target_url)
        )
        player.mediaStatusChanged.connect(
            lambda status, target_url=url: self._handle_preview_status(target_url, status)
        )

    def _start_preview_for_url(self, url: str, update_input: bool, reason: str, select_tab: bool) -> None:
        if update_input:
            self.url_input.setText(url)
        if reason == "手動" and not self._is_twitch_live_for_preview(url):
            return
        if "17.live" in url:
            self._show_preview_unavailable(url, reason, select_tab)
            return
        is_whowatch = "whowatch.tv" in url
        is_twitch = self._is_twitch_url(url)
        use_ffmpeg = self._should_use_ffmpeg_preview(url)
        use_ytdlp_preview = False
        process: QtCore.QProcess | None = None
        pipe_stop_event: threading.Event | None = None
        pipe_thread: QtCore.QThread | None = None
        pipe_worker: StreamlinkPreviewWorker | None = None
        pipe_proxy: PreviewPipeProxy | None = None
        stream_url = None
        preview_url = None
        start_delay_ms = 800
        if is_twitch and is_ytdlp_available():
            ytdlp_url = fetch_stream_url_with_ytdlp(url, self._append_log)
            if not ytdlp_url:
                label = "Twitch" if is_twitch else "ふわっち"
                self._append_log(f"{label}プレビュー用のURL取得に失敗しました。")
                return
            self._append_log(f"Twitchプレビュー準備: {ytdlp_url}")
            use_ytdlp_preview = True
            port = self._allocate_preview_udp_port()
            preview_url = f"udp://@127.0.0.1:{port}"
            output_url = f"udp://127.0.0.1:{port}?pkt_size=1316"
            process = self._create_ffmpeg_preview_process_for_url(ytdlp_url, output_url)
            if process is None:
                return
            use_ffmpeg = True
            start_delay_ms = 1500
        elif is_whowatch and is_ytdlp_available():
            ytdlp_url = fetch_stream_url_with_ytdlp(url, self._append_log)
            if not ytdlp_url:
                self._append_log("ふわっちプレビュー用のURL取得に失敗しました。")
                return
            self._append_log(f"ふわっちプレビュー準備: {ytdlp_url}")
            stream_url = ytdlp_url
            use_ytdlp_preview = True
            use_ffmpeg = False
        elif use_ffmpeg:
            port = self._allocate_preview_udp_port()
            preview_url = f"udp://@127.0.0.1:{port}"
            output_url = f"udp://127.0.0.1:{port}?pkt_size=1316"
            process = self._create_ffmpeg_preview_process(output_url)
            if process is None:
                return
            pipe_stop_event = threading.Event()
            pipe_thread = QtCore.QThread()
            pipe_worker = StreamlinkPreviewWorker(url, pipe_stop_event)
            pipe_worker.moveToThread(pipe_thread)
            pipe_proxy = PreviewPipeProxy(process)
            pipe_worker.data_signal.connect(pipe_proxy.write_data)
            pipe_worker.log_signal.connect(self._append_log)
            pipe_worker.finished_signal.connect(pipe_proxy.close)
            pipe_worker.finished_signal.connect(pipe_thread.quit)
            pipe_worker.finished_signal.connect(pipe_worker.deleteLater)
            pipe_thread.finished.connect(pipe_thread.deleteLater)
            pipe_thread.started.connect(pipe_worker.run)
            pipe_thread.start()
        else:
            if stream_url is None:
                stream_url = self._resolve_stream_url(url)
            if not stream_url:
                ytdlp_url = fetch_stream_url_with_ytdlp(url, self._append_log)
                if not ytdlp_url:
                    return
                use_ytdlp_preview = True
                port = self._allocate_preview_tcp_port()
                preview_url = f"tcp://127.0.0.1:{port}"
                output_url = f"tcp://127.0.0.1:{port}?listen=1&listen_timeout=5"
                process = self._create_ffmpeg_preview_process_for_url(ytdlp_url, output_url)
                if process is None:
                    return
                use_ffmpeg = True
        if url in self.preview_sessions:
            session = self.preview_sessions[url]
            player = session["player"]
            audio = session.get("audio")
            if isinstance(audio, QtMultimedia.QAudioOutput):
                audio.setVolume(float(self.preview_volume))
            if player.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
                player.stop()
            # ... (既存のクリーンアップ処理はそのまま維持) ...
            old_process = session.get("process")
            if isinstance(old_process, QtCore.QProcess):
                old_process.terminate()
                old_process.waitForFinished(2000)
                if old_process.state() == QtCore.QProcess.ProcessState.Running:
                    old_process.kill()
                old_process.deleteLater()
            old_stop_event = session.get("pipe_stop_event")
            if isinstance(old_stop_event, threading.Event):
                old_stop_event.set()
            old_thread = session.get("pipe_thread")
            if isinstance(old_thread, QtCore.QThread):
                old_thread.quit()
                old_thread.wait(2000)
                old_thread.deleteLater()
            old_proxy = session.get("pipe_proxy")
            if isinstance(old_proxy, PreviewPipeProxy):
                old_proxy.close()
                old_proxy.deleteLater()
            
            if use_ffmpeg and isinstance(process, QtCore.QProcess):
                self._start_player_with_source(player, preview_url, start_delay_ms)
                session["process"] = process
                session["pipe_stop_event"] = pipe_stop_event
                session["pipe_thread"] = pipe_thread
                session["pipe_worker"] = pipe_worker
                session["pipe_proxy"] = pipe_proxy
                session["preview_url"] = preview_url
                session["use_ffmpeg"] = True
                session["recording_path"] = None
                session["seek_to_tail"] = False
                self._bind_ffmpeg_process_retry(url, process)
            else:
                player.setSource(QtCore.QUrl(stream_url))
                session["process"] = None
                session["pipe_stop_event"] = None
                session["pipe_thread"] = None
                session["pipe_worker"] = None
                session["pipe_proxy"] = None
                session["preview_url"] = None
                session["use_ffmpeg"] = False
            session["recording_path"] = None
            session["seek_to_tail"] = False
            refresh_timer = session.get("recording_refresh_timer")
            if isinstance(refresh_timer, QtCore.QTimer):
                refresh_timer.stop()
                refresh_timer.deleteLater()
            session["recording_refresh_timer"] = None
            player.play()
            self._setup_twitch_refresh_timer(url)
            self._setup_preview_stall_watchdog(url)
            session["last_position"] = 0
            session["last_position_at"] = time.monotonic()
            if select_tab:
                self.preview_tabs.setCurrentWidget(session["widget"])
            self._set_preview_button_text("プレビュー停止")
            self._append_log(f"プレビューを更新しました（{reason}）。")
            session["retry_pending"] = False
            session["retry_count"] = 0
            session["last_retry_at"] = 0.0
            return
        audio = QtMultimedia.QAudioOutput(self)
        audio.setVolume(float(self.preview_volume))
        player = QtMultimedia.QMediaPlayer(self)
        player.setAudioOutput(audio)
        video = QtMultimediaWidgets.QVideoWidget()
        player.setVideoOutput(video)
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.addWidget(video)
        label = derive_channel_label(url)
        tab_index = self.preview_tabs.addTab(container, label)
        container.setProperty("preview_url", url)
        self.preview_sessions[url] = {
            "player": player,
            "audio": audio,
            "video": video,
            "widget": container,
            "tab_index": tab_index,
            "process": process,
            "pipe_stop_event": pipe_stop_event,
            "pipe_thread": pipe_thread,
            "pipe_worker": pipe_worker,
            "pipe_proxy": pipe_proxy,
            "preview_url": preview_url,
            "use_ffmpeg": bool(use_ffmpeg),
            "retry_pending": False,
            "retry_count": 0,
            "last_retry_at": 0.0,
            "refresh_timer": None,
            "stall_timer": None,
            "last_position": 0,
            "last_position_at": 0.0,
            "recording_path": None,
            "seek_to_tail": False,
        }
        if use_ffmpeg and isinstance(process, QtCore.QProcess):
            self._start_player_with_source(player, preview_url, start_delay_ms)
            self._bind_ffmpeg_process_retry(url, process)
        else:
            player.setSource(QtCore.QUrl(stream_url))
            player.play()
            self._setup_twitch_refresh_timer(url)
            self._setup_preview_stall_watchdog(url)
            session = self.preview_sessions.get(url)
            if isinstance(session, dict):
                session["last_position"] = 0
                session["last_position_at"] = time.monotonic()
        if select_tab or self.preview_tabs.count() == 1:
            self.preview_tabs.setCurrentWidget(container)
        self._set_preview_button_text("プレビュー停止")
        if use_ytdlp_preview:
            self._append_log(f"プレビューを開始しました（{reason}: yt-dlp）。")
        else:
            self._append_log(f"プレビューを開始しました（{reason}）。")
        player.errorOccurred.connect(
            lambda _, __, target_url=url: self._handle_preview_error(target_url)
        )
        player.mediaStatusChanged.connect(
            lambda status, target_url=url: self._handle_preview_status(target_url, status)
        )
        session = self.preview_sessions.get(url)
        if isinstance(session, dict):
            session["retry_pending"] = False
            session["retry_count"] = 0
            session["last_retry_at"] = 0.0

    def _show_preview_unavailable(self, url: str, reason: str, select_tab: bool) -> None:
        if url in self.preview_sessions:
            session = self.preview_sessions[url]
            label = session.get("message_label")
            if isinstance(label, QtWidgets.QLabel):
                label.setText("この配信サイトのプレビューは表示できません。\nタイムシフトから確認してください。")
            if select_tab:
                self.preview_tabs.setCurrentWidget(session["widget"])
            self._set_preview_button_text("プレビュー停止")
            self._append_log(f"プレビューを開始しました（{reason}: 非対応）。")
            return
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch(1)
        label = QtWidgets.QLabel("この配信サイトのプレビューは表示できません。\nタイムシフトから確認してください。")
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 16px; color: #94a3b8;")
        layout.addWidget(label)
        layout.addStretch(1)
        tab_index = self.preview_tabs.addTab(container, derive_channel_label(url))
        container.setProperty("preview_url", url)
        player = QtMultimedia.QMediaPlayer(self)
        self.preview_sessions[url] = {
            "player": player,
            "audio": None,
            "video": None,
            "widget": container,
            "tab_index": tab_index,
            "process": None,
            "pipe_stop_event": None,
            "pipe_thread": None,
            "pipe_worker": None,
            "pipe_proxy": None,
            "preview_url": None,
            "use_ffmpeg": False,
            "retry_pending": False,
            "retry_count": 0,
            "last_retry_at": 0.0,
            "refresh_timer": None,
            "stall_timer": None,
            "last_position": 0,
            "last_position_at": time.monotonic(),
            "recording_path": None,
            "seek_to_tail": False,
            "message_label": label,
        }
        if select_tab or self.preview_tabs.count() == 1:
            self.preview_tabs.setCurrentWidget(container)
        self._set_preview_button_text("プレビュー停止")
        self._append_log(f"プレビューを開始しました（{reason}: 非対応）。")

    def _stop_preview(self) -> None:
        current_url = self._get_current_preview_url()
        if not current_url:
            self._append_log("停止するプレビューがありません。")
            return
        self._stop_preview_for_url(current_url, remove_tab=True)

    def _toggle_preview(self) -> None:
        if self._is_preview_button_stop():
            self._stop_preview()
        else:
            self._start_preview()

    def _stop_preview_for_url(self, url: str, remove_tab: bool) -> None:
        session = self.preview_sessions.pop(url, None)
        if session is None:
            return
        # ... (タイマーやスレッドのクリーンアップは既存コード同様) ...
        refresh_timer = session.get("refresh_timer")
        if isinstance(refresh_timer, QtCore.QTimer):
            refresh_timer.stop()
            refresh_timer.deleteLater()
        stall_timer = session.get("stall_timer")
        if isinstance(stall_timer, QtCore.QTimer):
            stall_timer.stop()
            stall_timer.deleteLater()
        recording_timer = session.get("recording_refresh_timer")
        if isinstance(recording_timer, QtCore.QTimer):
            recording_timer.stop()
            recording_timer.deleteLater()
        player = session["player"]
        process = session.get("process")
        if isinstance(process, QtCore.QProcess):
            process.terminate()
            process.waitForFinished(2000)
            if process.state() == QtCore.QProcess.ProcessState.Running:
                process.kill()
            process.deleteLater()
        stop_event = session.get("pipe_stop_event")
        if isinstance(stop_event, threading.Event):
            stop_event.set()
        pipe_thread = session.get("pipe_thread")
        if isinstance(pipe_thread, QtCore.QThread):
            pipe_thread.quit()
            pipe_thread.wait(2000)
            pipe_thread.deleteLater()
        pipe_proxy = session.get("pipe_proxy")
        if isinstance(pipe_proxy, PreviewPipeProxy):
            pipe_proxy.close()
            pipe_proxy.deleteLater()
        player.stop()
        player.setSource(QtCore.QUrl())
        widget = session["widget"]
        if remove_tab:
            index = self.preview_tabs.indexOf(widget)
            if index != -1:
                self.preview_tabs.removeTab(index)
            widget.deleteLater()
        self._append_log(f"プレビューを停止しました: {url}")
        if self.preview_tabs.count() == 0:
            self._set_preview_button_text("プレビュー")

    # ... (その他のヘルパーメソッドは変更なし) ...
    def _start_player_with_source(self, player: QtMultimedia.QMediaPlayer, url: str, delay_ms: int) -> None:
        def _start() -> None:
            player.setSource(QtCore.QUrl(url))
            player.play()
        if delay_ms <= 0:
            _start()
            return
        QtCore.QTimer.singleShot(delay_ms, _start)

    def _setup_recording_refresh_timer(self, url: str) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        if not session.get("recording_path"):
            return
        existing_timer = session.get("recording_refresh_timer")
        if isinstance(existing_timer, QtCore.QTimer):
            return
        timer = QtCore.QTimer(self)
        timer.setInterval(5000)
        timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)
        timer.timeout.connect(lambda target_url=url: self._check_recording_refresh(target_url))
        timer.start()
        session["recording_refresh_timer"] = timer

    def _check_recording_refresh(self, url: str) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        recording_path = session.get("recording_path")
        if not recording_path:
            return
        if not self._is_recording_active_for_url(url):
            return
        path = Path(str(recording_path))
        if not path.exists():
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        last_size = int(session.get("recording_last_size", 0))
        if size <= last_size:
            return
        now = time.monotonic()
        last_reload = float(session.get("recording_reload_at", 0.0))
        if now - last_reload < 2.0:
            return
        session["recording_last_size"] = size
        session["recording_reload_at"] = now

    def _setup_twitch_refresh_timer(self, url: str) -> None:
        if not self._is_twitch_url(url):
            return
        session = self.preview_sessions.get(url)
        if session is None:
            return
        if session.get("use_ffmpeg"):
            return
        existing_timer = session.get("refresh_timer")
        if isinstance(existing_timer, QtCore.QTimer):
            return
        timer = QtCore.QTimer(self)
        timer.setInterval(60000)
        timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)
        timer.timeout.connect(lambda target_url=url: self._refresh_twitch_preview(target_url))
        timer.start()
        session["refresh_timer"] = timer

    def _setup_preview_stall_watchdog(self, url: str) -> None:
        if not self._is_twitch_url(url):
            return
        session = self.preview_sessions.get(url)
        if session is None:
            return
        if session.get("use_ffmpeg") and not self._is_twitch_url(url):
            return
        existing_timer = session.get("stall_timer")
        if isinstance(existing_timer, QtCore.QTimer):
            return
        timer = QtCore.QTimer(self)
        timer.setInterval(5000)
        timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)
        timer.timeout.connect(lambda target_url=url: self._check_preview_stall(target_url))
        timer.start()
        session["stall_timer"] = timer
        session["last_position"] = 0
        session["last_position_at"] = time.monotonic()

    def _refresh_twitch_preview(self, url: str) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        if session.get("use_ffmpeg"):
            return
        player = session.get("player")
        if not isinstance(player, QtMultimedia.QMediaPlayer):
            return
        if player.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
            status = player.mediaStatus()
            if status in (
                QtMultimedia.QMediaPlayer.MediaStatus.BufferedMedia,
                QtMultimedia.QMediaPlayer.MediaStatus.LoadedMedia,
            ):
                return
        stream_url = self._resolve_stream_url(url)
        if not stream_url:
            return
        player.setSource(QtCore.QUrl(stream_url))
        player.play()
        session["last_position"] = 0
        session["last_position_at"] = time.monotonic()

    def _refresh_recording_file_preview(self, url: str, reason: str) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        recording_path = session.get("recording_path")
        if not recording_path:
            return
        if not self._is_recording_active_for_url(url):
            return
        path = Path(str(recording_path))
        if not path.exists():
            QtCore.QTimer.singleShot(
                500,
                lambda target_url=url, reason_text=reason: self._refresh_recording_file_preview(
                    target_url, reason_text
                ),
            )
            return
        if path.stat().st_size < 188 * 10:
            QtCore.QTimer.singleShot(
                500,
                lambda target_url=url, reason_text=reason: self._refresh_recording_file_preview(
                    target_url, reason_text
                ),
            )
            return
        player = session.get("player")
        if not isinstance(player, QtMultimedia.QMediaPlayer):
            return
        file_url = QtCore.QUrl.fromLocalFile(str(path))
        session["seek_to_tail"] = True
        try:
            player.pause()
            player.setSource(file_url)
            player.play()
        except Exception:
            player.stop()
            player.setSource(file_url)
            player.play()
        session["last_position"] = int(player.position())
        session["last_position_at"] = time.monotonic()
        session["recording_last_size"] = path.stat().st_size
        session["recording_reload_at"] = time.monotonic()
        self._setup_preview_stall_watchdog(url)
        self._append_log(f"プレビューを再読み込みしました（録画ファイル: {reason}）。")

    def _seek_recording_preview_to_tail(self, url: str) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        if not session.get("recording_path"):
            return
        if not session.get("seek_to_tail"):
            return
        player = session.get("player")
        if not isinstance(player, QtMultimedia.QMediaPlayer):
            return
        duration = int(player.duration())
        if duration <= 0:
            return
        seek_position = max(0, duration - 3000)
        player.setPosition(seek_position)
        session["seek_to_tail"] = False

    def _check_preview_stall(self, url: str) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        if session.get("use_ffmpeg") and not self._is_twitch_url(url):
            return
        if session.get("recording_path"):
            now = time.monotonic()
            last_retry = float(session.get("last_retry_at", 0.0))
            if now - last_retry < 2.5:
                return
        player = session.get("player")
        if not isinstance(player, QtMultimedia.QMediaPlayer):
            return
        status = player.mediaStatus()
        if status in (
            QtMultimedia.QMediaPlayer.MediaStatus.LoadingMedia,
            QtMultimedia.QMediaPlayer.MediaStatus.BufferingMedia,
        ):
            session["last_position"] = int(player.position())
            session["last_position_at"] = time.monotonic()
            return
        if player.playbackState() != QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
            session["last_position"] = int(player.position())
            session["last_position_at"] = time.monotonic()
            return
        now = time.monotonic()
        current_position = int(player.position())
        last_position = int(session.get("last_position", 0))
        last_position_at = float(session.get("last_position_at", now))
        if current_position > last_position:
            session["last_position"] = current_position
            session["last_position_at"] = now
            return
        if now - last_position_at < 8.0:
            return
        session["last_position"] = current_position
        session["last_position_at"] = now
        if session.get("recording_path"):
            session["last_retry_at"] = now
            self._refresh_recording_file_preview(url, "停止検知")
            return
        self._schedule_preview_retry(url, "停止検知")

    def _handle_preview_error(self, url: str) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        if session.get("recording_path"):
            if self._is_recording_active_for_url(url):
                return
            self._refresh_recording_file_preview(url, "エラー")
            return
        if not (self._is_twitch_url(url) or session.get("use_ffmpeg")):
            return
        self._schedule_preview_retry(url, "再接続")

    def _handle_preview_status(self, url: str, status: QtMultimedia.QMediaPlayer.MediaStatus) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        if session.get("recording_path"):
            if status == QtMultimedia.QMediaPlayer.MediaStatus.LoadedMedia:
                self._seek_recording_preview_to_tail(url)
                return
            if status in (
                QtMultimedia.QMediaPlayer.MediaStatus.EndOfMedia,
                QtMultimedia.QMediaPlayer.MediaStatus.InvalidMedia,
            ):
                if self._is_recording_active_for_url(url):
                    return
                self._refresh_recording_file_preview(url, "EOF")
            return
        if not (self._is_twitch_url(url) or session.get("use_ffmpeg")):
            return
        if status in (
            QtMultimedia.QMediaPlayer.MediaStatus.EndOfMedia,
            QtMultimedia.QMediaPlayer.MediaStatus.InvalidMedia,
        ):
            self._schedule_preview_retry(url, "再接続")

    def _schedule_preview_retry(self, url: str, reason: str) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        if session.get("retry_pending"):
            return
        last_retry = float(session.get("last_retry_at", 0.0))
        now = time.monotonic()
        if now - last_retry < 2.5:
            return
        session["retry_pending"] = True
        session["last_retry_at"] = now
        session["retry_count"] = int(session.get("retry_count", 0)) + 1
        self._append_log(f"プレビュー再接続を試行します: {url}（{reason}）")
        QtCore.QTimer.singleShot(
            1000,
            lambda target_url=url: self._retry_preview(target_url),
        )

    def _retry_preview(self, url: str) -> None:
        session = self.preview_sessions.get(url)
        if session is None:
            return
        session["retry_pending"] = False
        if not self._is_twitch_url(url):
            return
        self._start_preview_for_url(
            url,
            update_input=False,
            reason="再接続",
            select_tab=False,
        )

    def _log_ffmpeg_preview_error(self, process: QtCore.QProcess) -> None:
        if not isinstance(process, QtCore.QProcess):
            return
        raw = process.readAllStandardError()
        text = bytes(raw).decode("utf-8", errors="replace").strip()
        if not text:
            return
        self._append_log(f"プレビュー(FFmpeg): {text}")

    def _bind_ffmpeg_process_retry(self, url: str, process: QtCore.QProcess) -> None:
        if not isinstance(process, QtCore.QProcess):
            return
        process.errorOccurred.connect(
            lambda _err, target_url=url: self._schedule_preview_retry(target_url, "ffmpegエラー")
        )
        process.finished.connect(
            lambda _code, _status, target_url=url: self._schedule_preview_retry(target_url, "ffmpeg終了")
        )

    def _stop_all_previews(self) -> None:
        for url in list(self.preview_sessions.keys()):
            self._stop_preview_for_url(url, remove_tab=True)

    def _update_timeshift_button_state(self) -> None:
        self.timeshift_button.setEnabled(self._has_active_recording_tasks())

    def _collect_timeshift_candidates(self) -> list[tuple[str, Path]]:
        candidates: list[tuple[str, Path]] = []
        if (
            self.manual_recording_url
            and self.manual_recording_path is not None
            and isinstance(self.worker_thread, QtCore.QThread)
            and self.worker_thread.isRunning()
        ):
            label = self._resolve_channel_folder_label(self.manual_recording_url)
            candidates.append((label, self.manual_recording_path))
        for url, session in self.auto_sessions.items():
            path = session.get("output_path")
            thread = session.get("thread")
            if not isinstance(path, Path):
                continue
            if not isinstance(thread, QtCore.QThread) or not thread.isRunning():
                continue
            label = self._resolve_channel_folder_label(url)
            candidates.append((label, path))
        return candidates

    def _select_timeshift_targets(self, candidates: list[tuple[str, Path]]) -> list[Path]:
        if len(candidates) <= 1:
            return [path for _, path in candidates]
        
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("タイムシフト再生の選択")
        dialog.setModal(True)
        dialog.setMinimumSize(550, 400)
        
        # --- スタイル適用 ---
        c_primary = "#0ea5e9"
        c_bg_app = "#f1f5f9"
        c_text = "#1e293b"
        c_border = "#e2e8f0"
        
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: #ffffff;
                color: {c_text};
                font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
                font-size: 14px;
            }}
            QListWidget {{
                background-color: {c_bg_app};
                border: 1px solid {c_border};
                border-radius: 8px;
                padding: 8px;
                outline: none;
            }}
            QListWidget::item {{
                background-color: #ffffff;
                border: 1px solid {c_border};
                border-radius: 6px;
                padding: 10px;
                margin-bottom: 6px;
                color: {c_text};
            }}
            QListWidget::item:selected {{
                background-color: #e0f2fe;
                border: 1px solid {c_primary};
                color: {c_primary};
                font-weight: bold;
            }}
            QListWidget::item:hover {{
                border: 1px solid {c_primary};
            }}
            QLabel {{
                color: {c_text};
                font-weight: bold;
                font-size: 15px;
                margin-bottom: 8px;
            }}
            QPushButton {{
                background-color: #ffffff;
                border: 1px solid {c_border};
                border-radius: 6px;
                padding: 8px 16px;
                color: #475569;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {c_bg_app};
                border-color: #94a3b8;
            }}
            QPushButton#PrimaryButton {{
                background-color: {c_primary};
                color: #ffffff;
                border: none;
            }}
            QPushButton#PrimaryButton:hover {{
                background-color: #0284c7;
            }}
        """)

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        title = QtWidgets.QLabel("再生する録画を選択してください（複数選択可）")
        layout.addWidget(title)
        
        list_widget = QtWidgets.QListWidget()
        list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        
        for label, path in candidates:
            # アイコンや詳細情報をリッチに表示
            item_text = f"{label}\n{path.name}"
            item = QtWidgets.QListWidgetItem(item_text)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, path)
            list_widget.addItem(item)
            
        if list_widget.count() > 0:
            list_widget.item(0).setSelected(True)
            
        layout.addWidget(list_widget)
        
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        
        btn_cancel = QtWidgets.QPushButton("キャンセル")
        btn_cancel.clicked.connect(dialog.reject)
        
        btn_ok = QtWidgets.QPushButton("再生開始")
        btn_ok.setObjectName("PrimaryButton")
        btn_ok.setMinimumWidth(120)
        btn_ok.clicked.connect(dialog.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        
        layout.addLayout(btn_layout)
        
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return []
            
        selected_paths: list[Path] = []
        for item in list_widget.selectedItems():
            data = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if isinstance(data, Path):
                selected_paths.append(data)
        return selected_paths

    def _resolve_timeshift_target(self) -> Path | None:
        if (
            self.manual_recording_url
            and self.manual_recording_path is not None
            and isinstance(self.worker_thread, QtCore.QThread)
            and self.worker_thread.isRunning()
        ):
            return self.manual_recording_path
        input_url = self.url_input.text().strip()
        if input_url and input_url in self.auto_sessions:
            session = self.auto_sessions.get(input_url, {})
            path = session.get("output_path")
            if isinstance(path, Path):
                return path
        if len(self.auto_sessions) == 1:
            session = next(iter(self.auto_sessions.values()))
            path = session.get("output_path")
            if isinstance(path, Path):
                return path
        return None

    def _open_timeshift_window(self) -> None:
        candidates = self._collect_timeshift_candidates()
        if not candidates:
            self._show_info("タイムシフト再生の対象が特定できません。録画中のURLを入力して再試行してください。")
            return
        target_paths = self._select_timeshift_targets(candidates)
        if not target_paths:
            return
        for target_path in target_paths:
            if not target_path.exists():
                self._show_info(f"録画ファイルが見つかりません: {target_path}")
                continue
            window = TimeShiftWindow(target_path, self)
            window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
            window.destroyed.connect(
                lambda _=None, w=window: self._remove_timeshift_window(w)
            )
            self.timeshift_windows.append(window)
            window.show()

    def _remove_timeshift_window(self, window: TimeShiftWindow) -> None:
        if window in self.timeshift_windows:
            self.timeshift_windows.remove(window)
