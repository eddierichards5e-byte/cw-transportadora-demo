"""Compatibilidade e utilitários de sincronização do CW V54."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import sqlite3

from config.settings import settings
from utils.database._conexao import conectar, registrar_sync, TABELAS_SYNC
from services.sync_service import sync_service

DB_LOCAL = str(settings.db_path)


def conectar_local():
    return sqlite3.connect(DB_LOCAL, timeout=30, check_same_thread=False)


def preparar_sync_log(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tabela TEXT, registro_id TEXT,
            operacao TEXT DEFAULT 'UPSERT', status TEXT DEFAULT 'PENDENTE',
            tentativas INTEGER DEFAULT 0, erro TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP, sincronizado_em TEXT
        )
    """)


def buscar_registros_locais(cursor, tabela, referencias):
    """Busca registros por sync_id e/ou id, mantendo compatibilidade com testes legados."""
    if not referencias:
        return []
    refs = [str(x) for x in referencias]
    placeholders = ",".join("?" for _ in refs)
    cursor.execute(f"SELECT * FROM {tabela} WHERE sync_id IN ({placeholders}) OR CAST(id AS TEXT) IN ({placeholders})", refs + refs)
    return [dict(row) if isinstance(row, sqlite3.Row) else {d[0]: v for d, v in zip(cursor.description, row)} for row in cursor.fetchall()]


def _timestamp_mais_recente(atual, remoto):
    if not remoto:
        return False
    if not atual:
        return True
    try:
        return datetime.fromisoformat(str(remoto).replace("Z", "+00:00")) > datetime.fromisoformat(str(atual).replace("Z", "+00:00"))
    except Exception:
        return str(remoto) > str(atual)


def reparar_e_enfileirar_fila():
    """Garante que todo registro local ainda não sincronizado possua uma pendência."""
    conn = conectar_local()
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        preparar_sync_log(cur)
        total = 0
        for tabela in TABELAS_SYNC:
            try:
                cur.execute(f"SELECT id FROM {tabela} WHERE COALESCE(sincronizado,0)=0 OR sync_id IS NULL OR atualizado_em IS NULL")
            except sqlite3.Error:
                continue
            for (rid,) in cur.fetchall():
                before = cur.execute("SELECT 1 FROM sync_log WHERE tabela=? AND registro_id=? AND status='PENDENTE' LIMIT 1", (tabela, str(rid))).fetchone()
                if not before:
                    registrar_sync(cur, tabela, rid)
                    total += 1
        conn.commit()
        return total
    finally:
        conn.close()


def sincronizar():
    return sync_service.executar(reparar_fila=True)


def contar_pendencias_sync():
    return sync_service.contar_pendencias()
