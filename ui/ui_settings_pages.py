# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets
from core.config import (
    OUTPUT_FORMAT_FLV,
    OUTPUT_FORMAT_MKV,
    OUTPUT_FORMAT_MOV,
    OUTPUT_FORMAT_MP3,
    OUTPUT_FORMAT_MP4_COPY,
    OUTPUT_FORMAT_TS,
    OUTPUT_FORMAT_WAV,
)
from ui.ui_settings_widgets import ColorPickerWidget, ModernSpinBox, ToggleSwitch


class SettingsPagesMixin:
    def _init_ui(self):
        # メインレイアウト（水平分割）
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. 左サイドバー
        self.sidebar = QtWidgets.QListWidget()
        self.sidebar.setFixedWidth(240)
        self.sidebar.addItems([
            "一般",
            "保存・整理",
            "録画",
            "ネットワーク",
            "自動化・監視",
            "監視リスト",
            "API",
            "ログ・システム",
        ])
        self.sidebar.setCurrentRow(0)
        main_layout.addWidget(self.sidebar)

        # 2. 右コンテンツエリア
        right_container = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # ページ切り替え用スタック
        self.stack = QtWidgets.QStackedWidget()
        right_layout.addWidget(self.stack)

        # フッター
        footer = QtWidgets.QFrame()  # フッター領域を生成
        footer.setObjectName("Footer")  # スタイル適用用のIDを設定
        footer_layout = QtWidgets.QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 16, 24, 16)
        footer_layout.setSpacing(12)
        
        self.btn_cancel = QtWidgets.QPushButton("閉じる")
        self.btn_cancel.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setFixedSize(100, 40)
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QtWidgets.QPushButton("設定を保存")  # 保存ボタンを生成
        self.btn_save.setObjectName("PrimaryButton")  # 保存ボタン用のスタイルIDを設定
        self.btn_save.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)  # カーソルを指アイコンにする
        self.btn_save.setFixedSize(140, 40)  # ボタンサイズを固定する
        self.btn_save.clicked.connect(self._save_settings)  # 保存処理に接続する
        self.btn_save.style().unpolish(self.btn_save)  # オブジェクト名変更後の再スタイル適用
        self.btn_save.style().polish(self.btn_save)  # スタイルを再評価して描画する
        self.btn_save.update()  # 見た目を即時更新する

        footer_layout.addStretch(1)
        footer_layout.addWidget(self.btn_cancel)
        footer_layout.addWidget(self.btn_save)
        
        right_layout.addWidget(footer)
        main_layout.addWidget(right_container)

        self._create_pages()
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)

    def _create_pages(self):
        self.stack.addWidget(self._page_general())
        self.stack.addWidget(self._page_storage())
        self.stack.addWidget(self._page_recording())
        self.stack.addWidget(self._page_network())
        self.stack.addWidget(self._page_automation())
        self.stack.addWidget(self._page_monitoring())
        self.stack.addWidget(self._page_api())
        self.stack.addWidget(self._page_system())

    def _make_scrollable_page(self, title):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        content.setObjectName("PageContent")
        c_layout = QtWidgets.QVBoxLayout(content)
        c_layout.setContentsMargins(32, 32, 32, 32)
        c_layout.setSpacing(24)
        
        lbl_title = QtWidgets.QLabel(title)
        lbl_title.setObjectName("PageTitle")
        lbl_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(lbl_title)
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        return page, c_layout

    def _add_card(self, layout, label_text, widget, description=None):
        container = QtWidgets.QFrame()
        container.setObjectName("Card")
        row = QtWidgets.QHBoxLayout(container)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)
        
        lbl_layout = QtWidgets.QVBoxLayout()
        lbl_layout.setSpacing(4)
        lbl = QtWidgets.QLabel(label_text)
        lbl.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {self._label_color};")
        lbl_layout.addWidget(lbl)
        
        if description:
            desc = QtWidgets.QLabel(description)
            desc.setObjectName("Description")
            desc.setWordWrap(True)
            lbl_layout.addWidget(desc)
        
        row.addLayout(lbl_layout, 1)
        row.addWidget(widget, 0)
        layout.addWidget(container)

    def _add_input_card(self, layout, label_text, widget, description=None):
        container = QtWidgets.QFrame()
        container.setObjectName("Card")
        vbox = QtWidgets.QVBoxLayout(container)
        vbox.setContentsMargins(20, 16, 20, 16)
        vbox.setSpacing(10)
        
        lbl = QtWidgets.QLabel(label_text)
        lbl.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {self._label_color};")
        vbox.addWidget(lbl)
        
        if description:
            desc = QtWidgets.QLabel(description)
            desc.setObjectName("Description")
            vbox.addWidget(desc)
            
        vbox.addWidget(widget)
        layout.addWidget(container)

    def _add_section_label(self, layout, text: str, with_separator: bool = True) -> None:
        if with_separator:
            divider = QtWidgets.QFrame()
            divider.setObjectName("SectionDivider")
            divider.setFixedHeight(1)
            layout.addWidget(divider)
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(
            f"font-weight: bold; margin-top: 18px; font-size: 18px; color: {self._section_label_color};"
        )
        layout.addWidget(lbl)

    def _build_ui_color_tab(self, mode: str) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)

        entries = [
            ("アクセント", "primary"),
            ("メイン背景", "main_bg"),
            ("サイドバー背景", "side_bg"),
            ("テキスト", "text"),
            ("境界線", "border"),
        ]
        for label, key in entries:
            picker = ColorPickerWidget()
            picker.colorChanged.connect(self._apply_live_ui_colors)
            self._ui_color_inputs[mode][key] = picker
            form.addRow(label, picker)
        return widget

    # --- Pages Implementation ---

    def _page_general(self):
        page, layout = self._make_scrollable_page("一般設定")
        # プレビュー音量
        self._add_section_label(layout, "再生設定", with_separator=False)
        self.preview_volume_input = ModernSpinBox('float')
        self.preview_volume_input.setRange(0.0, 1.0)
        self.preview_volume_input.setSingleStep(0.1)
        self._add_card(layout, "プレビュー音量", self.preview_volume_input, "プレビュー再生時の初期音量 (0.0 ~ 1.0)")

        self._add_section_label(layout, "クリップ分割設定")
        self.timeshift_segment_hours_input = ModernSpinBox('int')
        self.timeshift_segment_hours_input.setRange(0, 99)
        self.timeshift_segment_minutes_input = ModernSpinBox('int')
        self.timeshift_segment_minutes_input.setRange(0, 59)
        self.timeshift_segment_seconds_input = ModernSpinBox('int')
        self.timeshift_segment_seconds_input.setRange(0, 59)
        segment_row = QtWidgets.QHBoxLayout()
        segment_row.setSpacing(12)
        segment_row.addWidget(self.timeshift_segment_hours_input)
        segment_row.addWidget(QtWidgets.QLabel("時間"))
        segment_row.addWidget(self.timeshift_segment_minutes_input)
        segment_row.addWidget(QtWidgets.QLabel("分"))
        segment_row.addWidget(self.timeshift_segment_seconds_input)
        segment_row.addWidget(QtWidgets.QLabel("秒"))
        segment_row.addStretch(1)
        segment_widget = QtWidgets.QWidget()
        segment_widget.setLayout(segment_row)
        self._add_input_card(
            layout,
            "分割間隔",
            segment_widget,
            "長くしすぎると再生が重くなるため、用途に合わせて適切な値に設定してください。",
        )

        self._add_section_label(layout, "UIカラー")

        self.ui_custom_colors_input = ToggleSwitch()
        self.ui_custom_colors_input.toggled.connect(self._update_ui_color_option_state)
        self._add_card(layout, "カスタムカラーを使う", self.ui_custom_colors_input, "ONにすると下の配色をUIに反映します。")

        self.ui_color_tabs = QtWidgets.QTabWidget()
        self.ui_color_tabs.setObjectName("UiColorTabs")
        self.ui_color_tabs.currentChanged.connect(self._refresh_ui_preset_list)
        self.ui_color_tabs.addTab(self._build_ui_color_tab("light"), "ライト")
        self.ui_color_tabs.addTab(self._build_ui_color_tab("dark"), "ダーク")

        color_panel = QtWidgets.QWidget()
        color_panel_layout = QtWidgets.QVBoxLayout(color_panel)
        color_panel_layout.setContentsMargins(0, 0, 0, 0)
        color_panel_layout.setSpacing(12)
        color_panel_layout.addWidget(self.ui_color_tabs)

        reset_row = QtWidgets.QHBoxLayout()
        reset_row.addStretch(1)
        self.ui_preset_reset_btn = QtWidgets.QPushButton("リセット")
        self.ui_preset_reset_btn.setObjectName("UiColorResetButton")
        self.ui_preset_reset_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.ui_preset_reset_btn.clicked.connect(self._reset_ui_colors_current_tab)
        reset_row.addWidget(self.ui_preset_reset_btn)
        reset_widget = QtWidgets.QWidget()
        reset_widget.setLayout(reset_row)
        color_panel_layout.addWidget(reset_widget)

        self._add_input_card(layout, "配色設定", color_panel, "各色は #RRGGBB で指定します。")

        preset_controls = QtWidgets.QWidget()
        preset_layout = QtWidgets.QHBoxLayout(preset_controls)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(8)
        self.ui_preset_combo = QtWidgets.QComboBox()
        self.ui_preset_combo.setMinimumWidth(180)
        self.ui_preset_name_input = QtWidgets.QLineEdit()
        self.ui_preset_name_input.setPlaceholderText("プリセット名")
        self.ui_preset_save_btn = QtWidgets.QPushButton("保存")
        self.ui_preset_apply_btn = QtWidgets.QPushButton("適用")
        self.ui_preset_delete_btn = QtWidgets.QPushButton("削除")
        for btn in (
            self.ui_preset_save_btn,
            self.ui_preset_apply_btn,
            self.ui_preset_delete_btn,
        ):
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.ui_preset_save_btn.clicked.connect(self._save_ui_preset)
        self.ui_preset_apply_btn.clicked.connect(self._apply_ui_preset)
        self.ui_preset_delete_btn.clicked.connect(self._delete_ui_preset)

        preset_layout.addWidget(self.ui_preset_combo)
        preset_layout.addWidget(self.ui_preset_name_input, 1)
        preset_layout.addWidget(self.ui_preset_save_btn)
        preset_layout.addWidget(self.ui_preset_apply_btn)
        preset_layout.addWidget(self.ui_preset_delete_btn)
        self._add_input_card(layout, "プリセット", preset_controls, "現在のタブの配色を保存/適用します。")

        self._add_section_label(layout, "フォント")
        self.ui_font_combo = QtWidgets.QComboBox()
        self.ui_font_combo.setMinimumHeight(40)
        self._load_ui_font_options()
        self.ui_font_combo.currentIndexChanged.connect(self._apply_live_ui_font)
        self.ui_font_import_btn = QtWidgets.QPushButton("フォントを追加")
        self.ui_font_import_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.ui_font_import_btn.clicked.connect(self._import_ui_font)
        font_row = QtWidgets.QHBoxLayout()
        font_row.addWidget(self.ui_font_combo, 1)
        font_row.addWidget(self.ui_font_import_btn, 0)
        font_wrapper = QtWidgets.QWidget()
        font_wrapper.setLayout(font_row)
        font_row.setContentsMargins(0, 0, 0, 0)
        self._add_input_card(layout, "表示フォント", font_wrapper, "インストール済みフォントまたはインポートしたフォントを選択します。")

        layout.addStretch(1)
        return page

    def _page_storage(self):
        page, layout = self._make_scrollable_page("保存・整理")

        # 保存先
        self._add_section_label(layout, "保存先", with_separator=False)
        self.output_dir_input = QtWidgets.QLineEdit()
        self.output_browse = QtWidgets.QPushButton("参照")
        self.output_browse.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.output_browse.clicked.connect(self._browse_output_dir)

        h_box = QtWidgets.QHBoxLayout()
        h_box.addWidget(self.output_dir_input)
        h_box.addWidget(self.output_browse)
        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(h_box)
        h_box.setContentsMargins(0, 0, 0, 0)

        self._add_input_card(layout, "保存先フォルダ", wrapper, "録画ファイルの保存先を指定します。")

        # フォーマット
        self._add_section_label(layout, "保存形式")
        self.output_format_input = QtWidgets.QComboBox()
        self.output_format_input.addItems([
            "TS",
            "MP4",
            "MOV",
            "FLV",
            "MKV",
            "MP3",
            "WAV",
        ])
        self.output_format_input.setItemData(0, OUTPUT_FORMAT_TS)
        self.output_format_input.setItemData(1, OUTPUT_FORMAT_MP4_COPY)
        self.output_format_input.setItemData(2, OUTPUT_FORMAT_MOV)
        self.output_format_input.setItemData(3, OUTPUT_FORMAT_FLV)
        self.output_format_input.setItemData(4, OUTPUT_FORMAT_MKV)
        self.output_format_input.setItemData(5, OUTPUT_FORMAT_MP3)
        self.output_format_input.setItemData(6, OUTPUT_FORMAT_WAV)
        self.output_format_input.setMinimumHeight(40)
        self._add_input_card(layout, "保存フォーマット", self.output_format_input, "用途に合わせてファイル形式を選択してください。")

        self._add_section_label(layout, "保存ルール")
        self.output_date_folder_input = ToggleSwitch()
        self._add_card(layout, "日付フォルダで整理", self.output_date_folder_input, "録画日ごとにフォルダ分けします。")

        self.output_filename_with_channel_input = ToggleSwitch()
        self._add_card(layout, "ファイル名に配信者名を付ける", self.output_filename_with_channel_input, "録画ファイル名に配信者名を付加します。")

        self.keep_ts_input = ToggleSwitch()
        self._add_card(layout, "TSファイルを残す", self.keep_ts_input, "MP4保存時でも元のTSファイルを残します。")

        layout.addStretch(1)
        return page

    def _page_recording(self):
        page, layout = self._make_scrollable_page("録画設定")

        self._add_section_label(layout, "画質", with_separator=False)
        self.recording_quality_input = QtWidgets.QComboBox()
        self.recording_quality_input.addItems([
            "最高 (best)",
            "1080p",
            "720p",
            "480p",
            "360p",
            "最低 (worst)",
            "音声のみ (audio_only)",
        ])
        self.recording_quality_input.setItemData(0, "best")
        self.recording_quality_input.setItemData(1, "1080p")
        self.recording_quality_input.setItemData(2, "720p")
        self.recording_quality_input.setItemData(3, "480p")
        self.recording_quality_input.setItemData(4, "360p")
        self.recording_quality_input.setItemData(5, "worst")
        self.recording_quality_input.setItemData(6, "audio_only")
        self._add_input_card(layout, "録画画質", self.recording_quality_input, "Streamlinkで取得する画質を選択します。")

        self.youtube_backend_input = QtWidgets.QComboBox()
        self.youtube_backend_input.addItems([
            "Streamlink",
            "yt-dlp",
        ])
        self.youtube_backend_input.setItemData(0, "streamlink")
        self.youtube_backend_input.setItemData(1, "ytdlp")
        self._add_input_card(layout, "YouTube録画方式", self.youtube_backend_input, "YouTubeの録画方法を選択します。※画質に差はありません※")

        self._add_section_label(layout, "サイズ設定")
        self.recording_max_size_input = ModernSpinBox('int')
        self.recording_max_size_input.setRange(0, 1024 * 1024)
        self._add_card(layout, "録画ファイルの最大サイズ (MB)", self.recording_max_size_input, "0にすると無制限になります。")

        self.recording_size_margin_input = ModernSpinBox('int')
        self.recording_size_margin_input.setRange(0, 1024 * 1024)
        self._add_card(layout, "録画サイズ切替の余裕 (MB)", self.recording_size_margin_input, "上限に達する前に切り替える余裕幅です。")

        self._add_section_label(layout, "自動圧縮")
        self.auto_compress_enabled_input = ToggleSwitch()
        self.auto_compress_enabled_input.toggled.connect(self._update_auto_compress_option_state)
        self._add_card(layout, "録画後に自動圧縮", self.auto_compress_enabled_input, "録画後に再エンコードして容量を削減します。")

        self.auto_compress_profile_input = QtWidgets.QComboBox()
        self.auto_compress_profile_input.addItems([
            "長時間用",
            "中時間用",
            "短時間用",
            "カスタム",
        ])
        self.auto_compress_profile_input.setItemData(0, "long")
        self.auto_compress_profile_input.setItemData(1, "medium")
        self.auto_compress_profile_input.setItemData(2, "short")
        self.auto_compress_profile_input.setItemData(3, "custom")
        self.auto_compress_profile_input.currentIndexChanged.connect(
            self._on_auto_compress_profile_changed
        )
        self._add_input_card(layout, "圧縮プロファイル", self.auto_compress_profile_input, "時間に合わせた目安設定を一括で反映します。")

        self.auto_compress_codec_input = QtWidgets.QComboBox()
        self.auto_compress_codec_input.addItems([
            "H.264 (libx264)",
            "H.265 (libx265)",
        ])
        self.auto_compress_codec_input.setItemData(0, "libx264")
        self.auto_compress_codec_input.setItemData(1, "libx265")
        self._add_input_card(layout, "圧縮コーデック", self.auto_compress_codec_input, "容量を抑えたい場合はH.265を選択してください。\n再生互換性を重視する場合はH.264をおすすめします。")

        self.auto_compress_preset_input = QtWidgets.QComboBox()
        self.auto_compress_preset_input.addItems([
            "速い (fast)",
            "標準 (medium)",
            "高圧縮 (slow)",
        ])
        self.auto_compress_preset_input.setItemData(0, "fast")
        self.auto_compress_preset_input.setItemData(1, "medium")
        self.auto_compress_preset_input.setItemData(2, "slow")
        self._add_input_card(layout, "圧縮プリセット", self.auto_compress_preset_input, "速いほど処理が軽くなります。")

        self.auto_compress_resolution_input = QtWidgets.QComboBox()
        self.auto_compress_resolution_input.addItems([
            "元の解像度を維持",
            "144p",
            "240p",
            "360p",
            "480p",
            "720p",
            "1080p",
        ])
        self.auto_compress_resolution_input.setItemData(0, 0)
        self.auto_compress_resolution_input.setItemData(1, 144)
        self.auto_compress_resolution_input.setItemData(2, 240)
        self.auto_compress_resolution_input.setItemData(3, 360)
        self.auto_compress_resolution_input.setItemData(4, 480)
        self.auto_compress_resolution_input.setItemData(5, 720)
        self.auto_compress_resolution_input.setItemData(6, 1080)
        self._add_input_card(layout, "圧縮の最大解像度", self.auto_compress_resolution_input, "元の解像度より高い値は適用されません。")

        self.auto_compress_fps_input = ModernSpinBox('int')
        self.auto_compress_fps_input.setRange(0, 240)
        self._add_card(layout, "圧縮のFPS (0は元のまま)", self.auto_compress_fps_input, "フレームレートを固定して容量を抑えます。")

        self.auto_compress_video_bitrate_input = ModernSpinBox('int')
        self.auto_compress_video_bitrate_input.setRange(100, 50000)
        self._add_card(layout, "圧縮の映像ビットレート (kbps)", self.auto_compress_video_bitrate_input, "数値が小さいほど容量が減ります。")

        self.auto_compress_audio_bitrate_input = ModernSpinBox('int')
        self.auto_compress_audio_bitrate_input.setRange(32, 320)
        self._add_card(layout, "圧縮の音声ビットレート (kbps)", self.auto_compress_audio_bitrate_input, "音声の圧縮率を指定します。")

        self.auto_compress_keep_original_input = ToggleSwitch()
        self._add_card(layout, "圧縮前のファイルを残す", self.auto_compress_keep_original_input, "ONにすると元の録画ファイルを保持します。")

        self._add_section_label(layout, "透かし")
        self.watermark_enabled_input = ToggleSwitch()
        self._add_card(layout, "透かしを付ける", self.watermark_enabled_input, "録画ファイルに透かしを右下へ合成します。")

        self.watermark_open_dialog_button = QtWidgets.QPushButton("透かし設定を開く")
        self.watermark_open_dialog_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.watermark_open_dialog_button.clicked.connect(self._open_watermark_dialog)
        self._add_input_card(layout, "透かし詳細", self.watermark_open_dialog_button, "プレビュー付きの専用ウィンドウを開きます。")

        layout.addStretch(1)
        return page

    def _page_network(self):
        page, layout = self._make_scrollable_page("ネットワーク設定")
        
        self._add_section_label(layout, "再接続設定", with_separator=False)
        self.retry_count_input = ModernSpinBox('int')
        self.retry_count_input.setRange(0, 99)
        self._add_card(layout, "再接続リトライ回数", self.retry_count_input, "切断時に再接続を試みる最大回数")

        self.retry_wait_input = ModernSpinBox('int')
        self.retry_wait_input.setRange(1, 3600)
        self._add_card(layout, "リトライ待機時間 (秒)", self.retry_wait_input, "再接続までの待機時間")

        self._add_section_label(layout, "タイムアウト")
        self.http_timeout_input = ModernSpinBox('int')
        self.http_timeout_input.setRange(1, 300)
        self._add_card(layout, "HTTPタイムアウト (秒)", self.http_timeout_input, "通信応答がない場合のタイムアウト時間")

        self.stream_timeout_input = ModernSpinBox('int')
        self.stream_timeout_input.setRange(1, 600)
        self._add_card(layout, "ストリーム待機 (秒)", self.stream_timeout_input, "映像データが途切れた際の待機時間")

        layout.addStretch(1)
        return page

    def _page_automation(self):
        page, layout = self._make_scrollable_page("自動化・監視設定")
        
        self._add_section_label(layout, "自動録画", with_separator=False)
        self.auto_enabled_input = ToggleSwitch()
        self.auto_enabled_input.toggled.connect(self._update_auto_record_option_state)
        self._add_card(layout, "自動録画機能", self.auto_enabled_input, "監視リストの配信が開始されたら自動で録画します。")

        self.auto_startup_input = ToggleSwitch()
        self._add_card(layout, "アプリ起動時に監視開始", self.auto_startup_input, "アプリを起動した直後から監視をスタートします。")

        self.auto_notify_only_input = ToggleSwitch()
        self._add_card(layout, "通知のみで監視", self.auto_notify_only_input, "配信を検知しても録画せず、通知だけを行います。")

        self._add_section_label(layout, "監視サイクル")
        self.auto_check_interval_input = ModernSpinBox('int')
        self.auto_check_interval_input.setRange(20, 3600)
        self._add_card(layout, "監視サイクル (秒)", self.auto_check_interval_input, "配信状態をチェックする間隔")

        layout.addStretch(1)
        return page

    def _page_monitoring(self):
        page, layout = self._make_scrollable_page("監視対象リスト")
        
        self._add_section_label(layout, "監視対象", with_separator=False)
        desc = QtWidgets.QLabel("各サービスのURLまたはIDを1行に1つ入力してください。")
        desc.setObjectName("Description")
        layout.addWidget(desc)

        def add_collapsible_text_area(title, ph=""):
            container = QtWidgets.QWidget()
            container_layout = QtWidgets.QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(6)

            header = QtWidgets.QToolButton()
            header.setObjectName("CollapsibleHeader")
            header.setAutoRaise(True)
            header.setCheckable(True)
            header.setChecked(False)
            header.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            header.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
            header.setStyleSheet(f"font-weight: bold; color: {self._muted_label_color}; margin-top: 12px;")

            text_area = QtWidgets.QPlainTextEdit()
            text_area.setPlaceholderText(ph)
            text_area.setMinimumHeight(100)

            def _toggle(checked: bool) -> None:
                prefix = "▼ " if checked else "▶ "
                header.setText(prefix + title)
                text_area.setVisible(checked)

            header.toggled.connect(_toggle)
            _toggle(False)

            container_layout.addWidget(header)
            container_layout.addWidget(text_area)
            layout.addWidget(container)
            return text_area

        self.auto_notify_only_entries_input = add_collapsible_text_area(
            "通知のみで監視する配信",
            "URL/ID/チャンネルを1行ずつ（監視リストに含めたもののみ有効）",
        )
        self.youtube_channels_input = add_collapsible_text_area("YouTube")
        self.twitch_channels_input = add_collapsible_text_area("Twitch")
        self.twitcasting_input = add_collapsible_text_area("ツイキャス")
        self.niconico_input = add_collapsible_text_area("ニコニコ生放送")
        self.tiktok_input = add_collapsible_text_area("TikTok")
        self.fuwatch_input = add_collapsible_text_area("ふわっち")
        self.kick_input = add_collapsible_text_area("Kick")
        self.live17_input = add_collapsible_text_area("17LIVE")
        self.bigo_input = add_collapsible_text_area("BIGO LIVE")
        self.radiko_input = add_collapsible_text_area("radiko")
        self.openrectv_input = add_collapsible_text_area("OPENREC.tv")
        self.bilibili_input = add_collapsible_text_area("bilibili")
        self.abema_input = add_collapsible_text_area("AbemaTV")

        layout.addStretch(1)
        return page

    def _page_system(self):
        page, layout = self._make_scrollable_page("ログ・システム")
        
        self._add_section_label(layout, "システム", with_separator=False)
        self.tray_enabled_input = ToggleSwitch()
        self._add_card(layout, "タスクトレイ常駐", self.tray_enabled_input, "ウィンドウを閉じてもバックグラウンドで動作します。")

        self.auto_start_input = ToggleSwitch()
        self._add_card(layout, "PC起動時に自動実行", self.auto_start_input, "PC起動時にソフトを自動で立ち上げます。")

        self._add_section_label(layout, "ログ表示設定")

        self.log_panel_visible_input = ToggleSwitch()
        self._add_card(layout, "ログパネル表示", self.log_panel_visible_input, "右側のログパネルを表示します。")

        layout.addStretch(1)
        return page

    def _page_api(self):
        page, layout = self._make_scrollable_page("APIキー設定")
        
        self._add_section_label(layout, "YouTube", with_separator=False)
        self.youtube_api_key_input = QtWidgets.QLineEdit()
        self.youtube_api_key_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.youtube_api_key_input.setPlaceholderText("API Key")
        self._add_input_card(layout, "YouTube Data API v3", self.youtube_api_key_input, "YouTubeの監視精度を向上させるために使用します。")
        
        self._add_section_label(layout, "Twitch")
        self.twitch_client_id_input = QtWidgets.QLineEdit()
        self.twitch_client_id_input.setPlaceholderText("Client ID")
        self._add_input_card(layout, "Twitch Client ID", self.twitch_client_id_input)
        
        self.twitch_client_secret_input = QtWidgets.QLineEdit()
        self.twitch_client_secret_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.twitch_client_secret_input.setPlaceholderText("Client Secret")
        self._add_input_card(layout, "Twitch Client Secret", self.twitch_client_secret_input)
        layout.addStretch(1)
        return page
