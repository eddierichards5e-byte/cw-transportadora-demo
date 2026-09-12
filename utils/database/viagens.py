"""Ciclo de vida das viagens: criacao, finalizacao, consulta, exclusao."""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

from utils.logger import get_logger
from ._conexao import conectar, get_connection, registrar_sync, novo_id_global
from domain.viagens import validar_transicao_viagem, validar_transicao_nota
from domain.frota import validar_uso_em_viagem
from domain.capacidade import validar_capacidade

logger = get_logger(__name__)


def criar_viagem(caminhao_id, notas_ids, data_saida, motorista):

    if not notas_ids:
        raise ValueError("Nenhuma nota selecionada.")

    placeholders = ",".join(["?"] * len(notas_ids))

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT status, COALESCE(capacidade_kg,0), COALESCE(capacidade_m3,0), tipos_carga_permitidos FROM caminhoes WHERE id = ?", (caminhao_id,))
        caminhao = cursor.fetchone()
        if not caminhao:
            raise ValueError("Veículo não encontrado.")
        validar_uso_em_viagem(caminhao[0] or "ATIVO")

        # Revalida tudo dentro da mesma transação. Isso evita que duas ações
        # simultâneas consigam colocar a mesma nota em viagens diferentes.
        notas_ids = list(dict.fromkeys(int(n) for n in notas_ids))
        if not notas_ids:
            raise ValueError("Nenhuma nota selecionada.")
        placeholders = ",".join(["?"] * len(notas_ids))
        cursor.execute(f"""
            SELECT id, status, COALESCE(peso,0), COALESCE(cubagem_m3,0), tipo_carga
            FROM notas
            WHERE id IN ({placeholders})
        """, notas_ids)
        encontrados = {int(r[0]): r[1:] for r in cursor.fetchall()}
        faltantes = [n for n in notas_ids if n not in encontrados]
        if faltantes:
            raise ValueError(f"Nota(s) não encontrada(s): {', '.join(map(str, faltantes))}.")
        for nota_id in notas_ids:
            status, _, _, _ = encontrados[nota_id]
            validar_transicao_nota(status, "Em viagem")

        # Uma nota só pode ter um vínculo ativo. Registros históricos marcados
        # como deletados não bloqueiam uma nova viagem.
        cursor.execute(f"""
            SELECT nota_id, viagem_id FROM viagem_notas
            WHERE nota_id IN ({placeholders}) AND COALESCE(deletado,0)=0
        """, notas_ids)
        ocupadas = cursor.fetchall()
        if ocupadas:
            detalhes = ", ".join(f"nota #{n} (viagem #{v})" for n, v in ocupadas)
            raise ValueError(f"A(s) nota(s) já pertence(m) a uma viagem ativa: {detalhes}.")

        cursor.execute(f"""
            SELECT
                COALESCE(SUM(peso), 0),
                COALESCE(SUM(cubagem_m3), 0),
                COALESCE(SUM(valor_frete), 0)
            FROM notas
            WHERE id IN ({placeholders})
        """, notas_ids)

        peso_total, cubagem_total, frete_total = cursor.fetchone()
        tipos_permitidos = {v.strip().lower() for v in str(caminhao[3] or "").split(",") if v.strip()}
        tipos_carga = {str(encontrados[n][3] or "").strip().lower() for n in notas_ids if str(encontrados[n][3] or "").strip()}
        validar_capacidade(
            peso_total=peso_total, capacidade_kg=caminhao[1],
            cubagem_total=cubagem_total, capacidade_m3=caminhao[2],
        )
        if tipos_permitidos and tipos_carga - tipos_permitidos:
            raise ValueError("A carga contém tipo(s) não permitido(s) para este veículo.")

        cursor.execute("""
            INSERT INTO viagens (
                id, caminhao_id,
                data_saida,
                motorista,
                status,
                peso_total,
                frete_total,
                custo_total,
                lucro_total
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            novo_id_global(),
            caminhao_id,
            data_saida,
            motorista,
            "Em viagem",
            peso_total,
            frete_total,
            0,
            frete_total
        ))

        viagem_id = cursor.lastrowid
        registrar_sync(cursor, "viagens", viagem_id)

        for nota_id in notas_ids:
            cursor.execute("""
                INSERT INTO viagem_notas (id, viagem_id, nota_id)
                VALUES (?, ?, ?)
            """, (novo_id_global(), viagem_id, nota_id))

            viagem_nota_id = cursor.lastrowid
            registrar_sync(cursor, "viagem_notas", viagem_nota_id)

            cursor.execute("""
                UPDATE notas
                SET status = 'Em viagem'
                WHERE id = ?
            """, (nota_id,))

            registrar_sync(cursor, "notas", nota_id)

        conn.commit()

    return viagem_id


def alterar_status_viagem(viagem_id, novo_status):
    """Altera o status usando a máquina de estados do domínio."""
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT status FROM viagens WHERE id = ?", (viagem_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Viagem não encontrada.")
        validar_transicao_viagem(row[0], novo_status)
        alvo = str(novo_status).strip()
        aliases = {"em transito": "Em trânsito"}
        alvo = aliases.get(alvo.lower(), alvo)
        cursor.execute("UPDATE viagens SET status = ? WHERE id = ?", (alvo, viagem_id))
        registrar_sync(cursor, "viagens", viagem_id)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def apagar_viagem(viagem_id):
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, status FROM viagens WHERE id = ?", (viagem_id,))
        viagem = cursor.fetchone()
        if not viagem:
            raise ValueError("Viagem não encontrada.")
        if str(viagem[1] or '').strip().lower() in {"finalizada", "entregue", "encerrada"}:
            raise ValueError("Não é permitido excluir uma viagem já finalizada. Preserve o histórico de entrega.")

        cursor.execute("SELECT id, nota_id FROM viagem_notas WHERE viagem_id = ? AND COALESCE(deletado,0)=0", (viagem_id,))
        viagem_notas = cursor.fetchall()
        notas_ids = [nota_id for _, nota_id in viagem_notas]

        for viagem_nota_id, nota_id in viagem_notas:
            registrar_sync(cursor, "viagem_notas", viagem_nota_id, "DELETE")
            cursor.execute("UPDATE notas SET status = 'Disponível' WHERE id = ?", (nota_id,))
            registrar_sync(cursor, "notas", nota_id)

        # O histórico do vínculo fica representado pelo tombstone no sync_log/
        # nuvem, enquanto a relação local é removida para liberar a nota.
        cursor.execute("DELETE FROM viagem_notas WHERE viagem_id = ?", (viagem_id,))
        registrar_sync(cursor, "viagens", viagem_id, "DELETE")
        cursor.execute("DELETE FROM viagens WHERE id = ?", (viagem_id,))
        conn.commit()
        return len(notas_ids)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def listar_viagens():

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            viagens.id,
            viagens.data_saida,
            caminhoes.modelo,
            caminhoes.placa,
            viagens.motorista,
            viagens.status,
            viagens.peso_total,
            viagens.frete_total,
            COUNT(viagem_notas.nota_id) as total_notas
        FROM viagens
        LEFT JOIN caminhoes ON caminhoes.id = viagens.caminhao_id
        LEFT JOIN viagem_notas ON viagem_notas.viagem_id = viagens.id AND COALESCE(viagem_notas.deletado,0)=0
        GROUP BY viagens.id
        ORDER BY viagens.id DESC
    """)

    dados = cursor.fetchall()
    conn.close()

    return dados


def listar_notas_da_viagem(viagem_id):

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            notas.id,
            notas.numero_cte,
            remetente.nome,
            destinatario.nome,
            notas.origem,
            notas.destino,
            notas.valor_frete,
            notas.peso,
            notas.status
        FROM viagem_notas
        INNER JOIN notas ON notas.id = viagem_notas.nota_id
        LEFT JOIN clientes remetente ON remetente.id = notas.remetente_id
        LEFT JOIN clientes destinatario ON destinatario.id = notas.destinatario_id
        WHERE viagem_notas.viagem_id = ? AND COALESCE(viagem_notas.deletado,0)=0
        ORDER BY notas.id DESC
    """, (viagem_id,))

    dados = cursor.fetchall()
    conn.close()

    return dados


def finalizar_viagem(viagem_id, data_retorno):
    """Encerra a viagem e move suas notas para ``Entregue``.

    A etapa ``Entregue -> Finalizada`` das notas ocorre separadamente,
    após a confirmação administrativa da entrega.
    """
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT status FROM viagens WHERE id = ?", (viagem_id,))
        viagem = cursor.fetchone()
        if not viagem:
            raise ValueError("Viagem não encontrada.")
        status_atual = str(viagem[0] or '').strip().lower()
        if status_atual == "finalizada":
            return True
        if status_atual not in {"em viagem", "em rota", "em transito", "em trânsito"}:
            raise ValueError(f"A viagem não pode ser finalizada no status atual: {viagem[0]}")

        cursor.execute("""
            SELECT nota_id FROM viagem_notas
            WHERE viagem_id = ? AND COALESCE(deletado,0)=0
        """, (viagem_id,))
        nota_ids = [int(r[0]) for r in cursor.fetchall()]

        for nota_id in nota_ids:
            cursor.execute("SELECT status FROM notas WHERE id = ?", (nota_id,))
            nota = cursor.fetchone()
            if nota:
                validar_transicao_nota(nota[0], "Entregue")

        cursor.execute("""
            UPDATE viagens
            SET status = 'Finalizada',
                data_retorno = ?
            WHERE id = ?
        """, (data_retorno, viagem_id))

        for nota_id in nota_ids:
            cursor.execute("UPDATE notas SET status = 'Entregue' WHERE id = ?", (nota_id,))
            registrar_sync(cursor, "notas", nota_id)

        registrar_sync(cursor, "viagens", viagem_id)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finalizar_nota_entregue(nota_id):
    """Confirma administrativamente uma nota entregue como finalizada."""
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, status FROM notas WHERE id = ?", (nota_id,))
        nota = cursor.fetchone()
        if not nota:
            raise ValueError("Nota não encontrada.")
        validar_transicao_nota(nota[1], "Finalizada")
        cursor.execute("UPDATE notas SET status = 'Finalizada' WHERE id = ?", (nota_id,))
        registrar_sync(cursor, "notas", nota_id)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finalizar_notas_entregues(notas_ids):
    """Finaliza várias notas entregues em uma única transação."""
    ids = list(dict.fromkeys(int(n) for n in (notas_ids or [])))
    if not ids:
        raise ValueError("Nenhuma nota selecionada.")
    placeholders = ",".join("?" for _ in ids)
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT id, status FROM notas WHERE id IN ({placeholders})", ids)
        encontrados = {int(r[0]): r[1] for r in cursor.fetchall()}
        faltantes = [n for n in ids if n not in encontrados]
        if faltantes:
            raise ValueError(f"Nota(s) não encontrada(s): {', '.join(map(str, faltantes))}.")
        for nota_id in ids:
            validar_transicao_nota(encontrados[nota_id], "Finalizada")
        cursor.execute(f"UPDATE notas SET status = 'Finalizada' WHERE id IN ({placeholders})", ids)
        for nota_id in ids:
            registrar_sync(cursor, "notas", nota_id)
        conn.commit()
        return len(ids)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def buscar_detalhes_viagem(viagem_id):

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            viagens.id,
            viagens.data_saida,
            viagens.data_retorno,
            viagens.motorista,
            viagens.status,
            viagens.peso_total,
            viagens.frete_total,
            caminhoes.modelo,
            caminhoes.placa,
            caminhoes.capacidade_kg
        FROM viagens
        LEFT JOIN caminhoes ON caminhoes.id = viagens.caminhao_id
        WHERE viagens.id = ?
    """, (viagem_id,))

    dados = cursor.fetchone()
    conn.close()

    return dados


