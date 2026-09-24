"""Main window, pages and tray integration."""
import importlib.util
import sys
import time

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMenu, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from ysu_net.manager.config import SERVICES, Config, load_config, update_config
from . import icons, prefs as prefs_mod
from .engine import Engine, Status
from .theme import DARK, LIGHT, stylesheet
from .widgets import Card, Confirm, Segmented, StatusOrb, Toast, Toggle, label


def _version():
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("ysu-net-login")
    except PackageNotFoundError:
        return "dev"


class Bridge(QObject):
    """Delivers engine events from its worker thread to the GUI thread."""
    event = Signal(str, object)


def _row(*widgets, spacing=12, stretch_at=None):
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    for index, widget in enumerate(widgets):
        if widget is None:
            layout.addStretch(1)
        elif isinstance(widget, (QHBoxLayout, QVBoxLayout, QGridLayout)):
            layout.addLayout(widget, 1 if index == stretch_at else 0)
        else:
            layout.addWidget(widget, 1 if index == stretch_at else 0)
    return layout


def _setting(card, title, desc, control, *, first=False):
    """Windows 11 style row: title and description on the left, compact control on the right."""
    if not first:
        line = QFrame()
        line.setObjectName("Separator")
        card.body.addWidget(line)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(label(title))
    if isinstance(desc, QLabel):
        text.addWidget(desc)
    elif desc:
        text.addWidget(label(desc, "Muted", wrap=True))
    card.body.addLayout(_row(text, control, spacing=24, stretch_at=0))


def _page(title, subtitle):
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    inner = QWidget()
    body = QVBoxLayout(inner)
    body.setContentsMargins(32, 28, 32, 28)
    body.setSpacing(16)
    heading = QVBoxLayout()
    heading.setSpacing(2)
    heading.addWidget(label(title, "PageTitle"))
    heading.addWidget(label(subtitle, "PageSub"))
    head_row = QHBoxLayout()
    head_row.addLayout(heading, 1)
    body.addLayout(head_row)
    scroll.setWidget(inner)
    outer.addWidget(scroll)
    page.body = body
    page.head_row = head_row
    return page


class MainWindow(QMainWindow):
    def __init__(self, config_file, app_prefs, *, start_hidden=False):
        super().__init__()
        self.config_file = config_file
        self.prefs = app_prefs
        self.prefs_file = prefs_mod.prefs_path(config_file)
        self.tokens = LIGHT
        self.status = None
        self.auto_state = "off"
        self.auto_deadline = None
        self.auto_message = ""
        self.busy = False
        self.quitting = False
        self.tray_hint_shown = False
        self.account_loaded = False
        self.config = Config()

        self.setWindowTitle("YSU Net · 燕山大学校园网")
        self.setWindowIcon(icons.app_icon())
        self.resize(960, 640)
        self.setMinimumSize(820, 560)

        self.bridge = Bridge()
        self.bridge.event.connect(self._on_event)
        self.engine = Engine(config_file, self.bridge.event.emit)

        self._build()
        self._build_tray()
        self.toast = Toast(self.centralWidget())
        self.countdown = QTimer(self)
        self.countdown.timeout.connect(self._render_auto)
        self.countdown.start(1000)

        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self.apply_theme())
        self.apply_theme()
        self._load_config_into_ui()
        self.engine.start()
        self.engine.submit("status")
        if self.prefs.auto_reconnect:
            self.engine.submit("set_auto", True)
        if not start_hidden or not self.tray:
            self.show()

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(208)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 20, 14, 16)
        side.setSpacing(4)
        self.brand_icon = QLabel()
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_text.addWidget(label("YSU Net", "Brand"))
        brand_text.addWidget(label("燕山大学校园网", "BrandSub"))
        side.addLayout(_row(self.brand_icon, brand_text, None, spacing=10))
        side.addSpacing(22)

        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        self.stack = QStackedWidget()
        for index, (key, text) in enumerate((("home", "概览"), ("user", "账户"),
                                             ("settings", "设置"), ("logs", "日志"))):
            button = QPushButton("  " + text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIconSize(QSize(18, 18))
            button.icon_key = key
            button.clicked.connect(lambda _=False, i=index: self._navigate(i))
            self.nav_group.addButton(button)
            self.nav_buttons.append(button)
            side.addWidget(button)
        side.addStretch(1)
        self.side_pill = label("", "Pill")
        self.side_pill.setAlignment(Qt.AlignCenter)
        side.addWidget(self.side_pill)
        side.addSpacing(6)
        side.addWidget(label(f"v{_version()}", "BrandSub"))

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.progress = QProgressBar()
        self.progress.setObjectName("Busy")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        size_policy = self.progress.sizePolicy()
        size_policy.setRetainSizeWhenHidden(True)
        self.progress.setSizePolicy(size_policy)
        content_layout.addWidget(self.progress)
        content_layout.addWidget(self.stack, 1)

        layout.addWidget(sidebar)
        layout.addWidget(content, 1)

        self.stack.addWidget(self._build_overview())
        self.stack.addWidget(self._build_account())
        self.stack.addWidget(self._build_settings())
        self.stack.addWidget(self._build_logs())
        self.nav_buttons[0].setChecked(True)

        for i in range(4):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self._navigate(i))
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_current)

    def _build_overview(self):
        page = _page("概览", "连接状态、运营商与自动重连")
        self.refresh_button = QPushButton()
        self.refresh_button.setObjectName("Icon")
        self.refresh_button.setToolTip("刷新状态 (F5)")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(lambda: self.engine.submit("status"))
        page.head_row.addWidget(self.refresh_button, 0, Qt.AlignTop)

        hero = Card(margins=(24, 24, 24, 24))
        self.orb = StatusOrb(size=72)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.hero_title = label("正在查询…", "Hero")
        self.hero_sub = label("", "HeroSub", wrap=True)
        text.addStretch(1)
        text.addWidget(self.hero_title)
        text.addWidget(self.hero_sub)
        text.addStretch(1)
        self.connect_button = QPushButton("连接")
        self.connect_button.setCursor(Qt.PointingHandCursor)
        self.connect_button.setProperty("big", True)
        self.connect_button.clicked.connect(self._toggle_connection)
        hero.body.addLayout(_row(self.orb, text, self.connect_button, spacing=18, stretch_at=1))
        self.busy_label = label("", "Muted")
        self.busy_label.setVisible(False)
        hero.body.addWidget(self.busy_label)
        page.body.addWidget(hero)

        service = Card()
        service.body.addWidget(label("运营商", "CardTitle"))
        self.service_hint = label("", "Muted", wrap=True)
        service.body.addWidget(self.service_hint)
        self.segment = Segmented(SERVICES)
        self.segment.chosen.connect(self._choose_service)
        service.body.addWidget(self.segment)
        page.body.addWidget(service)

        auto = Card()
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(label("自动重连", "CardTitle"))
        self.auto_desc = label("", "Muted", wrap=True)
        text.addWidget(self.auto_desc)
        self.auto_toggle = Toggle()
        self.auto_toggle.clicked.connect(self._set_auto)
        auto.body.addLayout(_row(text, self.auto_toggle, stretch_at=0))
        page.body.addWidget(auto)
        page.body.addStretch(1)
        return page

    def _build_account(self):
        page = _page("账户", "账号信息、剩余流量与余额（以门户提供为准）")
        self.info_button = QPushButton("刷新")
        self.info_button.setCursor(Qt.PointingHandCursor)
        self.info_button.clicked.connect(lambda: self.engine.submit("info"))
        page.head_row.addWidget(self.info_button, 0, Qt.AlignTop)

        self.tiles_card = Card()
        self.tiles_card.body.addWidget(label("套餐与流量", "CardTitle"))
        self.tiles = QGridLayout()
        self.tiles.setSpacing(12)
        self.tiles_card.body.addLayout(self.tiles)
        self.tiles_note = label("流量和余额按门户原文展示，不推算额度或换算单位。门户未提供的项目不代表 0 或不限量。",
                                "Muted", wrap=True)
        self.tiles_card.body.addWidget(self.tiles_note)
        page.body.addWidget(self.tiles_card)

        self.fields_card = Card(spacing=10)
        self.fields_card.body.addWidget(label("在线信息", "CardTitle"))
        self.fields = QGridLayout()
        self.fields.setHorizontalSpacing(24)
        self.fields.setVerticalSpacing(10)
        self.fields_card.body.addLayout(self.fields)
        page.body.addWidget(self.fields_card)

        self.account_empty = Card()
        self.account_empty_label = label("在线后可查看账户与剩余流量。点击右上角“刷新”读取。", "Muted", wrap=True)
        self.account_empty.body.addWidget(self.account_empty_label)
        page.body.addWidget(self.account_empty)
        self.tiles_card.hide()
        self.fields_card.hide()
        page.body.addStretch(1)
        return page

    def _build_settings(self):
        page = _page("设置", "账号、连接参数与应用行为")

        account = Card()
        account.body.addWidget(label("校园网账号", "CardTitle"))
        account.body.addWidget(label("账号密码仅保存在本机配置文件中（仅当前用户可读），不会上传。", "Muted", wrap=True))
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("学号 / 工号")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.eye_action = self.pass_edit.addAction(icons.icon("eye", "#888"), QLineEdit.TrailingPosition)
        self.eye_action.setCheckable(True)
        self.eye_action.toggled.connect(lambda on: self.pass_edit.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.addWidget(label("账号"), 0, 0)
        grid.addWidget(self.user_edit, 0, 1)
        grid.addWidget(label("密码"), 1, 0)
        grid.addWidget(self.pass_edit, 1, 1)
        account.body.addLayout(grid)
        save_account = QPushButton("保存账号")
        save_account.setObjectName("Primary")
        save_account.setCursor(Qt.PointingHandCursor)
        save_account.clicked.connect(self._save_account)
        account.body.addLayout(_row(None, save_account))
        page.body.addWidget(account)

        connection = Card()
        connection.body.addWidget(label("连接参数", "CardTitle"))
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("API 认证（推荐）", "api")
        self.browser_note = label("", "Muted", wrap=True)
        if importlib.util.find_spec("playwright") is not None:
            from ysu_net.auth.system_browser import find_system_browser
            found = find_system_browser()
            self.backend_combo.addItem("浏览器认证（模拟网页登录）", "browser")
            self.browser_note.setText(
                f"浏览器认证将使用本机的 {found[0]}，在后台无窗口运行；仅在 API 认证异常时需要。" if found
                else "浏览器认证需要本机安装 Microsoft Edge 或 Google Chrome（Ubuntu 请使用 .deb 版本，Snap 版不可用）。")
        else:
            self.browser_note.setText("当前安装未包含浏览器认证组件。")
        self.backend_combo.setFixedWidth(250)
        self.tls_toggle = Toggle()
        self.spins = {}
        _setting(connection, "认证方式", self.browser_note, self.backend_combo, first=True)
        for key, text, tip in (
            ("check_interval", "在线检查间隔", "自动重连时，每隔多久确认一次在线状态"),
            ("retry_interval", "首次重试间隔", "登录或查询失败后首次等待时间，之后按倍数退避"),
            ("max_retry_interval", "最长重试间隔", "失败后退避等待的上限"),
            ("operation_timeout", "单次操作超时", "一次登录、下线或查询的最长等待时间"),
        ):
            spin = QSpinBox()
            spin.setRange(1, 86400)
            spin.setSuffix(" 秒")
            spin.setAlignment(Qt.AlignRight)
            spin.setButtonSymbols(QSpinBox.NoButtons)
            spin.setFixedWidth(120)
            self.spins[key] = spin
            _setting(connection, text, tip, spin)
        _setting(connection, "HTTPS 证书校验", "校验门户证书，防止账号密码被中间人截获；除非确有必要，请保持开启",
                 self.tls_toggle)
        save_conn = QPushButton("保存参数")
        save_conn.setCursor(Qt.PointingHandCursor)
        save_conn.clicked.connect(self._save_connection)
        connection.body.addSpacing(4)
        connection.body.addLayout(_row(label("修改后在下一轮检查时生效。", "Muted"), None, save_conn))
        page.body.addWidget(connection)

        app = Card()
        app.body.addWidget(label("应用", "CardTitle"))
        self.autostart_toggle = Toggle()
        self.autostart_toggle.clicked.connect(self._set_autostart)
        self.tray_toggle = Toggle()
        self.tray_toggle.clicked.connect(self._set_close_to_tray)
        self.theme_combo = QComboBox()
        for value, text in (("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")):
            self.theme_combo.addItem(text, value)
        self.theme_combo.currentIndexChanged.connect(self._set_theme)
        self.theme_combo.setFixedWidth(160)
        _setting(app, "登录系统后自动启动", "启动后最小化到托盘；配合“自动重连”即可开机自动联网",
                 self.autostart_toggle, first=True)
        _setting(app, "关闭窗口时驻留托盘", "关闭主窗口后继续在后台保持自动重连", self.tray_toggle)
        _setting(app, "外观", "浅色、深色或跟随系统设置", self.theme_combo)
        page.body.addWidget(app)

        about = Card(spacing=6)
        about.body.addWidget(label("关于", "CardTitle"))
        path = label(f"配置文件：{self.config_file}", "Muted", wrap=True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        about.body.addWidget(path)
        about.body.addWidget(label("命令行版本与本程序共用配置；同一配置同时只能由一个后台重连进程管理。", "Muted", wrap=True))
        page.body.addWidget(about)
        page.body.addStretch(1)
        return page

    def _build_logs(self):
        page = _page("日志", "本次运行期间的操作与自动重连记录（不包含密码或服务器原始响应）")
        self.copy_button = QPushButton("复制")
        self.copy_button.setCursor(Qt.PointingHandCursor)
        self.copy_button.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.log_view.toPlainText()))
        self.clear_button = QPushButton("清空")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(lambda: self.log_view.clear())
        page.head_row.addWidget(self.copy_button, 0, Qt.AlignTop)
        page.head_row.addWidget(self.clear_button, 0, Qt.AlignTop)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setMinimumHeight(380)
        page.body.addWidget(self.log_view, 1)
        return page

    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(icons.app_icon("#9aa2b4"), self)
        self.tray.setToolTip("YSU Net")
        menu = QMenu()
        self.tray_state = QAction("状态：查询中", menu)
        self.tray_state.setEnabled(False)
        menu.addAction(self.tray_state)
        menu.addSeparator()
        menu.addAction("打开主窗口", self.show_window)
        self.tray_connect = menu.addAction("连接", self._toggle_connection)
        self.tray_auto = menu.addAction("自动重连")
        self.tray_auto.setCheckable(True)
        self.tray_auto.triggered.connect(self._set_auto)
        menu.addSeparator()
        menu.addAction("退出", self.quit)
        self.tray.setContextMenu(menu)
        self.tray_menu = menu
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    # ------------------------------------------------------------------ theme
    def apply_theme(self):
        choice = self.prefs.theme
        if choice == "system":
            hints = QGuiApplication.styleHints()
            dark = hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark
        else:
            dark = choice == "dark"
        self.tokens = t = DARK if dark else LIGHT
        QApplication.instance().setStyleSheet(stylesheet(t, icons.svg_file("chevron", t["muted"])))
        self._dark_title_bar(dark)
        self.brand_icon.setPixmap(icons.render(icons.app_svg(), 34))
        for button in self.nav_buttons:
            button.setIcon(icons.icon(button.icon_key, t["muted"] if not button.isChecked() else t["accent"]))
        self.refresh_button.setIcon(icons.icon("refresh", t["muted"]))
        self.eye_action.setIcon(icons.icon("eye", t["muted"]))
        for toggle in (self.auto_toggle, self.tls_toggle, self.autostart_toggle, self.tray_toggle):
            toggle.colors = {"on": t["accent"], "off": t["idle"] if dark else "#c5ccd8",
                             "knob": "#ffffff"}
            toggle.update()
        self._render_status()
        self._render_auto()

    def _dark_title_bar(self, dark):
        if sys.platform != "win32":
            return
        try:  # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 20H1+ / 11); older systems ignore it.
            import ctypes
            value = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(value), 4)
        except (AttributeError, OSError):
            pass

    # ------------------------------------------------------------------ events
    def _on_event(self, kind, payload):
        if kind == "busy":
            self.busy = True
            self.progress.setVisible(True)
            self.busy_label.setText(payload)
            self.busy_label.setVisible(True)
            self._update_controls()
        elif kind == "idle":
            self.busy = False
            self.progress.setVisible(False)
            self.busy_label.setVisible(False)
            self._update_controls()
        elif kind == "status":
            previous = self.status
            self.status = payload
            self._render_status()
            if previous and previous.online is not None and payload.online is not None \
                    and previous.online != payload.online:
                self.log("网络" + ("已连接" if payload.online else "已断开"))
                if payload.online and self.stack.currentIndex() == 1:
                    self.engine.submit("info")
        elif kind == "auto":
            self.auto_state = payload["state"]
            delay = payload.get("delay")
            self.auto_deadline = time.monotonic() + delay if delay else None
            if payload["message"] != self.auto_message:
                self.log("自动重连：" + payload["message"])
            self.auto_message = payload["message"]
            self._render_auto()
            if self.auto_state == "external":
                self.notify(payload["message"])
        elif kind == "result":
            self.log(payload["message"], ok=payload["ok"])
            self.notify(("✓ " if payload["ok"] else "✕ ") + payload["message"])
        elif kind == "error":
            self.log(payload, ok=False)
            self.notify("✕ " + payload)
        elif kind == "info":
            self._render_account(payload)
        elif kind == "config":
            self._load_config_into_ui()

    def log(self, text, ok=None):
        mark = {True: "✓", False: "✕", None: "·"}[ok]
        self.log_view.appendPlainText(f"{time.strftime('%H:%M:%S')}  {mark} {text}")

    def notify(self, text):
        if self.isVisible() and not self.isMinimized():
            self.toast.show_message(text)
        elif self.tray:
            self.tray.showMessage("YSU Net", text.lstrip("✓✕ "), icons.app_icon(), 4000)

    # ------------------------------------------------------------------ rendering
    def _render_status(self):
        t = self.tokens
        s = self.status
        if s is None:
            color, title, sub, pill = t["idle"], "正在查询…", "首次打开会自动查询一次连接状态", ("查询中", "idle")
        elif s.online:
            parts = [s.service or "服务未知", s.ip, s.user]
            color, title, pill = t["success"], "已连接", ("在线", "success")
            sub = " · ".join(p for p in parts if p)
        elif s.online is False:
            color, title, sub, pill = t["idle"], "未连接", "点击“连接”登录校园网，或开启自动重连", ("离线", "idle")
        else:
            color, title, sub, pill = t["warning"], "状态未知", s.message or "查询失败", ("未知", "warning")
        self.orb.set_state(color, bool(s and s.online) or self.busy)
        self.hero_title.setText(title)
        self.hero_sub.setText(sub)
        name, tone = pill
        self.side_pill.setText("●  " + name)
        self.side_pill.setStyleSheet(f"color: {t[tone]}; background: {t[tone + '_soft']};")
        if self.tray:
            self.tray.setIcon(icons.app_icon({"success": "#22c55e", "warning": "#f59e0b"}.get(tone, "#9aa2b4")))
            self.tray.setToolTip(f"YSU Net · {title}" + (f" · {s.service}" if s and s.online and s.service else ""))
            self.tray_state.setText(f"状态：{title}")
        self._update_controls()

    def _update_controls(self):
        online = bool(self.status and self.status.online)
        self.connect_button.setText("断开连接" if online else "连接")
        self.connect_button.setObjectName("Danger" if online else "Primary")
        self.connect_button.style().unpolish(self.connect_button)
        self.connect_button.style().polish(self.connect_button)
        for widget in (self.connect_button, self.refresh_button, self.info_button, self.segment):
            widget.setEnabled(not self.busy)
        if self.tray:
            self.tray_connect.setText("断开连接" if online else "连接")
            self.tray_connect.setEnabled(not self.busy)
        self.orb.set_state(self.orb.color, online or self.busy)
        if online and self.status.service:
            self.service_hint.setText(f"当前在线：{self.status.service}。选择其他运营商会立即切换，并独立确认结果；失败时尝试恢复原连接。")
        else:
            self.service_hint.setText("选择下次登录使用的服务。在线时选择其他运营商会立即切换。")

    def _render_auto(self):
        t = self.tokens
        state = self.auto_state
        self.auto_toggle.setChecked(state == "on")
        self.auto_toggle.setEnabled(state != "external")
        if self.tray:
            self.tray_auto.setChecked(state == "on")
            self.tray_auto.setEnabled(state != "external")
        if state == "on":
            text = self.auto_message or "已开启"
            if self.auto_deadline and not self.busy:
                remaining = max(0, int(self.auto_deadline - time.monotonic()))
                text += f" · {remaining} 秒后再次检查"
            self.auto_desc.setStyleSheet(f"color: {t['muted']};")
        elif state == "external":
            text = self.auto_message
            self.auto_desc.setStyleSheet(f"color: {t['warning']};")
        else:
            text = "断线时自动登录，并在失败后按间隔退避重试。账号密码错误时会暂停，避免触发风控。"
            self.auto_desc.setStyleSheet(f"color: {t['muted']};")
        self.auto_desc.setText(text)

    def _render_account(self, summary):
        for grid in (self.tiles, self.fields):
            while grid.count():
                item = grid.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        if not summary or not summary["online"]:
            self.tiles_card.hide()
            self.fields_card.hide()
            self.account_empty.show()
            self.account_empty_label.setText("当前未在线，无法读取账户信息。请先连接校园网。"
                                             if summary else "暂未取得有效账户信息，请稍后刷新。")
            return
        self.account_loaded = True
        self.account_empty.hide()
        items = list(summary["items"])
        titles = " ".join(title for title, _ in items)
        if "剩余流量" not in titles:
            items.append(("剩余流量", "门户未提供"))
        if "余额" not in titles:
            items.append(("套餐与余额", "门户未提供"))
        columns = 3 if len(items) > 4 else 2
        for index, (title, content) in enumerate(items):
            tile = QFrame()
            tile.setObjectName("Tile")
            box = QVBoxLayout(tile)
            box.setContentsMargins(16, 14, 16, 14)
            box.setSpacing(4)
            box.addWidget(label(title, "StatLabel"))
            value = label(content, "StatValue" if len(content) <= 18 else None, wrap=True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.addWidget(value)
            tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.tiles.addWidget(tile, index // columns, index % columns)
        for row, (title, content) in enumerate(summary["fields"]):
            name = label(title, "Muted")
            value = label(content)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.fields.addWidget(name, row, 0)
            self.fields.addWidget(value, row, 1)
        self.fields.setColumnStretch(1, 1)
        self.tiles_card.show()
        self.fields_card.show()

    def _load_config_into_ui(self):
        try:
            config = load_config(self.config_file, environ={})
        except (ValueError, OSError) as exc:
            self.log(str(exc), ok=False)
            return
        self.config = config
        self.segment.set_value(config.service)
        self.user_edit.setText(config.username)
        self.pass_edit.clear()
        self.pass_edit.setPlaceholderText("已保存（留空则不修改）" if config.password else "请输入密码")
        index = self.backend_combo.findData(config.backend)
        self.backend_combo.setCurrentIndex(max(0, index))
        for key, spin in self.spins.items():
            spin.setValue(getattr(config, key))
        self.tls_toggle.setChecked(config.verify_tls)
        try:
            self.autostart_toggle.setChecked(prefs_mod.autostart_enabled())
        except OSError:
            self.autostart_toggle.setChecked(False)
        self.tray_toggle.setChecked(self.prefs.close_to_tray)
        self.tray_toggle.setEnabled(self.tray is not None)
        blocked = self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self.prefs.theme)))
        self.theme_combo.blockSignals(blocked)

    # ------------------------------------------------------------------ actions
    def _navigate(self, index):
        if index != self.stack.currentIndex():
            self._fade_in(self.stack.widget(index))
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        for button in self.nav_buttons:
            button.setIcon(icons.icon(button.icon_key, self.tokens["accent"] if button.isChecked() else self.tokens["muted"]))
        if index == 1 and not self.account_loaded and self.status and self.status.online:
            self.engine.submit("info")

    def _fade_in(self, widget):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", widget)
        animation.setDuration(180)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        # Drop the effect afterwards: it would otherwise re-render the page off-screen.
        animation.finished.connect(lambda: widget.setGraphicsEffect(None))
        animation.start(QPropertyAnimation.DeleteWhenStopped)

    def _refresh_current(self):
        self.engine.submit("info" if self.stack.currentIndex() == 1 else "status")

    def _toggle_connection(self):
        if self.busy:
            return
        if self.status and self.status.online:
            if self.auto_state == "on":
                if not Confirm.ask(self, "断开连接", "断开连接会同时关闭自动重连。确定下线吗？",
                                   "断开连接", danger=True):
                    return
            self.engine.submit("logout")
        else:
            self.engine.submit("login")

    def _choose_service(self, target):
        s = self.status
        if s and s.online and s.service != target:
            if not Confirm.ask(
                    self, f"切换到{target}",
                    f"将从“{s.service or '当前服务'}”切换到“{target}”。切换会先下线再登录，期间网络短暂中断；"
                    "若新服务登录失败，会尝试恢复原连接。", "立即切换"):
                self.segment.set_value(self.config.service)
                return
            self.engine.submit("switch", target)
        elif target != self.config.service:
            self.engine.submit("set_service", target)

    def _set_auto(self, enabled):
        self.prefs.auto_reconnect = bool(enabled)
        self._save_prefs()
        self.engine.submit("set_auto", bool(enabled))

    def _save_account(self):
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()
        if not username:
            self.notify("✕ 账号不能为空")
            return
        if not password and not self.config.password:
            self.notify("✕ 请输入密码")
            return
        changes = {"username": username}
        if password:
            changes["password"] = password
        try:
            update_config(self.config_file, **changes)
        except (ValueError, OSError) as exc:
            self.notify(f"✕ {exc}")
            return
        self._load_config_into_ui()
        self.log("账号已保存", ok=True)
        self.notify("✓ 账号已保存")

    def _save_connection(self):
        changes = {key: spin.value() for key, spin in self.spins.items()}
        changes["backend"] = self.backend_combo.currentData()
        changes["verify_tls"] = self.tls_toggle.isChecked()
        if not changes["verify_tls"] and self.config.verify_tls:
            if not Confirm.ask(self, "关闭证书校验",
                               "关闭 HTTPS 证书校验会让账号密码暴露于中间人攻击。仅在确认网络可信时使用。",
                               "仍然关闭", danger=True):
                self.tls_toggle.setChecked(True)
                return
        try:
            update_config(self.config_file, **changes)
        except (ValueError, OSError) as exc:
            self.notify(f"✕ {exc}")
            self._load_config_into_ui()
            return
        self._load_config_into_ui()
        self.log("连接参数已保存", ok=True)
        self.notify("✓ 参数已保存")

    def _set_autostart(self, enabled):
        try:
            prefs_mod.set_autostart(enabled)
        except OSError as exc:
            self.notify(f"✕ 自启设置失败：{exc}")
        self.autostart_toggle.setChecked(prefs_mod.autostart_enabled())
        if enabled and not self.prefs.auto_reconnect:
            self.notify("✓ 已开启自启。建议同时开启“自动重连”，登录系统后即可自动联网")

    def _set_close_to_tray(self, enabled):
        self.prefs.close_to_tray = bool(enabled)
        self._save_prefs()

    def _set_theme(self, _index):
        self.prefs.theme = self.theme_combo.currentData()
        self._save_prefs()
        self.apply_theme()

    def _save_prefs(self):
        try:
            prefs_mod.save_prefs(self.prefs_file, self.prefs)
        except OSError as exc:
            self.log(f"界面设置保存失败：{exc}", ok=False)

    # ------------------------------------------------------------------ window
    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):  # noqa: N802
        if not self.quitting and self.tray and self.prefs.close_to_tray:
            event.ignore()
            self.hide()
            if not self.tray_hint_shown:
                self.tray_hint_shown = True
                self.tray.showMessage("YSU Net 仍在运行",
                                      "已最小化到托盘；右键托盘图标可退出。", icons.app_icon(), 3000)
            return
        self.quit()
        event.accept()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast._place()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.hide()
        if self.tray:
            self.tray.hide()
        self.engine.shutdown()
        QApplication.instance().quit()
