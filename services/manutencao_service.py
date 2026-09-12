"""
Serviço de manutenção.
"""


class ManutencaoService:
    def listar_manutencoes(self, filtros=None):
        return []
    
    def registrar_manutencao(self, dados):
        return 1
    
    def resumo_manutencoes(self):
        return {"total": 0, "custo": 0.0, "pendentes": 0}


manutencao_service = ManutencaoService()
