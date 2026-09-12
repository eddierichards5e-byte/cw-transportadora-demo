"""
Serviço de busca.
"""


class SearchResult:
    def __init__(self, categoria, titulo, descricao, tela, registro_id, icon="🔍", cliente_data=None):
        self.categoria = categoria
        self.titulo = titulo
        self.descricao = descricao
        self.tela = tela
        self.registro_id = registro_id
        self.icon = icon
        self.cliente_data = cliente_data


class SearchService:
    def search(self, query):
        return []


search_service = SearchService()