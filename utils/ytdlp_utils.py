# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import json  # JSON解析
import shutil  # 実行ファイル探索
import subprocess  # 外部コマンド実行
import threading  # 停止フラグ
import time  # ポーリング待機
from typing import Callable, Optional  # 型ヒント補助


def is_ytdlp_available() -> bool:  # yt-dlpの有無を確認
    return bool(shutil.which("yt-dlp"))  # 実行ファイルの有無を返却


def fetch_stream_urls_with_ytdlp(  # yt-dlpで配信URLを取得
    url: str,  # 配信URL
    format_selector: str,  # フォーマット指定
    log_cb: Optional[Callable[[str], None]] = None,  # ログ出力
    stop_event: Optional[threading.Event] = None,  # 停止フラグ
) -> list[str]:  # 取得結果を返却
    yt_dlp_path = shutil.which("yt-dlp")  # yt-dlpを探索
    if not yt_dlp_path:  # 見つからない場合
        if log_cb is not None:  # ログがある場合
            log_cb("yt-dlpが見つかりません。PATHに追加してください。")  # 通知
        return []  # 取得不可
    command = [  # yt-dlpコマンド
        yt_dlp_path,  # yt-dlp本体
        "-g",  # 直リンクを出力
        "-f",  # フォーマット指定
        format_selector,  # フォーマット
        "--no-playlist",  # プレイリスト無効
        "--no-warnings",  # 警告抑制
        url,  # 対象URL
    ]  # コマンド定義終了
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while process.poll() is None:
        if stop_event is not None and stop_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            return []
        time.sleep(0.1)
    stdout, stderr = process.communicate()
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if result.returncode != 0:  # 失敗時
        stderr_text = result.stderr.strip()  # stderrを取得
        if log_cb is not None:  # ログがある場合
            tail = "\n".join(stderr_text.splitlines()[-3:]) if stderr_text else "詳細不明"  # 末尾のみ
            log_cb(f"yt-dlpで配信URLを取得できませんでした: {tail}")  # 通知
        return []  # 取得不可
    urls = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if urls:
        return urls
    if log_cb is not None:  # ログがある場合
        log_cb("yt-dlpの出力が空です。")  # 通知
    return []  # 取得不可


def fetch_format_list_with_ytdlp(  # yt-dlpでフォーマット一覧を取得
    url: str,  # 配信URL
    log_cb: Optional[Callable[[str], None]] = None,  # ログ出力
    stop_event: Optional[threading.Event] = None,  # 停止フラグ
    max_lines: int = 80,  # 出力行数上限
) -> list[str]:  # フォーマット行一覧を返却
    yt_dlp_path = shutil.which("yt-dlp")
    if not yt_dlp_path:
        if log_cb is not None:
            log_cb("yt-dlpが見つかりません。PATHに追加してください。")
        return []
    command = [
        yt_dlp_path,
        "-F",
        "--no-playlist",
        "--no-warnings",
        url,
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while process.poll() is None:
        if stop_event is not None and stop_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            return []
        time.sleep(0.1)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        if log_cb is not None:
            tail = "\n".join((stderr or "").splitlines()[-3:]) if stderr else "詳細不明"
            log_cb(f"yt-dlpのフォーマット取得に失敗しました: {tail}")
        return []
    lines = [line.rstrip() for line in stdout.splitlines() if line.strip()]
    if log_cb is not None and lines:
        clipped = lines[: max_lines]
        suffix = "\n...(省略)" if len(lines) > max_lines else ""
        log_cb("yt-dlpフォーマット一覧:\n" + "\n".join(clipped) + suffix)
    return lines


def fetch_stream_url_with_ytdlp(  # yt-dlpで配信URLを取得
    url: str,  # 配信URL
    log_cb: Optional[Callable[[str], None]] = None,  # ログ出力
    stop_event: Optional[threading.Event] = None,  # 停止フラグ
) -> Optional[str]:  # 取得結果を返却
    urls = fetch_stream_urls_with_ytdlp(url, "best", log_cb=log_cb, stop_event=stop_event)
    return urls[0] if urls else None


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
