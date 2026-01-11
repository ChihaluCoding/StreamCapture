# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from PyQt6 import QtGui
from settings_store import load_bool_setting, load_setting_value, save_setting_value

UI_COLOR_KEYS = ("primary", "main_bg", "side_bg", "text", "border")

_DEFAULT_UI_COLORS_LIGHT = {
    "primary": "#0ea5e9",
    "main_bg": "#f3f4f6",
    "side_bg": "#ffffff",
    "text": "#1e293b",
    "border": "#e2e8f0",
}

_DEFAULT_UI_COLORS_DARK = {
    "primary": "#38bdf8",
    "main_bg": "#0f172a",
    "side_bg": "#0b1220",
    "text": "#e2e8f0",
    "border": "#1f2a44",
}


def normalize_hex_color(value: str | None) -> str | None:
    if not value:
        return None
    color = QtGui.QColor(value)
    if not color.isValid():
        return None
    return color.name()


def adjust_color(hex_color: str, factor: float) -> str:
    color = QtGui.QColor(hex_color)
    if not color.isValid():
        return hex_color
    if factor >= 1.0:
        return color.lighter(int(factor * 100)).name()
    return color.darker(int(100 / max(0.01, factor))).name()


def blend_colors(color_a: str, color_b: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    c1 = QtGui.QColor(color_a)
    c2 = QtGui.QColor(color_b)
    if not c1.isValid():
        return color_b
    if not c2.isValid():
        return color_a
    r = c1.red() + (c2.red() - c1.red()) * ratio
    g = c1.green() + (c2.green() - c1.green()) * ratio
    b = c1.blue() + (c2.blue() - c1.blue()) * ratio
    return QtGui.QColor(int(r), int(g), int(b)).name()


def is_custom_ui_colors_enabled() -> bool:
    return load_bool_setting("ui_colors_enabled", False)


def get_default_ui_colors(is_dark: bool) -> dict[str, str]:
    return dict(_DEFAULT_UI_COLORS_DARK if is_dark else _DEFAULT_UI_COLORS_LIGHT)


def _parse_ui_colors(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    colors: dict[str, str] = {}
    for key in UI_COLOR_KEYS:
        value = data.get(key)
        if isinstance(value, str):
            normalized = normalize_hex_color(value)
            if normalized:
                colors[key] = normalized
    return colors


def get_ui_color_overrides(mode: str) -> dict[str, str]:
    raw = load_setting_value(f"ui_colors_{mode}", "{}", str)
    return _parse_ui_colors(raw)


def get_ui_color_edit_values(mode: str) -> dict[str, str]:
    defaults = get_default_ui_colors(mode == "dark")
    overrides = get_ui_color_overrides(mode)
    defaults.update(overrides)
    return defaults


def serialize_ui_colors(colors: dict[str, str]) -> str:
    return json.dumps(colors, ensure_ascii=True, sort_keys=True)


def load_ui_font_files() -> list[str]:
    raw = load_setting_value("ui_font_files", "[]", str)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str)]


def save_ui_font_files(files: list[str]) -> None:
    save_setting_value("ui_font_files", json.dumps(files, ensure_ascii=True))


def register_ui_font_files(files: list[str]) -> list[str]:
    families: list[str] = []
    for path in files:
        font_id = QtGui.QFontDatabase.addApplicationFont(path)
        if font_id == -1:
            continue
        families.extend(QtGui.QFontDatabase.applicationFontFamilies(font_id))
    return families


def get_ui_font_family() -> str:
    return load_setting_value("ui_font_family", "", str)


def _format_font_family(name: str) -> str:
    if name in ("sans-serif", "serif", "monospace", "system-ui"):
        return name
    if any(ch.isspace() for ch in name):
        return f"\"{name}\""
    return name


def get_ui_font_css_family(default_families: list[str] | None = None) -> str:
    families = []
    font = get_ui_font_family().strip()
    if font:
        families.append(font)
    if default_families:
        families.extend(default_families)
    return ", ".join(_format_font_family(name) for name in families)


def load_ui_color_presets(mode: str) -> dict[str, dict[str, str]]:
    raw = load_setting_value(f"ui_color_presets_{mode}", "{}", str)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    presets: dict[str, dict[str, str]] = {}
    for name, value in data.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        colors: dict[str, str] = {}
        for key in UI_COLOR_KEYS:
            color = value.get(key)
            if isinstance(color, str):
                normalized = normalize_hex_color(color)
                if normalized:
                    colors[key] = normalized
        if colors:
            presets[name] = colors
    return presets


def save_ui_color_presets(mode: str, presets: dict[str, dict[str, str]]) -> None:
    payload: dict[str, dict[str, str]] = {}
    for name, colors in presets.items():
        if not isinstance(name, str):
            continue
        clean: dict[str, str] = {}
        for key in UI_COLOR_KEYS:
            value = colors.get(key)
            if isinstance(value, str):
                normalized = normalize_hex_color(value)
                if normalized:
                    clean[key] = normalized
        if clean:
            payload[name] = clean
    save_setting_value(f"ui_color_presets_{mode}", json.dumps(payload, ensure_ascii=True, sort_keys=True))
