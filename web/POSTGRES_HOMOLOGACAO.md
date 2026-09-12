# Homologação PostgreSQL

A homologação final precisa de uma instância PostgreSQL real (por exemplo, o PostgreSQL do Supabase).

## 1. Configurar a variável

Não coloque a senha no Git. Configure `CW_DATABASE_URL` como secret no ambiente de homologação.

## 2. Executar a verificação

```bash
python web/verify_postgres.py
```

O script verifica conexão, 18 tabelas, colunas esperadas, FKs essenciais e executa um INSERT/DELETE dentro de transação com rollback.

## 3. Depois da homologação

- fazer backup do SQLite original;
- executar `migrate_sqlite_to_postgres.py` em uma cópia;
- comparar contagens e totais por tabela;
- executar CRUD real de cada módulo;
- testar usuários Mestre/Operacional/Comum;
- somente então apontar o Render para o banco definitivo.
