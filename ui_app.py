# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import threading  # 停止フラグ制御
import shutil  # 実行ファイル探索
import socket  # UDPポート確保
import sys  # 実行環境の判定
import time  # リトライ間隔の計測
from pathlib import Path  # パス操作
from typing import Optional  # 型ヒント補助
import csv  # CSV入出力
from PyQt6 import QtCore, QtGui, QtMultimedia, QtMultimediaWidgets, QtWidgets  # PyQt6の主要モジュール
from urllib.parse import urlparse  # URL解析
from streamlink import Streamlink  # Streamlink本体
from streamlink.exceptions import StreamlinkError  # Streamlink例外
from api_niconico import fetch_niconico_display_name_by_scraping  # ニコ生表示名取得
from api_tiktok import fetch_tiktok_display_name  # TikTok表示名取得
from api_twitch import (  # Twitch API処理
    fetch_twitch_display_name,  # Twitch表示名取得
    fetch_twitch_live_urls,  # Twitchライブ取得
)
from api_twitcasting import fetch_twitcasting_display_name_by_scraping  # ツイキャス表示名取得
from api_youtube import (  # YouTube API処理
    build_youtube_live_page_url,  # YouTubeライブページURL構築
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
    apply_streamlink_options_for_url,  # URL別オプション調整
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
        apply_streamlink_options_for_url(session, self._url)  # URL別のStreamlinkオプションを反映
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
class ToggleSwitch(QtWidgets.QWidget):  # つまみ付きトグルスイッチ
    toggled = QtCore.pyqtSignal(bool)  # トグル状態変更シグナル
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:  # 初期化処理
        super().__init__(parent)  # 親クラス初期化
        self._checked = False  # チェック状態を初期化
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)  # カーソルを指形状にする
        self.setSizePolicy(  # サイズポリシーを設定
            QtWidgets.QSizePolicy.Policy.Fixed,  # 横幅は固定
            QtWidgets.QSizePolicy.Policy.Fixed,  # 高さも固定
        )  # サイズポリシー設定終了
    def isChecked(self) -> bool:  # チェック状態の取得
        return bool(self._checked)  # チェック状態を返却
    def setChecked(self, checked: bool) -> None:  # チェック状態の設定
        if bool(self._checked) == bool(checked):  # 変更が無い場合
            return  # 何もしない
        self._checked = bool(checked)  # 状態を更新
        self.toggled.emit(bool(self._checked))  # シグナルを通知
        self.update()  # 再描画を依頼
    def toggle(self) -> None:  # 状態を反転
        self.setChecked(not self.isChecked())  # 反転状態を設定
    def sizeHint(self) -> QtCore.QSize:  # 推奨サイズ
        return QtCore.QSize(46, 26)  # トグルの標準サイズを返却
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # マウス押下処理
        if event.button() == QtCore.Qt.MouseButton.LeftButton:  # 左クリックの場合
            self.toggle()  # 状態を反転
            event.accept()  # イベントを消費
            return  # 処理終了
        super().mousePressEvent(event)  # 親クラスへ渡す
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # 描画処理
        painter = QtGui.QPainter(self)  # ペインターを生成
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)  # アンチエイリアス有効化
        rect = self.rect()  # 描画領域を取得
        track_rect = rect.adjusted(1, 1, -1, -1)  # 余白を引いたトラック領域
        radius = track_rect.height() / 2  # トラックの角丸半径
        if self.isEnabled():  # 有効状態の場合
            if self.isChecked():  # オンの場合
                track_color = QtGui.QColor("#3b82f6")  # オン時のトラック色
                border_color = QtGui.QColor("#2f6cd6")  # オン時の枠線色
            else:  # オフの場合
                track_color = QtGui.QColor("#cbd5e1")  # オフ時のトラック色
                border_color = QtGui.QColor("#b6c0cc")  # オフ時の枠線色
        else:  # 無効状態の場合
            track_color = QtGui.QColor("#e2e8f0")  # 無効時のトラック色
            border_color = QtGui.QColor("#d1d5db")  # 無効時の枠線色
        painter.setPen(QtGui.QPen(border_color, 1))  # 枠線ペンを設定
        painter.setBrush(QtGui.QBrush(track_color))  # 塗り色を設定
        painter.drawRoundedRect(track_rect, radius, radius)  # トラックを描画
        knob_size = track_rect.height() - 4  # つまみのサイズを計算
        knob_y = track_rect.top() + 2  # つまみのY位置
        if self.isChecked():  # オンの場合
            knob_x = track_rect.right() - knob_size - 2  # 右側に配置
        else:  # オフの場合
            knob_x = track_rect.left() + 2  # 左側に配置
        knob_rect = QtCore.QRectF(  # つまみの矩形を生成
            float(knob_x),  # X座標
            float(knob_y),  # Y座標
            float(knob_size),  # 幅
            float(knob_size),  # 高さ
        )  # 矩形生成終了
        painter.setPen(QtCore.Qt.PenStyle.NoPen)  # つまみの枠線を消す
        painter.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))  # つまみ色を白に設定
        painter.drawEllipse(knob_rect)  # つまみを描画
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
        self._apply_placeholder_palette(self.output_dir_input)  # プレースホルダ色を調整
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
        self.tray_enabled_input = ToggleSwitch()  # タスクトレイ常駐のトグルスイッチ
        basic_form.addRow("タスクトレイ常駐", self.tray_enabled_input)  # 行追加
        self.auto_start_input = ToggleSwitch()  # 自動起動のトグルスイッチ
        basic_form.addRow("PC起動時に開く", self.auto_start_input)  # 行追加
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
        self.auto_enabled_input = ToggleSwitch()  # 自動録画有効トグル
        self.auto_enabled_input.toggled.connect(self._update_auto_record_option_state)  # 自動録画設定の有効/無効を連動
        auto_form.addRow("自動録画", self.auto_enabled_input)  # 行追加
        self.auto_startup_input = ToggleSwitch()  # 起動時自動録画トグル
        auto_form.addRow("起動時の自動録画", self.auto_startup_input)  # 行追加
        self.auto_check_interval_input = QtWidgets.QSpinBox()  # 自動監視間隔入力
        self.auto_check_interval_input.setRange(20, 3600)  # 範囲設定
        auto_form.addRow("監視間隔(秒)", self.auto_check_interval_input)  # 行追加
        auto_group.setLayout(auto_form)  # グループにフォーム設定
        content_layout.addWidget(auto_group)  # 自動録画グループ追加
        log_group = QtWidgets.QGroupBox("ログ表示")  # ログ表示グループ
        log_form = QtWidgets.QFormLayout()  # ログ表示フォーム
        log_form.setLabelAlignment(  # ラベル右寄せ設定
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter  # 右寄せ・縦中央
        )  # ラベル右寄せ設定終了
        log_form.setFormAlignment(  # フォーム全体の配置設定
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop  # 左寄せ・上寄せ
        )  # フォーム配置設定終了
        log_form.setHorizontalSpacing(12)  # 水平方向の間隔設定
        log_form.setVerticalSpacing(10)  # 垂直方向の間隔設定
        self.log_show_monitor_input = ToggleSwitch()  # 監視ログ表示トグル
        log_form.addRow("監視ログ表示", self.log_show_monitor_input)  # 行追加
        self.log_show_recording_input = ToggleSwitch()  # 録画ログ表示トグル
        log_form.addRow("録画ログ表示", self.log_show_recording_input)  # 行追加
        self.log_show_preview_input = ToggleSwitch()  # プレビューログ表示トグル
        log_form.addRow("プレビューログ表示", self.log_show_preview_input)  # 行追加
        self.log_show_youtube_input = ToggleSwitch()  # YouTubeログ表示トグル
        log_form.addRow("YouTubeログ表示", self.log_show_youtube_input)  # 行追加
        self.log_show_info_input = ToggleSwitch()  # その他ログ表示トグル
        log_form.addRow("その他ログ表示", self.log_show_info_input)  # 行追加
        log_group.setLayout(log_form)  # グループにフォーム設定
        content_layout.addWidget(log_group)  # ログ表示グループ追加
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
        self._apply_placeholder_palette(self.twitcasting_input)  # プレースホルダ色を調整
        self.twitcasting_input.setMinimumHeight(90)  # 表示高さ調整
        service_form.addRow("ツイキャス監視", self.twitcasting_input)  # 行追加
        self.niconico_input = QtWidgets.QPlainTextEdit()  # ニコ生監視入力
        self.niconico_input.setPlaceholderText("lvxxxxxxxx またはURLを1行ずつ")  # プレースホルダ設定
        self._apply_placeholder_palette(self.niconico_input)  # プレースホルダ色を調整
        self.niconico_input.setMinimumHeight(90)  # 表示高さ調整
        service_form.addRow("ニコ生監視", self.niconico_input)  # 行追加
        self.tiktok_input = QtWidgets.QPlainTextEdit()  # TikTok監視入力
        self.tiktok_input.setPlaceholderText("@handle またはURLを1行ずつ")  # プレースホルダ設定
        self._apply_placeholder_palette(self.tiktok_input)  # プレースホルダ色を調整
        self.tiktok_input.setMinimumHeight(90)  # 表示高さ調整
        service_form.addRow("TikTok監視", self.tiktok_input)  # 行追加
        self.youtube_channels_input = QtWidgets.QPlainTextEdit()  # YouTube監視入力
        self.youtube_channels_input.setPlaceholderText(  # プレースホルダ設定
            "チャンネルURLをそのまま貼り付け可（例: https://www.youtube.com/@xxxx/live）\n"  # 例示文1
            "@handle / チャンネルID(UC...) も可"  # 例示文2
        )  # プレースホルダ設定終了
        self._apply_placeholder_palette(self.youtube_channels_input)  # プレースホルダ色を調整
        self.youtube_channels_input.setMinimumHeight(90)  # 表示高さ調整
        service_form.addRow("YouTube監視", self.youtube_channels_input)  # 行追加
        self.twitch_channels_input = QtWidgets.QPlainTextEdit()  # Twitch監視入力
        self.twitch_channels_input.setPlaceholderText(  # プレースホルダ設定
            "ログイン名 / URL（https://www.twitch.tv/xxxx）を1行ずつ"  # 例示文
        )  # プレースホルダ設定終了
        self._apply_placeholder_palette(self.twitch_channels_input)  # プレースホルダ色を調整
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
        self._apply_placeholder_palette(self.youtube_api_key_input)  # プレースホルダ色を調整
        api_form.addRow("YouTube APIキー", self.youtube_api_key_input)  # 行追加
        self.twitch_client_id_input = QtWidgets.QLineEdit()  # Twitch Client ID入力
        self.twitch_client_id_input.setPlaceholderText("Twitch Client ID")  # プレースホルダ設定
        self._apply_placeholder_palette(self.twitch_client_id_input)  # プレースホルダ色を調整
        api_form.addRow("Twitch Client ID", self.twitch_client_id_input)  # 行追加
        self.twitch_client_secret_input = QtWidgets.QLineEdit()  # Twitch Client Secret入力
        self.twitch_client_secret_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)  # マスク表示設定
        self.twitch_client_secret_input.setPlaceholderText("Twitch Client Secret")  # プレースホルダ設定
        self._apply_placeholder_palette(self.twitch_client_secret_input)  # プレースホルダ色を調整
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
        self.tray_enabled_input.setChecked(  # タスクトレイ常駐設定
            load_bool_setting("tray_enabled", False)  # 設定値取得
        )  # 設定反映終了
        self.auto_start_input.setChecked(  # 自動起動設定
            load_bool_setting("auto_start_enabled", False)  # 設定値取得
        )  # 設定反映終了
        self.auto_enabled_input.setChecked(  # 自動録画有効設定
            load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED)  # 設定値取得
        )  # 設定反映終了
        self.auto_startup_input.setChecked(  # 起動時自動録画設定
            load_bool_setting("auto_startup_recording", True)  # 設定値取得
        )  # 設定反映終了
        self.auto_check_interval_input.setValue(  # 自動監視間隔設定
            load_setting_value("auto_check_interval", DEFAULT_AUTO_CHECK_INTERVAL_SEC, int)  # 設定値取得
        )  # 設定反映終了
        self._update_auto_record_option_state(bool(self.auto_enabled_input.isChecked()))  # 自動録画設定を反映
        self.log_show_monitor_input.setChecked(  # 監視ログ表示設定
            load_bool_setting("log_show_monitor", True)  # 設定値取得
        )  # 設定反映終了
        self.log_show_recording_input.setChecked(  # 録画ログ表示設定
            load_bool_setting("log_show_recording", True)  # 設定値取得
        )  # 設定反映終了
        self.log_show_preview_input.setChecked(  # プレビューログ表示設定
            load_bool_setting("log_show_preview", True)  # 設定値取得
        )  # 設定反映終了
        self.log_show_youtube_input.setChecked(  # YouTubeログ表示設定
            load_bool_setting("log_show_youtube", True)  # 設定値取得
        )  # 設定反映終了
        self.log_show_info_input.setChecked(  # その他ログ表示設定
            load_bool_setting("log_show_info", True)  # 設定値取得
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
        save_setting_value("tray_enabled", int(self.tray_enabled_input.isChecked()))  # タスクトレイ常駐保存
        save_setting_value("auto_start_enabled", int(self.auto_start_input.isChecked()))  # 自動起動保存
        save_setting_value("auto_enabled", int(self.auto_enabled_input.isChecked()))  # 自動録画有効保存
        save_setting_value("auto_startup_recording", int(self.auto_startup_input.isChecked()))  # 起動時自動録画保存
        save_setting_value("auto_check_interval", int(self.auto_check_interval_input.value()))  # 自動監視間隔保存
        save_setting_value("log_show_monitor", int(self.log_show_monitor_input.isChecked()))  # 監視ログ表示保存
        save_setting_value("log_show_recording", int(self.log_show_recording_input.isChecked()))  # 録画ログ表示保存
        save_setting_value("log_show_preview", int(self.log_show_preview_input.isChecked()))  # プレビューログ表示保存
        save_setting_value("log_show_youtube", int(self.log_show_youtube_input.isChecked()))  # YouTubeログ表示保存
        save_setting_value("log_show_info", int(self.log_show_info_input.isChecked()))  # その他ログ表示保存
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
    def _apply_placeholder_palette(self, widget: QtWidgets.QWidget) -> None:  # プレースホルダ色を調整
        palette = widget.palette()  # 既存のパレットを取得
        palette.setColor(  # プレースホルダの色を設定
            QtGui.QPalette.ColorRole.PlaceholderText,  # プレースホルダ色の指定
            QtGui.QColor("#64748b"),  # 視認性の高いグレーを指定
        )  # 設定終了
        widget.setPalette(palette)  # パレットを反映
    def _update_auto_record_option_state(self, enabled: bool) -> None:  # 自動録画設定の有効状態を更新
        self.auto_startup_input.setEnabled(enabled)  # 起動時自動録画の有効状態を反映
class MainWindow(QtWidgets.QMainWindow):  # メインウィンドウ定義
    def __init__(self) -> None:  # 初期化処理
        super().__init__()  # 親クラス初期化
        self.setWindowIcon(QtGui.QIcon(str(Path(__file__).resolve().with_name("icon.ico"))))  # ウィンドウアイコン設定
        self.setWindowTitle("配信録画くん")  # ウィンドウタイトル設定
        self.setMinimumSize(900, 680)  # 最小サイズ設定
        self._allow_quit = False  # 終了許可フラグ
        self.tray_icon: QtWidgets.QSystemTrayIcon | None = None  # タスクトレイアイコン参照
        self.tray_menu: QtWidgets.QMenu | None = None  # タスクトレイメニュー参照
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
        self.auto_paused_by_user = False  # 自動録画の手動停止フラグ
        self.auto_monitor_forced = False  # 手動開始で自動監視を有効化したかどうか
        self.preview_tabs = QtWidgets.QTabWidget()  # プレビュー用タブウィジェット
        self.preview_tabs.setTabsClosable(True)  # タブのクローズを有効化
        self.preview_tabs.tabCloseRequested.connect(self._on_preview_tab_close)  # タブ閉じイベント接続
        self.preview_sessions: dict[str, dict] = {}  # プレビューセッション管理
        self.preview_volume = 0.5  # プレビュー音量の既定値
        self.channel_name_cache: dict[str, str] = {}  # 配信者名のキャッシュ
        self._build_menu()  # メニューバー構築
        self._build_ui()  # UI構築
        self._setup_tray_icon()  # タスクトレイを初期化
        self._apply_ui_theme()  # UIテーマを適用
        self._load_settings_to_ui()  # 設定をUIへ反映
        self._configure_auto_monitor()  # 自動監視を設定
        self._apply_tray_setting(False)  # タスクトレイ設定を反映
        self._apply_startup_setting(False)  # 自動起動設定を反映
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
        quit_action.triggered.connect(self._exit_app)  # 終了イベント接続
        file_menu.addAction(import_action)  # ファイルメニューへ追加
        file_menu.addAction(export_action)  # ファイルメニューへ追加
        file_menu.addSeparator()  # 区切り線を追加
        file_menu.addAction(quit_action)  # ファイルメニューへ追加
        settings_action = QtGui.QAction("設定", self)  # 設定アクション作成
        settings_action.triggered.connect(self._open_settings_dialog)  # 設定ダイアログ接続
        settings_menu.addAction(settings_action)  # 設定メニューへ追加
        api_help_action = QtGui.QAction("API / Client IDの設定方法", self)  # APIキー案内アクション作成
        api_help_action.triggered.connect(self._show_api_help)  # APIキー案内ダイアログ接続
        help_menu.addAction(api_help_action)  # ヘルプメニューへ追加
        about_action = QtGui.QAction("このソフトについて", self)  # 情報アクション作成
        about_action.triggered.connect(self._show_about)  # 情報ダイアログ接続
        help_menu.addAction(about_action)  # ヘルプメニューへ追加
        self._apply_menu_shadow_style(file_menu)  # ファイルメニューの影と余白を調整
        self._apply_menu_shadow_style(settings_menu)  # 設定メニューの影と余白を調整
        self._apply_menu_shadow_style(help_menu)  # ヘルプメニューの影と余白を調整
    def _apply_menu_shadow_style(self, menu: QtWidgets.QMenu) -> None:  # メニュー影を薄くする
        has_shortcut = False  # ショートカットの有無を初期化
        for action in menu.actions():  # メニュー内アクションを確認
            shortcut = action.shortcut().toString()  # ショートカット文字列を取得
            if shortcut:  # ショートカットがある場合
                has_shortcut = True  # ショートカットありとして記録
                break  # ループを終了
        if has_shortcut:  # ショートカットがある場合
            item_left_padding = 28  # ショートカット列を考慮した左余白
        else:  # ショートカットが無い場合
            item_left_padding = 18  # 左寄せに近づけるため左余白を控えめにする
        menu.setWindowFlag(  # ドロップシャドウを無効化
            QtCore.Qt.WindowType.NoDropShadowWindowHint,  # OSの影を無効化するフラグ
            True,  # フラグを有効化
        )  # ウィンドウフラグの設定終了
        menu.setStyleSheet(  # メニューの境界線を薄く設定
            "QMenu { "  # メニュー全体の指定開始
            "border: 1px solid rgba(0, 0, 0, 40); "  # 薄い境界線で影を軽く見せる
            "}"  # メニュー全体の指定終了
            "QMenu::item { "  # メニュー項目の指定開始
            f"padding: 6px 18px 6px {item_left_padding}px; "  # 左余白を調整して文字位置を揃える
            "}"  # メニュー項目の指定終了
        )  # スタイル適用終了
    def _setup_tray_icon(self) -> None:  # タスクトレイを初期化
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():  # タスクトレイ非対応の場合
            self.tray_icon = None  # トレイアイコンを無効化
            self.tray_menu = None  # トレイメニューを無効化
            return  # 処理中断
        icon = self.windowIcon()  # ウィンドウアイコンを取得
        if icon.isNull():  # アイコンが空の場合
            icon = self.style().standardIcon(  # 標準アイコンを取得
                QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon  # 代替アイコンを指定
            )  # 標準アイコン取得の終了
        self.tray_icon = QtWidgets.QSystemTrayIcon(icon, self)  # タスクトレイアイコン生成
        self.tray_menu = QtWidgets.QMenu(self)  # タスクトレイメニュー生成
        show_action = QtGui.QAction("表示", self)  # 表示アクション作成
        show_action.triggered.connect(self._show_from_tray)  # 表示イベント接続
        exit_action = QtGui.QAction("終了", self)  # 終了アクション作成
        exit_action.triggered.connect(self._exit_app)  # 終了イベント接続
        self.tray_menu.addAction(show_action)  # 表示アクションを追加
        self.tray_menu.addSeparator()  # 区切り線を追加
        self.tray_menu.addAction(exit_action)  # 終了アクションを追加
        self.tray_icon.setContextMenu(self.tray_menu)  # トレイメニューを設定
        self.tray_icon.activated.connect(self._on_tray_activated)  # トレイクリックを接続
        self.tray_icon.setToolTip("配信録画くん")  # ツールチップを設定
    def _apply_tray_setting(self, notify: bool) -> None:  # タスクトレイ設定を反映
        enabled = load_bool_setting("tray_enabled", False)  # タスクトレイ設定を取得
        if not enabled:  # 無効の場合
            if isinstance(self.tray_icon, QtWidgets.QSystemTrayIcon):  # トレイアイコンがある場合
                self.tray_icon.hide()  # トレイアイコンを非表示
            return  # 処理中断
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():  # タスクトレイ非対応の場合
            if notify:  # 通知が必要な場合
                self._show_info("この環境ではタスクトレイを利用できません。")  # 通知を表示
            return  # 処理中断
        if self.tray_icon is None:  # トレイアイコン未生成の場合
            self._setup_tray_icon()  # トレイアイコンを生成
        if isinstance(self.tray_icon, QtWidgets.QSystemTrayIcon):  # トレイアイコンがある場合
            self.tray_icon.show()  # トレイアイコンを表示
    def _show_from_tray(self) -> None:  # トレイからウィンドウを表示
        self.showNormal()  # 通常表示に戻す
        self.activateWindow()  # ウィンドウをアクティブ化
        self.raise_()  # 最前面に移動
    def _on_tray_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:  # トレイクリック処理
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:  # 通常クリックの場合
            self._show_from_tray()  # ウィンドウを表示
        elif reason == QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick:  # ダブルクリックの場合
            self._show_from_tray()  # ウィンドウを表示
    def _exit_app(self) -> None:  # アプリ終了処理
        self._allow_quit = True  # 終了許可フラグを設定
        if isinstance(self.tray_icon, QtWidgets.QSystemTrayIcon):  # トレイアイコンがある場合
            self.tray_icon.hide()  # トレイアイコンを非表示
        self.close()  # ウィンドウを閉じる
    def _apply_startup_setting(self, notify: bool) -> None:  # 自動起動設定を反映
        enabled = load_bool_setting("auto_start_enabled", False)  # 自動起動設定を取得
        if sys.platform != "win32":  # Windows以外の場合
            if enabled and notify:  # 有効なのに未対応の場合
                self._show_info("自動起動の設定はWindowsのみ対応しています。")  # 通知を表示
            return  # 処理中断
        success, message = self._set_windows_startup_enabled(enabled)  # レジストリ設定を反映
        if not success:  # 失敗した場合
            self._append_log(f"自動起動の設定に失敗しました: {message}")  # ログ出力
            if notify:  # 通知が必要な場合
                self._show_info(f"自動起動の設定に失敗しました: {message}")  # 通知を表示
    def _build_startup_command(self) -> str:  # 自動起動コマンドを構築
        script_path = Path(__file__).resolve().with_name("gui_app.py")  # 起動スクリプトを特定
        if not script_path.exists():  # スクリプトが見つからない場合
            script_path = Path(sys.argv[0]).resolve()  # 実行時の引数からパスを取得
        return f"\"{sys.executable}\" \"{script_path}\""  # 実行コマンドを返却
    def _set_windows_startup_enabled(self, enabled: bool) -> tuple[bool, str]:  # Windows自動起動設定
        try:  # 例外処理開始
            import winreg  # Windowsレジストリ操作
        except Exception as exc:  # 取り込み失敗時
            return False, f"winregの読み込みに失敗しました: {exc}"  # 失敗を返却
        value_name = "HaishinRokugaKun"  # レジストリ値名を定義
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"  # 起動レジストリのパス
        try:  # 例外処理開始
            with winreg.OpenKey(  # レジストリキーを開く
                winreg.HKEY_CURRENT_USER,  # 現在ユーザーのキーを指定
                key_path,  # 対象パスを指定
                0,  # 予約フラグ
                winreg.KEY_SET_VALUE,  # 書き込み権限を指定
            ) as key:  # キー操作の開始
                if enabled:  # 有効化する場合
                    command = self._build_startup_command()  # 起動コマンドを取得
                    winreg.SetValueEx(  # レジストリ値を設定
                        key,  # キー指定
                        value_name,  # 値名指定
                        0,  # 予約値
                        winreg.REG_SZ,  # 文字列型
                        command,  # コマンド文字列
                    )  # レジストリ設定の終了
                else:  # 無効化する場合
                    try:  # 例外処理開始
                        winreg.DeleteValue(key, value_name)  # レジストリ値を削除
                    except FileNotFoundError:  # 値が無い場合
                        pass  # 何もしない
        except OSError as exc:  # レジストリ操作失敗時
            return False, str(exc)  # 失敗理由を返却
        return True, ""  # 成功を返却
    def _build_ui(self) -> None:  # UI構築処理
        central = QtWidgets.QWidget()  # 中央ウィジェットを生成
        self.setCentralWidget(central)  # 中央ウィジェットを設定
        layout = QtWidgets.QVBoxLayout(central)  # メインレイアウトを作成
        layout.setContentsMargins(20, 16, 20, 16)  # 余白を広げて見栄えを改善
        layout.setSpacing(14)  # 行間を整えて視認性を向上
        header = QtWidgets.QLabel("配信URLとファイル名を入力し、録画を開始してください。")  # 説明ラベル
        header.setObjectName("header_label")  # ヘッダー用の識別名を設定
        layout.addWidget(header)  # 説明ラベル追加
        grid = QtWidgets.QGridLayout()  # 入力フォームのグリッドレイアウト
        grid.setHorizontalSpacing(12)  # 水平方向の間隔を設定
        grid.setVerticalSpacing(8)  # 垂直方向の間隔を設定
        layout.addLayout(grid)  # グリッドを追加
        url_label = QtWidgets.QLabel("配信URL")  # 配信URLラベル
        url_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)  # ラベル右寄せ
        self.url_input = QtWidgets.QLineEdit()  # URL入力欄
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")  # プレースホルダ設定
        grid.addWidget(url_label, 0, 0)  # URLラベル配置
        grid.addWidget(self.url_input, 0, 1)  # URL入力配置
        grid.setColumnStretch(1, 1)  # URL入力欄を伸縮させる
        grid.setColumnStretch(2, 0)  # ボタン側は伸縮しない
        grid.setColumnStretch(3, 0)  # ボタン側は伸縮しない
        button_row = QtWidgets.QHBoxLayout()  # ボタン行レイアウト
        self.preview_button = QtWidgets.QPushButton("プレビュー開始")  # プレビュー制御用ボタン
        self.start_button = QtWidgets.QPushButton("録画開始")  # 開始ボタン
        self.stop_button = QtWidgets.QPushButton("録画停止")  # 停止ボタン
        self.auto_resume_button = QtWidgets.QPushButton("自動録画再開")  # 自動録画再開ボタン
        self.stop_button.setEnabled(False)  # 停止ボタンを無効化
        self.auto_resume_button.setEnabled(False)  # 自動録画再開ボタンを無効化
        self.preview_button.clicked.connect(self._toggle_preview)  # プレビューイベント接続
        self.start_button.clicked.connect(self._start_recording)  # 開始イベント接続
        self.stop_button.clicked.connect(self._stop_recording)  # 停止イベント接続
        self.auto_resume_button.clicked.connect(self._resume_auto_recording)  # 自動録画再開イベント接続
        self.preview_button.setVisible(False)  # プレビューボタンは非表示で管理
        button_row.addStretch(1)  # 余白追加
        layout.addLayout(button_row)  # ボタン行追加
        record_button_row = QtWidgets.QHBoxLayout()  # 録画ボタン行レイアウト
        record_button_row.setSpacing(8)  # 録画ボタン間隔を調整
        record_button_row.addWidget(self.start_button)  # 開始ボタン追加
        record_button_row.addWidget(self.stop_button)  # 停止ボタン追加
        record_button_row.addWidget(self.auto_resume_button)  # 自動録画再開ボタン追加
        record_button_widget = QtWidgets.QWidget()  # 録画ボタン用のコンテナ
        record_button_widget.setLayout(record_button_row)  # コンテナにレイアウトを設定
        grid.addWidget(record_button_widget, 0, 2, 1, 2)  # ファイル名欄の位置にボタンを配置
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
    def _apply_ui_theme(self) -> None:  # UIの見た目を整える
        font = QtGui.QFont("Yu Gothic UI", 10)  # 落ち着いた日本語UI向けフォントを指定
        self.setFont(font)  # ウィンドウ全体にフォントを適用
        self.setStyleSheet(  # 画面全体のスタイルを指定
            "QWidget { "  # 全体の指定開始
            "color: #1f2a37; "  # 文字色を落ち着いた濃色にする
            "background: #f4f6f8; "  # 背景色を淡いグレーにする
            "} "  # 全体の指定終了
            "QLabel#header_label { "  # ヘッダーラベルの指定開始
            "font-size: 13px; "  # サイズを少し大きくする
            "font-weight: 600; "  # 太字で強調する
            "color: #111827; "  # 濃い文字色にする
            "} "  # ヘッダーラベルの指定終了
            "QLabel { "  # ラベル全体の指定開始
            "background: transparent; "  # 文字の後ろの背景を透明にする
            "} "  # ラベル全体の指定終了
            "QLineEdit, QPlainTextEdit, QTextEdit { "  # 入力欄の指定開始
            "background: #f8fafc; "  # 入力欄の背景を少し濃くする
            "border: 1px solid #9aa4b2; "  # 枠線をさらに濃くする
            "border-radius: 8px; "  # 角を丸めて柔らかくする
            "padding: 6px 8px; "  # 内側の余白を追加
            "selection-background-color: #d7ebff; "  # 選択色を淡くする
            "} "  # 入力欄の指定終了
            "QPlainTextEdit, QTextEdit { "  # 複数行入力欄の指定開始
            "background: #f5f7fb; "  # 背景を少し濃くする
            "} "  # 複数行入力欄の指定終了
            "QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus { "  # フォーカス時の指定開始
            "border: 1px solid #4f8fe0; "  # 強調色の枠線にする
            "background: #ffffff; "  # 背景色を白に戻す
            "} "  # フォーカス時の指定終了
            "QPushButton { "  # ボタンの指定開始
            "background: #ffffff; "  # ボタン背景を白にする
            "border: 1px solid #d2d7de; "  # 枠線を薄くする
            "border-radius: 10px; "  # 角を丸める
            "padding: 6px 14px; "  # 内側余白を調整
            "min-height: 26px; "  # 高さを揃える
            "} "  # ボタンの指定終了
            "QPushButton:hover { "  # ホバー時の指定開始
            "background: #f1f5f9; "  # 軽く色を付ける
            "border-color: #c7cdd6; "  # 枠線を少し濃くする
            "} "  # ホバー時の指定終了
            "QPushButton:pressed { "  # 押下時の指定開始
            "background: #e6edf5; "  # 押下時の色を濃くする
            "} "  # 押下時の指定終了
            "QGroupBox { "  # グループボックスの指定開始
            "border: 1px solid #d6dbe1; "  # 枠線を薄くする
            "border-radius: 10px; "  # 角を丸める
            "margin-top: 12px; "  # タイトル分の余白を確保
            "background: #ffffff; "  # 背景色を白にする
            "} "  # グループボックスの指定終了
            "QGroupBox::title { "  # グループボックスタイトルの指定開始
            "subcontrol-origin: margin; "  # タイトル位置を調整
            "left: 12px; "  # 左余白を設定
            "top: 2px; "  # 上余白を設定
            "padding: 0 6px; "  # タイトルの余白を設定
            "color: #334155; "  # タイトル色を調整
            "background: #f4f6f8; "  # タイトル背景を薄くする
            "} "  # グループボックスタイトルの指定終了
            "QTabWidget::pane { "  # タブ枠の指定開始
            "border: 1px solid #d6dbe1; "  # 枠線を薄くする
            "border-radius: 8px; "  # 角を丸める
            "} "  # タブ枠の指定終了
            "QTabBar::tab { "  # タブの指定開始
            "background: #e9eef4; "  # タブ背景色を設定
            "border: 1px solid #d6dbe1; "  # タブ枠線を薄くする
            "border-bottom: none; "  # 下線を消して一体感を出す
            "padding: 4px 12px; "  # タブの余白を調整
            "border-top-left-radius: 6px; "  # 左上角を丸める
            "border-top-right-radius: 6px; "  # 右上角を丸める
            "} "  # タブの指定終了
            "QTabBar::tab:selected { "  # 選択タブの指定開始
            "background: #ffffff; "  # 背景を白にする
            "border-color: #cdd3db; "  # 枠線を少し濃くする
            "} "  # 選択タブの指定終了
            "QTextEdit { "  # ログ表示欄の指定開始
            "background: #ffffff; "  # 背景を白にする
            "} "  # ログ表示欄の指定終了
        )  # スタイル指定の終了
    def _format_log_message(self, message: str) -> tuple[str, str]:  # ログを読みやすく整形
        raw = str(message).strip()  # 文字列化して余白を削除
        if not raw:  # 空文字の場合
            return "", ""  # 空として返却
        label = ""  # ラベルを初期化
        body = raw  # 本文を初期化
        if ":" in raw and not raw.lstrip().lower().startswith("http"):  # ラベル形式か判定
            candidate, rest = raw.split(":", 1)  # 先頭の区切りで分割
            if "://" not in candidate:  # URLスキームでない場合
                label = candidate.strip()  # ラベルを確定
                body = rest.strip()  # 本文を確定
        category = ""  # カテゴリを初期化
        if label:  # ラベルがある場合
            if label.startswith("自動監視"):  # 自動監視系のラベル
                category = "監視"  # 監視カテゴリに統一
            elif label.startswith("YouTube"):  # YouTube系のラベル
                category = "YouTube"  # YouTubeカテゴリに統一
            elif label.startswith("自動録画") or label.startswith("録画") or label == "出力先":  # 録画系ラベル
                category = "録画"  # 録画カテゴリに統一
            elif label.startswith("プレビュー"):  # プレビュー系ラベル
                category = "プレビュー"  # プレビューカテゴリに統一
            else:  # 未分類のラベル
                category = label  # ラベルをそのままカテゴリに使用
        else:  # ラベルが無い場合
            if raw.startswith("自動監視"):  # 自動監視の文章
                category = "監視"  # 監視カテゴリに設定
            elif raw.startswith("録画開始により自動録画"):  # 自動録画開始の補助文
                category = "監視"  # 監視カテゴリに設定
            elif raw.startswith("自動録画") or raw.startswith("録画"):  # 録画系の文章
                category = "録画"  # 録画カテゴリに設定
            elif raw.startswith("プレビュー"):  # プレビュー系の文章
                category = "プレビュー"  # プレビューカテゴリに設定
            else:  # その他の文章
                category = "情報"  # 情報カテゴリに設定
        if label and category:  # ラベルとカテゴリがある場合
            omit_labels = {  # 省略しても意味が通るラベル一覧
                "自動監視",  # 自動監視系
                "自動録画",  # 自動録画系
                "自動録画開始",  # 自動録画開始
                "自動録画終了",  # 自動録画終了
                "録画開始",  # 録画開始
                "録画終了",  # 録画終了
                "プレビュー",  # プレビュー系
                "YouTube /live検出",  # YouTube検出
                "YouTube",  # YouTube系
            }  # 省略対象の終了
            if label not in omit_labels:  # 省略対象でない場合
                body = f"{label} {body}".strip()  # ラベルを本文に加える
        return category, body  # 整形後のカテゴリと本文を返却
    def _is_log_category_enabled(self, category: str) -> bool:  # ログカテゴリの表示可否を確認
        mapping = {  # カテゴリと設定キーの対応
            "監視": "log_show_monitor",  # 監視ログの表示設定
            "録画": "log_show_recording",  # 録画ログの表示設定
            "プレビュー": "log_show_preview",  # プレビューログの表示設定
            "YouTube": "log_show_youtube",  # YouTubeログの表示設定
            "情報": "log_show_info",  # 情報ログの表示設定
        }  # 対応表の終了
        key = mapping.get(category)  # 対応キーを取得
        if not key:  # 対応が無い場合
            return True  # 既定で表示する
        return load_bool_setting(key, True)  # 設定値を取得して返却
    def _append_log(self, message: str) -> None:  # ログ追加処理
        timestamp = QtCore.QDateTime.currentDateTime().toString("HH:mm:ss")  # 時刻のみのタイムスタンプ生成
        category, body = self._format_log_message(message)  # ログを整形
        if not category or not body:  # 空のログの場合
            return  # 追記しない
        if not self._is_log_category_enabled(category):  # 表示対象外の場合
            return  # 追記しない
        self.log_output.append(f"{timestamp} | {category} | {body}")  # ログを追記
    def _show_tray_notification(self, title: str, message: str) -> None:  # タスクトレイ通知を表示
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():  # トレイ非対応の場合
            self._append_log(message)  # ログへ出力
            return  # 処理中断
        if self.tray_icon is None:  # トレイ未初期化の場合
            self._setup_tray_icon()  # トレイを初期化
        if not isinstance(self.tray_icon, QtWidgets.QSystemTrayIcon):  # トレイが無い場合
            self._append_log(message)  # ログへ出力
            return  # 処理中断
        self.tray_icon.show()  # トレイアイコンを表示
        self.tray_icon.showMessage(  # 通知を表示
            title,  # 通知タイトル
            message,  # 通知本文
            QtWidgets.QSystemTrayIcon.MessageIcon.Information,  # 情報アイコン
            4000,  # 表示時間
        )  # 通知表示の終了
    def _show_info(self, message: str) -> None:  # 通知表示処理
        QtWidgets.QMessageBox.information(self, "情報", message)  # 情報ダイアログ表示
    def _show_about(self) -> None:  # 情報ダイアログ表示
        QtWidgets.QMessageBox.information(  # 情報ダイアログを表示
            self,  # 親ウィンドウ指定
            "このアプリについて",  # タイトル指定
            "配信録画くん\n配信の録画・自動監視をサポートします。",  # 表示メッセージ
        )  # ダイアログ表示終了
    def _show_api_help(self) -> None:  # APIキー案内ダイアログ表示
        message = (  # 案内メッセージを組み立て
            "YouTube APIキーの取得方法\n"
            "1) Google Cloud Consoleでプロジェクトを作成\n"
            "2) YouTube Data API v3 を有効化\n"
            "3) 認証情報からAPIキーを作成\n"
            "4) 設定の「YouTube APIキー」に入力\n\n"
            "Twitch Client ID / Client Secret の取得方法\n"
            "1) https://dev.twitch.tv/ でDeveloper Consoleへログイン\n"
            "2) アプリケーションを登録\n"
            "3) Client ID と Client Secret を取得\n"
            "4) 設定の「Twitch Client ID / Client Secret」に入力\n\n"
            "※ Client Secretは他人に共有しないでください。"
        )  # メッセージ生成の終了
        QtWidgets.QMessageBox.information(  # 案内ダイアログを表示
            self,  # 親ウィンドウ指定
            "APIキーの準備",  # タイトル指定
            message,  # 表示メッセージ
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
            "StreamCapture.csv",  # 既定ファイル名
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
            self._apply_tray_setting(True)  # タスクトレイ設定を反映
            self._apply_startup_setting(True)  # 自動起動設定を反映
            self._show_info("設定を更新しました。")  # 通知表示
    def _resolve_stream_url(self, url: str) -> Optional[str]:  # ストリームURLを解決
        quality = DEFAULT_QUALITY  # 画質は常に最高品質に固定
        http_timeout = load_setting_value("http_timeout", 20, int)  # 設定からHTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # 設定からストリームタイムアウト取得
        session = Streamlink()  # Streamlinkセッション生成
        session.set_option("http-timeout", int(http_timeout))  # HTTPタイムアウト設定
        session.set_option("stream-timeout", int(stream_timeout))  # ストリームタイムアウト設定
        apply_streamlink_options_for_url(session, url)  # URL別のStreamlinkオプションを反映
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
    def _is_twitch_live_for_preview(self, url: str) -> bool:  # Twitchプレビューのライブ判定
        parsed = urlparse(url)  # URLを解析
        host = parsed.netloc.lower()  # ホストを取得
        if "twitch" not in host and "twitch" not in url:  # Twitch以外の場合
            return True  # 判定不要としてTrue
        login = normalize_twitch_login(url)  # ログイン名を取得
        if not login:  # ログイン名が無い場合
            return True  # 判定不要としてTrue
        client_id = load_setting_value("twitch_client_id", "", str).strip()  # Client ID取得
        client_secret = load_setting_value("twitch_client_secret", "", str).strip()  # Client Secret取得
        if not client_id or not client_secret:  # APIキー不足の場合
            self._append_log("Twitch APIキーが未設定のためライブ判定をスキップします。")  # 判定スキップログ
            return True  # 判定できないためTrue
        live_urls = fetch_twitch_live_urls(  # TwitchライブURLを取得
            client_id=client_id,  # Client ID指定
            client_secret=client_secret,  # Client Secret指定
            entries=[login],  # ログイン名を指定
            log_cb=self._append_log,  # ログコールバック指定
        )  # 取得終了
        for live_url in live_urls:  # ライブURLごとに確認
            live_login = normalize_twitch_login(live_url)  # ライブ側のログイン名を取得
            if live_login == login:  # ログイン名が一致する場合
                return True  # ライブ中としてTrue
        self._append_log("Twitch配信がオフラインのためプレビューを開始しません。")  # オフラインログ
        self._show_info("Twitch配信がオフラインのためプレビューを開始しません。")  # オフライン通知
        return False  # オフラインとしてFalse
    def _is_twitch_url(self, url: str) -> bool:  # Twitch URL判定
        parsed = urlparse(url)  # URLを解析
        host = parsed.netloc.lower()  # ホストを取得
        if "twitch" in host:  # ホストにTwitchが含まれる場合
            return True  # Twitch URLとして扱う
        return "twitch" in url  # 文字列からも補助的に判定する
    def _should_use_ffmpeg_preview(self, url: str) -> bool:  # FFmpegプレビュー使用判定
        return is_twitcasting_url(url)  # ツイキャスの場合はFFmpeg経由
    def _allocate_preview_tcp_port(self) -> int:  # TCPポート確保
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCPソケット生成
        sock.bind(("127.0.0.1", 0))  # 空きポートを割り当て
        port = sock.getsockname()[1]  # 割り当てポート取得
        sock.close()  # ソケットを閉じる
        return int(port)  # ポート番号を返却
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
            output_url,  # ネットワークへ出力
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
        merged_urls = merge_unique_urls(twitcasting_urls, niconico_urls, tiktok_urls)  # 監視URLを結合
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
        channel_label = self._resolve_channel_folder_label(normalized_url)  # 配信者名を取得
        self._show_tray_notification(  # 自動録画開始を通知
            "配信録画くん",  # 通知タイトル
            f"{channel_label}さんの配信の録画を開始します。",  # 通知本文
        )  # 通知表示の終了
        if self._is_twitch_url(normalized_url):  # Twitchの場合
            self._start_recording_preview_from_file(  # 録画ファイルでプレビュー
                normalized_url,  # URL指定
                output_path,  # 出力パス指定
                "自動録画",  # 理由指定
                False,  # タブを強制選択しない
            )  # 録画ファイルプレビューの終了
        else:  # Twitch以外の場合
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
        self._stop_preview_for_url(url, remove_tab=True)  # 自動録画のプレビューを停止
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
            preview_urls = self._collect_preview_urls_from_settings()  # 設定からプレビューURLを取得
            if not preview_urls:  # プレビュー対象が無い場合
                self._show_info("設定にプレビュー対象の配信URLがありません。")  # 通知表示
                return  # 処理中断
            self._append_log("設定に登録された配信URLのプレビューを開始します。")  # 開始ログを出力
            for preview_url in preview_urls:  # URLごとに処理
                self._start_preview_for_url(  # URL指定でプレビュー開始
                    preview_url,  # URL指定
                    update_input=False,  # 入力欄を更新しない
                    reason="設定",  # 理由は設定開始
                    select_tab=False,  # タブを強制選択しない
                )  # プレビュー開始の終了
            return  # 設定プレビューで終了
        self._start_preview_for_url(url, update_input=False, reason="手動", select_tab=True)  # URL指定でプレビュー開始
    def _is_recording_active_for_url(self, url: str) -> bool:  # URLの録画中判定
        if self.manual_recording_url == url:  # 手動録画URLが一致する場合
            thread = self.worker_thread  # 手動録画スレッドを取得
            if isinstance(thread, QtCore.QThread) and thread.isRunning():  # スレッドが動作中の場合
                return True  # 録画中として扱う
        session = self.auto_sessions.get(url)  # 自動録画セッションを取得
        if isinstance(session, dict):  # セッションが存在する場合
            thread = session.get("thread")  # 自動録画スレッドを取得
            if isinstance(thread, QtCore.QThread) and thread.isRunning():  # スレッドが動作中の場合
                return True  # 録画中として扱う
        return False  # 録画中ではない場合
    def _start_recording_preview_from_file(  # 録画ファイルからプレビュー開始
        self,  # 自身参照
        url: str,  # URL指定
        output_path: Path,  # 出力パス指定
        reason: str,  # 理由指定
        select_tab: bool,  # タブ選択フラグ
    ) -> None:  # 返り値なし
        if not self._is_twitch_url(url):  # Twitch以外の場合
            self._start_preview_for_url(  # 通常プレビューを実行
                url,  # URL指定
                update_input=False,  # 入力欄を更新しない
                reason=reason,  # 理由指定
                select_tab=select_tab,  # タブ選択を反映
            )  # 通常プレビューの終了
            return  # 以降の処理は不要
        if not self._is_recording_active_for_url(url):  # 録画中でない場合
            return  # 処理中断
        if not output_path.exists():  # 録画ファイルが無い場合
            QtCore.QTimer.singleShot(  # 少し待って再試行
                500,  # 待機時間
                lambda target_url=url, path=output_path: self._start_recording_preview_from_file(  # 再試行処理
                    target_url,  # URLを渡す
                    path,  # 出力パスを渡す
                    reason,  # 理由を渡す
                    select_tab,  # タブ選択を渡す
                ),  # 再試行呼び出し終了
            )  # タイマー設定終了
            return  # いったん終了
        if output_path.stat().st_size < 188 * 10:  # TSヘッダ程度しか無い場合
            QtCore.QTimer.singleShot(  # 少し待って再試行
                500,  # 待機時間
                lambda target_url=url, path=output_path: self._start_recording_preview_from_file(  # 再試行処理
                    target_url,  # URLを渡す
                    path,  # 出力パスを渡す
                    reason,  # 理由を渡す
                    select_tab,  # タブ選択を渡す
                ),  # 再試行呼び出し終了
            )  # タイマー設定終了
            return  # いったん終了
        file_url = QtCore.QUrl.fromLocalFile(str(output_path))  # ローカルファイルURLを生成
        if url in self.preview_sessions:  # 既存プレビューがある場合
            session = self.preview_sessions[url]  # セッションを取得
            player = session.get("player")  # プレイヤーを取得
            if not isinstance(player, QtMultimedia.QMediaPlayer):  # プレイヤーが無い場合
                return  # 何もしない
            refresh_timer = session.get("refresh_timer")  # 再接続タイマーを取得
            if isinstance(refresh_timer, QtCore.QTimer):  # タイマーがある場合
                refresh_timer.stop()  # タイマーを停止
                refresh_timer.deleteLater()  # タイマーを破棄
                session["refresh_timer"] = None  # 参照をクリア
            stall_timer = session.get("stall_timer")  # 停止検知タイマーを取得
            if isinstance(stall_timer, QtCore.QTimer):  # タイマーがある場合
                stall_timer.stop()  # タイマーを停止
                stall_timer.deleteLater()  # タイマーを破棄
                session["stall_timer"] = None  # 参照をクリア
            process = session.get("process")  # プロセスを取得
            if isinstance(process, QtCore.QProcess):  # プロセスがある場合
                process.terminate()  # プロセスを停止
                process.waitForFinished(2000)  # 停止を待機
                if process.state() == QtCore.QProcess.ProcessState.Running:  # まだ動作中の場合
                    process.kill()  # 強制停止
                process.deleteLater()  # プロセスを破棄
            stop_event = session.get("pipe_stop_event")  # 停止フラグを取得
            if isinstance(stop_event, threading.Event):  # 停止フラグがある場合
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
            player.stop()  # プレイヤーを停止
            player.setSource(file_url)  # ローカルファイルを設定
            player.play()  # 再生を開始
            session["process"] = None  # プロセス参照をクリア
            session["pipe_stop_event"] = None  # 停止フラグ参照をクリア
            session["pipe_thread"] = None  # スレッド参照をクリア
            session["pipe_worker"] = None  # ワーカー参照をクリア
            session["pipe_proxy"] = None  # 代理参照をクリア
            session["preview_url"] = None  # プレビューURLをクリア
            session["use_ffmpeg"] = False  # FFmpeg利用状態をクリア
            session["recording_path"] = str(output_path)  # 録画ファイルパスを保存
            session["seek_to_tail"] = True  # 末尾へ移動するフラグを設定
            session["last_position"] = 0  # 再生位置を初期化
            session["last_position_at"] = time.monotonic()  # 監視時刻を初期化
            session["recording_last_size"] = output_path.stat().st_size  # 録画ファイルのサイズを記録
            session["recording_reload_at"] = time.monotonic()  # 再読み込み時刻を記録
            self._setup_preview_stall_watchdog(url)  # 停止検知の監視を設定
            self._setup_recording_refresh_timer(url)  # 録画ファイルの更新監視を設定
            if select_tab:  # タブ選択を行う場合
                widget = session.get("widget")  # コンテナを取得
                if isinstance(widget, QtWidgets.QWidget):  # ウィジェットがある場合
                    self.preview_tabs.setCurrentWidget(widget)  # タブを選択
            self.preview_button.setText("プレビュー停止")  # ボタン表示更新
            self._append_log(f"プレビューを更新しました（{reason}: 録画ファイル）。")  # ログ出力
            return  # 更新処理を終了
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
            "process": None,  # プロセス参照をクリア
            "pipe_stop_event": None,  # 停止フラグ参照をクリア
            "pipe_thread": None,  # スレッド参照をクリア
            "pipe_worker": None,  # ワーカー参照をクリア
            "pipe_proxy": None,  # 代理参照をクリア
            "preview_url": None,  # プレビューURLをクリア
            "use_ffmpeg": False,  # FFmpeg利用状態をクリア
            "retry_pending": False,  # リトライ待機フラグ
            "retry_count": 0,  # リトライ回数
            "last_retry_at": 0.0,  # 最終リトライ時刻
            "refresh_timer": None,  # 再接続タイマー
            "stall_timer": None,  # 停止検知タイマー
            "recording_path": str(output_path),  # 録画ファイルパス
            "seek_to_tail": True,  # 末尾へ移動するフラグ
            "recording_refresh_timer": None,  # 録画ファイル更新タイマー
            "recording_last_size": output_path.stat().st_size,  # 録画ファイルのサイズ
            "recording_reload_at": time.monotonic(),  # 再読み込み時刻
            "last_position": 0,  # 再生位置の監視値
            "last_position_at": 0.0,  # 再生位置の更新時刻
        }  # セッション保存の終了
        player.setSource(file_url)  # ローカルファイルを設定
        player.play()  # 再生を開始
        self._setup_preview_stall_watchdog(url)  # 停止検知の監視を設定
        self._setup_recording_refresh_timer(url)  # 録画ファイルの更新監視を設定
        if select_tab or self.preview_tabs.count() == 1:  # タブ選択条件
            self.preview_tabs.setCurrentWidget(container)  # タブを選択
        self.preview_button.setText("プレビュー停止")  # ボタン表示更新
        self._append_log(f"プレビューを開始しました（{reason}: 録画ファイル）。")  # ログ出力
        player.errorOccurred.connect(  # 再生エラー時の処理
            lambda _, __, target_url=url: self._handle_preview_error(target_url)  # 対象URLで処理
        )  # エラー処理接続の終了
        player.mediaStatusChanged.connect(  # メディア状態変化時の処理
            lambda status, target_url=url: self._handle_preview_status(target_url, status)  # 状態変化を処理
        )  # 状態変化処理接続の終了
    def _start_preview_for_url(self, url: str, update_input: bool, reason: str, select_tab: bool) -> None:  # URL指定プレビュー開始
        if update_input:  # 入力欄を更新する場合
            self.url_input.setText(url)  # URL入力欄を更新
        if reason == "手動" and not self._is_twitch_live_for_preview(url):  # 手動プレビューのTwitch判定
            return  # オフラインなら開始しない
        use_ffmpeg = self._should_use_ffmpeg_preview(url)  # FFmpeg利用判定
        process: QtCore.QProcess | None = None  # プロセス初期化
        pipe_stop_event: threading.Event | None = None  # パイプ停止フラグ
        pipe_thread: QtCore.QThread | None = None  # パイプ転送スレッド
        pipe_worker: StreamlinkPreviewWorker | None = None  # パイプ読み込みワーカー
        pipe_proxy: PreviewPipeProxy | None = None  # パイプ書き込み代理
        stream_url = None  # ストリームURL初期化
        preview_url = None  # プレビューURL初期化
        if use_ffmpeg:  # FFmpegを使う場合
            port = self._allocate_preview_tcp_port()  # TCPポート確保
            preview_url = f"tcp://127.0.0.1:{port}"  # TCPで受信
            output_url = f"tcp://127.0.0.1:{port}?listen=1&listen_timeout=5"  # FFmpeg出力URLを生成
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
                self._start_player_with_source(player, preview_url, 800)  # 少し待ってから再生を開始
                session["process"] = process  # プロセス参照を更新
                session["pipe_stop_event"] = pipe_stop_event  # 停止フラグを更新
                session["pipe_thread"] = pipe_thread  # スレッド参照を更新
                session["pipe_worker"] = pipe_worker  # ワーカー参照を更新
                session["pipe_proxy"] = pipe_proxy  # 代理参照を更新
                session["preview_url"] = preview_url  # プレビューURLを更新
                session["use_ffmpeg"] = True  # FFmpeg利用状態を更新
                session["recording_path"] = None  # 録画ファイルパスをクリア
                session["seek_to_tail"] = False  # 末尾移動フラグを解除
            else:  # URL利用時
                player.setSource(QtCore.QUrl(stream_url))  # プレイヤーにソース設定
                session["process"] = None  # プロセス参照をクリア
                session["pipe_stop_event"] = None  # 停止フラグをクリア
                session["pipe_thread"] = None  # スレッド参照をクリア
                session["pipe_worker"] = None  # ワーカー参照をクリア
                session["pipe_proxy"] = None  # 代理参照をクリア
                session["preview_url"] = None  # プレビューURLをクリア
                session["use_ffmpeg"] = False  # FFmpeg利用状態を更新
            session["recording_path"] = None  # 録画ファイルパスをクリア
            session["seek_to_tail"] = False  # 末尾移動フラグを解除
            refresh_timer = session.get("recording_refresh_timer")  # 更新監視タイマーを取得
            if isinstance(refresh_timer, QtCore.QTimer):  # タイマーがある場合
                refresh_timer.stop()  # タイマーを停止
                refresh_timer.deleteLater()  # タイマーを破棄
            session["recording_refresh_timer"] = None  # タイマー参照をクリア
            player.play()  # 再生開始
            self._setup_twitch_refresh_timer(url)  # Twitchの再接続タイマーを設定
            self._setup_preview_stall_watchdog(url)  # 停止検知の監視を設定
            session["last_position"] = 0  # 監視用の再生位置を初期化
            session["last_position_at"] = time.monotonic()  # 監視時刻を初期化
            if select_tab:  # タブを選択する場合
                self.preview_tabs.setCurrentWidget(session["widget"])  # 対象タブを選択
            self.preview_button.setText("プレビュー停止")  # ボタン表示更新
            self._append_log(f"プレビューを更新しました（{reason}）。")  # ログ出力
            session["retry_pending"] = False  # リトライ待機を解除
            session["retry_count"] = 0  # リトライ回数を初期化
            session["last_retry_at"] = 0.0  # 最終リトライ時刻を初期化
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
            "use_ffmpeg": bool(use_ffmpeg),  # FFmpeg利用状態
            "retry_pending": False,  # リトライ待機フラグ
            "retry_count": 0,  # リトライ回数
            "last_retry_at": 0.0,  # 最終リトライ時刻
            "refresh_timer": None,  # 再接続タイマー
            "stall_timer": None,  # 停止検知タイマー
            "last_position": 0,  # 再生位置の監視値
            "last_position_at": 0.0,  # 再生位置の更新時刻
            "recording_path": None,  # 録画ファイルパス
            "seek_to_tail": False,  # 末尾へ移動するフラグ
        }  # セッション保存の終了
        if use_ffmpeg and isinstance(process, QtCore.QProcess):  # FFmpeg利用時
            self._start_player_with_source(player, preview_url, 800)  # 少し待ってから再生を開始
        else:  # URL利用時
            player.setSource(QtCore.QUrl(stream_url))  # プレイヤーにソース設定
            player.play()  # 再生開始
            self._setup_twitch_refresh_timer(url)  # Twitchの再接続タイマーを設定
            self._setup_preview_stall_watchdog(url)  # 停止検知の監視を設定
            session = self.preview_sessions.get(url)  # セッションを取得
            if isinstance(session, dict):  # セッションがある場合
                session["last_position"] = 0  # 監視用の再生位置を初期化
                session["last_position_at"] = time.monotonic()  # 監視時刻を初期化
        if select_tab or self.preview_tabs.count() == 1:  # タブ選択条件
            self.preview_tabs.setCurrentWidget(container)  # タブを選択
        self.preview_button.setText("プレビュー停止")  # ボタン表示更新
        self._append_log(f"プレビューを開始しました（{reason}）。")  # ログ出力
        player.errorOccurred.connect(  # 再生エラー時の再接続処理
            lambda _, __, target_url=url: self._handle_preview_error(target_url)  # 対象URLで処理
        )  # エラー処理接続の終了
        player.mediaStatusChanged.connect(  # メディア状態変化時の処理
            lambda status, target_url=url: self._handle_preview_status(target_url, status)  # 状態変化を処理
        )  # 状態変化処理接続の終了
        session = self.preview_sessions.get(url)  # セッションを取得
        if isinstance(session, dict):  # セッションがある場合
            session["retry_pending"] = False  # リトライ待機を解除
            session["retry_count"] = 0  # リトライ回数を初期化
            session["last_retry_at"] = 0.0  # 最終リトライ時刻を初期化
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
        refresh_timer = session.get("refresh_timer")  # 再接続タイマーを取得
        if isinstance(refresh_timer, QtCore.QTimer):  # タイマーがある場合
            refresh_timer.stop()  # タイマーを停止
            refresh_timer.deleteLater()  # タイマーを破棄
        stall_timer = session.get("stall_timer")  # 停止検知タイマーを取得
        if isinstance(stall_timer, QtCore.QTimer):  # タイマーがある場合
            stall_timer.stop()  # タイマーを停止
            stall_timer.deleteLater()  # タイマーを破棄
        recording_timer = session.get("recording_refresh_timer")  # 録画更新タイマーを取得
        if isinstance(recording_timer, QtCore.QTimer):  # タイマーがある場合
            recording_timer.stop()  # タイマーを停止
            recording_timer.deleteLater()  # タイマーを破棄
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
    def _start_player_with_source(self, player: QtMultimedia.QMediaPlayer, url: str, delay_ms: int) -> None:  # 再生開始を遅延
        def _start() -> None:  # 遅延後に実行する処理
            player.setSource(QtCore.QUrl(url))  # 再生ソースを設定
            player.play()  # 再生を開始
        if delay_ms <= 0:  # 遅延が不要な場合
            _start()  # すぐに再生を開始
            return  # 処理終了
        QtCore.QTimer.singleShot(delay_ms, _start)  # 遅延して再生を開始
    def _setup_recording_refresh_timer(self, url: str) -> None:  # 録画ファイル更新の監視タイマー
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        if not session.get("recording_path"):  # 録画ファイル再生でない場合
            return  # 何もしない
        existing_timer = session.get("recording_refresh_timer")  # 既存タイマーを取得
        if isinstance(existing_timer, QtCore.QTimer):  # 既にタイマーがある場合
            return  # 追加生成しない
        timer = QtCore.QTimer(self)  # 更新監視用のタイマーを生成
        timer.setInterval(5000)  # 5秒間隔で更新
        timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)  # タイマー種別を指定
        timer.timeout.connect(lambda target_url=url: self._check_recording_refresh(target_url))  # 監視処理を接続
        timer.start()  # タイマー開始
        session["recording_refresh_timer"] = timer  # タイマー参照を保存
    def _check_recording_refresh(self, url: str) -> None:  # 録画ファイルの更新確認
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        recording_path = session.get("recording_path")  # 録画ファイルパスを取得
        if not recording_path:  # 録画ファイルが無い場合
            return  # 何もしない
        if not self._is_recording_active_for_url(url):  # 録画中でない場合
            return  # 何もしない
        path = Path(str(recording_path))  # パスオブジェクトを生成
        if not path.exists():  # ファイルが無い場合
            return  # 何もしない
        try:  # 例外処理開始
            size = path.stat().st_size  # ファイルサイズを取得
        except OSError:  # 取得失敗時
            return  # 何もしない
        last_size = int(session.get("recording_last_size", 0))  # 前回サイズを取得
        if size <= last_size:  # サイズが増えていない場合
            return  # 何もしない
        now = time.monotonic()  # 現在時刻を取得
        last_reload = float(session.get("recording_reload_at", 0.0))  # 再読み込み時刻を取得
        if now - last_reload < 2.0:  # 再読み込み間隔が短い場合
            return  # 何もしない
        session["recording_last_size"] = size  # サイズを更新
        session["recording_reload_at"] = now  # 再読み込み時刻を更新
        self._refresh_recording_file_preview(url, "更新")  # 録画プレビューを再読込
    def _setup_twitch_refresh_timer(self, url: str) -> None:  # Twitchプレビュー再接続タイマー
        if not self._is_twitch_url(url):  # Twitch以外は対象外
            return  # 何もしない
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        if session.get("use_ffmpeg"):  # FFmpeg利用中は対象外
            return  # 何もしない
        existing_timer = session.get("refresh_timer")  # 既存タイマーを取得
        if isinstance(existing_timer, QtCore.QTimer):  # 既にタイマーがある場合
            return  # 追加生成しない
        timer = QtCore.QTimer(self)  # タイマーを生成
        timer.setInterval(60000)  # 1分間隔で更新
        timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)  # タイマー種別を指定
        timer.timeout.connect(lambda target_url=url: self._refresh_twitch_preview(target_url))  # タイマー処理を接続
        timer.start()  # タイマー開始
        session["refresh_timer"] = timer  # タイマー参照を保存
    def _setup_preview_stall_watchdog(self, url: str) -> None:  # プレビュー停止検知の監視タイマー
        if not self._is_twitch_url(url):  # Twitch以外は対象外
            return  # 何もしない
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        if session.get("use_ffmpeg"):  # FFmpeg利用中は対象外
            return  # 何もしない
        existing_timer = session.get("stall_timer")  # 既存タイマーを取得
        if isinstance(existing_timer, QtCore.QTimer):  # 既にタイマーがある場合
            return  # 追加生成しない
        timer = QtCore.QTimer(self)  # 監視用タイマーを生成
        timer.setInterval(5000)  # 5秒間隔で監視
        timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)  # タイマー種別を指定
        timer.timeout.connect(lambda target_url=url: self._check_preview_stall(target_url))  # 監視処理を接続
        timer.start()  # タイマー開始
        session["stall_timer"] = timer  # 監視タイマー参照を保存
        session["last_position"] = 0  # 最終再生位置を初期化
        session["last_position_at"] = time.monotonic()  # 最終更新時刻を記録
    def _refresh_twitch_preview(self, url: str) -> None:  # Twitchプレビュー再接続処理
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        if session.get("use_ffmpeg"):  # FFmpeg利用中は対象外
            return  # 何もしない
        player = session.get("player")  # プレイヤーを取得
        if not isinstance(player, QtMultimedia.QMediaPlayer):  # プレイヤーが無い場合
            return  # 何もしない
        if player.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:  # 再生中の場合
            status = player.mediaStatus()  # 再生状態を取得
            if status in (  # 問題が無い場合
                QtMultimedia.QMediaPlayer.MediaStatus.BufferedMedia,  # バッファ済み
                QtMultimedia.QMediaPlayer.MediaStatus.LoadedMedia,  # 読み込み済み
            ):  # 状態一覧の終了
                return  # 再接続しない
        stream_url = self._resolve_stream_url(url)  # ストリームURLを再取得
        if not stream_url:  # 取得できない場合
            return  # 何もしない
        player.setSource(QtCore.QUrl(stream_url))  # 新しいソースを設定
        player.play()  # 再生を開始
        session["last_position"] = 0  # 再生位置の監視を初期化
        session["last_position_at"] = time.monotonic()  # 最終更新時刻を更新
    def _refresh_recording_file_preview(self, url: str, reason: str) -> None:  # 録画ファイルプレビューを再読込
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        recording_path = session.get("recording_path")  # 録画ファイルパスを取得
        if not recording_path:  # 録画ファイルが無い場合
            return  # 何もしない
        if not self._is_recording_active_for_url(url):  # 録画中でない場合
            return  # 何もしない
        path = Path(str(recording_path))  # パスオブジェクトを生成
        if not path.exists():  # ファイルが無い場合
            QtCore.QTimer.singleShot(  # 少し待って再試行
                500,  # 待機時間
                lambda target_url=url, reason_text=reason: self._refresh_recording_file_preview(  # 再試行処理
                    target_url,  # URLを渡す
                    reason_text,  # 理由を渡す
                ),  # 再試行呼び出し終了
            )  # タイマー設定終了
            return  # いったん終了
        if path.stat().st_size < 188 * 10:  # データが少ない場合
            QtCore.QTimer.singleShot(  # 少し待って再試行
                500,  # 待機時間
                lambda target_url=url, reason_text=reason: self._refresh_recording_file_preview(  # 再試行処理
                    target_url,  # URLを渡す
                    reason_text,  # 理由を渡す
                ),  # 再試行呼び出し終了
            )  # タイマー設定終了
            return  # いったん終了
        player = session.get("player")  # プレイヤーを取得
        if not isinstance(player, QtMultimedia.QMediaPlayer):  # プレイヤーが無い場合
            return  # 何もしない
        file_url = QtCore.QUrl.fromLocalFile(str(path))  # ファイルURLを生成
        session["seek_to_tail"] = True  # 末尾追従フラグを設定
        player.stop()  # プレイヤーを停止
        player.setSource(file_url)  # ソースを更新
        player.play()  # 再生を再開
        session["last_position"] = 0  # 再生位置を初期化
        session["last_position_at"] = time.monotonic()  # 監視時刻を初期化
        session["recording_last_size"] = path.stat().st_size  # ファイルサイズを更新
        session["recording_reload_at"] = time.monotonic()  # 再読み込み時刻を更新
        self._setup_preview_stall_watchdog(url)  # 停止検知の監視を設定
        self._append_log(f"プレビューを再読み込みしました（録画ファイル: {reason}）。")  # ログ出力
    def _seek_recording_preview_to_tail(self, url: str) -> None:  # 録画プレビューを末尾へ移動
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        if not session.get("recording_path"):  # 録画ファイルが無い場合
            return  # 何もしない
        if not session.get("seek_to_tail"):  # 末尾移動が不要な場合
            return  # 何もしない
        player = session.get("player")  # プレイヤーを取得
        if not isinstance(player, QtMultimedia.QMediaPlayer):  # プレイヤーが無い場合
            return  # 何もしない
        duration = int(player.duration())  # 再生時間を取得
        if duration <= 0:  # まだ取得できない場合
            return  # 何もしない
        seek_position = max(0, duration - 3000)  # 末尾から3秒戻した位置
        player.setPosition(seek_position)  # 再生位置を移動
        session["seek_to_tail"] = False  # 末尾移動を完了
    def _check_preview_stall(self, url: str) -> None:  # プレビュー停止検知処理
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        if session.get("use_ffmpeg"):  # FFmpeg利用中は対象外
            return  # 何もしない
        if session.get("recording_path"):  # 録画ファイル再生中の場合
            now = time.monotonic()  # 現在時刻を取得
            last_retry = float(session.get("last_retry_at", 0.0))  # 最終リトライ時刻を取得
            if now - last_retry < 2.5:  # 再接続が近すぎる場合
                return  # 何もしない
        player = session.get("player")  # プレイヤー参照を取得
        if not isinstance(player, QtMultimedia.QMediaPlayer):  # プレイヤーが無い場合
            return  # 何もしない
        status = player.mediaStatus()  # メディア状態を取得
        if status in (  # 再生準備中の状態
            QtMultimedia.QMediaPlayer.MediaStatus.LoadingMedia,  # 読み込み中
            QtMultimedia.QMediaPlayer.MediaStatus.BufferingMedia,  # バッファリング中
        ):  # 状態一覧の終了
            session["last_position"] = int(player.position())  # 監視位置を更新
            session["last_position_at"] = time.monotonic()  # 更新時刻を記録
            return  # 監視対象外
        if player.playbackState() != QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:  # 再生中以外
            session["last_position"] = int(player.position())  # 監視位置を更新
            session["last_position_at"] = time.monotonic()  # 更新時刻を記録
            return  # 監視対象外
        now = time.monotonic()  # 現在時刻を取得
        current_position = int(player.position())  # 現在の再生位置を取得
        last_position = int(session.get("last_position", 0))  # 前回の再生位置を取得
        last_position_at = float(session.get("last_position_at", now))  # 前回更新時刻を取得
        if current_position > last_position:  # 再生が進んでいる場合
            session["last_position"] = current_position  # 監視位置を更新
            session["last_position_at"] = now  # 更新時刻を記録
            return  # 監視終了
        if now - last_position_at < 8.0:  # 停止判定までの猶予
            return  # まだ待機する
        session["last_position"] = current_position  # 監視位置を更新
        session["last_position_at"] = now  # 更新時刻を記録
        if session.get("recording_path"):  # 録画ファイル再生中の場合
            session["last_retry_at"] = now  # 最終リトライ時刻を更新
            self._refresh_recording_file_preview(url, "停止検知")  # 録画プレビューを更新
            return  # 録画プレビュー処理で終了
        self._schedule_preview_retry(url, "停止検知")  # 再接続をスケジュール
    def _handle_preview_error(self, url: str) -> None:  # プレビューエラー時の処理
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        if session.get("recording_path"):  # 録画ファイル再生中の場合
            self._refresh_recording_file_preview(url, "エラー")  # 録画プレビューを再読込
            return  # 以降の処理を行わない
        if not (self._is_twitch_url(url) or session.get("use_ffmpeg")):  # 対象外の場合
            return  # 何もしない
        self._schedule_preview_retry(url, "再接続")  # 再接続をスケジュール
    def _handle_preview_status(self, url: str, status: QtMultimedia.QMediaPlayer.MediaStatus) -> None:  # 状態変化処理
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        if session.get("recording_path"):  # 録画ファイル再生中の場合
            if status == QtMultimedia.QMediaPlayer.MediaStatus.LoadedMedia:  # 読み込み完了の場合
                self._seek_recording_preview_to_tail(url)  # 末尾へ移動
                return  # 以降の処理を行わない
            if status in (  # 再接続対象の状態
                QtMultimedia.QMediaPlayer.MediaStatus.EndOfMedia,  # 再生終了
                QtMultimedia.QMediaPlayer.MediaStatus.InvalidMedia,  # 無効メディア
            ):  # 状態一覧の終了
                self._refresh_recording_file_preview(url, "EOF")  # 録画プレビューを再読込
            return  # 録画プレビューはここで終了
        if not (self._is_twitch_url(url) or session.get("use_ffmpeg")):  # 対象外の場合
            return  # 何もしない
        if status in (  # 再接続対象の状態
            QtMultimedia.QMediaPlayer.MediaStatus.EndOfMedia,  # 再生終了
            QtMultimedia.QMediaPlayer.MediaStatus.InvalidMedia,  # 無効メディア
        ):  # 状態一覧の終了
            self._schedule_preview_retry(url, "再接続")  # 再接続をスケジュール
    def _schedule_preview_retry(self, url: str, reason: str) -> None:  # プレビュー再接続の予約
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        if session.get("retry_pending"):  # 既に待機中の場合
            return  # 重複を防止
        last_retry = float(session.get("last_retry_at", 0.0))  # 最終リトライ時刻
        now = time.monotonic()  # 現在時刻を取得
        if now - last_retry < 2.5:  # リトライ間隔が短い場合
            return  # 何もしない
        session["retry_pending"] = True  # リトライ待機を設定
        session["last_retry_at"] = now  # 最終リトライ時刻を更新
        session["retry_count"] = int(session.get("retry_count", 0)) + 1  # リトライ回数を更新
        self._append_log(f"プレビュー再接続を試行します: {url}（{reason}）")  # 再接続ログ
        QtCore.QTimer.singleShot(  # 少し待って再接続
            1000,  # 待機時間
            lambda target_url=url: self._retry_preview(target_url),  # 再接続処理を実行
        )  # タイマー設定終了
    def _retry_preview(self, url: str) -> None:  # プレビュー再接続処理
        session = self.preview_sessions.get(url)  # セッションを取得
        if session is None:  # セッションが無い場合
            return  # 何もしない
        session["retry_pending"] = False  # リトライ待機を解除
        if not self._is_twitch_url(url):  # Twitch以外は対象外
            return  # 何もしない
        self._start_preview_for_url(  # プレビューを再起動
            url,  # URL指定
            update_input=False,  # 入力欄を更新しない
            reason="再接続",  # 理由指定
            select_tab=False,  # タブを強制選択しない
        )  # 再接続の終了
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
            if not load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED):  # 自動録画が無効の場合
                self._show_info("配信URLを入力してください。")  # 通知表示
                return  # 処理中断
            twitcasting_urls = self._get_auto_twitcasting_urls()  # ツイキャスURL一覧を取得
            niconico_urls = self._get_auto_niconico_urls()  # ニコ生URL一覧を取得
            tiktok_urls = self._get_auto_tiktok_urls()  # TikTok URL一覧を取得
            youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧を取得
            twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧を取得
            merged_urls = merge_unique_urls(twitcasting_urls, niconico_urls, tiktok_urls)  # 監視URLを結合
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
        output_dir = Path(load_setting_value("output_dir", "recordings", str))  # 出力ディレクトリ取得
        resolved_filename = None  # ファイル名は常に自動命名に任せる
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
        if self._is_twitch_url(url):  # Twitchの場合
            self._start_recording_preview_from_file(  # 録画ファイルでプレビュー
                url,  # URL指定
                output_path,  # 出力パス指定
                "手動録画",  # 理由指定
                True,  # タブを選択
            )  # 録画ファイルプレビューの終了
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
        if self.worker_thread is not None:  # スレッドが存在する場合
            self.worker_thread.quit()  # スレッド終了要求
            self.worker_thread.wait(3000)  # スレッド終了待機
        self.worker = None  # ワーカー参照を破棄
        self.worker_thread = None  # スレッド参照を破棄
        self.stop_event = None  # 停止フラグ参照を破棄
        self.start_button.setEnabled(True)  # 開始ボタン有効化
        self.stop_button.setEnabled(False)  # 停止ボタン無効化
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # 終了時処理
        if not self._allow_quit and load_bool_setting("tray_enabled", False):  # トレイ常駐時の処理
            if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():  # トレイが使える場合
                self._apply_tray_setting(False)  # トレイ表示を反映
                self.hide()  # ウィンドウを非表示
                if isinstance(self.tray_icon, QtWidgets.QSystemTrayIcon):  # トレイアイコンがある場合
                    self.tray_icon.setToolTip("配信録画くん")  # 通知の代わりにツールチップだけ更新
                event.ignore()  # 終了を中断
                return  # 以降の終了処理を行わない
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
        QtWidgets.QApplication.instance().quit()  # アプリケーションを終了
