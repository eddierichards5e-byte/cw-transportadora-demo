"""
Serviço de operações.
"""


class OperacoesService:
    def criar_operacao(self, dados):
        print(f"[OPERACAO] Criada: {dados.get('nome_caminhao', 'N/A')}")
        return 1
    
    def listar_operacoes(self, filtros=None):
        return []
    
    def obter_operacao(self, op_id):
        return None
    
    def atualizar_operacao(self, op_id, dados):
        return True
    
    def excluir_operacao(self, op_id):
        return True


operacoes_service = OperacoesService()
