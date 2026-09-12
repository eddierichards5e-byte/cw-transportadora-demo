"""Design tokens globais da CW Transportadora."""
from PySide6.QtGui import QFont


class CWTheme:
    """Tema corporativo CW: azul-marinho, alto contraste e acentos controlados."""

    def __init__(self):
        self.colors = {
            "bg_primary": "#0B1422",
            "bg_secondary": "#101C2E",
            "bg_tertiary": "#16253A",
            "bg_elevated": "#14243A",
            "bg_overlay": "#1B304A",
            "bg_surface": "#101C2E",
            "bg_glass": "rgba(16, 28, 46, 0.94)",
            "text_primary": "#F4F7FB",
            "text_secondary": "#A8B6C9",
            "text_tertiary": "#71829A",
            "text_disabled": "#53657D",
            "text_inverted": "#0B1422",
            "border_subtle": "#1A2A40",
            "border_default": "#223650",
            "border_strong": "#2B4564",
            "border_hover": "#385574",
            "border_focus": "#B94747",
            "primary": "#E14B4B",
            "primary_hover": "#F05B5B",
            "primary_active": "#C83E3E",
            "primary_soft": "rgba(225, 75, 75, 0.14)",
            "success": "#36B37E",
            "success_soft": "rgba(54, 179, 126, 0.14)",
            "warning": "#D6A23C",
            "warning_soft": "rgba(214, 162, 60, 0.14)",
            "error": "#E05252",
            "error_soft": "rgba(224, 82, 82, 0.14)",
            "info": "#4C8DFF",
            "info_soft": "rgba(76, 141, 255, 0.14)",
            "sidebar_bg": "#0B1728",
            "sidebar_border": "#1D3048",
            "sidebar_text": "#A8B6C9",
            "sidebar_text_muted": "#71829A",
            "header_bg": "#101C2E",
            "header_border": "#223650",
            "card_bg": "#101C2E",
            "card_border": "#223650",
            "card_hover": "#16253A",
            "table_header_bg": "#14243A",
            "table_header_text": "#8EA1B8",
            "table_row_even": "#0F1A2A",
            "table_row_odd": "#101C2E",
            "table_row_hover": "rgba(76, 141, 255, 0.08)",
            "table_row_selected": "rgba(225, 75, 75, 0.12)",
            "brand": "#E14B4B",
            "brand_hover": "#F05B5B",
            "brand_active": "#C83E3E",
            "brand_soft": "rgba(225, 75, 75, 0.14)",
            "brand_glow": "rgba(225, 75, 75, 0.22)",
            "emerald": "#36B37E",
            "emerald_soft": "rgba(54, 179, 126, 0.14)",
            "sky": "#4C8DFF",
            "sky_soft": "rgba(76, 141, 255, 0.14)",
            "amber": "#D6A23C",
            "amber_soft": "rgba(214, 162, 60, 0.14)",
            "violet": "#9B83F5",
            "violet_soft": "rgba(155, 131, 245, 0.14)",
            "cyan": "#4BB7C5",
            "cyan_soft": "rgba(75, 183, 197, 0.14)",
            "rose": "#E98B9B",
            "rose_soft": "rgba(233, 139, 155, 0.14)",
        }
        self.spacing = self._Spacing()
        self.radius = self._Radius()
        self.typography = self._Typography()

    class _Spacing:
        XS = 4
        SM = 8
        MD = 12
        LG = 16
        XL = 24
        _2XL = 32
        _3XL = 48
        _4XL = 64
        SPACING_XS = 4
        SPACING_SM = 8
        SPACING_MD = 12
        SPACING_LG = 16
        SPACING_XL = 24
        SPACING_2XL = 32
        SPACING_3XL = 48
        SPACING_4XL = 64
        FONT_SIZE_XS = 11
        FONT_SIZE_SM = 12
        FONT_SIZE_MD = 14
        FONT_SIZE_LG = 16
        FONT_SIZE_XL = 18
        FONT_SIZE_2XL = 24
        FONT_SIZE_3XL = 32
        FONT_FAMILY_QT = "Segoe UI"

    class _Radius:
        XS = 4
        SM = 8
        MD = 12
        LG = 16
        XL = 20
        _2XL = 24

    class _Typography:
        FONT_SIZE_XS = 11
        FONT_SIZE_SM = 12
        FONT_SIZE_MD = 14
        FONT_SIZE_LG = 16
        FONT_SIZE_XL = 18
        FONT_SIZE_2XL = 24
        FONT_SIZE_3XL = 32
        FONT_FAMILY_QT = "Segoe UI"

    def get_font(self, size=14, bold=False, weight=None):
        font = QFont(self.spacing.FONT_FAMILY_QT, size)
        if weight is not None:
            try:
                font.setWeight(weight)
            except Exception:
                pass
        if bold:
            font.setBold(True)
        return font


cw_theme = CWTheme()
