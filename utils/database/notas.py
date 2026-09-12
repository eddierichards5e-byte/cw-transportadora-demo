"""Notas fiscais e manifestos: importacao, listagem, status."""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

from utils.logger import get_logger
from ._conexao import conectar, get_connection, registrar_sync, novo_id_global
from .clientes import obter_ou_criar_cliente
from utils.date_utils import sql_date_month, sql_date_year

logger = get_logger(__name__)


def salvar_nota(nota):
    """
    Salva uma nota, criando remetente/destinatário se necessário.

    Antes: abria até 5 conexões SQLite separadas na mesma operação
    (nota_existe, buscar_cliente_por_cnpj x2, criar_cliente x{0,2}, insert).
    Agora tudo roda em uma única conexão/transação.
    """
    chave_nfe = nota.get("chave_nfe") or nota.get("numero_cte")

    with get_connection() as conn:
        if nota_existe(chave_nfe, conn=conn):
            return False

        remetente_id = obter_ou_criar_cliente(
            nota.get("remetente_nome", ""),
            nota.get("remetente_cnpj", ""),
            nota.get("origem", ""),
            nota.get("uf_origem", ""),
            conn=conn,
        )

        destinatario_id = obter_ou_criar_cliente(
            nota.get("destinatario_nome", ""),
            nota.get("destinatario_cnpj", ""),
            nota.get("destino", ""),
            nota.get("uf_destino", ""),
            conn=conn,
        )

        cursor = conn.cursor()
        # Clientes criados automaticamente pela nota também precisam entrar na
        # fila de sincronização; a função pública de cadastro já faz isso, mas
        # aqui os clientes podem ser criados dentro da mesma transação.
        for cliente_id in (remetente_id, destinatario_id):
            if cliente_id:
                registrar_sync(cursor, "clientes", cliente_id)
        cursor.execute("""
            INSERT INTO notas (
                id, manifesto_id,
                chave_nfe,
                numero_cte,
                remetente_id,
                destinatario_id,
                valor_mercadoria,
                valor_frete,
                peso,
                origem,
                destino,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            novo_id_global(),
            nota.get("manifesto_id"),
            chave_nfe,
            nota.get("numero_cte", ""),
            remetente_id,
            destinatario_id,
            nota.get("valor_mercadoria", 0),
            nota.get("valor_frete", 0),
            nota.get("peso", 0),
            nota.get("origem", ""),
            nota.get("destino", ""),
            nota.get("status", "Disponível")
        ))

        nota_id = cursor.lastrowid
        registrar_sync(cursor, "notas", nota_id)
        conn.commit()

    return True


def listar_notas():

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            notas.id,
            notas.chave_nfe,
            notas.numero_cte,
            remetente.nome,
            destinatario.nome,
            notas.origem,
            notas.destino,
            notas.valor_frete,
            notas.peso,
            notas.status
        FROM notas
        LEFT JOIN clientes remetente
            ON remetente.id = notas.remetente_id
        LEFT JOIN clientes destinatario
            ON destinatario.id = notas.destinatario_id
        ORDER BY notas.id DESC
    """)

    dados = cursor.fetchall()
    conn.close()

    return dados


def nota_existe(chave_nfe, conn: Optional[sqlite3.Connection] = None):
    """
    Args:
        conn: conexão opcional já aberta (ver `buscar_cliente_por_cnpj`).
    """
    conexao_propria = conn is None
    if conexao_propria:
        conn = conectar()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM notas WHERE chave_nfe = ?",
        (chave_nfe,)
    )

    resultado = cursor.fetchone()
    if conexao_propria:
        conn.close()

    return resultado is not None


def criar_manifesto(nome_arquivo):

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO manifestos (id, nome_arquivo)
        VALUES (?, ?)
    """, (novo_id_global(), nome_arquivo))

    manifesto_id = cursor.lastrowid
    registrar_sync(cursor, "manifestos", manifesto_id)

    conn.commit()
    conn.close()

    return manifesto_id


def listar_manifestos(tipo_periodo="Geral", mes=None, ano=None):

    conn = conectar()
    cursor = conn.cursor()

    filtro = ""
    params = []

    if tipo_periodo == "Mês" and mes and ano:
        mes = str(mes).zfill(2)
        ano = str(ano)
        filtro = "WHERE CASE WHEN instr(COALESCE(manifestos.data_importacao,''), '/') > 0 THEN substr(COALESCE(manifestos.data_importacao,''), 4, 2) ELSE substr(COALESCE(manifestos.data_importacao,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(manifestos.data_importacao,''), '/') > 0 THEN substr(COALESCE(manifestos.data_importacao,''), 7, 4) ELSE substr(COALESCE(manifestos.data_importacao,''), 1, 4) END = ?"
        params = [mes, ano]

    elif tipo_periodo == "Ano" and ano:
        ano = str(ano)
        filtro = "WHERE CASE WHEN instr(COALESCE(manifestos.data_importacao,''), '/') > 0 THEN substr(COALESCE(manifestos.data_importacao,''), 7, 4) ELSE substr(COALESCE(manifestos.data_importacao,''), 1, 4) END = ?"
        params = [ano]

    cursor.execute(f"""
        SELECT
            manifestos.id,
            manifestos.nome_arquivo,
            manifestos.data_importacao,
            COUNT(notas.id) as total_notas,
            COALESCE(SUM(notas.valor_mercadoria), 0) as valor_total_notas,
            COALESCE(SUM(notas.valor_frete), 0) as frete_total,
            COALESCE(SUM(notas.peso), 0) as peso_total
        FROM manifestos
        LEFT JOIN notas ON notas.manifesto_id = manifestos.id
        {filtro}
        GROUP BY manifestos.id
        ORDER BY manifestos.id DESC
    """, params)

    dados = cursor.fetchall()
    conn.close()

    return dados


def listar_notas_por_manifesto(manifesto_id):

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            notas.id,
            notas.chave_nfe,
            notas.numero_cte,
            remetente.nome,
            destinatario.nome,
            notas.origem,
            notas.destino,
            notas.valor_mercadoria,
            notas.valor_frete,
            notas.peso,
            notas.status
        FROM notas
        LEFT JOIN clientes remetente
            ON remetente.id = notas.remetente_id
        LEFT JOIN clientes destinatario
            ON destinatario.id = notas.destinatario_id
        WHERE notas.manifesto_id = ?
        ORDER BY notas.id DESC
    """, (manifesto_id,))

    dados = cursor.fetchall()
    conn.close()

    return dados


def apagar_manifesto(manifesto_id):
    conn = conectar()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT id, nome_arquivo FROM manifestos WHERE id = ?",
            (manifesto_id,)
        )

        manifesto = cursor.fetchone()

        if not manifesto:
            raise Exception("Manifesto não encontrado.")

        cursor.execute(
            "SELECT id FROM notas WHERE manifesto_id = ?",
            (manifesto_id,)
        )

        notas_ids = [linha[0] for linha in cursor.fetchall()]

        for nota_id in notas_ids:
            registrar_sync(cursor, "notas", nota_id, "DELETE")

        registrar_sync(cursor, "manifestos", manifesto_id, "DELETE")

        cursor.execute(
            """
            DELETE FROM viagem_notas
            WHERE nota_id IN (
                SELECT id
                FROM notas
                WHERE manifesto_id = ?
            )
            """,
            (manifesto_id,)
        )

        cursor.execute(
            "DELETE FROM notas WHERE manifesto_id = ?",
            (manifesto_id,)
        )

        cursor.execute(
            "DELETE FROM manifestos WHERE id = ?",
            (manifesto_id,)
        )

        conn.commit()

        return True

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def listar_notas_por_cliente(
    cliente_id: int,
    apenas_disponiveis: bool = True,
    excluir_vinculadas: bool = True,
    manifesto_id: Optional[int] = None,
    termo: str = ""
):
    """
    Lista notas filtradas por cliente.
    
    Args:
        cliente_id: ID do cliente (pode ser remetente ou destinatário)
        apenas_disponiveis: Se True, retorna apenas notas com status 'Disponível'
        excluir_vinculadas: Se True, exclui notas já vinculadas a alguma viagem
        
    Returns:
        Lista de tuplas com dados das notas
    """
    conn = conectar()
    cursor = conn.cursor()
    
    query = """
        SELECT
            notas.id,
            notas.numero_cte,
            notas.chave_nfe,
            CASE 
                WHEN notas.destinatario_id = ? THEN destinatario.nome
                WHEN notas.remetente_id = ? THEN remetente.nome
                ELSE COALESCE(destinatario.nome, remetente.nome)
            END as cliente_nome,
            CASE 
                WHEN notas.destinatario_id = ? THEN notas.destino
                WHEN notas.remetente_id = ? THEN notas.origem
                ELSE COALESCE(notas.destino, notas.origem)
            END as cidade,
            notas.peso,
            notas.valor_frete,
            manifestos.data_importacao as data,
            COALESCE(notas.status, 'Disponível') as status
        FROM notas
        LEFT JOIN clientes destinatario
            ON destinatario.id = notas.destinatario_id
        LEFT JOIN clientes remetente
            ON remetente.id = notas.remetente_id
        LEFT JOIN manifestos
            ON manifestos.id = notas.manifesto_id
        WHERE notas.destinatario_id = ? OR notas.remetente_id = ?
    """
    
    params = [cliente_id, cliente_id, cliente_id, cliente_id, cliente_id, cliente_id]
    
    if apenas_disponiveis:
        query += " AND notas.status = 'Disponível'"
    
    if excluir_vinculadas:
        query += """
            AND notas.id NOT IN (
                SELECT nota_id
                FROM viagem_notas
            )
        """

    if manifesto_id is not None:
        query += " AND notas.manifesto_id = ?"
        params.append(manifesto_id)

    termo = (termo or "").strip()
    if termo:
        query += """
            AND (
                COALESCE(notas.numero_cte, '') LIKE ?
                OR COALESCE(notas.chave_nfe, '') LIKE ?
                OR COALESCE(remetente.nome, '') LIKE ?
                OR COALESCE(destinatario.nome, '') LIKE ?
            )
        """
        busca = f"%{termo}%"
        params.extend([busca, busca, busca, busca])

    query += " ORDER BY notas.id DESC"
    
    cursor.execute(query, params)
    dados = cursor.fetchall()
    conn.close()
    
    return dados



def listar_notas_planejamento(termo: str = "", prioridade: str | None = None, cliente_id: int | None = None):
    """Lista notas disponíveis agrupáveis por cliente para a Central de Montagem.

    O cliente operacional é o destinatário quando disponível; quando a nota não
    possui destinatário, usa o remetente como fallback. A prioridade vem do
    cadastro persistente do cliente e não interfere na seleção da nota.
    """
    conn = conectar()
    try:
        query = """
            SELECT
                n.id,
                COALESCE(d.id, r.id) AS cliente_id,
                COALESCE(d.nome, r.nome, 'Cliente não identificado') AS cliente_nome,
                COALESCE(d.cidade, n.destino, r.cidade, n.origem, '') AS cliente_cidade,
                n.chave_nfe,
                n.numero_cte,
                COALESCE(n.peso, 0) AS peso,
                COALESCE(n.valor_frete, 0) AS frete,
                COALESCE(n.origem, '') AS origem,
                COALESCE(n.destino, '') AS destino,
                COALESCE(c.prioridade, 'normal') AS prioridade,
                COALESCE(n.status, 'Disponível') AS status
            FROM notas n
            LEFT JOIN clientes d ON d.id = n.destinatario_id
            LEFT JOIN clientes r ON r.id = n.remetente_id
            LEFT JOIN clientes c ON c.id = COALESCE(d.id, r.id)
            WHERE lower(COALESCE(n.status, 'Disponível')) IN ('disponível', 'disponivel')
              AND NOT EXISTS (
                    SELECT 1 FROM viagem_notas vn
                    WHERE vn.nota_id = n.id AND COALESCE(vn.deletado, 0) = 0
              )
        """
        params = []
        termo = (termo or "").strip()
        if termo:
            query += """
                AND (
                    COALESCE(n.chave_nfe, '') LIKE ?
                    OR COALESCE(n.numero_cte, '') LIKE ?
                    OR CAST(n.id AS TEXT) LIKE ?
                    OR COALESCE(d.nome, '') LIKE ?
                    OR COALESCE(r.nome, '') LIKE ?
                    OR COALESCE(d.cnpj, '') LIKE ?
                    OR COALESCE(r.cnpj, '') LIKE ?
                    OR COALESCE(n.destino, '') LIKE ?
                )
            """
            busca = f"%{termo}%"
            params.extend([busca] * 8)

        prioridade = (prioridade or "").strip().lower()
        if prioridade in {"urgente", "prioritario", "normal"}:
            query += " AND COALESCE(c.prioridade, 'normal') = ?"
            params.append(prioridade)

        if cliente_id is not None:
            query += " AND COALESCE(d.id, r.id) = ?"
            params.append(cliente_id)

        query += " ORDER BY CASE COALESCE(c.prioridade, 'normal') WHEN 'urgente' THEN 0 WHEN 'prioritario' THEN 1 ELSE 2 END, COALESCE(d.nome, r.nome, ''), n.id DESC"
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def listar_notas_disponiveis(termo: str = ""):
    """Lista apenas notas aptas para planejamento, com busca por NF/CT-e ou nome."""
    conn = conectar(); cursor = conn.cursor()
    try:
        query = """
            SELECT n.id, n.chave_nfe, n.numero_cte, r.nome, d.nome, n.origem, n.destino,
                   n.valor_frete, n.peso, n.status
            FROM notas n
            LEFT JOIN clientes r ON r.id = n.remetente_id
            LEFT JOIN clientes d ON d.id = n.destinatario_id
            WHERE lower(COALESCE(n.status,'Disponível')) IN ('disponível','disponivel')
              AND n.id NOT IN (SELECT nota_id FROM viagem_notas)
        """
        params=[]
        termo=(termo or '').strip()
        if termo:
            busca=f"%{termo}%"
            query += " AND (COALESCE(n.chave_nfe,'') LIKE ? OR COALESCE(n.numero_cte,'') LIKE ? OR CAST(n.id AS TEXT) LIKE ? OR COALESCE(r.nome,'') LIKE ? OR COALESCE(d.nome,'') LIKE ?)"
            params.extend([busca,busca,busca,busca,busca])
        query += " ORDER BY n.id DESC"
        cursor.execute(query,params)
        return cursor.fetchall()
    finally:
        conn.close()


def buscar_nota_para_leitura(codigo: str):
    """Localiza uma NF disponível a partir do texto recebido pelo leitor USB/HID.

    Leitores de código de barras USB normalmente funcionam como teclado e
    enviam a leitura seguida de Enter. Priorizamos correspondência exata da
    chave NF-e (44 dígitos), depois CT-e e ID interno.
    """
    codigo = (codigo or "").strip()
    if not codigo:
        return None
    import re
    digits = re.sub(r"\D", "", codigo)
    conn = conectar(); cur = conn.cursor()
    try:
        base = """
            SELECT n.id, n.chave_nfe, n.numero_cte, r.nome, d.nome,
                   n.origem, n.destino, n.valor_frete, n.peso, n.status
            FROM notas n
            LEFT JOIN clientes r ON r.id=n.remetente_id
            LEFT JOIN clientes d ON d.id=n.destinatario_id
            WHERE lower(COALESCE(n.status,'Disponível')) IN ('disponível','disponivel')
              AND NOT EXISTS (SELECT 1 FROM viagem_notas vn WHERE vn.nota_id=n.id AND COALESCE(vn.deletado,0)=0)
        """
        if digits:
            cur.execute(base + " AND REPLACE(REPLACE(REPLACE(COALESCE(n.chave_nfe,''),'.',''),'-',''),' ','')=?", (digits,))
            row = cur.fetchone()
            if row:
                return row
            cur.execute(base + " AND REPLACE(REPLACE(REPLACE(COALESCE(n.numero_cte,''),'.',''),'-',''),' ','')=?", (digits,))
            row = cur.fetchone()
            if row:
                return row
            if digits.isdigit():
                cur.execute(base + " AND n.id=?", (int(digits),))
                row = cur.fetchone()
                if row:
                    return row
        # Alguns equipamentos podem devolver o texto completo; ainda tentamos
        # uma correspondência exata sem normalização.
        cur.execute(base + " AND (COALESCE(n.chave_nfe,'')=? OR COALESCE(n.numero_cte,'')=?)", (codigo, codigo))
        return cur.fetchone()
    finally:
        conn.close()

def listar_notas_entregues(termo: str = ""):
    """Lista notas em viagem e já entregues para acompanhamento/histórico."""
    conn = conectar(); cursor = conn.cursor()
    try:
        query = """
            SELECT n.id, n.chave_nfe, n.numero_cte, r.nome, d.nome, n.origem, n.destino,
                   n.valor_frete, n.peso, n.status, v.id, v.data_retorno
            FROM notas n
            LEFT JOIN clientes r ON r.id = n.remetente_id
            LEFT JOIN clientes d ON d.id = n.destinatario_id
            LEFT JOIN viagem_notas vn ON vn.nota_id = n.id
            LEFT JOIN viagens v ON v.id = vn.viagem_id
            WHERE (lower(COALESCE(n.status,'')) LIKE '%viagem%'
                     OR lower(COALESCE(n.status,'')) LIKE '%entreg%'
                     OR lower(COALESCE(n.status,'')) LIKE '%finaliz%')
        """
        params=[]; termo=(termo or '').strip()
        if termo:
            busca=f"%{termo}%"
            query += " AND (COALESCE(n.chave_nfe,'') LIKE ? OR COALESCE(n.numero_cte,'') LIKE ? OR CAST(n.id AS TEXT) LIKE ? OR COALESCE(r.nome,'') LIKE ? OR COALESCE(d.nome,'') LIKE ?)"
            params.extend([busca,busca,busca,busca,busca])
        query += " ORDER BY COALESCE(v.data_retorno,'') DESC, n.id DESC"
        cursor.execute(query,params)
        return cursor.fetchall()
    finally:
        conn.close()

def finalizar_nota_entregue(nota_id):
    """Finaliza uma nota que já foi marcada como entregue."""
    conn = conectar(); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, status FROM notas WHERE id = ?", (nota_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Nota não encontrada.")
        status = str(row[1] or "").strip().lower()
        if "entreg" not in status:
            raise ValueError("A nota precisa estar com status Entregue para ser finalizada.")
        cursor.execute("UPDATE notas SET status = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?", ("Finalizada", nota_id))
        registrar_sync(cursor, "notas", nota_id)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finalizar_notas_entregues(notas_ids):
    """Finaliza em lote somente notas que estejam Entregues. Retorna a quantidade."""
    ids = []
    for valor in notas_ids or []:
        try:
            ids.append(int(valor))
        except (TypeError, ValueError):
            continue
    if not ids:
        return 0
    conn = conectar(); cursor = conn.cursor()
    try:
        placeholders = ",".join(["?"] * len(ids))
        cursor.execute(f"SELECT id, status FROM notas WHERE id IN ({placeholders})", ids)
        rows = cursor.fetchall()
        finalizados = 0
        for rid, status_raw in rows:
            status = str(status_raw or "").strip().lower()
            if "entreg" not in status:
                continue
            cursor.execute("UPDATE notas SET status = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?", ("Finalizada", rid))
            registrar_sync(cursor, "notas", rid)
            finalizados += 1
        conn.commit()
        return finalizados
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def calcular_resumo_notas(notas_ids: list, conn: Optional[sqlite3.Connection] = None):
    """
    Calcula resumo das notas selecionadas.
    
    Args:
        notas_ids: Lista de IDs das notas
        conn: conexão opcional já aberta (ver `dados_dashboard`).
        
    Returns:
        Dict com quantidade, peso_total, frete_total, volumes
    """
    if not notas_ids:
        return {
            "quantidade": 0,
            "peso_total": 0,
            "frete_total": 0,
            "volumes": 0
        }
    
    conexao_propria = conn is None
    if conexao_propria:
        conn = conectar()
    cursor = conn.cursor()
    
    placeholders = ",".join(["?"] * len(notas_ids))
    
    cursor.execute(f"""
        SELECT
            COUNT(*) as quantidade,
            COALESCE(SUM(peso), 0) as peso_total,
            COALESCE(SUM(valor_frete), 0) as frete_total
        FROM notas
        WHERE id IN ({placeholders})
    """, notas_ids)
    
    quantidade, peso_total, frete_total = cursor.fetchone()
    
    # Volumes é estimado como 1 volume por nota (pode ser ajustado no futuro)
    volumes = quantidade
    
    if conexao_propria:
        conn.close()
    
    return {
        "quantidade": quantidade or 0,
        "peso_total": peso_total or 0,
        "frete_total": frete_total or 0,
        "volumes": volumes or 0
    }


