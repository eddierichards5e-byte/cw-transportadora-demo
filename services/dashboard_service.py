"""Fonte única de dados reais do dashboard executivo."""
from datetime import datetime, date, timedelta
from utils.date_utils import parse_data

from utils.database._conexao import conectar
from utils.logger import get_logger
from services.financeiro_service import financeiro_service

logger = get_logger(__name__)


class DashboardService:
    @staticmethod
    def _date(value):
        return parse_data(value)

    @classmethod
    def _in_period(cls, value, tipo, mes, ano):
        if tipo in ("Geral", "Total"):
            return True
        d = cls._date(value)
        if not d:
            return False
        if tipo == "Ano":
            return d.year == int(ano)
        if tipo == "Mês":
            return d.year == int(ano) and d.month == int(mes)
        return True

    @staticmethod
    def _status_finalizado(status):
        s = str(status or "").strip().lower()
        return any(x in s for x in ("final", "entreg", "conclu", "encerr", "baixad"))

    @staticmethod
    def _status_andamento(status):
        s = str(status or "").strip().lower()
        return any(x in s for x in ("viagem", "andament", "exec", "trânsito", "transito"))

    def _rows(self, sql, params=()):
        conn = conectar()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def _count(self, tabela):
        return int(self._rows(f"SELECT COUNT(*) FROM {tabela}")[0][0])

    def inteligencia_frota(self, limite=10):
        from services.frota_service import frota_service
        return frota_service.inteligencia_frota(limite)

    def diagnostico(self):
        tabelas = ("viagens", "operacoes_sp", "notas", "clientes", "caminhoes", "contas", "abastecimentos", "manutencoes", "manifestos")
        return {tabela: self._count(tabela) for tabela in tabelas}

    def _viagens(self):
        return self._rows("SELECT id,data_saida,status,motorista,frete_total,custo_total,lucro_total FROM viagens ORDER BY id DESC")

    def _operacoes(self):
        return self._rows("SELECT id,data_operacao,nome_caminhao,placa,motorista,valor_notas,frete_carreta,pedagio_carreta,outros_custos,custo_total,liquido FROM operacoes_sp ORDER BY id DESC")

    def _notas(self, tipo="Geral", mes=None, ano=None):
        rows = self._rows("SELECT criado_em,status,valor_mercadoria,valor_frete FROM notas")
        return [r for r in rows if self._in_period(r[0], tipo, mes, ano)]

    def calcular_kpis(self, tipo="Geral", mes=None, ano=None):
        viagens = [r for r in self._viagens() if self._in_period(r[1], tipo, mes, ano)]
        operacoes = [r for r in self._operacoes() if self._in_period(r[1], tipo, mes, ano)]
        notas = self._notas(tipo, mes, ano)
        contas = [r for r in self._rows("SELECT tipo,valor,status,vencimento,pagamento FROM contas WHERE COALESCE(deletado,0)=0") if self._in_period(r[3], tipo, mes, ano)]
        combustivel = [r for r in self._rows("SELECT data_abastecimento,valor_total,litros FROM abastecimentos") if self._in_period(r[0], tipo, mes, ano)]
        manut = [r for r in self._rows("SELECT data_manutencao,valor,status FROM manutencoes") if self._in_period(r[0], tipo, mes, ano)]

        # Separar corretamente valor da mercadoria (carga) de receita (frete).
        valor_notas = sum(float(r[2] or 0) for r in notas)
        valor_frete_notas = sum(float(r[3] or 0) for r in notas)

        if viagens:
            custo = sum(float(r[5] or 0) for r in viagens)
            lucro_operacional = sum(float(r[6] or 0) for r in viagens)
            total_fretes = len(viagens)
            receita_operacional = sum(float(r[4] or 0) for r in viagens)
            fonte = "viagens"
        elif operacoes:
            custo = sum(float(r[9] or 0) for r in operacoes)
            lucro_operacional = sum(float(r[10] or 0) for r in operacoes)
            total_fretes = len(operacoes)
            receita_operacional = sum(float(r[6] or 0) for r in operacoes)
            fonte = "operacoes_sp"
        else:
            custo = 0.0
            lucro_operacional = valor_frete_notas
            receita_operacional = valor_frete_notas
            total_fretes = len(notas)
            fonte = "notas"

        contas_pagar = sum(float(r[1] or 0) for r in contas if str(r[0] or "").lower() in ("pagar", "a pagar", "saida"))
        contas_receber = sum(float(r[1] or 0) for r in contas if str(r[0] or "").lower() in ("receber", "a receber", "entrada"))
        combustivel_total = sum(float(r[1] or 0) for r in combustivel)
        manut_total = sum(float(r[1] or 0) for r in manut)
        # Viagens já carregam custo_total; contas representam compromissos
        # financeiros separados. Não somamos combustível/manutenção novamente
        # quando esses custos já estiverem refletidos na viagem.
        despesas = custo + contas_pagar
        registros_resultado = viagens or operacoes
        has_lucro = bool(registros_resultado) and any(float((r[6] if viagens else r[10]) or 0) != 0 for r in registros_resultado)
        liquido = lucro_operacional if has_lucro else receita_operacional - despesas

        pend = concl = 0
        for r in viagens:
            if self._status_finalizado(r[2]):
                concl += 1
            else:
                pend += 1

        return {
            "total_fretes": total_fretes,
            "receita_bruta": receita_operacional,
            "valor_total_notas": valor_notas,
            "valor_notas": valor_notas,
            "valor_frete_notas": valor_frete_notas,
            "despesa_total": despesas,
            "liquido": liquido,
            "margem_percentual": (liquido / receita_operacional * 100) if receita_operacional else 0,
            "fretes_pendentes": pend,
            "fretes_concluidos": concl,
            "total_notas": len(notas),
            "caminhoes_ativos": self._count("caminhoes"),
            "motoristas_ativos": len({str(r[3]).strip() for r in viagens if r[3]}) if viagens else len({str(r[4]).strip() for r in operacoes if r[4]}),
            "clientes_ativos": self._count("clientes"),
            "km_total": 0.0,
            "litros_combustivel": sum(float(r[2] or 0) for r in combustivel),
            "custo_combustivel": combustivel_total,
            "custo_manutencao": manut_total,
            "contas_receber": contas_receber,
            "contas_pagar": contas_pagar,
            "saldo_caixa": liquido,
            "fonte": fonte,
        }


    def ranking_clientes_rentabilidade(self, limite=10, ano=None):
        """Ranking de clientes por receita de frete e margem estimada.
        Usa o cliente associado à nota e custos da viagem quando disponíveis.
        """
        where = "COALESCE(n.deletado,0)=0" if self._has_column('notas','deletado') else "1=1"
        params=[]
        if ano:
            where += " AND strftime('%Y', n.criado_em)=?"; params.append(str(int(ano)))
        rows=self._rows(f"""SELECT c.id,COALESCE(c.fantasia,c.razao_social,c.nome,'Cliente'),
            COUNT(DISTINCT n.id),COALESCE(SUM(n.valor_frete),0),COALESCE(SUM(n.valor_mercadoria),0)
            FROM notas n LEFT JOIN clientes c ON c.id=COALESCE(n.destinatario_id,n.remetente_id)
            WHERE {where} GROUP BY c.id ORDER BY SUM(COALESCE(n.valor_frete,0)) DESC LIMIT ?""", (*params,int(limite)))
        return [{"cliente_id":r[0],"cliente":r[1],"fretes":int(r[2] or 0),"receita":float(r[3] or 0),"mercadoria":float(r[4] or 0)} for r in rows]

    def ranking_veiculos(self, limite=10, ano=None):
        where=[]; params=[]
        if ano: where.append("strftime('%Y',v.data_saida)=?"); params.append(str(int(ano)))
        w=(' WHERE '+' AND '.join(where)) if where else ''
        rows=self._rows(f"""SELECT v.caminhao_id,COALESCE(c.placa,'Sem placa'),COUNT(*),
            COALESCE(SUM(v.frete_total),0),COALESCE(SUM(v.custo_total),0),COALESCE(SUM(v.lucro_total),0)
            FROM viagens v LEFT JOIN caminhoes c ON c.id=v.caminhao_id {w}
            GROUP BY v.caminhao_id,c.placa ORDER BY SUM(COALESCE(v.lucro_total,0)) DESC LIMIT ?""", (*params,int(limite)))
        return [{"veiculo_id":r[0],"veiculo":r[1],"viagens":int(r[2] or 0),"receita":float(r[3] or 0),"custo":float(r[4] or 0),"lucro":float(r[5] or 0),"margem":(float(r[5] or 0)/float(r[3] or 1)*100)} for r in rows]

    def viagens_alertas_rentabilidade(self, limite=10, margem_max=10.0):
        rows=self._rows("""SELECT id,data_saida,motorista,frete_total,custo_total,lucro_total,status
            FROM viagens WHERE COALESCE(frete_total,0)>0 AND COALESCE(lucro_total,0)/NULLIF(frete_total,0) <= ?
            ORDER BY COALESCE(lucro_total,0)/NULLIF(frete_total,0) ASC, id DESC LIMIT ?""", (float(margem_max) / 100.0,int(limite)))
        return [{"id":r[0],"data":r[1],"motorista":r[2],"receita":float(r[3] or 0),"custo":float(r[4] or 0),"lucro":float(r[5] or 0),"margem":(float(r[5] or 0)/float(r[3] or 1)*100),"status":r[6]} for r in rows]

    def _has_column(self, tabela, coluna):
        try:
            return bool(self._rows(f"PRAGMA table_info({tabela})")) and any(str(r[1]).lower()==coluna.lower() for r in self._rows(f"PRAGMA table_info({tabela})"))
        except Exception:
            return False

    def resumo_fretes_status(self, tipo="Geral", mes=None, ano=None):
        viagens = [r for r in self._viagens() if self._in_period(r[1], tipo, mes, ano)]
        out = {"Finalizadas": 0, "Em viagem": 0, "Pendentes": 0}
        if viagens:
            for r in viagens:
                if self._status_finalizado(r[2]): out["Finalizadas"] += 1
                elif self._status_andamento(r[2]): out["Em viagem"] += 1
                else: out["Pendentes"] += 1
            return out
        operacoes = [r for r in self._operacoes() if self._in_period(r[1], tipo, mes, ano)]
        if operacoes:
            out["Pendentes"] = len(operacoes)
            return out
        for row in self._notas(tipo, mes, ano):
            if self._status_finalizado(row[1]): out["Finalizadas"] += 1
            else: out["Pendentes"] += 1
        return out

    def saude_financeira(self, limite=8, dias=7):
        """Consolida alertas financeiros que exigem decisão no dashboard.

        Prioriza contas vencidas, contas a pagar que vencem em breve, viagens
        com prejuízo e viagens com margem muito baixa. Não cria valores: tudo
        vem das tabelas reais do sistema.
        """
        hoje = date.today()
        limite_data = hoje + timedelta(days=int(dias))
        contas = self._rows(
            "SELECT id,tipo,descricao,pessoa,valor,vencimento,status FROM contas "
            "WHERE COALESCE(deletado,0)=0 ORDER BY id DESC"
        )
        alertas = []
        vencidas_qtd = vencidas_valor = 0.0
        proximas_qtd = proximas_valor = 0.0
        for r in contas:
            tipo = str(r[1] or '').strip().lower()
            status = str(r[6] or 'Pendente').strip().lower()
            if status in ('pago','cancelado'):
                continue
            if not any(x in tipo for x in ('pagar','saida')):
                continue
            venc = self._date(r[5])
            if not venc:
                continue
            valor = float(r[4] or 0)
            if venc < hoje:
                vencidas_qtd += 1; vencidas_valor += valor
                alertas.append({
                    'prioridade':'CRÍTICA','tipo':'Conta vencida','referencia':str(r[2] or r[3] or f'Conta #{r[0]}'),
                    'prazo':str(r[5] or '—'),'valor':valor,'ordem':0,'id':int(r[0])
                })
            elif venc <= limite_data:
                proximas_qtd += 1; proximas_valor += valor
                alertas.append({
                    'prioridade':'ATENÇÃO','tipo':'Pagamento próximo','referencia':str(r[2] or r[3] or f'Conta #{r[0]}'),
                    'prazo':str(r[5] or '—'),'valor':valor,'ordem':1,'id':int(r[0])
                })

        prejuizo_qtd = prejuizo_valor = 0.0
        baixa_margem_qtd = 0
        for r in self._rows(
            "SELECT id,data_saida,motorista,frete_total,custo_total,lucro_total,status "
            "FROM viagens WHERE COALESCE(frete_total,0)>0 AND COALESCE(deletado,0)=0 ORDER BY id DESC"
        ):
            receita = float(r[3] or 0); lucro = float(r[5] or 0); custo = float(r[4] or 0)
            margem = (lucro / receita * 100.0) if receita else 0.0
            if lucro < 0:
                prejuizo_qtd += 1; prejuizo_valor += abs(lucro)
                alertas.append({
                    'prioridade':'CRÍTICA','tipo':'Viagem com prejuízo','referencia':f'VI-{r[0]} · {r[2] or "Motorista não informado"}',
                    'prazo':str(r[1] or '—')[:10],'valor':abs(lucro),'ordem':0,'id':int(r[0])
                })
            elif margem <= 10.0:
                baixa_margem_qtd += 1
                alertas.append({
                    'prioridade':'ATENÇÃO','tipo':'Margem muito baixa','referencia':f'VI-{r[0]} · margem {margem:.1f}%',
                    'prazo':str(r[1] or '—')[:10],'valor':custo,'ordem':2,'id':int(r[0])
                })

        alertas.sort(key=lambda x:(x['ordem'], -x['id']))
        return {
            'vencidas_qtd':int(vencidas_qtd),'vencidas_valor':vencidas_valor,
            'proximas_qtd':int(proximas_qtd),'proximas_valor':proximas_valor,
            'prejuizo_qtd':int(prejuizo_qtd),'prejuizo_valor':prejuizo_valor,
            'baixa_margem_qtd':int(baixa_margem_qtd),
            'alertas':alertas[:int(limite)]
        }

    def resumo_contas_receber_pagar(self, tipo="Geral", mes=None, ano=None):
        rows = [r for r in self._rows("SELECT tipo,valor,vencimento FROM contas WHERE COALESCE(deletado,0)=0") if self._in_period(r[2], tipo, mes, ano)]
        receber = sum(float(r[1] or 0) for r in rows if "receb" in str(r[0] or "").lower() or str(r[0] or "").lower() == "entrada")
        pagar = sum(float(r[1] or 0) for r in rows if "pag" in str(r[0] or "").lower() or str(r[0] or "").lower() == "saida")
        return {"receber": receber, "pagar": pagar}

    def resumo_combustivel(self, tipo="Geral", mes=None, ano=None):
        rows = [r for r in self._rows("SELECT data_abastecimento,litros,valor_total FROM abastecimentos WHERE COALESCE(deletado,0)=0") if self._in_period(r[0], tipo, mes, ano)]
        return {"litros": sum(float(r[1] or 0) for r in rows), "custo": sum(float(r[2] or 0) for r in rows), "km": 0.0, "media_km_l": 0.0}

    def resumo_combustivel_mes(self):
        agora = datetime.now()
        return self.resumo_combustivel("Mês", agora.month, agora.year)

    def resumo_manutencoes(self, tipo="Geral", mes=None, ano=None):
        rows = [r for r in self._rows("SELECT data_manutencao,valor,status FROM manutencoes WHERE COALESCE(deletado,0)=0") if self._in_period(r[0], tipo, mes, ano)]
        pend = sum(1 for r in rows if not self._status_finalizado(r[2]))
        return {"total": len(rows), "custo": sum(float(r[1] or 0) for r in rows), "pendentes": pend}

    def proximas_entregas(self, limite=8):
        rows = self._rows("""SELECT v.data_saida,v.id,v.status,v.motorista,c.placa,MIN(n.destino) AS destino
            FROM viagens v LEFT JOIN caminhoes c ON c.id=v.caminhao_id
            LEFT JOIN viagem_notas vn ON vn.viagem_id=v.id LEFT JOIN notas n ON n.id=vn.nota_id
            GROUP BY v.id ORDER BY v.id DESC LIMIT ?""", (int(limite),))
        rows = [r for r in rows if not self._status_finalizado(r[2])]
        return [{"data": r[0] or "—", "documento": f"VI-{r[1]}", "destino": r[5] or "—", "status": r[2] or "—", "motorista": r[3] or "—", "placa": r[4] or "—"} for r in rows[:int(limite)]]

    def dados_graficos_comparativo_mensal(self, ano=None):
        ano = int(ano or datetime.now().year)
        labels = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
        receitas, despesas = [0.0] * 12, [0.0] * 12
        # Receita = frete; valor_mercadoria representa apenas o valor da carga.
        for data, valor in self._rows("SELECT criado_em,valor_frete FROM notas"):
            d = self._date(data)
            if d and d.year == ano: receitas[d.month - 1] += float(valor or 0)
        for data, custo in self._rows("SELECT data_saida,custo_total FROM viagens"):
            d = self._date(data)
            if d and d.year == ano: despesas[d.month - 1] += float(custo or 0)
        return {"labels": labels, "receitas": receitas, "despesas": despesas}


dashboard_service = DashboardService()


def calcular_kpis(tipo="Geral", mes=None, ano=None): return dashboard_service.calcular_kpis(tipo, mes, ano)
def resumo_fretes_status(tipo="Geral", mes=None, ano=None): return dashboard_service.resumo_fretes_status(tipo, mes, ano)
def resumo_contas_receber_pagar(tipo="Geral", mes=None, ano=None): return dashboard_service.resumo_contas_receber_pagar(tipo, mes, ano)
def saude_financeira(limite=8, dias=7): return dashboard_service.saude_financeira(limite, dias)
def resumo_combustivel_mes(): return dashboard_service.resumo_combustivel_mes()
def resumo_combustivel(tipo="Geral", mes=None, ano=None): return dashboard_service.resumo_combustivel(tipo, mes, ano)
def resumo_manutencoes(tipo="Geral", mes=None, ano=None): return dashboard_service.resumo_manutencoes(tipo, mes, ano)
def proximas_entregas(limite=8): return dashboard_service.proximas_entregas(limite)
def dados_graficos_comparativo_mensal(ano=None): return dashboard_service.dados_graficos_comparativo_mensal(ano)
def inteligencia_frota(limite=10): return dashboard_service.inteligencia_frota(limite)
def diagnostico(): return dashboard_service.diagnostico()
def ranking_clientes_rentabilidade(limite=10, ano=None): return dashboard_service.ranking_clientes_rentabilidade(limite, ano)
def ranking_veiculos(limite=10, ano=None): return dashboard_service.ranking_veiculos(limite, ano)
def viagens_alertas_rentabilidade(limite=10, margem_max=10.0): return dashboard_service.viagens_alertas_rentabilidade(limite, margem_max)
