"""
Command Palette / Busca Global.
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt


class Command:
    def __init__(self, id, label, description="", icon="", category="", action=None):
        self.id = id
        self.label = label
        self.description = description
        self.icon = icon
        self.category = category
        self.action = action


class CommandRegistry:
    """Registry de comandos globais."""
    
    def __init__(self):
        self._commands = []
        self._nav_callback = None
        self._parent = None
    
    def build_default_commands(self, nav_callback, parent=None):
        self._nav_callback = nav_callback
        self._parent = parent
        self._commands = [
            Command("nav:dashboard", "Dashboard", "Painel principal", "🏠", "Navegação", lambda: nav_callback("dashboard")),
            Command("nav:operacoes", "Nova Operação", "Registro de transferências", "📝", "Navegação", lambda: nav_callback("operacoes")),
            Command("nav:notas", "Notas", "Importação de manifestos", "📄", "Navegação", lambda: nav_callback("notas")),
            Command("nav:ranking", "Ranking", "Ranking de clientes", "📊", "Navegação", lambda: nav_callback("ranking_clientes")),
        ]
    
    def set_search_provider(self, provider):
        pass
    
    def open(self, parent, query=""):
        dialog = QDialog(parent)
        dialog.setWindowTitle("Buscar (Ctrl+K)")
        dialog.setMinimumWidth(500)
        dialog.setMinimumHeight(400)
        
        layout = QVBoxLayout(dialog)
        
        search = QLineEdit()
        search.setPlaceholderText("Digite para buscar...")
        layout.addWidget(search)
        
        list_widget = QListWidget()
        layout.addWidget(list_widget)
        
        for cmd in self._commands:
            item = QListWidgetItem(f"{cmd.icon} {cmd.label}")
            item.setData(Qt.ItemDataRole.UserRole, cmd)
            list_widget.addItem(item)
        
        def on_activate(item):
            cmd = item.data(Qt.ItemDataRole.UserRole)
            if cmd and cmd.action:
                cmd.action()
                dialog.close()
        
        list_widget.itemActivated.connect(on_activate)
        search.setFocus()
        dialog.exec()
    
    def search(self, query):
        return []


command_registry = CommandRegistry()
