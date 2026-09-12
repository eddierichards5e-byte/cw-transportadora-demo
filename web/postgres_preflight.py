"""Preflight seguro do PostgreSQL antes de qualquer mudança estrutural.

SOMENTE LEITURA. Não executa INSERT/UPDATE/DELETE/ALTER/DROP.
Uso:
  CW_DATABASE_URL='postgresql://...' python web/postgres_preflight.py

O script identifica órfãos e duplicidades antes de qualquer tentativa de
adicionar Foreign Keys. Se houver órfãos, ele retorna código 3 e recomenda
corrigir/entender os dados antes da migração.
"""
from __future__ import annotations
import os, sys

RELATIONS = [
    ("notas", "manifesto_id", "manifestos", "id"),
    ("notas", "remetente_id", "clientes", "id"),
    ("notas", "destinatario_id", "clientes", "id"),
    ("viagens", "caminhao_id", "caminhoes", "id"),
    ("viagem_notas", "viagem_id", "viagens", "id"),
    ("viagem_notas", "nota_id", "notas", "id"),
    ("folha_funcionarios", "funcionario_id", "funcionarios", "id"),
    ("permissoes_usuario", "usuario_id", "usuarios", "id"),
    ("contas", "viagem_id", "viagens", "id"),
    ("abastecimentos", "viagem_id", "viagens", "id"),
    ("manutencoes", "viagem_id", "viagens", "id"),
]

def main():
    dsn = os.getenv("CW_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        print("BLOCKED: defina CW_DATABASE_URL/DATABASE_URL.")
        return 2
    import psycopg
    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            print("PostgreSQL conectado. Modo SOMENTE LEITURA.")
            cur.execute("""SELECT table_name FROM information_schema.tables
                           WHERE table_schema='public' AND table_type='BASE TABLE'
                           ORDER BY table_name""")
            tables={r[0] for r in cur.fetchall()}
            print(f"Tabelas públicas: {len(tables)}")
            problems=0
            for st, sc, tt, tc in RELATIONS:
                if st not in tables or tt not in tables:
                    print(f"SKIP {st}.{sc} -> {tt}.{tc}: tabela ausente")
                    continue
                cur.execute(f"""
                    SELECT count(*) FROM "{st}" s
                    LEFT JOIN "{tt}" t ON t."{tc}" = s."{sc}"
                    WHERE s."{sc}" IS NOT NULL AND t."{tc}" IS NULL
                """)
                n=cur.fetchone()[0]
                mark="OK" if n == 0 else "ORPHANS"
                print(f"{mark:7} {st}.{sc} -> {tt}.{tc}: {n}")
                problems += n
            # Duplicidade de sync_id nas tabelas que o usam
            for table in sorted(tables):
                cur.execute("""SELECT 1 FROM information_schema.columns
                               WHERE table_schema='public' AND table_name=%s
                               AND column_name='sync_id'""",(table,))
                if cur.fetchone():
                    cur.execute(f"""SELECT count(*) FROM (
                        SELECT sync_id FROM "{table}"
                        WHERE sync_id IS NOT NULL
                        GROUP BY sync_id HAVING count(*) > 1
                    ) d""")
                    dup=cur.fetchone()[0]
                    if dup:
                        print(f"DUPLICATE sync_id em {table}: {dup}")
                        problems += dup
            conn.rollback()
            if problems:
                print("\nBLOQUEADO: existem inconsistências. Nenhuma alteração foi feita.")
                return 3
            print("\nOK: nenhum órfão/duplicidade detectado nas verificações.")
            print("Ainda assim, faça backup e revisão das policies antes de adicionar FKs.")
            return 0

if __name__=="__main__":
    raise SystemExit(main())
