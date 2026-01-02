# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
import requests  # HTTP通信

def request_json(  # JSON取得処理
    url: str,  # リクエストURL
    params: dict,  # クエリパラメータ
    headers: dict,  # ヘッダー
    timeout_sec: int,  # タイムアウト秒
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[dict]:  # JSON辞書を返却
    try:  # 例外処理開始
        response = requests.get(  # GETリクエスト実行
            url,  # URL指定
            params=params,  # パラメータ指定
            headers=headers,  # ヘッダー指定
            timeout=timeout_sec,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"API通信に失敗しました: {exc}")  # エラーログを出力
        return None  # 失敗時はNoneを返却
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"API応答が失敗しました: {response.status_code}")  # エラーログ出力
        return None  # 失敗時はNoneを返却
    try:  # JSON解析の例外処理
        return response.json()  # JSONを返却
    except ValueError:  # JSON解析失敗時
        log_cb("API応答のJSON解析に失敗しました。")  # エラーログ出力
        return None  # 失敗時はNoneを返却
