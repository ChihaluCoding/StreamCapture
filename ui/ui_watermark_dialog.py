# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path
from PyQt6 import QtCore, QtGui, QtWidgets
from utils.settings_store import load_setting_value, save_setting_value
from ui.ui_settings_widgets import ModernSpinBox
from core.recording import find_ffmpeg_path


class WatermarkDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("透かし設定")
        self.resize(1100, 720)
        self._sample_source_pixmap: QtGui.QPixmap | None = None
        self._sample_source_size = QtCore.QSize()
        self._temp_dir = tempfile.TemporaryDirectory()
        self._composite_preview = False
        self._preview_source_path: Path | None = None
        self._exact_preview_timer = QtCore.QTimer(self)
        self._exact_preview_timer.setSingleShot(True)
        self._exact_preview_timer.timeout.connect(self._render_exact_preview)
        self._build_ui()
        self._apply_style()
        self._load_settings()

    def _build_ui(self) -> None:
        def section_label(text: str) -> QtWidgets.QLabel:
            label = QtWidgets.QLabel(text)
            label.setObjectName("SectionLabel")
            return label

        def field_label(text: str) -> QtWidgets.QLabel:
            label = QtWidgets.QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        def add_divider(layout: QtWidgets.QVBoxLayout) -> None:
            line = QtWidgets.QFrame()
            line.setObjectName("SectionDivider")
            line.setFixedHeight(1)
            layout.addWidget(line)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.preview_frame = QtWidgets.QFrame()
        self.preview_frame.setObjectName("WatermarkPreview")
        self.preview_frame.setMinimumSize(740, 520)
        preview_layout = QtWidgets.QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("color: #ffffff; font-size: 24px;")
        preview_layout.addWidget(self.preview_label, 1)
        self.preview_overlay_text = QtWidgets.QLabel(self.preview_frame)
        self.preview_overlay_text.setStyleSheet("color: rgba(255,255,255,0.85); font-size: 20px;")
        self.preview_overlay_text.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.preview_overlay_text.hide()
        self.preview_overlay_image = QtWidgets.QLabel(self.preview_frame)
        self.preview_overlay_image.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.preview_overlay_image.hide()
        self._image_opacity_effect = QtWidgets.QGraphicsOpacityEffect(self.preview_overlay_image)
        self.preview_overlay_image.setGraphicsEffect(self._image_opacity_effect)
        self.preview_frame.installEventFilter(self)
        layout.addWidget(self.preview_frame, 1)

        self.control_frame = QtWidgets.QFrame()
        self.control_frame.setObjectName("WatermarkControls")
        self.control_frame.setFixedWidth(300)
        control_layout = QtWidgets.QVBoxLayout(self.control_frame)
        control_layout.setContentsMargins(16, 16, 16, 16)
        control_layout.setSpacing(12)

        control_layout.addWidget(section_label("プレビュー"))
        self.preview_source_input = QtWidgets.QLineEdit()
        self.preview_source_input.textChanged.connect(self._load_preview_source)
        self.preview_source_browse = QtWidgets.QPushButton("参照")
        self.preview_source_browse.clicked.connect(self._browse_preview_source)
        preview_row = QtWidgets.QHBoxLayout()
        preview_row.addWidget(self.preview_source_input, 1)
        preview_row.addWidget(self.preview_source_browse, 0)
        control_layout.addWidget(field_label("サンプルファイル"))
        control_layout.addLayout(preview_row)
        self.exact_preview_toggle = QtWidgets.QCheckBox("正確プレビューを自動更新")
        self.exact_preview_toggle.toggled.connect(self._on_exact_preview_toggled)
        control_layout.addWidget(self.exact_preview_toggle)

        add_divider(control_layout)
        control_layout.addWidget(section_label("タイプ"))
        self.mode_input = QtWidgets.QComboBox()
        self.mode_input.addItems(["画像", "テキスト"])
        self.mode_input.setItemData(0, "image")
        self.mode_input.setItemData(1, "text")
        self.mode_input.currentIndexChanged.connect(self._update_mode_ui)
        self.mode_input.currentIndexChanged.connect(self._on_setting_changed)
        control_layout.addWidget(field_label("透かし種類"))
        control_layout.addWidget(self.mode_input)

        control_layout.addWidget(field_label("ロゴ画像ファイル"))
        self.image_path_input = QtWidgets.QLineEdit()
        self.image_path_input.textChanged.connect(self._update_preview_overlay)
        self.image_path_input.textChanged.connect(self._on_setting_changed)
        self.image_browse = QtWidgets.QPushButton("参照")
        self.image_browse.clicked.connect(self._browse_image_file)
        image_row = QtWidgets.QHBoxLayout()
        image_row.addWidget(self.image_path_input, 1)
        image_row.addWidget(self.image_browse, 0)
        control_layout.addLayout(image_row)

        control_layout.addWidget(field_label("透かしテキスト"))
        self.text_input = QtWidgets.QLineEdit()
        self.text_input.textChanged.connect(self._update_preview_text)
        self.text_input.textChanged.connect(self._on_setting_changed)
        control_layout.addWidget(self.text_input)

        add_divider(control_layout)
        control_layout.addWidget(section_label("見た目"))
        self.opacity_input = ModernSpinBox('float')
        self.opacity_input.setRange(0.0, 1.0)
        self.opacity_input.setSingleStep(0.05)
        self.opacity_input.valueChanged.connect(self._update_preview_overlay)
        self.opacity_input.valueChanged.connect(self._on_setting_changed)
        control_layout.addWidget(field_label("透明度 (0.0 ~ 1.0)"))
        control_layout.addWidget(self.opacity_input)

        self.logo_width_input = ModernSpinBox('float')
        self.logo_width_input.setRange(1.0, 50.0)
        self.logo_width_input.setSingleStep(0.5)
        self.logo_width_input.valueChanged.connect(self._update_preview_overlay)
        self.logo_width_input.valueChanged.connect(self._on_setting_changed)
        control_layout.addWidget(field_label("ロゴ幅 (% of 画面)"))
        control_layout.addWidget(self.logo_width_input)

        self.text_size_input = ModernSpinBox('float')
        self.text_size_input.setRange(1.0, 50.0)
        self.text_size_input.setSingleStep(0.5)
        self.text_size_input.valueChanged.connect(self._update_preview_overlay)
        self.text_size_input.valueChanged.connect(self._on_setting_changed)
        control_layout.addWidget(field_label("テキストサイズ (% of 画面幅)"))
        control_layout.addWidget(self.text_size_input)

        add_divider(control_layout)
        control_layout.addWidget(section_label("位置"))
        self.position_input = QtWidgets.QComboBox()
        self.position_input.addItems(["右下", "右上", "左下", "左上"])
        self.position_input.setItemData(0, "br")
        self.position_input.setItemData(1, "tr")
        self.position_input.setItemData(2, "bl")
        self.position_input.setItemData(3, "tl")
        self.position_input.currentIndexChanged.connect(self._update_preview_overlay)
        self.position_input.currentIndexChanged.connect(self._on_setting_changed)
        control_layout.addWidget(field_label("固定位置"))
        control_layout.addWidget(self.position_input)
        self.random_move_input = QtWidgets.QCheckBox("ランダム移動（数秒ごと）")
        self.random_move_input.toggled.connect(self._update_preview_overlay)
        self.random_move_input.toggled.connect(self._on_setting_changed)
        control_layout.addWidget(self.random_move_input)
        self.random_interval_input = ModernSpinBox('int')
        self.random_interval_input.setRange(1, 120)
        self.random_interval_input.setSingleStep(1)
        self.random_interval_input.valueChanged.connect(self._update_preview_overlay)
        self.random_interval_input.valueChanged.connect(self._on_setting_changed)
        control_layout.addWidget(field_label("移動間隔 (秒)"))
        control_layout.addWidget(self.random_interval_input)
        self.margin_input = ModernSpinBox('int')
        self.margin_input.setRange(0, 500)
        self.margin_input.setSingleStep(4)
        self.margin_input.valueChanged.connect(self._update_preview_overlay)
        self.margin_input.valueChanged.connect(self._on_setting_changed)
        control_layout.addWidget(field_label("余白 (px)"))
        control_layout.addWidget(self.margin_input)

        control_layout.addStretch(1)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.btn_close = QtWidgets.QPushButton("閉じる")
        self.btn_save = QtWidgets.QPushButton("保存")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.setDefault(True)
        self.btn_close.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._save_settings)
        button_row.addWidget(self.btn_close)
        button_row.addWidget(self.btn_save)
        control_layout.addLayout(button_row)

        layout.addWidget(self.control_frame, 0)

        self.setStyleSheet("")

    def _load_settings(self) -> None:
        mode = load_setting_value("watermark_mode", "image", str)
        mode_index = self.mode_input.findData(mode)
        if mode_index < 0:
            mode_index = self.mode_input.findData("image")
        self.mode_input.setCurrentIndex(max(0, mode_index))
        self.image_path_input.setText(load_setting_value("watermark_path", "", str))
        self.text_input.setText(load_setting_value("watermark_text", "", str))
        self.opacity_input.setValue(load_setting_value("watermark_opacity", 1.0, float))
        self.logo_width_input.setValue(load_setting_value("watermark_scale_percent", 13.0, float))
        self.text_size_input.setValue(load_setting_value("watermark_text_size_percent", 3.0, float))
        self.margin_input.setValue(load_setting_value("watermark_margin_px", 16, int))
        position = load_setting_value("watermark_position", "br", str)
        position_index = self.position_input.findData(position)
        if position_index < 0:
            position_index = self.position_input.findData("br")
        self.position_input.setCurrentIndex(max(0, position_index))
        self.random_move_input.setChecked(load_setting_value("watermark_random_enabled", False, bool))
        self.random_interval_input.setValue(load_setting_value("watermark_random_interval_sec", 5, int))
        self._update_mode_ui()
        self._update_preview_pixmap()
        self._update_preview_overlay()

    def _save_settings(self) -> None:
        save_setting_value("watermark_mode", str(self.mode_input.currentData()))
        save_setting_value("watermark_path", self.image_path_input.text().strip())
        save_setting_value("watermark_text", self.text_input.text().strip())
        save_setting_value("watermark_opacity", float(self.opacity_input.value()))
        save_setting_value("watermark_scale_percent", float(self.logo_width_input.value()))
        save_setting_value("watermark_text_size_percent", float(self.text_size_input.value()))
        save_setting_value("watermark_margin_px", int(self.margin_input.value()))
        save_setting_value("watermark_position", str(self.position_input.currentData()))
        save_setting_value("watermark_random_enabled", int(self.random_move_input.isChecked()))
        save_setting_value("watermark_random_interval_sec", int(self.random_interval_input.value()))
        self.accept()

    def _update_mode_ui(self) -> None:
        mode = str(self.mode_input.currentData())
        is_text = mode == "text"
        self.text_input.setEnabled(True)
        self.text_size_input.setEnabled(True)
        self.image_path_input.setEnabled(True)
        self.image_browse.setEnabled(True)
        self.logo_width_input.setEnabled(True)
        self._update_preview_overlay()

    def _update_preview_text(self) -> None:
        if str(self.mode_input.currentData()) != "text":
            return
        text = self.text_input.text().strip() or "透かしテキスト"
        self.preview_label.setText(text)
        self._update_preview_overlay()

    def _browse_image_file(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "ロゴ画像を選択",
            "",
            "画像ファイル (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if file_path:
            self.image_path_input.setText(file_path)
            self._update_mode_ui()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if obj is self.preview_frame and event.type() == QtCore.QEvent.Type.Resize:
            self._update_preview_pixmap()
            self._position_overlay()
        return super().eventFilter(obj, event)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._update_preview_pixmap)
        QtCore.QTimer.singleShot(0, self._update_preview_overlay)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        try:
            self._temp_dir.cleanup()
        finally:
            super().closeEvent(event)

    def _is_dark_mode(self) -> bool:
        palette = QtGui.QGuiApplication.palette()
        return palette.color(QtGui.QPalette.ColorRole.Window).lightness() < 128

    def _apply_style(self) -> None:
        if self._is_dark_mode():
            c_dialog_bg = "#0f1117"
            c_panel_bg = "#111827"
            c_panel_border = "#1f2937"
            c_preview_bg = "#0b1220"
            c_preview_bg_alt = "#111827"
            c_label = "#cbd5e1"
            c_section = "#e2e8f0"
            c_field = "#94a3b8"
            c_input_bg = "#0f172a"
            c_input_text = "#e2e8f0"
            c_input_border = "#1f2937"
            c_focus = "#38bdf8"
            c_button_bg = "#0f172a"
            c_button_text = "#e2e8f0"
            c_primary_bg = "#38bdf8"
            c_primary_border = "#0ea5e9"
            c_primary_text = "#0b1220"
        else:
            c_dialog_bg = "#f8fafc"
            c_panel_bg = "#ffffff"
            c_panel_border = "#e2e8f0"
            c_preview_bg = "#f1f5f9"
            c_preview_bg_alt = "#e2e8f0"
            c_label = "#334155"
            c_section = "#0f172a"
            c_field = "#64748b"
            c_input_bg = "#ffffff"
            c_input_text = "#0f172a"
            c_input_border = "#cbd5e1"
            c_focus = "#0ea5e9"
            c_button_bg = "#ffffff"
            c_button_text = "#0f172a"
            c_primary_bg = "#0ea5e9"
            c_primary_border = "#0284c7"
            c_primary_text = "#ffffff"

        self.setStyleSheet(
            f"""
            QDialog {{ background: {c_dialog_bg}; }}
            QFrame#WatermarkPreview {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c_preview_bg}, stop:1 {c_preview_bg_alt});
                border: 1px solid {c_panel_border};
                border-radius: 6px;
            }}
            QFrame#WatermarkControls {{
                background: {c_panel_bg};
                border: 1px solid {c_panel_border};
                border-radius: 6px;
            }}
            QLabel {{ color: {c_label}; }}
            QLabel#SectionLabel {{ color: {c_section}; font-size: 13px; font-weight: 600; padding-top: 6px; }}
            QLabel#FieldLabel {{ color: {c_field}; font-size: 12px; }}
            QFrame#SectionDivider {{ background: {c_panel_border}; }}
            QLineEdit, QComboBox {{
                background: {c_input_bg};
                color: {c_input_text};
                border: 1px solid {c_input_border};
                padding: 6px 8px;
                border-radius: 6px;
            }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {c_focus}; }}
            QPushButton {{
                background: {c_button_bg};
                color: {c_button_text};
                border: 1px solid {c_input_border};
                padding: 6px 12px;
                border-radius: 6px;
            }}
            QPushButton:hover {{ border: 1px solid {c_focus}; }}
            QPushButton#PrimaryButton {{
                background: {c_primary_bg};
                border: 1px solid {c_primary_border};
                color: {c_primary_text};
                font-weight: 600;
            }}
            """
        )
    def _build_sample_pixmap(self, size: QtCore.QSize) -> QtGui.QPixmap:
        width = max(1, size.width())
        height = max(1, size.height())
        pixmap = QtGui.QPixmap(width, height)
        pixmap.fill(QtGui.QColor("#1f2937"))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        grad = QtGui.QLinearGradient(0, 0, width, height)
        grad.setColorAt(0.0, QtGui.QColor("#0f172a"))
        grad.setColorAt(1.0, QtGui.QColor("#1f2937"))
        painter.fillRect(pixmap.rect(), grad)
        painter.setPen(QtGui.QColor("#e2e8f0"))
        font_size = max(14, int(min(width, height) * 0.06))
        painter.setFont(QtGui.QFont("Arial", font_size))
        painter.drawText(QtCore.QRect(0, 0, width, height), QtCore.Qt.AlignmentFlag.AlignCenter, "16:9 SAMPLE")
        painter.end()
        return pixmap

    def _preview_rect(self) -> QtCore.QRect:
        rect = self.preview_frame.contentsRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return rect
        target_ratio = 16 / 9
        width = rect.width()
        height = rect.height()
        if width / height > target_ratio:
            new_width = int(height * target_ratio)
            x = rect.x() + (width - new_width) // 2
            return QtCore.QRect(x, rect.y(), new_width, height)
        new_height = int(width / target_ratio)
        y = rect.y() + (height - new_height) // 2
        return QtCore.QRect(rect.x(), y, width, new_height)

    def _update_preview_pixmap(self) -> None:
        rect = self._preview_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        if self._sample_source_pixmap and not self._sample_source_pixmap.isNull():
            scaled = self._sample_source_pixmap.scaled(
                rect.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)
            self._sample_source_size = self._sample_source_pixmap.size()
        else:
            sample = self._build_sample_pixmap(rect.size())
            self.preview_label.setPixmap(sample)
            self._sample_source_size = rect.size()
        self.preview_label.setGeometry(rect)

    def _update_preview_overlay(self) -> None:
        if self._composite_preview:
            self.preview_overlay_text.hide()
            self.preview_overlay_image.hide()
            return
        self._composite_preview = False
        mode = str(self.mode_input.currentData())
        base_rect = self._preview_rect()
        self.preview_overlay_text.hide()
        self.preview_overlay_image.hide()
        if mode == "text":
            text = self.text_input.text().strip() or "透かしテキスト"
            opacity = max(0.0, min(1.0, float(self.opacity_input.value())))
            size_ratio = max(0.01, min(0.2, float(self.text_size_input.value()) / 100.0))
            font = self.preview_overlay_text.font()
            font.setPointSizeF(max(8.0, base_rect.width() * size_ratio))
            self.preview_overlay_text.setFont(font)
            self.preview_overlay_text.setText(text)
            self.preview_overlay_text.setStyleSheet(
                f"color: rgba(255,255,255,{opacity:.2f}); font-size: {font.pointSizeF():.1f}px;"
            )
            self.preview_overlay_text.adjustSize()
            self.preview_overlay_text.show()
        else:
            path = self.image_path_input.text().strip()
            if path:
                pixmap = QtGui.QPixmap(path)
            else:
                pixmap = QtGui.QPixmap()
            if pixmap.isNull():
                self.preview_overlay_image.setText("ロゴ")
                self.preview_overlay_image.setStyleSheet("color: rgba(255,255,255,0.85);")
                self.preview_overlay_image.adjustSize()
            else:
                target_ratio = max(0.01, min(0.5, float(self.logo_width_input.value()) / 100.0))
                target_width = max(40, int(base_rect.width() * target_ratio))
                scaled = pixmap.scaledToWidth(target_width, QtCore.Qt.TransformationMode.SmoothTransformation)
                self.preview_overlay_image.setPixmap(scaled)
                self.preview_overlay_image.resize(scaled.size())
            opacity = max(0.0, min(1.0, float(self.opacity_input.value())))
            self._image_opacity_effect.setOpacity(opacity)
            self.preview_overlay_image.show()
        self._position_overlay()

    def _position_overlay(self) -> None:
        base_rect = self._preview_rect()
        scale = base_rect.width() / 1920.0 if base_rect.width() > 0 else 1.0
        if self._sample_source_size.width() > 0:
            scale = base_rect.width() / self._sample_source_size.width()
        margin = max(0, int(self.margin_input.value() * scale))
        if base_rect.width() <= 0 or base_rect.height() <= 0:
            return
        position = str(self.position_input.currentData())
        if self.random_move_input.isChecked():
            interval = max(1.0, float(self.random_interval_input.value()))
            t = QtCore.QDateTime.currentMSecsSinceEpoch() / 1000.0
            k = math.floor(t / interval) + 1.0
            def prand(seed: float, scale: float) -> float:
                return abs(math.modf(math.sin(seed) * scale)[0])
            if self.preview_overlay_text.isVisible():
                size = self.preview_overlay_text.size()
                avail_w = max(0, base_rect.width() - size.width() - margin * 2)
                avail_h = max(0, base_rect.height() - size.height() - margin * 2)
                rx = prand(k * 12.9898, 43758.5453)
                ry = prand(k * 78.233, 12515.8733)
                x = base_rect.x() + margin + int(avail_w * rx)
                y = base_rect.y() + margin + int(avail_h * ry)
                self.preview_overlay_text.move(x, y)
            if self.preview_overlay_image.isVisible():
                size = self.preview_overlay_image.size()
                avail_w = max(0, base_rect.width() - size.width() - margin * 2)
                avail_h = max(0, base_rect.height() - size.height() - margin * 2)
                rx = prand(k * 12.9898, 43758.5453)
                ry = prand(k * 78.233, 12515.8733)
                x = base_rect.x() + margin + int(avail_w * rx)
                y = base_rect.y() + margin + int(avail_h * ry)
                self.preview_overlay_image.move(x, y)
            return
        if self.preview_overlay_text.isVisible():
            size = self.preview_overlay_text.size()
            if position == "tl":
                x = base_rect.x() + margin
                y = base_rect.y() + margin
            elif position == "tr":
                x = base_rect.x() + base_rect.width() - size.width() - margin
                y = base_rect.y() + margin
            elif position == "bl":
                x = base_rect.x() + margin
                y = base_rect.y() + base_rect.height() - size.height() - margin
            else:
                x = base_rect.x() + base_rect.width() - size.width() - margin
                y = base_rect.y() + base_rect.height() - size.height() - margin
            self.preview_overlay_text.move(x, y)
        if self.preview_overlay_image.isVisible():
            size = self.preview_overlay_image.size()
            if position == "tl":
                x = base_rect.x() + margin
                y = base_rect.y() + margin
            elif position == "tr":
                x = base_rect.x() + base_rect.width() - size.width() - margin
                y = base_rect.y() + margin
            elif position == "bl":
                x = base_rect.x() + margin
                y = base_rect.y() + base_rect.height() - size.height() - margin
            else:
                x = base_rect.x() + base_rect.width() - size.width() - margin
                y = base_rect.y() + base_rect.height() - size.height() - margin
            self.preview_overlay_image.move(x, y)

    def _browse_preview_source(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "サンプルファイルを選択",
            "",
            "動画/画像ファイル (*.mp4 *.mov *.mkv *.webm *.avi *.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if file_path:
            self.preview_source_input.setText(file_path)

    def _load_preview_source(self) -> None:
        path = Path(self.preview_source_input.text().strip())
        self._composite_preview = False
        self._preview_source_path = path if path.exists() else None
        if not path.exists():
            self._sample_source_pixmap = None
            self._update_preview_pixmap()
            self._update_preview_overlay()
            return
        pixmap = QtGui.QPixmap(str(path))
        if not pixmap.isNull():
            self._sample_source_pixmap = pixmap
            self._update_preview_pixmap()
            self._update_preview_overlay()
            return
        ffmpeg_path = find_ffmpeg_path()
        if not ffmpeg_path:
            QtWidgets.QMessageBox.information(self, "情報", "動画のプレビューにはffmpegが必要です。")
            return
        temp_path = Path(self._temp_dir.name) / "preview_frame.png"
        command = [
            ffmpeg_path,
            "-y",
            "-ss",
            "1",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(temp_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0 or not temp_path.exists():
            QtWidgets.QMessageBox.information(self, "情報", "サンプルの抽出に失敗しました。")
            return
        frame_pixmap = QtGui.QPixmap(str(temp_path))
        if frame_pixmap.isNull():
            QtWidgets.QMessageBox.information(self, "情報", "サンプル画像の読み込みに失敗しました。")
            return
        self._sample_source_pixmap = frame_pixmap
        self._update_preview_pixmap()
        self._update_preview_overlay()

    def _render_exact_preview(self) -> None:
        if not self._preview_source_path or not self._preview_source_path.exists():
            QtWidgets.QMessageBox.information(self, "情報", "サンプルファイルを指定してください。")
            return
        ffmpeg_path = find_ffmpeg_path()
        if not ffmpeg_path:
            QtWidgets.QMessageBox.information(self, "情報", "正確プレビューにはffmpegが必要です。")
            return
        mode = str(self.mode_input.currentData())
        opacity = max(0.0, min(1.0, float(self.opacity_input.value())))
        margin = max(0, int(self.margin_input.value()))
        output_path = Path(self._temp_dir.name) / "preview_composite.png"
        command = [ffmpeg_path, "-y"]
        is_image = self._preview_source_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        if not is_image:
            command += ["-ss", "1"]
        command += ["-i", str(self._preview_source_path)]
        if mode == "image":
            watermark_path = self.image_path_input.text().strip()
            if not watermark_path:
                QtWidgets.QMessageBox.information(self, "情報", "ロゴ画像ファイルを指定してください。")
                return
            scale_percent = float(self.logo_width_input.value())
            scale_ratio = max(0.01, min(1.0, scale_percent / 100.0))
            random_enabled = self.random_move_input.isChecked()
            interval = max(1, int(self.random_interval_input.value()))
            position = str(self.position_input.currentData())
            if random_enabled:
                x_expr = (
                    f"{margin} + max(0\\, W-w-2*{margin})*"
                    f"mod(mod(sin((floor(t/{interval})+1)*12.9898)*43758.5453\\,1)+1\\,1)"
                )
                y_expr = (
                    f"{margin} + max(0\\, H-h-2*{margin})*"
                    f"mod(mod(sin((floor(t/{interval})+1)*78.233)*12515.8733\\,1)+1\\,1)"
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
            command += [
                "-loop",
                "1",
                "-i",
                watermark_path,
                "-filter_complex",
                filter_graph,
                "-map",
                "[v]",
                "-frames:v",
                "1",
                str(output_path),
            ]
        else:
            text = self.text_input.text().strip()
            if not text:
                QtWidgets.QMessageBox.information(self, "情報", "透かしテキストを入力してください。")
                return
            text_size = float(self.text_size_input.value())
            size_ratio = max(0.01, min(0.2, text_size / 100.0))
            escaped_text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")
            fontcolor = f"white@{opacity:.2f}"
            random_enabled = self.random_move_input.isChecked()
            interval = max(1, int(self.random_interval_input.value()))
            position = str(self.position_input.currentData())
            if random_enabled:
                x_expr = (
                    f"{margin} + max(0\\, w-tw-2*{margin})*"
                    f"mod(mod(sin((floor(t/{interval})+1)*12.9898)*43758.5453\\,1)+1\\,1)"
                )
                y_expr = (
                    f"{margin} + max(0\\, h-th-2*{margin})*"
                    f"mod(mod(sin((floor(t/{interval})+1)*78.233)*12515.8733\\,1)+1\\,1)"
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
                f"fontcolor={fontcolor}:borderw=2:bordercolor=black@0.6[v]"
            )
            command += [
                "-vf",
                filter_graph,
                "-frames:v",
                "1",
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
        if result.returncode != 0 or not output_path.exists():
            QtWidgets.QMessageBox.information(self, "情報", "正確プレビューの生成に失敗しました。")
            return
        pixmap = QtGui.QPixmap(str(output_path))
        if pixmap.isNull():
            QtWidgets.QMessageBox.information(self, "情報", "正確プレビューの読み込みに失敗しました。")
            return
        self._sample_source_pixmap = pixmap
        self._sample_source_size = pixmap.size()
        self._composite_preview = True
        self._update_preview_pixmap()
        self.preview_overlay_text.hide()
        self.preview_overlay_image.hide()

    def _on_setting_changed(self) -> None:
        if not self._preview_source_path or not self._preview_source_path.exists():
            if self._composite_preview:
                self._composite_preview = False
                self._update_preview_pixmap()
                self._update_preview_overlay()
            return
        if not self.exact_preview_toggle.isChecked():
            if self._composite_preview:
                self._composite_preview = False
            self._update_preview_pixmap()
            self._update_preview_overlay()
            return
        self._exact_preview_timer.start(300)

    def _on_exact_preview_toggled(self, enabled: bool) -> None:
        if not enabled:
            self._composite_preview = False
            self._update_preview_pixmap()
            self._update_preview_overlay()
            return
        if self._preview_source_path and self._preview_source_path.exists():
            self._exact_preview_timer.start(100)
