"""Auto-generated parameter form: one widget per FieldSpec, no per-family code.

A label sits beside its field, right-aligned against it. A field whose text is long (a
file, or a text field whose default is longer than WIDE_TEXT_CHARS) takes a row of its
own under its label, the form's full width, and is at least wide enough to show that
default. A text field too narrow for its value shows the start of it (a file: the end,
its name) and the whole of it as a tooltip.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from heaton_life.playground.model import FieldSpec

DEBOUNCE_MS = 150
_ERROR_STYLE = "border: 1px solid #cc4444;"
WIDE_TEXT_CHARS = 16  # a text field whose default is longer takes the form's full width
FILE_FIELD_CHARS = 24  # a file field is at least this many average characters wide
LABEL_GAP = 4  # between a full-width control and the label above it


def scroll_bar_width(area: QAbstractScrollArea) -> int:
    """The width a vertical scroll bar takes from what the area shows: none where the
    platform draws it over the contents (macOS, unless set to always show them)."""
    bar, style = area.verticalScrollBar(), area.style()
    if bar is None or style is None:
        return 0
    if style.styleHint(QStyle.StyleHint.SH_ScrollBar_Transient, None, bar):
        return 0
    return bar.sizeHint().width()


def labeled_above(label: str, widget: QWidget) -> QWidget:
    """A control under its label, close enough to read as one: a full-width row."""
    block = QWidget()
    box = QVBoxLayout(block)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(LABEL_GAP)
    box.addWidget(QLabel(label))
    box.addWidget(widget)
    return block


class TextField(QLineEdit):
    """A line edit that shows the whole of a value too long for it as a tooltip."""

    def text_width(self, text: str) -> int:
        """The width this field needs to show ``text`` whole."""
        metrics = self.fontMetrics()
        chrome = self.minimumSizeHint().width() - metrics.maxWidth()  # frame and margins
        return metrics.horizontalAdvance(text) + chrome + 2  # and the cursor

    def event(self, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.ToolTip:
            self.setToolTip(self.text() if self.text_width(self.text()) > self.width() else "")
        return super().event(event)


class FormScrollArea(QScrollArea):
    """Scrolls a form down, never sideways: it is never narrower than the form needs. A
    floor (``set_floor``) keeps it one width across forms that need less."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._floor = 0

    def set_floor(self, width: int) -> None:
        self._floor = width
        self.fit_width()

    def fit_width(self) -> None:
        """Take the form's minimum width as this area's own (a scroll area doesn't ask
        for it, and would clip the form instead)."""
        form = self.widget()
        if form is None:
            return
        needed = max(self._floor, form.minimumSizeHint().width())
        self.setMinimumWidth(needed + scroll_bar_width(self) + 2 * self.frameWidth())

    def event(self, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.LayoutRequest:
            self.fit_width()  # the form's layout changed: a new form, or one just shown
        return super().event(event)


class ParamForm(QWidget):
    edited = pyqtSignal(dict)  # current values, debounced

    def __init__(self, specs: list[FieldSpec], values: dict[str, Any]) -> None:
        super().__init__()
        self._specs = specs
        self._widgets: dict[str, QWidget] = {}
        self._file_fields = {spec.name for spec in specs if spec.role == "file"}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit)

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # the panel's margins are the form's
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        for spec in specs:
            widget = self._make_widget(spec, values.get(spec.name, spec.default))
            self._widgets[spec.name] = widget
            if spec.role == "readonly":
                self._make_read_only(widget)
            field = widget
            if spec.role == "seed":
                dice = QPushButton("🎲")
                dice.setToolTip("Randomize seed")
                # Small, so the row is no taller than the others and the seed keeps its room.
                dice.setAttribute(Qt.WidgetAttribute.WA_MacSmallSize)
                dice.setFixedWidth(dice.sizeHint().height() * 3 // 2)
                dice.clicked.connect(self._randomize_seed(spec.name, spec.maximum))
                field = self._with_button(widget, dice)
            elif spec.role == "file":
                browse = QPushButton("Browse…")
                browse.setToolTip("Choose a file")
                browse.clicked.connect(self._browse_file(spec))
                field = self._with_button(widget, browse)
            if self._is_wide(spec):
                layout.addRow(labeled_above(spec.label, field))
            else:
                layout.addRow(spec.label, field)

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
            dspin.setDecimals(spec.decimals)
            dspin.setValue(float(value))
            dspin.valueChanged.connect(self._touch)
            return dspin
        edit = TextField(str(value))
        if spec.role == "file":
            # A path longer than the row shows its end, the file's name.
            edit.setMinimumWidth(edit.fontMetrics().averageCharWidth() * FILE_FIELD_CHARS)
        else:
            edit.setCursorPosition(0)
            if self._is_wide(spec):
                edit.setMinimumWidth(edit.text_width(str(spec.default)))
        edit.textEdited.connect(self._edited(spec))
        return edit

    @staticmethod
    def _is_wide(spec: FieldSpec) -> bool:
        """Whether the field takes a row of its own, under its label."""
        long_text = spec.kind == "str" and len(str(spec.default)) > WIDE_TEXT_CHARS
        return spec.role == "file" or long_text

    @staticmethod
    def _with_button(widget: QWidget, button: QPushButton) -> QWidget:
        """The field with its button to the right, as one row."""
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(widget, 1)
        box.addWidget(button)
        return row

    @staticmethod
    def _make_read_only(widget: QWidget) -> None:
        """A "readonly" field shows what the playground sets; it can be read and copied.
        Its text is dimmed, so it doesn't look like something to type into."""
        if isinstance(widget, QAbstractSpinBox):
            widget.setReadOnly(True)
            widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        elif isinstance(widget, QLineEdit):
            widget.setReadOnly(True)
        else:
            widget.setEnabled(False)
            return
        palette = widget.palette()
        dimmed = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        palette.setColor(QPalette.ColorRole.Text, dimmed)
        widget.setPalette(palette)

    def _randomize_seed(self, name: str, maximum: float) -> Callable[[], None]:
        def apply() -> None:
            widget = self._widgets[name]
            assert isinstance(widget, QSpinBox)
            widget.setValue(random.randrange(int(min(maximum, 2_147_483_647)) + 1))

        return apply

    def _browse_file(self, spec: FieldSpec) -> Callable[[], None]:
        edited = self._edited(spec)

        def browse() -> None:
            widget = self._widgets[spec.name]
            assert isinstance(widget, QLineEdit)
            current = Path(widget.text()).expanduser()
            start = str(current.parent) if current.is_absolute() else ""
            path, _ = QFileDialog.getOpenFileName(
                self, f"Choose {spec.label.lower()}", start, spec.file_filter
            )
            if path:
                widget.setText(path)
                edited()

        return browse

    def _edited(self, spec: FieldSpec) -> Callable[..., None]:
        """What an edit of the field by the user does: sets the fields it selects
        (FieldSpec.selects), then the debounced ``edited``."""
        if not spec.selects:
            return self._touch

        def edited(*_args: object) -> None:
            self.set_values(dict(spec.selects))
            self._touch()

        return edited

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
                    if name not in self._file_fields and not widget.hasFocus():
                        widget.setCursorPosition(0)  # too long for the field: its start
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
