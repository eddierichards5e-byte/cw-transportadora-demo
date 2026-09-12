"""
Branding compartilhado da CW Transportadora.
Centraliza o acesso à logo oficial para manter consistência entre login,
sidebar e demais pontos da interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from config.settings import settings


def get_official_logo_path() -> Optional[str]:
    """Retorna o caminho absoluto da logo oficial da CW, se existir."""
    candidates = [
        settings.resource_path("assets/logo_cw.jpg"),
        settings.resource_path("assets/logo_cw.png"),
        settings.resource_path("assets/logo.ico"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def load_official_logo_pixmap(
    width: int,
    height: int,
    *,
    keep_aspect: bool = True,
) -> Optional[QPixmap]:
    """Carrega a logo oficial já redimensionada com suavização."""
    logo_path = get_official_logo_path()
    if not logo_path:
        return None

    pixmap = QPixmap(logo_path)
    if pixmap.isNull():
        return None

    aspect_mode = (
        Qt.AspectRatioMode.KeepAspectRatio
        if keep_aspect
        else Qt.AspectRatioMode.IgnoreAspectRatio
    )
    return pixmap.scaled(
        width,
        height,
        aspect_mode,
        Qt.TransformationMode.SmoothTransformation,
    )
