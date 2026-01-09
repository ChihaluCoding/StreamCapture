# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import json  # JSON解析
import shutil  # 実行ファイル探索
import subprocess  # 外部コマンド実行
from typing import Callable, Optional  # 型ヒント補助


def is_ytdlp_available() -> bool:  # yt-dlpの有無を確認
    return bool(shutil.which("yt-dlp"))  # 実行ファイルの有無を返却


def fetch_stream_url_with_ytdlp(  # yt-dlpで配信URLを取得
    url: str,  # 配信URL
    log_cb: Optional[Callable[[str], None]] = None,  # ログ出力
) -> Optional[str]:  # 取得結果を返却
    yt_dlp_path = shutil.which("yt-dlp")  # yt-dlpを探索
    if not yt_dlp_path:  # 見つからない場合
        if log_cb is not None:  # ログがある場合
            log_cb("yt-dlpが見つかりません。PATHに追加してください。")  # 通知
        return None  # 取得不可
    command = [  # yt-dlpコマンド
        yt_dlp_path,  # yt-dlp本体
        "-g",  # 直リンクを出力
        "-f",  # フォーマット指定
        "best",  # 最高画質
        "--no-playlist",  # プレイリスト無効
        "--no-warnings",  # 警告抑制
        url,  # 対象URL
    ]  # コマンド定義終了
    result = subprocess.run(  # yt-dlp実行
        command,  # コマンド指定
        capture_output=True,  # 出力取得
        text=True,  # テキストとして取得
        encoding="utf-8",  # 文字コード指定
        errors="replace",  # デコード失敗時は置換
        check=False,  # 例外にしない
    )  # 実行結果を取得
    if result.returncode != 0:  # 失敗時
        stderr_text = result.stderr.strip()  # stderrを取得
        if log_cb is not None:  # ログがある場合
            tail = "\n".join(stderr_text.splitlines()[-3:]) if stderr_text else "詳細不明"  # 末尾のみ
            log_cb(f"yt-dlpで配信URLを取得できませんでした: {tail}")  # 通知
        return None  # 取得不可
    for line in result.stdout.splitlines():  # 出力を確認
        candidate = line.strip()  # 行を正規化
        if candidate:  # 空行を除外
            return candidate  # 最初のURLを返却
    if log_cb is not None:  # ログがある場合
        log_cb("yt-dlpの出力が空です。")  # 通知
    return None  # 取得不可


def fetch_metadata_with_ytdlp(  # yt-dlpでメタ情報を取得
    url: str,  # 配信URL
    log_cb: Optional[Callable[[str], None]] = None,  # ログ出力
) -> Optional[dict]:  # 取得結果を返却
    yt_dlp_path = shutil.which("yt-dlp")  # yt-dlpを探索
    if not yt_dlp_path:  # 見つからない場合
        if log_cb is not None:  # ログがある場合
            log_cb("yt-dlpが見つかりません。PATHに追加してください。")  # 通知
        return None  # 取得不可
    command = [  # yt-dlpコマンド
        yt_dlp_path,  # yt-dlp本体
        "-J",  # JSON出力
        "--no-playlist",  # プレイリスト無効
        "--no-warnings",  # 警告抑制
        url,  # 対象URL
    ]  # コマンド定義終了
    result = subprocess.run(  # yt-dlp実行
        command,  # コマンド指定
        capture_output=True,  # 出力取得
        text=True,  # テキストとして取得
        encoding="utf-8",  # 文字コード指定
        errors="replace",  # デコード失敗時は置換
        check=False,  # 例外にしない
    )  # 実行結果を取得
    if result.returncode != 0:  # 失敗時
        stderr_text = result.stderr.strip()  # stderrを取得
        if log_cb is not None:  # ログがある場合
            tail = "\n".join(stderr_text.splitlines()[-3:]) if stderr_text else "詳細不明"  # 末尾のみ
            log_cb(f"yt-dlpでメタ情報を取得できませんでした: {tail}")  # 通知
        return None  # 取得不可
    try:  # JSON解析
        return json.loads(result.stdout)  # JSONを返却
    except ValueError:  # JSON解析失敗時
        if log_cb is not None:  # ログがある場合
            log_cb("yt-dlpのJSON解析に失敗しました。")  # 通知
        return None  # 取得不可
