# -*- coding: utf-8 -*-
from __future__ import annotations

from string import Template
from PyQt6 import QtGui, QtWidgets
from theme_utils import (
    adjust_color,
    blend_colors,
    get_ui_color_overrides,
    get_ui_font_css_family,
    is_custom_ui_colors_enabled,
)


class SettingsStylesMixin:
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

        c_section_divider = blend_colors(c_base_text, c_dialog_bg, 0.75)

        c_editor_bg = c_card_bg
        c_editor_border = c_card_border
        c_editor_text = c_base_text
        c_editor_input_bg = c_input_bg
        c_ui_font = get_ui_font_css_family(["Yu Gothic UI", "Segoe UI", "sans-serif"])

        def tone(color: str, light_factor: float, dark_factor: float) -> str:
            return adjust_color(color, dark_factor if is_dark else light_factor)

        if is_custom_ui_colors_enabled():
            overrides = get_ui_color_overrides("dark" if is_dark else "light")
            if overrides:
                c_dialog_bg = overrides.get("main_bg", c_dialog_bg)
                c_sidebar_bg = overrides.get("side_bg", c_sidebar_bg)
                c_base_text = overrides.get("text", c_base_text)
                c_primary_bg = overrides.get("primary", c_primary_bg)
                c_primary_border = tone(c_primary_bg, 0.9, 1.1)
                c_primary_hover_bg = tone(c_primary_bg, 0.92, 1.08)
                c_primary_hover_border = tone(c_primary_bg, 0.88, 1.12)
                c_primary_pressed = tone(c_primary_bg, 0.84, 1.16)

                c_sidebar_border = overrides.get("border", c_sidebar_border)
                c_card_border = c_sidebar_border
                c_footer_border = c_sidebar_border
                c_input_border = c_sidebar_border
                c_combo_border = c_sidebar_border
                c_button_border = c_sidebar_border
                c_spin_btn_border = c_sidebar_border

                c_sidebar_item = blend_colors(c_base_text, c_sidebar_bg, 0.5)
                c_sidebar_selected_bg = tone(c_sidebar_bg, 0.97, 1.12)
                c_sidebar_selected_text = c_primary_bg
                c_sidebar_hover_bg = tone(c_sidebar_bg, 0.99, 1.08)
                c_sidebar_hover_text = c_base_text
                c_page_title = c_base_text
                c_desc = blend_colors(c_base_text, c_dialog_bg, 0.6)
                c_card_bg = tone(c_dialog_bg, 1.0, 1.06)
                c_footer_bg = tone(c_dialog_bg, 1.0, 1.04)
                c_input_bg = tone(c_dialog_bg, 0.99, 1.06)
                c_input_text = c_base_text
                c_input_focus_bg = tone(c_dialog_bg, 1.0, 1.12)
                c_focus_border = c_primary_bg
                c_spin_input_bg = c_input_bg
                c_spin_btn_bg = tone(c_dialog_bg, 0.98, 1.04)
                c_spin_btn_text = blend_colors(c_base_text, c_dialog_bg, 0.35)
                c_spin_btn_hover_bg = tone(c_spin_btn_bg, 0.96, 1.1)
                c_spin_btn_hover_text = c_primary_bg
                c_spin_btn_pressed = tone(c_spin_btn_bg, 0.92, 1.16)
                c_combo_bg = c_input_bg
                c_combo_text = c_base_text
                c_combo_focus_bg = c_input_focus_bg
                c_combo_arrow = blend_colors(c_base_text, c_dialog_bg, 0.5)
                c_button_bg = tone(c_dialog_bg, 1.0, 1.06)
                c_button_text = c_base_text
                c_button_hover_bg = tone(c_button_bg, 0.97, 1.1)
                c_button_hover_border = tone(c_button_border, 0.9, 1.1)
                c_button_hover_text = c_base_text
                self._label_color = c_base_text
                self._muted_label_color = blend_colors(c_base_text, c_dialog_bg, 0.5)
                self._section_label_color = c_base_text

        colors = {k: v for k, v in locals().items() if k.startswith("c_")}

        self.setStyleSheet(Template("""
            /* ベース設定 */
            QDialog {
                background-color: $c_dialog_bg;
                font-family: $c_ui_font;
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
                font-size: 26px;
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
                border: none;
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
            QFrame#SectionDivider {
                background-color: $c_section_divider;
                min-height: 2px;
                max-height: 2px;
                margin-bottom: 12px;
            }

            /* --- カラー設定タブ (常に見やすい配色に固定) --- */
            QTabWidget#UiColorTabs::pane {
                border: 1px solid $c_editor_border;
                background-color: $c_editor_bg;
                border-radius: 6px;
            }
            QTabWidget#UiColorTabs QWidget {
                background-color: $c_editor_bg;
            }
            QTabWidget#UiColorTabs QLabel {
                color: $c_editor_text;
            }
            QTabWidget#UiColorTabs QLineEdit {
                background-color: $c_editor_input_bg;
                color: $c_editor_text;
                border: 1px solid $c_editor_border;
            }
            QTabWidget#UiColorTabs QTabBar::tab {
                background-color: $c_editor_bg;
                color: $c_editor_text;
                border: 1px solid $c_editor_border;
                border-bottom: none;
                padding: 8px 16px;
                min-width: 80px;
            }
            QTabWidget#UiColorTabs QTabBar::tab:selected {
                background-color: $c_dialog_bg;
                color: $c_base_text;
            }
            QPushButton#UiColorResetButton {
                background-color: #ffffff;
                border: 1px solid $c_editor_border;
                color: $c_editor_text;
            }
            QPushButton#UiColorResetButton:hover {
                background-color: #f8fafc;
            }
        """).substitute(colors))
