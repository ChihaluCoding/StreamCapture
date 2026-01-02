# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
import requests  # HTTP通信
from api_common import request_json  # 共通API処理を読み込み
from platform_utils import normalize_twitch_login  # Twitch正規化を読み込み

def fetch_twitch_token(  # Twitchトークン取得
    client_id: str,  # クライアントID
    client_secret: str,  # クライアントシークレット
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # アクセストークンを返却
    try:  # 例外処理開始
        response = requests.post(  # POSTリクエスト実行
            "https://id.twitch.tv/oauth2/token",  # トークンURL
            data={  # フォームデータ
                "client_id": client_id,  # クライアントID
                "client_secret": client_secret,  # クライアントシークレット
                "grant_type": "client_credentials",  # グラントタイプ
            },  # データ終了
            timeout=15,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"Twitchトークン取得に失敗しました: {exc}")  # 失敗ログ出力
        return None  # 失敗時はNone
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"Twitchトークン取得が失敗しました: {response.status_code}")  # 失敗ログ出力
        return None  # 失敗時はNone
    try:  # JSON解析の例外処理
        data = response.json()  # JSON取得
    except ValueError:  # JSON解析失敗時
        log_cb("Twitchトークン応答の解析に失敗しました。")  # 失敗ログ出力
        return None  # 失敗時はNone
    token = data.get("access_token", "")  # トークン取得
    return token or None  # トークンを返却

def fetch_twitch_display_name(  # Twitch表示名取得
    client_id: str,  # クライアントID
    client_secret: str,  # クライアントシークレット
    login: str,  # ログイン名
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # 表示名を返却
    token = fetch_twitch_token(client_id, client_secret, log_cb)  # トークン取得
    if not token:  # トークンが無い場合
        return None  # 取得失敗
    headers = {  # リクエストヘッダー
        "Client-Id": client_id,  # クライアントID
        "Authorization": f"Bearer {token}",  # 認証ヘッダー
    }  # ヘッダー定義終了
    data = request_json(  # APIを呼び出し
        url="https://api.twitch.tv/helix/users",  # ユーザーAPI
        params={"login": login},  # ログイン名指定
        headers=headers,  # ヘッダー指定
        timeout_sec=15,  # タイムアウト指定
        log_cb=log_cb,  # ログコールバック指定
    )  # 呼び出し終了
    if data and data.get("data"):  # 結果がある場合
        display_name = data["data"][0].get("display_name", "")  # 表示名取得
        return display_name if display_name else None  # 表示名を返却
    log_cb(f"Twitch表示名の取得に失敗しました: {login}")  # 失敗ログ
    return None  # 失敗時はNone

def fetch_twitch_live_urls(  # TwitchライブURL取得
    client_id: str,  # クライアントID
    client_secret: str,  # クライアントシークレット
    entries: list[str],  # 入力一覧
    log_cb: Callable[[str], None],  # ログコールバック
) -> list[str]:  # ライブURL一覧を返却
    token = fetch_twitch_token(client_id, client_secret, log_cb)  # トークン取得
    if not token:  # トークンが無い場合
        return []  # 空リストを返却
    logins: list[str] = []  # ログイン名一覧
    for entry in entries:  # 入力ごとに処理
        login = normalize_twitch_login(entry)  # ログイン名を取得
        if login and login not in logins:  # 重複確認
            logins.append(login)  # ログイン名を追加
    if not logins:  # ログイン名が無い場合
        return []  # 空リストを返却
    headers = {  # リクエストヘッダー
        "Client-Id": client_id,  # クライアントID
        "Authorization": f"Bearer {token}",  # 認証ヘッダー
    }  # ヘッダー定義終了
    live_urls: list[str] = []  # ライブURL一覧
    for index in range(0, len(logins), 100):  # 100件ごとに処理
        batch = logins[index : index + 100]  # バッチを作成
        params = [("user_login", login) for login in batch]  # パラメータを生成
        try:  # 例外処理開始
            response = requests.get(  # GETリクエスト実行
                "https://api.twitch.tv/helix/streams",  # Streams API
                params=params,  # パラメータ指定
                headers=headers,  # ヘッダー指定
                timeout=15,  # タイムアウト指定
            )  # レスポンス取得
        except requests.RequestException as exc:  # 通信例外の捕捉
            log_cb(f"Twitchライブ取得に失敗しました: {exc}")  # 失敗ログ
            continue  # 次のバッチへ
        if response.status_code != 200:  # ステータス異常の場合
            log_cb(f"Twitchライブ取得が失敗しました: {response.status_code}")  # 失敗ログ
            continue  # 次のバッチへ
        try:  # JSON解析の例外処理
            data = response.json()  # JSON取得
        except ValueError:  # JSON解析失敗時
            log_cb("Twitchライブ応答の解析に失敗しました。")  # 失敗ログ
            continue  # 次のバッチへ
        for item in data.get("data", []):  # データを処理
            login = item.get("user_login", "").lower()  # ログイン名取得
            if not login:  # ログイン名が無い場合
                continue  # 次へ
            live_url = f"https://www.twitch.tv/{login}"  # ライブURL生成
            if live_url not in live_urls:  # 重複確認
                live_urls.append(live_url)  # ライブURL追加
    return live_urls  # ライブURL一覧を返却
