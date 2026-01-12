# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
import html  # HTMLエンティティの復元
import json  # JSON解析
import re  # 文字列の正規化処理
import requests  # HTTP通信
from urllib.parse import urlparse  # URL解析
from utils.platform_utils import normalize_tiktok_entry  # TikTok正規化を読み込み

def decode_json_string(raw_text: str) -> str:  # JSON文字列のデコード
    try:  # 例外処理開始
        return json.loads(f"\"{raw_text}\"")  # JSONとしてデコード
    except json.JSONDecodeError:  # デコード失敗時
        return raw_text  # 元の文字列を返却

def extract_tiktok_nickname(html_text: str) -> Optional[str]:  # TikTok表示名の抽出
    match = re.search(r"\"nickname\":\"([^\"]+)\"", html_text)  # ニックネームを検索
    if not match:  # 該当が無い場合
        return None  # 取得失敗
    nickname = decode_json_string(match.group(1))  # JSONエスケープを復元
    nickname = html.unescape(nickname)  # HTMLエンティティを復元
    nickname = nickname.strip()  # 前後の空白を除去
    return nickname if nickname else None  # ニックネームを返却

def fetch_tiktok_display_name(  # TikTok表示名取得
    url: str,  # 配信URL
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # TikTok表示名を返却
    normalized = normalize_tiktok_entry(url)  # URLを正規化
    if not normalized:  # 正規化失敗時
        return None  # 取得失敗
    parsed = urlparse(normalized)  # URLを解析
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    handle = None  # ハンドルの初期化
    for part in path_parts:  # パス要素を確認
        if part.startswith("@") and len(part) > 1:  # @handle形式の場合
            handle = part[1:]  # ハンドルを取得
            break  # 取得できたら終了
    if handle:  # ハンドルが取得できた場合
        profile_url = f"https://www.tiktok.com/@{handle}"  # プロフィールURLを生成
    else:  # ハンドルが無い場合
        profile_url = normalized  # 正規化URLを使用
    headers = {  # リクエストヘッダー
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",  # UA指定
        "Accept-Language": "ja,en;q=0.8",  # 言語指定
    }  # ヘッダー定義終了
    try:  # 例外処理開始
        response = requests.get(  # GETリクエスト実行
            profile_url,  # プロフィールURL
            headers=headers,  # ヘッダー指定
            timeout=15,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"TikTok表示名の取得に失敗しました: {exc}")  # 失敗ログ
        return None  # 取得失敗
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"TikTok表示名の取得が失敗しました: {response.status_code}")  # 失敗ログ
        return None  # 取得失敗
    nickname = extract_tiktok_nickname(response.text)  # 表示名を抽出
    if nickname:  # 取得できた場合
        return nickname  # 表示名を返却
    log_cb("TikTok表示名の抽出に失敗しました。")  # 失敗ログ
    return None  # 取得失敗
