# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
import html  # HTMLエスケープ解除
import re  # 正規表現処理
from urllib.parse import urlparse  # URL解析
import requests  # HTTP通信
from platform_utils import normalize_bigo_entry  # BIGO LIVE正規化
from ytdlp_utils import fetch_metadata_with_ytdlp  # yt-dlpメタ情報

BIGO_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)  # BIGO LIVE向けユーザーエージェント


def _extract_bigo_user_id(url: str) -> Optional[str]:  # BIGO LIVEのユーザーIDを抽出
    parsed = urlparse(url)  # URLを解析
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    if "user" in path_parts:  # /user/ID または /ja/user/ID 形式
        idx = path_parts.index("user")
        if len(path_parts) > idx + 1:
            return path_parts[idx + 1]
    if "u" in path_parts:  # /u/ID 形式
        idx = path_parts.index("u")
        if len(path_parts) > idx + 1:
            return path_parts[idx + 1]
    return None  # 抽出できない場合


def fetch_bigo_display_name_by_scraping(  # BIGO LIVE表示名取得（スクレイピング）
    entry: str,  # 入力値
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # 表示名を返却
    normalized = normalize_bigo_entry(entry)  # 入力を正規化
    if not normalized:  # 正規化に失敗した場合
        log_cb("BIGO LIVE表示名の取得に失敗しました: 入力が無効です。")  # 失敗ログ
        return None  # 取得失敗
    headers = {  # ヘッダーを定義
        "User-Agent": BIGO_UA,  # ユーザーエージェント設定
        "Referer": "https://www.bigo.tv/",  # リファラ設定
    }  # ヘッダー定義終了
    try:  # 例外処理開始
        response = requests.get(  # GETリクエスト実行
            normalized,  # 正規化URL指定
            headers=headers,  # ヘッダー指定
            timeout=10,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"BIGO LIVE表示名の取得に失敗しました: {exc}")  # 失敗ログ
        return None  # 取得失敗
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"BIGO LIVE表示名の取得が失敗しました: {response.status_code}")  # 失敗ログ
        meta = fetch_metadata_with_ytdlp(normalized, log_cb)  # yt-dlpでフォールバック
        if meta:  # 取得できた場合
            for key in ("uploader", "creator", "channel", "uploader_id", "channel_id", "user_name"):
                value = str(meta.get(key, "")).strip()
                if value:
                    return value
        return None  # 取得失敗
    user_id = _extract_bigo_user_id(normalized)  # ユーザーIDを取得
    patterns = [  # 正規表現候補
        r'<h1[^>]*class="[^"]*host-nickname[^"]*"[^>]*>\\s*<a[^>]*>(.*?)</a>',  # 提示HTML
        r'<a[^>]*href="/ja/user/\\d+"[^>]*>(.*?)</a>',  # /ja/user/ID形式
        r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"',  # og:title
    ]
    if user_id:  # IDがある場合
        patterns.insert(1, rf'<a[^>]*href="/ja/user/{user_id}"[^>]*>(.*?)</a>')  # ID一致
        patterns.insert(2, rf'<a[^>]*href="/user/{user_id}"[^>]*>(.*?)</a>')  # 英語パス
    for pattern in patterns:  # 候補を順に確認
        match = re.search(pattern, response.text, re.DOTALL)  # 文字列検索
        if not match:  # 見つからない場合
            continue  # 次の候補へ
        raw_name = match.group(1)  # 抽出結果を取得
        cleaned = re.sub(r"<[^>]+>", "", raw_name)  # 余分なタグを除去
        cleaned = html.unescape(cleaned).strip()  # HTMLエスケープを解除して整形
        if cleaned:  # 名前が取得できた場合
            return _normalize_bigo_display_name(cleaned)  # 表示名を返却
    json_patterns = [  # JSON内の候補
        r'"nickname"\\s*:\\s*"(.*?)"',  # ニックネーム
        r'"userName"\\s*:\\s*"(.*?)"',  # ユーザー名
        r'"profileName"\\s*:\\s*"(.*?)"',  # 表示名
    ]
    for pattern in json_patterns:  # JSON候補を確認
        match = re.search(pattern, response.text)  # 文字列検索
        if not match:  # 見つからない場合
            continue  # 次へ
        cleaned = html.unescape(match.group(1)).strip()  # エスケープ解除
        if cleaned:  # 名前が取得できた場合
            return _normalize_bigo_display_name(cleaned)  # 表示名を返却
    meta = fetch_metadata_with_ytdlp(normalized, log_cb)  # yt-dlpでフォールバック
    if meta:  # 取得できた場合
        for key in ("uploader", "creator", "channel", "uploader_id", "channel_id", "user_name"):
            value = str(meta.get(key, "")).strip()
            if value:
                return _normalize_bigo_display_name(value)
    log_cb("BIGO LIVE表示名の取得に失敗しました: 要素が見つかりません。")  # 失敗ログ
    return None  # 取得失敗


def _normalize_bigo_display_name(name: str) -> str:  # BIGO LIVE表示名の整形
    cleaned = name.strip()  # 文字列を正規化
    suffixes = (
        " - BIGO LIVE",
        "- BIGO LIVE",
        "｜BIGO LIVE",
        "| BIGO LIVE",
    )
    for suffix in suffixes:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip()
            break
    return cleaned
