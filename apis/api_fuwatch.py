# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import re  # 正規表現
from html import unescape  # HTMLエスケープ解除
from typing import Callable, Optional  # 型ヒント補助

import requests  # HTTPリクエスト

from utils.platform_utils import normalize_fuwatch_entry  # ふわっち正規化
from utils.ytdlp_utils import fetch_metadata_with_ytdlp, is_ytdlp_available  # yt-dlp補助

FUWATCH_UA = (  # ふわっち向けユーザーエージェント
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


def fetch_fuwatch_display_name_by_scraping(  # ふわっち表示名取得（スクレイピング）
    entry: str,  # 入力URL
    log_cb: Optional[Callable[[str], None]] = None,  # ログ出力
) -> Optional[str]:  # 表示名を返却
    normalized = normalize_fuwatch_entry(entry)  # 入力を正規化
    if not normalized:  # 正規化失敗時
        if log_cb is not None:  # ログがある場合
            log_cb("ふわっち表示名の取得に失敗しました: 入力が無効です。")  # 失敗ログ
        return None  # 取得不可
    headers = {  # リクエストヘッダー
        "User-Agent": FUWATCH_UA,  # ユーザーエージェント設定
        "Referer": "https://whowatch.tv/",  # リファラ設定
    }
    try:  # 取得処理
        response = requests.get(normalized, headers=headers, timeout=10)  # 配信ページ取得
    except requests.RequestException as exc:  # 通信失敗時
        if log_cb is not None:
            log_cb(f"ふわっち表示名の取得に失敗しました: {exc}")
        return None
    if response.status_code != 200:  # HTTP失敗時
        if log_cb is not None:
            log_cb(f"ふわっち表示名の取得が失敗しました: {response.status_code}")
        return None
    html_text = response.text  # HTML本文
    patterns = [  # 表示名抽出パターン
        r'<a[^>]*class="[^"]*\bname\b[^"]*"[^>]*>([^<]+)</a>',
        r'<a[^>]*href="/profile/[^"]+"[^>]*>([^<]+)</a>',
        r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, re.IGNORECASE)
        if not match:
            continue
        name = unescape(match.group(1)).strip()
        if not name:
            continue
        if "ふわっち" in name:  # サイトタイトルを除外
            continue
        return name
    if is_ytdlp_available():  # yt-dlpにフォールバック
        meta = fetch_metadata_with_ytdlp(normalized, log_cb)
        if isinstance(meta, dict):
            for key in ("uploader", "uploader_id", "creator", "channel", "channel_id", "author", "artist"):
                value = str(meta.get(key, "")).strip()
                if not value:
                    continue
                if "ふわっち" in value:
                    continue
                return value
    if log_cb is not None:
        log_cb("ふわっち表示名の取得に失敗しました: 要素が見つかりません。")
    return None
