# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import shutil  # 実行ファイル探索
import subprocess  # 外部コマンド実行
import threading  # 停止フラグ制御
import time  # 待機処理
from pathlib import Path  # パス操作
from typing import Callable, Optional  # 型ヒント補助
from streamlink import Streamlink  # Streamlink本体
from streamlink.exceptions import StreamlinkError  # Streamlink例外
from config import (  # 定数を読み込み
    DEFAULT_OUTPUT_FORMAT,  # 出力形式の既定値
    DEFAULT_QUALITY,  # 既定の画質指定
    FLUSH_INTERVAL_SEC,  # 定期フラッシュ間隔
    OUTPUT_FORMAT_MP4_COPY,  # 出力形式: MP4高速コピー
    OUTPUT_FORMAT_MP4_LIGHT,  # 出力形式: MP4軽量再エンコード
    OUTPUT_FORMAT_TS,  # 出力形式: TS
    READ_CHUNK_SIZE,  # 読み取りチャンクサイズ
)  # 定数読み込みの終了
from url_utils import (  # URL関連ユーティリティを読み込み
    build_default_recording_name,  # 既定ファイル名生成
    ensure_unique_path,  # パス重複回避
    safe_filename_component,  # ファイル名安全化
    derive_channel_label,  # 配信者ラベル推定
)
from ytdlp_utils import fetch_stream_url_with_ytdlp, is_ytdlp_available  # yt-dlp補助

def resolve_output_path(  # 出力パス決定
    output_dir: Path,  # 出力ディレクトリ
    filename: Optional[str],  # ファイル名
    url: Optional[str],  # 配信URL
    channel_label: Optional[str] = None,  # 配信者ラベル
) -> Path:  # 出力パスを返却
    if channel_label:  # ラベルが指定されている場合
        safe_label = safe_filename_component(channel_label)  # ラベルを安全化
        output_dir = output_dir / safe_label  # 配信者ごとのフォルダを作成
    elif url:  # URLが指定されている場合
        default_label = derive_channel_label(url)  # 配信者ラベルを生成
        output_dir = output_dir / default_label  # 配信者ごとのフォルダを作成
    output_dir.mkdir(parents=True, exist_ok=True)  # 出力先を確保
    if filename:  # ファイル名が指定された場合
        name = filename  # 指定名を使用
    else:  # 自動生成する場合
        name = build_default_recording_name()  # 既定の録画名を生成
    if "." not in Path(name).name:  # 拡張子が無い場合
        name = f"{name}.ts"  # TS拡張子を補完
    candidate = output_dir / name  # 出力候補パスを生成
    return ensure_unique_path(candidate)  # 重複回避したパスを返却

def normalize_output_format(output_format: str) -> str:  # 出力形式の正規化
    cleaned = str(output_format).strip().lower()  # 文字列を正規化
    if cleaned in (OUTPUT_FORMAT_TS, OUTPUT_FORMAT_MP4_COPY, OUTPUT_FORMAT_MP4_LIGHT):  # 対応形式の場合
        return cleaned  # 正規化済み形式を返却
    return DEFAULT_OUTPUT_FORMAT  # 既定形式にフォールバック

def build_mp4_output_path(input_path: Path) -> Path:  # MP4出力パス生成
    base = input_path.with_suffix("")  # 拡張子を除いたベース
    candidate = input_path.with_suffix(".mp4")  # 既定のMP4出力パス
    if not candidate.exists():  # 既定パスが未使用の場合
        return candidate  # 既定パスを返却
    for index in range(1, 1000):  # 衝突回避の連番
        candidate = base.with_name(f"{base.name}_{index}").with_suffix(".mp4")  # 連番付きパス
        if not candidate.exists():  # 未使用のパスが見つかった場合
            return candidate  # そのパスを返却
    return base.with_name(f"{base.name}_overflow").with_suffix(".mp4")  # 最終手段のパス

def delete_source_ts(  # 変換後のTS削除処理
    input_path: Path,  # 入力パス
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> None:  # 返り値なし
    if input_path.suffix.lower() != ".ts":  # TS以外は対象外
        return  # 何もしない
    if not input_path.exists():  # 既に削除済みの場合
        return  # 何もしない
    try:  # 削除の例外処理開始
        input_path.unlink()  # TSファイルを削除
        message = f"元のTSファイルを削除しました: {input_path}"  # 削除完了通知
    except OSError as exc:  # 削除失敗時の処理
        message = f"元のTSファイル削除に失敗しました: {exc}"  # 失敗通知
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(message)  # 状態通知

def convert_to_mp4(  # MP4変換処理
    input_path: Path,  # 入力パス
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> Optional[Path]:  # 返り値は出力パス
    if not input_path.exists():  # 入力ファイルが無い場合
        message = f"変換対象ファイルが存在しません: {input_path}"  # 通知文
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換不可
    if input_path.stat().st_size == 0:  # サイズがゼロの場合
        message = f"変換対象ファイルが空です: {input_path}"  # 通知文
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換不可
    ffmpeg_path = shutil.which("ffmpeg")  # ffmpegのパスを探索
    if not ffmpeg_path:  # ffmpegが見つからない場合
        message = "ffmpegが見つかりません。PATHにffmpegを追加してください。"  # 通知文
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換不可
    output_path = build_mp4_output_path(input_path)  # 出力パスを生成
    message = f"MP4変換を開始します: {output_path}"  # 開始通知
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(message)  # 状態通知
    command = [  # ffmpegコマンドの組み立て
        ffmpeg_path,  # ffmpeg実行ファイル
        "-y",  # 既存ファイル上書き
        "-i",  # 入力指定
        str(input_path),  # 入力パス
        "-c",  # コーデック指定
        "copy",  # 再エンコードせずコピー
        "-bsf:a",  # 音声ビットストリームフィルタ指定
        "aac_adtstoasc",  # AACのADTS→ASC変換
        "-movflags",  # MP4最適化フラグ
        "+faststart",  # 先頭へメタデータ移動
        str(output_path),  # 出力パス
    ]  # コマンド定義終了
    result = subprocess.run(  # ffmpeg実行
        command,  # コマンド指定
        capture_output=True,  # 出力を取得
        text=True,  # テキストとして取得
        encoding="utf-8",  # 文字コードを指定
        errors="replace",  # デコード失敗時は置換
        check=False,  # 例外にしない
    )  # 実行結果を取得
    if result.returncode != 0:  # 失敗時の処理
        stderr_text_full = result.stderr.strip()  # 標準エラーの全文を取得
        stderr_tail = stderr_text_full.splitlines()[-5:]  # エラー末尾を抽出
        stderr_text = "\n".join(stderr_tail) if stderr_tail else "詳細不明"  # エラー整形
        retry_message = "再エンコードでMP4変換を再試行します。"  # 再試行通知
        should_retry = (  # 再試行判定
            "Malformed AAC bitstream" in stderr_text_full  # AACエラー判定
            or "aac_adtstoasc" in stderr_text_full  # フィルタ指示判定
            or "av_interleaved_write_frame" in stderr_text_full  # 書き込みエラー判定
        )  # 再試行判定の終了
        if should_retry:  # 再試行が必要な場合
            if output_path.exists():  # 失敗した出力が残っている場合
                output_path.unlink(missing_ok=True)  # 出力ファイルを削除
            if status_cb is not None:  # コールバックが指定されている場合
                status_cb(retry_message)  # 再試行通知
            command_retry = [  # 再試行コマンドの組み立て
                ffmpeg_path,  # ffmpeg実行ファイル
                "-y",  # 既存ファイル上書き
                "-i",  # 入力指定
                str(input_path),  # 入力パス
                "-c:v",  # 映像コーデック指定
                "copy",  # 映像はコピー
                "-c:a",  # 音声コーデック指定
                "aac",  # AACで再エンコード
                "-b:a",  # 音声ビットレート指定
                "192k",  # 192kbps指定
                "-movflags",  # MP4最適化フラグ
                "+faststart",  # 先頭へメタデータ移動
                str(output_path),  # 出力パス
            ]  # 再試行コマンド定義終了
            result_retry = subprocess.run(  # 再試行の実行
                command_retry,  # 再試行コマンド
                capture_output=True,  # 出力を取得
                text=True,  # テキストとして取得
                encoding="utf-8",  # 文字コードを指定
                errors="replace",  # デコード失敗時は置換
                check=False,  # 例外にしない
            )  # 再試行結果を取得
            if result_retry.returncode == 0:  # 再試行成功時
                message = f"MP4変換が完了しました（再エンコード）: {output_path}"  # 完了通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
                delete_source_ts(input_path, status_cb=status_cb)  # 元TSファイルを削除
                return output_path  # 出力パスを返却
            retry_stderr = result_retry.stderr.strip().splitlines()[-5:]  # 再試行エラー末尾
            retry_text = "\n".join(retry_stderr) if retry_stderr else "詳細不明"  # 再試行エラー整形
            message = f"MP4変換に失敗しました（再試行）: {retry_text}"  # 再試行失敗通知
            if status_cb is not None:  # コールバックが指定されている場合
                status_cb(message)  # 状態通知
            return None  # 変換失敗
        message = f"MP4変換に失敗しました: {stderr_text}"  # 失敗通知
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換失敗
    message = f"MP4変換が完了しました: {output_path}"  # 完了通知
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(message)  # 状態通知
    delete_source_ts(input_path, status_cb=status_cb)  # 元TSファイルを削除
    return output_path  # 出力パスを返却

def convert_to_mp4_light(  # MP4軽量変換処理
    input_path: Path,  # 入力パス
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> Optional[Path]:  # 返り値は出力パス
    if not input_path.exists():  # 入力ファイルが無い場合
        message = f"変換対象ファイルが存在しません: {input_path}"  # 通知文
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換不可
    if input_path.stat().st_size == 0:  # サイズがゼロの場合
        message = f"変換対象ファイルが空です: {input_path}"  # 通知文
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換不可
    ffmpeg_path = shutil.which("ffmpeg")  # ffmpegのパスを探索
    if not ffmpeg_path:  # ffmpegが見つからない場合
        message = "ffmpegが見つかりません。PATHにffmpegを追加してください。"  # 通知文
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換不可
    output_path = build_mp4_output_path(input_path)  # 出力パスを生成
    message = f"MP4軽量変換を開始します: {output_path}"  # 開始通知
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(message)  # 状態通知
    command = [  # ffmpegコマンドの組み立て
        ffmpeg_path,  # ffmpeg実行ファイル
        "-y",  # 既存ファイル上書き
        "-i",  # 入力指定
        str(input_path),  # 入力パス
        "-c:v",  # 映像コーデック指定
        "libx264",  # H.264で再エンコード
        "-preset",  # エンコード速度指定
        "veryfast",  # 速度優先で軽量化
        "-crf",  # 品質指定
        "28",  # 軽量化向けのCRF値
        "-pix_fmt",  # ピクセルフォーマット指定
        "yuv420p",  # 互換性重視の形式
        "-c:a",  # 音声コーデック指定
        "aac",  # AACで再エンコード
        "-b:a",  # 音声ビットレート指定
        "128k",  # 128kbps指定
        "-movflags",  # MP4最適化フラグ
        "+faststart",  # 先頭へメタデータ移動
        str(output_path),  # 出力パス
    ]  # コマンド定義終了
    result = subprocess.run(  # ffmpeg実行
        command,  # コマンド指定
        capture_output=True,  # 出力を取得
        text=True,  # テキストとして取得
        encoding="utf-8",  # 文字コードを指定
        errors="replace",  # デコード失敗時は置換
        check=False,  # 例外にしない
    )  # 実行結果を取得
    if result.returncode != 0:  # 失敗時の処理
        stderr_text_full = result.stderr.strip()  # 標準エラーの全文を取得
        stderr_tail = stderr_text_full.splitlines()[-5:]  # エラー末尾を抽出
        stderr_text = "\n".join(stderr_tail) if stderr_tail else "詳細不明"  # エラー整形
        message = f"MP4軽量変換に失敗しました: {stderr_text}"  # 失敗通知
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return None  # 変換失敗
    message = f"MP4軽量変換が完了しました: {output_path}"  # 完了通知
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(message)  # 状態通知
    delete_source_ts(input_path, status_cb=status_cb)  # 元TSファイルを削除
    return output_path  # 出力パスを返却

def convert_recording(  # 出力形式に合わせた変換
    input_path: Path,  # 入力パス
    output_format: str,  # 出力形式指定
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> Optional[Path]:  # 返り値は出力パス
    normalized_format = normalize_output_format(output_format)  # 出力形式を正規化
    if normalized_format == OUTPUT_FORMAT_TS:  # TS指定の場合
        message = f"TS形式のため変換をスキップします: {input_path}"  # スキップ通知
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return input_path  # TSはそのまま返却
    if normalized_format == OUTPUT_FORMAT_MP4_LIGHT:  # 軽量MP4指定の場合
        return convert_to_mp4_light(input_path, status_cb=status_cb)  # 軽量変換を実行
    return convert_to_mp4(input_path, status_cb=status_cb)  # 高品質コピーMP4を実行

def select_stream(available_streams: dict, quality: str):  # ストリーム選択
    if quality in available_streams:  # 希望画質が存在する場合
        return available_streams[quality]  # その画質を返却
    if DEFAULT_QUALITY in available_streams:  # bestが存在する場合
        return available_streams[DEFAULT_QUALITY]  # bestを返却
    first_key = next(iter(available_streams))  # 最初のキーを取得
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
            streams = {}  # 空辞書に退避
        if streams:  # ストリームが取得できた場合
            stream = select_stream(streams, quality)  # ストリームを選択
            return stream  # 選択結果を返却
        if attempt > retry_count:  # リトライ回数を超えた場合
            raise RuntimeError("ストリームを取得できませんでした。")  # 例外送出
        message = f"{retry_wait}秒待機して再試行します（{attempt}/{retry_count}）..."  # 待機通知
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        time.sleep(retry_wait)  # 待機

def is_stream_available(  # ストリーム存在判定
    session: Streamlink,  # Streamlinkセッション
    url: str,  # 配信URL
    status_cb: Optional[Callable[[str], None]],  # 状態通知コールバック
) -> bool:  # 判定結果を返却
    try:  # 例外処理開始
        streams = session.streams(url)  # ストリーム一覧を取得
    except StreamlinkError as exc:  # Streamlink例外の捕捉
        message = f"ストリーム確認に失敗しました: {exc}"  # エラーメッセージ生成
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return False  # 取得失敗時はFalse
    return bool(streams)  # ストリーム有無を返却

def _record_stream_with_ytdlp(  # yt-dlpで録画処理
    url: str,  # 配信URL
    output_path: Path,  # 出力パス
    stop_event: Optional[threading.Event],  # 停止フラグ
    status_cb: Optional[Callable[[str], None]],  # 状態通知コールバック
) -> bool:  # 成否を返却
    if not is_ytdlp_available():  # yt-dlpが無い場合
        return False  # 何もしない
    stream_url = fetch_stream_url_with_ytdlp(url, status_cb)  # m3u8等のURLを取得
    if not stream_url:  # 取得失敗時
        return False  # 失敗を返却
    ffmpeg_path = shutil.which("ffmpeg")  # ffmpegを探索
    if not ffmpeg_path:  # ffmpegが無い場合
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb("ffmpegが見つかりません。PATHにffmpegを追加してください。")  # 通知
        return False  # 失敗を返却
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb("yt-dlpの配信URLで録画を試行します。")  # フォールバック通知
    command = [  # ffmpegコマンド定義
        ffmpeg_path,  # ffmpeg実行ファイル
        "-y",  # 上書き
        "-loglevel",  # ログレベル指定
        "error",  # エラーのみ表示
        "-reconnect",  # 再接続有効
        "1",  # 有効化フラグ
        "-reconnect_streamed",  # ストリーム再接続
        "1",  # 有効化フラグ
        "-reconnect_delay_max",  # 最大待機
        "5",  # 秒
        "-i",  # 入力指定
        stream_url,  # 取得したURL
        "-c",  # コーデック指定
        "copy",  # コピー
        "-f",  # 出力フォーマット指定
        "mpegts",  # TS出力
        str(output_path),  # 出力パス
    ]  # コマンド定義終了
    process = subprocess.Popen(  # ffmpeg起動
        command,  # コマンド指定
        stdout=subprocess.DEVNULL,  # 標準出力は捨てる
        stderr=subprocess.PIPE,  # エラー出力を取得
        text=True,  # テキスト取得
        encoding="utf-8",  # 文字コード指定
        errors="replace",  # デコード失敗時は置換
    )
    stopped = False  # 停止フラグ
    try:  # 待機処理
        while process.poll() is None:  # 実行中
            if should_stop(stop_event):  # 停止要求
                stopped = True  # 停止扱いにする
                process.terminate()  # 停止要求を送る
                try:  # 終了待機
                    process.wait(timeout=5)  # 少し待機
                except subprocess.TimeoutExpired:  # 終了しない場合
                    process.kill()  # 強制終了
                break  # ループ終了
            time.sleep(0.2)  # 少し待機
    finally:  # 後始末
        try:  # 出力回収
            _, stderr = process.communicate(timeout=1)  # 出力を回収
        except subprocess.TimeoutExpired:  # 取り切れない場合
            process.kill()  # 強制終了
            _, stderr = process.communicate()  # 出力を回収
        if process.returncode not in (0, None) and not stopped:  # 失敗時
            tail = "\n".join((stderr or "").splitlines()[-5:]) if stderr else "詳細不明"  # エラー末尾
            if status_cb is not None:  # コールバックが指定されている場合
                status_cb(f"yt-dlp経由の録画に失敗しました: {tail}")  # 通知
            return False  # 失敗
    if status_cb is not None and stopped:  # 停止で終了した場合
        status_cb("停止要求を受け付けました。録画を終了します。")  # 停止通知
    return True  # 成功扱い


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
    last_flush_time = time.time()  # 最終フラッシュ時刻
    total_written = 0  # 総書き込みバイト数を初期化
    output_file = None  # 出力ファイル参照
    try:  # 録画処理
        while True:  # 録画ループ
            if should_stop(stop_event):  # 停止要求の確認
                message = "停止要求を受け付けました。録画を終了します。"  # 停止通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
                break  # 録画ループを終了
            try:  # 例外処理開始
                stream = open_stream_with_retry(  # ストリームを取得
                    session=session,  # セッション指定
                    url=url,  # URL指定
                    quality=quality,  # 画質指定
                    retry_count=retry_count,  # リトライ回数
                    retry_wait=retry_wait,  # リトライ待機秒
                    stop_event=stop_event,  # 停止フラグ指定
                    status_cb=status_cb,  # 状態通知コールバック
                )  # ストリーム取得終了
            except RuntimeError as exc:  # 取得失敗を捕捉
                message = f"ストリームを取得できませんでした: {exc}"  # 取得失敗通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
                if _record_stream_with_ytdlp(url, output_path, stop_event, status_cb):  # yt-dlpへ切替
                    return  # ffmpeg録画に任せて終了
                break  # 録画ループを終了
            if stream is None:  # 停止によりストリームが取得できない場合
                break  # 録画ループを終了
            if output_file is None:  # 出力ファイルが未作成の場合
                output_file = output_path.open("ab", buffering=READ_CHUNK_SIZE)  # 出力ファイルを開く
            stream_fd = None  # ストリームファイルを初期化
            stream_ended = False  # 配信終了フラグ
            try:  # 例外処理開始
                stream_fd = stream.open()  # ストリームを開く
                while True:  # 読み取りループ
                    if should_stop(stop_event):  # 停止要求の確認
                        message = "停止要求を受け付けました。ストリームを閉じます。"  # 停止通知
                        if status_cb is not None:  # コールバックが指定されている場合
                            status_cb(message)  # 状態通知
                        break  # 読み取りループを終了
                    data = stream_fd.read(READ_CHUNK_SIZE)  # データ読み取り
                    if not data:  # データが空の場合
                        if total_written == 0:  # まだ書き込みが無い場合
                            message = "配信が開始されていないため録画を停止します。"  # 未配信通知
                            if status_cb is not None:  # コールバックが指定されている場合
                                status_cb(message)  # 状態通知
                            stream_ended = True  # 終了フラグを設定
                            break  # 内側ループを抜ける
                        available = is_stream_available(session, url, status_cb)  # 配信中判定
                        if available:  # 配信が継続している場合
                            message = "ストリームが一時的に切断されました。再接続を試みます。"  # 再接続通知
                            if status_cb is not None:  # コールバックが指定されている場合
                                status_cb(message)  # 状態通知
                        else:  # 配信が終了している場合
                            message = "配信が終了したため録画を停止します。"  # 終了通知
                            if status_cb is not None:  # コールバックが指定されている場合
                                status_cb(message)  # 状態通知
                            stream_ended = True  # 終了フラグを設定
                        break  # 内側ループを抜ける
                    output_file.write(data)  # ファイルへ書き込み
                    total_written += len(data)  # 書き込みバイト数を加算
                    now = time.time()  # 現在時刻を取得
                    if now - last_flush_time >= FLUSH_INTERVAL_SEC:  # フラッシュ条件
                        output_file.flush()  # 出力をフラッシュ
                        last_flush_time = now  # 最終フラッシュ時刻を更新
            except StreamlinkError as exc:  # Streamlink例外を捕捉
                message = f"ストリーム読み取り中にエラーが発生しました: {exc}"  # エラー通知
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb(message)  # 状態通知
            finally:  # 後始末
                if stream_fd is not None:  # ストリームが開かれている場合
                    stream_fd.close()  # ストリームを閉じる
            if stream_ended:  # 配信終了の場合
                break  # 録画ループを終了
    finally:  # 後始末
        if output_file is not None:  # 出力ファイルがある場合
            output_file.close()  # 出力ファイルを閉じる
