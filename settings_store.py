# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from PyQt6 import QtCore  # PyQt6の設定モジュール
from config import SETTINGS_APP, SETTINGS_ORG  # 設定定数を読み込み

def get_settings() -> QtCore.QSettings:  # 設定オブジェクト取得
    return QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)  # 設定を返却

def load_setting_value(key: str, default_value, value_type):  # 設定値の読み込み
    settings = get_settings()  # 設定オブジェクトを取得
    value = settings.value(key, default_value)  # 設定値を取得
    try:  # 型変換の例外処理
        return value_type(value)  # 型変換して返却
    except (TypeError, ValueError):  # 変換失敗時の処理
        return default_value  # 既定値を返却

def save_setting_value(key: str, value) -> None:  # 設定値の保存
    settings = get_settings()  # 設定オブジェクトを取得
    settings.setValue(key, value)  # 設定を保存

def to_bool(value: object, default_value: bool = False) -> bool:  # 真偽値の変換
    if isinstance(value, bool):  # 既に真偽値の場合
        return value  # そのまま返却
    if isinstance(value, (int, float)):  # 数値の場合
        return bool(value)  # 数値を真偽値に変換
    if isinstance(value, str):  # 文字列の場合
        text = value.strip().lower()  # 文字列を正規化
        if text in ("1", "true", "yes", "on"):  # 真に該当する場合
            return True  # Trueを返却
        if text in ("0", "false", "no", "off"):  # 偽に該当する場合
            return False  # Falseを返却
    return default_value  # 既定値を返却

def load_bool_setting(key: str, default_value: bool) -> bool:  # 真偽値設定の読み込み
    settings = get_settings()  # 設定オブジェクトを取得
    value = settings.value(key, default_value)  # 設定値を取得
    return to_bool(value, default_value)  # 真偽値へ変換して返却
