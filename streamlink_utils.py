# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from streamlink import Streamlink  # Streamlink本体
from urllib.parse import urlparse  # URL解析

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

def apply_streamlink_options_for_url(session: Streamlink, url: str) -> None:  # URL別Streamlinkオプション調整
    parsed = urlparse(url)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    if "twitch" not in host and "twitch" not in url:  # Twitch以外の場合
        return  # 何もしない
    session.set_option("twitch-disable-hosting", True)  # ホスティングを回避する
    session.set_option("twitch-low-latency", True)  # 低遅延モードを有効化する
