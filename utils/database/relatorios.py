"""Consultas agregadas: dashboard, ranking de clientes, top destinos, operacoes SP."""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

from utils.logger import get_logger
from ._conexao import conectar, registrar_sync, novo_id_global
from utils.date_utils import sql_date_month, sql_date_year

logger = get_logger(__name__)


def dados_dashboard(tipo_periodo="Geral", mes=None, ano=None, conn: Optional[sqlite3.Connection] = None):
    """
    Args:
        conn: conexão opcional já aberta para reaproveitar em operações que
            combinam várias consultas (ex.: carregar_dashboard). Se omitida,
            uma conexão própria é aberta e fechada aqui.
    """
    conexao_propria = conn is None
    if conexao_propria:
        conn = conectar()
    cursor = conn.cursor()

    filtro_viagens = ""
    params_viagens = []

    filtro_manifestos = ""
    params_manifestos = []

    filtro_notas = ""
    params_notas = []

    if tipo_periodo == "Mês" and mes and ano:
        filtro_viagens = "WHERE CASE WHEN instr(COALESCE(data_saida,''), '/') > 0 THEN substr(COALESCE(data_saida,''), 4, 2) ELSE substr(COALESCE(data_saida,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(data_saida,''), '/') > 0 THEN substr(COALESCE(data_saida,''), 7, 4) ELSE substr(COALESCE(data_saida,''), 1, 4) END = ?"
        params_viagens = [mes, ano]

        filtro_manifestos = "WHERE substr(data_importacao, 6, 2) = ? AND substr(data_importacao, 1, 4) = ?"
        params_manifestos = [mes, ano]

        filtro_notas = "WHERE CASE WHEN instr(COALESCE(criado_em,''), '/') > 0 THEN substr(COALESCE(criado_em,''), 4, 2) ELSE substr(COALESCE(criado_em,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(criado_em,''), '/') > 0 THEN substr(COALESCE(criado_em,''), 7, 4) ELSE substr(COALESCE(criado_em,''), 1, 4) END = ?"
        params_notas = [mes, ano]

    elif tipo_periodo == "Ano" and ano:
        filtro_viagens = "WHERE CASE WHEN instr(COALESCE(data_saida,''), '/') > 0 THEN substr(COALESCE(data_saida,''), 7, 4) ELSE substr(COALESCE(data_saida,''), 1, 4) END = ?"
        params_viagens = [ano]

        filtro_manifestos = "WHERE substr(data_importacao, 1, 4) = ?"
        params_manifestos = [ano]

        filtro_notas = "WHERE CASE WHEN instr(COALESCE(criado_em,''), '/') > 0 THEN substr(COALESCE(criado_em,''), 7, 4) ELSE substr(COALESCE(criado_em,''), 1, 4) END = ?"
        params_notas = [ano]

    cursor.execute(f"SELECT COUNT(*) FROM manifestos {filtro_manifestos}", params_manifestos)
    total_manifestos = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM notas {filtro_notas}", params_notas)
    total_notas = cursor.fetchone()[0]

    separador_notas = "AND" if filtro_notas else "WHERE"
    separador_viagens = "AND" if filtro_viagens else "WHERE"

    cursor.execute(
        f"SELECT COUNT(*) FROM notas {filtro_notas} {separador_notas} status = 'Disponível'",
        params_notas,
    )
    notas_disponiveis = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM notas {filtro_notas} {separador_notas} status = 'Em viagem'",
        params_notas,
    )
    notas_em_viagem = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM notas {filtro_notas} {separador_notas} status = 'Entregue'",
        params_notas,
    )
    notas_entregues = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM viagens {filtro_viagens}", params_viagens)
    total_viagens = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM viagens {filtro_viagens} {separador_viagens} status = 'Em viagem'",
        params_viagens,
    )
    viagens_em_andamento = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM viagens {filtro_viagens} {separador_viagens} status = 'Finalizada'",
        params_viagens,
    )
    viagens_finalizadas = cursor.fetchone()[0]

    cursor.execute(f"SELECT COALESCE(SUM(frete_total), 0) FROM viagens {filtro_viagens}", params_viagens)
    frete_total = cursor.fetchone()[0]

    cursor.execute(f"SELECT COALESCE(SUM(peso_total), 0) FROM viagens {filtro_viagens}", params_viagens)
    peso_total = cursor.fetchone()[0]

    if conexao_propria:
        conn.close()

    return {
        "total_manifestos": total_manifestos,
        "total_notas": total_notas,
        "notas_disponiveis": notas_disponiveis,
        "notas_em_viagem": notas_em_viagem,
        "notas_entregues": notas_entregues,
        "total_viagens": total_viagens,
        "viagens_em_andamento": viagens_em_andamento,
        "viagens_finalizadas": viagens_finalizadas,
        "frete_total": frete_total,
        "peso_total": peso_total
    }


def top_destinos_dashboard(tipo_periodo="Geral", mes=None, ano=None, conn: Optional[sqlite3.Connection] = None):
    """
    Args:
        conn: conexão opcional já aberta (ver `dados_dashboard`).
    """
    conexao_propria = conn is None
    if conexao_propria:
        conn = conectar()
    cursor = conn.cursor()

    filtro = ""
    params = []

    if tipo_periodo == "Mês" and mes and ano:
        filtro = "WHERE CASE WHEN instr(COALESCE(notas.criado_em,''), '/') > 0 THEN substr(COALESCE(notas.criado_em,''), 4, 2) ELSE substr(COALESCE(notas.criado_em,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(notas.criado_em,''), '/') > 0 THEN substr(COALESCE(notas.criado_em,''), 7, 4) ELSE substr(COALESCE(notas.criado_em,''), 1, 4) END = ?"
        params = [mes, ano]

    elif tipo_periodo == "Ano" and ano:
        filtro = "WHERE CASE WHEN instr(COALESCE(notas.criado_em,''), '/') > 0 THEN substr(COALESCE(notas.criado_em,''), 7, 4) ELSE substr(COALESCE(notas.criado_em,''), 1, 4) END = ?"
        params = [ano]

    cursor.execute(f"""
        SELECT
            notas.destino,
            COUNT(notas.id) as total_notas,
            COALESCE(SUM(notas.peso), 0) as peso_total
        FROM notas
        {filtro}
        GROUP BY notas.destino
        ORDER BY total_notas DESC
        LIMIT 4
    """, params)

    dados = cursor.fetchall()
    if conexao_propria:
        conn.close()

    return dados


def criar_operacao_sp(dados):
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO operacoes_sp (
                id, data_operacao,
                nome_caminhao,
                placa,
                motorista,
                valor_notas,
                frete_carreta,
                pedagio_carreta,
                outros_custos,
                custo_total,
                liquido
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            novo_id_global(),
            dados.get("data_operacao"),
            dados.get("nome_caminhao"),
            dados.get("placa"),
            dados.get("motorista"),
            dados.get("valor_notas", 0),
            dados.get("frete_carreta", 0),
            dados.get("pedagio_carreta", 0),
            dados.get("outros_custos", 0),
            dados.get("custo_total", 0),
            dados.get("liquido", 0)
        ))
        operacao_id = cursor.lastrowid
        registrar_sync(cursor, "operacoes_sp", operacao_id)
        conn.commit()
    finally:
        conn.close()
    return True


def listar_operacoes_sp():
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT
                id,
                data_operacao,
                nome_caminhao,
                placa,
                motorista,
                valor_notas,
                frete_carreta,
                pedagio_carreta,
                outros_custos,
                custo_total,
                liquido
            FROM operacoes_sp
            ORDER BY id DESC
        """)
        return cursor.fetchall()
    finally:
        conn.close()


def gerar_ranking_clientes_v6(tipo_periodo="Geral", mes=None, ano=None, conn: Optional[sqlite3.Connection] = None):
    """Ranking comercial por valor de mercadorias das notas dos manifestos.

    O período é definido pela data de importação do manifesto, e não pelo
    status da nota. Assim o ranking representa toda a carteira comercial.
    """
    conexao_propria = conn is None
    if conexao_propria:
        conn = conectar()
    cursor = conn.cursor()

    filtro = ""
    params = []
    if tipo_periodo == "Mês" and mes and ano:
        filtro = "WHERE CASE WHEN instr(COALESCE(manifestos.data_importacao,''), '/') > 0 THEN substr(COALESCE(manifestos.data_importacao,''), 4, 2) ELSE substr(COALESCE(manifestos.data_importacao,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(manifestos.data_importacao,''), '/') > 0 THEN substr(COALESCE(manifestos.data_importacao,''), 7, 4) ELSE substr(COALESCE(manifestos.data_importacao,''), 1, 4) END = ?"
        params = [str(mes).zfill(2), str(ano)]
    elif tipo_periodo == "Ano" and ano:
        filtro = "WHERE CASE WHEN instr(COALESCE(manifestos.data_importacao,''), '/') > 0 THEN substr(COALESCE(manifestos.data_importacao,''), 7, 4) ELSE substr(COALESCE(manifestos.data_importacao,''), 1, 4) END = ?"
        params = [str(ano)]

    cursor.execute(f"""
        SELECT
            destinatario.nome as cliente,
            COUNT(notas.id) as total_notas,
            COALESCE(SUM(notas.valor_mercadoria), 0) as valor_notas,
            COALESCE(SUM(notas.valor_frete), 0) as frete_total,
            COALESCE(SUM(notas.peso), 0) as peso_total
        FROM notas
        JOIN manifestos ON manifestos.id = notas.manifesto_id
        LEFT JOIN clientes destinatario ON destinatario.id = notas.destinatario_id
        {filtro}
        GROUP BY destinatario.id, destinatario.nome
        ORDER BY valor_notas DESC, frete_total DESC, total_notas DESC, cliente ASC
    """, params)

    dados = cursor.fetchall()
    if conexao_propria:
        conn.close()

    ranking = []
    for cliente, total_notas, valor_notas, frete_total, peso_total in dados:
        percentual_medio = (frete_total / valor_notas * 100) if valor_notas else 0
        ranking.append({
            "cliente": cliente or "Cliente não informado",
            "total_notas": total_notas or 0,
            "valor_notas": valor_notas or 0,
            "frete": frete_total or 0,
            "peso": peso_total or 0,
            "percentual_medio": percentual_medio,
        })
    return ranking
