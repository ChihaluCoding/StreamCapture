# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import os  # 環境変数
import re  # 拡張子判定
from datetime import datetime  # 日付フォルダ
import shutil  # 実行ファイル探索
import subprocess  # 外部コマンド実行
import threading  # 停止フラグ制御
import time  # 待機処理
from pathlib import Path  # パス操作
from typing import Callable, Optional  # 型ヒント補助
from streamlink import Streamlink  # Streamlink本体
from streamlink.exceptions import StreamlinkError  # Streamlink例外
from core.config import (  # 定数を読み込み
    DEFAULT_OUTPUT_FORMAT,  # 出力形式の既定値
    DEFAULT_QUALITY,  # 既定の画質指定
    DEFAULT_RECORDING_MAX_SIZE_MB,  # 録画サイズ上限の既定
    DEFAULT_RECORDING_SIZE_MARGIN_MB,  # 録画サイズ余裕の既定
    DEFAULT_AUTO_COMPRESS_MAX_HEIGHT,  # 自動圧縮の最大解像度既定
    DEFAULT_AUTO_COMPRESS_FPS,  # 自動圧縮のFPS既定値
    DEFAULT_YOUTUBE_RECORDING_BACKEND,  # YouTube録画方式の既定値
    FLUSH_INTERVAL_SEC,  # 定期フラッシュ間隔
    OUTPUT_FORMAT_FLV,  # 出力形式: FLV
    OUTPUT_FORMAT_MKV,  # 出力形式: MKV
    OUTPUT_FORMAT_MOV,  # 出力形式: MOV
    OUTPUT_FORMAT_MP3,  # 出力形式: MP3
    OUTPUT_FORMAT_WAV,  # 出力形式: WAV
    OUTPUT_FORMAT_MP4_COPY,  # 出力形式: MP4高速コピー
    OUTPUT_FORMAT_MP4_LIGHT,  # 出力形式: MP4軽量再エンコード
    OUTPUT_FORMAT_TS,  # 出力形式: TS
    READ_CHUNK_SIZE,  # 読み取りチャンクサイズ
)  # 定数読み込みの終了
from apis.api_youtube import build_youtube_live_page_url, resolve_youtube_live_url_by_redirect
from utils.platform_utils import normalize_youtube_entry
from utils.url_utils import (  # URL関連ユーティリティを読み込み
    build_default_recording_name,  # 既定ファイル名生成
    ensure_unique_path,  # パス重複回避
    safe_filename_component,  # ファイル名安全化
    derive_channel_label,  # 配信者ラベル推定
)
from utils.ytdlp_utils import (
    fetch_stream_url_with_ytdlp,
    fetch_stream_urls_with_ytdlp,
    is_ytdlp_available,
)  # yt-dlp補助
from utils.settings_store import load_bool_setting, load_setting_value  # 設定読み込み

def find_ffmpeg_path() -> Optional[str]:  # ffmpegのパスを解決
    env_path = os.environ.get("FFMPEG_PATH", "").strip()  # 環境変数優先
    if env_path and Path(env_path).exists():
        return env_path
    preferred = Path("C:/ffmpeg/bin/ffmpeg.exe")  # 既定の優先パス
    if preferred.exists():
        return str(preferred)
    return shutil.which("ffmpeg")  # PATHを検索

def find_whisper_path() -> Optional[str]:  # Whisper CLIのパスを解決
    for name in ("whisper", "whisper.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None

def transcribe_recording(  # 録画後の文字起こし
    input_path: Path,
    model: str,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    if not input_path.exists():
        message = f"文字起こし対象ファイルが存在しません: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    whisper_path = find_whisper_path()
    if not whisper_path:
        message = "文字起こしにはWhisper CLIが必要です。'pip install -U openai-whisper' を実行してください。"
        if status_cb is not None:
            status_cb(message)
        return None
    output_path = input_path.with_suffix(".srt")
    if output_path.exists():
        if status_cb is not None:
            status_cb(f"文字起こし結果が既に存在するためスキップします: {output_path}")
        return output_path
    safe_model = (model or "small").strip() or "small"
    command = [
        whisper_path,
        str(input_path),
        "--model",
        safe_model,
        "--task",
        "transcribe",
        "--output_format",
        "srt",
        "--output_dir",
        str(output_path.parent),
        "--fp16",
        "False",
    ]
    if status_cb is not None:
        status_cb(f"文字起こしを開始します: {output_path}")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        stderr_text = "\n".join(result.stderr.strip().splitlines()[-15:]) if result.stderr else "詳細不明"
        message = f"文字起こしに失敗しました: {stderr_text}"
        if status_cb is not None:
            status_cb(message)
        return None
    if output_path.exists():
        if status_cb is not None:
            status_cb(f"文字起こしが完了しました: {output_path}")
        return output_path
    if status_cb is not None:
        status_cb("文字起こしの出力が見つかりませんでした。")
    return None

def _has_valid_extension(name: str) -> bool:  # 拡張子の妥当性確認
    suffix = Path(name).suffix
    return bool(re.match(r"^\.[A-Za-z0-9]{1,5}$", suffix))

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
    if load_bool_setting("output_date_folder_enabled", False):
        date_folder = datetime.now().strftime("%Y-%m-%d")
        output_dir = output_dir / date_folder
    output_dir.mkdir(parents=True, exist_ok=True)  # 出力先を確保
    if filename:  # ファイル名が指定された場合
        name = filename  # 指定名を使用
    else:  # 自動生成する場合
        name = build_default_recording_name()  # 既定の録画名を生成
        if load_bool_setting("output_filename_with_channel", False):
            label_source = channel_label or (derive_channel_label(url) if url else "")
            safe_label = safe_filename_component(label_source)
            if safe_label:
                name = f"{safe_label}_{name}"
    if not _has_valid_extension(name):  # 拡張子が無い/不正な場合
        name = f"{name}.ts"  # TS拡張子を補完
    candidate = output_dir / name  # 出力候補パスを生成
    return ensure_unique_path(candidate)  # 重複回避したパスを返却

def normalize_output_format(output_format: str) -> str:  # 出力形式の正規化
    cleaned = str(output_format).strip().lower()  # 文字列を正規化
    if cleaned in (
        OUTPUT_FORMAT_TS,
        OUTPUT_FORMAT_MP4_COPY,
        OUTPUT_FORMAT_MP4_LIGHT,
        OUTPUT_FORMAT_MOV,
        OUTPUT_FORMAT_FLV,
        OUTPUT_FORMAT_MKV,
        OUTPUT_FORMAT_MP3,
        OUTPUT_FORMAT_WAV,
    ):  # 対応形式の場合
        return cleaned  # 正規化済み形式を返却
    return DEFAULT_OUTPUT_FORMAT  # 既定形式にフォールバック

def build_output_path(input_path: Path, suffix: str) -> Path:  # 出力パス生成
    base = input_path.with_suffix("")  # 拡張子を除いたベース
    candidate = input_path.with_suffix(suffix)  # 既定の出力パス
    if not candidate.exists():  # 既定パスが未使用の場合
        return candidate  # 既定パスを返却
    for index in range(1, 1000):  # 衝突回避の連番
        candidate = base.with_name(f"{base.name}_{index}").with_suffix(suffix)  # 連番付きパス
        if not candidate.exists():  # 未使用のパスが見つかった場合
            return candidate  # そのパスを返却
    return base.with_name(f"{base.name}_overflow").with_suffix(suffix)  # 最終手段のパス

def build_mp4_output_path(input_path: Path) -> Path:  # MP4出力パス生成
    return build_output_path(input_path, ".mp4")

def build_compressed_output_path(input_path: Path) -> Path:  # 圧縮後の出力パス生成
    base = input_path.with_suffix("")  # 拡張子を除いたベース
    candidate = base.with_name(f"{base.name}_compressed").with_suffix(".mp4")
    if not candidate.exists():
        return candidate
    for index in range(1, 1000):
        numbered = base.with_name(f"{base.name}_compressed_{index}").with_suffix(".mp4")
        if not numbered.exists():
            return numbered
    return base.with_name(f"{base.name}_compressed_overflow").with_suffix(".mp4")

def _resolve_watermark_path(status_cb: Optional[Callable[[str], None]]) -> Optional[Path]:
    raw_path = load_setting_value("watermark_path", "", str).strip()
    if not raw_path:
        if status_cb is not None:
            status_cb("ロゴ透かしが有効ですが、ロゴ画像が未指定です。")
        return None
    path = Path(raw_path).expanduser()
    if not path.exists():
        if status_cb is not None:
            status_cb(f"ロゴ画像が見つかりません: {path}")
        return None
    return path

def _escape_drawtext_text(text: str) -> str:
    escaped = text.replace("\\", "\\\\")
    escaped = escaped.replace(":", "\\:")
    escaped = escaped.replace("'", "\\'")
    escaped = escaped.replace("%", "\\%")
    return escaped

def _apply_text_watermark(
    input_path: Path,
    output_path: Path,
    text: str,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    if not input_path.exists():
        message = f"透かし対象ファイルが存在しません: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    if input_path.stat().st_size == 0:
        message = f"透かし対象ファイルが空です: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    ffmpeg_path = find_ffmpeg_path()
    if not ffmpeg_path:
        message = "ffmpegが見つかりません。PATHにffmpegを追加してください。"
        if status_cb is not None:
            status_cb(message)
        return None
    margin = int(load_setting_value("watermark_margin_px", 16, int))
    margin = max(0, margin)
    random_enabled = load_bool_setting("watermark_random_enabled", False)
    interval = max(1, int(load_setting_value("watermark_random_interval_sec", 5, int)))
    opacity = float(load_setting_value("watermark_opacity", 1.0, float))
    opacity = max(0.0, min(1.0, opacity))
    text_size = float(load_setting_value("watermark_text_size_percent", 3.0, float))
    size_ratio = max(0.01, min(0.2, text_size / 100.0))
    escaped_text = _escape_drawtext_text(text)
    fontcolor = f"white@{opacity:.2f}"
    position = load_setting_value("watermark_position", "br", str).strip().lower() or "br"
    if random_enabled:
        seed = int(time.time())
        t_expr = f"(floor(t/{interval})+{seed})"
        x_expr = (
            f"{margin}+max(0\\,w-tw-2*{margin})*"
            f"mod(({t_expr})*0.7548776662466927 + ({t_expr})*0.00337\\,1)"
        )
        y_expr = (
            f"{margin}+max(0\\,h-th-2*{margin})*"
            f"mod(({t_expr})*0.5698402909980532 + ({t_expr})*0.00731\\,1)"
        )
    else:
        if position == "tl":
            x_expr = f"{margin}"
            y_expr = f"{margin}"
        elif position == "tr":
            x_expr = f"w-tw-{margin}"
            y_expr = f"{margin}"
        elif position == "bl":
            x_expr = f"{margin}"
            y_expr = f"h-th-{margin}"
        else:
            x_expr = f"w-tw-{margin}"
            y_expr = f"h-th-{margin}"
    filter_graph = (
        "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[base];"
        f"[base]drawtext=text='{escaped_text}':"
        f"x={x_expr}:y={y_expr}:"
        f"fontsize=trunc(w*{size_ratio}):"
        f"fontcolor={fontcolor}[v]"
    )
    temp_output = ensure_unique_path(
        output_path.with_name(f"{output_path.stem}_watermark_tmp{output_path.suffix}")
    )
    message = f"透かし合成を開始します: {output_path}"
    if status_cb is not None:
        status_cb(message)
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        filter_graph,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
    ]
    if temp_output.suffix.lower() in (".mp4", ".mov"):
        command += ["-movflags", "+faststart"]
    command.append(str(temp_output))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)
        stderr_text = "\n".join(result.stderr.strip().splitlines()[-15:]) if result.stderr else "詳細不明"
        message = f"透かし合成に失敗しました: {stderr_text}"
        if status_cb is not None:
            status_cb(message)
        return None
    if not temp_output.exists() or temp_output.stat().st_size == 0:
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)
        if status_cb is not None:
            status_cb("透かし合成の出力が空のため失敗扱いにします。")
        return None
    try:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        temp_output.replace(output_path)
    except OSError as exc:
        if status_cb is not None:
            status_cb(f"透かし合成後のファイル移動に失敗しました: {exc}")
        return None
    message = f"透かし合成が完了しました: {output_path}"
    if status_cb is not None:
        status_cb(message)
    return output_path

def _build_output_path_for_format(input_path: Path, output_format: str) -> Path:
    if output_format in (OUTPUT_FORMAT_MP4_COPY, OUTPUT_FORMAT_MP4_LIGHT):
        return build_output_path(input_path, ".mp4")
    if output_format == OUTPUT_FORMAT_MOV:
        return build_output_path(input_path, ".mov")
    if output_format == OUTPUT_FORMAT_FLV:
        return build_output_path(input_path, ".flv")
    if output_format == OUTPUT_FORMAT_MKV:
        return build_output_path(input_path, ".mkv")
    return build_mp4_output_path(input_path)

def _apply_watermark(  # 透かし合成
    input_path: Path,
    output_path: Path,
    watermark_path: Path,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    if not input_path.exists():
        message = f"透かし対象ファイルが存在しません: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    if input_path.stat().st_size == 0:
        message = f"透かし対象ファイルが空です: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    ffmpeg_path = find_ffmpeg_path()
    if not ffmpeg_path:
        message = "ffmpegが見つかりません。PATHにffmpegを追加してください。"
        if status_cb is not None:
            status_cb(message)
        return None
    margin = int(load_setting_value("watermark_margin_px", 16, int))
    margin = max(0, margin)
    random_enabled = load_bool_setting("watermark_random_enabled", False)
    interval = max(1, int(load_setting_value("watermark_random_interval_sec", 5, int)))
    opacity = float(load_setting_value("watermark_opacity", 1.0, float))
    opacity = max(0.0, min(1.0, opacity))
    scale_percent = float(load_setting_value("watermark_scale_percent", 13.0, float))
    scale_ratio = max(0.01, min(1.0, scale_percent / 100.0))
    position = load_setting_value("watermark_position", "br", str).strip().lower() or "br"
    if random_enabled:
        seed = int(time.time())
        t_expr = f"(floor(t/{interval})+{seed})"
        x_expr = (
            f"{margin}+max(0\\,W-w-2*{margin})*"
            f"mod(({t_expr})*0.7548776662466927 + ({t_expr})*0.00337\\,1)"
        )
        y_expr = (
            f"{margin}+max(0\\,H-h-2*{margin})*"
            f"mod(({t_expr})*0.5698402909980532 + ({t_expr})*0.00731\\,1)"
        )
    else:
        if position == "tl":
            x_expr = f"{margin}"
            y_expr = f"{margin}"
        elif position == "tr":
            x_expr = f"W-w-{margin}"
            y_expr = f"{margin}"
        elif position == "bl":
            x_expr = f"{margin}"
            y_expr = f"H-h-{margin}"
        else:
            x_expr = f"W-w-{margin}"
            y_expr = f"H-h-{margin}"
    filter_graph = (
        "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=rgba[base];"
        f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wmraw];"
        f"[wmraw][base]scale2ref=w=trunc(main_w*{scale_ratio}):h=trunc(ow/mdar)[wm][base2];"
        f"[base2][wm]overlay={x_expr}:{y_expr},format=yuv420p[v]"
    )
    temp_output = ensure_unique_path(
        output_path.with_name(f"{output_path.stem}_watermark_tmp{output_path.suffix}")
    )
    message = f"透かし合成を開始します: {output_path}"
    if status_cb is not None:
        status_cb(message)
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-loop",
        "1",
        "-i",
        str(watermark_path),
        "-filter_complex",
        filter_graph,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
    ]
    if temp_output.suffix.lower() in (".mp4", ".mov"):
        command += ["-movflags", "+faststart"]
    command.append(str(temp_output))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)
        stderr_text = "\n".join(result.stderr.strip().splitlines()[-15:]) if result.stderr else "詳細不明"
        message = f"透かし合成に失敗しました: {stderr_text}"
        if status_cb is not None:
            status_cb(message)
        return None
    if not temp_output.exists() or temp_output.stat().st_size == 0:
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)
        if status_cb is not None:
            status_cb("透かし合成の出力が空のため失敗扱いにします。")
        return None
    try:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        temp_output.replace(output_path)
    except OSError as exc:
        if status_cb is not None:
            status_cb(f"透かし合成後のファイル移動に失敗しました: {exc}")
        return None
    message = f"透かし合成が完了しました: {output_path}"
    if status_cb is not None:
        status_cb(message)
    return output_path

def build_segment_output_path(base_path: Path, index: int) -> Path:  # 分割録画の出力パス生成
    if index <= 0:
        return base_path
    stem = base_path.with_suffix("").name
    suffix = base_path.suffix
    candidate = base_path.with_name(f"{stem}_{index:03d}{suffix}")
    return ensure_unique_path(candidate)

def delete_source_ts(  # 変換後のTS削除処理
    input_path: Path,  # 入力パス
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> None:  # 返り値なし
    if load_bool_setting("keep_ts_file", False):  # TS保持設定
        if status_cb is not None:
            status_cb("設定によりTSファイルを保持します。")
        return
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
    ffmpeg_path = find_ffmpeg_path()  # ffmpegのパスを探索
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
    ffmpeg_path = find_ffmpeg_path()  # ffmpegのパスを探索
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

def convert_to_container_copy(  # コンテナ変換（コピー）
    input_path: Path,  # 入力パス
    suffix: str,  # 出力拡張子
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> Optional[Path]:  # 返り値は出力パス
    if not input_path.exists():  # 入力ファイルが無い場合
        message = f"変換対象ファイルが存在しません: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    if input_path.stat().st_size == 0:  # サイズがゼロの場合
        message = f"変換対象ファイルが空です: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    ffmpeg_path = find_ffmpeg_path()
    if not ffmpeg_path:
        message = "ffmpegが見つかりません。PATHにffmpegを追加してください。"
        if status_cb is not None:
            status_cb(message)
        return None
    output_path = build_output_path(input_path, suffix)
    message = f"{suffix[1:].upper()}変換を開始します: {output_path}"
    if status_cb is not None:
        status_cb(message)
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-c",
        "copy",
        str(output_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        stderr_text = "\n".join(result.stderr.strip().splitlines()[-5:]) if result.stderr else "詳細不明"
        message = f"{suffix[1:].upper()}変換に失敗しました: {stderr_text}"
        if status_cb is not None:
            status_cb(message)
        return None
    message = f"{suffix[1:].upper()}変換が完了しました: {output_path}"
    if status_cb is not None:
        status_cb(message)
    delete_source_ts(input_path, status_cb=status_cb)
    return output_path

def convert_to_audio(  # 音声変換処理
    input_path: Path,  # 入力パス
    suffix: str,  # 出力拡張子
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> Optional[Path]:  # 返り値は出力パス
    if not input_path.exists():
        message = f"変換対象ファイルが存在しません: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    if input_path.stat().st_size == 0:
        message = f"変換対象ファイルが空です: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    ffmpeg_path = find_ffmpeg_path()
    if not ffmpeg_path:
        message = "ffmpegが見つかりません。PATHにffmpegを追加してください。"
        if status_cb is not None:
            status_cb(message)
        return None
    output_path = build_output_path(input_path, suffix)
    fmt_label = suffix[1:].upper()
    message = f"{fmt_label}変換を開始します: {output_path}"
    if status_cb is not None:
        status_cb(message)
    audio_codec = "libmp3lame" if suffix == ".mp3" else "pcm_s16le"
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-c:a",
        audio_codec,
        "-b:a",
        "192k",
        str(output_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        stderr_text = "\n".join(result.stderr.strip().splitlines()[-5:]) if result.stderr else "詳細不明"
        message = f"{fmt_label}変換に失敗しました: {stderr_text}"
        if status_cb is not None:
            status_cb(message)
        return None
    message = f"{fmt_label}変換が完了しました: {output_path}"
    if status_cb is not None:
        status_cb(message)
    delete_source_ts(input_path, status_cb=status_cb)
    return output_path

def convert_recording(  # 出力形式に合わせた変換
    input_path: Path,  # 入力パス
    output_format: str,  # 出力形式指定
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> Optional[Path]:  # 返り値は出力パス
    normalized_format = normalize_output_format(output_format)  # 出力形式を正規化
    watermark_enabled = load_bool_setting("watermark_enabled", False)
    watermark_mode = load_setting_value("watermark_mode", "image", str).strip().lower() or "image"
    if normalized_format == OUTPUT_FORMAT_TS:  # TS指定の場合
        if watermark_enabled and status_cb is not None:
            status_cb("透かし合成はTS形式では適用できないためスキップします。")
        message = f"TS形式のため変換をスキップします: {input_path}"  # スキップ通知
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb(message)  # 状態通知
        return input_path  # TSはそのまま返却
    if watermark_enabled and normalized_format not in (OUTPUT_FORMAT_MP3, OUTPUT_FORMAT_WAV):
        output_path = _build_output_path_for_format(input_path, normalized_format)
        if watermark_mode == "text":
            watermark_text = load_setting_value("watermark_text", "", str).strip()
            if watermark_text:
                watermarked_path = _apply_text_watermark(
                    input_path,
                    output_path,
                    watermark_text,
                    status_cb=status_cb,
                )
                if watermarked_path is not None:
                    delete_source_ts(input_path, status_cb=status_cb)
                    return watermarked_path
                if status_cb is not None:
                    status_cb("透かし合成に失敗したため通常変換を続行します。")
            elif status_cb is not None:
                status_cb("透かしテキストが未入力のため通常変換を続行します。")
        else:
            watermark_path = _resolve_watermark_path(status_cb)
            if watermark_path is not None:
                watermarked_path = _apply_watermark(input_path, output_path, watermark_path, status_cb=status_cb)
                if watermarked_path is not None:
                    delete_source_ts(input_path, status_cb=status_cb)
                    return watermarked_path
                if status_cb is not None:
                    status_cb("透かし合成に失敗したため通常変換を続行します。")
    if normalized_format == OUTPUT_FORMAT_MP4_COPY and input_path.suffix.lower() == ".mp4":
        message = f"MP4形式のため変換をスキップします: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return input_path
    if normalized_format == OUTPUT_FORMAT_MP4_LIGHT:  # 軽量MP4指定の場合
        return convert_to_mp4_light(input_path, status_cb=status_cb)  # 軽量変換を実行
    if normalized_format == OUTPUT_FORMAT_MOV:  # MOV指定
        return convert_to_container_copy(input_path, ".mov", status_cb=status_cb)
    if normalized_format == OUTPUT_FORMAT_FLV:  # FLV指定
        return convert_to_container_copy(input_path, ".flv", status_cb=status_cb)
    if normalized_format == OUTPUT_FORMAT_MKV:  # MKV指定
        return convert_to_container_copy(input_path, ".mkv", status_cb=status_cb)
    if normalized_format == OUTPUT_FORMAT_MP3:  # MP3指定
        return convert_to_audio(input_path, ".mp3", status_cb=status_cb)
    if normalized_format == OUTPUT_FORMAT_WAV:  # WAV指定
        return convert_to_audio(input_path, ".wav", status_cb=status_cb)
    return convert_to_mp4(input_path, status_cb=status_cb)  # 高品質コピーMP4を実行

def compress_recording(  # 録画後の自動圧縮
    input_path: Path,  # 入力パス
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> Optional[Path]:  # 返り値は出力パス
    if not input_path.exists():
        message = f"圧縮対象ファイルが存在しません: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    if input_path.stat().st_size == 0:
        message = f"圧縮対象ファイルが空です: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return None
    if input_path.suffix.lower() in (".mp3", ".wav"):
        message = f"音声ファイルは圧縮をスキップします: {input_path}"
        if status_cb is not None:
            status_cb(message)
        return input_path
    ffmpeg_path = find_ffmpeg_path()
    if not ffmpeg_path:
        message = "ffmpegが見つかりません。PATHにffmpegを追加してください。"
        if status_cb is not None:
            status_cb(message)
        return None
    codec = load_setting_value("auto_compress_codec", "libx265", str).strip() or "libx265"
    preset = load_setting_value("auto_compress_preset", "medium", str).strip() or "medium"
    max_height = int(load_setting_value("auto_compress_max_height", DEFAULT_AUTO_COMPRESS_MAX_HEIGHT, int))
    target_fps = int(load_setting_value("auto_compress_fps", DEFAULT_AUTO_COMPRESS_FPS, int))
    video_bitrate = int(load_setting_value("auto_compress_video_bitrate_kbps", 2500, int))
    audio_bitrate = int(load_setting_value("auto_compress_audio_bitrate_kbps", 128, int))
    keep_original = load_bool_setting("auto_compress_keep_original", True)
    output_path = build_compressed_output_path(input_path)
    message = f"録画後の自動圧縮を開始します: {output_path}"
    if status_cb is not None:
        status_cb(message)
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
    ]
    filters: list[str] = []
    if max_height > 0:
        filters.append(f"scale=-2:min(ih\\,{max_height})")
    if target_fps > 0:
        filters.append(f"fps={target_fps}")
    if filters:
        command += [
            "-vf",
            ",".join(filters),
        ]
    command += [
        "-c:v",
        codec,
        "-preset",
        preset,
        "-b:v",
        f"{max(1, video_bitrate)}k",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        f"{max(1, audio_bitrate)}k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    if codec == "libx265":
        try:
            flag_index = command.index("-movflags")
        except ValueError:
            flag_index = len(command) - 1
        command.insert(flag_index, "hvc1")
        command.insert(flag_index, "-tag:v")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        stderr_text = "\n".join(result.stderr.strip().splitlines()[-5:]) if result.stderr else "詳細不明"
        message = f"録画後の自動圧縮に失敗しました: {stderr_text}"
        if status_cb is not None:
            status_cb(message)
        return None
    message = f"録画後の自動圧縮が完了しました: {output_path}"
    if status_cb is not None:
        status_cb(message)
    if not keep_original:
        try:
            input_path.unlink()
            if status_cb is not None:
                status_cb(f"元のファイルを削除しました: {input_path}")
        except OSError as exc:
            if status_cb is not None:
                status_cb(f"元のファイル削除に失敗しました: {exc}")
    return output_path

def select_stream(available_streams: dict, quality: str):  # ストリーム選択
    requested = str(quality).strip().lower()
    if requested in available_streams:  # 希望画質が存在する場合
        return available_streams[requested]  # その画質を返却
    if requested.endswith("p"):  # 例: 1440p -> 1440p60 などを許容
        candidates: list[tuple[int, str]] = []
        for key in available_streams:
            key_lower = str(key).strip().lower()
            if key_lower.startswith(requested):
                suffix = key_lower.removeprefix(requested)
                match = re.match(r"(\d+)", suffix)
                score = int(match.group(1)) if match else 0
                candidates.append((score, key))
        if candidates:
            candidates.sort(reverse=True)
            return available_streams[candidates[0][1]]
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
    is_whowatch = "whowatch.tv" in url  # ふわっちURL判定
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
            if "No plugin can handle URL" in str(exc):  # 未対応URLの場合
                raise RuntimeError("StreamlinkがこのURLに対応していません。") from exc  # 即時フォールバック
            if is_whowatch and is_ytdlp_available():  # ふわっちはyt-dlpへ切替
                raise RuntimeError("Streamlinkで取得に失敗したためyt-dlpに切り替えます。") from exc
            streams = {}  # 空辞書に退避
        if streams:  # ストリームが取得できた場合
            if status_cb is not None and attempt == 1:
                available_keys = ", ".join(str(key) for key in streams.keys())
                status_cb(f"利用可能な画質: {available_keys}")
            stream = select_stream(streams, quality)  # ストリームを選択
            if status_cb is not None:
                selected_key = next((key for key, value in streams.items() if value is stream), None)
                if selected_key is not None:
                    status_cb(f"選択された画質: {selected_key}")
            return stream  # 選択結果を返却
        if is_whowatch and is_ytdlp_available():  # ふわっちは空の場合も即切替
            raise RuntimeError("Streamlinkでストリームが見つからないためyt-dlpに切り替えます。")
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

def _build_ytdlp_format_selector(quality: str, prefer_vp9: bool = False) -> str:
    cleaned = str(quality or "").strip().lower()
    if not cleaned:
        return "bestvideo+bestaudio/best"
    if cleaned == "audio_only":
        return "bestaudio"
    if cleaned in ("best", "worst"):
        if cleaned == "worst":
            return "worst"
        if prefer_vp9:
            return "bestvideo[vcodec^=vp9]+bestaudio/best"
        return "bestvideo+bestaudio/best"
    match = re.match(r"(\d+)", cleaned)
    if match:
        height = int(match.group(1))
        if prefer_vp9:
            return (
                f"bestvideo[vcodec^=vp9][height<={height}]+bestaudio/"
                f"bestvideo[height<={height}]+bestaudio/"
                f"best[height<={height}]"
            )
        return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
    if prefer_vp9:
        return "bestvideo[vcodec^=vp9]+bestaudio/best"
    return "bestvideo+bestaudio/best"

def _resolve_youtube_watch_url(url: str, status_cb: Optional[Callable[[str], None]]) -> Optional[str]:
    kind, _ = normalize_youtube_entry(url)
    if kind == "video":
        return url
    live_page_url = build_youtube_live_page_url(url)
    if not live_page_url:
        return None
    log_cb = status_cb or (lambda _msg: None)
    resolved = resolve_youtube_live_url_by_redirect(live_page_url, log_cb=log_cb)
    if resolved and status_cb is not None:
        status_cb(f"YouTubeライブURLを解決しました: {resolved}")
    return resolved


def _record_stream_with_ytdlp(  # yt-dlpで録画処理
    url: str,  # 配信URL
    output_path: Path,  # 出力パス
    stop_event: Optional[threading.Event],  # 停止フラグ
    status_cb: Optional[Callable[[str], None]],  # 状態通知コールバック
    quality: str = "best",  # 画質指定
    prefer_vp9: bool = False,  # VP9優先
) -> list[Path]:  # 出力パス一覧を返却
    if not is_ytdlp_available():  # yt-dlpが無い場合
        return []  # 何もしない
    format_selector = _build_ytdlp_format_selector(quality, prefer_vp9=prefer_vp9)
    stream_urls = fetch_stream_urls_with_ytdlp(url, format_selector, status_cb, stop_event=stop_event)
    if not stream_urls:  # 取得失敗時
        return []  # 失敗を返却
    if len(stream_urls) >= 2:
        output_path = output_path.with_suffix(".mp4")
    stream_url = stream_urls[0]
    audio_url = stream_urls[1] if len(stream_urls) >= 2 else None
    ffmpeg_path = find_ffmpeg_path()  # ffmpegを探索
    if not ffmpeg_path:  # ffmpegが無い場合
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb("ffmpegが見つかりません。PATHにffmpegを追加してください。")  # 通知
        return []  # 失敗を返却
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb("yt-dlpの配信URLで録画を試行します。")  # フォールバック通知
    max_mb = int(load_setting_value("recording_max_size_mb", DEFAULT_RECORDING_MAX_SIZE_MB, int))
    margin_mb = int(load_setting_value("recording_size_margin_mb", DEFAULT_RECORDING_SIZE_MARGIN_MB, int))
    max_bytes = max_mb * 1024 * 1024 if max_mb > 0 else 0
    margin_bytes = margin_mb * 1024 * 1024 if margin_mb > 0 else 0
    threshold = max_bytes - margin_bytes if max_bytes > 0 else 0
    if max_bytes > 0 and threshold <= 0:
        threshold = max_bytes
    segment_paths: list[Path] = []
    segment_index = 0
    while True:
        if should_stop(stop_event):
            break
        segment_path = build_segment_output_path(output_path, segment_index)
        segment_paths.append(segment_path)
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
        ]  # コマンド定義終了
        if audio_url:
            command += [
                "-i",
                audio_url,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(segment_path),
            ]
        else:
            command += [
                "-c",  # コーデック指定
                "copy",  # コピー
                "-f",  # 出力フォーマット指定
                "mpegts",  # TS出力
                str(segment_path),  # 出力パス
            ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stopped = False
        rotated = False
        try:
            while process.poll() is None:
                if should_stop(stop_event):
                    stopped = True
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
                if threshold > 0 and segment_path.exists():
                    if segment_path.stat().st_size >= threshold:
                        rotated = True
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        break
                time.sleep(0.2)
        finally:
            try:
                _, stderr = process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                _, stderr = process.communicate()
            if process.returncode not in (0, None) and not stopped and not rotated:
                stderr_text = stderr or ""
                if "Unrecognized option 'reconnect'" in stderr_text:
                    if status_cb is not None:
                        status_cb("ffmpegが-reconnectに未対応のため再試行します。")
                    fallback_command = [
                        ffmpeg_path,
                        "-y",
                        "-loglevel",
                        "error",
                    ]
                    if audio_url:
                        fallback_command += [
                            "-i",
                            stream_url,
                            "-i",
                            audio_url,
                            "-map",
                            "0:v:0",
                            "-map",
                            "1:a:0",
                            "-c",
                            "copy",
                            "-movflags",
                            "+faststart",
                            str(segment_path),
                        ]
                    else:
                        fallback_command += [
                            "-i",
                            stream_url,
                            "-c",
                            "copy",
                            "-f",
                            "mpegts",
                            str(segment_path),
                        ]
                    retry = subprocess.run(
                        fallback_command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    if retry.returncode == 0:
                        return segment_paths
                    retry_tail = "\n".join((retry.stderr or "").splitlines()[-5:]) if retry.stderr else "詳細不明"
                    if status_cb is not None:
                        status_cb(f"yt-dlp経由の録画に失敗しました: {retry_tail}")
                    return segment_paths
                tail = "\n".join(stderr_text.splitlines()[-5:]) if stderr_text else "詳細不明"
                if status_cb is not None:
                    status_cb(f"yt-dlp経由の録画に失敗しました: {tail}")
                return segment_paths
        if stopped:
            if status_cb is not None:
                status_cb("停止要求を受け付けました。録画を終了します。")
            break
        if not rotated:
            break
        if status_cb is not None:
            status_cb(f"録画サイズ上限のため分割します: {segment_path}")
        segment_index += 1
    return segment_paths


def record_stream(  # 録画処理
    session: Streamlink,  # Streamlinkセッション
    url: str,  # 配信URL
    quality: str,  # 画質指定
    output_path: Path,  # 出力パス
    retry_count: int,  # リトライ回数
    retry_wait: int,  # リトライ待機秒
    stop_event: Optional[threading.Event] = None,  # 停止フラグ
    status_cb: Optional[Callable[[str], None]] = None,  # 状態通知コールバック
) -> list[Path]:  # 関数定義終了
    start_message = f"録画開始: {url}"  # 開始通知メッセージ
    output_message = f"出力先: {output_path}"  # 出力先通知メッセージ
    if status_cb is not None:  # コールバックが指定されている場合
        status_cb(start_message)  # 開始通知
        status_cb(output_message)  # 出力先通知
    if ("youtube.com" in url or "youtu.be" in url) and is_ytdlp_available():
        youtube_backend = load_setting_value(
            "youtube_recording_backend",
            DEFAULT_YOUTUBE_RECORDING_BACKEND,
            str,
        ).strip().lower()
        if youtube_backend == "ytdlp":
            if status_cb is not None:
                status_cb("YouTubeはyt-dlpで録画します。")
            resolved_url = _resolve_youtube_watch_url(url, status_cb)
            if not resolved_url:
                if status_cb is not None:
                    status_cb("YouTubeライブURLの解決に失敗しました。Streamlinkに切り替えます。")
            else:
                segment_paths = _record_stream_with_ytdlp(
                    resolved_url,
                    output_path,
                    stop_event,
                    status_cb,
                    quality=quality,
                    prefer_vp9=False,
                )
                if segment_paths:
                    return segment_paths
            segment_paths = _record_stream_with_ytdlp(
                url,
                output_path,
                stop_event,
                status_cb,
                quality=quality,
                prefer_vp9=False,
            )
            if segment_paths:
                return segment_paths
            if status_cb is not None:
                status_cb("yt-dlpで録画できませんでした。Streamlinkに切り替えます。")
    if "whowatch.tv" in url and is_ytdlp_available():  # ふわっちはyt-dlpで録画
        if status_cb is not None:  # コールバックが指定されている場合
            status_cb("ふわっちはyt-dlpで録画を開始します。")  # 方式通知
        segment_paths = _record_stream_with_ytdlp(url, output_path, stop_event, status_cb, quality=quality)
        if not segment_paths and status_cb is not None:
            status_cb("yt-dlpで録画できませんでした。")  # 失敗通知
        return segment_paths  # ふわっちはStreamlinkを使わない
    last_flush_time = time.time()  # 最終フラッシュ時刻
    total_written = 0  # 総書き込みバイト数を初期化
    output_file = None  # 出力ファイル参照
    segment_paths: list[Path] = []
    segment_index = 0
    segment_written = 0
    max_mb = int(load_setting_value("recording_max_size_mb", DEFAULT_RECORDING_MAX_SIZE_MB, int))
    margin_mb = int(load_setting_value("recording_size_margin_mb", DEFAULT_RECORDING_SIZE_MARGIN_MB, int))
    max_bytes = max_mb * 1024 * 1024 if max_mb > 0 else 0
    margin_bytes = margin_mb * 1024 * 1024 if margin_mb > 0 else 0
    threshold = max_bytes - margin_bytes if max_bytes > 0 else 0
    if max_bytes > 0 and threshold <= 0:
        threshold = max_bytes
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
                if status_cb is not None:  # コールバックが指定されている場合
                    status_cb("Streamlinkが失敗したためyt-dlpで録画を試行します。")  # フォールバック通知
                fallback_segments = _record_stream_with_ytdlp(url, output_path, stop_event, status_cb, quality=quality)
                if fallback_segments:  # yt-dlpへ切替
                    return fallback_segments  # ffmpeg録画に任せて終了
                break  # 録画ループを終了
            if stream is None:  # 停止によりストリームが取得できない場合
                break  # 録画ループを終了
            if output_file is None:  # 出力ファイルが未作成の場合
                segment_path = build_segment_output_path(output_path, segment_index)
                output_file = segment_path.open("ab", buffering=READ_CHUNK_SIZE)  # 出力ファイルを開く
                segment_paths.append(segment_path)
                segment_written = 0
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
                    if threshold > 0 and (segment_written + len(data)) > threshold and segment_written > 0:
                        output_file.flush()
                        output_file.close()
                        if status_cb is not None:
                            status_cb(f"録画サイズ上限のため分割します: {segment_paths[-1]}")
                        output_file = None
                        segment_index += 1
                        segment_written = 0
                        segment_path = build_segment_output_path(output_path, segment_index)
                        output_file = segment_path.open("ab", buffering=READ_CHUNK_SIZE)
                        segment_paths.append(segment_path)
                    output_file.write(data)  # ファイルへ書き込み
                    total_written += len(data)  # 書き込みバイト数を加算
                    segment_written += len(data)
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
    return segment_paths
