"""Color tokens and the application style sheet for light and dark appearance."""
import sys

LIGHT = {
    "bg": "#f3f5f9", "sidebar": "#eaeef5", "surface": "#ffffff", "surface2": "#f1f4f9",
    "hover": "#e4e9f2", "border": "#e1e6ef", "text": "#161b26", "muted": "#687085",
    "accent": "#3563e9", "accent_hover": "#2b55d4", "accent_soft": "#e3ebff", "on_accent": "#ffffff",
    "success": "#15a150", "success_soft": "#ddf5e7", "warning": "#c77c02", "warning_soft": "#fdf0d7",
    "danger": "#d93636", "danger_soft": "#fde4e4", "idle": "#9aa2b4", "idle_soft": "#eceff4",
}
DARK = {
    "bg": "#0f1218", "sidebar": "#141821", "surface": "#1a1f2a", "surface2": "#212734",
    "hover": "#262d3b", "border": "#2a3140", "text": "#e9edf5", "muted": "#98a1b4",
    "accent": "#6a8dff", "accent_hover": "#8aa6ff", "accent_soft": "#1f2a4a", "on_accent": "#0d1220",
    "success": "#34d17a", "success_soft": "#16301f", "warning": "#f3b23c", "warning_soft": "#35290f",
    "danger": "#ff6b6b", "danger_soft": "#3a1a1d", "idle": "#6e778a", "idle_soft": "#232936",
}


def font_families():
    if sys.platform == "win32":
        return ["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"]
    if sys.platform == "darwin":
        return ["PingFang SC", "Helvetica Neue"]
    return ["Ubuntu", "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "Cantarell", "sans-serif"]


def stylesheet(t, chevron=""):
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t['text']}; font-size: 10pt; }}
QMainWindow, #Root {{ background: {t['bg']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 6px 8px; border-radius: 6px; }}

#Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['border']}; }}
#Brand {{ font-size: 13pt; font-weight: 700; }}
#BrandSub {{ color: {t['muted']}; font-size: 8.5pt; }}
#NavButton {{
    text-align: left; padding: 9px 14px; border: none; border-radius: 9px;
    background: transparent; color: {t['muted']}; font-weight: 500;
}}
#NavButton:hover {{ background: {t['hover']}; color: {t['text']}; }}
#NavButton:checked {{ background: {t['surface']}; color: {t['accent']}; font-weight: 700; }}

#PageTitle {{ font-size: 18pt; font-weight: 700; }}
#PageSub {{ color: {t['muted']}; }}
#Card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
#CardTitle {{ font-size: 11pt; font-weight: 700; }}
#Muted, QLabel[muted="true"] {{ color: {t['muted']}; }}
#Hero {{ font-size: 20pt; font-weight: 700; }}
#HeroSub {{ color: {t['muted']}; font-size: 10.5pt; }}
#StatValue {{ font-size: 15pt; font-weight: 700; }}
#StatLabel {{ color: {t['muted']}; font-size: 9pt; }}
#Tile {{ background: {t['surface2']}; border-radius: 12px; }}
#Separator {{ background: {t['border']}; max-height: 1px; min-height: 1px; }}

QPushButton {{
    background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 9px;
    padding: 7px 16px; font-weight: 500;
}}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:disabled {{ color: {t['idle']}; }}
QPushButton#Primary {{ background: {t['accent']}; color: {t['on_accent']}; border: none; font-weight: 700; }}
QPushButton#Primary:hover {{ background: {t['accent_hover']}; }}
QPushButton#Primary:disabled {{ background: {t['idle_soft']}; color: {t['idle']}; }}
QPushButton#Danger {{ background: {t['danger_soft']}; color: {t['danger']}; border: none; font-weight: 700; }}
QPushButton#Danger:hover {{ background: {t['danger']}; color: #ffffff; }}
QPushButton[big="true"] {{ padding: 11px 26px; font-size: 11pt; border-radius: 11px; min-width: 120px; }}
QPushButton#Icon {{ padding: 6px; border-radius: 8px; background: transparent; border: none; }}
QPushButton#Icon:hover {{ background: {t['hover']}; }}

#Segment {{ background: {t['surface2']}; border-radius: 10px; }}
#Segment QPushButton {{ background: transparent; border: none; border-radius: 8px; padding: 8px 12px; color: {t['muted']}; }}
#Segment QPushButton:hover {{ color: {t['text']}; }}
#Segment QPushButton:checked {{ background: {t['surface']}; color: {t['text']}; font-weight: 700; border: 1px solid {t['border']}; }}
#Segment QPushButton:disabled {{ color: {t['idle']}; }}

QLineEdit, QSpinBox, QComboBox {{
    background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 8px;
    padding: 7px 10px; selection-background-color: {t['accent']}; selection-color: {t['on_accent']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; background: {t['surface']}; }}
QComboBox {{ padding-right: 30px; }}
QComboBox::drop-down {{ border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 4px;
    selection-background-color: {t['accent_soft']}; selection-color: {t['text']};
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QPlainTextEdit {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 10px;
    font-family: "Cascadia Mono", "Consolas", "Ubuntu Mono", "DejaVu Sans Mono", monospace; font-size: 9.5pt;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['idle']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

QProgressBar#Busy {{ background: transparent; border: none; max-height: 3px; min-height: 3px; }}
QProgressBar#Busy::chunk {{ background: {t['accent']}; border-radius: 1px; }}

QDialog#Dialog {{ background: {t['surface']}; }}
#DialogTitle {{ font-size: 13pt; font-weight: 700; }}
#Toast {{ background: {t['text']}; border-radius: 10px; }}
#Toast QLabel {{ color: {t['bg']}; font-weight: 500; }}
#Pill {{ border-radius: 10px; padding: 3px 10px; font-size: 9pt; font-weight: 700; }}
QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
"""
