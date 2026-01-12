# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import datetime as dt  # 日時操作
import re  # 文字列の正規化処理
from pathlib import Path  # パス操作
from urllib.parse import parse_qs, urlparse  # URL解析

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

def merge_unique_urls(*url_lists: list[str]) -> list[str]:  # URL一覧の重複排除結合
    merged: list[str] = []  # 結果リストを初期化
    for url_list in url_lists:  # 各一覧を処理
        for url in url_list:  # URLごとに処理
            if url not in merged:  # 未登録の場合
                merged.append(url)  # 追加
    return merged  # 結合済み一覧を返却

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

def resolve_streamer_filename(url: str, raw_text: str) -> str | None:  # 配信者別ファイル名の取得
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
