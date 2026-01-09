# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
import html  # HTMLエスケープ解除
import re  # 正規表現処理
import requests  # HTTP通信
from platform_utils import normalize_17live_entry  # 17LIVE正規化
from ytdlp_utils import fetch_metadata_with_ytdlp  # yt-dlpメタ情報

LIVE17_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)  # 17LIVE向けユーザーエージェント


def _extract_17live_user_id(url: str) -> Optional[str]:  # 17LIVEのユーザーIDを抽出
    match = re.search(r"/live/(\\d+)", url)  # /live/ID形式
    if match:  # 一致した場合
        return match.group(1)  # IDを返却
    match = re.search(r"/profile/r/(\\d+)", url)  # /profile/r/ID形式
    if match:  # 一致した場合
        return match.group(1)  # IDを返却
    return None  # 抽出できない場合


def fetch_17live_display_name_by_scraping(  # 17LIVE表示名取得（スクレイピング）
    entry: str,  # 入力値
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # 表示名を返却
    normalized = normalize_17live_entry(entry)  # 入力を正規化
    if not normalized:  # 正規化に失敗した場合
        log_cb("17LIVE表示名の取得に失敗しました: 入力が無効です。")  # 失敗ログ
        return None  # 取得失敗
    headers = {  # ヘッダーを定義
        "User-Agent": LIVE17_UA,  # ユーザーエージェント設定
        "Referer": "https://17.live/",  # リファラ設定
    }  # ヘッダー定義終了
    try:  # 例外処理開始
        response = requests.get(  # GETリクエスト実行
            normalized,  # 正規化URL指定
            headers=headers,  # ヘッダー指定
            timeout=10,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"17LIVE表示名の取得に失敗しました: {exc}")  # 失敗ログ
        return None  # 取得失敗
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"17LIVE表示名の取得が失敗しました: {response.status_code}")  # 失敗ログ
        meta = fetch_metadata_with_ytdlp(normalized, log_cb)  # yt-dlpでフォールバック
        if meta:  # 取得できた場合
            for key in ("uploader", "creator", "channel", "uploader_id", "channel_id", "user_name"):
                value = str(meta.get(key, "")).strip()
                if value:
                    return value
        return None  # 取得失敗
    user_id = _extract_17live_user_id(normalized)  # ユーザーIDを取得
    patterns = []  # 正規表現候補
    if user_id:  # IDがある場合
        patterns.append(rf'<a[^>]*href="/ja/profile/r/{user_id}"[^>]*>(.*?)</a>')  # ID一致
        patterns.append(rf'<a[^>]*data-track-name="button_user\\.ID"[^>]*href="/ja/profile/r/{user_id}"[^>]*>(.*?)</a>')  # 追跡属性一致
    patterns.append(r'<a[^>]*class="[^"]*VideoLiveUserName__StreamerNameWithLink[^"]*"[^>]*>(.*?)</a>')  # クラス一致
    patterns.append(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"')  # og:title
    pages = [response.text]  # 検索対象HTML
    if user_id:  # IDがある場合
        profile_url = f"https://17.live/ja/profile/r/{user_id}"  # プロフィールURL
        try:  # 例外処理開始
            profile_res = requests.get(  # GETリクエスト実行
                profile_url,  # プロフィールURL
                headers=headers,  # ヘッダー指定
                timeout=10,  # タイムアウト指定
            )  # レスポンス取得
            if profile_res.status_code == 200:  # 成功時
                pages.append(profile_res.text)  # 追加で解析
        except requests.RequestException:  # 通信例外の捕捉
            pass  # 失敗時は無視
    for page in pages:  # ページごとに確認
        for pattern in patterns:  # 候補を順に確認
            match = re.search(pattern, page, re.DOTALL)  # 文字列検索
            if not match:  # 見つからない場合
                continue  # 次の候補へ
            raw_name = match.group(1)  # 抽出結果を取得
            cleaned = re.sub(r"<[^>]+>", "", raw_name)  # 余分なタグを除去
            cleaned = html.unescape(cleaned).strip()  # HTMLエスケープを解除して整形
            if cleaned:  # 名前が取得できた場合
                return cleaned  # 表示名を返却
    json_patterns = [  # JSON内の候補
        r'"displayName"\\s*:\\s*"(.*?)"',  # 表示名
        r'"nickname"\\s*:\\s*"(.*?)"',  # ニックネーム
        r'"userName"\\s*:\\s*"(.*?)"',  # ユーザー名
    ]
    for pattern in json_patterns:  # JSON候補を確認
        match = re.search(pattern, response.text)  # 文字列検索
        if not match:  # 見つからない場合
            continue  # 次へ
        cleaned = html.unescape(match.group(1)).strip()  # エスケープ解除
        if cleaned:  # 名前が取得できた場合
            return cleaned  # 表示名を返却
    meta = fetch_metadata_with_ytdlp(normalized, log_cb)  # yt-dlpでフォールバック
    if meta:  # 取得できた場合
        for key in ("uploader", "creator", "channel", "uploader_id", "channel_id", "user_name"):
            value = str(meta.get(key, "")).strip()
            if value:
                return value
    log_cb("17LIVE表示名の取得に失敗しました: 要素が見つかりません。")  # 失敗ログ
    return None  # 取得失敗
