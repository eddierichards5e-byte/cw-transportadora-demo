"""Ícones vetoriais consistentes para a interface premium."""
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtSvg import QSvgRenderer

_LUCIDE = {
    'layout-dashboard': '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    'truck': '<rect x="1" y="5" width="13" height="11" rx="2"/><path d="M14 8h4l4 4v4h-8z"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
    'route': '<circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M6 17c0-7 12-4 12-10"/>',
    'map': '<path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/>',
    'file-text': '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
    'package-check': '<path d="m16.5 9.4 2 2 4-4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9l7 7z"/><path d="M14 3v6h6"/>',
    'users': '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    'bus-front': '<path d="M4 17h16V7a3 3 0 0 0-3-3H7a3 3 0 0 0-3 3z"/><circle cx="8" cy="17" r="1.5"/><circle cx="16" cy="17" r="1.5"/><path d="M5 10h14M8 7h8M6 17v3M18 17v3"/>',
    'fuel': '<path d="M3 22V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v17M3 7h12M18 8l3 3v7a2 2 0 0 1-2 2h-1V8z"/><path d="M7 11h4"/>',
    'wrench': '<path d="M14.7 6.3a5 5 0 0 0-6.4 6.4L3 18l3 3 5.3-5.3a5 5 0 0 0 6.4-6.4L14 12l-3-3z"/>',
    'wallet': '<path d="M3 6h16a2 2 0 0 1 2 2v11H5a2 2 0 0 1-2-2z"/><path d="M3 6V5a2 2 0 0 1 2-2h13v3M17 13h4"/>',
    'file-bar-chart': '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 17v-3M12 17v-6M16 17v-4"/>',
    'users-round': '<path d="M18 21a8 8 0 0 0-16 0"/><circle cx="10" cy="7" r="4"/><path d="M22 21a6 6 0 0 0-4-5.65M16 3.13a4 4 0 0 1 0 7.75"/>',
    'settings': '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-1.8 1.8-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.55V20h-2.55v-.11a1.7 1.7 0 0 0-1.03-1.55 1.7 1.7 0 0 0-1.88.34l-.06.06-1.8-1.8.06-.06A1.7 1.7 0 0 0 8.1 15a1.7 1.7 0 0 0-1.55-1.03H6.4v-2.55h.15A1.7 1.7 0 0 0 8.1 10.4a1.7 1.7 0 0 0-.34-1.88L7.7 8.46l1.8-1.8.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03 1.55V5.4h2.55v.11a1.7 1.7 0 0 0 1.03 1.55 1.7 1.7 0 0 0 1.88-.34l.06-.06 1.8 1.8-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.55 1.03h.11v2.55h-.11A1.7 1.7 0 0 0 19.4 15z"/>',
    'user-cog': '<circle cx="9" cy="7" r="4"/><path d="M2 21v-2a7 7 0 0 1 7-7M19 15v6M16 18h6"/>',
    'shield-check': '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    'history': '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
    'refresh-cw': '<path d="M21 12a9 9 0 0 0-15.3-6.4L3 8"/><path d="M3 3v5h5M3 12a9 9 0 0 0 15.3 6.4L21 16"/><path d="M21 21v-5h-5"/>',
    'upload-cloud': '<path d="M16 16l-4-4-4 4M12 12v9"/><path d="M20.4 17.5A5 5 0 0 0 18 8h-1.3A8 8 0 1 0 4 16.3"/>',
    'circle': '<circle cx="12" cy="12" r="8"/>',
}

def get_lucide_pixmap(name, size=24, color="#ffffff"):
    body = _LUCIDE.get(name, _LUCIDE['circle'])
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap

def get_icon(name, size=None, color="#ffffff"):
    return get_lucide_pixmap(name, size or 24, color)

def get_pixmap(name, size=None, color="#ffffff"):
    return get_icon(name, size, color)
