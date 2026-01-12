# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
import json  # JSON解析
import re  # 正規表現処理
import requests  # HTTP通信
from apis.api_common import request_json  # 共通API処理を読み込み
from utils.platform_utils import normalize_youtube_entry  # YouTube正規化を読み込み

def build_youtube_live_page_url(entry: str) -> Optional[str]:  # YouTubeライブページURL構築
    kind, value = normalize_youtube_entry(entry)  # 入力を正規化
    if kind == "channel" and value:  # チャンネルIDの場合
        return f"https://www.youtube.com/channel/{value}/live"  # チャンネルID用のライブURL
    if kind == "handle" and value:  # ハンドルの場合
        return f"https://www.youtube.com/@{value}/live"  # ハンドル用のライブURL
    if kind == "user" and value:  # user形式の場合
        return f"https://www.youtube.com/user/{value}/live"  # user用のライブURL
    return None  # 対応外はNone

def resolve_youtube_live_url_by_redirect(  # /liveのリダイレクトからライブURL取得
    live_page_url: str,  # /liveページURL
    log_cb: Callable[[str], None],  # ログコールバック
    live_ids_cb: Optional[Callable[[list[str]], None]] = None,  # 検知ライブID通知
) -> Optional[str]:  # ライブURLを返却
    headers = {  # ユーザーエージェント指定
        "User-Agent": "Mozilla/5.0 (compatible; HaishinRecorder/1.0)",  # 軽量なUA文字列
    }  # ヘッダー定義終了
    try:  # 例外処理開始
        response = requests.get(  # /liveへアクセス
            live_page_url,  # /live URL指定
            headers=headers,  # ヘッダー指定
            allow_redirects=True,  # リダイレクトを許可
            timeout=10,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"YouTube /live取得に失敗しました: {exc}")  # 失敗ログ
        return None  # 取得失敗
    if response.status_code >= 400:  # エラーステータスの場合
        log_cb(f"YouTube /live応答が失敗しました: {response.status_code}")  # 失敗ログ
        return None  # 取得失敗
    final_url = response.url or ""  # 最終URLを取得
    history_urls = [resp.url for resp in response.history if resp.url]  # 履歴URL一覧
    try:  # HTML解析の例外処理
        html_text = response.text  # HTML本文取得
    except Exception:  # 取得失敗時
        html_text = ""  # 空文字にする
    if html_text and live_ids_cb is not None:  # HTMLがあり通知が必要な場合
        live_ids = _collect_live_video_ids_from_html(html_text)  # ライブ動画ID一覧を抽出
        if live_ids:  # ライブ動画IDがある場合
            live_ids_cb(live_ids)  # 検知結果を通知
    for candidate in history_urls + [final_url]:  # 履歴と最終URLを確認
        if "watch?v=" in candidate or "youtu.be/" in candidate:  # 動画URL判定
            return candidate  # ライブURLとして返却
    if html_text:  # HTMLがある場合
        match = re.search(  # watch URLを検索
            r"https?://www\\.youtube\\.com/watch\\?v=[\\w-]{6,}",  # watch URLパターン
            html_text,  # HTML本文
        )  # 検索終了
        if match:  # マッチした場合
            return match.group(0)  # ライブURLを返却
        video_match = re.search(  # videoIdを検索
            r'"videoId":"([\\w-]{6,})"',  # videoIdパターン
            html_text,  # HTML本文
        )  # 検索終了
        if video_match:  # マッチした場合
            video_id = video_match.group(1)  # videoIdを取得
            return f"https://www.youtube.com/watch?v={video_id}"  # watch URLを生成
        endpoint_match = re.search(  # watchEndpoint経由の動画IDを検索
            r'"watchEndpoint"\\s*:\\s*\\{[^}]*"videoId"\\s*:\\s*"([\\w-]{6,})"',  # watchEndpointパターン
            html_text,  # HTML本文
            re.DOTALL,  # 改行を含めて検索
        )  # 検索終了
        if endpoint_match:  # マッチした場合
            video_id = endpoint_match.group(1)  # videoIdを取得
            return f"https://www.youtube.com/watch?v={video_id}"  # watch URLを生成
        href_match = re.search(  # /watch?v=... 形式を検索
            r'/watch\\?v=([\\w-]{6,})',  # hrefパターン
            html_text,  # HTML本文
        )  # 検索終了
        if href_match:  # マッチした場合
            video_id = href_match.group(1)  # videoIdを取得
            return f"https://www.youtube.com/watch?v={video_id}"  # watch URLを生成
        player_response = _extract_json_from_marker(  # ytInitialPlayerResponseを抽出
            html_text,  # HTML本文
            "ytInitialPlayerResponse",  # マーカー文字列
        )  # 抽出終了
        live_video_id = _find_live_video_id(player_response)  # ライブ動画IDを探索
        if live_video_id:  # ライブ動画IDがある場合
            return f"https://www.youtube.com/watch?v={live_video_id}"  # watch URLを生成
        initial_data = _extract_json_from_marker(  # ytInitialDataを抽出
            html_text,  # HTML本文
            "ytInitialData",  # マーカー文字列
        )  # 抽出終了
        data_video_id = _find_live_video_id(initial_data)  # ライブ動画IDを探索
        if data_video_id:  # ライブ動画IDがある場合
            return f"https://www.youtube.com/watch?v={data_video_id}"  # watch URLを生成
    return None  # ライブ未検知

def _extract_json_from_marker(text: str, marker: str) -> Optional[dict]:  # マーカー付きJSON抽出
    index = text.find(marker)  # マーカー位置を検索
    if index == -1:  # マーカーが無い場合
        return None  # 抽出失敗
    start = text.find("{", index)  # JSON開始位置を検索
    if start == -1:  # 開始位置が無い場合
        return None  # 抽出失敗
    depth = 0  # 波括弧の深さ
    in_string = False  # 文字列内フラグ
    escape = False  # エスケープ中フラグ
    for offset in range(start, len(text)):  # 文字列を走査
        char = text[offset]  # 文字を取得
        if in_string:  # 文字列内の場合
            if escape:  # エスケープ中の場合
                escape = False  # エスケープを解除
            elif char == "\\\\":  # バックスラッシュの場合
                escape = True  # エスケープ開始
            elif char == '"':  # 文字列終端の場合
                in_string = False  # 文字列内フラグ解除
        else:  # 文字列外の場合
            if char == '"':  # 文字列開始の場合
                in_string = True  # 文字列内フラグ設定
            elif char == "{":  # 開始波括弧の場合
                depth += 1  # 深さを増加
            elif char == "}":  # 終了波括弧の場合
                depth -= 1  # 深さを減少
                if depth == 0:  # JSON終了の場合
                    json_text = text[start : offset + 1]  # JSON文字列を抽出
                    try:  # 例外処理開始
                        return json.loads(json_text)  # JSONを解析して返却
                    except json.JSONDecodeError:  # 解析失敗時
                        return None  # 抽出失敗
    return None  # 抽出失敗

def _find_live_video_id(data: Optional[object]) -> Optional[str]:  # ライブ動画ID探索
    live_ids = _find_live_video_ids(data)  # ライブ動画ID一覧を取得
    return live_ids[0] if live_ids else None  # 先頭のIDを返却

def _find_live_video_ids(data: Optional[object]) -> list[str]:  # ライブ動画ID一覧探索
    if data is None:  # データが無い場合
        return []  # 空一覧を返却
    live_ids: list[str] = []  # ライブ動画ID一覧を初期化
    stack = [data]  # 探索スタックを初期化
    while stack:  # スタックがある間ループ
        current = stack.pop()  # 要素を取得
        if isinstance(current, dict):  # 辞書の場合
            video_id = current.get("videoId")  # videoIdを取得
            is_live_now = current.get("isLiveNow")  # ライブ中フラグを取得
            is_live = current.get("isLive")  # ライブフラグを取得
            live_streamability = current.get("liveStreamability")  # ライブ可否情報を取得
            if video_id and (is_live_now or is_live or live_streamability):  # ライブ判定
                candidate = str(video_id)  # videoIdを文字列化
                if candidate not in live_ids:  # 重複していない場合
                    live_ids.append(candidate)  # ライブ動画IDを追加
            for value in current.values():  # 値を順に追加
                stack.append(value)  # スタックに追加
        elif isinstance(current, list):  # リストの場合
            for value in current:  # 要素を順に追加
                stack.append(value)  # スタックに追加
    return live_ids  # ライブ動画ID一覧を返却

def _collect_live_video_ids_from_html(html_text: str) -> list[str]:  # HTMLからライブ動画ID一覧を抽出
    live_ids: list[str] = []  # ライブ動画ID一覧を初期化
    player_response = _extract_json_from_marker(  # ytInitialPlayerResponseを抽出
        html_text,  # HTML本文
        "ytInitialPlayerResponse",  # マーカー文字列
    )  # 抽出終了
    initial_data = _extract_json_from_marker(  # ytInitialDataを抽出
        html_text,  # HTML本文
        "ytInitialData",  # マーカー文字列
    )  # 抽出終了
    for data in (player_response, initial_data):  # 抽出データを順に確認
        for video_id in _find_live_video_ids(data):  # ライブ動画IDを抽出
            if video_id not in live_ids:  # 重複していない場合
                live_ids.append(video_id)  # ライブ動画IDを追加
    return live_ids  # ライブ動画ID一覧を返却

def fetch_youtube_live_urls_by_live_redirect(  # /liveリダイレクトでライブURL取得
    entries: list[str],  # 入力一覧
    log_cb: Callable[[str], None],  # ログコールバック
    multi_detect_cb: Optional[Callable[[str, list[str]], None]] = None,  # 複数配信検知通知
) -> list[str]:  # ライブURL一覧を返却
    live_urls: list[str] = []  # ライブURL一覧
    for entry in entries:  # 入力ごとに処理
        live_page_url = build_youtube_live_page_url(entry)  # /live URLを構築
        if not live_page_url:  # URL構築失敗時
            log_cb("YouTube /live検出: 対応外の入力形式です。")  # 形式不明ログ
            continue  # 次へ
        detected_live_ids: list[str] = []  # 検知されたライブ動画ID一覧
        resolved = resolve_youtube_live_url_by_redirect(  # リダイレクト解決
            live_page_url,  # /live URL指定
            log_cb=log_cb,  # ログコールバック指定
            live_ids_cb=detected_live_ids.extend,  # 検知ライブIDを蓄積
        )  # 解決終了
        unique_live_ids: list[str] = []  # 重複除去後のライブ動画ID一覧
        for video_id in detected_live_ids:  # 検知IDを順に処理
            if video_id not in unique_live_ids:  # 重複確認
                unique_live_ids.append(video_id)  # 重複を除いて追加
        if len(unique_live_ids) > 1:  # 複数ライブが検知された場合
            log_cb(f"YouTube /live検出: 複数配信を検知 {live_page_url}")  # 複数検知ログ
            if multi_detect_cb is not None:  # 通知先がある場合
                multi_detect_cb(entry, unique_live_ids)  # 複数検知を通知
            continue  # 複数配信時は録画開始しない
        if not resolved and len(unique_live_ids) == 1:  # URL未解決かつIDがある場合
            resolved = f"https://www.youtube.com/watch?v={unique_live_ids[0]}"  # watch URLを生成
        if resolved and resolved not in live_urls:  # ライブURLが取得できた場合
            live_urls.append(resolved)  # ライブURLを追加
            log_cb(f"YouTube /live検出: 配信検知 {live_page_url} -> {resolved}")  # 検知ログ
        elif resolved is None:  # ライブが見つからない場合
            log_cb(f"YouTube /live検出: 配信なし {live_page_url}")  # 配信なしログ
    return live_urls  # ライブURL一覧を返却

def fetch_youtube_live_urls_with_fallback(  # YouTubeライブURL取得（フォールバック付）
    api_key: str,  # APIキー
    entries: list[str],  # 入力一覧
    log_cb: Callable[[str], None],  # ログコールバック
    multi_detect_cb: Optional[Callable[[str, list[str]], None]] = None,  # 複数配信検知通知
) -> list[str]:  # ライブURL一覧を返却
    if not entries:  # 入力が無い場合
        return []  # 空一覧を返却
    if not api_key:  # APIキーが無い場合
        log_cb("自動監視: YouTube APIキーが未設定のため /live 検出を使用します。")  # 代替処理ログ
        return fetch_youtube_live_urls_by_live_redirect(  # /live検出を実行
            entries,  # 入力一覧
            log_cb,  # ログコールバック
            multi_detect_cb=multi_detect_cb,  # 複数検知通知を設定
        )  # /live検出の実行終了
    live_urls = fetch_youtube_live_urls(  # API経由でライブ取得
        api_key=api_key,  # APIキー指定
        entries=entries,  # 配信者一覧指定
        log_cb=log_cb,  # ログ出力
    )  # 取得終了
    if live_urls:  # APIで取得できた場合
        return live_urls  # API結果を返却
    log_cb("自動監視: YouTube APIで取得できなかったため /live 検出を試行します。")  # フォールバックログ
    return fetch_youtube_live_urls_by_live_redirect(entries, log_cb)  # /live検出へフォールバック

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
                "maxResults": 10,  # 複数のライブ枠に対応できる件数を取得
                "key": api_key,  # APIキー
            },  # パラメータ終了
            headers={},  # ヘッダーなし
            timeout_sec=15,  # タイムアウト指定
            log_cb=log_cb,  # ログコールバック指定
        )  # 呼び出し終了
        if not data or not data.get("items"):  # ライブが無い場合
            continue  # 次へ
        for item in data.get("items", []):  # 取得したアイテムを順に処理
            video_id = item.get("id", {}).get("videoId")  # 動画ID取得
            if not video_id:  # 動画IDが無い場合
                continue  # 次へ
            live_url = f"https://www.youtube.com/watch?v={video_id}"  # ライブURL生成
            if live_url not in live_urls:  # 重複確認
                live_urls.append(live_url)  # ライブURLを追加
    return live_urls  # ライブURL一覧を返却
