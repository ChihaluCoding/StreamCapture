# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6 import QtCore, QtGui, QtWidgets
from string import Template
from config import (
    DEFAULT_AUTO_CHECK_INTERVAL_SEC, DEFAULT_AUTO_ENABLED, DEFAULT_BILIBILI_ENTRIES,
    DEFAULT_ABEMA_ENTRIES, DEFAULT_BIGO_ENTRIES, DEFAULT_FUWATCH_ENTRIES,
    DEFAULT_LIVE17_ENTRIES, DEFAULT_TIMESHIFT_SEGMENT_HOURS,
    DEFAULT_TIMESHIFT_SEGMENT_MINUTES,
    DEFAULT_TIMESHIFT_SEGMENT_SECONDS,
    DEFAULT_KICK_ENTRIES, DEFAULT_NICONICO_ENTRIES, DEFAULT_OPENRECTV_ENTRIES,
    DEFAULT_OUTPUT_FORMAT, DEFAULT_RADIKO_ENTRIES, DEFAULT_RETRY_COUNT,
    DEFAULT_RETRY_WAIT_SEC, DEFAULT_TIKTOK_ENTRIES, DEFAULT_TWITCASTING_ENTRIES,
    DEFAULT_RECORDING_QUALITY,
    DEFAULT_RECORDING_MAX_SIZE_MB, DEFAULT_RECORDING_SIZE_MARGIN_MB,
    DEFAULT_AUTO_COMPRESS_MAX_HEIGHT,
    OUTPUT_FORMAT_FLV, OUTPUT_FORMAT_MKV, OUTPUT_FORMAT_MOV, OUTPUT_FORMAT_MP3,
    OUTPUT_FORMAT_MP4_COPY, OUTPUT_FORMAT_MP4_LIGHT, OUTPUT_FORMAT_TS, OUTPUT_FORMAT_WAV,
)
from settings_store import load_bool_setting, load_setting_value, save_setting_value

# =============================================================================
# Custom Widgets (Modern Style)
# =============================================================================

class ToggleSwitch(QtWidgets.QWidget):
    """モダンなアニメーション付きトグルスイッチ"""
    toggled = QtCore.pyqtSignal(bool)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = False
        self._pos_progress = 0.0
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        self._anim = QtCore.QPropertyAnimation(self, b"pos_progress", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)

    def isChecked(self) -> bool: return self._checked
    def setChecked(self, checked: bool) -> None:
        if self._checked == checked: return
        self._checked = checked
        self.toggled.emit(self._checked)
        self._anim.stop()
        self._anim.setStartValue(self._pos_progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
    def setCheckedImmediate(self, checked: bool) -> None:
        if self._checked == checked:
            return
        self._checked = checked
        self._anim.stop()
        self._pos_progress = 1.0 if checked else 0.0
        self.update()
    def toggle(self) -> None: self.setChecked(not self.isChecked())
    def sizeHint(self) -> QtCore.QSize: return QtCore.QSize(48, 26)
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton: self.toggle()
    
    def get_pos_progress(self) -> float:  # アニメーション位置の取得
        return float(getattr(self, "_pos_progress", 0.0))  # 未初期化時の保険を含めて返す

    def set_pos_progress(self, p: float) -> None:  # アニメーション位置の更新
        self._pos_progress = float(p)  # 値を安全に反映する
        self.update()  # 再描画を要求する

    pos_progress = QtCore.pyqtProperty(float, get_pos_progress, set_pos_progress)  # プロパティ登録

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        h = rect.height()
        w = rect.width()
        
        c_off = QtGui.QColor("#cbd5e1") # Gray 300
        c_on = QtGui.QColor("#0ea5e9")  # Sky 500
        
        current_color = self._interpolate_color(c_off, c_on, self._pos_progress)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(current_color)
        painter.drawRoundedRect(rect, h/2, h/2)
        
        padding = 3
        knob_size = h - padding*2
        x_off = padding
        x_on = w - knob_size - padding
        curr_x = x_off + (x_on - x_off) * self._pos_progress
        
        painter.setBrush(QtGui.QColor("white"))
        painter.drawEllipse(QtCore.QRectF(curr_x, padding, knob_size, knob_size))

    def _interpolate_color(self, c1, c2, ratio):
        r = c1.red() + (c2.red() - c1.red()) * ratio
        g = c1.green() + (c2.green() - c1.green()) * ratio
        b = c1.blue() + (c2.blue() - c1.blue()) * ratio
        return QtGui.QColor(int(r), int(g), int(b))


class ModernSpinBox(QtWidgets.QWidget):
    """
    [ Value       ][ - ][ + ]
    入力欄の右側に操作ボタンをまとめた数値入力
    """
    valueChanged = QtCore.pyqtSignal(object)

    def __init__(self, mode: str = 'int', parent=None):
        super().__init__(parent)
        self._mode = mode
        self._value = 0 if mode == 'int' else 0.0
        self._min = 0
        self._max = 9999
        self._step = 1 if mode == 'int' else 0.1
        self._decimals = 2
        
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 1. 入力エリア (左)
        self.line_edit = QtWidgets.QLineEdit()
        self.line_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.line_edit.setObjectName("SpinInput")
        self.line_edit.setFixedHeight(38)
        
        # 2. マイナスボタン (中)
        self.btn_minus = _SpinGlyphButton("minus")
        self.btn_minus.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_minus.setObjectName("SpinBtnMinus")
        self.btn_minus.setFixedSize(40, 38)
        
        # 3. プラスボタン (右)
        self.btn_plus = _SpinGlyphButton("plus")
        self.btn_plus.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_plus.setObjectName("SpinBtnPlus")
        self.btn_plus.setFixedSize(40, 38)
        
        # 配置
        layout.addWidget(self.line_edit)
        layout.addWidget(self.btn_minus)
        layout.addWidget(self.btn_plus)
        
        self.btn_minus.clicked.connect(self._decrement)
        self.btn_plus.clicked.connect(self._increment)
        self.line_edit.editingFinished.connect(self._on_editing_finished)
        
        self._update_display()

    def _update_display(self):
        if self._mode == 'int':
            self.line_edit.setText(str(int(self._value)))
        else:
            fmt = "{:." + str(self._decimals) + "f}"
            self.line_edit.setText(fmt.format(self._value))

    def _increment(self):
        self.setValue(self._value + self._step)

    def _decrement(self):
        self.setValue(self._value - self._step)

    def _on_editing_finished(self):
        try:
            val = float(self.line_edit.text()) if self._mode == 'float' else int(self.line_edit.text())
            self.setValue(val)
        except ValueError:
            self._update_display()

    def setValue(self, val):
        if self._mode == 'int': val = int(val)
        else: val = float(val)
        val = max(self._min, min(self._max, val))
        if self._value != val:
            self._value = val
            self.valueChanged.emit(val)
        self._update_display()

    def value(self): return self._value
    def setRange(self, mn, mx): self._min = mn; self._max = mx; self.setValue(self._value)
    def setSingleStep(self, s): self._step = s
    def setDecimals(self, d): self._decimals = d; self._update_display()


# フォント依存を避けるため、＋／－を線で描画する
class _SpinGlyphButton(QtWidgets.QPushButton):
    def __init__(self, glyph: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("", parent)
        self._glyph = glyph

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = self.palette().color(QtGui.QPalette.ColorRole.ButtonText)
        painter.setPen(QtGui.QPen(color, 2))
        rect = self.rect()
        cx = rect.center().x()
        cy = rect.center().y()
        size = min(rect.width(), rect.height()) * 0.18
        painter.drawLine(QtCore.QPointF(cx - size, cy), QtCore.QPointF(cx + size, cy))
        if self._glyph == "plus":
            painter.drawLine(QtCore.QPointF(cx, cy - size), QtCore.QPointF(cx, cy + size))

# =============================================================================
# Main Settings Dialog
# =============================================================================

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.resize(950, 700)
        self._apply_global_style()
        self._init_ui()
        self._suppress_gdrive_confirm = True
        try:
            self._load_settings()
        finally:
            self._suppress_gdrive_confirm = False

    def _is_dark_mode(self) -> bool:
        palette = QtGui.QGuiApplication.palette()
        return palette.color(QtGui.QPalette.ColorRole.Window).lightness() < 128

    def _apply_global_style(self):
        # 優先順位を明確にするため、IDセレクタを強化し、記述順序を整理
        is_dark = self._is_dark_mode()
        if is_dark:
            c_dialog_bg = "#0f172a"
            c_sidebar_bg = "#0b1220"
            c_sidebar_border = "#1f2a44"
            c_sidebar_item = "#94a3b8"
            c_sidebar_selected_bg = "#0b2a3a"
            c_sidebar_selected_text = "#38bdf8"
            c_sidebar_hover_bg = "#111827"
            c_sidebar_hover_text = "#e2e8f0"
            c_page_title = "#e2e8f0"
            c_desc = "#94a3b8"
            c_card_bg = "#0b1220"
            c_card_border = "#1f2a44"
            c_footer_bg = "#0b1220"
            c_footer_border = "#1f2a44"
            c_input_bg = "#0f172a"
            c_input_border = "#334155"
            c_input_text = "#e2e8f0"
            c_input_focus_bg = "#111827"
            c_focus_border = "#38bdf8"
            c_spin_input_bg = "#111827"
            c_spin_btn_bg = "#0f172a"
            c_spin_btn_border = "#334155"
            c_spin_btn_text = "#e2e8f0"
            c_spin_btn_hover_bg = "#111827"
            c_spin_btn_hover_text = "#38bdf8"
            c_spin_btn_pressed = "#0b1220"
            c_combo_bg = "#0f172a"
            c_combo_border = "#334155"
            c_combo_text = "#e2e8f0"
            c_combo_focus_bg = "#111827"
            c_combo_arrow = "#94a3b8"
            c_button_bg = "#0f172a"
            c_button_border = "#334155"
            c_button_text = "#e2e8f0"
            c_button_hover_bg = "#111827"
            c_button_hover_border = "#475569"
            c_button_hover_text = "#ffffff"
            c_primary_bg = "#38bdf8"
            c_primary_border = "#0ea5e9"
            c_primary_hover_bg = "#0ea5e9"
            c_primary_hover_border = "#0284c7"
            c_primary_pressed = "#0284c7"
            c_base_text = "#e2e8f0"
            self._label_color = "#e2e8f0"
            self._muted_label_color = "#cbd5e1"
            self._section_label_color = "#e2e8f0"
        else:
            c_dialog_bg = "#f1f5f9"
            c_sidebar_bg = "#ffffff"
            c_sidebar_border = "#e2e8f0"
            c_sidebar_item = "#475569"
            c_sidebar_selected_bg = "#e0f2fe"
            c_sidebar_selected_text = "#0284c7"
            c_sidebar_hover_bg = "#f8fafc"
            c_sidebar_hover_text = "#334155"
            c_page_title = "#0f172a"
            c_desc = "#64748b"
            c_card_bg = "#ffffff"
            c_card_border = "#e2e8f0"
            c_footer_bg = "#ffffff"
            c_footer_border = "#e2e8f0"
            c_input_bg = "#f8fafc"
            c_input_border = "#cbd5e1"
            c_input_text = "#1e293b"
            c_input_focus_bg = "#ffffff"
            c_focus_border = "#0ea5e9"
            c_spin_input_bg = "#ffffff"
            c_spin_btn_bg = "#f8fafc"
            c_spin_btn_border = "#cbd5e1"
            c_spin_btn_text = "#475569"
            c_spin_btn_hover_bg = "#e2e8f0"
            c_spin_btn_hover_text = "#0ea5e9"
            c_spin_btn_pressed = "#cbd5e1"
            c_combo_bg = "#f8fafc"
            c_combo_border = "#cbd5e1"
            c_combo_text = "#1e293b"
            c_combo_focus_bg = "#ffffff"
            c_combo_arrow = "#64748b"
            c_button_bg = "#ffffff"
            c_button_border = "#cbd5e1"
            c_button_text = "#475569"
            c_button_hover_bg = "#f8fafc"
            c_button_hover_border = "#94a3b8"
            c_button_hover_text = "#0f172a"
            c_primary_bg = "#0ea5e9"
            c_primary_border = "#0284c7"
            c_primary_hover_bg = "#0284c7"
            c_primary_hover_border = "#0369a1"
            c_primary_pressed = "#0369a1"
            c_base_text = "#334155"
            self._label_color = "#1e293b"
            self._muted_label_color = "#475569"
            self._section_label_color = "#1e293b"

        colors = {k: v for k, v in locals().items() if k.startswith("c_")}

        self.setStyleSheet(Template("""
            /* ベース設定 */
            QDialog {
                background-color: $c_dialog_bg;
                font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
                font-size: 14px;
                color: $c_base_text;
            }
            
            /* --- サイドバー --- */
            QListWidget {
                background-color: $c_sidebar_bg;
                border: none;
                border-right: 1px solid $c_sidebar_border;
                outline: none;
                padding-top: 10px;
            }
            QListWidget::item {
                height: 44px;
                padding-left: 12px;
                margin: 4px 8px;
                border-radius: 6px;
                color: $c_sidebar_item;
                font-weight: 600;
            }
            QListWidget::item:selected {
                background-color: $c_sidebar_selected_bg;
                color: $c_sidebar_selected_text;
            }
            QListWidget::item:hover:!selected {
                background-color: $c_sidebar_hover_bg;
                color: $c_sidebar_hover_text;
            }

            /* --- コンテンツエリア --- */
            QScrollArea { border: none; background: transparent; }
            QWidget#PageContent { background-color: transparent; }
            
            QLabel#PageTitle {
                font-size: 22px;
                font-weight: bold;
                color: $c_page_title;
                margin-bottom: 20px;
            }
            QLabel#Description {
                color: $c_desc;
                font-size: 13px;
                margin-bottom: 8px;
            }

            /* カード */
            QFrame#Card {
                background-color: $c_card_bg;
                border: 1px solid $c_card_border;
                border-radius: 10px;
            }

            /* フッター */
            QFrame#Footer {
                background-color: $c_footer_bg;
                border-top: 1px solid $c_footer_border;
            }

            /* --- 入力フィールド (共通) --- */
            QLineEdit, QPlainTextEdit {
                background-color: $c_input_bg;
                border: 1px solid $c_input_border;
                border-radius: 6px;
                padding: 8px 12px;
                color: $c_input_text;
                selection-background-color: $c_focus_border;
            }
            QLineEdit:focus, QPlainTextEdit:focus {
                background-color: $c_input_focus_bg;
                border: 2px solid $c_focus_border;
                padding: 7px 11px;
            }

            /* --- スピンボックス (ModernSpinBox) --- */
            /* 入力部 (左) */
            QLineEdit#SpinInput {
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                border-right: none; /* ボタンと結合 */
                background-color: $c_spin_input_bg;
                font-weight: 600;
            }
            QLineEdit#SpinInput:focus {
                border: 2px solid $c_focus_border;
            }
            
            /* マイナスボタン (中) */
            QPushButton#SpinBtnMinus {
                background-color: $c_spin_btn_bg;
                border: 1px solid $c_spin_btn_border;
                border-right: none; /* プラスボタンと結合 */
                border-radius: 0px; /* 角丸なし */
                color: $c_spin_btn_text;
                font-family: "Helvetica Neue", "Arial", "Segoe UI", "Yu Gothic UI", sans-serif;
                font-weight: 600;
                font-size: 16px;
            }
            QPushButton#SpinBtnMinus:hover { background-color: $c_spin_btn_hover_bg; color: $c_spin_btn_hover_text; }
            QPushButton#SpinBtnMinus:pressed { background-color: $c_spin_btn_pressed; }

            /* プラスボタン (右) */
            QPushButton#SpinBtnPlus {
                background-color: $c_spin_btn_bg;
                border: 1px solid $c_spin_btn_border;
                border-left: 1px solid $c_spin_btn_border; /* 区切り線 */
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                color: $c_spin_btn_text;
                font-family: "Helvetica Neue", "Arial", "Segoe UI", "Yu Gothic UI", sans-serif;
                font-weight: 600;
                font-size: 16px;
            }
            QPushButton#SpinBtnPlus:hover { background-color: $c_spin_btn_hover_bg; color: $c_spin_btn_hover_text; }
            QPushButton#SpinBtnPlus:pressed { background-color: $c_spin_btn_pressed; }

            /* --- コンボボックス --- */
            QComboBox {
                background-color: $c_combo_bg;
                border: 1px solid $c_combo_border;
                border-radius: 6px;
                padding: 8px 12px;
                color: $c_combo_text;
            }
            QComboBox:focus {
                background-color: $c_combo_focus_bg;
                border: 2px solid $c_focus_border;
            }
            /* --- 通常ボタン --- */
            QPushButton {
                background-color: $c_button_bg;
                border: 1px solid $c_button_border;
                border-radius: 6px;
                padding: 8px 16px;
                color: $c_button_text;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: $c_button_hover_bg;
                border-color: $c_button_hover_border;
                color: $c_button_hover_text;
            }
            
            /* --- 保存ボタン (Primary) - IDセレクタで強力に指定 --- */
            QPushButton#PrimaryButton {
                background-color: $c_primary_bg;
                border: 1px solid $c_primary_border;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton#PrimaryButton:hover {
                background-color: $c_primary_hover_bg;
                border-color: $c_primary_hover_border;
            }
            QPushButton#PrimaryButton:pressed {
                background-color: $c_primary_pressed;
            }

            /* --- 折りたたみヘッダー --- */
            QToolButton#CollapsibleHeader {
                background: transparent;
                border: none;
                padding: 2px 0;
            }
            QToolButton#CollapsibleHeader:checked {
                background: transparent;
                border: none;
            }
        """).substitute(colors))

    def _init_ui(self):
        # メインレイアウト（水平分割）
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. 左サイドバー
        self.sidebar = QtWidgets.QListWidget()
        self.sidebar.setFixedWidth(240)
        self.sidebar.addItems([
            "一般設定",
            "保存・整理",
            "ネットワーク・録画",
            "自動化・監視",
            "監視リスト",
            "API連携",
            "Google Drive",
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
        self.stack.addWidget(self._page_network())
        self.stack.addWidget(self._page_automation())
        self.stack.addWidget(self._page_monitoring())
        self.stack.addWidget(self._page_api())
        self.stack.addWidget(self._page_gdrive())
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

    # --- Pages Implementation ---

    def _page_general(self):
        page, layout = self._make_scrollable_page("一般設定")
        # プレビュー音量
        self.preview_volume_input = ModernSpinBox('float')
        self.preview_volume_input.setRange(0.0, 1.0)
        self.preview_volume_input.setSingleStep(0.1)
        self._add_card(layout, "プレビュー音量", self.preview_volume_input, "プレビュー再生時の初期音量 (0.0 ~ 1.0)")

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
            "クリップ分割間隔",
            segment_widget,
            "時間/分/秒で分割間隔を指定します (0時間0分0秒は10秒として扱います)。",
        )

        layout.addStretch(1)
        return page

    def _page_storage(self):
        page, layout = self._make_scrollable_page("保存・整理")

        # 保存先
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

        self.output_date_folder_input = ToggleSwitch()
        self._add_card(layout, "日付フォルダで整理", self.output_date_folder_input, "録画日ごとにフォルダ分けします。")

        self.output_filename_with_channel_input = ToggleSwitch()
        self._add_card(layout, "ファイル名に配信者名を付ける", self.output_filename_with_channel_input, "録画ファイル名に配信者名を付加します。")

        self.keep_ts_input = ToggleSwitch()
        self._add_card(layout, "TSファイルを残す", self.keep_ts_input, "MP4保存時でも元のTSファイルを残します。")

        self.recording_max_size_input = ModernSpinBox('int')
        self.recording_max_size_input.setRange(0, 1024 * 1024)
        self._add_card(layout, "録画ファイルの最大サイズ (MB)", self.recording_max_size_input, "0にすると無制限になります。")

        self.recording_size_margin_input = ModernSpinBox('int')
        self.recording_size_margin_input.setRange(0, 1024 * 1024)
        self._add_card(layout, "録画サイズ切替の余裕 (MB)", self.recording_size_margin_input, "上限に達する前に切り替える余裕幅です。")

        self.auto_compress_enabled_input = ToggleSwitch()
        self.auto_compress_enabled_input.toggled.connect(self._update_auto_compress_option_state)
        self._add_card(layout, "録画後に自動圧縮", self.auto_compress_enabled_input, "録画後に再エンコードして容量を削減します。")

        self.auto_compress_codec_input = QtWidgets.QComboBox()
        self.auto_compress_codec_input.addItems([
            "H.264 (libx264)",
            "H.265 (libx265)",
        ])
        self.auto_compress_codec_input.setItemData(0, "libx264")
        self.auto_compress_codec_input.setItemData(1, "libx265")
        self._add_input_card(layout, "圧縮コーデック", self.auto_compress_codec_input, "互換性重視はH.264がおすすめです。")

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
            "1444p",
            "2160p",
        ])
        self.auto_compress_resolution_input.setItemData(0, 0)
        self.auto_compress_resolution_input.setItemData(1, 144)
        self.auto_compress_resolution_input.setItemData(2, 240)
        self.auto_compress_resolution_input.setItemData(3, 360)
        self.auto_compress_resolution_input.setItemData(4, 480)
        self.auto_compress_resolution_input.setItemData(5, 720)
        self.auto_compress_resolution_input.setItemData(6, 1080)
        self.auto_compress_resolution_input.setItemData(7, 1444)
        self.auto_compress_resolution_input.setItemData(8, 2160)
        self._add_input_card(layout, "圧縮の最大解像度", self.auto_compress_resolution_input, "元の解像度より高い値は適用されません。")

        self.auto_compress_video_bitrate_input = ModernSpinBox('int')
        self.auto_compress_video_bitrate_input.setRange(100, 50000)
        self._add_card(layout, "圧縮の映像ビットレート (kbps)", self.auto_compress_video_bitrate_input, "数値が小さいほど容量が減ります。")

        self.auto_compress_audio_bitrate_input = ModernSpinBox('int')
        self.auto_compress_audio_bitrate_input.setRange(32, 320)
        self._add_card(layout, "圧縮の音声ビットレート (kbps)", self.auto_compress_audio_bitrate_input, "音声の圧縮率を指定します。")

        self.auto_compress_keep_original_input = ToggleSwitch()
        self._add_card(layout, "圧縮前のファイルを残す", self.auto_compress_keep_original_input, "ONにすると元の録画ファイルを保持します。")

        layout.addStretch(1)
        return page

    def _page_network(self):
        page, layout = self._make_scrollable_page("ネットワーク・録画設定")
        
        self.retry_count_input = ModernSpinBox('int')
        self.retry_count_input.setRange(0, 99)
        self._add_card(layout, "再接続リトライ回数", self.retry_count_input, "切断時に再接続を試みる最大回数")

        self.retry_wait_input = ModernSpinBox('int')
        self.retry_wait_input.setRange(1, 3600)
        self._add_card(layout, "リトライ待機時間 (秒)", self.retry_wait_input, "再接続までの待機時間")

        self.http_timeout_input = ModernSpinBox('int')
        self.http_timeout_input.setRange(1, 300)
        self._add_card(layout, "HTTPタイムアウト (秒)", self.http_timeout_input, "通信応答がない場合のタイムアウト時間")

        self.stream_timeout_input = ModernSpinBox('int')
        self.stream_timeout_input.setRange(1, 600)
        self._add_card(layout, "ストリーム待機 (秒)", self.stream_timeout_input, "映像データが途切れた際の待機時間")

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

        layout.addStretch(1)
        return page

    def _page_automation(self):
        page, layout = self._make_scrollable_page("自動化・監視設定")
        
        self.auto_enabled_input = ToggleSwitch()
        self.auto_enabled_input.toggled.connect(self._update_auto_record_option_state)
        self._add_card(layout, "自動録画機能", self.auto_enabled_input, "監視リストの配信が開始されたら自動で録画します。")

        self.auto_startup_input = ToggleSwitch()
        self._add_card(layout, "アプリ起動時に監視開始", self.auto_startup_input, "アプリを起動した直後から監視をスタートします。")

        self.auto_notify_only_input = ToggleSwitch()
        self._add_card(layout, "通知のみで監視", self.auto_notify_only_input, "配信を検知しても録画せず、通知だけを行います。")

        self.auto_check_interval_input = ModernSpinBox('int')
        self.auto_check_interval_input.setRange(20, 3600)
        self._add_card(layout, "監視サイクル (秒)", self.auto_check_interval_input, "配信状態をチェックする間隔")

        layout.addStretch(1)
        return page

    def _page_monitoring(self):
        page, layout = self._make_scrollable_page("監視対象リスト")
        
        desc = QtWidgets.QLabel("各サービスのURLまたはIDを1行に1つ入力してください。")
        desc.setObjectName("Description")
        layout.addWidget(desc)

        def add_collapsible_text_area(title, ph):
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
            "通知のみ対象",
            "URL/ID/チャンネルを1行ずつ（監視リストに含めたもののみ有効）",
        )
        self.youtube_channels_input = add_collapsible_text_area("YouTube", "例: https://www.youtube.com/@channel")
        self.twitch_channels_input = add_collapsible_text_area("Twitch", "例: https://www.twitch.tv/shaka")
        self.twitcasting_input = add_collapsible_text_area("ツイキャス", "ID または URL")
        self.niconico_input = add_collapsible_text_area("ニコニコ生放送", "コミュニティID または URL")
        self.tiktok_input = add_collapsible_text_area("TikTok", "@handle または URL")
        self.fuwatch_input = add_collapsible_text_area("ふわっち", "URL")
        self.kick_input = add_collapsible_text_area("Kick", "URL")
        self.live17_input = add_collapsible_text_area("17LIVE", "URL")
        self.bigo_input = add_collapsible_text_area("BIGO LIVE", "URL または ID")
        self.radiko_input = add_collapsible_text_area("radiko", "URL")
        self.openrectv_input = add_collapsible_text_area("OPENREC.tv", "URL")
        self.bilibili_input = add_collapsible_text_area("bilibili", "URL")
        self.abema_input = add_collapsible_text_area("AbemaTV", "URL")

        layout.addStretch(1)
        return page

    def _page_system(self):
        page, layout = self._make_scrollable_page("ログ・システム")
        
        self.tray_enabled_input = ToggleSwitch()
        self._add_card(layout, "タスクトレイ常駐", self.tray_enabled_input, "ウィンドウを閉じてもバックグラウンドで動作します。")

        self.auto_start_input = ToggleSwitch()
        self._add_card(layout, "PC起動時に自動実行", self.auto_start_input, "PC起動時にソフトを自動で立ち上げます。")

        lbl = QtWidgets.QLabel("ログ表示設定")
        lbl.setStyleSheet(f"font-weight: bold; margin-top: 16px; font-size: 15px; color: {self._section_label_color};")
        layout.addWidget(lbl)

        self.log_panel_visible_input = ToggleSwitch()
        self._add_card(layout, "ログパネル表示", self.log_panel_visible_input, "右側のログパネルを表示します。")

        layout.addStretch(1)
        return page

    def _page_api(self):
        page, layout = self._make_scrollable_page("APIキー設定")
        
        self.youtube_api_key_input = QtWidgets.QLineEdit()
        self.youtube_api_key_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.youtube_api_key_input.setPlaceholderText("API Key")
        self._add_input_card(layout, "YouTube Data API v3", self.youtube_api_key_input, "YouTubeの監視精度を向上させるために使用します。")
        
        self.twitch_client_id_input = QtWidgets.QLineEdit()
        self.twitch_client_id_input.setPlaceholderText("Client ID")
        self._add_input_card(layout, "Twitch Client ID", self.twitch_client_id_input)
        
        self.twitch_client_secret_input = QtWidgets.QLineEdit()
        self.twitch_client_secret_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.twitch_client_secret_input.setPlaceholderText("Client Secret")
        self._add_input_card(layout, "Twitch Client Secret", self.twitch_client_secret_input)
        layout.addStretch(1)
        return page

    def _page_gdrive(self):
        page, layout = self._make_scrollable_page("Google Drive連携")

        self.gdrive_enabled_input = ToggleSwitch()
        self.gdrive_enabled_input.installEventFilter(self)
        self._add_card(layout, "Google Driveへ自動アップロード", self.gdrive_enabled_input, "録画完了後にGoogle Driveへアップロードします。")

        self.gdrive_credentials_input = QtWidgets.QLineEdit()
        self.gdrive_credentials_input.setPlaceholderText("client_secret.json のパス")
        self.gdrive_credentials_browse = QtWidgets.QPushButton("参照")
        self.gdrive_credentials_browse.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.gdrive_credentials_browse.clicked.connect(self._browse_gdrive_credentials)
        creds_row = QtWidgets.QHBoxLayout()
        creds_row.addWidget(self.gdrive_credentials_input)
        creds_row.addWidget(self.gdrive_credentials_browse)
        creds_wrapper = QtWidgets.QWidget()
        creds_wrapper.setLayout(creds_row)
        creds_row.setContentsMargins(0, 0, 0, 0)
        self._add_input_card(layout, "Google Drive 認証情報 (JSON)", creds_wrapper, "Google Cloudで作成したOAuthクライアントJSONを指定します。")

        self.gdrive_folder_input = QtWidgets.QLineEdit()
        self.gdrive_folder_input.setPlaceholderText("保存先フォルダID (未指定はマイドライブ直下)")
        self._add_input_card(layout, "Google Drive 保存先フォルダID", self.gdrive_folder_input, "フォルダIDを指定すると、そのフォルダに保存します。")

        layout.addStretch(1)
        return page

    # --- Loading & Saving Logic ---

    def _load_settings(self) -> None:
        self.output_dir_input.setText(load_setting_value("output_dir", "recordings", str))
        
        fmt = load_setting_value("output_format", DEFAULT_OUTPUT_FORMAT, str).lower()
        idx = self.output_format_input.findData(fmt)
        if idx < 0: idx = self.output_format_input.findData(DEFAULT_OUTPUT_FORMAT)
        self.output_format_input.setCurrentIndex(max(0, idx))

        self.output_date_folder_input.setChecked(load_bool_setting("output_date_folder_enabled", False))
        self.output_filename_with_channel_input.setChecked(load_bool_setting("output_filename_with_channel", False))

        self.gdrive_enabled_input.setChecked(load_bool_setting("gdrive_enabled", False))
        self.gdrive_credentials_input.setText(load_setting_value("gdrive_credentials_path", "", str))
        self.gdrive_folder_input.setText(load_setting_value("gdrive_folder_id", "", str))
            
        self.retry_count_input.setValue(load_setting_value("retry_count", DEFAULT_RETRY_COUNT, int))
        self.retry_wait_input.setValue(load_setting_value("retry_wait", DEFAULT_RETRY_WAIT_SEC, int))
        self.http_timeout_input.setValue(load_setting_value("http_timeout", 20, int))
        self.stream_timeout_input.setValue(load_setting_value("stream_timeout", 60, int))
        self.preview_volume_input.setValue(load_setting_value("preview_volume", 0.5, float))
        self.keep_ts_input.setChecked(load_bool_setting("keep_ts_file", False))
        self.recording_max_size_input.setValue(load_setting_value("recording_max_size_mb", DEFAULT_RECORDING_MAX_SIZE_MB, int))
        self.recording_size_margin_input.setValue(load_setting_value("recording_size_margin_mb", DEFAULT_RECORDING_SIZE_MARGIN_MB, int))
        self.auto_compress_enabled_input.setChecked(load_bool_setting("auto_compress_enabled", False))
        codec = load_setting_value("auto_compress_codec", "libx264", str).lower()
        codec_index = self.auto_compress_codec_input.findData(codec)
        if codec_index < 0:
            codec_index = 0
        self.auto_compress_codec_input.setCurrentIndex(codec_index)
        preset = load_setting_value("auto_compress_preset", "medium", str).lower()
        preset_index = self.auto_compress_preset_input.findData(preset)
        if preset_index < 0:
            preset_index = 1
        self.auto_compress_preset_input.setCurrentIndex(preset_index)
        max_height = load_setting_value("auto_compress_max_height", DEFAULT_AUTO_COMPRESS_MAX_HEIGHT, int)
        height_index = self.auto_compress_resolution_input.findData(max_height)
        if height_index < 0:
            height_index = 0
        self.auto_compress_resolution_input.setCurrentIndex(height_index)
        self.auto_compress_video_bitrate_input.setValue(load_setting_value("auto_compress_video_bitrate_kbps", 2500, int))
        self.auto_compress_audio_bitrate_input.setValue(load_setting_value("auto_compress_audio_bitrate_kbps", 128, int))
        self.auto_compress_keep_original_input.setChecked(load_bool_setting("auto_compress_keep_original", True))
        self.timeshift_segment_hours_input.setValue(
            load_setting_value("timeshift_segment_hours", DEFAULT_TIMESHIFT_SEGMENT_HOURS, int)
        )
        self.timeshift_segment_minutes_input.setValue(
            load_setting_value("timeshift_segment_minutes", DEFAULT_TIMESHIFT_SEGMENT_MINUTES, int)
        )
        self.timeshift_segment_seconds_input.setValue(
            load_setting_value("timeshift_segment_seconds", DEFAULT_TIMESHIFT_SEGMENT_SECONDS, int)
        )
        
        self.tray_enabled_input.setChecked(load_bool_setting("tray_enabled", False))
        self.auto_start_input.setChecked(load_bool_setting("auto_start_enabled", False))
        
        self.auto_enabled_input.setChecked(load_bool_setting("auto_enabled", DEFAULT_AUTO_ENABLED))
        self.auto_startup_input.setChecked(load_bool_setting("auto_startup_recording", True))
        self.auto_notify_only_input.setChecked(load_bool_setting("auto_notify_only", False))
        self.auto_check_interval_input.setValue(load_setting_value("auto_check_interval", DEFAULT_AUTO_CHECK_INTERVAL_SEC, int))
        self._update_auto_record_option_state(bool(self.auto_enabled_input.isChecked()))

        self.log_panel_visible_input.setChecked(load_bool_setting("log_panel_visible", False))

        self.twitcasting_input.setPlainText(load_setting_value("twitcasting_entries", DEFAULT_TWITCASTING_ENTRIES, str))
        self.niconico_input.setPlainText(load_setting_value("niconico_entries", DEFAULT_NICONICO_ENTRIES, str))
        self.tiktok_input.setPlainText(load_setting_value("tiktok_entries", DEFAULT_TIKTOK_ENTRIES, str))
        self.fuwatch_input.setPlainText(load_setting_value("fuwatch_entries", DEFAULT_FUWATCH_ENTRIES, str))
        self.kick_input.setPlainText(load_setting_value("kick_entries", DEFAULT_KICK_ENTRIES, str))
        self.live17_input.setPlainText(load_setting_value("live17_entries", DEFAULT_LIVE17_ENTRIES, str))
        self.bigo_input.setPlainText(load_setting_value("bigo_entries", DEFAULT_BIGO_ENTRIES, str))
        self.radiko_input.setPlainText(load_setting_value("radiko_entries", DEFAULT_RADIKO_ENTRIES, str))
        self.openrectv_input.setPlainText(load_setting_value("openrectv_entries", DEFAULT_OPENRECTV_ENTRIES, str))
        self.bilibili_input.setPlainText(load_setting_value("bilibili_entries", DEFAULT_BILIBILI_ENTRIES, str))
        self.abema_input.setPlainText(load_setting_value("abema_entries", DEFAULT_ABEMA_ENTRIES, str))
        self.auto_notify_only_entries_input.setPlainText(load_setting_value("auto_notify_only_entries", "", str))
        
        self.youtube_api_key_input.setText(load_setting_value("youtube_api_key", "", str))
        self.youtube_channels_input.setPlainText(load_setting_value("youtube_channels", "", str))
        
        self.twitch_client_id_input.setText(load_setting_value("twitch_client_id", "", str))
        self.twitch_client_secret_input.setText(load_setting_value("twitch_client_secret", "", str))
        self.twitch_channels_input.setPlainText(load_setting_value("twitch_channels", "", str))
        quality = load_setting_value("recording_quality", DEFAULT_RECORDING_QUALITY, str)
        quality_index = self.recording_quality_input.findData(quality)
        if quality_index < 0:
            quality_index = self.recording_quality_input.findData(DEFAULT_RECORDING_QUALITY)
        self.recording_quality_input.setCurrentIndex(max(0, quality_index))
        self._update_auto_compress_option_state(bool(self.auto_compress_enabled_input.isChecked()))

    def _save_settings(self) -> None:
        save_setting_value("output_dir", self.output_dir_input.text().strip())
        save_setting_value("output_format", str(self.output_format_input.currentData()))
        save_setting_value("output_date_folder_enabled", int(self.output_date_folder_input.isChecked()))
        save_setting_value("output_filename_with_channel", int(self.output_filename_with_channel_input.isChecked()))
        save_setting_value("gdrive_enabled", int(self.gdrive_enabled_input.isChecked()))
        save_setting_value("gdrive_credentials_path", self.gdrive_credentials_input.text().strip())
        save_setting_value("gdrive_folder_id", self.gdrive_folder_input.text().strip())
        save_setting_value("retry_count", int(self.retry_count_input.value()))
        save_setting_value("retry_wait", int(self.retry_wait_input.value()))
        save_setting_value("http_timeout", int(self.http_timeout_input.value()))
        save_setting_value("stream_timeout", int(self.stream_timeout_input.value()))
        save_setting_value("preview_volume", float(self.preview_volume_input.value()))
        save_setting_value("keep_ts_file", int(self.keep_ts_input.isChecked()))
        save_setting_value("recording_max_size_mb", int(self.recording_max_size_input.value()))
        save_setting_value("recording_size_margin_mb", int(self.recording_size_margin_input.value()))
        save_setting_value("auto_compress_enabled", int(self.auto_compress_enabled_input.isChecked()))
        save_setting_value("auto_compress_codec", str(self.auto_compress_codec_input.currentData()))
        save_setting_value("auto_compress_preset", str(self.auto_compress_preset_input.currentData()))
        save_setting_value("auto_compress_max_height", int(self.auto_compress_resolution_input.currentData()))
        save_setting_value("auto_compress_video_bitrate_kbps", int(self.auto_compress_video_bitrate_input.value()))
        save_setting_value("auto_compress_audio_bitrate_kbps", int(self.auto_compress_audio_bitrate_input.value()))
        save_setting_value("auto_compress_keep_original", int(self.auto_compress_keep_original_input.isChecked()))
        save_setting_value("timeshift_segment_hours", int(self.timeshift_segment_hours_input.value()))
        save_setting_value("timeshift_segment_minutes", int(self.timeshift_segment_minutes_input.value()))
        save_setting_value("timeshift_segment_seconds", int(self.timeshift_segment_seconds_input.value()))
        
        save_setting_value("tray_enabled", int(self.tray_enabled_input.isChecked()))
        save_setting_value("auto_start_enabled", int(self.auto_start_input.isChecked()))
        
        save_setting_value("auto_enabled", int(self.auto_enabled_input.isChecked()))
        save_setting_value("auto_startup_recording", int(self.auto_startup_input.isChecked()))
        save_setting_value("auto_notify_only", int(self.auto_notify_only_input.isChecked()))
        save_setting_value("auto_check_interval", int(self.auto_check_interval_input.value()))
        
        save_setting_value("log_panel_visible", int(self.log_panel_visible_input.isChecked()))
        
        save_setting_value("twitcasting_entries", self.twitcasting_input.toPlainText().strip())
        save_setting_value("niconico_entries", self.niconico_input.toPlainText().strip())
        save_setting_value("tiktok_entries", self.tiktok_input.toPlainText().strip())
        save_setting_value("fuwatch_entries", self.fuwatch_input.toPlainText().strip())
        save_setting_value("kick_entries", self.kick_input.toPlainText().strip())
        save_setting_value("live17_entries", self.live17_input.toPlainText().strip())
        save_setting_value("bigo_entries", self.bigo_input.toPlainText().strip())
        save_setting_value("radiko_entries", self.radiko_input.toPlainText().strip())
        save_setting_value("openrectv_entries", self.openrectv_input.toPlainText().strip())
        save_setting_value("bilibili_entries", self.bilibili_input.toPlainText().strip())
        save_setting_value("abema_entries", self.abema_input.toPlainText().strip())
        save_setting_value("auto_notify_only_entries", self.auto_notify_only_entries_input.toPlainText().strip())
        
        save_setting_value("youtube_api_key", self.youtube_api_key_input.text().strip())
        save_setting_value("youtube_channels", self.youtube_channels_input.toPlainText().strip())
        
        save_setting_value("twitch_client_id", self.twitch_client_id_input.text().strip())
        save_setting_value("twitch_client_secret", self.twitch_client_secret_input.text().strip())
        save_setting_value("twitch_channels", self.twitch_channels_input.toPlainText().strip())
        save_setting_value("recording_quality", str(self.recording_quality_input.currentData()))
        parent = self.parent()
        if parent is not None:
            if hasattr(parent, "_load_settings_to_ui"):
                parent._load_settings_to_ui()
            if hasattr(parent, "_configure_auto_monitor"):
                parent._configure_auto_monitor()
            if hasattr(parent, "_apply_tray_setting"):
                parent._apply_tray_setting(True)
            if hasattr(parent, "_apply_startup_setting"):
                parent._apply_startup_setting(True)
            if hasattr(parent, "_apply_log_panel_visibility"):
                parent._apply_log_panel_visibility()
        QtWidgets.QMessageBox.information(self, "情報", "設定を保存しました。")

    def _browse_output_dir(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "出力フォルダを選択")
        if directory:
            self.output_dir_input.setText(directory)

    def _browse_gdrive_credentials(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Google Drive 認証情報(JSON)を選択",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.gdrive_credentials_input.setText(path)

    def _update_auto_record_option_state(self, enabled: bool) -> None:
        self.auto_startup_input.setEnabled(True)

    def _update_auto_compress_option_state(self, enabled: bool) -> None:
        widgets = [
            self.auto_compress_codec_input,
            self.auto_compress_preset_input,
            self.auto_compress_resolution_input,
            self.auto_compress_video_bitrate_input,
            self.auto_compress_audio_bitrate_input,
            self.auto_compress_keep_original_input,
        ]
        for widget in widgets:
            widget.setEnabled(True)

    def _confirm_gdrive_enable(self) -> bool:
        if getattr(self, "_suppress_gdrive_confirm", False):
            return True
        message = (
            "この設定は録画時間が長いほど、Google APIのクエリを大量に消費する可能性があります。\n"
            "それでもオンにしますか？"
        )
        result = QtWidgets.QMessageBox.question(
            self,
            "確認",
            message,
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        return result == QtWidgets.QMessageBox.StandardButton.Yes

    def _show_gdrive_login_notice(self) -> None:
        message = (
            "ONにすると、初回のみGoogleアカウントでのログインが求められます。\n"
            "これはGoogle Driveへアップロードするための認証であり、ログイン情報が漏れることはありません。"
        )
        QtWidgets.QMessageBox.information(self, "確認", message, QtWidgets.QMessageBox.StandardButton.Ok)

    def _handle_gdrive_enable_request(self) -> None:
        if not self._confirm_gdrive_enable():
            return
        self._show_gdrive_login_notice()
        blocker = QtCore.QSignalBlocker(self.gdrive_enabled_input)
        self.gdrive_enabled_input.setCheckedImmediate(True)
        del blocker

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if obj is getattr(self, "gdrive_enabled_input", None):
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                if not self.gdrive_enabled_input.isChecked():
                    self._handle_gdrive_enable_request()
                    return True
        return super().eventFilter(obj, event)
