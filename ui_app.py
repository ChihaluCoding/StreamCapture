# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import threading  # 停止フラグ制御
import shutil  # 実行ファイル探索
import socket  # UDPポート確保
from pathlib import Path  # パス操作
from typing import Optional  # 型ヒント補助
import csv  # CSV入出力
from PyQt6 import QtCore, QtGui, QtMultimedia, QtMultimediaWidgets, QtWidgets  # PyQt6の主要モジュール
from urllib.parse import urlparse  # URL解析
from streamlink import Streamlink  # Streamlink本体
from streamlink.exceptions import StreamlinkError  # Streamlink例外
from api_niconico import fetch_niconico_display_name_by_scraping  # ニコ生表示名取得
from api_tiktok import fetch_tiktok_display_name  # TikTok表示名取得
from api_twitch import fetch_twitch_display_name  # Twitch表示名取得
from api_twitcasting import fetch_twitcasting_display_name_by_scraping  # ツイキャス表示名取得
from api_youtube import (  # YouTube API処理
    fetch_youtube_channel_title_by_id,  # チャンネル名取得
    fetch_youtube_channel_title_by_video,  # 動画経由のチャンネル名取得
    fetch_youtube_oembed_author_name,  # oEmbed取得
    resolve_youtube_channel_id,  # チャンネルID解決
)
from config import (  # 定数群
    DEFAULT_AUTO_CHECK_INTERVAL_SEC,  # 自動監視間隔
    DEFAULT_AUTO_ENABLED,  # 自動録画の既定
    DEFAULT_NICONICO_ENTRIES,  # ニコ生既定
    DEFAULT_QUALITY,  # 画質既定
    DEFAULT_RETRY_COUNT,  # リトライ回数既定
    DEFAULT_RETRY_WAIT_SEC,  # リトライ待機既定
    DEFAULT_TIKTOK_ENTRIES,  # TikTok既定
    DEFAULT_TWITCASTING_ENTRIES,  # ツイキャス既定
    READ_CHUNK_SIZE,  # 読み取りチャンクサイズ
)
from platform_utils import (  # 配信サービスURL処理
    derive_platform_label_for_folder,  # フォルダ名抽出
    normalize_niconico_entry,  # ニコ生正規化
    normalize_platform_urls,  # URL正規化
    normalize_tiktok_entry,  # TikTok正規化
    normalize_twitcasting_entry,  # ツイキャス正規化
    normalize_twitch_login,  # Twitch正規化
    normalize_youtube_entry,  # YouTube正規化
    is_twitcasting_url,  # ツイキャスURL判定
)
from recording import resolve_output_path, select_stream  # 録画系ユーティリティ
from settings_store import load_bool_setting, load_setting_value, save_setting_value  # 設定入出力
from url_utils import (  # URL関連ユーティリティ
    derive_channel_label,  # 配信者ラベル推定
    merge_unique_urls,  # URL結合
    parse_auto_url_list,  # URL解析
    safe_filename_component,  # ファイル名安全化
)
from workers import AutoCheckWorker, RecorderWorker  # ワーカー処理
from streamlink_utils import (  # Streamlinkヘッダー調整
    restore_streamlink_headers,  # ヘッダー復元
    set_streamlink_headers_for_url,  # URL別ヘッダー設定
)
class PreviewPipeProxy(QtCore.QObject):  # FFmpegパイプの書き込み代理
    def __init__(self, process: QtCore.QProcess) -> None:  # 初期化処理
        super().__init__()  # 親クラス初期化
        self._process = process  # プロセス参照を保存
        self._closed = False  # クローズ状態を初期化
    @QtCore.pyqtSlot(bytes)  # バイトデータ受け取りスロット
    def write_data(self, data: bytes) -> None:  # データ書き込み
        if self._closed:  # 既にクローズ済みの場合
            return  # 何もしない
        if self._process.state() != QtCore.QProcess.ProcessState.Running:  # プロセス停止時
            return  # 何もしない
        if self._process.write(data) == -1:  # 書き込み失敗時
            return  # 何もしない
        self._process.waitForBytesWritten(100)  # 書き込みを待機
    @QtCore.pyqtSlot()  # クローズ処理スロット
    def close(self) -> None:  # クローズ処理
        if self._closed:  # 既にクローズ済みの場合
            return  # 何もしない
        self._closed = True  # クローズ状態を更新
        self._process.closeWriteChannel()  # 標準入力を閉じる
class StreamlinkPreviewWorker(QtCore.QObject):  # Streamlinkプレビュー読み込みワーカー
    data_signal = QtCore.pyqtSignal(bytes)  # データ通知シグナル
    log_signal = QtCore.pyqtSignal(str)  # ログ通知シグナル
    finished_signal = QtCore.pyqtSignal()  # 終了通知シグナル
    def __init__(self, url: str, stop_event: threading.Event) -> None:  # 初期化処理
        super().__init__()  # 親クラス初期化
        self._url = url  # URLを保存
        self._stop_event = stop_event  # 停止フラグを保存
    def run(self) -> None:  # ワーカー実行
        stream_io = None  # ストリームI/O参照を初期化
        session = Streamlink()  # Streamlinkセッション生成
        http_timeout = load_setting_value("http_timeout", 20, int)  # HTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # ストリームタイムアウト取得
        session.set_option("http-timeout", int(http_timeout))  # HTTPタイムアウト設定
        session.set_option("stream-timeout", int(stream_timeout))  # ストリームタイムアウト設定
        original_headers = dict(session.http.headers)  # 元ヘッダーを退避
        try:  # 例外処理開始
            original_headers = set_streamlink_headers_for_url(session, self._url)  # ヘッダー調整
            streams = session.streams(self._url)  # ストリーム一覧を取得
            if not streams:  # ストリームが空の場合
                self.log_signal.emit("プレビュー用ストリームが見つかりませんでした。")  # ログ通知
                return  # 処理中断
            stream = select_stream(streams, DEFAULT_QUALITY)  # 最高品質ストリームを選択
            stream_io = stream.open()  # ストリームをオープン
            while not self._stop_event.is_set():  # 停止要求が無い間ループ
                data = stream_io.read(READ_CHUNK_SIZE)  # データを読み込み
                if not data:  # データが無い場合
                    break  # ループを抜ける
                self.data_signal.emit(data)  # データを通知
        except StreamlinkError as exc:  # Streamlink例外を捕捉
            self.log_signal.emit(f"プレビュー用ストリーム取得に失敗しました: {exc}")  # 失敗ログ
        except Exception as exc:  # 予期しない例外を捕捉
            self.log_signal.emit(f"プレビュー用ストリーム読み込みに失敗しました: {exc}")  # 失敗ログ
        finally:  # 後始末
            restore_streamlink_headers(session, original_headers)  # ヘッダーを復元
            if stream_io is not None and hasattr(stream_io, "close"):  # I/Oがある場合
                try:  # 例外処理開始
                    stream_io.close()  # ストリームを閉じる
                except Exception:  # クローズ失敗時
                    pass  # 例外を無視
            self.finished_signal.emit()  # 終了通知
class SettingsDialog(QtWidgets.QDialog):  # 設定ダイアログ定義
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:  # 初期化処理
        super().__init__(parent)  # 親クラス初期化
        self.setWindowTitle("設定")  # タイトル設定
        self.setMinimumWidth(520)  # 最小幅設定
        self._build_ui()  # UI構築
        self._load_settings()  # 設定読込
    def _build_ui(self) -> None:  # UI構築処理
        layout = QtWidgets.QVBoxLayout(self)  # メインレイアウト作成
        layout.setContentsMargins(18, 18, 18, 18)  # 余白調整
        layout.setSpacing(12)  # レイアウト間隔調整
        scroll_area = QtWidgets.QScrollArea()  # スクロール領域作成
        scroll_area.setWidgetResizable(True)  # 可変サイズ設定
        scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)  # 枠線非表示
        content = QtWidgets.QWidget()  # スクロール内コンテンツ
        content_layout = QtWidgets.QVBoxLayout(content)  # コンテンツレイアウト作成
        content_layout.setContentsMargins(0, 0, 0, 0)  # 余白調整
        content_layout.setSpacing(16)  # グループ間隔調整
        basic_group = QtWidgets.QGroupBox("基本設定")  # 基本設定グループ
        basic_form = QtWidgets.QFormLayout()  # 基本設定フォーム
        basic_form.setLabelAlignment(  # ラベル右寄せ設定
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter  # 右寄せ・縦中央
        )  # ラベル右寄せ設定終了
        basic_form.setFormAlignment(  # フォーム全体の配置設定
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop  # 左寄せ・上寄せ
        )  # フォーム配置設定終了
        basic_form.setHorizontalSpacing(12)  # 水平方向の間隔設定
        basic_form.setVerticalSpacing(10)  # 垂直方向の間隔設定
        self.output_dir_input = QtWidgets.QLineEdit()  # 出力フォルダ入力
        self.output_browse = QtWidgets.QPushButton("参照")  # 参照ボタン
        self.output_browse.clicked.connect(self._browse_output_dir)  # 参照イベント接続
        output_row = QtWidgets.QHBoxLayout()  # 出力行レイアウト
        output_row.addWidget(self.output_dir_input)  # 出力フォルダ入力追加
        output_row.addWidget(self.output_browse)  # 参照ボタン追加
        basic_form.addRow("出力フォルダ", output_row)  # 行追加
        self.retry_count_input = QtWidgets.QSpinBox()  # リトライ回数入力
        self.retry_count_input.setRange(0, 999)  # 範囲設定
        basic_form.addRow("再接続回数", self.retry_count_input)  # 行追加
        self.retry_wait_input = QtWidgets.QSpinBox()  # リトライ待機入力
        self.retry_wait_input.setRange(1, 3600)  # 範囲設定
        basic_form.addRow("再接続待機秒", self.retry_wait_input)  # 行追加
        self.http_timeout_input = QtWidgets.QSpinBox()  # HTTPタイムアウト入力
        self.http_timeout_input.setRange(1, 300)  # 範囲設定
        basic_form.addRow("HTTPタイムアウト秒", self.http_timeout_input)  # 行追加
        self.stream_timeout_input = QtWidgets.QSpinBox()  # ストリームタイムアウト入力
        self.stream_timeout_input.setRange(1, 600)  # 範囲設定
        basic_form.addRow("ストリームタイムアウト秒", self.stream_timeout_input)  # 行追加
        self.preview_volume_input = QtWidgets.QDoubleSpinBox()  # プレビュー音量入力
        self.preview_volume_input.setRange(0.0, 1.0)  # 範囲設定
        self.preview_volume_input.setSingleStep(0.1)  # ステップ設定
        self.preview_volume_input.setDecimals(2)  # 表示小数桁設定
        basic_form.addRow("プレビュー音量", self.preview_volume_input)  # 行追加
        basic_group.setLayout(basic_form)  # グループにフォーム設定
        content_layout.addWidget(basic_group)  # 基本設定グループ追加
        auto_group = QtWidgets.QGroupBox("自動録画")  # 自動録画グループ
        auto_form = QtWidgets.QFormLayout()  # 自動録画フォーム
        auto_form.setLabelAlignment(  # ラベル右寄せ設定
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter  # 右寄せ・縦中央
        )  # ラベル右寄せ設定終了
        auto_form.setFormAlignment(  # フォーム全体の配置設定
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop  # 左寄せ・上寄せ
        )  # フォーム配置設定終了
        auto_form.setHorizontalSpacing(12)  # 水平方向の間隔設定
        auto_form.setVerticalSpacing(10)  # 垂直方向の間隔設定
        self.auto_enabled_input = QtWidgets.QCheckBox("自動録画を有効化")  # 自動録画有効チェック
        auto_form.addRow("自動録画", self.auto_enabled_input)  # 行追加
        self.auto_check_interval_input = QtWidgets.QSpinBox()  # 自動監視間隔入力
        self.auto_check_interval_input.setRange(20, 3600)  # 範囲設定
        auto_form.addRow("監視間隔(秒)", self.auto_check_interval_input)  # 行追加
        auto_group.setLayout(auto_form)  # グループにフォーム設定
        content_layout.addWidget(auto_group)  # 自動録画グループ追加
        service_group = QtWidgets.QGroupBox("配信監視")  # 配信監視グループ
        service_form = QtWidgets.QFormLayout()  # 配信監視フォーム
        service_form.setLabelAlignment(  # ラベル右寄せ設定
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter  # 右寄せ・縦中央
        )  # ラベル右寄せ設定終了
        service_form.setFormAlignment(  # フォーム全体の配置設定
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop  # 左寄せ・上寄せ
        )  # フォーム配置設定終了
        service_form.setHorizontalSpacing(12)  # 水平方向の間隔設定
        service_form.setVerticalSpacing(10)  # 垂直方向の間隔設定
        self.twitcasting_input = QtWidgets.QPlainTextEdit()  # ツイキャス監視入力
        self.twitcasting_input.setPlaceholderText("ツイキャスIDまたはURLを1行ずつ")  # プレースホルダ設定
        self.twitcasting_input.setMinimumHeight(90)  # 表示高さ調整
        service_form.addRow("ツイキャス監視", self.twitcasting_input)  # 行追加
        self.niconico_input = QtWidgets.QPlainTextEdit()  # ニコ生監視入力
        self.niconico_input.setPlaceholderText("lvxxxxxxxx またはURLを1行ずつ")  # プレースホルダ設定
        self.niconico_input.setMinimumHeight(90)  # 表示高さ調整
        service_form.addRow("ニコ生監視", self.niconico_input)  # 行追加
        self.tiktok_input = QtWidgets.QPlainTextEdit()  # TikTok監視入力
        self.tiktok_input.setPlaceholderText("@handle またはURLを1行ずつ")  # プレースホルダ設定
        self.tiktok_input.setMinimumHeight(90)  # 表示高さ調整
        service_form.addRow("TikTok監視", self.tiktok_input)  # 行追加
        self.youtube_channels_input = QtWidgets.QPlainTextEdit()  # YouTube監視入力
        self.youtube_channels_input.setPlaceholderText(  # プレースホルダ設定
            "チャンネルURLをそのまま貼り付け可（例: https://www.youtube.com/@xxxx/live）\n"  # 例示文1
            "@handle / チャンネルID(UC...) も可"  # 例示文2
        )  # プレースホルダ設定終了
        self.youtube_channels_input.setMinimumHeight(90)  # 表示高さ調整
        service_form.addRow("YouTube監視", self.youtube_channels_input)  # 行追加
        self.twitch_channels_input = QtWidgets.QPlainTextEdit()  # Twitch監視入力
        self.twitch_channels_input.setPlaceholderText(  # プレースホルダ設定
            "ログイン名 / URL（https://www.twitch.tv/xxxx）を1行ずつ"  # 例示文
        )  # プレースホルダ設定終了
        self.twitch_channels_input.setMinimumHeight(90)  # 表示高さ調整
        service_form.addRow("Twitch監視", self.twitch_channels_input)  # 行追加
        service_group.setLayout(service_form)  # グループにフォーム設定
        content_layout.addWidget(service_group)  # 配信監視グループ追加
        api_group = QtWidgets.QGroupBox("API・認証")  # API設定グループ
        api_form = QtWidgets.QFormLayout()  # API設定フォーム
        api_form.setLabelAlignment(  # ラベル右寄せ設定
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter  # 右寄せ・縦中央
        )  # ラベル右寄せ設定終了
        api_form.setFormAlignment(  # フォーム全体の配置設定
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop  # 左寄せ・上寄せ
        )  # フォーム配置設定終了
        api_form.setHorizontalSpacing(12)  # 水平方向の間隔設定
        api_form.setVerticalSpacing(10)  # 垂直方向の間隔設定
        self.youtube_api_key_input = QtWidgets.QLineEdit()  # YouTube APIキー入力
        self.youtube_api_key_input.setPlaceholderText("YouTube Data API v3 キー")  # プレースホルダ設定
        api_form.addRow("YouTube APIキー", self.youtube_api_key_input)  # 行追加
        self.twitch_client_id_input = QtWidgets.QLineEdit()  # Twitch Client ID入力
        self.twitch_client_id_input.setPlaceholderText("Twitch Client ID")  # プレースホルダ設定
        api_form.addRow("Twitch Client ID", self.twitch_client_id_input)  # 行追加
        self.twitch_client_secret_input = QtWidgets.QLineEdit()  # Twitch Client Secret入力
        self.twitch_client_secret_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)  # マスク表示設定
        self.twitch_client_secret_input.setPlaceholderText("Twitch Client Secret")  # プレースホルダ設定
        api_form.addRow("Twitch Client Secret", self.twitch_client_secret_input)  # 行追加
        api_group.setLayout(api_form)  # グループにフォーム設定
        content_layout.addWidget(api_group)  # API設定グループ追加
        content_layout.addStretch(1)  # 下余白伸縮追加
        scroll_area.setWidget(content)  # スクロールにコンテンツ設定
        layout.addWidget(scroll_area)  # スクロール領域追加
        button_row = QtWidgets.QHBoxLayout()  # ボタン行レイアウト
        self.save_button = QtWidgets.QPushButton("保存")  # 保存ボタン
        self.cancel_button = QtWidgets.QPushButton("キャンセル")  # キャンセルボタン
        self.save_button.clicked.connect(self._save_settings)  # 保存イベント接続
        self.cancel_button.clicked.connect(self.reject)  # キャンセルイベント接続
        button_row.addStretch(1)  # 余白追加
        button_row.addWidget(self.save_button)  # 保存ボタン追加
        button_row.addWidget(self.cancel_button)  # キャンセルボタン追加
        layout.addLayout(button_row)  # ボタン行追加
    def _load_settings(self) -> None:  # 設定読み込み
        self.output_dir_input.setText(  # 出力フォルダ設定
            load_setting_value("output_dir", "recordings", str)  # 設定値取得
        )  # 設定反映終了
        self.retry_count_input.setValue(  # リトライ回数設定
            load_setting_value("retry_count", DEFAULT_RETRY_COUNT, int)  # 設定値取得
        )  # 設定反映終了
        self.retry_wait_input.setValue(  # リトライ待機設定
            load_setting_value("retry_wait", DEFAULT_RETRY_WAIT_SEC, int)  # 設定値取得
        )  # 設定反映終了
        self.http_timeout_input.setValue(  # HTTPタイムアウト設定
            load_setting_value("http_timeout", 20, int)  # 設定値取得
        )  # 設定反映終了
        self.stream_timeout_input.setValue(  # ストリームタイムアウト設定
            load_setting_value("stream_timeout", 60, int)  # 設定値取得
        )  # 設定反映終了
        self.preview_volume_input.setValue(  # プレビュー音量設定
            load_setting_value("preview_volume", 0.5, float)  # 設定値取得
        )  # 設定反映終了
        self.auto_enabled_input.setChecked(  # 自動録画有効設定
            load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED)  # 設定値取得
        )  # 設定反映終了
        self.auto_check_interval_input.setValue(  # 自動監視間隔設定
            load_setting_value("auto_check_interval", DEFAULT_AUTO_CHECK_INTERVAL_SEC, int)  # 設定値取得
        )  # 設定反映終了
        self.twitcasting_input.setPlainText(  # ツイキャス監視設定
            load_setting_value("twitcasting_entries", DEFAULT_TWITCASTING_ENTRIES, str)  # 設定値取得
        )  # 設定反映終了
        self.niconico_input.setPlainText(  # ニコ生監視設定
            load_setting_value("niconico_entries", DEFAULT_NICONICO_ENTRIES, str)  # 設定値取得
        )  # 設定反映終了
        self.tiktok_input.setPlainText(  # TikTok監視設定
            load_setting_value("tiktok_entries", DEFAULT_TIKTOK_ENTRIES, str)  # 設定値取得
        )  # 設定反映終了
        self.youtube_api_key_input.setText(  # YouTube APIキー設定
            load_setting_value("youtube_api_key", "", str)  # 設定値取得
        )  # 設定反映終了
        self.youtube_channels_input.setPlainText(  # YouTube配信者設定
            load_setting_value("youtube_channels", "", str)  # 設定値取得
        )  # 設定反映終了
        self.twitch_client_id_input.setText(  # Twitch Client ID設定
            load_setting_value("twitch_client_id", "", str)  # 設定値取得
        )  # 設定反映終了
        self.twitch_client_secret_input.setText(  # Twitch Client Secret設定
            load_setting_value("twitch_client_secret", "", str)  # 設定値取得
        )  # 設定反映終了
        self.twitch_channels_input.setPlainText(  # Twitch配信者設定
            load_setting_value("twitch_channels", "", str)  # 設定値取得
        )  # 設定反映終了
    def _save_settings(self) -> None:  # 設定保存
        save_setting_value("output_dir", self.output_dir_input.text().strip())  # 出力フォルダ保存
        save_setting_value("retry_count", int(self.retry_count_input.value()))  # リトライ回数保存
        save_setting_value("retry_wait", int(self.retry_wait_input.value()))  # リトライ待機保存
        save_setting_value("http_timeout", int(self.http_timeout_input.value()))  # HTTPタイムアウト保存
        save_setting_value("stream_timeout", int(self.stream_timeout_input.value()))  # ストリームタイムアウト保存
        save_setting_value("preview_volume", float(self.preview_volume_input.value()))  # プレビュー音量保存
        save_setting_value("auto_enabled", int(self.auto_enabled_input.isChecked()))  # 自動録画有効保存
        save_setting_value("auto_check_interval", int(self.auto_check_interval_input.value()))  # 自動監視間隔保存
        save_setting_value("twitcasting_entries", self.twitcasting_input.toPlainText().strip())  # ツイキャス監視保存
        save_setting_value("niconico_entries", self.niconico_input.toPlainText().strip())  # ニコ生監視保存
        save_setting_value("tiktok_entries", self.tiktok_input.toPlainText().strip())  # TikTok監視保存
        save_setting_value("youtube_api_key", self.youtube_api_key_input.text().strip())  # YouTube APIキー保存
        save_setting_value("youtube_channels", self.youtube_channels_input.toPlainText().strip())  # YouTube配信者保存
        save_setting_value("twitch_client_id", self.twitch_client_id_input.text().strip())  # Twitch Client ID保存
        save_setting_value("twitch_client_secret", self.twitch_client_secret_input.text().strip())  # Twitch Client Secret保存
        save_setting_value("twitch_channels", self.twitch_channels_input.toPlainText().strip())  # Twitch配信者保存
        self.accept()  # ダイアログを閉じる
    def _browse_output_dir(self) -> None:  # 出力フォルダ参照
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "出力フォルダを選択")  # ダイアログ表示
        if directory:  # 選択があった場合
            self.output_dir_input.setText(directory)  # 入力欄に反映
class MainWindow(QtWidgets.QMainWindow):  # メインウィンドウ定義
    def __init__(self) -> None:  # 初期化処理
        super().__init__()  # 親クラス初期化
        self.setWindowTitle("配信録画くん")  # ウィンドウタイトル設定
        self.setMinimumSize(900, 680)  # 最小サイズ設定
        self.worker_thread: QtCore.QThread | None = None  # ワーカースレッド参照
        self.worker: RecorderWorker | None = None  # ワーカー参照
        self.stop_event: threading.Event | None = None  # 停止フラグ参照
        self.manual_recording_url: str | None = None  # 手動録画URL参照
        self.auto_sessions: dict[str, dict] = {}  # 自動録画セッション管理
        self.auto_timer = QtCore.QTimer(self)  # 自動監視タイマー
        self.auto_timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)  # タイマー種別設定
        self.auto_timer.timeout.connect(self._on_auto_timer)  # タイマーイベント接続
        self.auto_check_thread: QtCore.QThread | None = None  # 自動監視スレッド参照
        self.auto_check_worker: AutoCheckWorker | None = None  # 自動監視ワーカー参照
        self.auto_check_in_progress = False  # 自動監視中フラグ
        self.preview_tabs = QtWidgets.QTabWidget()  # プレビュー用タブウィジェット
        self.preview_tabs.setTabsClosable(True)  # タブのクローズを有効化
        self.preview_tabs.tabCloseRequested.connect(self._on_preview_tab_close)  # タブ閉じイベント接続
        self.preview_sessions: dict[str, dict] = {}  # プレビューセッション管理
        self.preview_volume = 0.5  # プレビュー音量の既定値
        self.channel_name_cache: dict[str, str] = {}  # 配信者名のキャッシュ
        self._build_menu()  # メニューバー構築
        self._build_ui()  # UI構築
        self._load_settings_to_ui()  # 設定をUIへ反映
        self._configure_auto_monitor()  # 自動監視を設定
    def _build_menu(self) -> None:  # メニューバー構築処理
        menu_bar = self.menuBar()  # メニューバー取得
        file_menu = menu_bar.addMenu("ファイル")  # ファイルメニュー作成
        settings_menu = menu_bar.addMenu("設定")  # 設定メニュー作成
        help_menu = menu_bar.addMenu("ヘルプ")  # ヘルプメニュー作成
        import_action = QtGui.QAction("CSVのインポート", self)  # CSVインポートアクション作成
        import_action.triggered.connect(self._import_monitoring_csv)  # インポートイベント接続
        export_action = QtGui.QAction("CSVのエクスポート", self)  # CSVエクスポートアクション作成
        export_action.triggered.connect(self._export_monitoring_csv)  # エクスポートイベント接続
        quit_action = QtGui.QAction("終了", self)  # 終了アクション作成
        quit_action.setShortcut(QtGui.QKeySequence("Ctrl+Q"))  # ショートカット設定
        quit_action.triggered.connect(self.close)  # 終了イベント接続
        file_menu.addAction(import_action)  # ファイルメニューへ追加
        file_menu.addAction(export_action)  # ファイルメニューへ追加
        file_menu.addSeparator()  # 区切り線を追加
        file_menu.addAction(quit_action)  # ファイルメニューへ追加
        settings_action = QtGui.QAction("設定", self)  # 設定アクション作成
        settings_action.setShortcut(QtGui.QKeySequence("Ctrl+,"))  # ショートカット設定
        settings_action.triggered.connect(self._open_settings_dialog)  # 設定ダイアログ接続
        settings_menu.addAction(settings_action)  # 設定メニューへ追加
        about_action = QtGui.QAction("このアプリについて", self)  # 情報アクション作成
        about_action.triggered.connect(self._show_about)  # 情報ダイアログ接続
        help_menu.addAction(about_action)  # ヘルプメニューへ追加
    def _build_ui(self) -> None:  # UI構築処理
        central = QtWidgets.QWidget()  # 中央ウィジェットを生成
        self.setCentralWidget(central)  # 中央ウィジェットを設定
        layout = QtWidgets.QVBoxLayout(central)  # メインレイアウトを作成
        header = QtWidgets.QLabel("配信URLとファイル名を入力し、録画を開始してください。")  # 説明ラベル
        layout.addWidget(header)  # 説明ラベル追加
        grid = QtWidgets.QGridLayout()  # 入力フォームのグリッドレイアウト
        grid.setHorizontalSpacing(12)  # 水平方向の間隔を設定
        grid.setVerticalSpacing(8)  # 垂直方向の間隔を設定
        layout.addLayout(grid)  # グリッドを追加
        url_label = QtWidgets.QLabel("配信URL")  # 配信URLラベル
        url_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)  # ラベル右寄せ
        self.url_input = QtWidgets.QLineEdit()  # URL入力欄
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")  # プレースホルダ設定
        filename_label = QtWidgets.QLabel("ファイル名")  # ファイル名ラベル
        filename_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)  # ラベル右寄せ
        self.filename_input = QtWidgets.QLineEdit()  # ファイル名入力
        self.filename_input.setPlaceholderText("省略可")  # プレースホルダ設定
        grid.addWidget(url_label, 0, 0)  # URLラベル配置
        grid.addWidget(self.url_input, 0, 1)  # URL入力配置
        grid.addWidget(filename_label, 0, 2)  # ファイル名ラベル配置
        grid.addWidget(self.filename_input, 0, 3)  # ファイル名入力配置
        button_row = QtWidgets.QHBoxLayout()  # ボタン行レイアウト
        self.preview_button = QtWidgets.QPushButton("プレビュー開始")  # プレビューボタン
        self.settings_button = QtWidgets.QPushButton("設定")  # 設定ボタン
        self.start_button = QtWidgets.QPushButton("録画開始")  # 開始ボタン
        self.stop_button = QtWidgets.QPushButton("録画停止")  # 停止ボタン
        self.stop_button.setEnabled(False)  # 停止ボタンを無効化
        self.preview_button.clicked.connect(self._toggle_preview)  # プレビューイベント接続
        self.settings_button.clicked.connect(self._open_settings_dialog)  # 設定ダイアログ表示
        self.start_button.clicked.connect(self._start_recording)  # 開始イベント接続
        self.stop_button.clicked.connect(self._stop_recording)  # 停止イベント接続
        button_row.addWidget(self.preview_button)  # プレビューボタン追加
        button_row.addWidget(self.settings_button)  # 設定ボタン追加
        button_row.addStretch(1)  # 余白追加
        button_row.addWidget(self.start_button)  # 開始ボタン追加
        button_row.addWidget(self.stop_button)  # 停止ボタン追加
        layout.addLayout(button_row)  # ボタン行追加
        content_row = QtWidgets.QHBoxLayout()  # プレビューとログの横並びレイアウト
        preview_group = QtWidgets.QGroupBox("プレビュー")  # プレビュー枠を作成
        preview_layout = QtWidgets.QVBoxLayout(preview_group)  # プレビュー用レイアウト
        self.preview_tabs.setMinimumHeight(260)  # プレビューの最小高さ設定
        preview_layout.addWidget(self.preview_tabs)  # プレビュータブを追加
        preview_group.setStyleSheet("")  # プレビュー背景色をクリア
        log_group = QtWidgets.QGroupBox("ログ")  # ログ枠を作成
        log_layout = QtWidgets.QVBoxLayout(log_group)  # ログ用レイアウト
        self.log_output = QtWidgets.QTextEdit()  # ログ表示欄
        self.log_output.setReadOnly(True)  # 読み取り専用
        self.log_output.setFont(QtGui.QFont("Menlo", 10))  # 等幅フォント指定
        self.log_output.setStyleSheet("")  # ログ背景色をクリア
        log_group.setStyleSheet("")  # ログ枠背景色をクリア
        log_layout.addWidget(self.log_output)  # ログ欄追加
        content_row.addWidget(preview_group, 1)  # プレビュー枠を追加
        content_row.addWidget(log_group, 1)  # ログ枠を追加
        layout.addLayout(content_row)  # 横並び行を追加
    def _append_log(self, message: str) -> None:  # ログ追加処理
        timestamp = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")  # タイムスタンプ生成
        self.log_output.append(f"[{timestamp}] {message}")  # ログを追記
    def _show_info(self, message: str) -> None:  # 通知表示処理
        QtWidgets.QMessageBox.information(self, "情報", message)  # 情報ダイアログ表示
    def _show_about(self) -> None:  # 情報ダイアログ表示
        QtWidgets.QMessageBox.information(  # 情報ダイアログを表示
            self,  # 親ウィンドウ指定
            "このアプリについて",  # タイトル指定
            "配信録画くん\n配信の録画・自動監視をサポートします。",  # 表示メッセージ
        )  # ダイアログ表示終了
    def _collect_monitoring_entries(self) -> dict[str, list[str]]:  # 監視設定の収集
        mapping = {  # 監視設定の対応表
            "twitcasting": load_setting_value("twitcasting_entries", "", str),  # ツイキャス
            "niconico": load_setting_value("niconico_entries", "", str),  # ニコ生
            "tiktok": load_setting_value("tiktok_entries", "", str),  # TikTok
            "youtube": load_setting_value("youtube_channels", "", str),  # YouTube
            "twitch": load_setting_value("twitch_channels", "", str),  # Twitch
        }  # 対応表定義終了
        entries: dict[str, list[str]] = {}  # 監視入力を格納
        for key, raw_text in mapping.items():  # 設定を順に確認
            parsed = parse_auto_url_list(raw_text)  # 監視入力を解析
            entries[key] = parsed  # 解析結果を格納
        return entries  # 監視入力を返却
    def _apply_monitoring_entries(self, entries: dict[str, list[str]]) -> None:  # 監視設定の反映
        key_map = {  # 保存先キーの対応表
            "twitcasting": "twitcasting_entries",  # ツイキャス
            "niconico": "niconico_entries",  # ニコ生
            "tiktok": "tiktok_entries",  # TikTok
            "youtube": "youtube_channels",  # YouTube
            "twitch": "twitch_channels",  # Twitch
        }  # 対応表定義終了
        for service, setting_key in key_map.items():  # 監視入力を保存
            values = entries.get(service, [])  # サービス別の値を取得
            text = "\n".join(values)  # 1行ずつに整形
            save_setting_value(setting_key, text)  # 設定を保存
    def _export_monitoring_csv(self) -> None:  # CSVエクスポート処理
        path, _ = QtWidgets.QFileDialog.getSaveFileName(  # 保存先を選択
            self,  # 親ウィンドウ
            "CSVをエクスポート",  # ダイアログタイトル
            "monitoring.csv",  # 既定ファイル名
            "CSVファイル (*.csv)",  # フィルタ
        )  # ダイアログ終了
        if not path:  # キャンセルされた場合
            return  # 処理中断
        entries = self._collect_monitoring_entries()  # 監視入力を取得
        try:  # 例外処理開始
            with open(path, "w", encoding="utf-8", newline="") as csv_file:  # CSVを開く
                writer = csv.writer(csv_file)  # CSVライター作成
                writer.writerow(["service", "entry"])  # ヘッダーを書き込み
                for service, values in entries.items():  # サービスごとに出力
                    for value in values:  # 入力値ごとに出力
                        writer.writerow([service, value])  # 1行を書き込み
        except OSError as exc:  # ファイル書き込みエラー
            self._show_info(f"CSVのエクスポートに失敗しました: {exc}")  # 失敗通知
            return  # 処理中断
        self._show_info("CSVをエクスポートしました。")  # 成功通知
    def _import_monitoring_csv(self) -> None:  # CSVインポート処理
        path, _ = QtWidgets.QFileDialog.getOpenFileName(  # 読み込み元を選択
            self,  # 親ウィンドウ
            "CSVをインポート",  # ダイアログタイトル
            "",  # 初期パス
            "CSVファイル (*.csv)",  # フィルタ
        )  # ダイアログ終了
        if not path:  # キャンセルされた場合
            return  # 処理中断
        imported: dict[str, list[str]] = {  # インポート結果を初期化
            "twitcasting": [],  # ツイキャス
            "niconico": [],  # ニコ生
            "tiktok": [],  # TikTok
            "youtube": [],  # YouTube
            "twitch": [],  # Twitch
        }  # 初期化終了
        try:  # 例外処理開始
            with open(path, "r", encoding="utf-8", newline="") as csv_file:  # CSVを開く
                reader = csv.reader(csv_file)  # CSVリーダー作成
                rows = list(reader)  # 行を全て取得
        except OSError as exc:  # ファイル読み込みエラー
            self._show_info(f"CSVのインポートに失敗しました: {exc}")  # 失敗通知
            return  # 処理中断
        if not rows:  # 空ファイルの場合
            self._show_info("CSVが空です。")  # 空通知
            return  # 処理中断
        header = [cell.strip().lower() for cell in rows[0]]  # ヘッダーを取得
        has_header = "service" in header and "entry" in header  # ヘッダー判定
        if has_header:  # ヘッダー付きの場合
            service_index = header.index("service")  # service列位置
            entry_index = header.index("entry")  # entry列位置
            data_rows = rows[1:]  # データ行を抽出
        else:  # ヘッダー無しの場合
            service_index = 0  # service列位置
            entry_index = 1  # entry列位置
            data_rows = rows  # 全行をデータ行として扱う
        for row in data_rows:  # データ行を処理
            if len(row) <= max(service_index, entry_index):  # 列数不足の場合
                continue  # 次の行へ
            service = row[service_index].strip().lower()  # サービス名を取得
            entry = row[entry_index].strip()  # 入力値を取得
            if not service or not entry:  # 空欄の場合
                continue  # 次の行へ
            if service not in imported:  # 未対応サービスの場合
                continue  # 次の行へ
            imported[service].append(entry)  # 監視入力を追加
        self._apply_monitoring_entries(imported)  # 設定へ反映
        self._configure_auto_monitor()  # 自動監視を再設定
        self._show_info("CSVをインポートしました。")  # 成功通知
    def _load_settings_to_ui(self) -> None:  # 設定の読み込み
        self.preview_volume = load_setting_value("preview_volume", 0.5, float)  # プレビュー音量を保持
        for session in self.preview_sessions.values():  # 既存プレビューを更新
            audio = session.get("audio")  # 音声出力を取得
            if isinstance(audio, QtMultimedia.QAudioOutput):  # 音声出力がある場合
                audio.setVolume(float(self.preview_volume))  # 音量を反映
    def _open_settings_dialog(self) -> None:  # 設定ダイアログ表示
        dialog = SettingsDialog(self)  # 設定ダイアログ生成
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:  # OK時の処理
            self._load_settings_to_ui()  # 設定を再読み込み
            self._configure_auto_monitor()  # 自動監視を再設定
            self._show_info("設定を更新しました。")  # 通知表示
    def _resolve_stream_url(self, url: str) -> Optional[str]:  # ストリームURLを解決
        quality = DEFAULT_QUALITY  # 画質は常に最高品質に固定
        http_timeout = load_setting_value("http_timeout", 20, int)  # 設定からHTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # 設定からストリームタイムアウト取得
        session = Streamlink()  # Streamlinkセッション生成
        session.set_option("http-timeout", int(http_timeout))  # HTTPタイムアウト設定
        session.set_option("stream-timeout", int(stream_timeout))  # ストリームタイムアウト設定
        original_headers = dict(session.http.headers)  # 元のヘッダーを退避
        try:  # 例外処理開始
            original_headers = set_streamlink_headers_for_url(session, url)  # ヘッダー調整
            streams = session.streams(url)  # ストリーム一覧を取得
        except StreamlinkError as exc:  # Streamlink例外を捕捉
            self._append_log(f"プレビュー用ストリーム取得に失敗しました: {exc}")  # ログ出力
            return None  # 失敗時はNone
        finally:  # 後始末
            restore_streamlink_headers(session, original_headers)  # ヘッダーを復元
        if not streams:  # ストリームが空の場合
            self._append_log("プレビュー用ストリームが見つかりませんでした。")  # ログ出力
            return None  # 失敗時はNone
        stream = select_stream(streams, quality)  # 最高品質ストリームを選択
        if hasattr(stream, "to_url"):  # URL変換メソッドがある場合
            try:  # 例外処理開始
                return stream.to_url()  # URLを返却
            except TypeError as exc:  # URL化できない場合
                self._append_log(f"プレビュー用ストリームURLの取得に失敗しました: {exc}")  # 失敗ログ
        if hasattr(stream, "url"):  # URL属性がある場合
            return getattr(stream, "url")  # URLを返却
        self._append_log("プレビューに対応したストリームURLを取得できませんでした。")  # ログ出力
        return None  # 失敗時はNone
    def _should_use_ffmpeg_preview(self, url: str) -> bool:  # FFmpegプレビュー使用判定
        return is_twitcasting_url(url)  # ツイキャスの場合はFFmpeg経由
    def _allocate_preview_udp_port(self) -> int:  # UDPポート確保
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDPソケット生成
        sock.bind(("127.0.0.1", 0))  # 空きポートを割り当て
        port = sock.getsockname()[1]  # 割り当てポート取得
        sock.close()  # ソケットを閉じる
        return int(port)  # ポート番号を返却
    def _create_ffmpeg_preview_process(self, output_url: str) -> Optional[QtCore.QProcess]:  # FFmpegプレビュー生成
        ffmpeg_path = shutil.which("ffmpeg")  # ffmpegのパスを探索
        if not ffmpeg_path:  # ffmpegが見つからない場合
            self._append_log("プレビューにffmpegが必要です。PATHにffmpegを追加してください。")  # 失敗ログ
            return None  # 生成失敗
        args = [  # ffmpeg引数を定義
            "-loglevel",  # ログレベル指定
            "error",  # エラーのみ出力
            "-fflags",  # 解析フラグ指定
            "+genpts",  # PTS生成を有効化
            "-i",  # 入力指定
            "pipe:0",  # 標準入力から受け取る
            "-c:v",  # 映像コーデック指定
            "libx264",  # H.264へ再エンコード
            "-preset",  # 速度プリセット
            "veryfast",  # 高速設定
            "-tune",  # チューニング指定
            "zerolatency",  # 低遅延設定
            "-c:a",  # 音声コーデック指定
            "aac",  # AACへ再エンコード
            "-b:a",  # 音声ビットレート指定
            "192k",  # 192kbps指定
            "-f",  # 出力フォーマット指定
            "mpegts",  # MPEG-TS指定
            output_url,  # UDPへ出力
        ]  # 引数定義終了
        process = QtCore.QProcess(self)  # プロセスを生成
        process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.SeparateChannels)  # 標準出力とエラーを分離
        process.readyReadStandardError.connect(  # エラー出力の通知を接続
            lambda: self._log_ffmpeg_preview_error(process)  # FFmpegエラーをログへ出力
        )  # 接続終了
        process.setProgram(ffmpeg_path)  # 実行ファイルを設定
        process.setArguments(args)  # 引数を設定
        process.start()  # プロセス開始
        if not process.waitForStarted(2000):  # 起動失敗の場合
            self._append_log("プレビュー用ffmpegの起動に失敗しました。")  # 失敗ログ
            process.deleteLater()  # プロセスを破棄
            return None  # 生成失敗
        return process  # プロセスを返却
    def _resolve_channel_display_name(self, url: str) -> Optional[str]:  # 配信者の表示名取得
        parsed = urlparse(url)  # URLを解析
        host = parsed.netloc.lower()  # ホストを取得
        if "youtube" in host or "youtu.be" in host:  # YouTubeの場合
            api_key = load_setting_value("youtube_api_key", "", str).strip()  # APIキー取得
            if not api_key:  # APIキーが無い場合
                if parsed.scheme and parsed.netloc:  # URL形式の場合
                    return fetch_youtube_oembed_author_name(url, self._append_log)  # oEmbedで取得
                return None  # 取得を中止
            kind, value = normalize_youtube_entry(url)  # URLを正規化
            if kind == "video" and value:  # 動画URLの場合
                title = fetch_youtube_channel_title_by_video(api_key, value, self._append_log)  # チャンネル名を取得
                if title:  # チャンネル名が取得できた場合
                    return title  # チャンネル名を返却
            channel_id = resolve_youtube_channel_id(api_key, url, self._append_log)  # チャンネルIDを解決
            if channel_id:  # チャンネルIDがある場合
                title = fetch_youtube_channel_title_by_id(api_key, channel_id, self._append_log)  # チャンネル名を取得
                if title:  # チャンネル名が取得できた場合
                    return title  # チャンネル名を返却
            if parsed.scheme and parsed.netloc:  # URL形式の場合
                return fetch_youtube_oembed_author_name(url, self._append_log)  # oEmbedで取得
            return None  # 取得失敗
        if "twitch" in host or "twitch" in url:  # Twitchの場合
            login = normalize_twitch_login(url)  # ログイン名を取得
            if not login:  # ログイン名が無い場合
                return None  # 取得を中止
            client_id = load_setting_value("twitch_client_id", "", str).strip()  # Client ID取得
            client_secret = load_setting_value("twitch_client_secret", "", str).strip()  # Client Secret取得
            if not client_id or not client_secret:  # APIキーが不足の場合
                return None  # 取得を中止
            title = fetch_twitch_display_name(client_id, client_secret, login, self._append_log)  # 表示名取得
            return title if title else None  # 表示名を返却
        if "twitcasting.tv" in host or "twitcasting" in url:  # ツイキャスの場合
            title = fetch_twitcasting_display_name_by_scraping(url, self._append_log)  # 表示名取得
            return title if title else None  # 表示名を返却
        if "nicovideo.jp" in host or "nicovideo" in url:  # ニコ生の場合
            title = fetch_niconico_display_name_by_scraping(url, self._append_log)  # 表示名取得
            return title if title else None  # 表示名を返却
        if "tiktok" in host or "tiktok" in url:  # TikTokの場合
            title = fetch_tiktok_display_name(url, self._append_log)  # 表示名取得
            return title if title else None  # 表示名を返却
        return None  # 対象外の場合
    def _resolve_channel_folder_label(self, url: str) -> str:  # フォルダ用配信者名の取得
        cached = self.channel_name_cache.get(url)  # キャッシュを取得
        if cached:  # キャッシュがある場合
            return cached  # キャッシュを返却
        display_name = self._resolve_channel_display_name(url)  # 表示名を取得
        if display_name:  # 表示名がある場合
            label = safe_filename_component(display_name)  # 表示名を安全化
            self.channel_name_cache[url] = label  # キャッシュに保存
            return label  # 安全化した名前を返却
        parsed = urlparse(url)  # URLを解析
        host = parsed.netloc.lower()  # ホストを取得
        if "twitch" in host or "twitch" in url:  # Twitchの場合
            login = normalize_twitch_login(url)  # ログイン名を取得
            if login:  # ログイン名がある場合
                fallback = safe_filename_component(login)  # ログイン名を安全化
                self.channel_name_cache[url] = fallback  # キャッシュに保存
                return fallback  # ログイン名を返却
        if "youtube" in host or "youtu.be" in host:  # YouTubeの場合
            kind, value = normalize_youtube_entry(url)  # URLを正規化
            if value:  # 値がある場合
                fallback = safe_filename_component(value)  # 値を安全化
                self.channel_name_cache[url] = fallback  # キャッシュに保存
                return fallback  # 値を返却
        platform_label = derive_platform_label_for_folder(url)  # サービス固有ラベルを取得
        if platform_label:  # ラベルがある場合
            fallback = safe_filename_component(platform_label)  # ラベルを安全化
            self.channel_name_cache[url] = fallback  # キャッシュに保存
            return fallback  # ラベルを返却
        fallback = derive_channel_label(url)  # 代替ラベルを生成
        self.channel_name_cache[url] = fallback  # キャッシュに保存
        return fallback  # 代替ラベルを返却
    def _get_current_preview_url(self) -> Optional[str]:  # 現在のプレビューURL取得
        current_widget = self.preview_tabs.currentWidget()  # 現在のタブを取得
        if current_widget is None:  # タブが無い場合
            return None  # Noneを返却
        value = current_widget.property("preview_url")  # URLプロパティ取得
        return str(value) if value else None  # URLを返却
    def _on_preview_tab_close(self, index: int) -> None:  # タブのクローズ処理
        widget = self.preview_tabs.widget(index)  # 対象タブを取得
        if widget is None:  # タブが無い場合
            return  # 何もしない
        url = widget.property("preview_url")  # URLプロパティ取得
        if isinstance(url, str) and url:  # URLがある場合
            self._stop_preview_for_url(url, remove_tab=True)  # プレビュー停止
        else:  # URLが無い場合
            self.preview_tabs.removeTab(index)  # タブを削除
    def _configure_auto_monitor(self) -> None:  # 自動監視の設定
        enabled = load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED)  # 有効設定を取得
        interval = load_setting_value("auto_check_interval", DEFAULT_AUTO_CHECK_INTERVAL_SEC, int)  # 間隔設定を取得
        youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧を取得
        twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧を取得
        twitcasting_urls = self._get_auto_twitcasting_urls()  # ツイキャスURL一覧を取得
        niconico_urls = self._get_auto_niconico_urls()  # ニコ生URL一覧を取得
        tiktok_urls = self._get_auto_tiktok_urls()  # TikTok URL一覧を取得
        merged_urls = merge_unique_urls(twitcasting_urls, niconico_urls, tiktok_urls)  # 監視URLを結合
        has_targets = bool(youtube_channels or twitch_channels or merged_urls)  # 監視対象の有無
        if enabled and has_targets:  # 有効かつ監視対象がある場合
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
            else:  # 無効の場合
                self._append_log("自動監視を停止しました。")  # ログ出力
    def _trigger_auto_check_now(self) -> None:  # 自動監視の即時実行
        if self.auto_check_in_progress:  # 監視中の場合
            return  # 重複チェックを防止
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
    def _get_auto_youtube_channels(self) -> list[str]:  # YouTube配信者一覧の取得
        raw_text = load_setting_value("youtube_channels", "", str)  # 設定文字列を取得
        return parse_auto_url_list(raw_text)  # 解析済み一覧を返却
    def _get_auto_twitch_channels(self) -> list[str]:  # Twitch配信者一覧の取得
        raw_text = load_setting_value("twitch_channels", "", str)  # 設定文字列を取得
        return parse_auto_url_list(raw_text)  # 解析済み一覧を返却
    def _on_auto_timer(self) -> None:  # 自動監視タイマー処理
        if self.auto_check_in_progress:  # 監視中の場合
            return  # 重複チェックを防止
        if not load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED):  # 無効の場合
            return  # 何もしない
        twitcasting_urls = self._get_auto_twitcasting_urls()  # ツイキャスURL一覧を取得
        niconico_urls = self._get_auto_niconico_urls()  # ニコ生URL一覧を取得
        tiktok_urls = self._get_auto_tiktok_urls()  # TikTok URL一覧を取得
        youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧を取得
        twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧を取得
        merged_urls = merge_unique_urls(twitcasting_urls, niconico_urls, tiktok_urls)  # 監視URLを結合
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
        self.auto_check_worker.finished_signal.connect(self._on_auto_check_finished)  # 完了イベント接続
        self.auto_check_thread.start()  # 監視スレッド開始
    def _on_auto_check_finished(self, live_urls: list[str]) -> None:  # 自動監視完了処理
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
        }  # セッション保存の終了
        self._append_log(f"自動録画開始: {normalized_url} -> {output_path}")  # ログ出力
        self._start_preview_for_url(  # 自動録画時のプレビュー開始
            normalized_url,  # URL指定
            update_input=False,  # 入力欄を更新しない
            reason="自動録画",  # 理由指定
            select_tab=False,  # タブを強制選択しない
        )  # プレビュー開始の終了
        if not self.stop_button.isEnabled():  # 停止ボタンが無効の場合
            self.stop_button.setEnabled(True)  # 停止ボタンを有効化
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
        if not self.auto_sessions and self.stop_event is None:  # 録画が無い場合
            self.stop_button.setEnabled(False)  # 停止ボタンを無効化
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
    def _start_preview(self) -> None:  # プレビュー開始処理
        url = self.url_input.text().strip()  # URL取得
        if not url:  # URLが空の場合
            self._show_info("配信URLを入力してください。")  # 通知表示
            return  # 処理中断
        self._start_preview_for_url(url, update_input=False, reason="手動", select_tab=True)  # URL指定でプレビュー開始
    def _start_preview_for_url(self, url: str, update_input: bool, reason: str, select_tab: bool) -> None:  # URL指定プレビュー開始
        if update_input:  # 入力欄を更新する場合
            self.url_input.setText(url)  # URL入力欄を更新
        use_ffmpeg = self._should_use_ffmpeg_preview(url)  # FFmpeg利用判定
        process: QtCore.QProcess | None = None  # プロセス初期化
        pipe_stop_event: threading.Event | None = None  # パイプ停止フラグ
        pipe_thread: QtCore.QThread | None = None  # パイプ転送スレッド
        pipe_worker: StreamlinkPreviewWorker | None = None  # パイプ読み込みワーカー
        pipe_proxy: PreviewPipeProxy | None = None  # パイプ書き込み代理
        stream_url = None  # ストリームURL初期化
        preview_url = None  # プレビューURL初期化
        if use_ffmpeg:  # FFmpegを使う場合
            port = self._allocate_preview_udp_port()  # UDPポート確保
            preview_url = f"udp://127.0.0.1:{port}"  # プレビューURLを生成
            output_url = f"{preview_url}?pkt_size=1316"  # FFmpeg出力URLを生成
            process = self._create_ffmpeg_preview_process(output_url)  # プロセス生成
            if process is None:  # 生成に失敗した場合
                return  # 処理中断
            pipe_stop_event = threading.Event()  # 停止フラグを生成
            pipe_thread = QtCore.QThread()  # パイプ転送スレッド生成
            pipe_worker = StreamlinkPreviewWorker(url, pipe_stop_event)  # ワーカー生成
            pipe_worker.moveToThread(pipe_thread)  # ワーカーをスレッドへ移動
            pipe_proxy = PreviewPipeProxy(process)  # 書き込み代理を生成
            pipe_worker.data_signal.connect(pipe_proxy.write_data)  # データ転送を接続
            pipe_worker.log_signal.connect(self._append_log)  # ログ接続
            pipe_worker.finished_signal.connect(pipe_proxy.close)  # 標準入力クローズを接続
            pipe_worker.finished_signal.connect(pipe_thread.quit)  # スレッド終了を接続
            pipe_worker.finished_signal.connect(pipe_worker.deleteLater)  # ワーカー破棄を接続
            pipe_thread.finished.connect(pipe_thread.deleteLater)  # スレッド破棄を接続
            pipe_thread.started.connect(pipe_worker.run)  # 実行開始を接続
            pipe_thread.start()  # スレッド開始
        else:  # URLを使う場合
            stream_url = self._resolve_stream_url(url)  # ストリームURLを取得
            if not stream_url:  # URLが取得できない場合
                return  # 処理中断
        if url in self.preview_sessions:  # 既存プレビューがある場合
            session = self.preview_sessions[url]  # セッションを取得
            player = session["player"]  # プレイヤーを取得
            audio = session.get("audio")  # 音声出力を取得
            if isinstance(audio, QtMultimedia.QAudioOutput):  # 音声出力がある場合
                audio.setVolume(float(self.preview_volume))  # 音量を反映
            if player.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:  # 再生中判定
                player.stop()  # 既存プレビューを停止
            old_process = session.get("process")  # 既存プロセスを取得
            if isinstance(old_process, QtCore.QProcess):  # 既存プロセスがある場合
                old_process.terminate()  # 既存プロセスを停止
                old_process.waitForFinished(2000)  # 停止を待機
                if old_process.state() == QtCore.QProcess.ProcessState.Running:  # まだ動作中の場合
                    old_process.kill()  # 強制停止
                old_process.deleteLater()  # プロセスを破棄
            old_stop_event = session.get("pipe_stop_event")  # 既存停止フラグを取得
            if isinstance(old_stop_event, threading.Event):  # 停止フラグがある場合
                old_stop_event.set()  # 停止フラグを設定
            old_thread = session.get("pipe_thread")  # 既存スレッドを取得
            if isinstance(old_thread, QtCore.QThread):  # スレッドが存在する場合
                old_thread.quit()  # スレッド終了要求
                old_thread.wait(2000)  # 終了待機
                old_thread.deleteLater()  # スレッドを破棄
            old_proxy = session.get("pipe_proxy")  # 既存代理を取得
            if isinstance(old_proxy, PreviewPipeProxy):  # 代理がある場合
                old_proxy.close()  # 代理を閉じる
                old_proxy.deleteLater()  # 代理を破棄
            if use_ffmpeg and isinstance(process, QtCore.QProcess):  # FFmpeg利用時
                player.setSource(QtCore.QUrl(preview_url))  # UDPソースを設定
                session["process"] = process  # プロセス参照を更新
                session["pipe_stop_event"] = pipe_stop_event  # 停止フラグを更新
                session["pipe_thread"] = pipe_thread  # スレッド参照を更新
                session["pipe_worker"] = pipe_worker  # ワーカー参照を更新
                session["pipe_proxy"] = pipe_proxy  # 代理参照を更新
                session["preview_url"] = preview_url  # プレビューURLを更新
                player.play()  # 再生開始
            else:  # URL利用時
                player.setSource(QtCore.QUrl(stream_url))  # プレイヤーにソース設定
                session["process"] = None  # プロセス参照をクリア
                session["pipe_stop_event"] = None  # 停止フラグをクリア
                session["pipe_thread"] = None  # スレッド参照をクリア
                session["pipe_worker"] = None  # ワーカー参照をクリア
                session["pipe_proxy"] = None  # 代理参照をクリア
                session["preview_url"] = None  # プレビューURLをクリア
                player.play()  # 再生開始
            if select_tab:  # タブを選択する場合
                self.preview_tabs.setCurrentWidget(session["widget"])  # 対象タブを選択
            self.preview_button.setText("プレビュー停止")  # ボタン表示更新
            self._append_log(f"プレビューを更新しました（{reason}）。")  # ログ出力
            return  # 処理終了
        audio = QtMultimedia.QAudioOutput(self)  # 音声出力を生成
        audio.setVolume(float(self.preview_volume))  # 音量を反映
        player = QtMultimedia.QMediaPlayer(self)  # プレイヤーを生成
        player.setAudioOutput(audio)  # 音声出力を関連付け
        video = QtMultimediaWidgets.QVideoWidget()  # 映像表示を生成
        player.setVideoOutput(video)  # 映像出力を関連付け
        container = QtWidgets.QWidget()  # タブ用コンテナ
        container_layout = QtWidgets.QVBoxLayout(container)  # コンテナレイアウト
        container_layout.addWidget(video)  # 映像を配置
        label = derive_channel_label(url)  # ラベルを生成
        tab_index = self.preview_tabs.addTab(container, label)  # タブを追加
        container.setProperty("preview_url", url)  # URLプロパティを保存
        self.preview_sessions[url] = {  # セッションを保存
            "player": player,  # プレイヤー参照
            "audio": audio,  # 音声出力参照
            "video": video,  # 映像参照
            "widget": container,  # コンテナ参照
            "tab_index": tab_index,  # タブインデックス
            "process": process,  # プロセス参照
            "pipe_stop_event": pipe_stop_event,  # 停止フラグ参照
            "pipe_thread": pipe_thread,  # スレッド参照
            "pipe_worker": pipe_worker,  # ワーカー参照
            "pipe_proxy": pipe_proxy,  # 代理参照
            "preview_url": preview_url,  # プレビューURL
        }  # セッション保存の終了
        if use_ffmpeg and isinstance(process, QtCore.QProcess):  # FFmpeg利用時
            player.setSource(QtCore.QUrl(preview_url))  # UDPソースを設定
        else:  # URL利用時
            player.setSource(QtCore.QUrl(stream_url))  # プレイヤーにソース設定
        player.play()  # 再生開始
        if select_tab or self.preview_tabs.count() == 1:  # タブ選択条件
            self.preview_tabs.setCurrentWidget(container)  # タブを選択
        self.preview_button.setText("プレビュー停止")  # ボタン表示更新
        self._append_log(f"プレビューを開始しました（{reason}）。")  # ログ出力
    def _stop_preview(self) -> None:  # プレビュー停止処理
        current_url = self._get_current_preview_url()  # 現在のURLを取得
        if not current_url:  # URLが無い場合
            self._append_log("停止するプレビューがありません。")  # ログ出力
            return  # 処理中断
        self._stop_preview_for_url(current_url, remove_tab=True)  # 対象プレビューを停止
    def _toggle_preview(self) -> None:  # プレビュー切替処理
        if self.preview_button.text() == "プレビュー停止":  # 再生中判定
            self._stop_preview()  # 停止処理
        else:  # 停止中の場合
            self._start_preview()  # 開始処理
    def _stop_preview_for_url(self, url: str, remove_tab: bool) -> None:  # URL指定プレビュー停止
        session = self.preview_sessions.pop(url, None)  # セッションを取得して削除
        if session is None:  # セッションが無い場合
            return  # 処理中断
        player = session["player"]  # プレイヤーを取得
        process = session.get("process")  # プロセスを取得
        if isinstance(process, QtCore.QProcess):  # プロセスが存在する場合
            process.terminate()  # プロセスを停止
            process.waitForFinished(2000)  # 停止を待機
            if process.state() == QtCore.QProcess.ProcessState.Running:  # まだ動作中の場合
                process.kill()  # 強制停止
            process.deleteLater()  # プロセスを破棄
        stop_event = session.get("pipe_stop_event")  # 停止フラグを取得
        if isinstance(stop_event, threading.Event):  # 停止フラグが存在する場合
            stop_event.set()  # 停止フラグを設定
        pipe_thread = session.get("pipe_thread")  # パイプスレッドを取得
        if isinstance(pipe_thread, QtCore.QThread):  # スレッドが存在する場合
            pipe_thread.quit()  # スレッド終了要求
            pipe_thread.wait(2000)  # 終了待機
            pipe_thread.deleteLater()  # スレッドを破棄
        pipe_proxy = session.get("pipe_proxy")  # パイプ代理を取得
        if isinstance(pipe_proxy, PreviewPipeProxy):  # 代理が存在する場合
            pipe_proxy.close()  # 代理を閉じる
            pipe_proxy.deleteLater()  # 代理を破棄
        player.stop()  # 再生停止
        player.setSource(QtCore.QUrl())  # ソースをクリア
        widget = session["widget"]  # コンテナを取得
        if remove_tab:  # タブ削除を行う場合
            index = self.preview_tabs.indexOf(widget)  # タブインデックス取得
            if index != -1:  # タブが存在する場合
                self.preview_tabs.removeTab(index)  # タブを削除
            widget.deleteLater()  # ウィジェットを破棄
        self._append_log(f"プレビューを停止しました: {url}")  # ログ出力
        if self.preview_tabs.count() == 0:  # タブが無い場合
            self.preview_button.setText("プレビュー開始")  # ボタン表示更新
    def _log_ffmpeg_preview_error(self, process: QtCore.QProcess) -> None:  # FFmpegエラー出力の処理
        if not isinstance(process, QtCore.QProcess):  # プロセスが無い場合
            return  # 何もしない
        raw = process.readAllStandardError()  # 標準エラーを取得
        text = bytes(raw).decode("utf-8", errors="replace").strip()  # 文字列に変換
        if not text:  # 空の場合
            return  # 何もしない
        self._append_log(f"プレビュー(FFmpeg): {text}")  # ログに追記
    def _stop_all_previews(self) -> None:  # 全プレビュー停止処理
        for url in list(self.preview_sessions.keys()):  # URL一覧を取得
            self._stop_preview_for_url(url, remove_tab=True)  # URLごとに停止
    def _start_recording(self) -> None:  # 録画開始処理
        url = self.url_input.text().strip()  # URL取得
        if not url:  # URLが空の場合
            self._show_info("配信URLを入力してください。")  # 通知表示
            return  # 処理中断
        self.manual_recording_url = url  # 手動録画URLを記録
        output_dir = Path(load_setting_value("output_dir", "recordings", str))  # 出力ディレクトリ取得
        filename = self.filename_input.text().strip()  # ファイル名取得
        if filename:  # ファイル名が指定された場合
            resolved_filename = filename  # 入力ファイル名を使用
        else:  # 入力が空の場合
            resolved_filename = None  # 自動命名に任せる
        channel_label = self._resolve_channel_folder_label(url)  # 配信者名を取得
        output_path = resolve_output_path(  # 出力パス生成
            output_dir,  # 出力ディレクトリ
            resolved_filename,  # ファイル名
            url,  # 配信URL
            channel_label=channel_label,  # 配信者ラベル
        )  # 出力パス生成終了
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
    def _stop_current_recordings(self) -> None:  # 現在の録画を停止
        if self.stop_event is not None:  # 手動録画がある場合
            self.stop_event.set()  # 停止フラグを設定
        for session in self.auto_sessions.values():  # 自動録画セッションを確認
            stop_event = session.get("stop_event")  # 停止フラグ取得
            if isinstance(stop_event, threading.Event):  # 停止フラグがある場合
                stop_event.set()  # 停止フラグを設定
    def _stop_recording(self) -> None:  # 録画停止処理
        if self.stop_event is None and not self.auto_sessions:  # 録画が無い場合
            self._append_log("停止対象の録画がありません。")  # ログ出力
            return  # 処理中断
        self._stop_current_recordings()  # 現在の録画を停止
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
        self.manual_recording_url = None  # 手動録画URLをクリア
        if self.worker_thread is not None:  # スレッドが存在する場合
            self.worker_thread.quit()  # スレッド終了要求
            self.worker_thread.wait(3000)  # スレッド終了待機
        self.worker = None  # ワーカー参照を破棄
        self.worker_thread = None  # スレッド参照を破棄
        self.stop_event = None  # 停止フラグ参照を破棄
        self.start_button.setEnabled(True)  # 開始ボタン有効化
        self.stop_button.setEnabled(False)  # 停止ボタン無効化
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # 終了時処理
        if self._has_active_recording_tasks():  # 録画/変換が動作中の場合
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
