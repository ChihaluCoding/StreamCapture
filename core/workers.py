# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import threading  # 停止フラグ制御
from pathlib import Path  # パス操作
from PyQt6 import QtCore  # PyQt6のコア機能
from streamlink import Streamlink  # Streamlink本体
from streamlink.exceptions import StreamlinkError  # Streamlink例外
from apis.api_twitch import fetch_twitch_live_urls  # Twitch API処理
from apis.api_youtube import fetch_youtube_live_urls_with_fallback  # YouTube API処理
from utils.platform_utils import normalize_twitch_login  # Twitch入力の正規化
from core.recording import (
    OUTPUT_FORMAT_TS,
    OUTPUT_FORMAT_MP3,
    OUTPUT_FORMAT_WAV,
    convert_recording,
    compress_recording,
    normalize_output_format,
    record_stream,
    transcribe_recording,
)  # 録画処理を読み込み
from utils.streamlink_utils import (  # Streamlinkヘッダー調整
    apply_streamlink_options_for_url,  # URL別オプション調整
    restore_streamlink_headers,  # ヘッダー復元
    set_streamlink_headers_for_url,  # URL別ヘッダー設定
)
from utils.ytdlp_utils import fetch_stream_url_with_ytdlp, is_ytdlp_available  # yt-dlp補助
from utils.settings_store import load_bool_setting, load_setting_value  # 設定入出力

class RecorderWorker(QtCore.QObject):  # 録画ワーカー定義
    log_signal = QtCore.pyqtSignal(str)  # ログ通知シグナル
    conversion_started = QtCore.pyqtSignal(str)  # 変換開始通知シグナル
    watermark_started = QtCore.pyqtSignal(str)  # 透かし合成開始通知シグナル
    compression_started = QtCore.pyqtSignal(str)  # 圧縮開始通知シグナル
    compression_finished = QtCore.pyqtSignal(str)  # 圧縮終了通知シグナル
    finished_signal = QtCore.pyqtSignal(int)  # 終了通知シグナル
    def __init__(  # 初期化処理
        self,  # 自身参照
        url: str,  # 配信URL
        quality: str,  # 画質指定
        output_path: Path,  # 出力パス
        output_format: str,  # 出力形式
        retry_count: int,  # リトライ回数
        retry_wait: int,  # リトライ待機秒
        http_timeout: int,  # HTTPタイムアウト
        stream_timeout: int,  # ストリームタイムアウト
        stop_event: threading.Event,  # 停止フラグ
    ) -> None:  # 返り値なし
        super().__init__()  # 親クラス初期化
        self.url = url  # URLを保存
        self.quality = quality  # 画質を保存
        self.output_path = output_path  # 出力パスを保存
        self.output_format = output_format  # 出力形式を保存
        self.retry_count = retry_count  # リトライ回数を保存
        self.retry_wait = retry_wait  # リトライ待機秒を保存
        self.http_timeout = http_timeout  # HTTPタイムアウトを保存
        self.stream_timeout = stream_timeout  # ストリームタイムアウトを保存
        self.stop_event = stop_event  # 停止フラグを保存
    def run(self) -> None:  # 録画処理実行
        session = Streamlink()  # Streamlinkセッション生成
        session.set_option("http-timeout", self.http_timeout)  # HTTPタイムアウト設定
        session.set_option("stream-timeout", self.stream_timeout)  # ストリームタイムアウト設定
        apply_streamlink_options_for_url(session, self.url)  # URL別のStreamlinkオプションを反映
        set_streamlink_headers_for_url(session, self.url)  # URLに合わせてヘッダー調整
        def status_cb(message: str) -> None:  # 状態通知用コールバック
            self.log_signal.emit(message)  # ログシグナル送信
        exit_code = 0  # 終了コードの初期化
        segment_paths: list[Path] = []
        try:  # 例外処理開始
            segment_paths = record_stream(  # 録画関数を実行
                session=session,  # セッション指定
                url=self.url,  # URL指定
                quality=self.quality,  # 画質指定
                output_path=self.output_path,  # 出力パス指定
                retry_count=self.retry_count,  # リトライ回数指定
                retry_wait=self.retry_wait,  # リトライ待機指定
                stop_event=self.stop_event,  # 停止フラグ指定
                status_cb=status_cb,  # 状態通知コールバック
            )  # 録画実行終了
        except Exception as exc:  # 予期しない例外を捕捉
            status_cb(f"致命的なエラーが発生しました: {exc}")  # エラーメッセージ通知
            exit_code = 1  # 異常終了コードを設定
        normalized_format = normalize_output_format(self.output_format)
        if normalized_format != OUTPUT_FORMAT_TS and segment_paths:
            self.conversion_started.emit(self.url)
        converted_paths: list[Path] = []
        if normalized_format == OUTPUT_FORMAT_TS:
            converted_paths = list(segment_paths)
        else:
            watermark_enabled = load_bool_setting("watermark_enabled", False)
            watermark_mode = load_setting_value("watermark_mode", "image", str).strip().lower() or "image"
            watermark_path = load_setting_value("watermark_path", "", str).strip()
            watermark_text = load_setting_value("watermark_text", "", str).strip()
            for segment_path in segment_paths:
                if watermark_enabled and normalized_format not in (OUTPUT_FORMAT_MP3, OUTPUT_FORMAT_WAV):
                    if watermark_mode == "text" and watermark_text:
                        self.watermark_started.emit(self.url)
                    elif watermark_mode != "text" and watermark_path:
                        self.watermark_started.emit(self.url)
                converted_path = convert_recording(
                    segment_path,
                    normalized_format,
                    status_cb=status_cb,
                )
                if converted_path:
                    converted_paths.append(converted_path)
        final_paths = list(converted_paths)
        if load_bool_setting("auto_compress_enabled", False):
            self.compression_started.emit(self.url)
            final_paths = []
            for converted_path in converted_paths:
                compressed_path = compress_recording(converted_path, status_cb=status_cb)
                final_paths.append(compressed_path or converted_path)
            self.compression_finished.emit(self.url)
        if load_bool_setting("transcribe_enabled", False):
            model = load_setting_value("transcribe_model", "small", str)
            for final_path in final_paths:
                transcribe_recording(final_path, model, status_cb=status_cb)
        self.finished_signal.emit(exit_code)  # 終了シグナル送信

class AutoCheckWorker(QtCore.QObject):  # 自動監視ワーカー定義
    log_signal = QtCore.pyqtSignal(str)  # ログ通知シグナル
    notify_signal = QtCore.pyqtSignal(str)  # 通知用シグナル
    finished_signal = QtCore.pyqtSignal(list, list)  # 完了通知シグナル
    def __init__(  # 初期化処理
        self,  # 自身参照
        youtube_api_key: str,  # YouTube APIキー
        youtube_channels: list[str],  # YouTube配信者一覧
        youtube_notify_channels: list[str],  # YouTube通知のみ一覧
        twitch_client_id: str,  # Twitch Client ID
        twitch_client_secret: str,  # Twitch Client Secret
        twitch_channels: list[str],  # Twitch配信者一覧
        twitch_notify_channels: list[str],  # Twitch通知のみ一覧
        fallback_urls: list[str],  # URL監視のフォールバック一覧
        fallback_notify_urls: list[str],  # 通知のみのURL監視一覧
        http_timeout: int,  # HTTPタイムアウト
        stream_timeout: int,  # ストリームタイムアウト
    ) -> None:  # 返り値なし
        super().__init__()  # 親クラス初期化
        self.youtube_api_key = youtube_api_key  # YouTube APIキーを保存
        self.youtube_channels = youtube_channels  # YouTube配信者一覧を保存
        self.youtube_notify_channels = youtube_notify_channels  # YouTube通知のみ一覧を保存
        self.twitch_client_id = twitch_client_id  # Twitch Client IDを保存
        self.twitch_client_secret = twitch_client_secret  # Twitch Client Secretを保存
        self.twitch_channels = twitch_channels  # Twitch配信者一覧を保存
        self.twitch_notify_channels = twitch_notify_channels  # Twitch通知のみ一覧を保存
        self.fallback_urls = fallback_urls  # フォールバックURL一覧を保存
        self.fallback_notify_urls = fallback_notify_urls  # 通知のみURL一覧を保存
        self.http_timeout = http_timeout  # HTTPタイムアウトを保存
        self.stream_timeout = stream_timeout  # ストリームタイムアウトを保存
        self.stop_event = threading.Event()  # 停止フラグを生成
    def stop(self) -> None:  # 停止処理
        self.stop_event.set()  # 停止フラグを設定
    def run(self) -> None:  # 監視処理実行
        live_urls: list[str] = []  # ライブURL一覧
        notify_urls: list[str] = []  # 通知のみURL一覧
        try:  # 例外処理開始
            if self.youtube_channels:  # YouTube配信者がある場合
                def _notify_youtube_multi(entry: str, live_ids: list[str]) -> None:  # 複数配信通知
                    message = (  # 通知メッセージを組み立て
                        "YouTubeで複数の配信枠を検知しましたが、"  # 先頭文
                        "APIキーが未設定のため録画を開始しません。 "  # 条件説明
                        f"対象: {entry}"  # 対象情報
                    )  # メッセージ生成の終了
                    self.notify_signal.emit(message)  # ポップアップ通知
                    self.log_signal.emit(f"自動監視: {message}")  # ログにも記録
                youtube_live = fetch_youtube_live_urls_with_fallback(  # YouTubeライブ取得
                    api_key=self.youtube_api_key,  # APIキー指定
                    entries=self.youtube_channels,  # 配信者一覧指定
                    log_cb=self.log_signal.emit,  # ログ出力
                    multi_detect_cb=_notify_youtube_multi,  # 複数配信検知通知
                )  # 取得終了
                for live_url in youtube_live:  # ライブURLごとに処理
                    if live_url not in live_urls:  # 重複確認
                        live_urls.append(live_url)  # ライブURLを追加
            if self.youtube_notify_channels:  # YouTube通知のみ一覧がある場合
                youtube_notify = fetch_youtube_live_urls_with_fallback(  # YouTubeライブ取得
                    api_key=self.youtube_api_key,  # APIキー指定
                    entries=self.youtube_notify_channels,  # 配信者一覧指定
                    log_cb=self.log_signal.emit,  # ログ出力
                    multi_detect_cb=None,  # 通知のみは追加通知を行わない
                )  # 取得終了
                for live_url in youtube_notify:  # ライブURLごとに処理
                    if live_url in live_urls:  # 録画対象が優先
                        continue
                    if live_url not in notify_urls:  # 重複確認
                        notify_urls.append(live_url)  # 通知URLを追加
            if self.twitch_channels:  # Twitch配信者がある場合
                if not self.twitch_client_id or not self.twitch_client_secret:  # APIキーが不足の場合
                    self.log_signal.emit("自動監視: Twitch APIキー未設定のためURL監視に切り替えます。")  # 監視方法ログ
                    for entry in self.twitch_channels:  # 入力ごとに処理
                        login = normalize_twitch_login(entry)  # ログイン名を正規化
                        if not login:  # ログイン名が空の場合
                            continue  # 次の入力へ
                        url = f"https://www.twitch.tv/{login}"  # Twitch URLを生成
                        if url not in self.fallback_urls:  # 重複確認
                            self.fallback_urls.append(url)  # フォールバックへ追加
                else:  # APIキーがある場合
                    twitch_live = fetch_twitch_live_urls(  # Twitchライブ取得
                        client_id=self.twitch_client_id,  # Client ID指定
                        client_secret=self.twitch_client_secret,  # Client Secret指定
                        entries=self.twitch_channels,  # 配信者一覧指定
                        log_cb=self.log_signal.emit,  # ログ出力
                    )  # 取得終了
                    for live_url in twitch_live:  # ライブURLごとに処理
                        if live_url not in live_urls:  # 重複確認
                            live_urls.append(live_url)  # ライブURLを追加
            if self.twitch_notify_channels:  # Twitch通知のみ一覧がある場合
                if not self.twitch_client_id or not self.twitch_client_secret:  # APIキーが不足の場合
                    for entry in self.twitch_notify_channels:  # 入力ごとに処理
                        login = normalize_twitch_login(entry)  # ログイン名を正規化
                        if not login:  # ログイン名が空の場合
                            continue  # 次の入力へ
                        url = f"https://www.twitch.tv/{login}"  # Twitch URLを生成
                        if url not in self.fallback_notify_urls:  # 重複確認
                            self.fallback_notify_urls.append(url)  # 通知のみへ追加
                else:  # APIキーがある場合
                    twitch_notify = fetch_twitch_live_urls(  # Twitchライブ取得
                        client_id=self.twitch_client_id,  # Client ID指定
                        client_secret=self.twitch_client_secret,  # Client Secret指定
                        entries=self.twitch_notify_channels,  # 配信者一覧指定
                        log_cb=self.log_signal.emit,  # ログ出力
                    )  # 取得終了
                    for live_url in twitch_notify:  # ライブURLごとに処理
                        if live_url in live_urls:  # 録画対象が優先
                            continue
                        if live_url not in notify_urls:  # 重複確認
                            notify_urls.append(live_url)  # 通知URLを追加
            if self.fallback_urls or self.fallback_notify_urls:  # フォールバックURLがある場合
                session = Streamlink()  # Streamlinkセッション生成
                session.set_option("http-timeout", self.http_timeout)  # HTTPタイムアウト設定
                session.set_option("stream-timeout", self.stream_timeout)  # ストリームタイムアウト設定
                def _check_fallback_urls(urls: list[str], target_list: list[str], log_prefix: str) -> None:
                    for url in urls:  # URLごとにチェック
                        if self.stop_event.is_set():  # 停止要求の確認
                            break  # ループを中断
                        if "whowatch.tv" in url and is_ytdlp_available():  # ふわっちはyt-dlp優先
                            stream_url = fetch_stream_url_with_ytdlp(url, self.log_signal.emit)  # yt-dlpで確認
                            if stream_url:  # URLが取れる場合
                                if url not in target_list:  # 重複確認
                                    target_list.append(url)  # ライブURLとして追加
                                self.log_signal.emit(f"{log_prefix}: yt-dlpで配信検知 {url}")  # 検知ログ
                            else:
                                self.log_signal.emit(f"{log_prefix}: yt-dlpで配信なし {url}")  # 配信なしログ
                            continue  # Streamlinkには回さない
                        self.log_signal.emit(f"{log_prefix}: チェック開始 {url}")  # 監視開始ログ
                        apply_streamlink_options_for_url(session, url)  # URL別のStreamlinkオプションを反映
                        original_headers = set_streamlink_headers_for_url(session, url)  # ヘッダー調整
                        try:  # 例外処理開始
                            streams = session.streams(url)  # ストリーム一覧を取得
                        except StreamlinkError as exc:  # Streamlink例外の捕捉
                            self.log_signal.emit(f"{log_prefix}: 取得失敗 {url} - {exc}")  # 失敗ログ通知
                            if is_ytdlp_available():  # yt-dlpが使える場合
                                stream_url = fetch_stream_url_with_ytdlp(url, self.log_signal.emit)  # yt-dlpで確認
                                if stream_url:  # URLが取れる場合
                                    if url not in target_list:  # 重複確認
                                        target_list.append(url)  # ライブURLとして追加
                                    self.log_signal.emit(f"{log_prefix}: yt-dlpで配信検知 {url}")  # 検知ログ
                            continue  # 次のURLへ
                        finally:  # 後始末
                            restore_streamlink_headers(session, original_headers)  # ヘッダーを復元
                        if streams:  # ストリームが取得できた場合
                            if url not in target_list:  # 重複確認
                                target_list.append(url)  # ライブURLとして追加
                            self.log_signal.emit(f"{log_prefix}: 配信検知 {url}")  # 配信検知ログ
                        else:  # ストリームが無い場合
                            if (
                                ("bigo.tv" in url or "bigo.live" in url or "whowatch.tv" in url)
                                and is_ytdlp_available()
                            ):  # yt-dlp優先対象
                                stream_url = fetch_stream_url_with_ytdlp(url, self.log_signal.emit)  # yt-dlpで確認
                                if stream_url:  # URLが取れる場合
                                    if url not in target_list:  # 重複確認
                                        target_list.append(url)  # ライブURLとして追加
                                    self.log_signal.emit(f"{log_prefix}: yt-dlpで配信検知 {url}")  # 検知ログ
                                    continue  # 次のURLへ
                            self.log_signal.emit(f"{log_prefix}: 配信なし {url}")  # 配信なしログ
                if self.fallback_urls:
                    _check_fallback_urls(self.fallback_urls, live_urls, "自動監視")
                if self.fallback_notify_urls:
                    notify_candidates = [url for url in self.fallback_notify_urls if url not in live_urls]
                    _check_fallback_urls(notify_candidates, notify_urls, "自動監視(通知のみ)")
        except Exception as exc:  # 予期しない例外の捕捉
            self.log_signal.emit(f"自動監視: 予期しないエラー {exc}")  # 失敗ログ通知
        self.finished_signal.emit(live_urls, notify_urls)  # 完了通知
