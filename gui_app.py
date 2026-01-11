#!/usr/bin/env python3  # 実行用のシェバン指定
# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import sys  # アプリ終了コード
from pathlib import Path  # パス操作
from typing import Iterable  # 型ヒント補助
from PyQt6 import QtCore, QtGui, QtWidgets  # PyQt6のGUI基盤
from theme_utils import get_ui_font_family, load_ui_font_files, register_ui_font_files
from ui_app import MainWindow  # メインウィンドウを読み込み

class _FilteredStderr:  # 標準エラーのフィルタクラス
    def __init__(self, original, suppress_keywords: Iterable[str]) -> None:  # 初期化処理
        self._original = original  # 元のstderrを保持
        self._suppress_keywords = tuple(suppress_keywords)  # 抑制キーワードを保持
        self._buffer = ""  # 行バッファを初期化
        self.encoding = getattr(original, "encoding", "utf-8")  # 文字コード情報を保持
    def write(self, text: str) -> int:  # 書き込み処理
        if not text:  # 空文字の場合
            return 0  # 何も書かない
        self._buffer += text  # バッファへ追加
        while "\n" in self._buffer:  # 行区切りがある間
            line, self._buffer = self._buffer.split("\n", 1)  # 1行取り出し
            if any(keyword in line for keyword in self._suppress_keywords):  # 抑制対象の場合
                continue  # 出力しない
            self._original.write(f"{line}\n")  # 元stderrへ出力
        return len(text)  # 書き込み長を返却
    def flush(self) -> None:  # フラッシュ処理
        if self._buffer:  # 残りがある場合
            line = self._buffer  # 残り行を取得
            self._buffer = ""  # バッファをクリア
            if not any(keyword in line for keyword in self._suppress_keywords):  # 抑制対象でない場合
                self._original.write(line)  # 元stderrへ出力
        self._original.flush()  # 元stderrをフラッシュ
    def fileno(self) -> int:  # ファイル番号取得
        return self._original.fileno()  # 元stderrの番号を返却
    def isatty(self) -> bool:  # TTY判定
        return self._original.isatty()  # 元stderrの判定を返却

def _install_stderr_filter() -> None:  # stderrのフィルタを設定
    suppress = [  # 抑制対象のキーワード一覧
        "co located POCs unavailable",  # H.264の既知の警告
        "vt decoder cb: output image buffer is null",  # macOSのVideoToolbox警告
        "hardware accelerator failed to decode picture",  # macOSのHWデコード警告
    ]  # 抑制一覧の終了
    sys.stderr = _FilteredStderr(sys.stderr, suppress)  # stderrを差し替え


def main() -> int:  # エントリポイント
    QtCore.QLoggingCategory.setFilterRules(  # FFmpeg関連のQtログを抑制
        "qt.multimedia.ffmpeg=false\n"
        "qt.multimedia.ffmpeg.*=false"
    )  # ログ抑制設定の終了
    _install_stderr_filter()  # stderrの警告を抑制
    app = QtWidgets.QApplication(sys.argv)  # アプリケーション生成
    font_files = load_ui_font_files()
    if font_files:
        register_ui_font_files(font_files)
    font_family = get_ui_font_family().strip()
    if font_family:
        app.setFont(QtGui.QFont(font_family))
    app.setApplicationName("はいろく！")  # アプリ名設定
    app.setWindowIcon(QtGui.QIcon(str(Path(__file__).resolve().with_name("icon.png"))))  # アプリ全体のアイコン
    app.setQuitOnLastWindowClosed(False)  # タスクトレイ常駐に備えて終了を抑制
    window = MainWindow()  # メインウィンドウ生成
    window.show()  # ウィンドウ表示
    return app.exec()  # イベントループ開始

if __name__ == "__main__":  # 直接実行時の分岐
    sys.exit(main())  # メイン処理実行
