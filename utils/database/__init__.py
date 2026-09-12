"""
Database utils - Criacao e gerenciamento do banco SQLite.
Delega toda a criacao de tabelas para _conexao.py (schema unico).
"""

from utils.database._conexao import (
    conectar, get_connection, get_connection_rows,
    criar_banco, criar_backup_manual, listar_backups_manuais, resetar_dados_operacionais, restaurar_backup, tabela_existe_sqlite, registrar_sync, agora_sync, novo_id_global, diagnostico_banco
)
from utils.database.caminhoes import listar_caminhoes, apagar_todos_caminhoes, cadastrar_caminhao, excluir_caminhao
from utils.database.clientes import buscar_cliente_por_cnpj, criar_cliente, obter_ou_criar_cliente, buscar_clientes_por_nome, atualizar_prioridade_cliente, obter_prioridade_cliente
from utils.database.notas import (
    salvar_nota, listar_notas, listar_notas_disponiveis, listar_notas_entregues, buscar_nota_para_leitura, listar_notas_planejamento, nota_existe,
    criar_manifesto, listar_manifestos, listar_notas_por_manifesto,
    apagar_manifesto, listar_notas_por_cliente, calcular_resumo_notas, finalizar_nota_entregue, finalizar_notas_entregues
)
from utils.database.viagens import (
    criar_viagem, apagar_viagem, listar_viagens,
    listar_notas_da_viagem, finalizar_viagem, buscar_detalhes_viagem
)
from utils.database.relatorios import dados_dashboard, top_destinos_dashboard, criar_operacao_sp, listar_operacoes_sp


def sqlite_connection_factory(db_path=None):
    import sqlite3
    if db_path is None:
        db_path = "data/cw_transportadora.db"
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def criar_caminhoes_padrao():
    """Compatibilidade histórica: o CW não cria veículos fictícios.

    Mantida apenas para não quebrar o main legado; a frota deve ser cadastrada
    pelo usuário e permanecer vazia após um reset até que veículos reais sejam
    incluídos.
    """
    return False


def remover_caminhoes_demonstracao():
    """Remove veículos fictícios das versões antigas, uma única vez.

    Somente identificadores claramente usados como dados de demonstração são
    atingidos. A remoção é sincronizada para que a frota falsa não reapareça
    em outros computadores.
    """
    placas = {"ABC-1234", "DEF-5678", "GHI-9012", "Renault Master", "3/4 Branco", "3/4 Preto", "Toco"}
    modelos = {"Volvo FH 540", "Scania R450", "Mercedes Actros", "Renault Master", "Caminhão 3/4 Branco", "Caminhão 3/4 Preto", "Caminhão Toco"}
    conn = conectar(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, placa, modelo FROM caminhoes")
        removidos = []
        for rid, placa, modelo in cur.fetchall():
            if str(placa or "").strip() in placas or str(modelo or "").strip() in modelos:
                removidos.append(int(rid))
        for rid in removidos:
            # Veículos de demonstração podem ter deixado viagens históricas.
            # Desvinculamos somente as viagens não ativas para permitir a
            # remoção definitiva sem apagar o histórico.
            try:
                cur.execute("""
                    SELECT COUNT(*) FROM viagens
                    WHERE caminhao_id=?
                      AND lower(COALESCE(status,'')) NOT LIKE '%final%'
                      AND lower(COALESCE(status,'')) NOT LIKE '%entreg%'
                      AND lower(COALESCE(status,'')) NOT LIKE '%cancel%'
                """, (rid,))
                if int(cur.fetchone()[0] or 0) == 0:
                    cur.execute("UPDATE viagens SET caminhao_id=NULL WHERE caminhao_id=?", (rid,))
                    try: registrar_sync(cur, "caminhoes", rid, "DELETE")
                    except Exception: pass
                    cur.execute("DELETE FROM caminhoes WHERE id=?", (rid,))
            except Exception:
                pass
        conn.commit()
        if removidos:
            logger_msg = f"[DB] Veículos de demonstração removidos: {len(removidos)}"
            print(logger_msg)
        return len(removidos)
    finally:
        conn.close()



def gerar_ranking_clientes_v6(tipo, mes, ano, conn=None):
    return []
