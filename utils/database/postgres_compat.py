"""Compatibilidade PostgreSQL para os serviços legados SQLite do CW Web.

A versão desktop continua usando SQLite. Quando CW_DATABASE_URL está definido,
conectar() retorna esta camada, que preserva a API usada pelos serviços web.
"""
from __future__ import annotations
import os, re
from urllib.parse import urlparse
import psycopg
from psycopg.rows import tuple_row

class PGRow(tuple):
    __slots__ = ()
    _columns = ()
    def __new__(cls, values, columns):
        obj = tuple.__new__(cls, values)
        obj._columns = tuple(columns)
        return obj
    def __getitem__(self, key):
        if isinstance(key, str):
            try: return super().__getitem__(self._columns.index(key))
            except ValueError: raise KeyError(key)
        return super().__getitem__(key)
    def keys(self): return self._columns
    def get(self, key, default=None):
        try: return self[key]
        except (KeyError, IndexError): return default

_INSERT_TABLE_RE = re.compile(r"^\s*INSERT\s+(?:OR\s+REPLACE\s+)?INTO\s+([\w\"]+)", re.I)

def _sql(sql: str) -> str:
    s = sql.replace("?", "%s")
    s = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\s+permissoes_usuario", "INSERT INTO permissoes_usuario", s, flags=re.I)
    if re.search(r"INSERT\s+INTO\s+permissoes_usuario", s, re.I) and "ON CONFLICT" not in s.upper():
        s += " ON CONFLICT (usuario_id, modulo) DO UPDATE SET pode_visualizar=EXCLUDED.pode_visualizar, pode_criar=EXCLUDED.pode_criar, pode_editar=EXCLUDED.pode_editar, pode_excluir=EXCLUDED.pode_excluir, pode_exportar=EXCLUDED.pode_exportar, pode_sincronizar=EXCLUDED.pode_sincronizar"
    # SQLite idiom used by the legacy reporting/fleet filters.
    s = re.sub(r"\binstr\(([^,]+),\s*'([^']*)'\)\s*", r"POSITION('\2' IN \1)", s, flags=re.I)
    # Legacy SQLite custom functions translated to PostgreSQL expressions.
    s = re.sub(r"\bNORMALIZE\(COALESCE\(([^,()]+),\s*'([^']*)'\)\)", r"lower(COALESCE(\1, '\2'))", s, flags=re.I)
    s = re.sub(r"\bDIGITS\(COALESCE\(([^,()]+),\s*'([^']*)'\)\)", r"regexp_replace(COALESCE(\1, '\2'), '[^0-9]', '', 'g')", s, flags=re.I)
    s = re.sub(r"\bNORMALIZE\(([^()]+)\)", r"lower(\1)", s, flags=re.I)
    s = re.sub(r"\bDIGITS\(([^()]+)\)", r"regexp_replace(\1, '[^0-9]', '', 'g')", s, flags=re.I)
    # SQLite boolean columns are stored as INTEGER (0/1); PostgreSQL uses BOOLEAN.
    bool_cols = r"(?:deletado|sincronizado|ativo|deve_alterar_senha|pode_visualizar|pode_criar|pode_editar|pode_excluir|pode_exportar|pode_sincronizar)"
    s = re.sub(rf"COALESCE\(([^,()]+\.)?({bool_cols}),\s*0\)\s*=\s*0", r"COALESCE(\1\2, FALSE) IS FALSE", s, flags=re.I)
    s = re.sub(rf"COALESCE\(([^,()]+\.)?({bool_cols}),\s*0\)", r"COALESCE(\1\2, FALSE)", s, flags=re.I)
    s = re.sub(rf"\b({bool_cols})\s*=\s*([01])\b", lambda m: f"{m.group(1)} = {'TRUE' if m.group(2) == '1' else 'FALSE'}", s, flags=re.I)
    # SQLite strftime() is used by financial/dashboard filters. The web schema
    # keeps these legacy date fields as text, so cast explicitly in PostgreSQL.
    s = re.sub(r"strftime\(\s*'(%m|%Y)'\s*,\s*([^,)]+)\)", lambda m: f"to_char(CAST({m.group(2).strip()} AS timestamp), '{'MM' if m.group(1) == '%m' else 'YYYY'}')", s, flags=re.I)
    # SQLite concatenation || is also PostgreSQL syntax.
    return s

class PGCursor:
    def __init__(self, cursor):
        self._c = cursor
        self._lastrowid = None
    @property
    def lastrowid(self): return self._lastrowid
    @property
    def rowcount(self): return self._c.rowcount
    def execute(self, sql, params=None):
        sql2 = _sql(sql)
        m = _INSERT_TABLE_RE.match(sql2)
        if m and "RETURNING" not in sql2.upper():
            table = m.group(1).strip('"')
            if table in {"manifestos","clientes","notas","caminhoes","viagens","funcionarios","folha_funcionarios","operacoes_sp","contas","abastecimentos","manutencoes","sync_log","auditoria","usuarios","permissoes_usuario","viagem_notas"}:
                sql2 += " RETURNING id"
                self._c.execute(sql2, params or ())
                row = self._c.fetchone()
                self._lastrowid = row[0] if row else None
                return self
        self._c.execute(sql2, params or ())
        return self
    def executemany(self, sql, seq): self._c.executemany(_sql(sql), seq); return self
    def fetchone(self):
        row = self._c.fetchone()
        return self._row(row)
    def fetchall(self): return [self._row(r) for r in self._c.fetchall()]
    def fetchmany(self, size=None): return [self._row(r) for r in self._c.fetchmany(size)]
    def _row(self, row):
        if row is None: return None
        cols = [d.name for d in self._c.description] if self._c.description else []
        return PGRow(row, cols)
    @property
    def description(self): return self._c.description
    def __getattr__(self, name): return getattr(self._c, name)

class PGConnection:
    def __init__(self, dsn: str):
        self._conn = psycopg.connect(dsn, autocommit=False)
        self.row_factory = None
    def cursor(self): return PGCursor(self._conn.cursor(row_factory=tuple_row))
    def execute(self, sql, params=None):
        cur = self.cursor(); cur.execute(sql, params); return cur
    def commit(self): self._conn.commit()
    def rollback(self): self._conn.rollback()
    def close(self): self._conn.close()
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        if exc: self.rollback()
        else: self.commit()
        self.close()

def postgres_configured() -> bool:
    return bool(os.getenv("CW_DATABASE_URL") or os.getenv("DATABASE_URL"))

def connect_postgres() -> PGConnection:
    dsn = os.getenv("CW_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("CW_DATABASE_URL/DATABASE_URL não configurado")
    return PGConnection(dsn)
