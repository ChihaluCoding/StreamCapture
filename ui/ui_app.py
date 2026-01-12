# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import threading  # 停止フラグ制御
from pathlib import Path  # パス操作
from PyQt6 import QtCore, QtGui, QtWidgets  # PyQt6の主要モジュール
from core.workers import AutoCheckWorker, RecorderWorker  # ワーカー処理
from ui.ui_preview import TimeShiftWindow  # プレビュー関連
from ui.ui_mainwindow_menu import MainWindowMenuMixin  # メニュー分割
from ui.ui_mainwindow_tray import MainWindowTrayMixin  # トレイ分割
from ui.ui_mainwindow_layout import MainWindowLayoutMixin  # レイアウト分割
from ui.ui_mainwindow_logging import MainWindowLoggingMixin  # ログ分割
from ui.ui_mainwindow_settings import MainWindowSettingsMixin  # 設定分割
from ui.ui_mainwindow_preview import MainWindowPreviewMixin  # プレビュー分割
from ui.ui_mainwindow_recording import MainWindowRecordingMixin  # 録画分割


class MainWindow(  # メインウィンドウ定義
    QtWidgets.QMainWindow,  # Qtのメインウィンドウ
    MainWindowMenuMixin,  # メニュー機能
    MainWindowTrayMixin,  # トレイ機能
    MainWindowLayoutMixin,  # レイアウト機能
    MainWindowLoggingMixin,  # ログ機能
    MainWindowSettingsMixin,  # 設定機能
    MainWindowPreviewMixin,  # プレビュー機能
    MainWindowRecordingMixin,  # 録画機能
):  # クラス定義終了
    def __init__(self) -> None:  # 初期化処理
        super().__init__()  # 親クラス初期化
        icon_path = Path(__file__).resolve().parents[1] / "icon.png"
        self.setWindowIcon(QtGui.QIcon(str(icon_path)))  # ウィンドウアイコン設定
        self.setWindowTitle("はいろく！")  # ウィンドウタイトル設定
        self.setMinimumSize(900, 680)  # 最小サイズ設定
        self._allow_quit = False  # 終了許可フラグ
        self._force_quit = False  # 強制終了フラグ
        self.tray_icon: QtWidgets.QSystemTrayIcon | None = None  # タスクトレイアイコン参照
        self.tray_menu: QtWidgets.QMenu | None = None  # タスクトレイメニュー参照
        self.worker_thread: QtCore.QThread | None = None  # ワーカースレッド参照
        self.worker: RecorderWorker | None = None  # ワーカー参照
        self.stop_event: threading.Event | None = None  # 停止フラグ参照
        self.manual_recording_url: str | None = None  # 手動録画URL参照
        self.manual_recording_path: Path | None = None  # 手動録画パス参照
        self.auto_sessions: dict[str, dict] = {}  # 自動録画セッション管理
        self.timeshift_windows: list[TimeShiftWindow] = []  # クリップ作成ツールウィンドウ管理
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
        self.channel_display_name_cache: dict[str, str] = {}  # 表示名キャッシュ
        self._build_menu()  # メニューバー構築
        self._build_ui()  # UI構築
        self._setup_tray_icon()  # タスクトレイを初期化
        self._apply_ui_theme()  # UIテーマを適用
        self._load_settings_to_ui()  # 設定をUIへ反映
        self._configure_auto_monitor()  # 自動監視を設定
        self._apply_tray_setting(False)  # タスクトレイ設定を反映
        self._apply_startup_setting(False)  # 自動起動設定を反映
