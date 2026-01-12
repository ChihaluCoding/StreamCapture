# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
import html  # HTMLエスケープ解除
import json  # JSON解析
import re  # 正規表現処理
import requests  # HTTP通信
from utils.platform_utils import normalize_niconico_entry  # ニコ生URL正規化

NICONICO_UA = (  # ニコ生向けユーザーエージェント
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "  # macOS向けUA
    "AppleWebKit/537.36 (KHTML, like Gecko) "  # WebKit互換情報
    "Chrome/122.0.0.0 Safari/537.36"  # Chrome互換情報
)  # ユーザーエージェント定義終了

def fetch_niconico_display_name_by_scraping(  # ニコ生表示名取得（スクレイピング）
    entry: str,  # 入力値
    log_cb: Callable[[str], None],  # ログコールバック
) -> Optional[str]:  # 表示名を返却
    normalized = normalize_niconico_entry(entry)  # 入力を正規化
    if not normalized:  # 正規化に失敗した場合
        log_cb("ニコ生表示名の取得に失敗しました: 入力が無効です。")  # 失敗ログ
        return None  # 取得失敗
    headers = {  # ヘッダーを定義
        "User-Agent": NICONICO_UA,  # ユーザーエージェント設定
    }  # ヘッダー定義終了
    try:  # 例外処理開始
        response = requests.get(  # GETリクエスト実行
            normalized,  # 正規化URL指定
            headers=headers,  # ヘッダー指定
            timeout=10,  # タイムアウト指定
        )  # レスポンス取得
    except requests.RequestException as exc:  # 通信例外の捕捉
        log_cb(f"ニコ生表示名の取得に失敗しました: {exc}")  # 失敗ログ
        return None  # 取得失敗
    if response.status_code != 200:  # ステータス異常の場合
        log_cb(f"ニコ生表示名の取得が失敗しました: {response.status_code}")  # 失敗ログ
        return None  # 取得失敗
    html_text = response.text  # HTML本文を取得
    props_match = re.search(  # data-props属性を検索
        r'data-props="(.*?)"',  # data-props属性
        html_text,  # HTML本文
        re.DOTALL,  # 改行を含めて検索
    )  # 検索終了
    if props_match:  # data-propsが見つかった場合
        try:  # 例外処理開始
            props_raw = html.unescape(props_match.group(1))  # HTMLエスケープを解除
            props = json.loads(props_raw)  # JSONを解析
        except Exception as exc:  # 解析例外の捕捉
            log_cb(f"ニコ生表示名の解析に失敗しました: {exc}")  # 失敗ログ
            props = None  # 解析失敗時はNone
        if isinstance(props, dict):  # 辞書である場合
            program = props.get("program")  # program情報を取得
            if isinstance(program, dict):  # programが辞書の場合
                supplier = program.get("supplier")  # supplier情報を取得
                if isinstance(supplier, dict):  # supplierが辞書の場合
                    name = str(supplier.get("name", "")).strip()  # 配信者名を取得
                    if name:  # 名前が取得できた場合
                        return name  # 配信者名を返却
    match = re.search(  # 配信者名の要素を検索
        r'<div[^>]*class="user-name-area"[^>]*>.*?<a[^>]*class="[^"]*label[^"]*"[^>]*>(.*?)</a>',  # 対象要素
        html_text,  # HTML本文
        re.DOTALL,  # 改行を含めて検索
    )  # 検索終了
    if match:  # 要素が見つかった場合
        raw_name = match.group(1)  # 抽出結果を取得
        cleaned = re.sub(r"<[^>]+>", "", raw_name)  # 余分なタグを除去
        cleaned = html.unescape(cleaned).strip()  # HTMLエスケープを解除して整形
        return cleaned if cleaned else None  # 表示名を返却
    label_match = re.search(  # labelアンカーから配信者名を検索
        r'<a[^>]*class="[^"]*label[^"]*"[^>]*href="https://www\.nicovideo\.jp/user/[^"]+"[^>]*>(.*?)</a>',  # labelアンカー
        html_text,  # HTML本文
        re.DOTALL,  # 改行を含めて検索
    )  # 検索終了
    if label_match:  # labelアンカーが見つかった場合
        raw_name = label_match.group(1)  # 抽出結果を取得
        cleaned = re.sub(r"<[^>]+>", "", raw_name)  # 余分なタグを除去
        cleaned = html.unescape(cleaned).strip()  # HTMLエスケープを解除して整形
        return cleaned if cleaned else None  # 表示名を返却
    fallback_match = re.search(  # 埋め込みJSONから配信者名を検索
        r'"(?:ownerName|userName)"\s*:\s*"([^"]+)"',  # 可能性のあるキーを探索
        html_text,  # HTML本文
    )  # 検索終了
    if fallback_match:  # JSON由来の名前が見つかった場合
        cleaned = html.unescape(fallback_match.group(1)).strip()  # エスケープ解除して整形
        return cleaned if cleaned else None  # 表示名を返却
    log_cb("ニコ生表示名の取得に失敗しました: 要素が見つかりません。")  # 失敗ログ
    return None  # 取得失敗
