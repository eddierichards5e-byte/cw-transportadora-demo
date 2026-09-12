# CW Transportadora Web — PostgreSQL / produção

## Banco
A versão web usa PostgreSQL quando `CW_DATABASE_URL` ou `DATABASE_URL` estiver definido. Em produção, o projeto exige PostgreSQL e não inicia sem essa variável.

### Supabase
Crie um projeto PostgreSQL e use uma connection string com SSL. Guarde a senha somente como secret do ambiente; nunca coloque no GitHub.

## Variáveis obrigatórias
- `CW_WEB_SECRET`: segredo aleatório com pelo menos 32 caracteres.
- `CW_ENV=production`
- `CW_DATABASE_URL`: connection string PostgreSQL com SSL.
- `CW_HTTPS_ONLY=1`
- `CW_DISABLE_DOCS=1`

## Migração de um SQLite existente
Faça primeiro um backup do arquivo `.db` e rode em um ambiente de homologação:

```bash
export CW_SQLITE_PATH=/caminho/cw_transportadora.db
export CW_DATABASE_URL='postgresql://...?...sslmode=require'
python migrate_sqlite_to_postgres.py
```

O script cria o schema PostgreSQL e copia os registros preservando IDs. Ele usa `ON CONFLICT DO NOTHING`, portanto é seguro para reexecução de tabelas já parcialmente migradas.

## Homologação
```bash
pip install -r requirements.txt
python -m compileall .
CW_ENV=production CW_DATABASE_URL='...' CW_WEB_SECRET='...' uvicorn app:app --host 0.0.0.0 --port 8000
```

`GET /api/health` deve retornar `ok=true`, `database=postgresql` e `database_ok=true`.

## Segurança
- Não publique `.env`.
- Use HTTPS.
- Ative RLS no Supabase para tabelas acessíveis diretamente pela API do Supabase.
- A aplicação web usa a conexão PostgreSQL do servidor; a senha do banco nunca deve chegar ao navegador.
- Faça backup do banco antes de migrações e mudanças de schema.


## v2.5 — PostgreSQL Homologation
- Corrigida tradução de booleanos SQLite (0/1) para PostgreSQL.
- Corrigida tradução de `strftime('%m'/'%Y', ...)` usada pelos módulos financeiro/dashboard.
- Corrigido o migrador para não tentar reiniciar identity em `sync_estado`, que não possui coluna `id`.
- Adicionados testes estáticos de compatibilidade SQL.
