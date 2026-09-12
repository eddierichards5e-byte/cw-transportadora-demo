"""Verificação de homologação PostgreSQL do CW Transportadora Web.

Uso:
  CW_DATABASE_URL='postgresql://...' python web/verify_postgres.py

O script não altera dados de negócio. O teste CRUD usa uma transação e faz
ROLLBACK. A senha nunca é impressa.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
schema=ROOT/'web'/'migrations'/'001_postgres_schema.sql'
EXPECTED={
 'manifestos': {'id','nome_arquivo','data_importacao','sync_id','sincronizado','atualizado_em','deletado'},
 'clientes': {'id','nome','cnpj','cidade','uf','razao_social','fantasia','cpf','telefone','codigo','prioridade','criado_em','sync_id','sincronizado','atualizado_em','deletado'},
 'notas': {'id','manifesto_id','chave_nfe','numero_cte','remetente_id','destinatario_id','valor_mercadoria','valor_frete','peso','origem','destino','status','criado_em','cubagem_m3','tipo_carga','sync_id','sincronizado','atualizado_em','deletado'},
 'caminhoes': {'id','placa','modelo','motorista','capacidade_kg','media_km_l','status','capacidade_m3','tipos_carga_permitidos','sync_id','sincronizado','atualizado_em','deletado'},
 'viagens': {'id','caminhao_id','data_saida','data_retorno','motorista','status','peso_total','frete_total','custo_total','lucro_total','custo_combustivel','custo_pedagio','custo_motorista','custo_outros','margem_percentual','sync_id','sincronizado','atualizado_em','deletado'},
 'viagem_notas': {'id','viagem_id','nota_id','sync_id','sincronizado','atualizado_em','deletado'},
 'funcionarios': {'id','nome','cargo','status','salario','telefone','data_admissao','vale_refeicao','criado_em','sync_id','sincronizado','atualizado_em','deletado'},
 'folha_funcionarios': {'id','funcionario_id','mes','ano','salario','vale_refeicao','hora_extra','outros','total','qtd_horas_extra','valor_hora_extra','criado_em'},
 'operacoes_sp': {'id','data_operacao','nome_caminhao','placa','motorista','valor_notas','frete_carreta','pedagio_carreta','outros_custos','custo_total','liquido','criado_em','sync_id','sincronizado','atualizado_em','deletado'},
 'contas': {'id','tipo','descricao','pessoa','categoria','valor','vencimento','pagamento','status','observacao','viagem_id','criado_em','sync_id','sincronizado','atualizado_em','deletado'},
 'abastecimentos': {'id','data_abastecimento','veiculo','motorista','km_atual','litros','valor_litro','valor_total','media_km_l','custo_km','posto','observacao','viagem_id','criado_em','sync_id','sincronizado','atualizado_em','deletado'},
 'manutencoes': {'id','data_manutencao','veiculo','km_atual','tipo','descricao','oficina','valor','proxima_revisao_km','status','observacao','viagem_id','criado_em','sync_id','sincronizado','atualizado_em','deletado'},
 'usuarios': {'id','nome_completo','usuario','senha_hash','senha_salt','nivel_acesso','ativo','deve_alterar_senha','tentativas_falhas','bloqueado_ate','ultimo_login','criado_por','criado_em','atualizado_em'},
 'permissoes_usuario': {'id','usuario_id','modulo','pode_visualizar','pode_criar','pode_editar','pode_excluir','pode_exportar','pode_sincronizar'},
 'auditoria': {'id','usuario_id','usuario_nome','acao','modulo','registro_afetado','detalhes','criado_em'},
 'sync_log': {'id','tabela','registro_id','operacao','status','tentativas','erro','criado_em','sincronizado_em','atualizado_em'},
 'sync_estado': {'chave','valor'},
 'sync_conflitos': {'id','tabela','registro_id','versao_local','versao_nuvem','decisao','detalhes','criado_em'},
}

def main():
    dsn=os.getenv('CW_DATABASE_URL') or os.getenv('DATABASE_URL')
    if not dsn:
        print('BLOCKED: defina CW_DATABASE_URL ou DATABASE_URL para testar um PostgreSQL real.')
        return 2
    try:
        import psycopg
    except ImportError:
        print('BLOCKED: instale as dependências do web/requirements.txt antes da homologação.')
        return 2
    print('1/5 conexão PostgreSQL...')
    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT version(), current_database(), current_user')
            version, db, user=cur.fetchone()
            print(f'   OK: {db} / {user} / PostgreSQL detectado')
            print('2/5 schema...')
            for table, cols in EXPECTED.items():
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", (table,))
                got={r[0] for r in cur.fetchall()}
                missing=cols-got
                if missing:
                    raise RuntimeError(f'{table}: colunas ausentes: {sorted(missing)}')
            print(f'   OK: {len(EXPECTED)} tabelas e colunas esperadas')
            print('3/5 foreign keys essenciais...')
            cur.execute("""SELECT tc.table_name,kcu.column_name,ccu.table_name,ccu.column_name
              FROM information_schema.table_constraints tc
              JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema
              JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name=tc.constraint_name AND ccu.table_schema=tc.table_schema
              WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'""")
            fks={(a,b,c,d) for a,b,c,d in cur.fetchall()}
            needed={('notas','manifesto_id','manifestos','id'),('notas','remetente_id','clientes','id'),('notas','destinatario_id','clientes','id'),('viagens','caminhao_id','caminhoes','id'),('viagem_notas','viagem_id','viagens','id'),('viagem_notas','nota_id','notas','id'),('permissoes_usuario','usuario_id','usuarios','id'),('contas','viagem_id','viagens','id'),('abastecimentos','viagem_id','viagens','id'),('manutencoes','viagem_id','viagens','id')}
            if not needed <= fks: raise RuntimeError('Foreign keys essenciais ausentes: '+repr(sorted(needed-fks)))
            print('   OK: foreign keys essenciais')
            print('4/5 identity + rollback CRUD...')
            cur.execute("INSERT INTO sync_estado(chave,valor) VALUES (%s,%s) ON CONFLICT (chave) DO UPDATE SET valor=EXCLUDED.valor RETURNING chave", ('__cw_homologacao__','ok'))
            assert cur.fetchone()[0]=='__cw_homologacao__'
            cur.execute('DELETE FROM sync_estado WHERE chave=%s',('__cw_homologacao__',))
            conn.rollback()
            print('   OK: INSERT/DELETE + rollback')
            print('5/5 isolamento final...')
            cur.execute('SELECT COUNT(*) FROM sync_estado WHERE chave=%s',('__cw_homologacao__',))
            assert cur.fetchone()[0]==0
            print('   OK: registro de canário não persistiu')
    print('HOMOLOGAÇÃO ESTRUTURAL: PASSOU')
    return 0

if __name__=='__main__': sys.exit(main())
