#!/usr/bin/env python3  # 実行用のシェバン指定
# -*- coding: utf-8 -*-  # 文字コード指定
from __future__ import annotations  # 型ヒントの将来互換対応
import sys  # アプリ終了コード
import threading  # 停止フラグ制御
from pathlib import Path  # パス操作
from PyQt6 import QtCore, QtGui, QtWidgets  # PyQt6の主要モジュール
from streamlink import Streamlink  # Streamlink本体
from record_live import (  # 録画処理の共有関数を利用
    DEFAULT_QUALITY,  # 既定画質
    DEFAULT_RETRY_COUNT,  # 既定リトライ回数
    DEFAULT_RETRY_WAIT_SEC,  # 既定リトライ待機
    record_stream,  # 録画関数
    resolve_output_path,  # 出力パス生成
)
# 区切り
# 区切り
class RecorderWorker(QtCore.QObject):  # 録画ワーカー定義
    log_signal = QtCore.pyqtSignal(str)  # ログ通知シグナル
    finished_signal = QtCore.pyqtSignal(int)  # 終了通知シグナル
# 区切り
    def __init__(  # 初期化処理
        self,  # 自身参照
        url: str,  # 配信URL
        quality: str,  # 画質指定
        output_path: Path,  # 出力パス
        retry_count: int,  # リトライ回数
        retry_wait: int,  # リトライ待機秒
        http_timeout: int,  # HTTPタイムアウト
        stream_timeout: int,  # ストリームタイムアウト
        stop_event: threading.Event,  # 停止フラグ
    ) -> None:  # 返り値なし
        super().__init__()  # 親クラス初期化
        self.url = url  # URLを保存
        self.quality = quality  # 画質を保存
        self.output_path = output_path  # 出力パスを保存
        self.retry_count = retry_count  # リトライ回数を保存
        self.retry_wait = retry_wait  # リトライ待機を保存
        self.http_timeout = http_timeout  # HTTPタイムアウトを保存
        self.stream_timeout = stream_timeout  # ストリームタイムアウトを保存
        self.stop_event = stop_event  # 停止フラグを保存
# 区切り
    def run(self) -> None:  # 録画処理実行
        session = Streamlink()  # Streamlinkセッション生成
        session.set_option("http-timeout", self.http_timeout)  # HTTPタイムアウト設定
        session.set_option("stream-timeout", self.stream_timeout)  # ストリームタイムアウト設定
# 区切り
        def status_cb(message: str) -> None:  # 状態通知用コールバック
            self.log_signal.emit(message)  # ログシグナル送信
# 区切り
        exit_code = 0  # 終了コードの初期化
        try:  # 例外処理開始
            record_stream(  # 録画関数を実行
                session=session,  # セッション指定
                url=self.url,  # URL指定
                quality=self.quality,  # 画質指定
                output_path=self.output_path,  # 出力パス指定
                retry_count=self.retry_count,  # リトライ回数指定
                retry_wait=self.retry_wait,  # リトライ待機指定
                stop_event=self.stop_event,  # 停止フラグ指定
                status_cb=status_cb,  # 状態通知コールバック
            )  # 録画実行終了
        except Exception as exc:  # 予期しない例外を捕捉
            status_cb(f"致命的なエラーが発生しました: {exc}")  # エラーメッセージ通知
            exit_code = 1  # 異常終了コードを設定
        self.finished_signal.emit(exit_code)  # 終了シグナル送信
# 区切り
# 区切り
class MainWindow(QtWidgets.QMainWindow):  # メインウィンドウ定義
    def __init__(self) -> None:  # 初期化処理
        super().__init__()  # 親クラス初期化
        self.setWindowTitle("配信録画くん")  # ウィンドウタイトル設定
        self.setMinimumSize(780, 520)  # 最小サイズ設定
        self.worker_thread: QtCore.QThread | None = None  # ワーカースレッド参照
        self.worker: RecorderWorker | None = None  # ワーカー参照
        self.stop_event: threading.Event | None = None  # 停止フラグ参照
        self._build_ui()  # UI構築
# 区切り
    def _build_ui(self) -> None:  # UI構築処理
        central = QtWidgets.QWidget()  # 中央ウィジェットを生成
        self.setCentralWidget(central)  # 中央ウィジェットを設定
        layout = QtWidgets.QVBoxLayout(central)  # メインレイアウトを作成
# 区切り
        form = QtWidgets.QFormLayout()  # 入力フォームレイアウト
        layout.addLayout(form)  # フォームを追加
# 区切り
        self.url_input = QtWidgets.QLineEdit()  # URL入力欄
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")  # プレースホルダ設定
        form.addRow("配信URL", self.url_input)  # フォーム行追加
# 区切り
        self.quality_input = QtWidgets.QLineEdit(DEFAULT_QUALITY)  # 画質入力欄
        form.addRow("画質", self.quality_input)  # フォーム行追加
# 区切り
        output_row = QtWidgets.QHBoxLayout()  # 出力ディレクトリ行
        self.output_dir_input = QtWidgets.QLineEdit("recordings")  # 出力ディレクトリ入力
        browse_button = QtWidgets.QPushButton("参照")  # 参照ボタン
        browse_button.clicked.connect(self._browse_output_dir)  # 参照イベント接続
        output_row.addWidget(self.output_dir_input)  # 入力欄追加
        output_row.addWidget(browse_button)  # ボタン追加
        form.addRow("出力フォルダ", output_row)  # フォーム行追加
# 区切り
        self.filename_input = QtWidgets.QLineEdit()  # ファイル名入力
        self.filename_input.setPlaceholderText("省略可")  # プレースホルダ設定
        form.addRow("ファイル名", self.filename_input)  # フォーム行追加
# 区切り
        self.retry_count_input = QtWidgets.QSpinBox()  # リトライ回数入力
        self.retry_count_input.setRange(0, 999)  # 範囲設定
        self.retry_count_input.setValue(DEFAULT_RETRY_COUNT)  # 初期値設定
        form.addRow("再接続回数", self.retry_count_input)  # フォーム行追加
# 区切り
        self.retry_wait_input = QtWidgets.QSpinBox()  # リトライ待機入力
        self.retry_wait_input.setRange(1, 3600)  # 範囲設定
        self.retry_wait_input.setValue(DEFAULT_RETRY_WAIT_SEC)  # 初期値設定
        form.addRow("再接続待機秒", self.retry_wait_input)  # フォーム行追加
# 区切り
        self.http_timeout_input = QtWidgets.QSpinBox()  # HTTPタイムアウト入力
        self.http_timeout_input.setRange(1, 300)  # 範囲設定
        self.http_timeout_input.setValue(20)  # 初期値設定
        form.addRow("HTTPタイムアウト秒", self.http_timeout_input)  # フォーム行追加
# 区切り
        self.stream_timeout_input = QtWidgets.QSpinBox()  # ストリームタイムアウト入力
        self.stream_timeout_input.setRange(1, 600)  # 範囲設定
        self.stream_timeout_input.setValue(60)  # 初期値設定
        form.addRow("ストリームタイムアウト秒", self.stream_timeout_input)  # フォーム行追加
# 区切り
        button_row = QtWidgets.QHBoxLayout()  # ボタン行レイアウト
        self.start_button = QtWidgets.QPushButton("録画開始")  # 開始ボタン
        self.stop_button = QtWidgets.QPushButton("録画停止")  # 停止ボタン
        self.stop_button.setEnabled(False)  # 停止ボタンを無効化
        self.start_button.clicked.connect(self._start_recording)  # 開始イベント接続
        self.stop_button.clicked.connect(self._stop_recording)  # 停止イベント接続
        button_row.addWidget(self.start_button)  # 開始ボタン追加
        button_row.addWidget(self.stop_button)  # 停止ボタン追加
        layout.addLayout(button_row)  # ボタン行追加
# 区切り
        self.log_output = QtWidgets.QTextEdit()  # ログ表示欄
        self.log_output.setReadOnly(True)  # 読み取り専用
        self.log_output.setFont(QtGui.QFont("Consolas", 10))  # 等幅フォント指定
        layout.addWidget(self.log_output)  # ログ欄追加
# 区切り
    def _browse_output_dir(self) -> None:  # 出力ディレクトリ参照
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "出力フォルダを選択")  # ダイアログ表示
        if directory:  # 選択があった場合
            self.output_dir_input.setText(directory)  # 入力欄に反映
# 区切り
    def _append_log(self, message: str) -> None:  # ログ追加処理
        timestamp = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")  # タイムスタンプ生成
        self.log_output.append(f"[{timestamp}] {message}")  # ログを追記
# 区切り
    def _start_recording(self) -> None:  # 録画開始処理
        url = self.url_input.text().strip()  # URL取得
        if not url:  # URLが空の場合
            QtWidgets.QMessageBox.warning(self, "入力エラー", "配信URLを入力してください。")  # 警告表示
            return  # 処理中断
        output_dir = Path(self.output_dir_input.text().strip())  # 出力ディレクトリ取得
        filename = self.filename_input.text().strip() or None  # ファイル名取得
        output_path = resolve_output_path(output_dir, filename)  # 出力パス生成
        self._append_log(f"出力パス: {output_path}")  # ログ出力
# 区切り
        self.stop_event = threading.Event()  # 停止フラグ生成
        self.worker_thread = QtCore.QThread()  # ワーカースレッド生成
        self.worker = RecorderWorker(  # ワーカー生成
            url=url,  # URL指定
            quality=self.quality_input.text().strip() or DEFAULT_QUALITY,  # 画質指定
            output_path=output_path,  # 出力パス指定
            retry_count=int(self.retry_count_input.value()),  # リトライ回数指定
            retry_wait=int(self.retry_wait_input.value()),  # リトライ待機指定
            http_timeout=int(self.http_timeout_input.value()),  # HTTPタイムアウト指定
            stream_timeout=int(self.stream_timeout_input.value()),  # ストリームタイムアウト指定
            stop_event=self.stop_event,  # 停止フラグ指定
        )  # ワーカー生成終了
        self.worker.moveToThread(self.worker_thread)  # スレッドへ移動
        self.worker_thread.started.connect(self.worker.run)  # 開始イベント接続
        self.worker.log_signal.connect(self._append_log)  # ログ接続
        self.worker.finished_signal.connect(self._on_recording_finished)  # 終了イベント接続
        self.worker_thread.start()  # スレッド開始
        self.start_button.setEnabled(False)  # 開始ボタン無効化
        self.stop_button.setEnabled(True)  # 停止ボタン有効化
# 区切り
    def _stop_recording(self) -> None:  # 録画停止処理
        if self.stop_event is not None:  # 停止フラグが存在する場合
            self.stop_event.set()  # 停止フラグを設定
            self._append_log("停止要求を送信しました。")  # ログ出力
        self.stop_button.setEnabled(False)  # 停止ボタン無効化
# 区切り
    def _on_recording_finished(self, exit_code: int) -> None:  # 録画終了処理
        self._append_log(f"録画終了（終了コード: {exit_code}）")  # ログ出力
        if self.worker_thread is not None:  # スレッドが存在する場合
            self.worker_thread.quit()  # スレッド終了要求
            self.worker_thread.wait(3000)  # スレッド終了待機
        self.worker = None  # ワーカー参照を破棄
        self.worker_thread = None  # スレッド参照を破棄
        self.stop_event = None  # 停止フラグ参照を破棄
        self.start_button.setEnabled(True)  # 開始ボタン有効化
        self.stop_button.setEnabled(False)  # 停止ボタン無効化
# 区切り
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # 終了時処理
        if self.stop_event is not None:  # 録画中の場合
            self.stop_event.set()  # 停止フラグを設定
        if self.worker_thread is not None:  # スレッドが存在する場合
            self.worker_thread.quit()  # スレッド終了要求
            self.worker_thread.wait(3000)  # スレッド終了待機
        event.accept()  # 終了を許可
# 区切り
# 区切り
def main() -> int:  # エントリポイント
    app = QtWidgets.QApplication(sys.argv)  # アプリケーション生成
    app.setApplicationName("配信録画くん")  # アプリ名設定
    window = MainWindow()  # メインウィンドウ生成
    window.show()  # ウィンドウ表示
    return app.exec()  # イベントループ開始
# 区切り
# 区切り
if __name__ == "__main__":  # 直接実行時の分岐
    sys.exit(main())  # メイン処理実行
