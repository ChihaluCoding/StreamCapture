# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
from typing import Callable, Optional  # 型ヒント補助
from urllib.parse import parse_qs, urlparse  # URL解析

def normalize_youtube_entry(entry: str) -> tuple[str, str]:  # YouTube入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return ("", "")  # 空を返却
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    if host:  # URL形式の場合
        if "youtu.be" in host and path_parts:  # 短縮URLの場合
            return ("video", path_parts[0])  # 動画IDとして返却
        if "youtube" in host and path_parts:  # YouTubeドメインの場合
            query = parse_qs(parsed.query)  # クエリを解析
            if "v" in query and query["v"]:  # 動画IDがクエリにある場合
                return ("video", query["v"][0])  # 動画IDとして返却
            if path_parts[0] == "channel" and len(path_parts) >= 2:  # channel形式の場合
                return ("channel", path_parts[1])  # チャンネルIDを返却
            if path_parts[0].startswith("@"):  # ハンドル形式の場合
                return ("handle", path_parts[0][1:])  # ハンドルを返却
            if path_parts[0] == "user" and len(path_parts) >= 2:  # user形式の場合
                return ("user", path_parts[1])  # ユーザー名を返却
            if path_parts[0] == "c" and len(path_parts) >= 2:  # カスタムURLの場合
                return ("handle", path_parts[1])  # ハンドルとして扱う
    if cleaned.startswith("@"):  # ハンドル形式の場合
        return ("handle", cleaned[1:])  # ハンドルを返却
    if cleaned.startswith("UC"):  # チャンネルID形式の場合
        return ("channel", cleaned)  # チャンネルIDを返却
    return ("handle", cleaned)  # それ以外はハンドルとして扱う

def normalize_twitch_login(entry: str) -> str:  # Twitchログイン名の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return ""  # 空を返却
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    if host and "twitch.tv" in host and path_parts:  # Twitch URLの場合
        return path_parts[0].lower()  # 最初のパス要素を返却
    cleaned = cleaned.lstrip("@")  # 先頭の@を削除
    return cleaned.lower()  # 小文字化して返却

def normalize_twitcasting_entry(entry: str) -> Optional[str]:  # ツイキャス入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return None  # 変換不可
    if "://" not in cleaned and "twitcasting.tv" in cleaned:  # スキーム無しURLの場合
        cleaned = f"https://{cleaned}"  # httpsを補完
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    if host and "twitcasting.tv" in host and path_parts:  # ツイキャスURLの場合
        user = path_parts[0]  # ユーザー名を取得
        return f"https://twitcasting.tv/{user}"  # 正規URLを返却
    cleaned = cleaned.lstrip("@")  # 先頭の@を削除
    if not cleaned:  # 空になった場合
        return None  # 変換不可
    return f"https://twitcasting.tv/{cleaned}"  # 正規URLを返却

def extract_twitcasting_user_id(entry: str) -> Optional[str]:  # ツイキャスユーザーID取得
    normalized = normalize_twitcasting_entry(entry)  # 入力を正規化
    if not normalized:  # 正規化失敗時
        return None  # 取得失敗
    parsed = urlparse(normalized)  # URLを解析
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    if not path_parts:  # パスが無い場合
        return None  # 取得失敗
    user_id = path_parts[0]  # ユーザーIDを取得
    return user_id if user_id else None  # ユーザーIDを返却

def is_twitcasting_url(url: str) -> bool:  # ツイキャスURL判定
    parsed = urlparse(url)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    if host and "twitcasting.tv" in host:  # ツイキャスドメインの場合
        return True  # ツイキャスURLとして扱う
    return "twitcasting.tv" in url  # 文字列判定も補助的に実施


def normalize_niconico_entry(entry: str) -> Optional[str]:  # ニコ生入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return None  # 変換不可
    if "://" not in cleaned and "nicovideo.jp" in cleaned:  # スキーム無しURLの場合
        cleaned = f"https://{cleaned}"  # httpsを補完
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    if host and "nicovideo.jp" in host and parsed.path:  # ニコ生URLの場合
        return cleaned  # URLをそのまま返却
    if cleaned.startswith("lv"):  # lv形式の場合
        return f"https://live.nicovideo.jp/watch/{cleaned}"  # 正規URLを返却
    return None  # 変換不可

def normalize_tiktok_entry(entry: str) -> Optional[str]:  # TikTok入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return None  # 変換不可
    if "://" not in cleaned and "tiktok.com" in cleaned:  # スキーム無しURLの場合
        cleaned = f"https://{cleaned}"  # httpsを補完
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    if host and "tiktok.com" in host and parsed.path:  # TikTok URLの場合
        return cleaned  # URLをそのまま返却
    cleaned = cleaned.lstrip("@")  # 先頭の@を削除
    if not cleaned:  # 空になった場合
        return None  # 変換不可
    return f"https://www.tiktok.com/@{cleaned}/live"  # 正規URLを返却

def normalize_kick_entry(entry: str) -> Optional[str]:  # Kick入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return None  # 変換不可
    if "://" not in cleaned and "kick.com" in cleaned:  # スキーム無しURLの場合
        cleaned = f"https://{cleaned}"  # httpsを補完
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    if host and "kick.com" in host and path_parts:  # Kick URLの場合
        return f"https://kick.com/{path_parts[0]}"  # 正規URLを返却
    cleaned = cleaned.lstrip("@")  # 先頭の@を削除
    if not cleaned:  # 空になった場合
        return None  # 変換不可
    return f"https://kick.com/{cleaned}"  # 正規URLを返却

def normalize_abema_entry(entry: str) -> Optional[str]:  # AbemaTV入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return None  # 変換不可
    if "://" not in cleaned and "abema.tv" in cleaned:  # スキーム無しURLの場合
        cleaned = f"https://{cleaned}"  # httpsを補完
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    if host and "abema.tv" in host and parsed.path:  # AbemaTV URLの場合
        return cleaned  # URLをそのまま返却
    return None  # 変換不可

def normalize_17live_entry(entry: str) -> Optional[str]:  # 17LIVE入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return None  # 変換不可
    if "://" not in cleaned and "17.live" in cleaned:  # スキーム無しURLの場合
        cleaned = f"https://{cleaned}"  # httpsを補完
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    if host and "17.live" in host and parsed.path:  # 17LIVE URLの場合
        return cleaned  # URLをそのまま返却
    return None  # 変換不可

def normalize_radiko_entry(entry: str) -> Optional[str]:  # radiko入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return None  # 変換不可
    if "://" not in cleaned and "radiko.jp" in cleaned:  # スキーム無しURLの場合
        cleaned = f"https://{cleaned}"  # httpsを補完
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    if host and "radiko.jp" in host and parsed.path:  # radiko URLの場合
        return cleaned  # URLをそのまま返却
    return None  # 変換不可

def normalize_openrectv_entry(entry: str) -> Optional[str]:  # OPENREC.tv入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return None  # 変換不可
    if "://" not in cleaned and "openrec.tv" in cleaned:  # スキーム無しURLの場合
        cleaned = f"https://{cleaned}"  # httpsを補完
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    if host and "openrec.tv" in host and parsed.path:  # OPENREC.tv URLの場合
        return cleaned  # URLをそのまま返却
    cleaned = cleaned.lstrip("@")  # 先頭の@を削除
    if not cleaned:  # 空になった場合
        return None  # 変換不可
    return f"https://www.openrec.tv/user/{cleaned}"  # 正規URLを返却

def normalize_bilibili_entry(entry: str) -> Optional[str]:  # bilibili入力の正規化
    cleaned = entry.strip()  # 文字列を正規化
    if not cleaned:  # 空の場合
        return None  # 変換不可
    if "://" not in cleaned and "bilibili.com" in cleaned:  # スキーム無しURLの場合
        cleaned = f"https://{cleaned}"  # httpsを補完
    parsed = urlparse(cleaned)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    if host and "bilibili.com" in host and parsed.path:  # bilibili URLの場合
        return cleaned  # URLをそのまま返却
    return None  # 変換不可

def normalize_platform_urls(  # 配信サービス入力のURL正規化
    entries: list[str],  # 入力一覧
    normalizer: Callable[[str], Optional[str]],  # 正規化関数
) -> list[str]:  # URL一覧を返却
    urls: list[str] = []  # URL一覧を初期化
    for entry in entries:  # 入力ごとに処理
        normalized = normalizer(entry)  # 正規化を実行
        if not normalized:  # 正規化失敗時
            continue  # 次へ
        if normalized not in urls:  # 重複確認
            urls.append(normalized)  # URLを追加
    return urls  # URL一覧を返却

def derive_platform_label_for_folder(url: str) -> Optional[str]:  # フォルダ名用ラベルの抽出
    parsed = urlparse(url)  # URLを解析
    host = parsed.netloc.lower()  # ホストを取得
    path_parts = [part for part in parsed.path.split("/") if part]  # パス要素を取得
    if host and "twitcasting.tv" in host and path_parts:  # ツイキャスの場合
        return path_parts[0]  # ユーザー名を返却
    if host and "nicovideo.jp" in host and path_parts:  # ニコ生の場合
        if "watch" in path_parts:  # watch形式の場合
            watch_index = path_parts.index("watch")  # watch位置を取得
            if len(path_parts) > watch_index + 1:  # 次の要素がある場合
                return path_parts[watch_index + 1]  # lvxxxx等を返却
        return path_parts[-1]  # 最後の要素を返却
    if host and "tiktok.com" in host and path_parts:  # TikTokの場合
        for part in path_parts:  # パス要素を順に確認
            if part.startswith("@") and len(part) > 1:  # @handle形式の場合
                return part[1:]  # @を除いたハンドルを返却
    if host and "kick.com" in host and path_parts:  # Kickの場合
        return path_parts[0]  # スラッグを返却
    if host and "radiko.jp" in host and path_parts:  # radikoの場合
        return path_parts[-1]  # 末尾パスを返却
    if host and "openrec.tv" in host and path_parts:  # OPENREC.tvの場合
        return path_parts[-1]  # 末尾パスを返却
    if host and "showroom-live.com" in host and path_parts:  # SHOWROOMの場合
        if path_parts[0] == "r" and len(path_parts) > 1:  # /r/room形式
            return path_parts[1]  # ルーム名を返却
        return path_parts[-1]  # 末尾パスを返却
    if host and "17.live" in host and path_parts:  # 17LIVEの場合
        if "live" in path_parts:  # /live/ID形式
            idx = path_parts.index("live")
            if len(path_parts) > idx + 1:
                return path_parts[idx + 1]
        return path_parts[-1]
    if host and "abema.tv" in host and path_parts:  # AbemaTVの場合
        if "channels" in path_parts:  # channels形式の場合
            idx = path_parts.index("channels")
            if len(path_parts) > idx + 1:
                return path_parts[idx + 1]
        if "now-on-air" in path_parts:  # now-on-air形式の場合
            idx = path_parts.index("now-on-air")
            if len(path_parts) > idx + 1:
                return path_parts[idx + 1]
        return path_parts[-1]
    if host and "bilibili.com" in host and path_parts:  # bilibiliの場合
        return path_parts[-1]  # 末尾パスを返却
    return None  # 抽出失敗
