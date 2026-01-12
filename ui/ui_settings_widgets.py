# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


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
        if self._checked != checked:
            return
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


class ColorPickerWidget(QtWidgets.QWidget):
    colorChanged = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = ""
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.line_edit = QtWidgets.QLineEdit()
        self.line_edit.setPlaceholderText("#RRGGBB")
        self.line_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.line_edit, 1)

        self.button = QtWidgets.QPushButton()
        self.button.setFixedSize(40, 30)
        self.button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._choose_color)
        layout.addWidget(self.button, 0)

        self._update_button()

    def color(self) -> str:
        return self._color

    def setColor(self, value: str) -> None:
        self.line_edit.setText(value)

    def _choose_color(self) -> None:
        current = QtGui.QColor(self._color) if self._color else QtGui.QColor("#ffffff")
        color = QtWidgets.QColorDialog.getColor(current, self, "色を選択")
        if color.isValid():
            self.setColor(color.name())

    def _on_text_changed(self, text: str) -> None:
        color = QtGui.QColor(text.strip())
        if color.isValid():
            normalized = color.name()
            if normalized != self._color:
                self._color = normalized
                self._update_button()
                self.colorChanged.emit(self._color)
        else:
            if self._color:
                self._color = ""
                self._update_button()

    def _update_button(self) -> None:
        if self._color:
            self.button.setStyleSheet(f"background-color: {self._color}; border: 1px solid #94a3b8;")
        else:
            self.button.setStyleSheet("")
