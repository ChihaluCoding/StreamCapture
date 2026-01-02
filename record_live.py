#!/usr/bin/env python3  # 実行用のシェバン指定
# -*- coding: utf-8 -*-  # 文字コード指定

from __future__ import annotations  # 型ヒントの将来互換対応

import argparse  # コマンドライン引数解析
import datetime as dt  # 日時操作
import sys  # 終了コード返却
import threading  # 停止フラグ管理
import time  # 待機処理
from pathlib import Path  # パス操作
from typing import Callable, Optional  # オプション型とコールバック型

from streamlink import Streamlink  # Streamlink本体
from streamlink.exceptions import StreamlinkError  # Streamlink例外

DEFAULT_QUALITY = "best"  # 既定の画質指定
DEFAULT_RETRY_COUNT = 5  # 既定の再接続回数
DEFAULT_RETRY_WAIT_SEC = 10  # 既定の再接続待機秒
READ_CHUNK_SIZE = 1024 * 1024  # 読み取りチャンクサイズ
FLUSH_INTERVAL_SEC = 5  # 定期フラッシュ間隔


def build_parser() -> argparse.ArgumentParser:  # 引数パーサ生成
    parser = argparse.ArgumentParser(  # パーサを生成
        description="StreamlinkでYouTube/Twitch配信を録画します。",  # 説明文
    )  # パーサ生成の終了
    parser.add_argument(  # URL引数を追加
        "url",  # URLの位置引数
        help="録画対象の配信URLを指定します。",  # 説明
    )  # URL引数の追加終了
    parser.add_argument(  # 出力ディレクトリを追加
        "-o",  # 短縮オプション
        "--output-dir",  # 出力ディレクトリ指定
        default="recordings",  # 既定ディレクトリ
        help="録画ファイルの出力先ディレクトリ。",  # 説明
    )  # 出力ディレクトリ引数の追加終了
    parser.add_argument(  # 画質指定を追加
        "-q",  # 短縮オプション
        "--quality",  # 画質指定
        default=DEFAULT_QUALITY,  # 既定画質
        help="Streamlinkの画質指定（例: best, worst, 1080p）。",  # 説明
    )  # 画質引数の追加終了
    parser.add_argument(  # 出力ファイル名を追加
        "-f",  # 短縮オプション
        "--filename",  # ファイル名指定
        default=None,  # 既定は自動生成
        help="出力ファイル名（拡張子省略可）。",  # 説明
    )  # ファイル名引数の追加終了
    parser.add_argument(  # リトライ回数を追加
        "--retry-count",  # リトライ回数指定
        type=int,  # 整数型
        default=DEFAULT_RETRY_COUNT,  # 既定値
        help="切断時に再接続を試みる回数。",  # 説明
    )  # リトライ回数引数の追加終了
    parser.add_argument(  # リトライ待機を追加
        "--retry-wait",  # リトライ待機秒
        type=int,  # 整数型
        default=DEFAULT_RETRY_WAIT_SEC,  # 既定値
        help="再接続の待機秒数。",  # 説明
    )  # リトライ待機引数の追加終了
    parser.add_argument(  # HTTPタイムアウトを追加
        "--http-timeout",  # HTTPタイムアウト指定
        type=int,  # 整数型
        default=20,  # 既定値
        help="HTTPタイムアウト秒数。",  # 説明
    )  # HTTPタイムアウト引数の追加終了
    parser.add_argument(  # ストリームタイムアウトを追加
        "--stream-timeout",  # ストリームタイムアウト
        type=int,  # 整数型
        default=60,  # 既定値
        help="ストリームタイムアウト秒数。",  # 説明
    )  # ストリームタイムアウト引数の追加終了
    return parser  # パーサを返却


def resolve_output_path(output_dir: Path, filename: Optional[str]) -> Path:  # 出力パス決定
    output_dir.mkdir(parents=True, exist_ok=True)  # 出力先を確保
    if filename:  # ファイル名が指定された場合
        name = filename  # 指定名を使用
    else:  # 自動生成する場合
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")  # タイムスタンプ生成
        name = f"{timestamp}.ts"  # 既定拡張子で生成
    if "." not in Path(name).name:  # 拡張子が無い場合
        name = f"{name}.ts"  # TS拡張子を補完
    return output_dir / name  # 出力パスを返却


def select_stream(available_streams: dict, quality: str):  # ストリーム選択
    if quality in available_streams:  # 希望画質が存在する場合
        return available_streams[quality]  # その画質を返却
    if DEFAULT_QUALITY in available_streams:  # bestが存在する場合
        print(  # 画質フォールバック通知
            f"指定画質 '{quality}' が見つからないため '{DEFAULT_QUALITY}' を使用します。"
        )  # 通知の終了
        return available_streams[DEFAULT_QUALITY]  # bestを返却
    first_key = next(iter(available_streams))  # 最初のキーを取得
    print(  # フォールバック通知
        f"指定画質 '{quality}' が見つからないため '{first_key}' を使用します。"
    )  # 通知の終了
    return available_streams[first_key]  # 最初の画質を返却


def should_stop(stop_event: Optional[threading.Event]) -> bool:  # 停止判定
    return stop_event is not None and stop_event.is_set()  # 停止フラグの状態を返却


def open_stream_with_retry(  # リトライ付きでストリームを開く
    session: Streamlink,  # Streamlinkセッション
    url: str,  # 配信URL
    quality: str,  # 画質指定
    retry_count: int,  # リトライ回数
    retry_wait: int,  # リトライ待機秒
    stop_event: Optional[threading.Event],  # 停止フラグ
    status_cb: Optional[Callable[[str], None]],  # 状態通知コールバック
):  # 関数定義終了
    attempt = 0  # 試行回数カウンタ
    while True:  # リトライループ
        if should_stop(stop_event):  # 停止要求の確認
            return None  # 停止時は取得を中断
        attempt += 1  # 試行回数を加算
        try:  # 例外処理開始
            streams = session.streams(url)  # ストリーム一覧を取得
        except StreamlinkError as exc:  # Streamlink例外の捕捉
            message = f"ストリーム取得に失敗しました: {exc}"  # メッセージ生成
            if status_cb is not None:  # コールバックが指定されている場合
                status_cb(message)  # 状態通知
            else:  # コールバックが無い場合
                print(message)  # 標準出力に通知
            streams = {}  # 空辞書に退避
        if streams:  # ストリームが取得できた場合
            stream = select_stream(streams, quality)  # ストリームを選択
            return stream  # 選択結果を返却
        if attempt > retry_count:  # リトライ回数を超えた場合
            raise RuntimeError("ストリームを取得できませんでした。")  # 例外送出
        message = f"{retry_wait}秒待機して再試行します（{attempt}/{retry_count}）..."  # 待機通知
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        else:  # コールバックが無い場合
            print(message)  # 標準出力に通知
        time.sleep(retry_wait)  # 待機


def record_stream(  # 録画処理
    session: Streamlink,  # Streamlinkセッション
    url: str,  # 配信URL
    quality: str,  # 画質指定
    output_path: Path,  # 出力パス
    retry_count: int,  # リトライ回数
    retry_wait: int,  # リトライ待機秒
    stop_event: Optional[threading.Event] = None,  # 停止フラグ
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
):  # 関数定義終了
    start_message = f"録画開始: {url}"  # 開始通知メッセージ
    output_message = f"出力先: {output_path}"  # 出力先通知メッセージ
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(start_message)  # 開始通知
        status_cb(output_message)  # 出力先通知
    else:  # コールバックが無い場合
        print(start_message)  # 開始通知
        print(output_message)  # 出力先通知
    last_flush_time = time.time()  # 最終フラッシュ時刻
    with output_path.open("ab", buffering=READ_CHUNK_SIZE) as output_file:  # 出力ファイルを開く
        while True:  # 録画ループ
            if should_stop(stop_event):  # 停止要求の確認
                message = "停止要求を受け付けました。録画を終了します。"  # 停止通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
                else:  # コールバックが無い場合
                    print(message)  # 標準出力に通知
                break  # 録画ループを終了
            stream = open_stream_with_retry(  # ストリームを取得
                session=session,  # セッション指定
                url=url,  # URL指定
                quality=quality,  # 画質指定
                retry_count=retry_count,  # リトライ回数
                retry_wait=retry_wait,  # リトライ待機秒
                stop_event=stop_event,  # 停止フラグ指定
                status_cb=status_cb,  # 状態通知コールバック
            )  # ストリーム取得終了
            if stream is None:  # 停止によりストリームが取得できない場合
                break  # 録画ループを終了
            stream_fd = None  # ストリームファイルを初期化
            try:  # 例外処理開始
                stream_fd = stream.open()  # ストリームを開く
                while True:  # 読み取りループ
                    if should_stop(stop_event):  # 停止要求の確認
                        message = "停止要求を受け付けました。ストリームを閉じます。"  # 停止通知
                        if status_cb is not None:  # コールバックが指定されている場合
                            status_cb(message)  # 状態通知
                        else:  # コールバックが無い場合
                            print(message)  # 標準出力に通知
                        break  # 読み取りループを終了
                    data = stream_fd.read(READ_CHUNK_SIZE)  # データ読み取り
                    if not data:  # データが空の場合
                        message = "ストリームが終了しました。再接続を試みます。"  # 終了通知
                        if status_cb is not None:  # コールバックが指定されている場合
                            status_cb(message)  # 状態通知
                        else:  # コールバックが無い場合
                            print(message)  # 標準出力に通知
                        break  # 内側ループを抜ける
                    output_file.write(data)  # ファイルへ書き込み
                    now = time.time()  # 現在時刻を取得
                    if now - last_flush_time >= FLUSH_INTERVAL_SEC:  # フラッシュ条件
                        output_file.flush()  # 出力をフラッシュ
                        last_flush_time = now  # 最終フラッシュ時刻を更新
            except StreamlinkError as exc:  # Streamlink例外を捕捉
                message = f"ストリーム読み取り中にエラーが発生しました: {exc}"  # エラー通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
                else:  # コールバックが無い場合
                    print(message)  # 標準出力に通知
            finally:  # 後始末
                if stream_fd is not None:  # ストリームが開かれている場合
                    stream_fd.close()  # ストリームを閉じる


def main() -> int:  # エントリポイント
    parser = build_parser()  # 引数パーサ生成
    args = parser.parse_args()  # 引数を解析

    output_dir = Path(args.output_dir)  # 出力ディレクトリを取得
    output_path = resolve_output_path(output_dir, args.filename)  # 出力パスを確定

    session = Streamlink()  # Streamlinkセッションを生成
    session.set_option("http-timeout", args.http_timeout)  # HTTPタイムアウトを設定
    session.set_option("stream-timeout", args.stream_timeout)  # ストリームタイムアウト設定

    try:  # 例外処理開始
        record_stream(  # 録画処理を開始
            session=session,  # セッション指定
            url=args.url,  # URL指定
            quality=args.quality,  # 画質指定
            output_path=output_path,  # 出力パス指定
            retry_count=args.retry_count,  # リトライ回数指定
            retry_wait=args.retry_wait,  # リトライ待機秒指定
        )  # 録画処理終了
    except KeyboardInterrupt:  # Ctrl+Cの捕捉
        print("録画を停止しました。")  # 停止通知
        return 0  # 正常終了コード
    except Exception as exc:  # 予期しない例外の捕捉
        print(f"致命的なエラーが発生しました: {exc}")  # エラー表示
        return 1  # 異常終了コード
    return 0  # 正常終了コード


if __name__ == "__main__":  # 直接実行時の分岐
    sys.exit(main())  # メイン処理を実行
