"""Cadastro e consulta de caminhoes da frota."""

import sqlite3
from typing import Optional

from utils.logger import get_logger
from ._conexao import conectar, registrar_sync, novo_id_global

logger = get_logger(__name__)


def listar_caminhoes(conn: Optional[sqlite3.Connection] = None):
    """
    Args:
        conn: conexão opcional já aberta (ver `dados_dashboard`).
    """
    conexao_propria = conn is None
    if conexao_propria:
        conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, placa, modelo, motorista, capacidade_kg, media_km_l, COALESCE(status, 'ATIVO')
        FROM caminhoes
        ORDER BY modelo
    """)

    dados = cursor.fetchall()
    if conexao_propria:
        conn.close()

    return dados


def apagar_todos_caminhoes():
    """Remove todos os caminhões da tabela."""
    try:
        conn = conectar()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM caminhoes")
        conn.commit()
        conn.close()

        logger.info("Todos os caminhões foram apagados")
        return True

    except Exception as erro:
        logger.error(f"Erro ao apagar caminhões: {erro}")
        return False


def criar_caminhoes_padrao():

    conn = conectar()
    cursor = conn.cursor()

    caminhoes = [
        ("Renault Master", "Renault Master", "Motorista Master", 1500, 9),
        ("3/4 Branco", "Caminhão 3/4 Branco", "Motorista Branco", 3500, 7),
        ("3/4 Preto", "Caminhão 3/4 Preto", "Motorista Preto", 3500, 7),
        ("Toco", "Caminhão Toco", "Motorista Toco", 6000, 5),
    ]

    for placa, modelo, motorista, capacidade, media in caminhoes:
        cursor.execute("SELECT id FROM caminhoes WHERE placa = ?", (placa,))
        existe = cursor.fetchone()

        if not existe:
            cursor.execute("""
                INSERT INTO caminhoes
                (id, placa, modelo, motorista, capacidade_kg, media_km_l)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (novo_id_global(), placa, modelo, motorista, capacidade, media))

            registrar_sync(cursor, "caminhoes", cursor.lastrowid)

    conn.commit()
    conn.close()


def cadastrar_caminhao(placa, modelo, motorista, capacidade_kg, media_km_l):

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO caminhoes (
            id, placa,
            modelo,
            motorista,
            capacidade_kg,
            media_km_l
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        novo_id_global(),
        placa,
        modelo,
        motorista,
        capacidade_kg,
        media_km_l
    ))

    registrar_sync(cursor, "caminhoes", cursor.lastrowid)

    conn.commit()
    conn.close()




def excluir_caminhao(caminhao_id):
    """Exclui veículo mantendo histórico e bloqueando apenas operações ativas.

    Viagens históricas não impedem a exclusão. O vínculo é removido antes de
    apagar o cadastro do veículo, preservando a viagem.
    """
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM caminhoes WHERE id = ?", (caminhao_id,))
        if not cursor.fetchone():
            raise ValueError("Veículo não encontrado.")

        cursor.execute("""
            SELECT id, status FROM viagens
            WHERE caminhao_id = ?
        """, (caminhao_id,))
        viagens = cursor.fetchall()
        ativos = []
        for vid, status in viagens:
            st = str(status or '').strip().lower()
            # Somente estados inequivocamente operacionais bloqueiam exclusão.
            if st in {
                'em viagem', 'em andamento', 'iniciada', 'iniciado',
                'planejada', 'planejado', 'aguardando saída', 'aguardando saida'
            }:
                ativos.append(int(vid))
        if ativos:
            raise ValueError(
                f"Este veículo possui {len(ativos)} viagem(ns) em andamento. "
                "Finalize ou cancele a operação antes de excluir o veículo."
            )

        # Histórico permanece intacto; apenas perde a referência ao veículo.
        cursor.execute("UPDATE viagens SET caminhao_id = NULL WHERE caminhao_id = ?", (caminhao_id,))
        registrar_sync(cursor, "caminhoes", caminhao_id, "DELETE")
        cursor.execute("DELETE FROM caminhoes WHERE id = ?", (caminhao_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def alterar_status_caminhao(caminhao_id, novo_status):
    """Atualiza o status operacional do veículo de forma transacional."""
    from domain.frota import normalizar_status

    status = normalizar_status(novo_status).value
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, status FROM caminhoes WHERE id = ?", (caminhao_id,))
        atual = cursor.fetchone()
        if not atual:
            raise ValueError("Veículo não encontrado.")

        if status != "ATIVO":
            cursor.execute("""
                SELECT COUNT(*) FROM viagens
                WHERE caminhao_id = ?
                  AND lower(COALESCE(status,'')) IN
                      ('em viagem','em rota','em trânsito','em transito','iniciada','iniciado','em andamento','planejada','planejado','aguardando saída','aguardando saida')
            """, (caminhao_id,))
            if int(cursor.fetchone()[0] or 0) > 0:
                raise ValueError("Não é possível colocar o veículo como manutenção/inativo enquanto ele possui uma viagem operacional ativa.")

        cursor.execute("UPDATE caminhoes SET status = ? WHERE id = ?", (status, caminhao_id))
        registrar_sync(cursor, "caminhoes", caminhao_id)
        conn.commit()
        return status
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
