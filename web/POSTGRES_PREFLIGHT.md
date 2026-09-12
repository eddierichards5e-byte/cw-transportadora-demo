# v2.7 — Plano seguro de homologação PostgreSQL

Esta versão NÃO altera o Supabase de produção.

## Ordem obrigatória

1. Execute `python web/postgres_preflight.py` contra o banco de homologação.
2. Se retornar `BLOQUEADO`, não adicione Foreign Keys.
3. Investigue os registros órfãos e a origem da sincronização.
4. Faça backup.
5. Somente após a homologação, aplique constraints em uma janela controlada.
6. Rode `verify_postgres.py`.
7. Teste todos os módulos da aplicação web.

## Resultado conhecido do banco atual

Na auditoria realizada, foram encontrados registros ativos/sincronizados que
referenciam entidades ausentes. Por segurança, esta v2.7 NÃO corrige, apaga ou
altera esses registros.

## Separação do desktop

O programa Python do PC não é alterado por esta versão. O trabalho web deve
usar seu próprio ambiente de execução e, idealmente, um banco de homologação
antes de apontar para produção.
