"""
Avatar utilities — CW Transportadora
Funções compartilhadas para renderizar avatares circulares e iniciais.
Usado por Sidebar, TopBar, Perfil, Gerenciar Usuários, etc.
"""

from typing import Optional
from PySide6.QtWidgets import QLabel, QWidget
from PySide6.QtCore import Qt, QSize, Signal, QObject
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont

from ui.theme.cw_theme import cw_theme
from services.perfil_service import perfil_service


# ── Signal bus para notificar quando avatar muda ──────────────────────────────
class _AvatarBus(QObject):
    avatar_updated = Signal(int)   # emite usuario_id


avatar_bus = _AvatarBus()


# ── Helper: imagem → pixmap circular ─────────────────────────────────────────
def fazer_pixmap_circular(caminho: str, tamanho: int) -> Optional[QPixmap]:
    """Recorta qualquer imagem em círculo perfeito, anti-aliased."""
    if not caminho:
        return None
    src = QPixmap(caminho)
    if src.isNull():
        return None
    src = src.scaled(
        tamanho, tamanho,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    dst = QPixmap(tamanho, tamanho)
    dst.fill(Qt.GlobalColor.transparent)
    painter = QPainter(dst)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addEllipse(0, 0, tamanho, tamanho)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, src)
    painter.end()
    return dst


# ── Helper: iniciais → pixmap circular colorido ──────────────────────────────
def fazer_pixmap_iniciais(nome: str, tamanho: int) -> QPixmap:
    """Gera um pixmap circular com as iniciais do nome numa cor determinística."""
    initials = perfil_service.get_initials(nome) if nome else "?"
    color = perfil_service.get_avatar_color(nome) if nome else "#6366F1"

    dst = QPixmap(tamanho, tamanho)
    dst.fill(Qt.GlobalColor.transparent)
    painter = QPainter(dst)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Círculo colorido
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(0, 0, tamanho, tamanho)

    # Texto das iniciais
    font_size = max(8, tamanho // 3)
    font = QFont(cw_theme.typography.FONT_FAMILY_QT, font_size)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(0, 0, tamanho, tamanho, Qt.AlignmentFlag.AlignCenter, initials)
    painter.end()
    return dst


# ── Widget reutilizável: AvatarWidget ────────────────────────────────────────
class AvatarWidget(QLabel):
    """
    Avatar circular 'inteligente':
    - Se o usuário tiver foto → mostra foto circular
    - Se não → mostra iniciais com cor determinística
    - Atualiza automaticamente via avatar_bus quando a foto muda
    """

    def __init__(self, usuario_id: Optional[int] = None, nome: str = "",
                 tamanho: int = 40, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._usuario_id = usuario_id
        self._nome = nome
        self._tamanho = tamanho

        self.setFixedSize(tamanho, tamanho)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c = cw_theme.colors
        self.setStyleSheet(f"""
        QLabel {{
            background: transparent;
            border: 2px solid {c['border_subtle']};
            border-radius: {tamanho // 2}px;
        }}
        """)
        
        # Adicionar sombra suave
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8)
        shadow.setColor(QColor(0, 0, 0, 0.2))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

        self._refresh()

        # Escuta o bus global para re-renderizar se a foto mudar
        if usuario_id is not None:
            avatar_bus.avatar_updated.connect(self._on_avatar_updated)

    def _on_avatar_updated(self, uid: int):
        if uid == self._usuario_id:
            self._refresh()

    def _refresh(self):
        """Carrega foto ou iniciais e aplica ao QLabel."""
        if self._usuario_id is not None:
            path = perfil_service.get_avatar_path(self._usuario_id)
            if path:
                pix = fazer_pixmap_circular(path, self._tamanho)
                if pix:
                    self.setPixmap(pix)
                    self.setText("")
                    return

        # Fallback: iniciais
        pix = fazer_pixmap_iniciais(self._nome, self._tamanho)
        self.setPixmap(pix)
        self.setText("")

    def update_user(self, usuario_id: Optional[int], nome: str):
        self._usuario_id = usuario_id
        self._nome = nome
        self._refresh()
