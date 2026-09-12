"""Prepara uma base do CW para distribuição sem deixar dados operacionais."""
from utils.database._conexao import resetar_dados_operacionais

def preparar_base_para_distribuicao(criar_backup=True):
    """Executa o reset operacional real e retorna o backup criado.

    O argumento é mantido por compatibilidade com versões antigas; o reset
    sempre cria e valida um backup antes de apagar os dados.
    """
    return resetar_dados_operacionais()
