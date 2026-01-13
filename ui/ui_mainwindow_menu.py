# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from PyQt6 import QtCore, QtGui, QtWidgets  # PyQt6の主要モジュール


class MainWindowMenuMixin:  # メニュー構築用ミックスイン
    def _build_menu(self) -> None:  # メニューバー構築処理
        menu_bar = self.menuBar()  # メニューバー取得
        try:
            menu_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.MenuFont)
        except AttributeError:
            menu_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont)
        menu_bar.setFont(menu_font)
        menu_bar.setStyleSheet("QMenuBar::item { padding: 4px 6px; }")
        file_menu = menu_bar.addMenu("ファイル")  # ファイルメニュー作成
        settings_menu = menu_bar.addMenu("オプション")  # 設定メニュー作成
        help_menu = menu_bar.addMenu("ヘルプ")  # ヘルプメニュー作成
        for menu in (file_menu, settings_menu, help_menu):
            menu.setFont(menu_font)
            menu.setStyleSheet("QMenu { border-radius: 0px; }")
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
        settings_action = QtGui.QAction("環境設定", self)  # 設定アクション作成
        settings_action.triggered.connect(self._open_settings_dialog)  # 設定ダイアログ接続
        settings_menu.addAction(settings_action)  # 設定メニューへ追加
        api_help_action = QtGui.QAction("API / Client IDの設定方法", self)  # APIキー案内アクション作成
        api_help_action.triggered.connect(self._show_api_help)  # APIキー案内ダイアログ接続
        help_menu.addAction(api_help_action)  # ヘルプメニューへ追加
        about_action = QtGui.QAction("このソフトについて", self)  # 情報アクション作成
        about_action.triggered.connect(self._show_about)  # 情報ダイアログ接続
        help_menu.addAction(about_action)  # ヘルプメニューへ追加
