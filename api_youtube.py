# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
import requests  # HTTP通信
from api_common import request_json  # 共通API処理を読み込み
from platform_utils import normalize_youtube_entry  # YouTube正規化を読み込み

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
    if kind in ("user", "handle") and value:  # user/handleの場合
        data = request_json(  # APIを呼び出し
            url="https://www.googleapis.com/youtube/v3/channels",  # チャンネルAPI
            params={"part": "id", "forUsername": value, "key": api_key},  # パラメータ指定
            headers={},  # ヘッダーなし
            timeout_sec=15,  # タイムアウト指定
            log_cb=log_cb,  # ログコールバック指定
        )  # 呼び出し終了
        if data and data.get("items"):  # 結果がある場合
            return data["items"][0]["id"]  # チャンネルIDを返却
    return None  # 取得失敗

def fetch_youtube_oembed_author_name(  # YouTubeのoEmbedからチャンネル名取得
    url: str,  # URL
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # チャンネル名を返却
    try:  # 例外処理開始
        response = requests.get(  # oEmbed取得
            "https://www.youtube.com/oembed",  # oEmbedエンドポイント
            params={"url": url, "format": "json"},  # パラメータ指定
            timeout=10,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"YouTube oEmbedの取得に失敗しました: {exc}")  # 失敗ログ
        return None  # 取得失敗
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"YouTube oEmbedの取得が失敗しました: {response.status_code}")  # 失敗ログ
        return None  # 取得失敗
    try:  # JSON解析の例外処理
        data = response.json()  # JSONを取得
    except ValueError:  # JSON解析失敗時
        log_cb("YouTube oEmbed応答の解析に失敗しました。")  # 失敗ログ
        return None  # 取得失敗
    author_name = str(data.get("author_name", "")).strip()  # チャンネル名を取得
    return author_name if author_name else None  # チャンネル名を返却

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
        title = data["items"][0]["snippet"].get("title", "")  # タイトル取得
        return title if title else None  # タイトルを返却
    log_cb(f"YouTubeチャンネル名の取得に失敗しました: {channel_id}")  # 失敗ログ
    return None  # 取得失敗

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
    if not data or not data.get("items"):  # 結果が無い場合
        log_cb(f"YouTube動画情報の取得に失敗しました: {video_id}")  # 失敗ログ
        return None  # 取得失敗
    channel_id = data["items"][0]["snippet"].get("channelId", "")  # チャンネルID取得
    if not channel_id:  # チャンネルIDが無い場合
        return None  # 取得失敗
    return fetch_youtube_channel_title_by_id(api_key, channel_id, log_cb)  # チャンネル名を取得

def fetch_youtube_live_urls(  # YouTubeライブURL取得
    api_key: str,  # APIキー
    entries: list[str],  # 入力一覧
    log_cb: Callable[[str], None],  # ログコールバック
) -> list[str]:  # ライブURL一覧を返却
    live_urls: list[str] = []  # ライブURL一覧
    for entry in entries:  # 入力ごとに処理
        channel_id = resolve_youtube_channel_id(api_key, entry, log_cb)  # チャンネルID解決
        if not channel_id:  # 解決失敗時
            continue  # 次へ
        data = request_json(  # APIを呼び出し
            url="https://www.googleapis.com/youtube/v3/search",  # Search API
            params={  # パラメータ指定
                "part": "snippet",  # スニペット取得
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
