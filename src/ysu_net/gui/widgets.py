"""Custom widgets: animated toggle, status orb, segmented control, card and toast."""
from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)


class Toggle(QAbstractButton):
    """iOS / Fluent style switch with a sliding knob."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        self.colors = {"on": "#3563e9", "off": "#c5ccd8", "knob": "#ffffff"}

    def _animate(self, checked):
        self._anim.stop()
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked):  # noqa: N802 - Qt API
        # Programmatic updates jump without animation, avoiding a flicker on startup.
        blocked = self.blockSignals(True)
        super().setChecked(checked)
        self.blockSignals(blocked)
        self._anim.stop()
        self._offset = 1.0 if checked else 0.0
        self.update()

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def sizeHint(self):  # noqa: N802
        return QSize(46, 26)

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on, off = QColor(self.colors["on"]), QColor(self.colors["off"])
        t = self._offset
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        if not self.isEnabled():
            track.setAlphaF(0.45)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 13, 13)
        p.setBrush(QColor(self.colors["knob"]))
        x = 3 + t * (self.width() - 26)
        p.drawEllipse(QRectF(x, 3, 20, 20))


class StatusOrb(QWidget):
    """A colored dot with a soft pulsing halo while connected or busy."""

    def __init__(self, parent=None, size=64):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.color = QColor("#9aa2b4")
        self.pulsing = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, color, pulsing):
        self.color = QColor(color)
        self.pulsing = pulsing
        self.update()

    def _tick(self):
        if self.pulsing and self.isVisible():
            self._phase = (self._phase + 0.02) % 1.0
            self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = self.width() * 0.2
        halo = QColor(self.color)
        halo.setAlphaF(0.16)
        p.setBrush(halo)
        p.drawEllipse(c, r * 1.9, r * 1.9)
        if self.pulsing:
            ring = QColor(self.color)
            ring.setAlphaF(0.35 * (1 - self._phase))
            p.setBrush(ring)
            rr = r * (1.0 + 1.4 * self._phase)
            p.drawEllipse(c, rr, rr)
        p.setBrush(self.color)
        p.drawEllipse(c, r, r)


class Card(QFrame):
    def __init__(self, parent=None, spacing=12, margins=(20, 18, 20, 18)):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)


class Segmented(QFrame):
    """Mutually exclusive pill buttons; emits the chosen label."""

    chosen = Signal(str)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setObjectName("Segment")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for text in options:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.group.addButton(button)
            layout.addWidget(button)
            self.buttons[text] = button
            button.clicked.connect(lambda _=False, t=text: self.chosen.emit(t))

    def set_value(self, text):
        if text in self.buttons:
            self.buttons[text].setChecked(True)

    def value(self):
        button = self.group.checkedButton()
        return button.text() if button else None


class Toast(QFrame):
    """Transient message anchored to the bottom of its parent."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Toast")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.fade = QPropertyAnimation(self.effect, b"opacity", self)
        self.fade.setDuration(220)
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self._hide)
        self.hide()

    def show_message(self, text, ms=3200):
        self.label.setText(text)
        self.setMaximumWidth(min(520, self.parent().width() - 48))
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self.fade.stop()
        self.fade.setStartValue(self.effect.opacity() if self.isVisible() else 0.0)
        self.fade.setEndValue(1.0)
        self.fade.start()
        self.timer.start(ms)

    def _place(self):
        parent = self.parent()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 24)

    def _hide(self):
        self.fade.stop()
        self.fade.setStartValue(1.0)
        self.fade.setEndValue(0.0)
        self.fade.finished.connect(self._finish)
        self.fade.start()

    def _finish(self):
        self.fade.finished.disconnect(self._finish)
        if self.effect.opacity() < 0.05:
            self.hide()


class Confirm(QDialog):
    """Themed replacement for QMessageBox.question."""

    def __init__(self, parent, title, text, confirm, *, danger=False):
        super().__init__(parent)
        self.setObjectName("Dialog")
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 20)
        layout.setSpacing(10)
        layout.addWidget(label(title, "DialogTitle"))
        body = label(text, "Muted", wrap=True)
        layout.addWidget(body)
        layout.addSpacing(10)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        accept = QPushButton(confirm)
        accept.setObjectName("Danger" if danger else "Primary")
        accept.setCursor(Qt.PointingHandCursor)
        accept.clicked.connect(self.accept)
        accept.setDefault(True)
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        layout.addLayout(buttons)

    @classmethod
    def ask(cls, parent, title, text, confirm, *, danger=False):
        return cls(parent, title, text, confirm, danger=danger).exec() == QDialog.Accepted


def label(text="", name=None, *, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget
