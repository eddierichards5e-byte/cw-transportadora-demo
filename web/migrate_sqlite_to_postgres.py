"""Migra um banco SQLite existente para PostgreSQL.

Uso:
  CW_SQLITE_PATH=/caminho/cw_transportadora.db CW_DATABASE_URL=postgresql://... python migrate_sqlite_to_postgres.py
"""
from __future__ import annotations
import os, sqlite3
from pathlib import Path
import psycopg

ROOT = Path(__file__).resolve().parent
SCHEMA = ROOT / "migrations" / "001_postgres_schema.sql"
TABLES = ["manifestos","clientes","notas","caminhoes","viagens","viagem_notas","funcionarios","folha_funcionarios","operacoes_sp","contas","abastecimentos","manutencoes","usuarios","permissoes_usuario","auditoria","sync_log","sync_estado"]
IDENTITY_TABLES = [t for t in TABLES if t != "sync_estado"]

def main():
    src = Path(os.getenv("CW_SQLITE_PATH", ""))
    dsn = os.getenv("CW_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not src.exists(): raise SystemExit("CW_SQLITE_PATH não aponta para um banco SQLite existente.")
    if not dsn: raise SystemExit("Defina CW_DATABASE_URL ou DATABASE_URL.")
    s = sqlite3.connect(str(src)); s.row_factory = sqlite3.Row
    with psycopg.connect(dsn) as p:
        with p.cursor() as c:
            c.execute(SCHEMA.read_text(encoding="utf-8"))
            for table in TABLES:
                cols = [r[1] for r in s.execute(f"PRAGMA table_info({table})").fetchall()]
                if not cols: continue
                rows = s.execute(f"SELECT * FROM {table}").fetchall()
                if not rows: continue
                quoted = ",".join('"'+x+'"' for x in cols)
                placeholders = ",".join(["%s"] * len(cols))
                sql = f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
                for row in rows: c.execute(sql, tuple(row))
                print(f"{table}: {len(rows)} registros")
            # Reposiciona as identidades para nunca colidir com IDs importados.
            for table in IDENTITY_TABLES:
                c.execute(f'SELECT COALESCE(MAX(id), 0) + 1 FROM "{table}"')
                nxt = int(c.fetchone()[0])
                c.execute(f'ALTER TABLE "{table}" ALTER COLUMN id RESTART WITH {nxt}')
        p.commit()
    s.close(); print("Migração concluída.")

if __name__ == "__main__": main()
