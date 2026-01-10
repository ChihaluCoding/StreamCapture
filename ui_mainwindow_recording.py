# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import threading  # 停止フラグ制御
import time  # リトライ間隔の計測
from pathlib import Path  # パス操作
from urllib.parse import urlparse  # URL解析
from PyQt6 import QtCore, QtGui, QtMultimedia, QtMultimediaWidgets, QtWidgets  # PyQt6の主要モジュール
from config import (  # 定数群
    DEFAULT_AUTO_CHECK_INTERVAL_SEC,  # 自動監視間隔
    DEFAULT_AUTO_ENABLED,  # 自動録画の既定
    DEFAULT_ABEMA_ENTRIES,  # AbemaTV既定
    DEFAULT_BIGO_ENTRIES,  # BIGO LIVE既定
    DEFAULT_LIVE17_ENTRIES,  # 17LIVE既定
    DEFAULT_BILIBILI_ENTRIES,  # bilibili既定
    DEFAULT_FUWATCH_ENTRIES,  # ふわっち既定
    DEFAULT_KICK_ENTRIES,  # Kick既定
    DEFAULT_NICONICO_ENTRIES,  # ニコ生既定
    DEFAULT_OPENRECTV_ENTRIES,  # OPENREC.tv既定
    DEFAULT_OUTPUT_FORMAT,  # 出力形式の既定
    DEFAULT_QUALITY,  # 画質既定
    DEFAULT_RADIKO_ENTRIES,  # radiko既定
    DEFAULT_RETRY_COUNT,  # リトライ回数既定
    DEFAULT_RETRY_WAIT_SEC,  # リトライ待機既定
    DEFAULT_TIKTOK_ENTRIES,  # TikTok既定
    DEFAULT_TWITCASTING_ENTRIES,  # ツイキャス既定
)
from platform_utils import (  # 配信サービスURL処理
    derive_platform_label_for_folder,  # 配信者ラベル抽出
    normalize_platform_urls,  # URL正規化
    normalize_twitch_login,  # Twitch正規化
    normalize_youtube_entry,  # YouTube正規化
    normalize_niconico_entry,  # ニコ生正規化
    normalize_twitcasting_entry,  # ツイキャス正規化
    normalize_tiktok_entry,  # TikTok正規化
    normalize_fuwatch_entry,  # ふわっち正規化
    normalize_kick_entry,  # Kick正規化
    normalize_abema_entry,  # AbemaTV正規化
    normalize_bigo_entry,  # BIGO LIVE正規化
    normalize_17live_entry,  # 17LIVE正規化
    normalize_radiko_entry,  # radiko正規化
    normalize_openrectv_entry,  # OPENREC.tv正規化
    normalize_bilibili_entry,  # bilibili正規化
)
from recording import resolve_output_path, select_stream  # 録画系ユーティリティ
from settings_store import load_bool_setting, load_setting_value  # 設定入出力
from url_utils import derive_channel_label, merge_unique_urls, parse_auto_url_list  # URL関連ユーティリティ
from workers import AutoCheckWorker, RecorderWorker  # ワーカー処理
from streamlink_utils import (  # Streamlinkヘッダー調整
    apply_streamlink_options_for_url,  # URL別オプション調整
    restore_streamlink_headers,  # ヘッダー復元
    set_streamlink_headers_for_url,  # URL別ヘッダー設定
)


class MainWindowRecordingMixin:  # MainWindowRecordingMixin定義
    def _format_platform_name(self, url: str) -> str:
        host = urlparse(url).netloc.lower()
        if "youtube" in host or "youtu.be" in host:
            return "YouTube"
        if "twitch" in host:
            return "Twitch"
        if "twitcasting.tv" in host:
            return "ツイキャス"
        if "nicovideo.jp" in host:
            return "ニコ生"
        if "tiktok.com" in host:
            return "TikTok"
        if "kick.com" in host:
            return "Kick"
        if "abema.tv" in host:
            return "AbemaTV"
        if "17.live" in host:
            return "17LIVE"
        if "bigo.tv" in host or "bigo.live" in host:
            return "BIGO"
        if "radiko.jp" in host:
            return "radiko"
        if "openrec.tv" in host:
            return "OPENREC"
        if "bilibili.com" in host:
            return "bilibili"
        if "whowatch.tv" in host:
            return "ふわっち"
        return "不明"

    def _format_recording_label(self, url: str) -> str:
        platform = self._format_platform_name(url)
        name = None
        cache = getattr(self, "channel_display_name_cache", None)
        if isinstance(cache, dict):
            name = cache.get(url)
        if not name and hasattr(self, "_resolve_channel_display_name"):
            try:
                name = self._resolve_channel_display_name(url)
            except Exception:
                name = None
            if name and isinstance(cache, dict):
                cache[url] = name
        if not name:
            name = derive_platform_label_for_folder(url) or derive_channel_label(url)
        return f"{platform} / {name}" if name else platform

    def _ensure_recording_duration_timer(self) -> QtCore.QTimer:
        timer = getattr(self, "recording_duration_timer", None)
        if isinstance(timer, QtCore.QTimer):
            return timer
        timer = QtCore.QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(self._update_recording_duration_label)
        self.recording_duration_timer = timer
        return timer

    def _format_duration(self, seconds: float) -> str:
        safe_seconds = max(0, int(seconds))
        hours = safe_seconds // 3600
        minutes = (safe_seconds % 3600) // 60
        secs = safe_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _update_recording_duration_label(self) -> None:
        label_widget = getattr(self, "recording_duration_label", None)
        if not isinstance(label_widget, QtWidgets.QLabel):
            return
        now = time.monotonic()
        lines: list[str] = []
        manual_started = getattr(self, "manual_recording_started_at", None)
        if isinstance(manual_started, (int, float)):
            duration = self._format_duration(now - manual_started)
            if isinstance(getattr(self, "manual_recording_url", None), str):
                display_label = self._format_recording_label(self.manual_recording_url)
                lines.append(f"{display_label}: {duration}")
            else:
                lines.append(f"手動: {duration}")
        auto_sessions = getattr(self, "auto_sessions", {})
        if isinstance(auto_sessions, dict) and auto_sessions:
            max_lines = 5
            for index, (url, session) in enumerate(auto_sessions.items()):
                if index >= max_lines:
                    break
                started_at = session.get("started_at")
                if not isinstance(started_at, (int, float)):
                    continue
                display_label = self._format_recording_label(url)
                lines.append(f"{display_label}: {self._format_duration(now - started_at)}")
            remaining = len(auto_sessions) - max_lines
            if remaining > 0:
                lines.append(f"他 {remaining}件")
        if not lines:
            label_widget.setText("録画時間: 00:00:00")
        else:
            label_widget.setText("\n".join(lines))

    def _stop_recording_duration_timer_if_idle(self) -> None:
        timer = getattr(self, "recording_duration_timer", None)
        if not isinstance(timer, QtCore.QTimer):
            return
        has_manual = getattr(self, "manual_recording_started_at", None)
        if has_manual is not None:
            return
        auto_sessions = getattr(self, "auto_sessions", {})
        if isinstance(auto_sessions, dict) and auto_sessions:
            return
        timer.stop()
        self._update_recording_duration_label()
    def _configure_auto_monitor(self) -> None:  # 自動監視の設定
        enabled = load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED)  # 有効設定を取得
        interval = load_setting_value("auto_check_interval", DEFAULT_AUTO_CHECK_INTERVAL_SEC, int)  # 間隔設定を取得
        self._refresh_auto_resume_button_state()  # 自動録画再開ボタンの状態を更新
        if self.auto_paused_by_user:  # 手動停止中の場合
            if self.auto_timer.isActive():  # 自動監視が動作中の場合
                self.auto_timer.stop()  # 自動監視を停止
            if self.auto_check_worker is not None:  # 自動監視ワーカーが存在する場合
                self.auto_check_worker.stop()  # 監視停止を要求
            self._cleanup_auto_check_thread()  # 自動監視スレッドを後始末
            self.auto_check_in_progress = False  # 監視中フラグを解除
            if enabled:  # 自動録画が有効の場合
                self._append_log("自動監視: 手動停止中のため停止します。")  # 手動停止中ログ
            return  # 手動停止中は再設定しない
        youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧を取得
        twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧を取得
        twitcasting_urls = self._get_auto_twitcasting_urls()  # ツイキャスURL一覧を取得
        niconico_urls = self._get_auto_niconico_urls()  # ニコ生URL一覧を取得
        tiktok_urls = self._get_auto_tiktok_urls()  # TikTok URL一覧を取得
        fuwatch_urls = self._get_auto_fuwatch_urls()  # ふわっちURL一覧を取得
        kick_urls = self._get_auto_kick_urls()  # Kick URL一覧を取得
        abema_urls = self._get_auto_abema_urls()  # AbemaTV URL一覧を取得
        live17_urls = self._get_auto_17live_urls()  # 17LIVE URL一覧を取得
        bigo_urls = self._get_auto_bigo_urls()  # BIGO LIVE URL一覧を取得
        radiko_urls = self._get_auto_radiko_urls()  # radiko URL一覧を取得
        openrectv_urls = self._get_auto_openrectv_urls()  # OPENREC.tv URL一覧を取得
        bilibili_urls = self._get_auto_bilibili_urls()  # bilibili URL一覧を取得
        merged_urls = merge_unique_urls(  # 監視URLを結合
            twitcasting_urls,  # ツイキャスURL一覧
            niconico_urls,  # ニコ生URL一覧
            tiktok_urls,  # TikTok URL一覧
            fuwatch_urls,  # ふわっちURL一覧
            kick_urls,  # Kick URL一覧
            abema_urls,  # AbemaTV URL一覧
            live17_urls,  # 17LIVE URL一覧
            bigo_urls,  # BIGO LIVE URL一覧
            radiko_urls,  # radiko URL一覧
            openrectv_urls,  # OPENREC.tv URL一覧
            bilibili_urls,  # bilibili URL一覧
        )  # 結合の終了
        has_targets = bool(youtube_channels or twitch_channels or merged_urls)  # 監視対象の有無
        auto_startup = load_bool_setting("auto_startup_recording", True)  # 起動時自動録画設定を取得
        if enabled and has_targets and (auto_startup or self.auto_monitor_forced):  # 有効かつ監視対象がある場合
            self.auto_timer.setInterval(int(interval) * 1000)  # タイマー間隔を設定
            if not self.auto_timer.isActive():  # タイマーが停止中の場合
                self.auto_timer.start()  # タイマー開始
            self._append_log("自動監視を開始しました。")  # ログ出力
            self._trigger_auto_check_now()  # 起動直後に即時チェック
        else:  # 無効またはURLが無い場合
            if self.auto_timer.isActive():  # タイマーが動作中の場合
                self.auto_timer.stop()  # タイマー停止
            if enabled and not has_targets:  # 有効だが対象無しの場合
                self._append_log("自動監視: 監視対象が未設定のため停止します。")  # ログ出力
            # 無効時の停止ログは起動時のノイズになるため出力しない
    def _trigger_auto_check_now(self) -> None:  # 自動監視の即時実行
        if self.auto_check_in_progress:  # 監視中の場合
            return  # 重複チェックを防止
        if self.auto_paused_by_user:  # 手動停止中の場合
            return  # 何もしない
        QtCore.QTimer.singleShot(200, self._on_auto_timer)  # 少し遅延して監視を実行
    def _get_auto_twitcasting_urls(self) -> list[str]:  # ツイキャス監視URL一覧の取得
        raw_text = load_setting_value("twitcasting_entries", DEFAULT_TWITCASTING_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_twitcasting_entry)  # 正規化URL一覧を返却
    def _get_auto_niconico_urls(self) -> list[str]:  # ニコ生監視URL一覧の取得
        raw_text = load_setting_value("niconico_entries", DEFAULT_NICONICO_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_niconico_entry)  # 正規化URL一覧を返却
    def _get_auto_tiktok_urls(self) -> list[str]:  # TikTok監視URL一覧の取得
        raw_text = load_setting_value("tiktok_entries", DEFAULT_TIKTOK_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_tiktok_entry)  # 正規化URL一覧を返却
    def _get_auto_fuwatch_urls(self) -> list[str]:  # ふわっち監視URL一覧の取得
        raw_text = load_setting_value("fuwatch_entries", DEFAULT_FUWATCH_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_fuwatch_entry)  # 正規化URL一覧を返却
    def _get_auto_kick_urls(self) -> list[str]:  # Kick監視URL一覧の取得
        raw_text = load_setting_value("kick_entries", DEFAULT_KICK_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_kick_entry)  # 正規化URL一覧を返却
    def _get_auto_abema_urls(self) -> list[str]:  # AbemaTV監視URL一覧の取得
        raw_text = load_setting_value("abema_entries", DEFAULT_ABEMA_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_abema_entry)  # 正規化URL一覧を返却
    def _get_auto_17live_urls(self) -> list[str]:  # 17LIVE監視URL一覧の取得
        raw_text = load_setting_value("live17_entries", DEFAULT_LIVE17_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_17live_entry)  # 正規化URL一覧を返却
    def _get_auto_bigo_urls(self) -> list[str]:  # BIGO LIVE監視URL一覧の取得
        raw_text = load_setting_value("bigo_entries", DEFAULT_BIGO_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_bigo_entry)  # 正規化URL一覧を返却
    def _get_auto_radiko_urls(self) -> list[str]:  # radiko監視URL一覧の取得
        raw_text = load_setting_value("radiko_entries", DEFAULT_RADIKO_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_radiko_entry)  # 正規化URL一覧を返却
    def _get_auto_openrectv_urls(self) -> list[str]:  # OPENREC.tv監視URL一覧の取得
        raw_text = load_setting_value("openrectv_entries", DEFAULT_OPENRECTV_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_openrectv_entry)  # 正規化URL一覧を返却
    def _get_auto_bilibili_urls(self) -> list[str]:  # bilibili監視URL一覧の取得
        raw_text = load_setting_value("bilibili_entries", DEFAULT_BILIBILI_ENTRIES, str)  # 設定文字列を取得
        entries = parse_auto_url_list(raw_text)  # 入力一覧を取得
        return normalize_platform_urls(entries, normalize_bilibili_entry)  # 正規化URL一覧を返却
    def _get_auto_youtube_channels(self) -> list[str]:  # YouTube配信者一覧の取得
        raw_text = load_setting_value("youtube_channels", "", str)  # 設定文字列を取得
        return parse_auto_url_list(raw_text)  # 解析済み一覧を返却
    def _get_auto_twitch_channels(self) -> list[str]:  # Twitch配信者一覧の取得
        raw_text = load_setting_value("twitch_channels", "", str)  # 設定文字列を取得
        return parse_auto_url_list(raw_text)  # 解析済み一覧を返却
    def _collect_preview_urls_from_settings(self) -> list[str]:  # 設定からプレビューURL一覧を作成
        twitcasting_urls = self._get_auto_twitcasting_urls()  # ツイキャスURL一覧を取得
        niconico_urls = self._get_auto_niconico_urls()  # ニコ生URL一覧を取得
        tiktok_urls = self._get_auto_tiktok_urls()  # TikTok URL一覧を取得
        fuwatch_urls = self._get_auto_fuwatch_urls()  # ふわっちURL一覧を取得
        kick_urls = self._get_auto_kick_urls()  # Kick URL一覧を取得
        abema_urls = self._get_auto_abema_urls()  # AbemaTV URL一覧を取得
        live17_urls = self._get_auto_17live_urls()  # 17LIVE URL一覧を取得
        bigo_urls = self._get_auto_bigo_urls()  # BIGO LIVE URL一覧を取得
        radiko_urls = self._get_auto_radiko_urls()  # radiko URL一覧を取得
        openrectv_urls = self._get_auto_openrectv_urls()  # OPENREC.tv URL一覧を取得
        bilibili_urls = self._get_auto_bilibili_urls()  # bilibili URL一覧を取得
        youtube_entries = self._get_auto_youtube_channels()  # YouTube入力一覧を取得
        twitch_entries = self._get_auto_twitch_channels()  # Twitch入力一覧を取得
        youtube_urls: list[str] = []  # YouTubeプレビューURL一覧を初期化
        for entry in youtube_entries:  # 入力ごとに処理
            cleaned = entry.strip()  # 入力値を正規化
            if not cleaned:  # 空の場合
                continue  # 次へ
            url = ""  # URL変数を初期化
            if cleaned.startswith("http://") or cleaned.startswith("https://"):  # URL形式の場合
                url = cleaned  # そのまま使用
            elif "youtube.com" in cleaned or "youtu.be" in cleaned:  # スキーム無しURLの場合
                url = f"https://{cleaned}"  # httpsを補完
            else:  # URL形式でない場合
                url = build_youtube_live_page_url(cleaned) or ""  # /live URLを生成
            if not url:  # URLが空の場合
                continue  # 次へ
            if url not in youtube_urls:  # 重複していない場合
                youtube_urls.append(url)  # URLを追加
        twitch_urls: list[str] = []  # TwitchプレビューURL一覧を初期化
        for entry in twitch_entries:  # 入力ごとに処理
            login = normalize_twitch_login(entry)  # ログイン名を正規化
            if not login:  # ログイン名が空の場合
                continue  # 次へ
            url = f"https://www.twitch.tv/{login}"  # Twitch URLを生成
            if url not in twitch_urls:  # 重複していない場合
                twitch_urls.append(url)  # URLを追加
        merged_urls = merge_unique_urls(  # プレビュー対象URLを結合
            twitcasting_urls,  # ツイキャスURL一覧
            niconico_urls,  # ニコ生URL一覧
            tiktok_urls,  # TikTok URL一覧
            fuwatch_urls,  # ふわっちURL一覧
            kick_urls,  # Kick URL一覧
            abema_urls,  # AbemaTV URL一覧
            live17_urls,  # 17LIVE URL一覧
            bigo_urls,  # BIGO LIVE URL一覧
            radiko_urls,  # radiko URL一覧
            openrectv_urls,  # OPENREC.tv URL一覧
            bilibili_urls,  # bilibili URL一覧
            youtube_urls,  # YouTube URL一覧
            twitch_urls,  # Twitch URL一覧
        )  # 結合の終了
        return merged_urls  # 結合済みURL一覧を返却
    def _on_auto_timer(self) -> None:  # 自動監視タイマー処理
        if self.auto_check_in_progress:  # 監視中の場合
            return  # 重複チェックを防止
        if self.auto_paused_by_user:  # 手動停止中の場合
            return  # 何もしない
        if not load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED):  # 無効の場合
            return  # 何もしない
        twitcasting_urls = self._get_auto_twitcasting_urls()  # ツイキャスURL一覧を取得
        niconico_urls = self._get_auto_niconico_urls()  # ニコ生URL一覧を取得
        tiktok_urls = self._get_auto_tiktok_urls()  # TikTok URL一覧を取得
        fuwatch_urls = self._get_auto_fuwatch_urls()  # ふわっちURL一覧を取得
        kick_urls = self._get_auto_kick_urls()  # Kick URL一覧を取得
        abema_urls = self._get_auto_abema_urls()  # AbemaTV URL一覧を取得
        live17_urls = self._get_auto_17live_urls()  # 17LIVE URL一覧を取得
        bigo_urls = self._get_auto_bigo_urls()  # BIGO LIVE URL一覧を取得
        radiko_urls = self._get_auto_radiko_urls()  # radiko URL一覧を取得
        openrectv_urls = self._get_auto_openrectv_urls()  # OPENREC.tv URL一覧を取得
        bilibili_urls = self._get_auto_bilibili_urls()  # bilibili URL一覧を取得
        youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧を取得
        twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧を取得
        merged_urls = merge_unique_urls(  # 監視URLを結合
            twitcasting_urls,  # ツイキャスURL一覧
            niconico_urls,  # ニコ生URL一覧
            tiktok_urls,  # TikTok URL一覧
            fuwatch_urls,  # ふわっちURL一覧
            kick_urls,  # Kick URL一覧
            abema_urls,  # AbemaTV URL一覧
            live17_urls,  # 17LIVE URL一覧
            bigo_urls,  # BIGO LIVE URL一覧
            radiko_urls,  # radiko URL一覧
            openrectv_urls,  # OPENREC.tv URL一覧
            bilibili_urls,  # bilibili URL一覧
        )  # 結合の終了
        if not (merged_urls or youtube_channels or twitch_channels):  # 対象が無い場合
            return  # 何もしない
        self._start_auto_check(merged_urls)  # 自動監視を開始
    def _start_auto_check(self, urls: list[str]) -> None:  # 自動監視の開始
        self.auto_check_in_progress = True  # 監視中フラグを設定
        http_timeout = load_setting_value("http_timeout", 20, int)  # HTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # ストリームタイムアウト取得
        youtube_api_key = load_setting_value("youtube_api_key", "", str).strip()  # YouTube APIキー取得
        youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧取得
        twitch_client_id = load_setting_value("twitch_client_id", "", str).strip()  # Twitch Client ID取得
        twitch_client_secret = load_setting_value("twitch_client_secret", "", str).strip()  # Twitch Client Secret取得
        twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧取得
        self.auto_check_thread = QtCore.QThread()  # 監視スレッドを生成
        self.auto_check_worker = AutoCheckWorker(  # 監視ワーカー生成
            youtube_api_key=youtube_api_key,  # YouTube APIキー指定
            youtube_channels=youtube_channels,  # YouTube配信者指定
            twitch_client_id=twitch_client_id,  # Twitch Client ID指定
            twitch_client_secret=twitch_client_secret,  # Twitch Client Secret指定
            twitch_channels=twitch_channels,  # Twitch配信者指定
            fallback_urls=urls,  # フォールバックURL指定
            http_timeout=int(http_timeout),  # HTTPタイムアウト指定
            stream_timeout=int(stream_timeout),  # ストリームタイムアウト指定
        )  # ワーカー生成終了
        self.auto_check_worker.moveToThread(self.auto_check_thread)  # ワーカーをスレッドへ移動
        self.auto_check_thread.started.connect(self.auto_check_worker.run)  # 開始イベント接続
        self.auto_check_worker.log_signal.connect(self._append_log)  # ログ接続
        self.auto_check_worker.notify_signal.connect(self._show_info)  # 通知ポップアップを接続
        self.auto_check_worker.finished_signal.connect(self._on_auto_check_finished)  # 完了イベント接続
        self.auto_check_thread.start()  # 監視スレッド開始
    def _on_auto_check_finished(self, live_urls: list[str]) -> None:  # 自動監視完了処理
        if self.auto_paused_by_user:  # 手動停止中の場合
            self._append_log("自動監視: 手動停止中のため録画開始をスキップしました。")  # スキップログ
            self._cleanup_auto_check_thread()  # 自動監視スレッドを後始末
            self.auto_check_in_progress = False  # 監視中フラグを解除
            return  # 録画開始はしない
        if not load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED):  # 自動録画が無効の場合
            self._append_log("自動監視: 無効設定のため録画開始をスキップしました。")  # スキップログ
            self._cleanup_auto_check_thread()  # 自動監視スレッドを後始末
            self.auto_check_in_progress = False  # 監視中フラグを解除
            return  # 録画開始はしない
        for url in live_urls:  # ライブURLごとに処理
            self._start_auto_recording(url)  # 自動録画を開始
        self._cleanup_auto_check_thread()  # 監視スレッドを後始末
        self.auto_check_in_progress = False  # 監視中フラグを解除
    def _cleanup_auto_check_thread(self) -> None:  # 自動監視スレッドの後始末
        if self.auto_check_worker is not None:  # ワーカーが存在する場合
            self.auto_check_worker.deleteLater()  # ワーカーを破棄
        if self.auto_check_thread is not None:  # スレッドが存在する場合
            self.auto_check_thread.quit()  # スレッド終了要求
            self.auto_check_thread.wait(3000)  # スレッド終了待機
            self.auto_check_thread.deleteLater()  # スレッドを破棄
        self.auto_check_worker = None  # ワーカー参照を破棄
        self.auto_check_thread = None  # スレッド参照を破棄
    def _start_auto_recording(self, url: str) -> None:  # 自動録画開始処理
        normalized_url = url.strip()  # URLを正規化
        if not normalized_url:  # URLが空の場合
            return  # 処理中断
        if normalized_url in self.auto_sessions:  # 既に録画中の場合
            return  # 重複開始を防止
        if self.manual_recording_url == normalized_url:  # 手動録画中の場合
            self._append_log(f"自動録画: 手動録画中のためスキップ {normalized_url}")  # ログ出力
            return  # 処理中断
        output_dir = Path(load_setting_value("output_dir", "recordings", str))  # 出力ディレクトリ取得
        output_format = load_setting_value("output_format", DEFAULT_OUTPUT_FORMAT, str)  # 出力形式を取得
        auto_filename = None  # 配信者別ファイル名を使わない
        channel_label = self._resolve_channel_folder_label(normalized_url)  # 配信者名を取得
        output_path = resolve_output_path(  # 出力パス生成
            output_dir,  # 出力ディレクトリ
            auto_filename,  # ファイル名
            normalized_url,  # 配信URL
            channel_label=channel_label,  # 配信者ラベル
        )  # 出力パス生成終了
        quality = DEFAULT_QUALITY  # 画質は常に最高品質に固定
        retry_count = load_setting_value("retry_count", DEFAULT_RETRY_COUNT, int)  # リトライ回数取得
        retry_wait = load_setting_value("retry_wait", DEFAULT_RETRY_WAIT_SEC, int)  # リトライ待機取得
        http_timeout = load_setting_value("http_timeout", 20, int)  # HTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # ストリームタイムアウト取得
        stop_event = threading.Event()  # 停止フラグ生成
        thread = QtCore.QThread()  # 録画スレッド生成
        worker = RecorderWorker(  # 録画ワーカー生成
            url=normalized_url,  # URL指定
            quality=quality,  # 最高品質を指定
            output_path=output_path,  # 出力パス指定
            output_format=output_format,  # 出力形式指定
            retry_count=int(retry_count),  # リトライ回数指定
            retry_wait=int(retry_wait),  # リトライ待機指定
            http_timeout=int(http_timeout),  # HTTPタイムアウト指定
            stream_timeout=int(stream_timeout),  # ストリームタイムアウト指定
            stop_event=stop_event,  # 停止フラグ指定
        )  # ワーカー生成終了
        worker.moveToThread(thread)  # ワーカーをスレッドへ移動
        thread.started.connect(worker.run)  # 開始イベント接続
        worker.log_signal.connect(self._append_log)  # ログ接続
        worker.finished_signal.connect(  # 終了イベント接続
            lambda exit_code, record_url=normalized_url: self._on_auto_recording_finished(record_url, exit_code)  # 終了処理
        )  # イベント接続の終了
        thread.start()  # 録画スレッド開始
        self.auto_sessions[normalized_url] = {  # セッションを保存
            "thread": thread,  # スレッド参照
            "worker": worker,  # ワーカー参照
            "stop_event": stop_event,  # 停止フラグ参照
            "output_path": output_path,  # 出力パス参照
            "started_at": time.monotonic(),  # 開始時刻
        }  # セッション保存の終了
        self._append_log(f"自動録画開始: {normalized_url} -> {output_path}")  # ログ出力
        timer = self._ensure_recording_duration_timer()
        if not timer.isActive():
            timer.start()
        self._update_recording_duration_label()
        channel_label = self._resolve_channel_folder_label(normalized_url)  # 配信者名を取得
        self._show_tray_notification(  # 自動録画開始を通知
            "配信録画くん",  # 通知タイトル
            f"{channel_label}さんの配信の録画を開始します。",  # 通知本文
        )  # 通知表示の終了
        if self._is_twitch_url(normalized_url):  # Twitchの場合
            self._show_preview_unavailable(normalized_url, "自動録画", False)  # 非対応表示
        elif "17.live" in normalized_url:  # 17LIVEの場合
            self._show_preview_unavailable(normalized_url, "自動録画", False)  # 非対応表示
        else:  # Twitch以外の場合
            self._start_preview_for_url(  # 自動録画時のプレビュー開始
                normalized_url,  # URL指定
                update_input=False,  # 入力欄を更新しない
                reason="自動録画",  # 理由指定
                select_tab=False,  # タブを強制選択しない
            )  # プレビュー開始の終了
        if not self.stop_button.isEnabled():  # 停止ボタンが無効の場合
            self.stop_button.setEnabled(True)  # 停止ボタンを有効化
        self._update_timeshift_button_state()  # タイムシフトボタン状態を更新
    def _on_auto_recording_finished(self, url: str, exit_code: int) -> None:  # 自動録画終了処理
        session = self.auto_sessions.pop(url, None)  # セッションを取得して削除
        if session is not None:  # セッションが存在する場合
            thread = session.get("thread")  # スレッド参照を取得
            worker = session.get("worker")  # ワーカー参照を取得
            if thread is not None:  # スレッドが存在する場合
                thread.quit()  # スレッド終了要求
                thread.wait(3000)  # スレッド終了待機
                thread.deleteLater()  # スレッドを破棄
            if worker is not None:  # ワーカーが存在する場合
                worker.deleteLater()  # ワーカーを破棄
        self._append_log(f"自動録画終了: {url}（終了コード: {exit_code}）")  # ログ出力
        self._stop_preview_for_url(url, remove_tab=True)  # 自動録画のプレビューを停止
        if not self.auto_sessions and self.stop_event is None:  # 録画が無い場合
            self.stop_button.setEnabled(False)  # 停止ボタンを無効化
        self._update_timeshift_button_state()  # タイムシフトボタン状態を更新
        self._stop_recording_duration_timer_if_idle()
    def _stop_all_auto_recordings(self) -> None:  # 自動録画の一括停止
        for url, session in list(self.auto_sessions.items()):  # セッションを列挙
            stop_event = session.get("stop_event")  # 停止フラグを取得
            if isinstance(stop_event, threading.Event):  # 停止フラグが存在する場合
                stop_event.set()  # 停止フラグを設定
            thread = session.get("thread")  # スレッド参照を取得
            if isinstance(thread, QtCore.QThread):  # スレッドが存在する場合
                thread.quit()  # スレッド終了要求
                thread.wait(3000)  # スレッド終了待機
                thread.deleteLater()  # スレッドを破棄
        self.auto_sessions.clear()  # セッション一覧をクリア
        self._update_timeshift_button_state()  # タイムシフトボタン状態を更新
        self._stop_recording_duration_timer_if_idle()
    def _start_recording(self) -> None:  # 録画開始処理
        url = self.url_input.text().strip()  # URL取得
        if not url:  # URLが空の場合
            if not load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED):  # 自動録画が無効の場合
                self._show_info("配信URLを入力してください。")  # 通知表示
                return  # 処理中断
            twitcasting_urls = self._get_auto_twitcasting_urls()  # ツイキャスURL一覧を取得
            niconico_urls = self._get_auto_niconico_urls()  # ニコ生URL一覧を取得
            tiktok_urls = self._get_auto_tiktok_urls()  # TikTok URL一覧を取得
            fuwatch_urls = self._get_auto_fuwatch_urls()  # ふわっちURL一覧を取得
            kick_urls = self._get_auto_kick_urls()  # Kick URL一覧を取得
            bigo_urls = self._get_auto_bigo_urls()  # BIGO LIVE URL一覧を取得
            radiko_urls = self._get_auto_radiko_urls()  # radiko URL一覧を取得
            openrectv_urls = self._get_auto_openrectv_urls()  # OPENREC.tv URL一覧を取得
            bilibili_urls = self._get_auto_bilibili_urls()  # bilibili URL一覧を取得
            youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧を取得
            twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧を取得
            merged_urls = merge_unique_urls(  # 監視URLを結合
                twitcasting_urls,  # ツイキャスURL一覧
                niconico_urls,  # ニコ生URL一覧
                tiktok_urls,  # TikTok URL一覧
                fuwatch_urls,  # ふわっちURL一覧
                kick_urls,  # Kick URL一覧
                bigo_urls,  # BIGO LIVE URL一覧
                radiko_urls,  # radiko URL一覧
                openrectv_urls,  # OPENREC.tv URL一覧
                bilibili_urls,  # bilibili URL一覧
            )  # 結合の終了
            if not (merged_urls or youtube_channels or twitch_channels):  # 対象が無い場合
                self._show_info("自動録画の監視対象が未設定です。")  # 通知表示
                return  # 処理中断
            if self.auto_check_in_progress:  # 既に監視中の場合
                self._append_log("自動監視が実行中のため開始要求をスキップしました。")  # ログ出力
                return  # 処理中断
            if self.auto_paused_by_user:  # 手動停止状態の場合
                self.auto_paused_by_user = False  # 手動停止状態を解除
                self._refresh_auto_resume_button_state()  # 自動録画再開ボタン状態を更新
            self.auto_monitor_forced = True  # 手動開始で自動監視を有効化
            self._configure_auto_monitor()  # 自動監視を再設定
            self._append_log("録画開始により自動録画を開始します。")  # 開始ログを出力
            self._trigger_auto_check_now()  # すぐに監視を実行
            return  # 処理中断
        self.manual_recording_url = url  # 手動録画URLを記録
        self.manual_recording_started_at = time.monotonic()
        output_dir = Path(load_setting_value("output_dir", "recordings", str))  # 出力ディレクトリ取得
        output_format = load_setting_value("output_format", DEFAULT_OUTPUT_FORMAT, str)  # 出力形式を取得
        resolved_filename = None  # ファイル名は常に自動命名に任せる
        channel_label = self._resolve_channel_folder_label(url)  # 配信者名を取得
        output_path = resolve_output_path(  # 出力パス生成
            output_dir,  # 出力ディレクトリ
            resolved_filename,  # ファイル名
            url,  # 配信URL
            channel_label=channel_label,  # 配信者ラベル
        )  # 出力パス生成終了
        self.manual_recording_path = output_path  # 手動録画パスを保存
        self._append_log(f"出力パス: {output_path}")  # ログ出力
        quality = DEFAULT_QUALITY  # 画質は常に最高品質に固定
        retry_count = load_setting_value("retry_count", DEFAULT_RETRY_COUNT, int)  # リトライ回数取得
        retry_wait = load_setting_value("retry_wait", DEFAULT_RETRY_WAIT_SEC, int)  # リトライ待機取得
        http_timeout = load_setting_value("http_timeout", 20, int)  # HTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # ストリームタイムアウト取得
        self.stop_event = threading.Event()  # 停止フラグ生成
        self.worker_thread = QtCore.QThread()  # ワーカースレッド生成
        self.worker = RecorderWorker(  # ワーカー生成
            url=url,  # URL指定
            quality=quality,  # 最高品質を指定
            output_path=output_path,  # 出力パス指定
            output_format=output_format,  # 出力形式指定
            retry_count=int(retry_count),  # リトライ回数指定
            retry_wait=int(retry_wait),  # リトライ待機指定
            http_timeout=int(http_timeout),  # HTTPタイムアウト指定
            stream_timeout=int(stream_timeout),  # ストリームタイムアウト指定
            stop_event=self.stop_event,  # 停止フラグ指定
        )  # ワーカー生成終了
        self.worker.moveToThread(self.worker_thread)  # スレッドへ移動
        self.worker_thread.started.connect(self.worker.run)  # 開始イベント接続
        self.worker.log_signal.connect(self._append_log)  # ログ接続
        self.worker.finished_signal.connect(self._on_recording_finished)  # 終了イベント接続
        self.worker_thread.start()  # スレッド開始
        self.start_button.setEnabled(False)  # 開始ボタン無効化
        self.stop_button.setEnabled(True)  # 停止ボタン有効化
        self._update_timeshift_button_state()  # タイムシフトボタン状態を更新
        timer = self._ensure_recording_duration_timer()
        if not timer.isActive():
            timer.start()
        self._update_recording_duration_label()
        if self._is_twitch_url(url):  # Twitchの場合
            self._show_preview_unavailable(url, "手動録画", True)  # 非対応表示
        elif "17.live" in url:  # 17LIVEの場合
            self._show_preview_unavailable(url, "手動録画", True)  # 非対応表示
        else:  # Twitch以外の場合
            self._start_preview_for_url(  # 録画中はプレビューを表示
                url,  # URL指定
                update_input=False,  # 入力欄を更新しない
                reason="手動録画",  # 理由指定
                select_tab=True,  # タブを選択
            )  # プレビュー開始の終了
    def _stop_current_recordings(self) -> None:  # 現在の録画を停止
        if self.stop_event is not None:  # 手動録画がある場合
            self.stop_event.set()  # 停止フラグを設定
        if self.manual_recording_url:  # 手動録画URLがある場合
            self._stop_preview_for_url(self.manual_recording_url, remove_tab=True)  # 手動録画のプレビューを停止
        for record_url, session in self.auto_sessions.items():  # 自動録画セッションを確認
            stop_event = session.get("stop_event")  # 停止フラグ取得
            if isinstance(stop_event, threading.Event):  # 停止フラグがある場合
                stop_event.set()  # 停止フラグを設定
            if record_url:  # URLがある場合
                self._stop_preview_for_url(record_url, remove_tab=True)  # 自動録画のプレビューを停止
    def _pause_auto_recording_by_user(self) -> None:  # 手動停止で自動録画を止める
        if self.auto_paused_by_user:  # 既に手動停止中の場合
            return  # 何もしない
        if not load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED):  # 自動録画が無効の場合
            return  # 何もしない
        self.auto_paused_by_user = True  # 手動停止状態に設定
        self._refresh_auto_resume_button_state()  # 自動録画再開ボタン状態を更新
        if self.auto_timer.isActive():  # 自動監視が動作中の場合
            self.auto_timer.stop()  # 自動監視を停止
        if self.auto_check_worker is not None:  # 自動監視ワーカーが存在する場合
            self.auto_check_worker.stop()  # 監視停止を要求
        self._cleanup_auto_check_thread()  # 自動監視スレッドを後始末
        self.auto_check_in_progress = False  # 監視中フラグを解除
        self._append_log("自動監視を手動で停止しました。")  # 手動停止ログ
    def _resume_auto_recording(self) -> None:  # 自動録画再開処理
        if not self.auto_paused_by_user:  # 手動停止状態ではない場合
            self._append_log("自動録画は停止中ではありません。")  # 状態ログ
            return  # 処理中断
        self.auto_paused_by_user = False  # 手動停止状態を解除
        self._refresh_auto_resume_button_state()  # 自動録画再開ボタン状態を更新
        self._append_log("自動録画を再開します。")  # 再開ログ
        self._configure_auto_monitor()  # 自動監視を再設定
    def _refresh_auto_resume_button_state(self) -> None:  # 自動録画再開ボタン状態更新
        auto_enabled = load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED)  # 自動録画の有効設定を取得
        self.auto_resume_button.setEnabled(self.auto_paused_by_user and auto_enabled)  # 再開ボタンの有効状態を反映
    def _stop_recording(self) -> None:  # 録画停止処理
        if self.stop_event is None and not self.auto_sessions:  # 録画が無い場合
            self._append_log("停止対象の録画がありません。")  # ログ出力
            return  # 処理中断
        self._stop_current_recordings()  # 現在の録画を停止
        self._pause_auto_recording_by_user()  # 自動録画を手動停止状態にする
        self._append_log("停止要求を送信しました。")  # ログ出力
        self.stop_button.setEnabled(False)  # 停止ボタン無効化
    def _has_active_recording_tasks(self) -> bool:  # 録画/変換が動作中か判定
        if isinstance(self.worker_thread, QtCore.QThread) and self.worker_thread.isRunning():  # 手動録画が動作中の場合
            return True  # 動作中として返却
        for session in self.auto_sessions.values():  # 自動録画セッションを確認
            thread = session.get("thread")  # スレッド参照を取得
            if isinstance(thread, QtCore.QThread) and thread.isRunning():  # 自動録画が動作中の場合
                return True  # 動作中として返却
        return False  # 動作中の録画が無い場合
    def _on_recording_finished(self, exit_code: int) -> None:  # 録画終了処理
        self._append_log(f"録画終了（終了コード: {exit_code}）")  # ログ出力
        if self.manual_recording_url:  # 手動録画URLがある場合
            self._stop_preview_for_url(self.manual_recording_url, remove_tab=True)  # 手動録画のプレビューを停止
        self.manual_recording_url = None  # 手動録画URLをクリア
        self.manual_recording_path = None  # 手動録画パスをクリア
        self.manual_recording_started_at = None
        if self.worker_thread is not None:  # スレッドが存在する場合
            self.worker_thread.quit()  # スレッド終了要求
            self.worker_thread.wait(3000)  # スレッド終了待機
        self.worker = None  # ワーカー参照を破棄
        self.worker_thread = None  # スレッド参照を破棄
        self.stop_event = None  # 停止フラグ参照を破棄
        self.start_button.setEnabled(True)  # 開始ボタン有効化
        self.stop_button.setEnabled(False)  # 停止ボタン無効化
        self._update_timeshift_button_state()  # タイムシフトボタン状態を更新
        self._stop_recording_duration_timer_if_idle()
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # 終了時処理
        if not self._allow_quit and load_bool_setting("tray_enabled", False):  # トレイ常駐時の処理
            if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():  # トレイが使える場合
                self._apply_tray_setting(False)  # トレイ表示を反映
                self.hide()  # ウィンドウを非表示
                if isinstance(self.tray_icon, QtWidgets.QSystemTrayIcon):  # トレイアイコンがある場合
                    self.tray_icon.setToolTip("配信録画くん")  # 通知の代わりにツールチップだけ更新
                event.ignore()  # 終了を中断
                return  # 以降の終了処理を行わない
        if not self._force_quit and self._has_active_recording_tasks():  # 録画/変換が動作中の場合
            self._show_info("録画の停止処理または変換処理が完了するまで終了できません。")  # 通知表示
            event.ignore()  # 終了を中断
            return  # 処理を終了
        self._stop_all_previews()  # プレビューを停止
        if self.auto_timer.isActive():  # 自動監視が動作中の場合
            self.auto_timer.stop()  # 自動監視を停止
        if self.auto_check_worker is not None:  # 自動監視ワーカーが存在する場合
            self.auto_check_worker.stop()  # 監視停止を要求
        self._cleanup_auto_check_thread()  # 自動監視スレッドを後始末
        self._stop_all_auto_recordings()  # 自動録画を停止
        if self.stop_event is not None:  # 録画中の場合
            self.stop_event.set()  # 停止フラグを設定
        if self.worker_thread is not None:  # スレッドが存在する場合
            self.worker_thread.quit()  # スレッド終了要求
            self.worker_thread.wait(3000)  # スレッド終了待機
        event.accept()  # 終了を許可
        QtWidgets.QApplication.instance().quit()  # アプリケーションを終了
