"""Normalização centralizada de datas do CW.

O banco pode conter registros históricos em ISO ou DD/MM/YYYY. A camada de
apresentação deve usar formatar_data_br; consultas novas devem preferir ISO.
"""
from __future__ import annotations
from datetime import datetime

FORMATOS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
)


def parse_data(value):
    if value in (None, ""):
        return None
    text = str(value).strip().replace("T", " ")
    for fmt in FORMATOS:
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def normalizar_data(value):
    d = parse_data(value)
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else None


def formatar_data_br(value):
    d = parse_data(value)
    return d.strftime("%d/%m/%Y") if d else "—"


def sql_date_year(column: str) -> str:
    """Expressão SQLite que extrai o ano de ISO ou DD/MM/YYYY histórico."""
    col = f"COALESCE({column}, '')"
    return f"CASE WHEN instr({col}, '/') > 0 THEN substr({col}, 7, 4) ELSE substr({col}, 1, 4) END"

def sql_date_month(column: str) -> str:
    """Expressão SQLite que extrai o mês de ISO ou DD/MM/YYYY histórico."""
    col = f"COALESCE({column}, '')"
    return f"CASE WHEN instr({col}, '/') > 0 THEN substr({col}, 4, 2) ELSE substr({col}, 6, 2) END"
