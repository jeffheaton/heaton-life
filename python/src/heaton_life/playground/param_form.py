"""Auto-generated parameter form: one widget per FieldSpec, no per-family code."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QToolButton,
    QWidget,
)

from heaton_life.playground.model import FieldSpec

DEBOUNCE_MS = 150
_ERROR_STYLE = "border: 1px solid #cc4444;"


class ParamForm(QWidget):
    edited = pyqtSignal(dict)  # current values, debounced

    def __init__(self, specs: list[FieldSpec], values: dict[str, Any]) -> None:
        super().__init__()
        self._specs = specs
        self._widgets: dict[str, QWidget] = {}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit)

        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for spec in specs:
            widget = self._make_widget(spec, values.get(spec.name, spec.default))
            self._widgets[spec.name] = widget
            if spec.role == "seed":
                row = QWidget()
                box = QHBoxLayout(row)
                box.setContentsMargins(0, 0, 0, 0)
                box.addWidget(widget, 1)
                dice = QToolButton()
                dice.setText("🎲")
                dice.setToolTip("Randomize seed")
                dice.clicked.connect(self._randomize_seed(spec.name, spec.maximum))
                box.addWidget(dice)
                layout.addRow(spec.label, row)
            else:
                layout.addRow(spec.label, widget)

    # -- construction -------------------------------------------------------------------

    def _make_widget(self, spec: FieldSpec, value: Any) -> QWidget:
        if spec.kind == "choice":
            combo = QComboBox()
            combo.addItems(list(spec.choices))
            combo.setCurrentText(str(value))
            combo.currentTextChanged.connect(self._touch)
            return combo
        if spec.kind == "bool":
            check = QCheckBox()
            check.setChecked(bool(value))
            check.toggled.connect(self._touch)
            return check
        if spec.kind == "int":
            spin = QSpinBox()
            spin.setRange(int(spec.minimum), int(min(spec.maximum, 2_147_483_647)))
            spin.setValue(int(value))
            spin.valueChanged.connect(self._touch)
            return spin
        if spec.kind == "float":
            dspin = QDoubleSpinBox()
            dspin.setRange(spec.minimum, spec.maximum)
            dspin.setSingleStep(spec.step)
            dspin.setDecimals(3)
            dspin.setValue(float(value))
            dspin.valueChanged.connect(self._touch)
            return dspin
        edit = QLineEdit(str(value))
        edit.textEdited.connect(self._touch)
        return edit

    def _randomize_seed(self, name: str, maximum: float) -> Callable[[], None]:
        def apply() -> None:
            widget = self._widgets[name]
            assert isinstance(widget, QSpinBox)
            widget.setValue(random.randrange(int(min(maximum, 2_147_483_647)) + 1))

        return apply

    # -- values -------------------------------------------------------------------------

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for spec in self._specs:
            widget = self._widgets[spec.name]
            if isinstance(widget, QComboBox):
                out[spec.name] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                out[spec.name] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                out[spec.name] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                out[spec.name] = round(widget.value(), 6)
            elif isinstance(widget, QLineEdit):
                out[spec.name] = widget.text()
        return out

    def set_values(self, values: dict[str, Any]) -> None:
        """Programmatic update (presets) without triggering edits."""
        for name, value in values.items():
            widget = self._widgets.get(name)
            if widget is None:
                continue
            widget.blockSignals(True)
            try:
                if isinstance(widget, QComboBox):
                    widget.setCurrentText(str(value))
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QSpinBox):
                    widget.setValue(int(value))
                elif isinstance(widget, QDoubleSpinBox):
                    widget.setValue(float(value))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value))
            finally:
                widget.blockSignals(False)

    # -- error highlighting ---------------------------------------------------------------

    def mark_error(self, name: str) -> None:
        widget = self._widgets.get(name)
        if widget is not None:
            widget.setStyleSheet(_ERROR_STYLE)

    def clear_errors(self) -> None:
        for widget in self._widgets.values():
            widget.setStyleSheet("")

    # -- internals ------------------------------------------------------------------------

    def _touch(self, *_args: object) -> None:
        self._debounce.start()

    def _emit(self) -> None:
        self.edited.emit(self.values())
