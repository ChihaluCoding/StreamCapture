#!/usr/bin/env python3  # 実行用のシェバン指定
# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import datetime as dt  # 日時操作
import re  # 文字列の正規化処理
import shutil  # 実行ファイル探索
import subprocess  # 外部コマンド実行
import sys  # アプリ終了コード
import threading  # 停止フラグ制御
import time  # 待機処理
from pathlib import Path  # パス操作
from typing import Callable, Optional  # 型ヒント補助
from urllib.parse import parse_qs, urlparse  # URL解析
import requests  # HTTP通信
from PyQt6 import QtCore, QtGui, QtMultimedia, QtMultimediaWidgets, QtWidgets  # PyQt6の主要モジュール
from streamlink import Streamlink  # Streamlink本体
from streamlink.exceptions import StreamlinkError  # Streamlink例外
DEFAULT_QUALITY = "best"  # 既定の画質指定
DEFAULT_RETRY_COUNT = 5  # 既定の再接続回数
DEFAULT_RETRY_WAIT_SEC = 10  # 既定の再接続待機秒
READ_CHUNK_SIZE = 1024 * 1024  # 読み取りチャンクサイズ
FLUSH_INTERVAL_SEC = 5  # 定期フラッシュ間隔
DEFAULT_AUTO_ENABLED = False  # 自動録画の既定有効状態
DEFAULT_AUTO_CHECK_INTERVAL_SEC = 10  # 自動監視の既定間隔秒
DEFAULT_AUTO_URLS = ""  # 自動監視の既定URL一覧
SETTINGS_ORG = "PF"  # 設定の組織名
SETTINGS_APP = "配信録画くん"  # 設定のアプリ名
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
def parse_auto_url_list(raw_text: str) -> list[str]:  # 自動録画URLの解析
    urls: list[str] = []  # URLリストを初期化
    for line in raw_text.splitlines():  # 行ごとに処理
        candidate = line.strip()  # 空白を除去
        if not candidate:  # 空行の場合
            continue  # スキップ
        if candidate in urls:  # 重複の場合
            continue  # スキップ
        urls.append(candidate)  # URLを追加
    return urls  # URL一覧を返却
def safe_filename_component(text: str) -> str:  # ファイル名の安全化
    cleaned = text.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return "stream"  # 既定名を返却
    replaced = re.sub(r'[\\/:*?"<>|]', "_", cleaned)  # 禁止文字を置換
    replaced = re.sub(r"[\x00-\x1f]", "_", replaced)  # 制御文字を置換
    collapsed = re.sub(r"\s+", " ", replaced).strip()  # 空白を整理
    collapsed = collapsed.rstrip(". ")  # 末尾のドットと空白を削除
    return collapsed if collapsed else "stream"  # 空の場合は既定名
def derive_channel_label(url: str) -> str:  # URLからチャンネル名を推定
    parsed = urlparse(url)  # URLを解析
    host = parsed.netloc  # ホストを取得
    path = parsed.path  # パスを取得
    if not host and path:  # スキーム無しURLの場合
        parts = path.strip("/").split("/")  # パスを分割
        host = parts[0] if parts else ""  # 先頭をホストとして使用
        path = "/".join(parts[1:])  # 残りをパスとして扱う
    host = host.replace("www.", "")  # wwwを除去
    query = parse_qs(parsed.query)  # クエリを解析
    candidate = ""  # 候補文字列を初期化
    if "v" in query and query["v"]:  # 動画IDがある場合
        candidate = query["v"][0]  # 動画IDを使用
    elif path.strip("/"):  # パスに要素がある場合
        candidate = path.strip("/").split("/")[-1]  # 末尾要素を使用
    elif host:  # ホストのみの場合
        candidate = host  # ホストを使用
    if host and candidate and candidate not in host:  # ホストと候補を組み合わせる場合
        label = f"{host}_{candidate}"  # 結合ラベルを生成
    else:  # 結合しない場合
        label = candidate or host or "stream"  # 代替ラベルを生成
    return safe_filename_component(label)  # 安全なラベルを返却
def parse_streamer_filename_map(raw_text: str) -> dict[str, str]:  # 配信者別ファイル名の解析
    mapping: dict[str, str] = {}  # マッピング辞書を初期化
    for line in raw_text.splitlines():  # 行ごとに処理
        entry = line.strip()  # 文字列を正規化
        if not entry:  # 空行の場合
            continue  # スキップ
        if "=" not in entry:  # 区切りが無い場合
            continue  # スキップ
        key, name = entry.split("=", 1)  # キーと名前に分割
        key = key.strip()  # キーを正規化
        name = name.strip()  # 名前を正規化
        if not key or not name:  # キーまたは名前が空の場合
            continue  # スキップ
        label = derive_channel_label(key)  # 配信者ラベルを生成
        mapping[label] = name  # マッピングに追加
    return mapping  # マッピングを返却
def resolve_streamer_filename(url: str, raw_text: str) -> Optional[str]:  # 配信者別ファイル名の取得
    mapping = parse_streamer_filename_map(raw_text)  # マッピングを解析
    label = derive_channel_label(url)  # 配信者ラベルを生成
    filename = mapping.get(label)  # マッピングから取得
    return filename if filename else None  # ファイル名を返却
def build_default_recording_name() -> str:  # 既定ファイル名を生成
    now = dt.datetime.now()  # 現在時刻を取得
    timestamp = (  # 日付時刻を生成
        f"{now.year}年{now.month:02d}月{now.day:02d}日-"  # 年月日を生成
        f"{now.hour:02d}時{now.minute:02d}分{now.second:02d}秒"  # 時分秒を生成
    )  # 日付時刻生成の終了
    return timestamp  # 既定名を返却
def ensure_unique_path(candidate: Path) -> Path:  # パスの重複回避
    if not candidate.exists():  # 未使用の場合
        return candidate  # そのまま返却
    base = candidate.with_suffix("")  # 拡張子を除いたベース
    suffix = candidate.suffix  # 拡張子を取得
    for index in range(1, 1000):  # 連番を探索
        numbered = base.with_name(f"{base.name}_{index}").with_suffix(suffix)  # 連番パス生成
        if not numbered.exists():  # 未使用の場合
            return numbered  # 未使用パスを返却
    return base.with_name(f"{base.name}_overflow").with_suffix(suffix)  # 最終手段のパス
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
def normalize_youtube_entry(entry: str) -> tuple[str, str]:  # YouTube入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return ("", "")  # 空を返却
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    if host:  # URL形式の場合
        if "youtu.be" in host and path_parts:  # 短縮URLの場合
            return ("video", path_parts[0])  # 動画IDとして返却
        if "youtube" in host and path_parts:  # YouTubeドメインの場合
            query = parse_qs(parsed.query)  # クエリを解析
            if "v" in query and query["v"]:  # 動画IDがクエリにある場合
                return ("video", query["v"][0])  # 動画IDとして返却
            if path_parts[0] == "channel" and len(path_parts) >= 2:  # channel形式の場合
                return ("channel", path_parts[1])  # チャンネルIDを返却
            if path_parts[0].startswith("@"):  # ハンドル形式の場合
                return ("handle", path_parts[0][1:])  # ハンドルを返却
            if path_parts[0] == "user" and len(path_parts) >= 2:  # user形式の場合
                return ("user", path_parts[1])  # ユーザー名を返却
            if path_parts[0] == "c" and len(path_parts) >= 2:  # カスタムURLの場合
                return ("handle", path_parts[1])  # ハンドルとして扱う
    if cleaned.startswith("@"):  # ハンドル形式の場合
        return ("handle", cleaned[1:])  # ハンドルを返却
    if cleaned.startswith("UC"):  # チャンネルID形式の場合
        return ("channel", cleaned)  # チャンネルIDを返却
    return ("handle", cleaned)  # それ以外はハンドルとして扱う
def resolve_youtube_channel_id(  # YouTubeチャンネルID解決
    api_key: str,  # APIキー
    entry: str,  # 入力値
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # チャンネルIDを返却
    kind, value = normalize_youtube_entry(entry)  # 入力を正規化
    if kind == "channel" and value:  # チャンネルIDの場合
        return value  # そのまま返却
    if kind == "handle" and value:  # ハンドルの場合
        data = request_json(  # APIを呼び出し
            url="https://www.googleapis.com/youtube/v3/channels",  # チャンネルAPI
            params={"part": "id", "forHandle": value, "key": api_key},  # パラメータ指定
            headers={},  # ヘッダーなし
            timeout_sec=15,  # タイムアウト指定
            log_cb=log_cb,  # ログコールバック指定
        )  # 呼び出し終了
        if data and data.get("items"):  # 結果がある場合
            return data["items"][0]["id"]  # チャンネルIDを返却
        log_cb(f"YouTubeハンドルの解決に失敗しました: {value}")  # 失敗ログ
        return None  # 失敗時はNone
    if kind == "user" and value:  # ユーザー名の場合
        data = request_json(  # APIを呼び出し
            url="https://www.googleapis.com/youtube/v3/channels",  # チャンネルAPI
            params={"part": "id", "forUsername": value, "key": api_key},  # パラメータ指定
            headers={},  # ヘッダーなし
            timeout_sec=15,  # タイムアウト指定
            log_cb=log_cb,  # ログコールバック指定
        )  # 呼び出し終了
        if data and data.get("items"):  # 結果がある場合
            return data["items"][0]["id"]  # チャンネルIDを返却
        log_cb(f"YouTubeユーザー名の解決に失敗しました: {value}")  # 失敗ログ
        return None  # 失敗時はNone
    if kind == "video" and value:  # 動画IDの場合
        data = request_json(  # APIを呼び出し
            url="https://www.googleapis.com/youtube/v3/videos",  # 動画API
            params={"part": "snippet", "id": value, "key": api_key},  # パラメータ指定
            headers={},  # ヘッダーなし
            timeout_sec=15,  # タイムアウト指定
            log_cb=log_cb,  # ログコールバック指定
        )  # 呼び出し終了
        if data and data.get("items"):  # 結果がある場合
            return data["items"][0]["snippet"]["channelId"]  # チャンネルIDを返却
        log_cb(f"YouTube動画IDの解決に失敗しました: {value}")  # 失敗ログ
        return None  # 失敗時はNone
    log_cb(f"YouTube入力が不正です: {entry}")  # 不正入力ログ
    return None  # 失敗時はNone
def fetch_youtube_oembed_author_name(  # YouTubeのoEmbedからチャンネル名取得
    url: str,  # 配信URL
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # チャンネル名を返却
    data = request_json(  # APIを呼び出し
        url="https://www.youtube.com/oembed",  # oEmbed API
        params={"url": url, "format": "json"},  # パラメータ指定
        headers={},  # ヘッダーなし
        timeout_sec=15,  # タイムアウト指定
        log_cb=log_cb,  # ログコールバック指定
    )  # 呼び出し終了
    if data:  # 応答がある場合
        author_name = data.get("author_name", "")  # チャンネル名取得
        return author_name if author_name else None  # チャンネル名を返却
    log_cb("YouTubeのoEmbedからチャンネル名取得に失敗しました。")  # 失敗ログ
    return None  # 失敗時はNone
def fetch_youtube_channel_title_by_id(  # YouTubeチャンネル名取得
    api_key: str,  # APIキー
    channel_id: str,  # チャンネルID
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # チャンネル名を返却
    data = request_json(  # APIを呼び出し
        url="https://www.googleapis.com/youtube/v3/channels",  # チャンネルAPI
        params={"part": "snippet", "id": channel_id, "key": api_key},  # パラメータ指定
        headers={},  # ヘッダーなし
        timeout_sec=15,  # タイムアウト指定
        log_cb=log_cb,  # ログコールバック指定
    )  # 呼び出し終了
    if data and data.get("items"):  # 結果がある場合
        snippet = data["items"][0].get("snippet", {})  # スニペット取得
        title = snippet.get("title", "")  # チャンネル名取得
        return title if title else None  # チャンネル名を返却
    log_cb(f"YouTubeチャンネル名の取得に失敗しました: {channel_id}")  # 失敗ログ
    return None  # 失敗時はNone
def fetch_youtube_channel_title_by_video(  # YouTube動画からチャンネル名取得
    api_key: str,  # APIキー
    video_id: str,  # 動画ID
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # チャンネル名を返却
    data = request_json(  # APIを呼び出し
        url="https://www.googleapis.com/youtube/v3/videos",  # 動画API
        params={"part": "snippet", "id": video_id, "key": api_key},  # パラメータ指定
        headers={},  # ヘッダーなし
        timeout_sec=15,  # タイムアウト指定
        log_cb=log_cb,  # ログコールバック指定
    )  # 呼び出し終了
    if data and data.get("items"):  # 結果がある場合
        snippet = data["items"][0].get("snippet", {})  # スニペット取得
        title = snippet.get("channelTitle", "")  # チャンネル名取得
        return title if title else None  # チャンネル名を返却
    log_cb(f"YouTube動画チャンネル名の取得に失敗しました: {video_id}")  # 失敗ログ
    return None  # 失敗時はNone
def fetch_youtube_live_urls(  # YouTubeライブURL取得
    api_key: str,  # APIキー
    entries: list[str],  # 入力一覧
    log_cb: Callable[[str], None],  # ログコールバック
) -> list[str]:  # ライブURL一覧を返却
    channel_ids: list[str] = []  # チャンネルID一覧
    for entry in entries:  # 入力ごとに処理
        channel_id = resolve_youtube_channel_id(api_key, entry, log_cb)  # チャンネルID解決
        if channel_id and channel_id not in channel_ids:  # 重複確認
            channel_ids.append(channel_id)  # チャンネルIDを追加
    live_urls: list[str] = []  # ライブURL一覧
    for channel_id in channel_ids:  # チャンネルIDごとに処理
        data = request_json(  # APIを呼び出し
            url="https://www.googleapis.com/youtube/v3/search",  # 検索API
            params={  # パラメータ指定
                "part": "id",  # 取得対象
                "channelId": channel_id,  # チャンネルID
                "eventType": "live",  # ライブ指定
                "type": "video",  # 動画指定
                "key": api_key,  # APIキー
            },  # パラメータ終了
            headers={},  # ヘッダーなし
            timeout_sec=15,  # タイムアウト指定
            log_cb=log_cb,  # ログコールバック指定
        )  # 呼び出し終了
        if not data or not data.get("items"):  # ライブが無い場合
            continue  # 次へ
        video_id = data["items"][0]["id"].get("videoId")  # 動画ID取得
        if not video_id:  # 動画IDが無い場合
            continue  # 次へ
        live_url = f"https://www.youtube.com/watch?v={video_id}"  # ライブURL生成
        if live_url not in live_urls:  # 重複確認
            live_urls.append(live_url)  # ライブURLを追加
    return live_urls  # ライブURL一覧を返却
def normalize_twitch_login(entry: str) -> str:  # Twitchログイン名の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return ""  # 空を返却
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    if host and "twitch.tv" in host and path_parts:  # Twitch URLの場合
        return path_parts[0].lower()  # 最初のパス要素を返却
    cleaned = cleaned.lstrip("@")  # 先頭の@を削除
    return cleaned.lower()  # 小文字化して返却
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
def resolve_output_path(  # 出力パス決定
    output_dir: Path,  # 出力ディレクトリ
    filename: Optional[str],  # ファイル名
    url: Optional[str],  # 配信URL
    channel_label: Optional[str] = None,  # 配信者ラベル
) -> Path:  # 出力パスを返却
    if channel_label:  # ラベルが指定されている場合
        safe_label = safe_filename_component(channel_label)  # ラベルを安全化
        output_dir = output_dir / safe_label  # 配信者ごとのフォルダを作成
    elif url:  # URLが指定されている場合
        default_label = derive_channel_label(url)  # 配信者ラベルを生成
        output_dir = output_dir / default_label  # 配信者ごとのフォルダを作成
    output_dir.mkdir(parents=True, exist_ok=True)  # 出力先を確保
    if filename:  # ファイル名が指定された場合
        name = filename  # 指定名を使用
    else:  # 自動生成する場合
        name = build_default_recording_name()  # 既定の録画名を生成
    if "." not in Path(name).name:  # 拡張子が無い場合
        name = f"{name}.ts"  # TS拡張子を補完
    candidate = output_dir / name  # 出力候補パスを生成
    return ensure_unique_path(candidate)  # 重複回避したパスを返却
def build_mp4_output_path(input_path: Path) -> Path:  # MP4出力パス生成
    base = input_path.with_suffix("")  # 拡張子を除いたベース
    candidate = input_path.with_suffix(".mp4")  # 既定のMP4出力パス
    if not candidate.exists():  # 既定パスが未使用の場合
        return candidate  # 既定パスを返却
    for index in range(1, 1000):  # 衝突回避の連番
        candidate = base.with_name(f"{base.name}_{index}").with_suffix(".mp4")  # 連番付きパス
        if not candidate.exists():  # 未使用のパスが見つかった場合
            return candidate  # そのパスを返却
    return base.with_name(f"{base.name}_overflow").with_suffix(".mp4")  # 最終手段のパス
def delete_source_ts(  # 変換後のTS削除処理
    input_path: Path,  # 入力パス
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> None:  # 返り値なし
    if input_path.suffix.lower() != ".ts":  # TS以外は対象外
        return  # 何もしない
    if not input_path.exists():  # 既に削除済みの場合
        return  # 何もしない
    try:  # 削除の例外処理開始
        input_path.unlink()  # TSファイルを削除
        message = f"元のTSファイルを削除しました: {input_path}"  # 削除完了通知
    except OSError as exc:  # 削除失敗時の処理
        message = f"元のTSファイル削除に失敗しました: {exc}"  # 失敗通知
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(message)  # 状態通知
def convert_to_mp4(  # MP4変換処理
    input_path: Path,  # 入力パス
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> Optional[Path]:  # 返り値は出力パス
    if not input_path.exists():  # 入力ファイルが無い場合
        message = f"変換対象ファイルが存在しません: {input_path}"  # 通知文
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換不可
    if input_path.stat().st_size == 0:  # サイズがゼロの場合
        message = f"変換対象ファイルが空です: {input_path}"  # 通知文
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換不可
    ffmpeg_path = shutil.which("ffmpeg")  # ffmpegのパスを探索
    if not ffmpeg_path:  # ffmpegが見つからない場合
        message = "ffmpegが見つかりません。PATHにffmpegを追加してください。"  # 通知文
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換不可
    output_path = build_mp4_output_path(input_path)  # 出力パスを生成
    message = f"MP4変換を開始します: {output_path}"  # 開始通知
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(message)  # 状態通知
    command = [  # ffmpegコマンドの組み立て
        ffmpeg_path,  # ffmpeg実行ファイル
        "-y",  # 既存ファイル上書き
        "-i",  # 入力指定
        str(input_path),  # 入力パス
        "-c",  # コーデック指定
        "copy",  # 再エンコードせずコピー
        "-bsf:a",  # 音声ビットストリームフィルタ指定
        "aac_adtstoasc",  # AACのADTS→ASC変換
        "-movflags",  # MP4最適化フラグ
        "+faststart",  # 先頭へメタデータ移動
        str(output_path),  # 出力パス
    ]  # コマンド定義終了
    result = subprocess.run(  # ffmpeg実行
        command,  # コマンド指定
        capture_output=True,  # 出力を取得
        text=True,  # テキストとして取得
        encoding="utf-8",  # 文字コードを指定
        errors="replace",  # デコード失敗時は置換
        check=False,  # 例外にしない
    )  # 実行結果を取得
    if result.returncode != 0:  # 失敗時の処理
        stderr_text_full = result.stderr.strip()  # 標準エラーの全文を取得
        stderr_tail = stderr_text_full.splitlines()[-5:]  # エラー末尾を抽出
        stderr_text = "\n".join(stderr_tail) if stderr_tail else "詳細不明"  # エラー整形
        retry_message = "再エンコードでMP4変換を再試行します。"  # 再試行通知
        should_retry = (  # 再試行判定
            "Malformed AAC bitstream" in stderr_text_full  # AACエラー判定
            or "aac_adtstoasc" in stderr_text_full  # フィルタ指示判定
            or "av_interleaved_write_frame" in stderr_text_full  # 書き込みエラー判定
        )  # 再試行判定の終了
        if should_retry:  # 再試行が必要な場合
            if output_path.exists():  # 失敗した出力が残っている場合
                output_path.unlink(missing_ok=True)  # 出力ファイルを削除
            if status_cb is not None:  # コールバックが指定されている場合
                status_cb(retry_message)  # 再試行通知
            command_retry = [  # 再試行コマンドの組み立て
                ffmpeg_path,  # ffmpeg実行ファイル
                "-y",  # 既存ファイル上書き
                "-i",  # 入力指定
                str(input_path),  # 入力パス
                "-c:v",  # 映像コーデック指定
                "copy",  # 映像はコピー
                "-c:a",  # 音声コーデック指定
                "aac",  # AACで再エンコード
                "-b:a",  # 音声ビットレート指定
                "192k",  # 192kbps指定
                "-movflags",  # MP4最適化フラグ
                "+faststart",  # 先頭へメタデータ移動
                str(output_path),  # 出力パス
            ]  # 再試行コマンド定義終了
            result_retry = subprocess.run(  # 再試行の実行
                command_retry,  # 再試行コマンド
                capture_output=True,  # 出力を取得
                text=True,  # テキストとして取得
                encoding="utf-8",  # 文字コードを指定
                errors="replace",  # デコード失敗時は置換
                check=False,  # 例外にしない
            )  # 再試行結果を取得
            if result_retry.returncode == 0:  # 再試行成功時
                message = f"MP4変換が完了しました（再エンコード）: {output_path}"  # 完了通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
                delete_source_ts(input_path, status_cb=status_cb)  # 元TSファイルを削除
                return output_path  # 出力パスを返却
            retry_stderr = result_retry.stderr.strip().splitlines()[-5:]  # 再試行エラー末尾
            retry_text = "\n".join(retry_stderr) if retry_stderr else "詳細不明"  # 再試行エラー整形
            message = f"MP4変換に失敗しました（再試行）: {retry_text}"  # 再試行失敗通知
            if status_cb is not None:  # コールバックが指定されている場合
                status_cb(message)  # 状態通知
            return None  # 変換失敗
        message = f"MP4変換に失敗しました: {stderr_text}"  # 失敗通知
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換失敗
    message = f"MP4変換が完了しました: {output_path}"  # 完了通知
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(message)  # 状態通知
    delete_source_ts(input_path, status_cb=status_cb)  # 元TSファイルを削除
    return output_path  # 出力パスを返却
def select_stream(available_streams: dict, quality: str):  # ストリーム選択
    if quality in available_streams:  # 希望画質が存在する場合
        return available_streams[quality]  # その画質を返却
    if DEFAULT_QUALITY in available_streams:  # bestが存在する場合
        return available_streams[DEFAULT_QUALITY]  # bestを返却
    first_key = next(iter(available_streams))  # 最初のキーを取得
    return available_streams[first_key]  # 最初の画質を返却
def should_stop(stop_event: Optional[threading.Event]) -> bool:  # 停止判定
    return stop_event is not None and stop_event.is_set()  # 停止フラグの状態を返却
def open_stream_with_retry(  # リトライ付きでストリームを開く
    session: Streamlink,  # Streamlinkセッション
    url: str,  # 配信URL
    quality: str,  # 画質指定
    retry_count: int,  # リトライ回数
    retry_wait: int,  # リトライ待機秒
    stop_event: Optional[threading.Event],  # 停止フラグ
    status_cb: Optional[Callable[[str], None]],  # 状態通知コールバック
):  # 関数定義終了
    attempt = 0  # 試行回数カウンタ
    while True:  # リトライループ
        if should_stop(stop_event):  # 停止要求の確認
            return None  # 停止時は取得を中断
        attempt += 1  # 試行回数を加算
        try:  # 例外処理開始
            streams = session.streams(url)  # ストリーム一覧を取得
        except StreamlinkError as exc:  # Streamlink例外の捕捉
            message = f"ストリーム取得に失敗しました: {exc}"  # メッセージ生成
            if status_cb is not None:  # コールバックが指定されている場合
                status_cb(message)  # 状態通知
            streams = {}  # 空辞書に退避
        if streams:  # ストリームが取得できた場合
            stream = select_stream(streams, quality)  # ストリームを選択
            return stream  # 選択結果を返却
        if attempt > retry_count:  # リトライ回数を超えた場合
            raise RuntimeError("ストリームを取得できませんでした。")  # 例外送出
        message = f"{retry_wait}秒待機して再試行します（{attempt}/{retry_count}）..."  # 待機通知
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        time.sleep(retry_wait)  # 待機
def is_stream_available(  # ストリーム存在判定
    session: Streamlink,  # Streamlinkセッション
    url: str,  # 配信URL
    status_cb: Optional[Callable[[str], None]],  # 状態通知コールバック
) -> bool:  # 判定結果を返却
    try:  # 例外処理開始
        streams = session.streams(url)  # ストリーム一覧を取得
    except StreamlinkError as exc:  # Streamlink例外の捕捉
        message = f"ストリーム確認に失敗しました: {exc}"  # エラーメッセージ生成
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return False  # 取得失敗時はFalse
    return bool(streams)  # ストリーム有無を返却
def record_stream(  # 録画処理
    session: Streamlink,  # Streamlinkセッション
    url: str,  # 配信URL
    quality: str,  # 画質指定
    output_path: Path,  # 出力パス
    retry_count: int,  # リトライ回数
    retry_wait: int,  # リトライ待機秒
    stop_event: Optional[threading.Event] = None,  # 停止フラグ
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
):  # 関数定義終了
    start_message = f"録画開始: {url}"  # 開始通知メッセージ
    output_message = f"出力先: {output_path}"  # 出力先通知メッセージ
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(start_message)  # 開始通知
        status_cb(output_message)  # 出力先通知
    last_flush_time = time.time()  # 最終フラッシュ時刻
    with output_path.open("ab", buffering=READ_CHUNK_SIZE) as output_file:  # 出力ファイルを開く
        while True:  # 録画ループ
            if should_stop(stop_event):  # 停止要求の確認
                message = "停止要求を受け付けました。録画を終了します。"  # 停止通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
                break  # 録画ループを終了
            try:  # 例外処理開始
                stream = open_stream_with_retry(  # ストリームを取得
                    session=session,  # セッション指定
                    url=url,  # URL指定
                    quality=quality,  # 画質指定
                    retry_count=retry_count,  # リトライ回数
                    retry_wait=retry_wait,  # リトライ待機秒
                    stop_event=stop_event,  # 停止フラグ指定
                    status_cb=status_cb,  # 状態通知コールバック
                )  # ストリーム取得終了
            except RuntimeError as exc:  # 取得失敗を捕捉
                message = f"ストリームを取得できませんでした: {exc}"  # 取得失敗通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
                break  # 録画ループを終了
            if stream is None:  # 停止によりストリームが取得できない場合
                break  # 録画ループを終了
            stream_fd = None  # ストリームファイルを初期化
            stream_ended = False  # 配信終了フラグ
            try:  # 例外処理開始
                stream_fd = stream.open()  # ストリームを開く
                while True:  # 読み取りループ
                    if should_stop(stop_event):  # 停止要求の確認
                        message = "停止要求を受け付けました。ストリームを閉じます。"  # 停止通知
                        if status_cb is not None:  # コールバックが指定されている場合
                            status_cb(message)  # 状態通知
                        break  # 読み取りループを終了
                    data = stream_fd.read(READ_CHUNK_SIZE)  # データ読み取り
                    if not data:  # データが空の場合
                        available = is_stream_available(session, url, status_cb)  # 配信中判定
                        if available:  # 配信が継続している場合
                            message = "ストリームが一時的に切断されました。再接続を試みます。"  # 再接続通知
                            if status_cb is not None:  # コールバックが指定されている場合
                                status_cb(message)  # 状態通知
                        else:  # 配信が終了している場合
                            message = "配信が終了したため録画を停止します。"  # 終了通知
                            if status_cb is not None:  # コールバックが指定されている場合
                                status_cb(message)  # 状態通知
                            stream_ended = True  # 終了フラグを設定
                        break  # 内側ループを抜ける
                    output_file.write(data)  # ファイルへ書き込み
                    now = time.time()  # 現在時刻を取得
                    if now - last_flush_time >= FLUSH_INTERVAL_SEC:  # フラッシュ条件
                        output_file.flush()  # 出力をフラッシュ
                        last_flush_time = now  # 最終フラッシュ時刻を更新
            except StreamlinkError as exc:  # Streamlink例外を捕捉
                message = f"ストリーム読み取り中にエラーが発生しました: {exc}"  # エラー通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
            finally:  # 後始末
                if stream_fd is not None:  # ストリームが開かれている場合
                    stream_fd.close()  # ストリームを閉じる
            if stream_ended:  # 配信終了の場合
                break  # 録画ループを終了
class RecorderWorker(QtCore.QObject):  # 録画ワーカー定義
    log_signal = QtCore.pyqtSignal(str)  # ログ通知シグナル
    finished_signal = QtCore.pyqtSignal(int)  # 終了通知シグナル
    def __init__(  # 初期化処理
        self,  # 自身参照
        url: str,  # 配信URL
        quality: str,  # 画質指定
        output_path: Path,  # 出力パス
        retry_count: int,  # リトライ回数
        retry_wait: int,  # リトライ待機秒
        http_timeout: int,  # HTTPタイムアウト
        stream_timeout: int,  # ストリームタイムアウト
        stop_event: threading.Event,  # 停止フラグ
    ) -> None:  # 返り値なし
        super().__init__()  # 親クラス初期化
        self.url = url  # URLを保存
        self.quality = quality  # 画質を保存
        self.output_path = output_path  # 出力パスを保存
        self.retry_count = retry_count  # リトライ回数を保存
        self.retry_wait = retry_wait  # リトライ待機を保存
        self.http_timeout = http_timeout  # HTTPタイムアウトを保存
        self.stream_timeout = stream_timeout  # ストリームタイムアウトを保存
        self.stop_event = stop_event  # 停止フラグを保存
    def run(self) -> None:  # 録画処理実行
        session = Streamlink()  # Streamlinkセッション生成
        session.set_option("http-timeout", self.http_timeout)  # HTTPタイムアウト設定
        session.set_option("stream-timeout", self.stream_timeout)  # ストリームタイムアウト設定
        def status_cb(message: str) -> None:  # 状態通知用コールバック
            self.log_signal.emit(message)  # ログシグナル送信
        exit_code = 0  # 終了コードの初期化
        try:  # 例外処理開始
            record_stream(  # 録画関数を実行
                session=session,  # セッション指定
                url=self.url,  # URL指定
                quality=self.quality,  # 画質指定
                output_path=self.output_path,  # 出力パス指定
                retry_count=self.retry_count,  # リトライ回数指定
                retry_wait=self.retry_wait,  # リトライ待機指定
                stop_event=self.stop_event,  # 停止フラグ指定
                status_cb=status_cb,  # 状態通知コールバック
            )  # 録画実行終了
        except Exception as exc:  # 予期しない例外を捕捉
            status_cb(f"致命的なエラーが発生しました: {exc}")  # エラーメッセージ通知
            exit_code = 1  # 異常終了コードを設定
        convert_to_mp4(self.output_path, status_cb=status_cb)  # MP4変換を実行
        self.finished_signal.emit(exit_code)  # 終了シグナル送信
class AutoCheckWorker(QtCore.QObject):  # 自動監視ワーカー定義
    log_signal = QtCore.pyqtSignal(str)  # ログ通知シグナル
    finished_signal = QtCore.pyqtSignal(list)  # 完了通知シグナル
    def __init__(  # 初期化処理
        self,  # 自身参照
        youtube_api_key: str,  # YouTube APIキー
        youtube_channels: list[str],  # YouTube配信者一覧
        twitch_client_id: str,  # Twitch Client ID
        twitch_client_secret: str,  # Twitch Client Secret
        twitch_channels: list[str],  # Twitch配信者一覧
        fallback_urls: list[str],  # URL監視のフォールバック一覧
        http_timeout: int,  # HTTPタイムアウト
        stream_timeout: int,  # ストリームタイムアウト
    ) -> None:  # 返り値なし
        super().__init__()  # 親クラス初期化
        self.youtube_api_key = youtube_api_key  # YouTube APIキーを保存
        self.youtube_channels = youtube_channels  # YouTube配信者一覧を保存
        self.twitch_client_id = twitch_client_id  # Twitch Client IDを保存
        self.twitch_client_secret = twitch_client_secret  # Twitch Client Secretを保存
        self.twitch_channels = twitch_channels  # Twitch配信者一覧を保存
        self.fallback_urls = fallback_urls  # フォールバックURL一覧を保存
        self.http_timeout = http_timeout  # HTTPタイムアウトを保存
        self.stream_timeout = stream_timeout  # ストリームタイムアウトを保存
        self.stop_event = threading.Event()  # 停止フラグを生成
    def stop(self) -> None:  # 停止処理
        self.stop_event.set()  # 停止フラグを設定
    def run(self) -> None:  # 監視処理実行
        live_urls: list[str] = []  # ライブURL一覧
        try:  # 例外処理開始
            if self.youtube_channels:  # YouTube配信者がある場合
                if not self.youtube_api_key:  # APIキーが無い場合
                    self.log_signal.emit("自動監視: YouTube APIキーが未設定です。")  # 失敗ログ
                else:  # APIキーがある場合
                    youtube_live = fetch_youtube_live_urls(  # YouTubeライブ取得
                        api_key=self.youtube_api_key,  # APIキー指定
                        entries=self.youtube_channels,  # 配信者一覧指定
                        log_cb=self.log_signal.emit,  # ログ出力
                    )  # 取得終了
                    for live_url in youtube_live:  # ライブURLごとに処理
                        if live_url not in live_urls:  # 重複確認
                            live_urls.append(live_url)  # ライブURLを追加
            if self.twitch_channels:  # Twitch配信者がある場合
                if not self.twitch_client_id or not self.twitch_client_secret:  # APIキーが不足の場合
                    self.log_signal.emit("自動監視: Twitch APIキーが未設定です。")  # 失敗ログ
                else:  # APIキーがある場合
                    twitch_live = fetch_twitch_live_urls(  # Twitchライブ取得
                        client_id=self.twitch_client_id,  # Client ID指定
                        client_secret=self.twitch_client_secret,  # Client Secret指定
                        entries=self.twitch_channels,  # 配信者一覧指定
                        log_cb=self.log_signal.emit,  # ログ出力
                    )  # 取得終了
                    for live_url in twitch_live:  # ライブURLごとに処理
                        if live_url not in live_urls:  # 重複確認
                            live_urls.append(live_url)  # ライブURLを追加
            if self.fallback_urls:  # フォールバックURLがある場合
                session = Streamlink()  # Streamlinkセッション生成
                session.set_option("http-timeout", self.http_timeout)  # HTTPタイムアウト設定
                session.set_option("stream-timeout", self.stream_timeout)  # ストリームタイムアウト設定
                for url in self.fallback_urls:  # URLごとにチェック
                    if self.stop_event.is_set():  # 停止要求の確認
                        break  # ループを中断
                    try:  # 例外処理開始
                        streams = session.streams(url)  # ストリーム一覧を取得
                    except StreamlinkError as exc:  # Streamlink例外の捕捉
                        self.log_signal.emit(f"自動監視: 取得失敗 {url} - {exc}")  # 失敗ログ通知
                        continue  # 次のURLへ
                    if streams:  # ストリームが取得できた場合
                        if url not in live_urls:  # 重複確認
                            live_urls.append(url)  # ライブURLとして追加
        except Exception as exc:  # 予期しない例外の捕捉
            self.log_signal.emit(f"自動監視: 予期しないエラー {exc}")  # 失敗ログ通知
        self.finished_signal.emit(live_urls)  # 完了通知
class SettingsDialog(QtWidgets.QDialog):  # 設定ダイアログ定義
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:  # 初期化処理
        super().__init__(parent)  # 親クラス初期化
        self.setWindowTitle("設定")  # タイトル設定
        self.setMinimumWidth(520)  # 最小幅設定
        self._build_ui()  # UI構築
        self._load_settings()  # 設定読込
    def _build_ui(self) -> None:  # UI構築処理
        layout = QtWidgets.QVBoxLayout(self)  # メインレイアウト作成
        form = QtWidgets.QFormLayout()  # フォームレイアウト作成
        layout.addLayout(form)  # フォーム追加
        self.output_dir_input = QtWidgets.QLineEdit()  # 出力フォルダ入力
        self.output_browse = QtWidgets.QPushButton("参照")  # 参照ボタン
        self.output_browse.clicked.connect(self._browse_output_dir)  # 参照イベント接続
        output_row = QtWidgets.QHBoxLayout()  # 出力行レイアウト
        output_row.addWidget(self.output_dir_input)  # 出力フォルダ入力追加
        output_row.addWidget(self.output_browse)  # 参照ボタン追加
        form.addRow("出力フォルダ", output_row)  # 行追加
        self.quality_input = QtWidgets.QLineEdit()  # 画質入力
        form.addRow("画質", self.quality_input)  # 行追加
        self.retry_count_input = QtWidgets.QSpinBox()  # リトライ回数入力
        self.retry_count_input.setRange(0, 999)  # 範囲設定
        form.addRow("再接続回数", self.retry_count_input)  # 行追加
        self.retry_wait_input = QtWidgets.QSpinBox()  # リトライ待機入力
        self.retry_wait_input.setRange(1, 3600)  # 範囲設定
        form.addRow("再接続待機秒", self.retry_wait_input)  # 行追加
        self.http_timeout_input = QtWidgets.QSpinBox()  # HTTPタイムアウト入力
        self.http_timeout_input.setRange(1, 300)  # 範囲設定
        form.addRow("HTTPタイムアウト秒", self.http_timeout_input)  # 行追加
        self.stream_timeout_input = QtWidgets.QSpinBox()  # ストリームタイムアウト入力
        self.stream_timeout_input.setRange(1, 600)  # 範囲設定
        form.addRow("ストリームタイムアウト秒", self.stream_timeout_input)  # 行追加
        self.preview_volume_input = QtWidgets.QDoubleSpinBox()  # プレビュー音量入力
        self.preview_volume_input.setRange(0.0, 1.0)  # 範囲設定
        self.preview_volume_input.setSingleStep(0.1)  # ステップ設定
        form.addRow("プレビュー音量", self.preview_volume_input)  # 行追加
        self.auto_enabled_input = QtWidgets.QCheckBox("自動録画を有効化")  # 自動録画有効チェック
        form.addRow("自動録画", self.auto_enabled_input)  # 行追加
        self.auto_check_interval_input = QtWidgets.QSpinBox()  # 自動監視間隔入力
        self.auto_check_interval_input.setRange(10, 3600)  # 範囲設定
        form.addRow("監視間隔(秒)", self.auto_check_interval_input)  # 行追加
        self.auto_urls_input = QtWidgets.QPlainTextEdit()  # 自動録画URL入力
        self.auto_urls_input.setPlaceholderText("https://www.twitch.tv/xxxx\nhttps://www.youtube.com/@xxxx/live")  # プレースホルダ設定
        form.addRow("監視対象URL", self.auto_urls_input)  # 行追加
        self.streamer_filename_input = QtWidgets.QPlainTextEdit()  # 配信者別ファイル名入力
        self.streamer_filename_input.setPlaceholderText(  # プレースホルダ設定
            "URLまたは配信者=ファイル名\n例: https://www.twitch.tv/xxxx=2024年01月01日-10時"  # 例示文
        )  # プレースホルダ設定終了
        form.addRow("配信者別ファイル名", self.streamer_filename_input)  # 行追加
        self.youtube_api_key_input = QtWidgets.QLineEdit()  # YouTube APIキー入力
        self.youtube_api_key_input.setPlaceholderText("YouTube Data API v3 キー")  # プレースホルダ設定
        form.addRow("YouTube APIキー", self.youtube_api_key_input)  # 行追加
        self.youtube_channels_input = QtWidgets.QPlainTextEdit()  # YouTube配信者入力
        self.youtube_channels_input.setPlaceholderText("チャンネルID(UC...) または @handle を1行ずつ")  # プレースホルダ設定
        form.addRow("YouTube配信者", self.youtube_channels_input)  # 行追加
        self.twitch_client_id_input = QtWidgets.QLineEdit()  # Twitch Client ID入力
        self.twitch_client_id_input.setPlaceholderText("Twitch Client ID")  # プレースホルダ設定
        form.addRow("Twitch Client ID", self.twitch_client_id_input)  # 行追加
        self.twitch_client_secret_input = QtWidgets.QLineEdit()  # Twitch Client Secret入力
        self.twitch_client_secret_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)  # マスク表示設定
        self.twitch_client_secret_input.setPlaceholderText("Twitch Client Secret")  # プレースホルダ設定
        form.addRow("Twitch Client Secret", self.twitch_client_secret_input)  # 行追加
        self.twitch_channels_input = QtWidgets.QPlainTextEdit()  # Twitch配信者入力
        self.twitch_channels_input.setPlaceholderText("Twitchログイン名を1行ずつ")  # プレースホルダ設定
        form.addRow("Twitch配信者", self.twitch_channels_input)  # 行追加
        button_row = QtWidgets.QHBoxLayout()  # ボタン行レイアウト
        self.save_button = QtWidgets.QPushButton("保存")  # 保存ボタン
        self.cancel_button = QtWidgets.QPushButton("キャンセル")  # キャンセルボタン
        self.save_button.clicked.connect(self._save_settings)  # 保存イベント接続
        self.cancel_button.clicked.connect(self.reject)  # キャンセルイベント接続
        button_row.addStretch(1)  # 余白追加
        button_row.addWidget(self.save_button)  # 保存ボタン追加
        button_row.addWidget(self.cancel_button)  # キャンセルボタン追加
        layout.addLayout(button_row)  # ボタン行追加
    def _load_settings(self) -> None:  # 設定読み込み
        self.output_dir_input.setText(  # 出力フォルダ設定
            load_setting_value("output_dir", "recordings", str)  # 設定値取得
        )  # 設定反映終了
        self.quality_input.setText(  # 画質設定
            load_setting_value("quality", DEFAULT_QUALITY, str)  # 設定値取得
        )  # 設定反映終了
        self.retry_count_input.setValue(  # リトライ回数設定
            load_setting_value("retry_count", DEFAULT_RETRY_COUNT, int)  # 設定値取得
        )  # 設定反映終了
        self.retry_wait_input.setValue(  # リトライ待機設定
            load_setting_value("retry_wait", DEFAULT_RETRY_WAIT_SEC, int)  # 設定値取得
        )  # 設定反映終了
        self.http_timeout_input.setValue(  # HTTPタイムアウト設定
            load_setting_value("http_timeout", 20, int)  # 設定値取得
        )  # 設定反映終了
        self.stream_timeout_input.setValue(  # ストリームタイムアウト設定
            load_setting_value("stream_timeout", 60, int)  # 設定値取得
        )  # 設定反映終了
        self.preview_volume_input.setValue(  # プレビュー音量設定
            load_setting_value("preview_volume", 0.5, float)  # 設定値取得
        )  # 設定反映終了
        self.auto_enabled_input.setChecked(  # 自動録画有効設定
            load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED)  # 設定値取得
        )  # 設定反映終了
        self.auto_check_interval_input.setValue(  # 自動監視間隔設定
            load_setting_value("auto_check_interval", DEFAULT_AUTO_CHECK_INTERVAL_SEC, int)  # 設定値取得
        )  # 設定反映終了
        self.auto_urls_input.setPlainText(  # 自動録画URL設定
            load_setting_value("auto_urls", DEFAULT_AUTO_URLS, str)  # 設定値取得
        )  # 設定反映終了
        self.streamer_filename_input.setPlainText(  # 配信者別ファイル名設定
            load_setting_value("streamer_filenames", "", str)  # 設定値取得
        )  # 設定反映終了
        self.youtube_api_key_input.setText(  # YouTube APIキー設定
            load_setting_value("youtube_api_key", "", str)  # 設定値取得
        )  # 設定反映終了
        self.youtube_channels_input.setPlainText(  # YouTube配信者設定
            load_setting_value("youtube_channels", "", str)  # 設定値取得
        )  # 設定反映終了
        self.twitch_client_id_input.setText(  # Twitch Client ID設定
            load_setting_value("twitch_client_id", "", str)  # 設定値取得
        )  # 設定反映終了
        self.twitch_client_secret_input.setText(  # Twitch Client Secret設定
            load_setting_value("twitch_client_secret", "", str)  # 設定値取得
        )  # 設定反映終了
        self.twitch_channels_input.setPlainText(  # Twitch配信者設定
            load_setting_value("twitch_channels", "", str)  # 設定値取得
        )  # 設定反映終了
    def _save_settings(self) -> None:  # 設定保存
        save_setting_value("output_dir", self.output_dir_input.text().strip())  # 出力フォルダ保存
        save_setting_value("quality", self.quality_input.text().strip() or DEFAULT_QUALITY)  # 画質保存
        save_setting_value("retry_count", int(self.retry_count_input.value()))  # リトライ回数保存
        save_setting_value("retry_wait", int(self.retry_wait_input.value()))  # リトライ待機保存
        save_setting_value("http_timeout", int(self.http_timeout_input.value()))  # HTTPタイムアウト保存
        save_setting_value("stream_timeout", int(self.stream_timeout_input.value()))  # ストリームタイムアウト保存
        save_setting_value("preview_volume", float(self.preview_volume_input.value()))  # プレビュー音量保存
        save_setting_value("auto_enabled", int(self.auto_enabled_input.isChecked()))  # 自動録画有効保存
        save_setting_value("auto_check_interval", int(self.auto_check_interval_input.value()))  # 自動監視間隔保存
        save_setting_value("auto_urls", self.auto_urls_input.toPlainText().strip())  # 自動録画URL保存
        save_setting_value("streamer_filenames", self.streamer_filename_input.toPlainText().strip())  # 配信者別ファイル名保存
        save_setting_value("youtube_api_key", self.youtube_api_key_input.text().strip())  # YouTube APIキー保存
        save_setting_value("youtube_channels", self.youtube_channels_input.toPlainText().strip())  # YouTube配信者保存
        save_setting_value("twitch_client_id", self.twitch_client_id_input.text().strip())  # Twitch Client ID保存
        save_setting_value("twitch_client_secret", self.twitch_client_secret_input.text().strip())  # Twitch Client Secret保存
        save_setting_value("twitch_channels", self.twitch_channels_input.toPlainText().strip())  # Twitch配信者保存
        self.accept()  # ダイアログを閉じる
    def _browse_output_dir(self) -> None:  # 出力フォルダ参照
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "出力フォルダを選択")  # ダイアログ表示
        if directory:  # 選択があった場合
            self.output_dir_input.setText(directory)  # 入力欄に反映
class MainWindow(QtWidgets.QMainWindow):  # メインウィンドウ定義
    def __init__(self) -> None:  # 初期化処理
        super().__init__()  # 親クラス初期化
        self.setWindowTitle("配信録画くん")  # ウィンドウタイトル設定
        self.setMinimumSize(900, 680)  # 最小サイズ設定
        self.worker_thread: QtCore.QThread | None = None  # ワーカースレッド参照
        self.worker: RecorderWorker | None = None  # ワーカー参照
        self.stop_event: threading.Event | None = None  # 停止フラグ参照
        self.manual_recording_url: str | None = None  # 手動録画URL参照
        self.auto_sessions: dict[str, dict] = {}  # 自動録画セッション管理
        self.auto_timer = QtCore.QTimer(self)  # 自動監視タイマー
        self.auto_timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)  # タイマー種別設定
        self.auto_timer.timeout.connect(self._on_auto_timer)  # タイマーイベント接続
        self.auto_check_thread: QtCore.QThread | None = None  # 自動監視スレッド参照
        self.auto_check_worker: AutoCheckWorker | None = None  # 自動監視ワーカー参照
        self.auto_check_in_progress = False  # 自動監視中フラグ
        self.preview_tabs = QtWidgets.QTabWidget()  # プレビュー用タブウィジェット
        self.preview_tabs.setTabsClosable(True)  # タブのクローズを有効化
        self.preview_tabs.tabCloseRequested.connect(self._on_preview_tab_close)  # タブ閉じイベント接続
        self.preview_sessions: dict[str, dict] = {}  # プレビューセッション管理
        self.preview_volume = 0.5  # プレビュー音量の既定値
        self.channel_name_cache: dict[str, str] = {}  # 配信者名のキャッシュ
        self._build_ui()  # UI構築
        self._load_settings_to_ui()  # 設定をUIへ反映
        self._configure_auto_monitor()  # 自動監視を設定
    def _build_ui(self) -> None:  # UI構築処理
        central = QtWidgets.QWidget()  # 中央ウィジェットを生成
        self.setCentralWidget(central)  # 中央ウィジェットを設定
        layout = QtWidgets.QVBoxLayout(central)  # メインレイアウトを作成
        header = QtWidgets.QLabel("配信URLとファイル名を入力し、録画を開始してください。")  # 説明ラベル
        layout.addWidget(header)  # 説明ラベル追加
        form = QtWidgets.QFormLayout()  # 入力フォームレイアウト
        layout.addLayout(form)  # フォームを追加
        self.url_input = QtWidgets.QLineEdit()  # URL入力欄
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")  # プレースホルダ設定
        form.addRow("配信URL", self.url_input)  # フォーム行追加
        self.filename_input = QtWidgets.QLineEdit()  # ファイル名入力
        self.filename_input.setPlaceholderText("省略可")  # プレースホルダ設定
        form.addRow("ファイル名", self.filename_input)  # フォーム行追加
        button_row = QtWidgets.QHBoxLayout()  # ボタン行レイアウト
        self.preview_button = QtWidgets.QPushButton("プレビュー開始")  # プレビューボタン
        self.settings_button = QtWidgets.QPushButton("設定")  # 設定ボタン
        self.start_button = QtWidgets.QPushButton("録画開始")  # 開始ボタン
        self.stop_button = QtWidgets.QPushButton("録画停止")  # 停止ボタン
        self.stop_button.setEnabled(False)  # 停止ボタンを無効化
        self.preview_button.clicked.connect(self._toggle_preview)  # プレビューイベント接続
        self.settings_button.clicked.connect(self._open_settings_dialog)  # 設定ダイアログ表示
        self.start_button.clicked.connect(self._start_recording)  # 開始イベント接続
        self.stop_button.clicked.connect(self._stop_recording)  # 停止イベント接続
        button_row.addWidget(self.preview_button)  # プレビューボタン追加
        button_row.addWidget(self.settings_button)  # 設定ボタン追加
        button_row.addStretch(1)  # 余白追加
        button_row.addWidget(self.start_button)  # 開始ボタン追加
        button_row.addWidget(self.stop_button)  # 停止ボタン追加
        layout.addLayout(button_row)  # ボタン行追加
        content_row = QtWidgets.QHBoxLayout()  # プレビューとログの横並びレイアウト
        preview_group = QtWidgets.QGroupBox("プレビュー")  # プレビュー枠を作成
        preview_layout = QtWidgets.QVBoxLayout(preview_group)  # プレビュー用レイアウト
        self.preview_tabs.setMinimumHeight(260)  # プレビューの最小高さ設定
        preview_layout.addWidget(self.preview_tabs)  # プレビュータブを追加
        preview_group.setStyleSheet("")  # プレビュー背景色をクリア
        log_group = QtWidgets.QGroupBox("ログ")  # ログ枠を作成
        log_layout = QtWidgets.QVBoxLayout(log_group)  # ログ用レイアウト
        self.log_output = QtWidgets.QTextEdit()  # ログ表示欄
        self.log_output.setReadOnly(True)  # 読み取り専用
        self.log_output.setFont(QtGui.QFont("Consolas", 10))  # 等幅フォント指定
        self.log_output.setStyleSheet("")  # ログ背景色をクリア
        log_group.setStyleSheet("")  # ログ枠背景色をクリア
        log_layout.addWidget(self.log_output)  # ログ欄追加
        content_row.addWidget(preview_group, 1)  # プレビュー枠を追加
        content_row.addWidget(log_group, 1)  # ログ枠を追加
        layout.addLayout(content_row)  # 横並び行を追加
    def _append_log(self, message: str) -> None:  # ログ追加処理
        timestamp = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")  # タイムスタンプ生成
        self.log_output.append(f"[{timestamp}] {message}")  # ログを追記
    def _show_info(self, message: str) -> None:  # 通知表示処理
        QtWidgets.QMessageBox.information(self, "情報", message)  # 情報ダイアログ表示
    def _load_settings_to_ui(self) -> None:  # 設定の読み込み
        self.preview_volume = load_setting_value("preview_volume", 0.5, float)  # プレビュー音量を保持
        for session in self.preview_sessions.values():  # 既存プレビューを更新
            audio = session.get("audio")  # 音声出力を取得
            if isinstance(audio, QtMultimedia.QAudioOutput):  # 音声出力がある場合
                audio.setVolume(float(self.preview_volume))  # 音量を反映
    def _open_settings_dialog(self) -> None:  # 設定ダイアログ表示
        dialog = SettingsDialog(self)  # 設定ダイアログ生成
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:  # OK時の処理
            self._load_settings_to_ui()  # 設定を再読み込み
            self._configure_auto_monitor()  # 自動監視を再設定
            self._show_info("設定を更新しました。")  # 通知表示
    def _resolve_stream_url(self, url: str) -> Optional[str]:  # ストリームURLを解決
        quality = load_setting_value("quality", DEFAULT_QUALITY, str)  # 設定から画質取得
        http_timeout = load_setting_value("http_timeout", 20, int)  # 設定からHTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # 設定からストリームタイムアウト取得
        session = Streamlink()  # Streamlinkセッション生成
        session.set_option("http-timeout", int(http_timeout))  # HTTPタイムアウト設定
        session.set_option("stream-timeout", int(stream_timeout))  # ストリームタイムアウト設定
        try:  # 例外処理開始
            streams = session.streams(url)  # ストリーム一覧を取得
        except StreamlinkError as exc:  # Streamlink例外を捕捉
            self._append_log(f"プレビュー用ストリーム取得に失敗しました: {exc}")  # ログ出力
            return None  # 失敗時はNone
        if not streams:  # ストリームが空の場合
            self._append_log("プレビュー用ストリームが見つかりませんでした。")  # ログ出力
            return None  # 失敗時はNone
        stream = select_stream(streams, quality or DEFAULT_QUALITY)  # ストリーム選択
        if hasattr(stream, "to_url"):  # URL変換メソッドがある場合
            return stream.to_url()  # URLを返却
        if hasattr(stream, "url"):  # URL属性がある場合
            return getattr(stream, "url")  # URLを返却
        self._append_log("プレビューに対応したストリームURLを取得できませんでした。")  # ログ出力
        return None  # 失敗時はNone
    def _resolve_channel_display_name(self, url: str) -> Optional[str]:  # 配信者の表示名取得
        parsed = urlparse(url)  # URLを解析
        host = parsed.netloc.lower()  # ホストを取得
        if "youtube" in host or "youtu.be" in host:  # YouTubeの場合
            api_key = load_setting_value("youtube_api_key", "", str).strip()  # APIキー取得
            if not api_key:  # APIキーが無い場合
                if parsed.scheme and parsed.netloc:  # URL形式の場合
                    return fetch_youtube_oembed_author_name(url, self._append_log)  # oEmbedで取得
                return None  # 取得を中止
            kind, value = normalize_youtube_entry(url)  # URLを正規化
            if kind == "video" and value:  # 動画URLの場合
                title = fetch_youtube_channel_title_by_video(api_key, value, self._append_log)  # チャンネル名を取得
                if title:  # チャンネル名が取得できた場合
                    return title  # チャンネル名を返却
            channel_id = resolve_youtube_channel_id(api_key, url, self._append_log)  # チャンネルIDを解決
            if channel_id:  # チャンネルIDがある場合
                title = fetch_youtube_channel_title_by_id(api_key, channel_id, self._append_log)  # チャンネル名を取得
                if title:  # チャンネル名が取得できた場合
                    return title  # チャンネル名を返却
            if parsed.scheme and parsed.netloc:  # URL形式の場合
                return fetch_youtube_oembed_author_name(url, self._append_log)  # oEmbedで取得
            return None  # 取得失敗
        if "twitch" in host or "twitch" in url:  # Twitchの場合
            login = normalize_twitch_login(url)  # ログイン名を取得
            if not login:  # ログイン名が無い場合
                return None  # 取得を中止
            client_id = load_setting_value("twitch_client_id", "", str).strip()  # Client ID取得
            client_secret = load_setting_value("twitch_client_secret", "", str).strip()  # Client Secret取得
            if not client_id or not client_secret:  # APIキーが不足の場合
                return None  # 取得を中止
            title = fetch_twitch_display_name(client_id, client_secret, login, self._append_log)  # 表示名取得
            return title if title else None  # 表示名を返却
        return None  # 対象外の場合
    def _resolve_channel_folder_label(self, url: str) -> str:  # フォルダ用配信者名の取得
        cached = self.channel_name_cache.get(url)  # キャッシュを取得
        if cached:  # キャッシュがある場合
            return cached  # キャッシュを返却
        display_name = self._resolve_channel_display_name(url)  # 表示名を取得
        if display_name:  # 表示名がある場合
            label = safe_filename_component(display_name)  # 表示名を安全化
            self.channel_name_cache[url] = label  # キャッシュに保存
            return label  # 安全化した名前を返却
        parsed = urlparse(url)  # URLを解析
        host = parsed.netloc.lower()  # ホストを取得
        if "twitch" in host or "twitch" in url:  # Twitchの場合
            login = normalize_twitch_login(url)  # ログイン名を取得
            if login:  # ログイン名がある場合
                fallback = safe_filename_component(login)  # ログイン名を安全化
                self.channel_name_cache[url] = fallback  # キャッシュに保存
                return fallback  # ログイン名を返却
        if "youtube" in host or "youtu.be" in host:  # YouTubeの場合
            kind, value = normalize_youtube_entry(url)  # URLを正規化
            if value:  # 値がある場合
                fallback = safe_filename_component(value)  # 値を安全化
                self.channel_name_cache[url] = fallback  # キャッシュに保存
                return fallback  # 値を返却
        fallback = derive_channel_label(url)  # 代替ラベルを生成
        self.channel_name_cache[url] = fallback  # キャッシュに保存
        return fallback  # 代替ラベルを返却
    def _get_current_preview_url(self) -> Optional[str]:  # 現在のプレビューURL取得
        current_widget = self.preview_tabs.currentWidget()  # 現在のタブを取得
        if current_widget is None:  # タブが無い場合
            return None  # Noneを返却
        value = current_widget.property("preview_url")  # URLプロパティ取得
        return str(value) if value else None  # URLを返却
    def _on_preview_tab_close(self, index: int) -> None:  # タブのクローズ処理
        widget = self.preview_tabs.widget(index)  # 対象タブを取得
        if widget is None:  # タブが無い場合
            return  # 何もしない
        url = widget.property("preview_url")  # URLプロパティ取得
        if isinstance(url, str) and url:  # URLがある場合
            self._stop_preview_for_url(url, remove_tab=True)  # プレビュー停止
        else:  # URLが無い場合
            self.preview_tabs.removeTab(index)  # タブを削除
    def _configure_auto_monitor(self) -> None:  # 自動監視の設定
        enabled = load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED)  # 有効設定を取得
        interval = load_setting_value("auto_check_interval", DEFAULT_AUTO_CHECK_INTERVAL_SEC, int)  # 間隔設定を取得
        youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧を取得
        twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧を取得
        urls = self._get_auto_url_list()  # 監視URL一覧を取得
        has_targets = bool(youtube_channels or twitch_channels or urls)  # 監視対象の有無
        if enabled and has_targets:  # 有効かつ監視対象がある場合
            self.auto_timer.setInterval(int(interval) * 1000)  # タイマー間隔を設定
            if not self.auto_timer.isActive():  # タイマーが停止中の場合
                self.auto_timer.start()  # タイマー開始
            self._append_log("自動監視を開始しました。")  # ログ出力
            self._trigger_auto_check_now()  # 起動直後に即時チェック
        else:  # 無効またはURLが無い場合
            if self.auto_timer.isActive():  # タイマーが動作中の場合
                self.auto_timer.stop()  # タイマー停止
            if enabled and not has_targets:  # 有効だが対象無しの場合
                self._append_log("自動監視: 監視対象が未設定のため停止します。")  # ログ出力
            else:  # 無効の場合
                self._append_log("自動監視を停止しました。")  # ログ出力
    def _trigger_auto_check_now(self) -> None:  # 自動監視の即時実行
        if self.auto_check_in_progress:  # 監視中の場合
            return  # 重複チェックを防止
        QtCore.QTimer.singleShot(200, self._on_auto_timer)  # 少し遅延して監視を実行
    def _get_auto_url_list(self) -> list[str]:  # 自動監視URL一覧の取得
        raw_text = load_setting_value("auto_urls", DEFAULT_AUTO_URLS, str)  # 設定文字列を取得
        return parse_auto_url_list(raw_text)  # 解析済みURL一覧を返却
    def _get_auto_youtube_channels(self) -> list[str]:  # YouTube配信者一覧の取得
        raw_text = load_setting_value("youtube_channels", "", str)  # 設定文字列を取得
        return parse_auto_url_list(raw_text)  # 解析済み一覧を返却
    def _get_auto_twitch_channels(self) -> list[str]:  # Twitch配信者一覧の取得
        raw_text = load_setting_value("twitch_channels", "", str)  # 設定文字列を取得
        return parse_auto_url_list(raw_text)  # 解析済み一覧を返却
    def _on_auto_timer(self) -> None:  # 自動監視タイマー処理
        if self.auto_check_in_progress:  # 監視中の場合
            return  # 重複チェックを防止
        if not load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED):  # 無効の場合
            return  # 何もしない
        urls = self._get_auto_url_list()  # 監視URL一覧を取得
        youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧を取得
        twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧を取得
        if not (urls or youtube_channels or twitch_channels):  # 対象が無い場合
            return  # 何もしない
        self._start_auto_check(urls)  # 自動監視を開始
    def _start_auto_check(self, urls: list[str]) -> None:  # 自動監視の開始
        self.auto_check_in_progress = True  # 監視中フラグを設定
        http_timeout = load_setting_value("http_timeout", 20, int)  # HTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # ストリームタイムアウト取得
        youtube_api_key = load_setting_value("youtube_api_key", "", str).strip()  # YouTube APIキー取得
        youtube_channels = self._get_auto_youtube_channels()  # YouTube配信者一覧取得
        twitch_client_id = load_setting_value("twitch_client_id", "", str).strip()  # Twitch Client ID取得
        twitch_client_secret = load_setting_value("twitch_client_secret", "", str).strip()  # Twitch Client Secret取得
        twitch_channels = self._get_auto_twitch_channels()  # Twitch配信者一覧取得
        self.auto_check_thread = QtCore.QThread()  # 監視スレッドを生成
        self.auto_check_worker = AutoCheckWorker(  # 監視ワーカー生成
            youtube_api_key=youtube_api_key,  # YouTube APIキー指定
            youtube_channels=youtube_channels,  # YouTube配信者指定
            twitch_client_id=twitch_client_id,  # Twitch Client ID指定
            twitch_client_secret=twitch_client_secret,  # Twitch Client Secret指定
            twitch_channels=twitch_channels,  # Twitch配信者指定
            fallback_urls=urls,  # フォールバックURL指定
            http_timeout=int(http_timeout),  # HTTPタイムアウト指定
            stream_timeout=int(stream_timeout),  # ストリームタイムアウト指定
        )  # ワーカー生成終了
        self.auto_check_worker.moveToThread(self.auto_check_thread)  # ワーカーをスレッドへ移動
        self.auto_check_thread.started.connect(self.auto_check_worker.run)  # 開始イベント接続
        self.auto_check_worker.log_signal.connect(self._append_log)  # ログ接続
        self.auto_check_worker.finished_signal.connect(self._on_auto_check_finished)  # 完了イベント接続
        self.auto_check_thread.start()  # 監視スレッド開始
    def _on_auto_check_finished(self, live_urls: list[str]) -> None:  # 自動監視完了処理
        for url in live_urls:  # ライブURLごとに処理
            self._start_auto_recording(url)  # 自動録画を開始
        self._cleanup_auto_check_thread()  # 監視スレッドを後始末
        self.auto_check_in_progress = False  # 監視中フラグを解除
    def _cleanup_auto_check_thread(self) -> None:  # 自動監視スレッドの後始末
        if self.auto_check_worker is not None:  # ワーカーが存在する場合
            self.auto_check_worker.deleteLater()  # ワーカーを破棄
        if self.auto_check_thread is not None:  # スレッドが存在する場合
            self.auto_check_thread.quit()  # スレッド終了要求
            self.auto_check_thread.wait(3000)  # スレッド終了待機
            self.auto_check_thread.deleteLater()  # スレッドを破棄
        self.auto_check_worker = None  # ワーカー参照を破棄
        self.auto_check_thread = None  # スレッド参照を破棄
    def _start_auto_recording(self, url: str) -> None:  # 自動録画開始処理
        normalized_url = url.strip()  # URLを正規化
        if not normalized_url:  # URLが空の場合
            return  # 処理中断
        if normalized_url in self.auto_sessions:  # 既に録画中の場合
            return  # 重複開始を防止
        if self.manual_recording_url == normalized_url:  # 手動録画中の場合
            self._append_log(f"自動録画: 手動録画中のためスキップ {normalized_url}")  # ログ出力
            return  # 処理中断
        output_dir = Path(load_setting_value("output_dir", "recordings", str))  # 出力ディレクトリ取得
        filename_map_text = load_setting_value("streamer_filenames", "", str)  # 配信者別ファイル名設定を取得
        auto_filename = resolve_streamer_filename(normalized_url, filename_map_text)  # 配信者別ファイル名を取得
        channel_label = self._resolve_channel_folder_label(normalized_url)  # 配信者名を取得
        output_path = resolve_output_path(  # 出力パス生成
            output_dir,  # 出力ディレクトリ
            auto_filename,  # ファイル名
            normalized_url,  # 配信URL
            channel_label=channel_label,  # 配信者ラベル
        )  # 出力パス生成終了
        quality = load_setting_value("quality", DEFAULT_QUALITY, str)  # 画質設定取得
        retry_count = load_setting_value("retry_count", DEFAULT_RETRY_COUNT, int)  # リトライ回数取得
        retry_wait = load_setting_value("retry_wait", DEFAULT_RETRY_WAIT_SEC, int)  # リトライ待機取得
        http_timeout = load_setting_value("http_timeout", 20, int)  # HTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # ストリームタイムアウト取得
        stop_event = threading.Event()  # 停止フラグ生成
        thread = QtCore.QThread()  # 録画スレッド生成
        worker = RecorderWorker(  # 録画ワーカー生成
            url=normalized_url,  # URL指定
            quality=quality or DEFAULT_QUALITY,  # 画質指定
            output_path=output_path,  # 出力パス指定
            retry_count=int(retry_count),  # リトライ回数指定
            retry_wait=int(retry_wait),  # リトライ待機指定
            http_timeout=int(http_timeout),  # HTTPタイムアウト指定
            stream_timeout=int(stream_timeout),  # ストリームタイムアウト指定
            stop_event=stop_event,  # 停止フラグ指定
        )  # ワーカー生成終了
        worker.moveToThread(thread)  # ワーカーをスレッドへ移動
        thread.started.connect(worker.run)  # 開始イベント接続
        worker.log_signal.connect(self._append_log)  # ログ接続
        worker.finished_signal.connect(  # 終了イベント接続
            lambda exit_code, record_url=normalized_url: self._on_auto_recording_finished(record_url, exit_code)  # 終了処理
        )  # イベント接続の終了
        thread.start()  # 録画スレッド開始
        self.auto_sessions[normalized_url] = {  # セッションを保存
            "thread": thread,  # スレッド参照
            "worker": worker,  # ワーカー参照
            "stop_event": stop_event,  # 停止フラグ参照
            "output_path": output_path,  # 出力パス参照
        }  # セッション保存の終了
        self._append_log(f"自動録画開始: {normalized_url} -> {output_path}")  # ログ出力
        self._start_preview_for_url(  # 自動録画時のプレビュー開始
            normalized_url,  # URL指定
            update_input=False,  # 入力欄を更新しない
            reason="自動録画",  # 理由指定
            select_tab=False,  # タブを強制選択しない
        )  # プレビュー開始の終了
        if not self.stop_button.isEnabled():  # 停止ボタンが無効の場合
            self.stop_button.setEnabled(True)  # 停止ボタンを有効化
    def _on_auto_recording_finished(self, url: str, exit_code: int) -> None:  # 自動録画終了処理
        session = self.auto_sessions.pop(url, None)  # セッションを取得して削除
        if session is not None:  # セッションが存在する場合
            thread = session.get("thread")  # スレッド参照を取得
            worker = session.get("worker")  # ワーカー参照を取得
            if thread is not None:  # スレッドが存在する場合
                thread.quit()  # スレッド終了要求
                thread.wait(3000)  # スレッド終了待機
                thread.deleteLater()  # スレッドを破棄
            if worker is not None:  # ワーカーが存在する場合
                worker.deleteLater()  # ワーカーを破棄
        self._append_log(f"自動録画終了: {url}（終了コード: {exit_code}）")  # ログ出力
        if not self.auto_sessions and self.stop_event is None:  # 録画が無い場合
            self.stop_button.setEnabled(False)  # 停止ボタンを無効化
    def _stop_all_auto_recordings(self) -> None:  # 自動録画の一括停止
        for url, session in list(self.auto_sessions.items()):  # セッションを列挙
            stop_event = session.get("stop_event")  # 停止フラグを取得
            if isinstance(stop_event, threading.Event):  # 停止フラグが存在する場合
                stop_event.set()  # 停止フラグを設定
            thread = session.get("thread")  # スレッド参照を取得
            if isinstance(thread, QtCore.QThread):  # スレッドが存在する場合
                thread.quit()  # スレッド終了要求
                thread.wait(3000)  # スレッド終了待機
                thread.deleteLater()  # スレッドを破棄
        self.auto_sessions.clear()  # セッション一覧をクリア
    def _start_preview(self) -> None:  # プレビュー開始処理
        url = self.url_input.text().strip()  # URL取得
        if not url:  # URLが空の場合
            self._show_info("配信URLを入力してください。")  # 通知表示
            return  # 処理中断
        self._start_preview_for_url(url, update_input=False, reason="手動", select_tab=True)  # URL指定でプレビュー開始
    def _start_preview_for_url(self, url: str, update_input: bool, reason: str, select_tab: bool) -> None:  # URL指定プレビュー開始
        if update_input:  # 入力欄を更新する場合
            self.url_input.setText(url)  # URL入力欄を更新
        stream_url = self._resolve_stream_url(url)  # ストリームURLを取得
        if not stream_url:  # URLが取得できない場合
            return  # 処理中断
        if url in self.preview_sessions:  # 既存プレビューがある場合
            session = self.preview_sessions[url]  # セッションを取得
            player = session["player"]  # プレイヤーを取得
            audio = session.get("audio")  # 音声出力を取得
            if isinstance(audio, QtMultimedia.QAudioOutput):  # 音声出力がある場合
                audio.setVolume(float(self.preview_volume))  # 音量を反映
            if player.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:  # 再生中判定
                player.stop()  # 既存プレビューを停止
            player.setSource(QtCore.QUrl(stream_url))  # プレイヤーにソース設定
            player.play()  # 再生開始
            if select_tab:  # タブを選択する場合
                self.preview_tabs.setCurrentWidget(session["widget"])  # 対象タブを選択
            self.preview_button.setText("プレビュー停止")  # ボタン表示更新
            self._append_log(f"プレビューを更新しました（{reason}）。")  # ログ出力
            return  # 処理終了
        audio = QtMultimedia.QAudioOutput(self)  # 音声出力を生成
        audio.setVolume(float(self.preview_volume))  # 音量を反映
        player = QtMultimedia.QMediaPlayer(self)  # プレイヤーを生成
        player.setAudioOutput(audio)  # 音声出力を関連付け
        video = QtMultimediaWidgets.QVideoWidget()  # 映像表示を生成
        player.setVideoOutput(video)  # 映像出力を関連付け
        container = QtWidgets.QWidget()  # タブ用コンテナ
        container_layout = QtWidgets.QVBoxLayout(container)  # コンテナレイアウト
        container_layout.addWidget(video)  # 映像を配置
        label = derive_channel_label(url)  # ラベルを生成
        tab_index = self.preview_tabs.addTab(container, label)  # タブを追加
        container.setProperty("preview_url", url)  # URLプロパティを保存
        self.preview_sessions[url] = {  # セッションを保存
            "player": player,  # プレイヤー参照
            "audio": audio,  # 音声出力参照
            "video": video,  # 映像参照
            "widget": container,  # コンテナ参照
            "tab_index": tab_index,  # タブインデックス
        }  # セッション保存の終了
        player.setSource(QtCore.QUrl(stream_url))  # プレイヤーにソース設定
        player.play()  # 再生開始
        if select_tab or self.preview_tabs.count() == 1:  # タブ選択条件
            self.preview_tabs.setCurrentWidget(container)  # タブを選択
        self.preview_button.setText("プレビュー停止")  # ボタン表示更新
        self._append_log(f"プレビューを開始しました（{reason}）。")  # ログ出力
    def _stop_preview(self) -> None:  # プレビュー停止処理
        current_url = self._get_current_preview_url()  # 現在のURLを取得
        if not current_url:  # URLが無い場合
            self._append_log("停止するプレビューがありません。")  # ログ出力
            return  # 処理中断
        self._stop_preview_for_url(current_url, remove_tab=True)  # 対象プレビューを停止
    def _toggle_preview(self) -> None:  # プレビュー切替処理
        if self.preview_button.text() == "プレビュー停止":  # 再生中判定
            self._stop_preview()  # 停止処理
        else:  # 停止中の場合
            self._start_preview()  # 開始処理
    def _stop_preview_for_url(self, url: str, remove_tab: bool) -> None:  # URL指定プレビュー停止
        session = self.preview_sessions.pop(url, None)  # セッションを取得して削除
        if session is None:  # セッションが無い場合
            return  # 処理中断
        player = session["player"]  # プレイヤーを取得
        player.stop()  # 再生停止
        player.setSource(QtCore.QUrl())  # ソースをクリア
        widget = session["widget"]  # コンテナを取得
        if remove_tab:  # タブ削除を行う場合
            index = self.preview_tabs.indexOf(widget)  # タブインデックス取得
            if index != -1:  # タブが存在する場合
                self.preview_tabs.removeTab(index)  # タブを削除
            widget.deleteLater()  # ウィジェットを破棄
        self._append_log(f"プレビューを停止しました: {url}")  # ログ出力
        if self.preview_tabs.count() == 0:  # タブが無い場合
            self.preview_button.setText("プレビュー開始")  # ボタン表示更新
    def _stop_all_previews(self) -> None:  # 全プレビュー停止処理
        for url in list(self.preview_sessions.keys()):  # URL一覧を取得
            self._stop_preview_for_url(url, remove_tab=True)  # URLごとに停止
    def _start_recording(self) -> None:  # 録画開始処理
        url = self.url_input.text().strip()  # URL取得
        if not url:  # URLが空の場合
            self._show_info("配信URLを入力してください。")  # 通知表示
            return  # 処理中断
        self.manual_recording_url = url  # 手動録画URLを記録
        output_dir = Path(load_setting_value("output_dir", "recordings", str))  # 出力ディレクトリ取得
        filename = self.filename_input.text().strip()  # ファイル名取得
        if filename:  # ファイル名が指定された場合
            resolved_filename = filename  # 入力ファイル名を使用
        else:  # 入力が空の場合
            filename_map_text = load_setting_value("streamer_filenames", "", str)  # 配信者別ファイル名設定を取得
            resolved_filename = resolve_streamer_filename(url, filename_map_text)  # 配信者別ファイル名を取得
        channel_label = self._resolve_channel_folder_label(url)  # 配信者名を取得
        output_path = resolve_output_path(  # 出力パス生成
            output_dir,  # 出力ディレクトリ
            resolved_filename,  # ファイル名
            url,  # 配信URL
            channel_label=channel_label,  # 配信者ラベル
        )  # 出力パス生成終了
        self._append_log(f"出力パス: {output_path}")  # ログ出力
        quality = load_setting_value("quality", DEFAULT_QUALITY, str)  # 画質設定取得
        retry_count = load_setting_value("retry_count", DEFAULT_RETRY_COUNT, int)  # リトライ回数取得
        retry_wait = load_setting_value("retry_wait", DEFAULT_RETRY_WAIT_SEC, int)  # リトライ待機取得
        http_timeout = load_setting_value("http_timeout", 20, int)  # HTTPタイムアウト取得
        stream_timeout = load_setting_value("stream_timeout", 60, int)  # ストリームタイムアウト取得
        self.stop_event = threading.Event()  # 停止フラグ生成
        self.worker_thread = QtCore.QThread()  # ワーカースレッド生成
        self.worker = RecorderWorker(  # ワーカー生成
            url=url,  # URL指定
            quality=quality or DEFAULT_QUALITY,  # 画質指定
            output_path=output_path,  # 出力パス指定
            retry_count=int(retry_count),  # リトライ回数指定
            retry_wait=int(retry_wait),  # リトライ待機指定
            http_timeout=int(http_timeout),  # HTTPタイムアウト指定
            stream_timeout=int(stream_timeout),  # ストリームタイムアウト指定
            stop_event=self.stop_event,  # 停止フラグ指定
        )  # ワーカー生成終了
        self.worker.moveToThread(self.worker_thread)  # スレッドへ移動
        self.worker_thread.started.connect(self.worker.run)  # 開始イベント接続
        self.worker.log_signal.connect(self._append_log)  # ログ接続
        self.worker.finished_signal.connect(self._on_recording_finished)  # 終了イベント接続
        self.worker_thread.start()  # スレッド開始
        self.start_button.setEnabled(False)  # 開始ボタン無効化
        self.stop_button.setEnabled(True)  # 停止ボタン有効化
    def _stop_current_recordings(self) -> None:  # 現在の録画を停止
        if self.stop_event is not None:  # 手動録画がある場合
            self.stop_event.set()  # 停止フラグを設定
        for session in self.auto_sessions.values():  # 自動録画セッションを確認
            stop_event = session.get("stop_event")  # 停止フラグ取得
            if isinstance(stop_event, threading.Event):  # 停止フラグがある場合
                stop_event.set()  # 停止フラグを設定
    def _stop_recording(self) -> None:  # 録画停止処理
        if self.stop_event is None and not self.auto_sessions:  # 録画が無い場合
            self._append_log("停止対象の録画がありません。")  # ログ出力
            return  # 処理中断
        self._stop_current_recordings()  # 現在の録画を停止
        self._append_log("停止要求を送信しました。")  # ログ出力
        self.stop_button.setEnabled(False)  # 停止ボタン無効化
    def _on_recording_finished(self, exit_code: int) -> None:  # 録画終了処理
        self._append_log(f"録画終了（終了コード: {exit_code}）")  # ログ出力
        self.manual_recording_url = None  # 手動録画URLをクリア
        if self.worker_thread is not None:  # スレッドが存在する場合
            self.worker_thread.quit()  # スレッド終了要求
            self.worker_thread.wait(3000)  # スレッド終了待機
        self.worker = None  # ワーカー参照を破棄
        self.worker_thread = None  # スレッド参照を破棄
        self.stop_event = None  # 停止フラグ参照を破棄
        self.start_button.setEnabled(True)  # 開始ボタン有効化
        self.stop_button.setEnabled(False)  # 停止ボタン無効化
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # 終了時処理
        self._stop_all_previews()  # プレビューを停止
        if self.auto_timer.isActive():  # 自動監視が動作中の場合
            self.auto_timer.stop()  # 自動監視を停止
        if self.auto_check_worker is not None:  # 自動監視ワーカーが存在する場合
            self.auto_check_worker.stop()  # 監視停止を要求
        self._cleanup_auto_check_thread()  # 自動監視スレッドを後始末
        self._stop_all_auto_recordings()  # 自動録画を停止
        if self.stop_event is not None:  # 録画中の場合
            self.stop_event.set()  # 停止フラグを設定
        if self.worker_thread is not None:  # スレッドが存在する場合
            self.worker_thread.quit()  # スレッド終了要求
            self.worker_thread.wait(3000)  # スレッド終了待機
        event.accept()  # 終了を許可
def main() -> int:  # エントリポイント
    app = QtWidgets.QApplication(sys.argv)  # アプリケーション生成
    app.setApplicationName("配信録画くん")  # アプリ名設定
    window = MainWindow()  # メインウィンドウ生成
    window.show()  # ウィンドウ表示
    return app.exec()  # イベントループ開始
if __name__ == "__main__":  # 直接実行時の分岐
    sys.exit(main())  # メイン処理実行
