# Deploy gratuito — CW Transportadora Web v2.8

## Objetivo
Primeiro deploy público de demonstração. Não use o Supabase de produção como banco da demo.

## Render
1. Crie um Web Service a partir deste repositório.
2. O `render.yaml` na raiz já define build/start/health check.
3. Escolha o plano Free.
4. Defina `CW_DATABASE_URL` apontando para um PostgreSQL de homologação.
5. `CW_WEB_SECRET` é gerado automaticamente pelo Render.
6. Não coloque chaves `service_role` ou senhas no Git.

## Limitações
O Free Web Service entra em sleep após 15 minutos sem tráfego e o filesystem local é efêmero.
