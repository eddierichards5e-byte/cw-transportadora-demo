"""Migrações não destrutivas da fundação V83/V83.2."""
from __future__ import annotations

from utils.database import conectar


def _coluna_existe(conn, tabela: str, coluna: str) -> bool:
    return any(str(row[1]).lower() == coluna.lower() for row in conn.execute(f"PRAGMA table_info({tabela})").fetchall())


def aplicar_v83_indices():
    """Aplica índices e colunas de negócio sem apagar dados existentes."""
    conn = conectar()
    try:
        # Colunas de custo da viagem. Mantêm os campos legados e permitem
        # explicar exatamente de onde veio o custo/lucro exibido ao usuário.
        novas_colunas = (
            ("viagens", "custo_combustivel", "REAL DEFAULT 0"),
            ("viagens", "custo_pedagio", "REAL DEFAULT 0"),
            ("viagens", "custo_motorista", "REAL DEFAULT 0"),
            ("viagens", "custo_outros", "REAL DEFAULT 0"),
            ("viagens", "margem_percentual", "REAL DEFAULT 0"),
            ("viagens", "atualizado_em", "TEXT"),
        )
        for tabela, coluna, tipo in novas_colunas:
            if not _coluna_existe(conn, tabela, coluna):
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")

        indices = (
            ("idx_notas_criado_em_v83", "notas", "criado_em"),
            ("idx_notas_status_v83", "notas", "status"),
            ("idx_notas_chave_nfe_v83", "notas", "chave_nfe"),
            ("idx_viagens_data_saida_v83", "viagens", "data_saida"),
            ("idx_viagens_status_v83", "viagens", "status"),
            ("idx_viagens_caminhao_v83", "viagens", "caminhao_id"),
            ("idx_viagem_notas_viagem_v83", "viagem_notas", "viagem_id"),
            ("idx_viagem_notas_nota_v83", "viagem_notas", "nota_id"),
            ("idx_contas_vencimento_v83", "contas", "vencimento"),
            ("idx_contas_viagem_v83", "contas", "viagem_id"),
            ("idx_abastecimentos_data_v83", "abastecimentos", "data_abastecimento"),
            ("idx_manutencoes_data_v83", "manutencoes", "data_manutencao"),
        )
        for name, table, column in indices:
            try:
                conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({column})")
            except Exception:
                # Instalações muito antigas podem não possuir uma tabela opcional.
                continue

        conn.commit()
    finally:
        conn.close()
