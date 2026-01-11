# Windows向けにPyInstallerでEXEを生成するスクリプト  # 目的を明記
$ErrorActionPreference = "Stop"  # エラー発生時に停止する設定
# 実行パスを整えるための前準備  # 目的の区切りコメント
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path  # スクリプト位置を基準にプロジェクトルートを取得
Set-Location $projectRoot  # 作業ディレクトリをプロジェクトルートに移動
# 余計な通知や警告を抑制  # 目的の区切りコメント
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"  # pipの更新通知を抑制
$env:PYTHONWARNINGS = "ignore"  # Python警告の表示を抑制
$env:PYGAME_HIDE_SUPPORT_PROMPT = "1"  # pygameの起動メッセージを抑制
# 既存の生成物を削除  # 目的の区切りコメント
$distExe = Join-Path $projectRoot "dist\はいろく！.exe"  # 既存EXEのパスを組み立て
if (Test-Path $distExe) {  # 既存EXEがある場合
    try {  # 削除の例外処理開始
        Remove-Item -Force $distExe  # 既存EXEを削除
    } catch {  # 削除失敗時の処理
        Write-Error "dist\はいろく！.exe を削除できませんでした。実行中なら終了してください。"  # エラー通知
        exit 1  # 失敗終了
    }  # 例外処理の終了
}  # 既存EXE削除の終了
# ビルドに必要なツールの更新  # 目的の区切りコメント
python -m pip install --upgrade pyinstaller  # PyInstallerを最新に更新
# PyInstallerの設定値  # 目的の区切りコメント
$appName = "はいろく！"  # 出力EXEのアプリ名
$entryScript = "gui_app.py"  # エントリーポイントのスクリプト
$iconPath = "icon.png"  # EXEとアプリのアイコン
$addData = "icon.png;."  # 実行時に参照するアイコンを同梱
# 競合しやすいQt関連のモジュールを除外  # 目的の区切りコメント
$excludeArgs = @(  # 除外指定を配列で定義
    "--exclude-module", "PyQt5",  # PyQt6のみを同梱するためにPyQt5を除外
    "--exclude-module", "PyQt5.sip",  # PyQt5のSIPバインディングを除外
    "--exclude-module", "PyQt5.QtCore",  # PyQt5のQtCoreを除外
    "--exclude-module", "PyQt5.QtGui",  # PyQt5のQtGuiを除外
    "--exclude-module", "PyQt5.QtWidgets",  # PyQt5のQtWidgetsを除外
    "--exclude-module", "PyQt5.QtMultimedia",  # PyQt5のQtMultimediaを除外
    "--exclude-module", "PyQt5.QtNetwork",  # PyQt5のQtNetworkを除外
    "--exclude-module", "PyQt5.QtMultimediaWidgets",  # PyQt5のQtMultimediaWidgetsを除外
    "--exclude-module", "PySide6",  # PySide6の本体を除外
    "--exclude-module", "PySide6.QtCore",  # PySide6のQtCoreを除外
    "--exclude-module", "PySide6.QtGui",  # PySide6のQtGuiを除外
    "--exclude-module", "PySide6.QtWidgets",  # PySide6のQtWidgetsを除外
    "--exclude-module", "PySide6.QtMultimedia",  # PySide6のQtMultimediaを除外
    "--exclude-module", "PySide6.QtNetwork",  # PySide6のQtNetworkを除外
    "--exclude-module", "PySide6.QtMultimediaWidgets",  # PySide6のQtMultimediaWidgetsを除外
    "--exclude-module", "qt_material"  # 未使用のテーマパッケージを除外
)  # 除外指定の終了
# Streamlinkのプラグイン検出に必要な同梱指定  # 目的の区切りコメント
$streamlinkArgs = @(  # Streamlink関連の追加指定
    "--collect-all", "streamlink",  # Streamlink本体とプラグイン関連データをまとめて同梱
    "--copy-metadata", "streamlink"  # importlib.metadataでのプラグイン検出に必要なメタ情報を同梱
)  # Streamlink指定の終了
# PyInstallerの追加オプション  # 目的の区切りコメント
$extraArgs = @(  # 追加オプションを配列で定義
    "--log-level", "ERROR"  # 警告ログを抑制
)  # 追加オプションの終了
# EXEの生成実行  # 目的の区切りコメント
$pyInstallerArgs = @(  # PyInstallerの引数を組み立て
    "PyInstaller",  # 実行対象のモジュール名
    "--noconfirm",  # 既存ファイルの上書きを許可
    "--clean",  # キャッシュを削除してクリーンビルド
    "--onefile",  # 単一EXEで出力
    "--windowed",  # コンソール非表示でGUI起動
    "--name", $appName,  # 出力ファイル名
    "--icon", $iconPath,  # EXEアイコンの指定
    "--add-data", $addData  # 追加データの同梱
) + $excludeArgs + $streamlinkArgs + $extraArgs + @($entryScript)  # 除外と追加オプションとエントリを結合
# PyQt6を先に読み込んでからPyInstallerを実行  # 目的の区切りコメント
$argLiteral = ($pyInstallerArgs | ForEach-Object { "'" + ($_ -replace "'", "''") + "'" }) -join ", "  # Python側に渡す引数を整形
python -c "import PyQt6, sys, runpy; sys.argv = [$argLiteral]; runpy.run_module('PyInstaller', run_name='__main__')"  # PyInstallerを起動
