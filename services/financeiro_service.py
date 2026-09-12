"""Serviço financeiro do CW Transportadora.

Mantém a regra de negócio fora das telas e registra toda alteração na fila de
sincronização. O serviço trabalha com as tabelas existentes (contas,
abastecimentos e manutenções) e não depende de internet para validar a regra;
a camada de sessão/sincronização continua responsável por bloquear operação
quando a nuvem estiver indisponível.
"""
from datetime import date, datetime
from typing import Any

from utils.database._conexao import conectar, registrar_sync, novo_id_global
from utils.logger import get_logger
from services.seguranca_service import exigir_permissao
from services.auditoria_service import auditoria_service, ACAO_CONFIG_ALTERADA

logger = get_logger(__name__)

TIPOS = {"a pagar": "A pagar", "pagar": "A pagar", "saida": "A pagar", "saída": "A pagar",
         "a receber": "A receber", "receber": "A receber", "entrada": "A receber"}
STATUS = {"pendente": "Pendente", "pago": "Pago", "cancelado": "Cancelado"}


def _normalizar_data(valor):
    if valor in (None, ""):
        return None
    if hasattr(valor, "toString"):
        valor = valor.toString("yyyy-MM-dd")
    valor = str(valor).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(valor[:26], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {valor}")


def _float(valor, nome="valor"):
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        raise ValueError(f"{nome.capitalize()} inválido.")
    if numero < 0:
        raise ValueError(f"{nome.capitalize()} não pode ser negativo.")
    return round(numero, 2)


class FinanceiroService:
    def listar_contas(self, tipo=None, status=None, mes=None, ano=None, pagina=1, por_pagina=50):
        pagina = max(1, int(pagina or 1)); por_pagina = min(200, max(1, int(por_pagina or 50)))
        where, params = ["COALESCE(deletado,0)=0"], []
        if tipo:
            tipo_n = TIPOS.get(str(tipo).strip().lower(), str(tipo).strip())
            where.append("LOWER(tipo)=LOWER(?)"); params.append(tipo_n)
        if status:
            status_n = STATUS.get(str(status).strip().lower(), str(status).strip())
            where.append("LOWER(status)=LOWER(?)"); params.append(status_n)
        if mes:
            where.append("strftime('%m', vencimento)=?"); params.append(f"{int(mes):02d}")
        if ano:
            where.append("strftime('%Y', vencimento)=?"); params.append(str(int(ano)))
        base = " FROM contas WHERE " + " AND ".join(where)
        conn = conectar()
        try:
            total = int(conn.execute("SELECT COUNT(*)" + base, params).fetchone()[0])
            offset = (pagina - 1) * por_pagina
            rows = conn.execute("SELECT id,tipo,descricao,pessoa,categoria,valor,vencimento,pagamento,status,observacao,criado_em" + base + " ORDER BY date(vencimento) ASC, id DESC LIMIT ? OFFSET ?", (*params, por_pagina, offset)).fetchall()
            colunas = ["id","tipo","descricao","pessoa","categoria","valor","vencimento","pagamento","status","observacao","criado_em"]
            items = [dict(zip(colunas, r)) for r in rows]
            return {"items": items, "total": total, "pagina": pagina, "por_pagina": por_pagina, "paginas": (total + por_pagina - 1)//por_pagina}
        finally:
            conn.close()

    def criar_conta(self, dados):
        exigir_permissao("contas", "criar")
        dados = self._validar_dados(dados)
        conn = conectar(); cur = conn.cursor()
        try:
            viagem_id = dados[9] if isinstance(dados, (list, tuple)) and len(dados) > 9 else None
            tem_viagem_id = any(str(r[1]).lower() == "viagem_id" for r in cur.execute("PRAGMA table_info(contas)").fetchall())
            if tem_viagem_id:
                cur.execute("""INSERT INTO contas(id,tipo,descricao,pessoa,categoria,valor,vencimento,pagamento,status,observacao,viagem_id)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (novo_id_global(),) + tuple(dados[:9]) + (viagem_id,))
            else:
                cur.execute("""INSERT INTO contas(id,tipo,descricao,pessoa,categoria,valor,vencimento,pagamento,status,observacao)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""", (novo_id_global(),) + tuple(dados[:9]))
                viagem_id = None
            conta_id = int(cur.lastrowid); registrar_sync(cur, "contas", conta_id); conn.commit()
            auditoria_service.registrar(ACAO_CONFIG_ALTERADA, "contas", registro_afetado=conta_id, operacao="CRIAR_CONTA", viagem_id=viagem_id)
            return conta_id
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()

    def atualizar_conta(self, conta_id, dados):
        exigir_permissao("contas", "editar")
        conta_id = int(conta_id); dados = self._validar_dados(dados)
        conn = conectar(); cur = conn.cursor()
        try:
            if not cur.execute("SELECT id FROM contas WHERE id=?", (conta_id,)).fetchone():
                raise ValueError("Conta não encontrada.")
            viagem_id = dados[9] if isinstance(dados, (list, tuple)) and len(dados) > 9 else None
            tem_viagem_id = any(str(r[1]).lower() == "viagem_id" for r in cur.execute("PRAGMA table_info(contas)").fetchall())
            if tem_viagem_id:
                cur.execute("""UPDATE contas SET tipo=?,descricao=?,pessoa=?,categoria=?,valor=?,vencimento=?,pagamento=?,status=?,observacao=?,viagem_id=? WHERE id=?""", (*tuple(dados[:9]), viagem_id, conta_id))
            else:
                cur.execute("""UPDATE contas SET tipo=?,descricao=?,pessoa=?,categoria=?,valor=?,vencimento=?,pagamento=?,status=?,observacao=? WHERE id=?""", (*tuple(dados[:9]), conta_id))
                viagem_id = None
            registrar_sync(cur, "contas", conta_id); conn.commit(); auditoria_service.registrar(ACAO_CONFIG_ALTERADA, "contas", registro_afetado=conta_id, operacao="ATUALIZAR_CONTA", viagem_id=viagem_id); return True
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()

    def marcar_pago(self, conta_id, data_pagamento=None):
        exigir_permissao("contas", "editar")
        conta_id = int(conta_id); data_pagamento = _normalizar_data(data_pagamento) or date.today().isoformat()
        conn = conectar(); cur = conn.cursor()
        try:
            row = cur.execute("SELECT status FROM contas WHERE id=? AND COALESCE(deletado,0)=0", (conta_id,)).fetchone()
            if not row: raise ValueError("Conta não encontrada.")
            if str(row[0] or "").lower() == "cancelado": raise ValueError("Conta cancelada não pode ser paga.")
            cur.execute("UPDATE contas SET status='Pago', pagamento=? WHERE id=?", (data_pagamento, conta_id))
            registrar_sync(cur, "contas", conta_id); conn.commit(); auditoria_service.registrar(ACAO_CONFIG_ALTERADA, "contas", registro_afetado=conta_id, operacao="MARCAR_PAGO"); return True
        except Exception:
            conn.rollback(); raise
        finally: conn.close()

    def excluir_conta(self, conta_id):
        exigir_permissao("contas", "excluir")
        conta_id = int(conta_id); conn = conectar(); cur = conn.cursor()
        try:
            row = cur.execute("SELECT id,status FROM contas WHERE id=? AND COALESCE(deletado,0)=0", (conta_id,)).fetchone()
            if not row: raise ValueError("Conta não encontrada.")
            registrar_sync(cur, "contas", conta_id, "DELETE")
            cur.execute("DELETE FROM contas WHERE id=?", (conta_id,)); conn.commit(); auditoria_service.registrar(ACAO_CONFIG_ALTERADA, "contas", registro_afetado=conta_id, operacao="EXCLUIR_CONTA"); return True
        except Exception:
            conn.rollback(); raise
        finally: conn.close()

    def resumo_financeiro(self, mes=None, ano=None):
        where, params = ["COALESCE(deletado,0)=0"], []
        if mes: where.append("strftime('%m',vencimento)=?"); params.append(f"{int(mes):02d}")
        if ano: where.append("strftime('%Y',vencimento)=?"); params.append(str(int(ano)))
        conn = conectar()
        try:
            rows = conn.execute("SELECT tipo,valor,status,vencimento,pagamento FROM contas WHERE " + " AND ".join(where), params).fetchall()
            receber = sum(float(r[1] or 0) for r in rows if str(r[0] or '').lower() == 'a receber' and str(r[2] or '').lower() != 'cancelado')
            pagar = sum(float(r[1] or 0) for r in rows if str(r[0] or '').lower() == 'a pagar' and str(r[2] or '').lower() != 'cancelado')
            recebido = sum(float(r[1] or 0) for r in rows if str(r[0] or '').lower() == 'a receber' and str(r[2] or '').lower() == 'pago')
            pago = sum(float(r[1] or 0) for r in rows if str(r[0] or '').lower() == 'a pagar' and str(r[2] or '').lower() == 'pago')
            hoje = date.today().isoformat()
            vencidas = sum(1 for r in rows if str(r[2] or '').lower() == 'pendente' and r[3] and str(r[3])[:10] < hoje)
            return {"receitas_previstas": receber, "despesas_previstas": pagar, "saldo_previsto": receber-pagar,
                    "receitas_recebidas": recebido, "despesas_pagas": pago, "saldo_realizado": recebido-pago,
                    "vencidas": vencidas, "lancamentos": len(rows)}
        finally: conn.close()

    def fluxo_caixa(self, mes=None, ano=None):
        """Retorna entradas/saídas realizadas agrupadas por mês."""
        where, params = ["COALESCE(deletado,0)=0", "LOWER(status)='pago'"], []
        if ano: where.append("strftime('%Y',COALESCE(pagamento,vencimento))=?"); params.append(str(int(ano)))
        if mes: where.append("strftime('%m',COALESCE(pagamento,vencimento))=?"); params.append(f"{int(mes):02d}")
        conn = conectar()
        try:
            rows = conn.execute("SELECT tipo,COALESCE(pagamento,vencimento),valor FROM contas WHERE " + ' AND '.join(where), params).fetchall()
            out = {}
            for tipo, data, valor in rows:
                chave = str(data or '')[:7]
                bucket = out.setdefault(chave, {"entradas":0.0,"saidas":0.0})
                if str(tipo or '').lower() == 'a receber': bucket['entradas'] += float(valor or 0)
                else: bucket['saidas'] += float(valor or 0)
            for bucket in out.values(): bucket['saldo'] = bucket['entradas'] - bucket['saidas']
            return dict(sorted(out.items()))
        finally: conn.close()

    @staticmethod
    def _validar_dados(dados: Any):
        if isinstance(dados, dict):
            get = dados.get
            tipo = TIPOS.get(str(get('tipo','')).strip().lower())
            descricao = str(get('descricao','')).strip(); pessoa = str(get('pessoa','')).strip()
            categoria = str(get('categoria','Outros')).strip() or 'Outros'; valor = _float(get('valor',0))
            vencimento = _normalizar_data(get('vencimento')); pagamento = _normalizar_data(get('pagamento'))
            status = STATUS.get(str(get('status','Pendente')).strip().lower(), str(get('status','Pendente')).strip())
            observacao = str(get('observacao','')).strip()
            viagem_id = get('viagem_id')
        else:
            campos = list(dados)
            tipo,descricao,pessoa,categoria,valor,vencimento,pagamento,status,observacao = campos[:9]
            viagem_id = campos[9] if len(campos) > 9 else None
            tipo = TIPOS.get(str(tipo).strip().lower()); descricao=str(descricao or '').strip(); pessoa=str(pessoa or '').strip(); categoria=str(categoria or 'Outros').strip() or 'Outros'; valor=_float(valor); vencimento=_normalizar_data(vencimento); pagamento=_normalizar_data(pagamento); status=STATUS.get(str(status or 'Pendente').strip().lower(), str(status or 'Pendente').strip()); observacao=str(observacao or '').strip()
        if not tipo: raise ValueError('Tipo de conta inválido. Use A pagar ou A receber.')
        if not descricao: raise ValueError('Informe a descrição do lançamento.')
        if not vencimento: raise ValueError('Informe o vencimento.')
        if status not in STATUS.values(): raise ValueError('Status financeiro inválido.')
        if status == 'Pago' and not pagamento: pagamento = date.today().isoformat()
        if status != 'Pago': pagamento = None if not pagamento else pagamento
        return (tipo,descricao,pessoa,categoria,valor,vencimento,pagamento,status,observacao)


financeiro_service = FinanceiroService()
