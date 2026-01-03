#!/usr/bin/env python3  # 実行用のシェバン指定
# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import sys  # アプリ終了コード
from PyQt6 import QtWidgets  # PyQt6のGUI基盤
from ui_app import MainWindow  # メインウィンドウを読み込み

def main() -> int:  # エントリポイント
    app = QtWidgets.QApplication(sys.argv)  # アプリケーション生成
    app.setApplicationName("配信録画くん")  # アプリ名設定
    app.setQuitOnLastWindowClosed(False)  # タスクトレイ常駐に備えて終了を抑制
    window = MainWindow()  # メインウィンドウ生成
    window.show()  # ウィンドウ表示
    return app.exec()  # イベントループ開始

if __name__ == "__main__":  # 直接実行時の分岐
    sys.exit(main())  # メイン処理実行
