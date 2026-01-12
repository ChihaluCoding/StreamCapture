# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6 import QtCore, QtGui, QtWidgets
from utils.theme_utils import (
    adjust_color,
    blend_colors,
    get_ui_color_overrides,
    get_ui_font_css_family,
    is_custom_ui_colors_enabled,
)

class MainWindowLayoutMixin:
    def _build_ui(self) -> None:
        """
        メインウィンドウのUI構築 (コマンドセンター・スタイル)
        左側に操作パネル、右側にモニター＆ログを配置する「左右分割レイアウト」に刷新
        """
        central = QtWidgets.QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        # メインレイアウト（左右分割）
        main_layout = QtWidgets.QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # =====================================================================
        # 1. 左サイドバー (操作パネル) - 幅固定で常時表示
        # =====================================================================
        sidebar_frame = QtWidgets.QFrame()
        sidebar_frame.setObjectName("SidebarFrame")
        sidebar_frame.setFixedWidth(320) # 幅を固定して「操作盤」らしさを出す
        
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(24, 32, 24, 32)
        sidebar_layout.setSpacing(24)

        # --- タイトル（非表示） ---

        # --- URL入力エリア ---
        url_group = QtWidgets.QWidget()
        url_layout = QtWidgets.QVBoxLayout(url_group)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(8)
        
        url_label = QtWidgets.QLabel("配信URL")  # ラベルを日本語化
        url_label.setObjectName("FieldLabel")
        url_layout.addWidget(url_label)

        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("URLを入力...")
        self.url_input.setObjectName("UrlInput")
        self.url_input.setMinimumHeight(44)
        self.url_input.setMinimumHeight(44)
        url_layout.addWidget(self.url_input)

        sidebar_layout.addWidget(url_group)

        # --- アクションボタン群 ---
        btns_layout = QtWidgets.QVBoxLayout()
        btns_layout.setSpacing(12)

        # プレビューボタンは不要になったため生成しない

        # 録画開始ボタン (巨大化して強調)
        self.start_button = QtWidgets.QPushButton("● 録画開始")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.start_button.setFixedHeight(52) # 少し縦幅を抑える
        self.start_button.clicked.connect(self._start_recording)
        btns_layout.addWidget(self.start_button)

        # 停止ボタン
        self.stop_button = QtWidgets.QPushButton("■ 停止")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.stop_button.setFixedHeight(52)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_recording)
        btns_layout.addWidget(self.stop_button)

        self.recording_duration_label = QtWidgets.QLabel("録画時間: 00:00:00")
        self.recording_duration_label.setObjectName("RecordingDurationLabel")
        self.recording_duration_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.recording_duration_label.setWordWrap(True)
        btns_layout.addWidget(self.recording_duration_label)

        sidebar_layout.addLayout(btns_layout)

        # スペーサー (下詰めにするため)
        sidebar_layout.addStretch(1)

        # --- サブ機能 (下部に配置) ---
        sub_layout = QtWidgets.QVBoxLayout()
        sub_layout.setSpacing(12)

        self.auto_resume_button = QtWidgets.QPushButton("自動録画: 待機中")
        self.auto_resume_button.setObjectName("StatusButton")
        self.auto_resume_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.auto_resume_button.setEnabled(False)
        self.auto_resume_button.clicked.connect(self._resume_auto_recording)
        sub_layout.addWidget(self.auto_resume_button)

        self.timeshift_button = QtWidgets.QPushButton("クリップ作成")
        self.timeshift_button.setObjectName("StatusButton")
        self.timeshift_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.timeshift_button.setEnabled(False)
        self.timeshift_button.clicked.connect(self._open_timeshift_window)
        sub_layout.addWidget(self.timeshift_button)

        version_label = QtWidgets.QLabel("v1.0.0 beta")
        version_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        version_label.setStyleSheet("font-weight: normal; color: #94a3b8;")
        sub_layout.addWidget(version_label)

        sidebar_layout.addLayout(sub_layout)

        # サイドバーをメインに追加
        main_layout.addWidget(sidebar_frame)

        # =====================================================================
        # 2. 右側メインエリア (モニター & ログ) - 上下分割
        # =====================================================================
        right_area = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_area)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # --- 上部: ライブモニターエリア ---
        monitor_frame = QtWidgets.QFrame()
        monitor_frame.setObjectName("MonitorFrame")
        monitor_layout = QtWidgets.QVBoxLayout(monitor_frame)
        monitor_layout.setContentsMargins(0, 0, 0, 0)
        monitor_layout.setSpacing(0)

        # モニターヘッダー
        mon_header_lbl = QtWidgets.QLabel("ライブプレビュー")  # セクション名を日本語化
        mon_header_lbl.setObjectName("SectionHeader")
        monitor_layout.addWidget(mon_header_lbl)

        # プレビュータブ (映像エリア)
        self.preview_tabs.setObjectName("PreviewTabs")
        self.preview_tabs.setDocumentMode(True)
        monitor_layout.addWidget(self.preview_tabs)

        # --- 下部: ログエリア (ターミナル風) ---
        log_frame = QtWidgets.QFrame()
        self.log_frame = log_frame
        log_frame.setObjectName("LogFrame")
        log_layout = QtWidgets.QVBoxLayout(log_frame)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)

        # ログヘッダー
        log_header_lbl = QtWidgets.QLabel("ログ")  # セクション名を日本語化
        log_header_lbl.setObjectName("SectionHeader")
        log_layout.addWidget(log_header_lbl)

        # ログ出力
        self.log_output = QtWidgets.QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("LogOutput")
        log_layout.addWidget(self.log_output)

        # スプリッターで上下分割 (モニター優先)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.main_splitter = splitter
        splitter.setObjectName("RightSplitter")
        splitter.setHandleWidth(1)
        splitter.addWidget(monitor_frame)
        splitter.addWidget(log_frame)
        splitter.setStretchFactor(0, 3)  # モニター側の比率を増やす
        splitter.setStretchFactor(1, 1)  # ログ側は控えめにする
        splitter.setSizes([650, 350])  # 初期サイズを強制して比率を目立たせる

        right_layout.addWidget(splitter)
        main_layout.addWidget(right_area)

    def _apply_ui_theme(self) -> None:
        """
        別物レベルのモダンUIテーマ (Left-Sidebar Pro Style)
        OS標準の見た目をCSSで完全に上書きし、フラットでシャープな印象にします。
        """
        
        palette = QtGui.QGuiApplication.palette()
        is_dark = palette.color(QtGui.QPalette.ColorRole.Window).lightness() < 128

        if is_dark:
            c_side_bg = "#0b1220"
            c_main_bg = "#0f172a"
            c_text = "#e2e8f0"
            c_text_muted = "#94a3b8"
            c_border = "#1f2a44"
            c_primary = "#38bdf8"
            c_primary_hover = "#0ea5e9"
            c_primary_pressed = "#0284c7"
            c_danger = "#f87171"
            c_danger_hover = "#ef4444"
            c_danger_bg = "#3b0a0a"
            c_danger_disabled_bg = "#111827"
            c_danger_disabled_text = "#475569"
            c_danger_disabled_border = "#1f2a44"
            c_secondary_bg = "#0f172a"
            c_secondary_hover_bg = "#0b2a3a"
            c_status_hover_bg = "#111827"
            c_monitor_bg = "#0b1220"
            c_section_bg = "#0f172a"
            c_tab_bg = "#0f172a"
            c_tab_selected_bg = "#111827"
            c_tab_hover_bg = "#1f2937"
            c_input_bg = "#0f172a"
            c_input_focus_bg = "#111827"
            c_log_bg = "#0b1220"
            c_log_text = "#e2e8f0"
        else:
            c_side_bg = "#ffffff"
            c_main_bg = "#f3f4f6"
            c_text = "#1e293b"
            c_text_muted = "#64748b"
            c_border = "#e2e8f0"
            c_primary = "#0ea5e9"
            c_primary_hover = "#0284c7"
            c_primary_pressed = "#0369a1"
            c_danger = "#ef4444"
            c_danger_hover = "#dc2626"
            c_danger_bg = "#fff1f2"
            c_danger_disabled_bg = "#f1f5f9"
            c_danger_disabled_text = "#cbd5e1"
            c_danger_disabled_border = "#e2e8f0"
            c_secondary_bg = "#ffffff"
            c_secondary_hover_bg = "#f0f9ff"
            c_status_hover_bg = "#f8fafc"
            c_monitor_bg = "#ffffff"
            c_section_bg = "#f8fafc"
            c_tab_bg = "#f8fafc"
            c_tab_selected_bg = "#ffffff"
            c_tab_hover_bg = "#e2e8f0"
            c_input_bg = "#f8fafc"
            c_input_focus_bg = "#ffffff"
            c_log_bg = "#ffffff"
            c_log_text = "#1e293b"

        def tone(color: str, light_factor: float, dark_factor: float) -> str:
            return adjust_color(color, dark_factor if is_dark else light_factor)

        if is_custom_ui_colors_enabled():
            overrides = get_ui_color_overrides("dark" if is_dark else "light")
            if overrides:
                c_main_bg = overrides.get("main_bg", c_main_bg)
                c_side_bg = overrides.get("side_bg", c_side_bg)
                c_text = overrides.get("text", c_text)
                c_primary = overrides.get("primary", c_primary)
                c_border = overrides.get("border", c_border)

                c_text_muted = blend_colors(c_text, c_main_bg, 0.5)
                c_primary_hover = tone(c_primary, 0.92, 1.08)
                c_primary_pressed = tone(c_primary, 0.84, 1.16)
                c_secondary_bg = tone(c_main_bg, 0.98, 1.06)
                c_secondary_hover_bg = tone(c_secondary_bg, 0.96, 1.1)
                c_status_hover_bg = tone(c_main_bg, 0.96, 1.1)
                c_monitor_bg = tone(c_side_bg, 0.98, 1.06)
                c_section_bg = tone(c_main_bg, 0.99, 1.05)
                c_tab_bg = tone(c_main_bg, 0.99, 1.06)
                c_tab_selected_bg = tone(c_main_bg, 1.0, 1.1)
                c_tab_hover_bg = tone(c_main_bg, 0.96, 1.12)
                c_input_bg = tone(c_main_bg, 0.99, 1.08)
                c_input_focus_bg = tone(c_main_bg, 1.0, 1.12)
                c_log_bg = tone(c_main_bg, 1.0, 1.08)
                c_log_text = c_text

        font_main = get_ui_font_css_family(["Noto Sans JP", "Meiryo UI", "Meiryo", "Segoe UI", "sans-serif"])
        font_mono = '"Consolas", "Monaco", monospace'  # 等幅フォントは既存を維持

        self.setStyleSheet(f"""
            /* 全体のリセット */
            QWidget {{
                font-family: {font_main};
                color: {c_text};
                font-size: 14px;
            }}
            QMainWindow, QWidget#CentralWidget {{
                background-color: {c_main_bg};
            }}
            
            /* サイドバー */
            QFrame#SidebarFrame {{
                background-color: {c_side_bg};
                border-right: 1px solid {c_border};
            }}
            QLabel#SidebarTitle {{
                font-size: 28px;
                font-weight: 700;
                color: {c_primary};
                line-height: 1.2;
                font-family: {font_main};
            }}
            QLabel#FieldLabel {{
                font-size: 12px;
                font-weight: bold;
                color: {c_text_muted};
                letter-spacing: 1px;
            }}
            
            /* 入力欄 */
            QLineEdit#UrlInput {{
                background-color: {c_input_bg};
                border: 2px solid {c_border};
                border-radius: 8px;
                padding: 0 12px;
                font-size: 15px;
                color: {c_text};
            }}
            QLineEdit#UrlInput:focus {{
                border-color: {c_primary};
                background-color: {c_input_focus_bg};
            }}

            /* ボタン類 */
            QPushButton {{
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }}
            
            /* プライマリボタン（録画開始） */
            QPushButton#PrimaryButton {{
                background-color: {c_primary};
                color: white;
                border: none;
                font-size: 16px;
                letter-spacing: 1px;
            }}
            QPushButton#PrimaryButton:hover {{
                background-color: {c_primary_hover};
            }}
            QPushButton#PrimaryButton:pressed {{
                background-color: {c_primary_pressed};
            }}

            /* デンジャーボタン（録画停止） */
            QPushButton#DangerButton {{
                background-color: {c_danger_bg};
                color: {c_danger};
                border: 2px solid {c_danger};
                font-size: 16px;
            }}
            QPushButton#DangerButton:hover {{
                background-color: {c_danger_hover};
                color: white;
            }}
            QPushButton#DangerButton:disabled {{
                background-color: {c_danger_disabled_bg};
                color: {c_danger_disabled_text};
                border-color: {c_danger_disabled_border};
            }}

            /* セカンダリボタン（プレビューなど） */
            QPushButton#SecondaryButton {{
                background-color: {c_secondary_bg};
                border: 2px solid {c_border};
                color: {c_text};
            }}
            QPushButton#SecondaryButton:hover {{
                border-color: {c_primary};
                color: {c_primary};
                background-color: {c_secondary_hover_bg};
            }}

            /* ステータス系（小ボタン） */
            QPushButton#StatusButton {{
                background-color: transparent;
                border: 1px solid {c_border};
                color: {c_text_muted};
                font-size: 12px;
                height: 36px;
            }}
            QPushButton#StatusButton:hover {{
                background-color: {c_status_hover_bg};
                color: {c_text};
            }}
            QPushButton#StatusButton:disabled {{
                color: {c_danger_disabled_text};
                border-color: {c_danger_disabled_bg};
            }}

            QLabel#RecordingDurationLabel {{
                font-size: 12px;
                color: {c_text_muted};
                padding-top: 4px;
            }}

            /* 右側エリア（モニター・ログ） */
            QFrame#MonitorFrame, QFrame#LogFrame {{
                background-color: {c_monitor_bg};
            }}
            
            QLabel#SectionHeader {{
                background-color: {c_section_bg};
                color: {c_text_muted};
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
                padding: 8px 12px;
                border-bottom: 1px solid {c_border};
                border-top: 1px solid {c_border};
            }}

            /* ログ出力 (ターミナルスタイル) */
            QTextEdit#LogOutput {{
                background-color: {c_log_bg};
                color: {c_log_text};
                border: none;
                font-family: {font_mono};
                font-size: 13px;
                line-height: 1.5;
                padding: 12px;
            }}

            /* スプリッター */
            QSplitter::handle {{
                background-color: {c_border};
            }}

            /* タブウィジェット */
            QTabWidget::pane {{
                border: none;
                background-color: #000000; /* 映像エリア背景 */
            }}
            QTabBar::tab {{
                background: {c_tab_bg};
                color: {c_text_muted};
                padding: 8px 24px;
                border-right: 1px solid {c_border};
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                background: {c_tab_selected_bg};
                color: {c_primary};
                border-bottom: 2px solid {c_primary};
            }}
            QTabBar::tab:hover {{
                background: {c_tab_hover_bg};
                color: {c_text};
            }}
        """)
