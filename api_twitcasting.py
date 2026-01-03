# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
import html  # HTMLエスケープ解除
import re  # 正規表現処理
import threading  # 排他制御
import time  # 時刻取得
import requests  # HTTP通信
from platform_utils import extract_twitcasting_user_id, normalize_twitcasting_entry  # ユーザーID抽出

from streamlink_utils import TWITCASTING_BASE_URL, TWITCASTING_UA  # ツイキャス向けヘッダー

TWITCASTING_TOKEN_CACHE = {"access_token": "", "expires_at": 0.0}  # ツイキャストークンのキャッシュ
TWITCASTING_TOKEN_LOCK = threading.Lock()  # ツイキャストークンの排他制御

def reset_twitcasting_token_cache() -> None:  # ツイキャストークンのリセット
    with TWITCASTING_TOKEN_LOCK:  # 排他制御を開始
        TWITCASTING_TOKEN_CACHE["access_token"] = ""  # トークンを初期化
        TWITCASTING_TOKEN_CACHE["expires_at"] = 0.0  # 有効期限を初期化

def fetch_twitcasting_token(  # ツイキャストークン取得
    client_id: str,  # クライアントID
    client_secret: str,  # クライアントシークレット
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # トークンを返却
    if not client_id or not client_secret:  # 入力不足の場合
        return None  # 取得失敗
    now = time.time()  # 現在時刻を取得
    with TWITCASTING_TOKEN_LOCK:  # 排他制御を開始
        cached_token = str(TWITCASTING_TOKEN_CACHE.get("access_token", ""))  # 既存トークンを取得
        expires_at = float(TWITCASTING_TOKEN_CACHE.get("expires_at", 0.0))  # 有効期限を取得
        if cached_token and expires_at - 30 > now:  # 期限内の場合
            return cached_token  # キャッシュトークンを返却
    try:  # 例外処理開始
        response = requests.post(  # トークン取得を実行
            "https://apiv2.twitcasting.tv/oauth2/access_token",  # トークンエンドポイント
            data={  # フォームデータ
                "grant_type": "client_credentials",  # クライアントクレデンシャル指定
                "client_id": client_id,  # クライアントID
                "client_secret": client_secret,  # クライアントシークレット
            },  # フォームデータ終了
            timeout=15,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"ツイキャストークン取得に失敗しました: {exc}")  # 失敗ログ
        return None  # 取得失敗
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"ツイキャストークン取得が失敗しました: {response.status_code}")  # 失敗ログ
        return None  # 取得失敗
    try:  # JSON解析の例外処理
        data = response.json()  # JSONを取得
    except ValueError:  # JSON解析失敗時
        log_cb("ツイキャストークン応答の解析に失敗しました。")  # 失敗ログ
        return None  # 取得失敗
    token = str(data.get("access_token", ""))  # トークンを取得
    expires_in_raw = data.get("expires_in", 0)  # 有効期限秒を取得
    try:  # 数値変換の例外処理
        expires_in = int(expires_in_raw)  # 有効期限を数値化
    except (TypeError, ValueError):  # 変換失敗時
        expires_in = 0  # 失敗時は0に設定
    if token:  # トークンが取得できた場合
        safe_expires_in = expires_in if expires_in > 0 else 3600  # 有効期限の安全値
        with TWITCASTING_TOKEN_LOCK:  # 排他制御を開始
            TWITCASTING_TOKEN_CACHE["access_token"] = token  # トークンを保存
            TWITCASTING_TOKEN_CACHE["expires_at"] = now + float(safe_expires_in)  # 期限を保存
        return token  # トークンを返却
    log_cb("ツイキャストークンが空です。")  # 失敗ログ
    return None  # 取得失敗

def request_twitcasting_json(  # ツイキャスAPIのJSON取得
    path: str,  # APIパス
    client_id: str,  # クライアントID
    client_secret: str,  # クライアントシークレット
    params: Optional[dict],  # クエリパラメータ
    log_cb: Callable[[str], None],  # ログコールバック
    allow_retry: bool = True,  # 再試行可否
) -> Optional[dict]:  # JSON辞書を返却
    token = fetch_twitcasting_token(client_id, client_secret, log_cb)  # トークン取得
    if not token:  # トークンが無い場合
        return None  # 取得失敗
    url = f"https://apiv2.twitcasting.tv{path}"  # APIのURLを生成
    headers = {  # リクエストヘッダー
        "X-Api-Version": "2.0",  # APIバージョン指定
        "Authorization": f"Bearer {token}",  # 認証トークン
    }  # ヘッダー定義終了
    try:  # 例外処理開始
        response = requests.get(  # GETリクエスト実行
            url,  # URL指定
            params=params or {},  # パラメータ指定
            headers=headers,  # ヘッダー指定
            timeout=15,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"ツイキャスAPI通信に失敗しました: {exc}")  # 失敗ログ
        return None  # 失敗時はNone
    if response.status_code == 401 and allow_retry:  # トークン期限切れの場合
        reset_twitcasting_token_cache()  # キャッシュをクリア
        return request_twitcasting_json(  # 再試行を実行
            path,  # APIパス
            client_id,  # クライアントID
            client_secret,  # クライアントシークレット
            params,  # パラメータ
            log_cb,  # ログコールバック
            False,  # 再試行禁止で再呼び出し
        )  # 再試行終了
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"ツイキャスAPI応答が失敗しました: {response.status_code}")  # 失敗ログ
        return None  # 失敗時はNone
    try:  # JSON解析の例外処理
        return response.json()  # JSONを返却
    except ValueError:  # JSON解析失敗時
        log_cb("ツイキャスAPI応答のJSON解析に失敗しました。")  # 失敗ログ
        return None  # 失敗時はNone

def fetch_twitcasting_display_name(  # ツイキャス表示名取得
    client_id: str,  # クライアントID
    client_secret: str,  # クライアントシークレット
    user_id: str,  # ユーザーID
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # 表示名を返却
    data = request_twitcasting_json(  # APIを呼び出し
        path=f"/users/{user_id}",  # ユーザー取得API
        client_id=client_id,  # クライアントID
        client_secret=client_secret,  # クライアントシークレット
        params=None,  # パラメータなし
        log_cb=log_cb,  # ログコールバック
    )  # 呼び出し終了
    if data and data.get("user"):  # ユーザーデータがある場合
        name = str(data["user"].get("name", "")).strip()  # 表示名を取得
        return name if name else None  # 表示名を返却
    log_cb(f"ツイキャス表示名の取得に失敗しました: {user_id}")  # 失敗ログ
    return None  # 取得失敗

def fetch_twitcasting_display_name_by_scraping(  # ツイキャス表示名取得（スクレイピング）
    entry: str,  # 入力値
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # 表示名を返却
    normalized = normalize_twitcasting_entry(entry)  # 入力を正規化
    if not normalized:  # 正規化に失敗した場合
        log_cb("ツイキャス表示名の取得に失敗しました: 入力が無効です。")  # 失敗ログ
        return None  # 取得失敗
    headers = {  # ヘッダーを定義
        "User-Agent": TWITCASTING_UA,  # ユーザーエージェント設定
        "Referer": TWITCASTING_BASE_URL,  # リファラ設定
    }  # ヘッダー定義終了
    try:  # 例外処理開始
        response = requests.get(  # GETリクエスト実行
            normalized,  # 正規化URL指定
            headers=headers,  # ヘッダー指定
            timeout=10,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"ツイキャス表示名の取得に失敗しました: {exc}")  # 失敗ログ
        return None  # 取得失敗
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"ツイキャス表示名の取得が失敗しました: {response.status_code}")  # 失敗ログ
        return None  # 取得失敗
    match = re.search(  # 配信者名の要素を検索
        r'<span[^>]*class="tw-live-author__info-username-inner"[^>]*>(.*?)</span>',  # 対象のspan
        response.text,  # HTML本文
        re.DOTALL,  # 改行を含めて検索
    )  # 検索終了
    if not match:  # 要素が見つからない場合
        log_cb("ツイキャス表示名の取得に失敗しました: 要素が見つかりません。")  # 失敗ログ
        return None  # 取得失敗
    raw_name = match.group(1)  # 抽出結果を取得
    cleaned = re.sub(r"<[^>]+>", "", raw_name)  # 余分なタグを除去
    cleaned = html.unescape(cleaned).strip()  # HTMLエスケープを解除して整形
    return cleaned if cleaned else None  # 表示名を返却

def fetch_twitcasting_live_urls(  # ツイキャスライブURL取得
    client_id: str,  # クライアントID
    client_secret: str,  # クライアントシークレット
    entries: list[str],  # 入力一覧
    log_cb: Callable[[str], None],  # ログコールバック
) -> list[str]:  # ライブURL一覧を返却
    live_urls: list[str] = []  # ライブURL一覧
    user_ids: list[str] = []  # ユーザーID一覧
    for entry in entries:  # 入力ごとに処理
        user_id = extract_twitcasting_user_id(entry)  # ユーザーIDを取得
        if user_id and user_id not in user_ids:  # 重複確認
            user_ids.append(user_id)  # ユーザーIDを追加
    if not user_ids:  # ユーザーIDが無い場合
        return live_urls  # 空一覧を返却
    for user_id in user_ids:  # ユーザーIDごとに処理
        data = request_twitcasting_json(  # ライブ情報を取得
            path=f"/users/{user_id}/current_live",  # ライブ情報API
            client_id=client_id,  # クライアントID
            client_secret=client_secret,  # クライアントシークレット
            params=None,  # パラメータなし
            log_cb=log_cb,  # ログコールバック
        )  # 呼び出し終了
        if not data:  # 取得失敗の場合
            continue  # 次のユーザーへ
        is_live = bool(data.get("is_live", False))  # 配信中フラグを取得
        if not is_live:  # 配信中でない場合
            continue  # 次のユーザーへ
        live_url = f"https://twitcasting.tv/{user_id}"  # ライブURLを生成
        if live_url not in live_urls:  # 重複確認
            live_urls.append(live_url)  # ライブURLを追加
    return live_urls  # ライブURL一覧を返却
