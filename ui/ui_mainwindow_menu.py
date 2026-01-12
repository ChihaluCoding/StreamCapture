# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from PyQt6 import QtCore, QtGui, QtWidgets  # PyQt6の主要モジュール


class MainWindowMenuMixin:  # メニュー構築用ミックスイン
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
