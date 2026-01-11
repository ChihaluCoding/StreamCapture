# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import os  # ユーザー情報取得
import plistlib  # macOSのLaunchAgent設定
import subprocess  # launchctl実行
import sys  # OS判定用
from pathlib import Path  # パス操作
from PyQt6 import QtCore, QtGui, QtWidgets  # PyQt6の主要モジュール
from settings_store import load_bool_setting  # 設定読み込み


class MainWindowTrayMixin:  # タスクトレイ/自動起動用ミックスイン
    def _should_minimize_to_tray(self) -> bool:  # 最小化時にトレイへ送るか判定
        if sys.platform != "darwin":  # macOS以外は対象外
            return False  # 何もしない
        if not load_bool_setting("tray_enabled", False):  # トレイ無効なら対象外
            return False  # 何もしない
        return QtWidgets.QSystemTrayIcon.isSystemTrayAvailable()  # トレイ可否を返却

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
        self.tray_recording_actions: list[QtGui.QAction] = []  # 録画中一覧の表示枠
        self.tray_recording_separator = self.tray_menu.addSeparator()  # 区切り線を追加
        show_action = QtGui.QAction("表示", self)  # 表示アクション作成
        show_action.triggered.connect(self._show_from_tray)  # 表示イベント接続
        exit_action = QtGui.QAction("終了", self)  # 終了アクション作成
        exit_action.triggered.connect(self._exit_app)  # 終了イベント接続
        self.tray_menu.addAction(show_action)  # 表示アクションを追加
        self.tray_menu.addSeparator()  # 区切り線を追加
        self.tray_menu.addAction(exit_action)  # 終了アクションを追加
        self.tray_icon.setContextMenu(self.tray_menu)  # トレイメニューを設定
        self.tray_icon.activated.connect(self._on_tray_activated)  # トレイクリックを接続
        self.tray_icon.setToolTip("はいろく！")  # ツールチップを設定
        self._update_tray_menu_recordings()

    def _update_tray_menu_recordings(self) -> None:  # 録画中一覧を更新
        menu = getattr(self, "tray_menu", None)
        if not isinstance(menu, QtWidgets.QMenu):
            return
        separator = getattr(self, "tray_recording_separator", None)
        if not isinstance(separator, QtGui.QAction):
            return
        for action in getattr(self, "tray_recording_actions", []):
            menu.removeAction(action)
        self.tray_recording_actions = []
        items: list[str] = []
        if hasattr(self, "_get_tray_recording_items"):
            items = self._get_tray_recording_items()
        if not items:
            items = ["録画中: なし"]
        insert_before = separator
        for label in items:
            action = QtGui.QAction(label, self)
            action.setEnabled(False)
            menu.insertAction(insert_before, action)
            self.tray_recording_actions.append(action)

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
            if hasattr(self, "_update_tray_tooltip"):
                self._update_tray_tooltip()

    def _show_from_tray(self) -> None:  # トレイからウィンドウを表示
        self.showNormal()  # 通常表示に戻す
        self.activateWindow()  # ウィンドウをアクティブ化
        self.raise_()  # 最前面に移動

    def _on_tray_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:  # トレイクリック処理
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick:  # ダブルクリックの場合
            self._show_from_tray()  # ウィンドウを表示

    def _exit_app(self) -> None:  # アプリ終了処理
        self._allow_quit = True  # 終了許可フラグを設定
        self._force_quit = True  # 録画中でも終了できるよう強制終了フラグを立てる
        if isinstance(self.tray_icon, QtWidgets.QSystemTrayIcon):  # トレイアイコンがある場合
            self.tray_icon.hide()  # トレイアイコンを非表示
        self.close()  # ウィンドウを閉じる

    def changeEvent(self, event: QtCore.QEvent) -> None:  # ウィンドウ状態変更
        QtWidgets.QMainWindow.changeEvent(self, event)  # 既定処理を優先
        if event.type() != QtCore.QEvent.Type.WindowStateChange:  # 対象イベント以外
            return  # 何もしない
        if not self.isMinimized():  # 最小化状態でなければ終了
            return  # 何もしない
        if not self._should_minimize_to_tray():  # トレイへ送らない場合
            return  # 何もしない
        self._apply_tray_setting(False)  # トレイ表示を反映
        self.hide()  # ウィンドウを非表示
        if isinstance(self.tray_icon, QtWidgets.QSystemTrayIcon):  # トレイアイコンがある場合
            if hasattr(self, "_update_tray_tooltip"):
                self._update_tray_tooltip()
            else:
                self.tray_icon.setToolTip("はいろく！")  # ツールチップを更新

    def _apply_startup_setting(self, notify: bool) -> None:  # 自動起動設定を反映
        enabled = load_bool_setting("auto_start_enabled", False)  # 自動起動設定を取得
        if sys.platform == "win32":  # Windowsの場合
            success, message = self._set_windows_startup_enabled(enabled)  # レジストリ設定を反映
        elif sys.platform == "darwin":  # macOSの場合
            success, message = self._set_macos_startup_enabled(enabled)  # LaunchAgentを反映
        else:  # その他OSの場合
            if enabled and notify:  # 有効なのに未対応の場合
                self._show_info("自動起動の設定はWindows/macOSのみ対応しています。")  # 通知を表示
            return  # 処理中断
        if not success:  # 失敗した場合
            self._append_log(f"自動起動の設定に失敗しました: {message}")  # ログ出力
            if notify:  # 通知が必要な場合
                self._show_info(f"自動起動の設定に失敗しました: {message}")  # 通知を表示

    def _build_startup_command(self) -> str:  # 自動起動コマンドを構築
        script_path = Path(__file__).resolve().with_name("gui_app.py")  # 起動スクリプトを特定
        if not script_path.exists():  # スクリプトが見つからない場合
            script_path = Path(sys.argv[0]).resolve()  # 実行時の引数からパスを取得
        return f"\"{sys.executable}\" \"{script_path}\""  # 実行コマンドを返却

    def _build_startup_args(self) -> list[str]:  # macOS向け起動引数
        script_path = Path(__file__).resolve().with_name("gui_app.py")  # 起動スクリプトを特定
        if not script_path.exists():  # スクリプトが見つからない場合
            script_path = Path(sys.argv[0]).resolve()  # 実行時の引数からパスを取得
        return [sys.executable, str(script_path)]  # ProgramArguments形式で返却

    def _set_windows_startup_enabled(self, enabled: bool) -> tuple[bool, str]:  # Windows自動起動設定
        try:  # 例外処理開始
            import winreg  # Windowsレジストリ操作
        except Exception as exc:  # 取り込み失敗時
            return False, f"winregの読み込みに失敗しました: {exc}"  # 失敗を返却
        value_name = "HaishinRokugaKun"  # レジストリ値名を定義
        key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"  # 起動レジストリのパス
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

    def _set_macos_startup_enabled(self, enabled: bool) -> tuple[bool, str]:  # macOS自動起動設定
        label = "jp.kotohasaki.haishinrokugakun"  # LaunchAgentラベル
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"  # plist保存先
        try:
            if enabled:
                plist_path.parent.mkdir(parents=True, exist_ok=True)  # 保存先を作成
                plist_data = {
                    "Label": label,
                    "ProgramArguments": self._build_startup_args(),
                    "RunAtLoad": True,
                    "KeepAlive": False,
                    "StandardOutPath": str(Path.home() / "Library/Logs/haishinrokugakun.out"),
                    "StandardErrorPath": str(Path.home() / "Library/Logs/haishinrokugakun.err"),
                }
                with plist_path.open("wb") as handle:
                    plistlib.dump(plist_data, handle)
                try:
                    uid = str(os.getuid())
                    subprocess.run(
                        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
                        check=False,
                        capture_output=True,
                    )
                except Exception:
                    pass  # 次回ログインで読み込まれるため無視
            else:
                if plist_path.exists():
                    try:
                        uid = str(os.getuid())
                        subprocess.run(
                            ["launchctl", "bootout", f"gui/{uid}", str(plist_path)],
                            check=False,
                            capture_output=True,
                        )
                    except Exception:
                        pass
                    plist_path.unlink()
        except OSError as exc:
            return False, str(exc)
        return True, ""
