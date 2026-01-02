# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from streamlink import Streamlink  # Streamlink本体

TWITCASTING_BASE_URL = "https://twitcasting.tv/"  # ツイキャスの基準URL
TWITCASTING_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)  # ツイキャス用ユーザーエージェント

def set_streamlink_headers_for_url(session: Streamlink, url: str) -> dict:  # URL別ヘッダー適用
    original_headers = dict(session.http.headers)  # 元のヘッダーを退避
    if "twitcasting.tv" in url:  # ツイキャスURLの場合
        session.http.headers["User-Agent"] = TWITCASTING_UA  # UAを上書き
        session.http.headers["Referer"] = TWITCASTING_BASE_URL  # リファラを追加
    else:  # ツイキャス以外の場合
        if session.http.headers.get("Referer") == TWITCASTING_BASE_URL:  # ツイキャス由来の場合
            session.http.headers.pop("Referer", None)  # リファラを削除
    return original_headers  # 元のヘッダーを返却

def restore_streamlink_headers(session: Streamlink, original_headers: dict) -> None:  # ヘッダー復元
    session.http.headers.clear()  # 現在のヘッダーをクリア
    session.http.headers.update(original_headers)  # 元のヘッダーを復元
