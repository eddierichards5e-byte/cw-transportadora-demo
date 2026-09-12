"""Consultas e cadastro de clientes."""

import sqlite3
from typing import Optional

from utils.logger import get_logger
from ._conexao import conectar, registrar_sync, novo_id_global

logger = get_logger(__name__)


def buscar_cliente_por_cnpj(cnpj, conn: Optional[sqlite3.Connection] = None):
    """
    Args:
        conn: conexão opcional já aberta, reaproveitada por `obter_ou_criar_cliente`
            e `salvar_nota` para evitar abrir várias conexões na mesma operação.
    """
    conexao_propria = conn is None
    if conexao_propria:
        conn = conectar()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM clientes WHERE cnpj = ?",
        (cnpj,)
    )

    resultado = cursor.fetchone()
    if conexao_propria:
        conn.close()

    if resultado:
        return resultado[0]

    return None


def criar_cliente(nome, cnpj, cidade="", uf="", conn: Optional[sqlite3.Connection] = None):
    """
    Args:
        conn: conexão opcional já aberta (ver `buscar_cliente_por_cnpj`).
    """
    conexao_propria = conn is None
    if conexao_propria:
        conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO clientes
        (id, nome, cnpj, cidade, uf)
        VALUES (?, ?, ?, ?, ?)
    """, (novo_id_global(), nome, cnpj, cidade, uf))

    cliente_id = cursor.lastrowid
    registrar_sync(cursor, "clientes", cliente_id)

    conn.commit()
    if conexao_propria:
        conn.close()

    return cliente_id


def obter_ou_criar_cliente(nome, cnpj, cidade="", uf="", conn: Optional[sqlite3.Connection] = None):
    """
    Args:
        conn: conexão opcional já aberta (ver `buscar_cliente_por_cnpj`).
    """
    if not cnpj:
        cnpj = nome

    cliente_id = buscar_cliente_por_cnpj(cnpj, conn=conn)

    if cliente_id:
        return cliente_id

    return criar_cliente(nome, cnpj, cidade, uf, conn=conn)


def buscar_clientes_por_nome(termo_busca: str):
    """
    Busca clientes de forma inteligente (ERP-style), com tolerância a schema antigo.
    
    Implementa busca inteligente estilo ERP:
    - Ignora maiúsculas/minúsculas
    - Ignora acentos
    - Aceita pesquisa parcial
    - Busca em múltiplos campos simultaneamente (nome, cnpj, cpf, telefone, cidade, código)
    
    Args:
        termo_busca: Termo para busca (pode ser parcial)
        
    Returns:
        Lista de tuplas (id, nome, cnpj, cidade, uf)
    """
    import re
    import unicodedata

    termo_busca = (termo_busca or "").strip()
    if not termo_busca:
        return []

    def normalizar_texto(valor: str) -> str:
        """Converte texto para forma comparável, sem acentos e sem caixa."""
        texto = unicodedata.normalize("NFKD", str(valor or ""))
        texto = "".join(char for char in texto if not unicodedata.combining(char))
        return " ".join(texto.casefold().split())

    def so_digitos(valor: str) -> str:
        return re.sub(r"\D", "", str(valor or ""))

    termo_norm = normalizar_texto(termo_busca)
    termo_like = f"%{termo_norm}%"
    termo_digits = so_digitos(termo_busca)
    termo_digits_like = f"%{termo_digits}%" if termo_digits else None

    conn = conectar()
    cursor = conn.cursor()

    # Funções utilitárias no SQLite (evita duplicação no Python e permite LIKE)
    if hasattr(conn, "create_function"):
        conn.create_function("NORMALIZE", 1, normalizar_texto)
        conn.create_function("DIGITS", 1, so_digitos)

    # Detectar colunas existentes para não quebrar em bases antigas
    if hasattr(conn, "create_function"):
        cursor.execute("PRAGMA table_info(clientes)")
        cols = {row[1] for row in cursor.fetchall()}
    else:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s", ("clientes",))
        cols = {row[0] for row in cursor.fetchall()}

    # Campos candidatos (se existirem)
    text_fields = [f for f in ("nome", "razao_social", "fantasia", "cidade", "uf", "codigo") if f in cols]
    doc_fields = [f for f in ("cnpj", "cpf", "telefone") if f in cols]

    predicates = []
    params = []

    # Texto geral: normalizado (casefold + sem acento)
    for field in (*text_fields, *doc_fields):
        predicates.append(f"NORMALIZE(COALESCE({field}, '')) LIKE ?")
        params.append(termo_like)

    # Pesquisa por dígitos (CPF/CNPJ/telefone), ignorando máscara
    if termo_digits_like:
        for field in doc_fields:
            predicates.append(f"DIGITS(COALESCE({field}, '')) LIKE ?")
            params.append(termo_digits_like)
        # Também permitir busca por ID/código numérico quando o usuário digita só números
        predicates.append("CAST(id AS TEXT) LIKE ?")
        params.append(termo_digits_like)

    if not predicates:
        conn.close()
        return []

    # Limite maior para não "sumir" cliente (o chamador pode paginar/filtrar depois)
    limit = 200
    sql = f"""
        SELECT id, nome, cnpj, cidade, uf
        FROM clientes
        WHERE {" OR ".join(predicates)}
        ORDER BY nome
        LIMIT ?
    """

    cursor.execute(sql, (*params, limit))
    dados = cursor.fetchall()
    conn.close()
    return dados

def atualizar_prioridade_cliente(cliente_id: int, prioridade: str):
    """Atualiza a prioridade operacional de um cliente e agenda sincronização."""
    prioridade = (prioridade or "normal").strip().lower()
    if prioridade not in {"urgente", "prioritario", "normal"}:
        raise ValueError("Prioridade inválida. Use urgente, prioritario ou normal.")

    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE clientes SET prioridade = ? WHERE id = ?",
            (prioridade, cliente_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Cliente não encontrado.")
        registrar_sync(cursor, "clientes", cliente_id)
        conn.commit()
    finally:
        conn.close()
    return prioridade


def obter_prioridade_cliente(cliente_id: int) -> str:
    """Retorna a prioridade persistida do cliente."""
    conn = conectar()
    try:
        row = conn.execute(
            "SELECT COALESCE(prioridade, 'normal') FROM clientes WHERE id = ?",
            (cliente_id,),
        ).fetchone()
        return str(row[0] or "normal") if row else "normal"
    finally:
        conn.close()

