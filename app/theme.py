"""
HicoForge theme — sibling palette to HicoSend.
Dark gradient base + brand red + amber/orange forge accent.
"""

# ---- Brand palette ----
BRAND_RED = "#E11D2C"
BRAND_RED_DEEP = "#9F1119"
BRAND_RED_BRIGHT = "#EF2533"

# Forge accent (differentiates from HicoSend's pure red)
EMBER_ORANGE = "#FF7A1A"
EMBER_GOLD = "#FFB347"
EMBER_DEEP = "#B84A00"

# Surfaces
BG_TOP = "#1B1B1F"
BG_BOTTOM = "#0E0E11"
SURFACE = "#16161A"
SURFACE_RAISED = "#1F1F24"
SURFACE_HOVER = "#26262C"
BORDER_SUBTLE = "#2A2A30"
BORDER_FOCUS = EMBER_ORANGE

# Text
TEXT_PRIMARY = "#F5F6F8"
TEXT_SECONDARY = "#A8ACB4"
TEXT_DIM = "#6E727A"
TEXT_DISABLED = "#4A4D54"

# Status
SUCCESS = "#22C55E"
WARNING = "#F59E0B"
ERROR = BRAND_RED

# Typography
FONT_DISPLAY = "Segoe UI Variable Display, Segoe UI, Inter, system-ui"
FONT_TEXT = "Segoe UI Variable Text, Segoe UI, Inter, system-ui"
FONT_MONO = "JetBrains Mono, Cascadia Code, Consolas, monospace"

# Sizing
RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14
RADIUS_XL = 20

# Window
WINDOW_BG_QSS = f"""
    QWidget#RootShell {{
        background: qlineargradient(
            x1:0, y1:0, x2:0.5, y2:1,
            stop:0 {BG_TOP},
            stop:1 {BG_BOTTOM}
        );
        border-radius: {RADIUS_LG}px;
    }}
"""

# Master stylesheet
APP_QSS = f"""
    * {{
        font-family: {FONT_TEXT};
        color: {TEXT_PRIMARY};
        outline: none;
    }}

    QWidget#RootShell {{
        background: qlineargradient(
            x1:0, y1:0, x2:0.5, y2:1,
            stop:0 {BG_TOP},
            stop:1 {BG_BOTTOM}
        );
    }}

    /* --- Title bar --- */
    QWidget#TitleBar {{
        background: transparent;
    }}
    QLabel#AppTitle {{
        font-family: {FONT_DISPLAY};
        font-size: 14px;
        font-weight: 600;
        color: {TEXT_PRIMARY};
        letter-spacing: 0.3px;
    }}
    QLabel#AppSubtitle {{
        font-size: 10px;
        color: {TEXT_DIM};
        letter-spacing: 2px;
    }}

    /* --- Window controls --- */
    QPushButton#WinBtn {{
        background: transparent;
        border: none;
        color: {TEXT_SECONDARY};
        font-size: 14px;
        padding: 0;
        min-width: 36px;
        min-height: 28px;
    }}
    QPushButton#WinBtn:hover {{
        background: {SURFACE_HOVER};
        color: {TEXT_PRIMARY};
    }}
    QPushButton#WinBtnClose:hover {{
        background: {BRAND_RED};
        color: white;
    }}

    /* --- Grid picker --- */
    QWidget#GridPicker {{
        background: {SURFACE};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_MD}px;
    }}
    QLabel#GridPickerLabel {{
        font-size: 11px;
        font-weight: 500;
        color: {TEXT_SECONDARY};
        letter-spacing: 1.5px;
        padding-left: 4px;
    }}
    QPushButton#GridBtn {{
        background: transparent;
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_SM}px;
        color: {TEXT_SECONDARY};
        font-size: 12px;
        font-weight: 500;
        padding: 6px 12px;
        min-width: 32px;
    }}
    QPushButton#GridBtn:hover {{
        background: {SURFACE_HOVER};
        color: {TEXT_PRIMARY};
        border-color: {EMBER_ORANGE};
    }}
    QPushButton#GridBtn:checked {{
        background: qlineargradient(
            x1:0, y1:0, x2:0, y2:1,
            stop:0 {EMBER_ORANGE},
            stop:1 {EMBER_DEEP}
        );
        color: white;
        border-color: {EMBER_ORANGE};
    }}

    /* --- Preset combo --- */
    QComboBox#PresetCombo {{
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_SM}px;
        padding: 6px 10px;
        color: {TEXT_PRIMARY};
        font-size: 12px;
        min-width: 160px;
    }}
    QComboBox#PresetCombo:hover {{
        border-color: {EMBER_ORANGE};
    }}
    QComboBox#PresetCombo::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox#PresetCombo QAbstractItemView {{
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER_SUBTLE};
        selection-background-color: {EMBER_DEEP};
        color: {TEXT_PRIMARY};
        padding: 4px;
    }}

    /* --- Drop tile (empty slot) --- */
    QWidget#TileEmpty {{
        background: {SURFACE};
        border: 2px dashed {BORDER_SUBTLE};
        border-radius: {RADIUS_MD}px;
    }}
    QWidget#TileEmpty:hover {{
        border-color: {EMBER_ORANGE};
        background: {SURFACE_RAISED};
    }}
    QLabel#TileEmptyLabel {{
        color: {TEXT_DIM};
        font-size: 13px;
        font-weight: 500;
    }}
    QLabel#TileEmptyHint {{
        color: {TEXT_DISABLED};
        font-size: 10px;
        letter-spacing: 1px;
    }}

    /* --- Drop tile (configured) --- */
    QWidget#Tile {{
        background: {SURFACE};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_MD}px;
    }}
    QWidget#Tile:hover {{
        border-color: {EMBER_ORANGE};
    }}
    QWidget#TileActive {{
        background: {SURFACE_RAISED};
        border: 2px solid {EMBER_ORANGE};
        border-radius: {RADIUS_MD}px;
    }}
    QLabel#TileName {{
        font-family: {FONT_DISPLAY};
        font-size: 14px;
        font-weight: 600;
        color: {TEXT_PRIMARY};
    }}
    QLabel#TileCategory {{
        font-size: 9px;
        font-weight: 600;
        color: {EMBER_GOLD};
        letter-spacing: 1.5px;
    }}
    QLabel#TileDesc {{
        font-size: 11px;
        color: {TEXT_SECONDARY};
    }}

    /* --- Standard buttons --- */
    QPushButton#PrimaryBtn {{
        background: qlineargradient(
            x1:0, y1:0, x2:0, y2:1,
            stop:0 {EMBER_ORANGE},
            stop:1 {EMBER_DEEP}
        );
        color: white;
        border: none;
        border-radius: {RADIUS_SM}px;
        padding: 8px 18px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#PrimaryBtn:hover {{
        background: qlineargradient(
            x1:0, y1:0, x2:0, y2:1,
            stop:0 {EMBER_GOLD},
            stop:1 {EMBER_ORANGE}
        );
    }}
    QPushButton#GhostBtn {{
        background: transparent;
        color: {TEXT_SECONDARY};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_SM}px;
        padding: 6px 12px;
        font-size: 11px;
    }}
    QPushButton#GhostBtn:hover {{
        color: {TEXT_PRIMARY};
        border-color: {EMBER_ORANGE};
    }}

    /* --- Scrollbar --- */
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_SUBTLE};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {EMBER_ORANGE};
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
    }}
"""
