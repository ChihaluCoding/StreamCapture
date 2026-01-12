# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import csv  # CSV入出力
from pathlib import Path  # パス操作
from PyQt6 import QtMultimedia, QtWidgets  # PyQt6の主要モジュール
from core.config import (  # 定数群
    DEFAULT_AUTO_CHECK_INTERVAL_SEC,  # 自動監視間隔
    DEFAULT_AUTO_ENABLED,  # 自動録画の既定
    DEFAULT_ABEMA_ENTRIES,  # AbemaTV既定
    DEFAULT_BIGO_ENTRIES,  # BIGO LIVE既定
    DEFAULT_FUWATCH_ENTRIES,  # ふわっち既定
    DEFAULT_LIVE17_ENTRIES,  # 17LIVE既定
    DEFAULT_BILIBILI_ENTRIES,  # bilibili既定
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
from utils.platform_utils import (  # 配信サービスURL処理
    normalize_abema_entry,  # AbemaTV正規化
    normalize_17live_entry,  # 17LIVE正規化
    normalize_fuwatch_entry,  # ふわっち正規化
    normalize_niconico_entry,  # ニコ生正規化
    normalize_kick_entry,  # Kick正規化
    normalize_bilibili_entry,  # bilibili正規化
    normalize_openrectv_entry,  # OPENREC.tv正規化
    normalize_radiko_entry,  # radiko正規化
    normalize_bigo_entry,  # BIGO LIVE正規化
    normalize_tiktok_entry,  # TikTok正規化
    normalize_twitcasting_entry,  # ツイキャス正規化
    normalize_twitch_login,  # Twitch正規化
    normalize_youtube_entry,  # YouTube正規化
)
from utils.settings_store import load_bool_setting, load_setting_value, save_setting_value  # 設定入出力
from utils.url_utils import parse_auto_url_list  # URL解析
from ui.ui_settings import SettingsDialog  # 設定ダイアログ


class MainWindowSettingsMixin:  # MainWindowSettingsMixin定義
    def _collect_monitoring_entries(self) -> dict[str, list[str]]:  # 監視設定の収集
        mapping = {  # 監視設定の対応表
            "twitcasting": load_setting_value("twitcasting_entries", "", str),  # ツイキャス
            "niconico": load_setting_value("niconico_entries", "", str),  # ニコ生
            "tiktok": load_setting_value("tiktok_entries", "", str),  # TikTok
            "fuwatch": load_setting_value("fuwatch_entries", "", str),  # ふわっち
            "kick": load_setting_value("kick_entries", "", str),  # Kick
            "abema": load_setting_value("abema_entries", "", str),  # AbemaTV
            "17live": load_setting_value("live17_entries", "", str),  # 17LIVE
            "bigo": load_setting_value("bigo_entries", "", str),  # BIGO LIVE
            "radiko": load_setting_value("radiko_entries", "", str),  # radiko
            "openrectv": load_setting_value("openrectv_entries", "", str),  # OPENREC.tv
            "bilibili": load_setting_value("bilibili_entries", "", str),  # bilibili
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
            "fuwatch": "fuwatch_entries",  # ふわっち
            "kick": "kick_entries",  # Kick
            "abema": "abema_entries",  # AbemaTV
            "17live": "live17_entries",  # 17LIVE
            "bigo": "bigo_entries",  # BIGO LIVE
            "radiko": "radiko_entries",  # radiko
            "openrectv": "openrectv_entries",  # OPENREC.tv
            "bilibili": "bilibili_entries",  # bilibili
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
            "fuwatch": [],  # ふわっち
            "kick": [],  # Kick
            "abema": [],  # AbemaTV
            "17live": [],  # 17LIVE
            "bigo": [],  # BIGO LIVE
            "radiko": [],  # radiko
            "openrectv": [],  # OPENREC.tv
            "bilibili": [],  # bilibili
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
        if hasattr(self, "_apply_log_panel_visibility"):
            self._apply_log_panel_visibility()
    def _open_settings_dialog(self) -> None:  # 設定ダイアログ表示
        dialog = SettingsDialog(self)  # 設定ダイアログ生成
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:  # OK時の処理
            self._load_settings_to_ui()  # 設定を再読み込み
            self._configure_auto_monitor()  # 自動監視を再設定
            self._apply_tray_setting(True)  # タスクトレイ設定を反映
            self._apply_startup_setting(True)  # 自動起動設定を反映
            self._show_info("設定を更新しました。")  # 通知表示
