"""
Serviço de combustível.
"""


class CombustivelService:
    def listar_abastecimentos(self, filtros=None):
        return []
    
    def registrar_abastecimento(self, dados):
        return 1
    
    def resumo_combustivel(self):
        return {"litros": 0.0, "custo": 0.0, "km": 0.0, "media": 0.0}


combustivel_service = CombustivelService()
