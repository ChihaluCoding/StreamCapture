# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from PyQt6 import QtCore, QtWidgets  # PyQt6の主要モジュール
from utils.settings_store import load_bool_setting  # 設定読み込み


class MainWindowLoggingMixin:  # MainWindowLoggingMixin定義
    def _apply_log_panel_visibility(self) -> None:  # ログパネル表示切り替え
        visible = load_bool_setting("log_panel_visible", False)
        log_frame = getattr(self, "log_frame", None)
        splitter = getattr(self, "main_splitter", None)
        if isinstance(log_frame, QtWidgets.QWidget):
            log_frame.setVisible(bool(visible))
        if isinstance(splitter, QtWidgets.QSplitter):
            if visible:
                splitter.setSizes([650, 350])
            else:
                splitter.setSizes([1000, 0])
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
    def _append_log(self, message: str) -> None:  # ログ追加処理
        timestamp = QtCore.QDateTime.currentDateTime().toString("HH:mm:ss")  # 時刻のみのタイムスタンプ生成
        category, body = self._format_log_message(message)  # ログを整形
        if not category or not body:  # 空のログの場合
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
            "はいろく！\n配信の録画・自動監視をサポートします。",  # 表示メッセージ
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
