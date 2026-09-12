from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from utils.database import conectar, dados_dashboard, listar_viagens, gerar_ranking_clientes_v6
from config.settings import settings
from utils.date_utils import sql_date_month, sql_date_year


class RelatoriosService:
    @staticmethod
    def descricao_periodo(tipo, mes, ano):
        if tipo == "Mês":
            nomes = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
            return f"{nomes[int(mes)-1]}/{ano}"
        if tipo == "Ano":
            return str(ano)
        return "Total / Histórico completo"

    def carregar_relatorio(self, tipo_periodo: str, mes: str, ano: str) -> Dict[str, Any]:
        # Uma unica conexao compartilhada para as 3 consultas desta operacao
        # (antes eram 3 conexoes SQLite abertas/fechadas em sequencia).
        conn = conectar()
        try:
            dados = dados_dashboard(tipo_periodo, mes, ano, conn=conn)
            extras = self.buscar_extras(tipo_periodo, mes, ano, conn=conn)
            ranking = gerar_ranking_clientes_v6(tipo_periodo, mes, ano, conn=conn)
        finally:
            conn.close()

        receitas = extras["frete_notas"] + dados["frete_total"] + extras["contas_recebidas"]
        despesas = extras["folha"] + extras["combustivel"] + extras["manutencao"] + extras["contas_pagas"]
        lucro = receitas - despesas

        return {
            "dados": dados,
            "extras": extras,
            "ranking": ranking,
            "receitas": receitas,
            "despesas": despesas,
            "lucro": lucro,
        }

    def buscar_extras(self, tipo_periodo: str, mes: str, ano: str, conn: Any = None) -> Dict[str, Any]:
        """
        Args:
            conn: conexao opcional ja aberta, reaproveitada por `carregar_relatorio`.
        """
        conexao_propria = conn is None
        if conexao_propria:
            conn = conectar()
        cursor = conn.cursor()

        filtro_notas = filtro_folha = filtro_comb = filtro_manut = filtro_contas = ""
        params_notas: List[str] = []
        params_folha: List[str] = []
        params_comb: List[str] = []
        params_manut: List[str] = []
        params_contas: List[str] = []

        if tipo_periodo == "Mês":
            filtro_notas = "WHERE CASE WHEN instr(COALESCE(criado_em,''), '/') > 0 THEN substr(COALESCE(criado_em,''), 4, 2) ELSE substr(COALESCE(criado_em,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(criado_em,''), '/') > 0 THEN substr(COALESCE(criado_em,''), 7, 4) ELSE substr(COALESCE(criado_em,''), 1, 4) END = ?"
            filtro_folha = "WHERE mes = ? AND ano = ?"
            filtro_comb = "WHERE CASE WHEN instr(COALESCE(data_abastecimento,''), '/') > 0 THEN substr(COALESCE(data_abastecimento,''), 4, 2) ELSE substr(COALESCE(data_abastecimento,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(data_abastecimento,''), '/') > 0 THEN substr(COALESCE(data_abastecimento,''), 7, 4) ELSE substr(COALESCE(data_abastecimento,''), 1, 4) END = ?"
            filtro_manut = "WHERE CASE WHEN instr(COALESCE(data_manutencao,''), '/') > 0 THEN substr(COALESCE(data_manutencao,''), 4, 2) ELSE substr(COALESCE(data_manutencao,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(data_manutencao,''), '/') > 0 THEN substr(COALESCE(data_manutencao,''), 7, 4) ELSE substr(COALESCE(data_manutencao,''), 1, 4) END = ?"
            filtro_contas = "WHERE substr(vencimento, 4, 2) = ? AND substr(vencimento, 7, 4) = ?"
            # Listas independentes para evitar aliasing de objeto mutável
            params_notas = [mes, ano]
            params_folha = [mes, ano]
            params_comb = [mes, ano]
            params_manut = [mes, ano]
            params_contas = [mes, ano]
        elif tipo_periodo == "Ano":
            filtro_notas = "WHERE CASE WHEN instr(COALESCE(criado_em,''), '/') > 0 THEN substr(COALESCE(criado_em,''), 7, 4) ELSE substr(COALESCE(criado_em,''), 1, 4) END = ?"
            filtro_folha = "WHERE ano = ?"
            filtro_comb = "WHERE CASE WHEN instr(COALESCE(data_abastecimento,''), '/') > 0 THEN substr(COALESCE(data_abastecimento,''), 7, 4) ELSE substr(COALESCE(data_abastecimento,''), 1, 4) END = ?"
            filtro_manut = "WHERE CASE WHEN instr(COALESCE(data_manutencao,''), '/') > 0 THEN substr(COALESCE(data_manutencao,''), 7, 4) ELSE substr(COALESCE(data_manutencao,''), 1, 4) END = ?"
            filtro_contas = "WHERE substr(vencimento, 7, 4) = ?"
            # Listas independentes para evitar aliasing de objeto mutável
            params_notas = [ano]
            params_folha = [ano]
            params_comb = [ano]
            params_manut = [ano]
            params_contas = [ano]

        try:
            cursor.execute(f"SELECT COALESCE(SUM(valor_mercadoria), 0), COALESCE(SUM(valor_frete), 0) FROM notas {filtro_notas}", params_notas)
            valor_notas, frete_notas = cursor.fetchone()

            cursor.execute(f"SELECT COALESCE(SUM(total), 0) FROM folha_funcionarios {filtro_folha}", params_folha)
            folha = cursor.fetchone()[0]

            cursor.execute(f"SELECT COALESCE(SUM(valor_total), 0) FROM abastecimentos {filtro_comb}", params_comb)
            combustivel = cursor.fetchone()[0]

            cursor.execute(f"SELECT COALESCE(SUM(valor), 0) FROM manutencoes {filtro_manut}", params_manut)
            manutencao = cursor.fetchone()[0]

            cursor.execute(f"""
                SELECT
                    COALESCE(SUM(CASE WHEN tipo = 'Receber' AND status = 'Recebido' THEN valor ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN tipo = 'Pagar' AND status = 'Pago' THEN valor ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN tipo = 'Receber' AND status NOT IN ('Recebido', 'Cancelado') THEN valor ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN tipo = 'Pagar' AND status NOT IN ('Pago', 'Cancelado') THEN valor ELSE 0 END), 0)
                FROM contas
                {filtro_contas}
            """, params_contas)
            contas_recebidas, contas_pagas, contas_a_receber, contas_a_pagar = cursor.fetchone()

            cursor.execute("SELECT data_abastecimento, veiculo, posto, valor_total FROM abastecimentos ORDER BY id DESC")
            abastecimentos = cursor.fetchall()

            cursor.execute("SELECT data_manutencao, veiculo, descricao, valor, status FROM manutencoes ORDER BY id DESC")
            manutencoes = cursor.fetchall()

            cursor.execute("SELECT tipo, descricao, pessoa, categoria, valor, vencimento, status FROM contas ORDER BY id DESC")
            contas = cursor.fetchall()
        finally:
            if conexao_propria:
                conn.close()

        return {
            "valor_notas": valor_notas or 0,
            "frete_notas": frete_notas or 0,
            "folha": folha or 0,
            "combustivel": combustivel or 0,
            "manutencao": manutencao or 0,
            "contas_recebidas": contas_recebidas or 0,
            "contas_pagas": contas_pagas or 0,
            "contas_a_receber": contas_a_receber or 0,
            "contas_a_pagar": contas_a_pagar or 0,
            "abastecimentos": abastecimentos,
            "manutencoes_lista": manutencoes,
            "contas_lista": contas,
        }

    def listar_viagens_periodo(self, tipo_periodo: str, mes: str, ano: str):
        return [viagem for viagem in listar_viagens() if self.data_no_periodo(viagem[1], tipo_periodo, mes, ano)]

    def data_no_periodo(self, data_texto: str | None, tipo_periodo: str, mes: str, ano: str) -> bool:
        if tipo_periodo == "Geral":
            return True
        if not data_texto:
            return False
        try:
            data = datetime.strptime(str(data_texto).split(" ")[0], "%d/%m/%Y")
            if tipo_periodo == "Mês":
                return data.strftime("%m") == mes and data.strftime("%Y") == ano
            if tipo_periodo == "Ano":
                return data.strftime("%Y") == ano
        except Exception:
            return False
        return True


relatorios_service = RelatoriosService()

# V71: centralização de relatório gerencial PDF (compatível com a API histórica acima).
def _v71_resumo(self, tipo="Total", mes=None, ano=None):
    tipo = "Geral" if tipo == "Total" else tipo
    mes, ano = int(mes or datetime.now().month), int(ano or datetime.now().year)
    c = conectar(); cur = c.cursor()
    try:
        def per(col):
            if tipo == "Mês":
                # datas DD/MM/YYYY e YYYY-MM-DD
                return f" AND (({col} LIKE '%/{mes:02d}/{ano}') OR ({col} LIKE '{ano}-{mes:02d}-%'))"
            if tipo == "Ano":
                return f" AND (({col} LIKE '%/{ano}') OR ({col} LIKE '{ano}-%'))"
            return ""
        def val(sql): cur.execute(sql); return cur.fetchone()[0] or 0
        n=per('criado_em'); v=per('data_saida'); cb=per('data_abastecimento'); m=per('data_manutencao'); ct=per('vencimento')
        valor_notas=val(f"SELECT COALESCE(SUM(valor_mercadoria),0) FROM notas WHERE COALESCE(deletado,0)=0{n}")
        frete_notas=val(f"SELECT COALESCE(SUM(valor_frete),0) FROM notas WHERE COALESCE(deletado,0)=0{n}")
        total_notas=val(f"SELECT COUNT(*) FROM notas WHERE COALESCE(deletado,0)=0{n}")
        frete_viagens=val(f"SELECT COALESCE(SUM(frete_total),0) FROM viagens WHERE COALESCE(deletado,0)=0{v}")
        custo_viagens=val(f"SELECT COALESCE(SUM(custo_total),0) FROM viagens WHERE COALESCE(deletado,0)=0{v}")
        lucro_viagens=val(f"SELECT COALESCE(SUM(lucro_total),0) FROM viagens WHERE COALESCE(deletado,0)=0{v}")
        total_viagens=val(f"SELECT COUNT(*) FROM viagens WHERE COALESCE(deletado,0)=0{v}")
        combustivel=val(f"SELECT COALESCE(SUM(valor_total),0) FROM abastecimentos WHERE COALESCE(deletado,0)=0{cb}")
        litros=val(f"SELECT COALESCE(SUM(litros),0) FROM abastecimentos WHERE COALESCE(deletado,0)=0{cb}")
        manutencao=val(f"SELECT COALESCE(SUM(valor),0) FROM manutencoes WHERE COALESCE(deletado,0)=0{m}")
        manut_qtd=val(f"SELECT COUNT(*) FROM manutencoes WHERE COALESCE(deletado,0)=0{m}")
        recebidas=val(f"SELECT COALESCE(SUM(valor),0) FROM contas WHERE COALESCE(deletado,0)=0 AND tipo IN ('Receber','A receber') AND status='Recebido'{ct}")
        pagas=val(f"SELECT COALESCE(SUM(valor),0) FROM contas WHERE COALESCE(deletado,0)=0 AND tipo IN ('Pagar','A pagar') AND status='Pago'{ct}")
        a_receber=val(f"SELECT COALESCE(SUM(valor),0) FROM contas WHERE COALESCE(deletado,0)=0 AND tipo IN ('Receber','A receber') AND status NOT IN ('Recebido','Cancelado'){ct}")
        a_pagar=val(f"SELECT COALESCE(SUM(valor),0) FROM contas WHERE COALESCE(deletado,0)=0 AND tipo IN ('Pagar','A pagar') AND status NOT IN ('Pago','Cancelado'){ct}")
        if tipo=='Mês': folha=val("SELECT COALESCE(SUM(total),0) FROM folha_funcionarios WHERE mes=%d AND ano=%d"%(mes,ano))
        elif tipo=='Ano': folha=val("SELECT COALESCE(SUM(total),0) FROM folha_funcionarios WHERE ano=%d"%ano)
        else: folha=val("SELECT COALESCE(SUM(total),0) FROM folha_funcionarios")
        receitas=float(frete_notas)+float(frete_viagens)+float(recebidas); despesas=float(folha)+float(combustivel)+float(manutencao)+float(pagas); resultado=receitas-despesas
        return {'periodo': self.descricao_periodo(tipo,mes,ano),'receitas':receitas,'despesas':despesas,'resultado':resultado,'margem':resultado/receitas*100 if receitas else 0,'valor_notas':float(valor_notas),'frete_notas':float(frete_notas),'frete_viagens':float(frete_viagens),'total_notas':int(total_notas),'total_viagens':int(total_viagens),'custo_viagens':float(custo_viagens),'lucro_viagens':float(lucro_viagens),'combustivel':float(combustivel),'litros':float(litros),'manutencao':float(manutencao),'manut_qtd':int(manut_qtd),'folha':float(folha),'recebidas':float(recebidas),'pagas':float(pagas),'a_receber':float(a_receber),'a_pagar':float(a_pagar),'clientes':int(val("SELECT COUNT(*) FROM clientes WHERE COALESCE(deletado,0)=0")),'veiculos':int(val("SELECT COUNT(*) FROM caminhoes WHERE COALESCE(deletado,0)=0")),'motoristas':int(val("SELECT COUNT(*) FROM funcionarios WHERE COALESCE(deletado,0)=0 AND lower(COALESCE(cargo,'')) LIKE '%motor%'"))}
    finally: c.close()

def _v71_descricao(self,tipo,mes,ano):
    if tipo=='Mês': return ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"][int(mes)-1]+f"/{ano}"
    if tipo=='Ano': return str(ano)
    return 'Total / Histórico completo'

def _v71_pdf(self,caminho,tipo='Total',mes=None,ano=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    r=self.carregar_resumo(tipo,mes,ano); path=Path(caminho); path.parent.mkdir(parents=True,exist_ok=True)
    doc=SimpleDocTemplate(str(path),pagesize=A4,leftMargin=14*mm,rightMargin=14*mm,topMargin=15*mm,bottomMargin=15*mm); st=getSampleStyleSheet()
    def money(v): return f"R$ {float(v or 0):,.2f}".replace(',','X').replace('.',',').replace('X','.')
    def tb(rows):
        t=Table(rows,colWidths=[90*mm,75*mm],repeatRows=1); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0F172A')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#CBD5E1')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F8FAFC')]),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)])); return t
    story=[Paragraph(str(settings.configuracoes.get('empresa') or 'CW TRANSPORTADORA').upper(),st['Title']),Paragraph('RELATÓRIO GERENCIAL CONSOLIDADO',st['Heading2']),Paragraph(f"Período: {r['periodo']} · Emitido em {datetime.now().strftime('%d/%m/%Y %H:%M')}",st['Normal']),Spacer(1,5*mm),Paragraph('Resumo financeiro',st['Heading2']),tb([['Indicador','Valor'],['Receitas',money(r['receitas'])],['Despesas',money(r['despesas'])],['Resultado',money(r['resultado'])],['Margem',f"{r['margem']:.1f}%"],['A receber',money(r['a_receber'])],['A pagar',money(r['a_pagar'])]]),Spacer(1,5*mm),Paragraph('Operação',st['Heading2']),tb([['Indicador','Valor'],['Notas fiscais',str(r['total_notas'])],['Valor das mercadorias',money(r['valor_notas'])],['Frete das notas',money(r['frete_notas'])],['Viagens',str(r['total_viagens'])],['Frete das viagens',money(r['frete_viagens'])],['Custo das viagens',money(r['custo_viagens'])],['Lucro das viagens',money(r['lucro_viagens'])]]),Spacer(1,5*mm),Paragraph('Custos',st['Heading2']),tb([['Indicador','Valor'],['Folha',money(r['folha'])],['Combustível',money(r['combustivel'])],['Litros',f"{r['litros']:,.1f}"],['Manutenção',money(r['manutencao'])],['Ordens de manutenção',str(r['manut_qtd'])],['Recebido',money(r['recebidas'])],['Pago',money(r['pagas'])]]),Spacer(1,5*mm),Paragraph('Cadastros principais',st['Heading2']),tb([['Indicador','Quantidade'],['Clientes',str(r['clientes'])],['Veículos',str(r['veiculos'])],['Motoristas',str(r['motoristas'])]]),Spacer(1,5*mm),Paragraph('Relatório gerado automaticamente pelo CW Transportadora com os registros disponíveis no momento da emissão.',st['Normal'])]
    def footer(canvas,doc): canvas.saveState(); canvas.setFont('Helvetica',7); canvas.setFillColor(colors.HexColor('#64748B')); canvas.drawString(14*mm,8*mm,'CW Transportadora · Relatório gerencial'); canvas.drawRightString(A4[0]-14*mm,8*mm,f'Página {doc.page}'); canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer); return str(path)

RelatoriosService.carregar_resumo=_v71_resumo
RelatoriosService.descricao_periodo=_v71_descricao
RelatoriosService.gerar_pdf=_v71_pdf


# V72: relatório premium detalhado — tabelas operacionais e rankings.
def _v72_colunas(cur, tabela):
    try:
        return {str(r[1]).lower() for r in cur.execute(f"PRAGMA table_info({tabela})").fetchall()}
    except Exception:
        return set()


def _v72_where_data(col, tipo, mes, ano):
    if tipo == 'Mês':
        return f" AND (({col} LIKE '%/{int(mes):02d}/{int(ano)}') OR ({col} LIKE '{int(ano)}-{int(mes):02d}-%'))"
    if tipo == 'Ano':
        return f" AND (({col} LIKE '%/{int(ano)}') OR ({col} LIKE '{int(ano)}-%'))"
    return ''


def _v72_detalhes(self, tipo='Total', mes=None, ano=None, limite=15):
    mes, ano = int(mes or datetime.now().month), int(ano or datetime.now().year)
    c=conectar(); cur=c.cursor()
    try:
        def rows(sql):
            try: return cur.execute(sql).fetchall()
            except Exception: return []
        out={'viagens':[],'veiculos':[],'clientes':[],'contas':[],'combustivel':[],'manutencoes':[],'mensal':[]}
        cv=_v72_colunas(cur,'viagens'); cc=_v72_colunas(cur,'caminhoes'); cn=_v72_colunas(cur,'notas'); cta=_v72_colunas(cur,'contas'); cab=_v72_colunas(cur,'abastecimentos'); cm=_v72_colunas(cur,'manutencoes')
        wv=_v72_where_data('v.data_saida',tipo,mes,ano)
        if cv:
            cols=['v.id','v.data_saida','v.status','v.motorista','v.frete_total','v.custo_total','v.lucro_total']
            if 'caminhao_id' in cv: cols += ["c.placa"]
            q=f"SELECT {','.join(cols)} FROM viagens v " + ("LEFT JOIN caminhoes c ON c.id=v.caminhao_id " if 'caminhao_id' in cv else '') + f"WHERE COALESCE(v.deletado,0)=0{wv} ORDER BY v.data_saida DESC, v.id DESC LIMIT {int(limite)}"
            for r in rows(q):
                base=list(r); placa=base.pop() if 'caminhao_id' in cv else '—'
                out['viagens'].append([base[0],base[1] or '—',placa or '—',base[3] or '—',float(base[4] or 0),float(base[5] or 0),float(base[6] or 0),base[2] or '—'])
        if cc:
            # frota atual + quantidade de viagens e custos de combustível/manutenção quando possível.
            q=f"SELECT id,placa,modelo,motorista,media_km_l FROM caminhoes WHERE COALESCE(deletado,0)=0 ORDER BY placa LIMIT {int(limite)}" if 'deletado' in cc else f"SELECT id,placa,modelo,motorista,media_km_l FROM caminhoes ORDER BY placa LIMIT {int(limite)}"
            for r in rows(q): out['veiculos'].append(list(r))
        if cn and 'destinatario_id' in cn:
            # Ranking por cliente a partir das notas, mantendo compatibilidade com cadastros antigos.
            cli_cols=_v72_colunas(cur,'clientes')
            if cli_cols:
                names=[f'c.{x}' for x in ('fantasia','razao_social','nome') if x in cli_cols]
                name=('COALESCE('+','.join(names)+",'Cliente')") if names else "'Cliente'"
                w=_v72_where_data('n.criado_em',tipo,mes,ano)
                q=f"SELECT {name},COUNT(n.id),COALESCE(SUM(n.valor_frete),0),COALESCE(SUM(n.valor_mercadoria),0) FROM notas n LEFT JOIN clientes c ON c.id=COALESCE(n.destinatario_id,n.remetente_id) WHERE COALESCE(n.deletado,0)=0{w} GROUP BY c.id ORDER BY SUM(COALESCE(n.valor_frete,0)) DESC LIMIT {int(limite)}"
                out['clientes']=[list(r) for r in rows(q)]
        if cta:
            w=_v72_where_data('ct.vencimento',tipo,mes,ano)
            q=f"SELECT ct.descricao,ct.tipo,ct.valor,ct.vencimento,ct.status FROM contas ct WHERE COALESCE(ct.deletado,0)=0{w} ORDER BY ct.vencimento DESC LIMIT {int(limite)}" if {'descricao','tipo','valor','vencimento','status'} <= cta else ''
            out['contas']=[list(r) for r in rows(q)] if q else []
        if cab:
            w=_v72_where_data('a.data_abastecimento',tipo,mes,ano)
            q=f"SELECT a.data_abastecimento,a.veiculo,a.km_atual,a.litros,a.valor_total,a.media_km_l,a.custo_km FROM abastecimentos a WHERE COALESCE(a.deletado,0)=0{w} ORDER BY a.data_abastecimento DESC LIMIT {int(limite)}" if {'data_abastecimento','veiculo','km_atual','litros','valor_total'} <= cab else ''
            out['combustivel']=[list(r) for r in rows(q)] if q else []
        if cm:
            w=_v72_where_data('m.data_manutencao',tipo,mes,ano)
            q=f"SELECT m.data_manutencao,m.veiculo,m.tipo,m.descricao,m.valor,m.proxima_revisao_km,m.status FROM manutencoes m WHERE COALESCE(m.deletado,0)=0{w} ORDER BY m.data_manutencao DESC LIMIT {int(limite)}" if {'data_manutencao','veiculo','valor','status'} <= cm else ''
            out['manutencoes']=[list(r) for r in rows(q)] if q else []
        # Comparativo mensal: receita de fretes de notas + viagens e custos operacionais.
        if tipo in ('Ano','Mês'):
            y=int(ano)
            for m in range(1,13):
                n=_v72_where_data('n.criado_em','Mês',m,y); v=_v72_where_data('v.data_saida','Mês',m,y); a=_v72_where_data('a.data_abastecimento','Mês',m,y); ma=_v72_where_data('m.data_manutencao','Mês',m,y)
                def one(sql):
                    try: cur.execute(sql); return float(cur.fetchone()[0] or 0)
                    except Exception: return 0.0
                rec=one(f"SELECT COALESCE(SUM(valor_frete),0) FROM notas n WHERE COALESCE(deletado,0)=0{n}") if cn else 0
                rec+=one(f"SELECT COALESCE(SUM(frete_total),0) FROM viagens v WHERE COALESCE(deletado,0)=0{v}") if cv else 0
                cost=one(f"SELECT COALESCE(SUM(valor_total),0) FROM abastecimentos a WHERE COALESCE(deletado,0)=0{a}") if cab else 0
                cost+=one(f"SELECT COALESCE(SUM(valor),0) FROM manutencoes m WHERE COALESCE(deletado,0)=0{ma}") if cm else 0
                out['mensal'].append([m,rec,cost,rec-cost])
        # Folha detalhada para o relatório gerencial.
        try:
            if {'id','funcionario_id','mes','ano','salario','vale','horas_extra','valor_hora_extra','outros','total','status'} <= set(_v72_colunas(cur,'folha_funcionarios')):
                w=_v72_where_data('f.ano',tipo,mes,ano)
                q=f"SELECT f.mes,f.ano,COALESCE(fn.nome,'Funcionário'),f.salario,f.vale,f.horas_extra,f.valor_hora_extra,f.outros,f.total,f.status FROM folha_funcionarios f LEFT JOIN funcionarios fn ON fn.id=f.funcionario_id WHERE 1=1{w} ORDER BY f.ano DESC,f.mes DESC,fn.nome LIMIT {int(limite)}"
                out['folha']=[list(r) for r in rows(q)]
        except Exception:
            out['folha']=[]
        return out
    finally: c.close()


def _v72_pdf(self,caminho,tipo='Total',mes=None,ano=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
    r=self.carregar_resumo(tipo,mes,ano); d=_v72_detalhes(self,tipo,mes,ano,15)
    path=Path(caminho); path.parent.mkdir(parents=True,exist_ok=True)
    doc=SimpleDocTemplate(str(path),pagesize=A4,leftMargin=12*mm,rightMargin=12*mm,topMargin=14*mm,bottomMargin=15*mm)
    st=getSampleStyleSheet(); st.add(ParagraphStyle(name='V72Title',parent=st['Title'],fontName='Helvetica-Bold',fontSize=20,leading=23,spaceAfter=4)); st.add(ParagraphStyle(name='V72H',parent=st['Heading2'],fontName='Helvetica-Bold',fontSize=12,leading=15,spaceBefore=8,spaceAfter=6)); st.add(ParagraphStyle(name='V72Small',parent=st['Normal'],fontSize=8.5,leading=11,textColor=colors.HexColor('#475569'))); st.add(ParagraphStyle(name='V72Kpi',parent=st['Heading2'],fontName='Helvetica-Bold',fontSize=14,leading=17,spaceBefore=5,spaceAfter=5,textColor=colors.HexColor('#0F172A')))
    def money(v): return f"R$ {float(v or 0):,.2f}".replace(',','X').replace('.',',').replace('X','.')
    def cell(v): return Paragraph(str(v if v not in (None,'') else '—').replace('&','&amp;'),st['V72Small'])
    def tb(headers, data, widths=None):
        vals=[[cell(x) for x in headers]]+[[cell(x) for x in row] for row in data]
        t=Table(vals,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0F172A')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7.5),('GRID',(0,0),(-1,-1),.25,colors.HexColor('#CBD5E1')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F8FAFC')]),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        return t
    empresa=str(settings.configuracoes.get('empresa') or 'CW TRANSPORTADORA').upper(); story=[Paragraph(empresa,st['V72Title']),Paragraph('RELATÓRIO GERENCIAL PREMIUM · CONSOLIDADO',st['V72H']),Paragraph(f"Período: {r['periodo']} · Emitido em {datetime.now().strftime('%d/%m/%Y %H:%M')}",st['V72Small']),Spacer(1,4*mm)]
    story += [Paragraph('1. Resumo executivo',st['V72H']),tb(['Indicador','Valor'],[['Receitas',money(r['receitas'])],['Despesas',money(r['despesas'])],['Resultado',money(r['resultado'])],['Margem',f"{r['margem']:.1f}%"],['A receber',money(r['a_receber'])],['A pagar',money(r['a_pagar'])],['Notas',r['total_notas']],['Viagens',r['total_viagens']],["Combustível",money(r['combustivel'])],["Manutenção",money(r['manutencao'])]],[80*mm,88*mm])]
    story += [Paragraph('2. Indicadores operacionais',st['V72H']),tb(['Indicador','Valor'],[['Valor das mercadorias',money(r['valor_notas'])],['Frete das notas',money(r['frete_notas'])],['Frete das viagens',money(r['frete_viagens'])],['Custo das viagens',money(r['custo_viagens'])],['Lucro das viagens',money(r['lucro_viagens'])],['Folha',money(r['folha'])],['Litros abastecidos',f"{r['litros']:,.1f}"],['Ordens de manutenção',r['manut_qtd']],["Clientes",r['clientes']],["Veículos",r['veiculos']],["Motoristas",r['motoristas']]], [80*mm,88*mm])]
    if d['mensal']:
        nomes=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']; story += [Paragraph(f"3. Evolução mensal · {ano}",st['V72H']),tb(['Mês','Receita','Custos op.','Resultado'],[[nomes[x[0]-1],money(x[1]),money(x[2]),money(x[3])] for x in d['mensal']],[30*mm,46*mm,46*mm,46*mm]),PageBreak()]
    story += [Paragraph('4. Viagens detalhadas',st['V72H'])]
    if d['viagens']: story += [tb(['ID','Saída','Veículo','Motorista','Receita','Custo','Lucro','Status'],[[x[0],x[1],x[2],x[3],money(x[4]),money(x[5]),money(x[6]),x[7]] for x in d['viagens']],[13*mm,22*mm,23*mm,29*mm,22*mm,22*mm,22*mm,25*mm])]
    else: story += [Paragraph('Nenhuma viagem detalhada disponível no período.',st['V72Small'])]
    story += [Paragraph('5. Ranking de clientes',st['V72H'])]
    if d['clientes']: story += [tb(['Cliente','Notas','Frete','Mercadorias'],[[x[0],x[1],money(x[2]),money(x[3])] for x in d['clientes']],[70*mm,20*mm,38*mm,40*mm])]
    else: story += [Paragraph('Nenhum ranking de clientes disponível.',st['V72Small'])]
    story += [Paragraph('6. Frota e desempenho cadastral',st['V72H'])]
    if d['veiculos']: story += [tb(['ID','Placa','Modelo','Motorista','Média km/L'],[[x[0],x[1],x[2],x[3],x[4]] for x in d['veiculos']],[15*mm,32*mm,43*mm,50*mm,30*mm])]
    else: story += [Paragraph('Nenhum veículo cadastrado.',st['V72Small'])]
    story += [PageBreak(),Paragraph('7. Contas e compromissos financeiros',st['V72H'])]
    if d['contas']: story += [tb(['Descrição','Tipo','Valor','Vencimento','Status'],[[x[0],x[1],money(x[2]),x[3],x[4]] for x in d['contas']],[58*mm,28*mm,30*mm,30*mm,32*mm])]
    else: story += [Paragraph('Nenhuma conta encontrada no período.',st['V72Small'])]
    story += [Paragraph('8. Abastecimentos',st['V72H'])]
    if d['combustivel']: story += [tb(['Data','Veículo','KM','Litros','Valor','km/L','Custo/km'],[[x[0],x[1],f'{float(x[2] or 0):,.0f}',f'{float(x[3] or 0):,.1f}',money(x[4]),f'{float(x[5] or 0):,.2f}',money(x[6])] for x in d['combustivel']],[25*mm,35*mm,25*mm,25*mm,28*mm,25*mm,28*mm])]
    else: story += [Paragraph('Nenhum abastecimento detalhado disponível.',st['V72Small'])]
    story += [Paragraph('9. Folha de pagamento',st['V72H']), Paragraph('Visão consolidada dos lançamentos de folha disponíveis para a competência/período selecionado.',st['V72Small'])]
    if d.get('folha'): story += [tb(['Mês/Ano','Funcionário','Salário','Vale','Horas extra','Extra','Outros','Total','Status'],[[f'{x[0]}/{x[1]}',x[2],money(x[3]),money(x[4]),f'{float(x[5] or 0):,.2f}',money(x[6]),money(x[7]),money(x[8]),x[9]] for x in d['folha']],[18*mm,43*mm,25*mm,22*mm,24*mm,24*mm,24*mm,25*mm,20*mm])]
    else: story += [Paragraph('Nenhum lançamento de folha encontrado no período.',st['V72Small'])]
    story += [Paragraph('10. Manutenções',st['V72H'])]
    if d['manutencoes']: story += [tb(['Data','Veículo','Tipo','Descrição','Valor','Próx. KM','Status'],[[x[0],x[1],x[2],x[3],money(x[4]),x[5],x[6]] for x in d['manutencoes']],[24*mm,30*mm,25*mm,45*mm,25*mm,25*mm,23*mm])]
    else: story += [Paragraph('Nenhuma manutenção detalhada disponível.',st['V72Small'])]
    story += [Spacer(1,6*mm),Paragraph('11. Observações e critérios',st['V72H']),Paragraph('Este relatório consolida somente registros ativos disponíveis no banco no momento da emissão. Custos de viagem são considerados vinculados apenas quando o sistema possui atribuição explícita; o relatório não realiza rateios ou suposições. Valores financeiros são apresentados em reais e os detalhes são limitados aos registros mais recentes para manter o documento executivo legível.',st['V72Small'])]
    def footer(canvas,doc):
        canvas.saveState(); canvas.setFont('Helvetica',7); canvas.setFillColor(colors.HexColor('#64748B')); canvas.drawString(12*mm,8*mm,'CW Transportadora · Relatório Gerencial Premium V82'); canvas.drawRightString(A4[0]-12*mm,8*mm,f'Página {doc.page}'); canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer); return str(path)

RelatoriosService.detalhes_premium = _v72_detalhes
RelatoriosService.gerar_pdf = _v72_pdf

# V84.7: relatório PDF robusto — compatibilidade real com o schema atual.
def _v84_7_detalhes(self, tipo='Total', mes=None, ano=None, limite=15):
    mes, ano = int(mes or datetime.now().month), int(ano or datetime.now().year)
    c = conectar(); cur = c.cursor()
    try:
        def cols(tabela): return _v72_colunas(cur, tabela)
        def rows(sql, params=()):
            try: return cur.execute(sql, params).fetchall()
            except Exception: return []
        def ativo(alias, tabela):
            return f"COALESCE({alias}.deletado,0)=0" if 'deletado' in cols(tabela) else '1=1'
        def data_where(col, tipo_, mes_, ano_): return _v72_where_data(col, tipo_, mes_, ano_)
        out = {'viagens': [], 'veiculos': [], 'clientes': [], 'contas': [], 'combustivel': [], 'manutencoes': [], 'mensal': [], 'folha': []}
        cv, cc, cn = cols('viagens'), cols('caminhoes'), cols('notas')
        cta, cab, cm, cf, cfn = cols('contas'), cols('abastecimentos'), cols('manutencoes'), cols('folha_funcionarios'), cols('funcionarios')

        if cv and {'id','data_saida','status','motorista','frete_total','custo_total','lucro_total'} <= cv:
            join = "LEFT JOIN caminhoes c ON c.id=v.caminhao_id " if 'caminhao_id' in cv and cc else ''
            placa = 'COALESCE(c.placa,\'—\')' if join else "'—'"
            w = data_where('v.data_saida', tipo, mes, ano)
            q = f"SELECT v.id,v.data_saida,{placa},v.motorista,v.frete_total,v.custo_total,v.lucro_total,v.status FROM viagens v {join}WHERE {ativo('v','viagens')}{w} ORDER BY v.data_saida DESC,v.id DESC LIMIT ?"
            out['viagens'] = [list(r) for r in rows(q,(int(limite),))]

        if cc and {'id','placa','modelo','motorista'} <= cc:
            media = 'media_km_l' if 'media_km_l' in cc else None
            media_expr = f',c.{media}' if media else ',NULL'
            q = f"SELECT c.id,c.placa,c.modelo,c.motorista{media_expr} FROM caminhoes c WHERE {ativo('c','caminhoes')} ORDER BY c.placa LIMIT ?"
            out['veiculos'] = [list(r) for r in rows(q,(int(limite),))]

        if cn and 'destinatario_id' in cn and _v72_colunas(cur,'clientes'):
            cli = cols('clientes')
            names = [f'c.{x}' for x in ('fantasia','razao_social','nome') if x in cli]
            name = "COALESCE(" + ','.join(names) + ",'Cliente')" if names else "'Cliente'"
            w = data_where('n.criado_em',tipo,mes,ano)
            q = f"SELECT {name},COUNT(n.id),COALESCE(SUM(n.valor_frete),0),COALESCE(SUM(n.valor_mercadoria),0) FROM notas n LEFT JOIN clientes c ON c.id=COALESCE(n.destinatario_id,n.remetente_id) WHERE {ativo('n','notas')}{w} GROUP BY c.id ORDER BY SUM(COALESCE(n.valor_frete,0)) DESC LIMIT ?"
            out['clientes'] = [list(r) for r in rows(q,(int(limite),))]

        if cta and {'descricao','tipo','valor','vencimento','status'} <= cta:
            w = data_where('ct.vencimento',tipo,mes,ano)
            q = f"SELECT ct.descricao,ct.tipo,ct.valor,ct.vencimento,ct.status FROM contas ct WHERE {ativo('ct','contas')}{w} ORDER BY ct.vencimento DESC LIMIT ?"
            out['contas'] = [list(r) for r in rows(q,(int(limite),))]

        if cab and {'data_abastecimento','veiculo','km_atual','litros','valor_total'} <= cab:
            media = 'media_km_l' if 'media_km_l' in cab else None
            custo = 'custo_km' if 'custo_km' in cab else None
            expr_media = f'a.{media}' if media else 'NULL'; expr_custo = f'a.{custo}' if custo else 'NULL'
            w = data_where('a.data_abastecimento',tipo,mes,ano)
            q = f"SELECT a.data_abastecimento,a.veiculo,a.km_atual,a.litros,a.valor_total,{expr_media},{expr_custo} FROM abastecimentos a WHERE {ativo('a','abastecimentos')}{w} ORDER BY a.data_abastecimento DESC LIMIT ?"
            out['combustivel'] = [list(r) for r in rows(q,(int(limite),))]

        if cm and {'data_manutencao','veiculo','valor','status'} <= cm:
            tipo_col = 'tipo' if 'tipo' in cm else None; desc_col = 'descricao' if 'descricao' in cm else None; prox = 'proxima_revisao_km' if 'proxima_revisao_km' in cm else None
            qcols = ['m.data_manutencao','m.veiculo',f'm.{tipo_col}' if tipo_col else "'—'",f'm.{desc_col}' if desc_col else "'—'",'m.valor',f'm.{prox}' if prox else 'NULL','m.status']
            w = data_where('m.data_manutencao',tipo,mes,ano)
            q = f"SELECT {','.join(qcols)} FROM manutencoes m WHERE {ativo('m','manutencoes')}{w} ORDER BY m.data_manutencao DESC LIMIT ?"
            out['manutencoes'] = [list(r) for r in rows(q,(int(limite),))]

        # Folha: usa os nomes reais do schema (vale_refeicao/qtd_horas_extra/valor_hora_extra/hora_extra).
        if cf and {'funcionario_id','mes','ano','salario','vale_refeicao','qtd_horas_extra','valor_hora_extra','hora_extra','outros','total'} <= cf:
            where = [] ; params = []
            if tipo == 'Mês': where += ['f.mes=?','f.ano=?']; params += [f'{mes:02d}',str(ano)]
            elif tipo == 'Ano': where += ['f.ano=?']; params += [str(ano)]
            where_sql = ' AND '.join(where) if where else '1=1'
            join = 'LEFT JOIN funcionarios fn ON fn.id=f.funcionario_id' if cfn else ''
            nome = "COALESCE(fn.nome,'Funcionário')" if cfn else "'Funcionário'"
            status = 'fn.status' if cfn and 'status' in cfn else "'Ativo'"
            q = f"SELECT f.mes,f.ano,{nome},f.salario,f.vale_refeicao,f.qtd_horas_extra,f.valor_hora_extra,f.hora_extra,f.outros,f.total,{status} FROM folha_funcionarios f {join} WHERE {where_sql} ORDER BY f.ano DESC,f.mes DESC,{nome} LIMIT ?"
            out['folha'] = [list(r) for r in rows(q,(*params,int(limite)))]

        # Comparativo mensal: Ano = 12 meses; Mês = somente a competência escolhida.
        meses = range(1,13) if tipo == 'Ano' else ([mes] if tipo == 'Mês' else [])
        for mm in meses:
            def one(sql):
                try: return float(cur.execute(sql).fetchone()[0] or 0)
                except Exception: return 0.0
            rec = 0.0; cost = 0.0
            if cn: rec += one(f"SELECT COALESCE(SUM(valor_frete),0) FROM notas n WHERE {ativo('n','notas')}{data_where('n.criado_em','Mês',mm,ano)}")
            if cv: rec += one(f"SELECT COALESCE(SUM(frete_total),0) FROM viagens v WHERE {ativo('v','viagens')}{data_where('v.data_saida','Mês',mm,ano)}")
            if cab: cost += one(f"SELECT COALESCE(SUM(valor_total),0) FROM abastecimentos a WHERE {ativo('a','abastecimentos')}{data_where('a.data_abastecimento','Mês',mm,ano)}")
            if cm: cost += one(f"SELECT COALESCE(SUM(valor),0) FROM manutencoes m WHERE {ativo('m','manutencoes')}{data_where('m.data_manutencao','Mês',mm,ano)}")
            if cf:
                cost += one(f"SELECT COALESCE(SUM(total),0) FROM folha_funcionarios f WHERE f.mes='{mm:02d}' AND f.ano='{ano}'")
            out['mensal'].append([mm,rec,cost,rec-cost])
        return out
    finally:
        c.close()


def _v84_7_pdf(self,caminho,tipo='Total',mes=None,ano=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    r = self.carregar_resumo(tipo,mes,ano); d = _v84_7_detalhes(self,tipo,mes,ano,20)
    path = Path(caminho); path.parent.mkdir(parents=True,exist_ok=True)
    doc = SimpleDocTemplate(str(path),pagesize=A4,leftMargin=12*mm,rightMargin=12*mm,topMargin=15*mm,bottomMargin=16*mm,title='Relatório Gerencial Premium - CW Transportadora',author='CW Transportadora')
    st=getSampleStyleSheet()
    st.add(ParagraphStyle(name='R47Title',parent=st['Title'],fontName='Helvetica-Bold',fontSize=21,leading=24,textColor=colors.HexColor('#0F172A'),spaceAfter=5))
    st.add(ParagraphStyle(name='R47H',parent=st['Heading2'],fontName='Helvetica-Bold',fontSize=12.5,leading=15,textColor=colors.HexColor('#0F172A'),spaceBefore=8,spaceAfter=6))
    st.add(ParagraphStyle(name='R47Small',parent=st['Normal'],fontSize=8.3,leading=10.5,textColor=colors.HexColor('#475569')))
    st.add(ParagraphStyle(name='R47Note',parent=st['Normal'],fontSize=7.7,leading=10,textColor=colors.HexColor('#64748B')))
    def money(v): return f"R$ {float(v or 0):,.2f}".replace(',','X').replace('.',',').replace('X','.')
    def safe(v):
        s = str(v if v not in (None,'') else '—')
        return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    def cell(v): return Paragraph(safe(v),st['R47Small'])
    def table(headers,data,widths):
        vals=[[cell(x) for x in headers]]+[[cell(x) for x in row] for row in data]
        t=Table(vals,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0F172A')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),.25,colors.HexColor('#CBD5E1')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F8FAFC')]),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)])); return t
    empresa=str(settings.configuracoes.get('empresa') or 'CW TRANSPORTADORA').strip().upper()
    periodo=r['periodo']; emitido=datetime.now().strftime('%d/%m/%Y %H:%M')
    story=[Paragraph(empresa,st['R47Title']),Paragraph('RELATÓRIO GERENCIAL PREMIUM',st['R47H']),Paragraph(f'Período: {safe(periodo)} · Emitido em {emitido}',st['R47Small']),Spacer(1,4*mm)]
    story += [Paragraph('Resumo financeiro',st['R47H']),table(['Indicador','Valor'],[['Receitas',money(r['receitas'])],['Despesas',money(r['despesas'])],['Resultado',money(r['resultado'])],['Margem',f"{r['margem']:.1f}%"],['A receber',money(r['a_receber'])],['A pagar',money(r['a_pagar'])]],[80*mm,88*mm])]
    story += [Paragraph('Operação e custos',st['R47H']),table(['Indicador','Valor'],[['Notas fiscais',r['total_notas']],['Valor das mercadorias',money(r['valor_notas'])],['Frete das notas',money(r['frete_notas'])],['Viagens',r['total_viagens']],['Frete das viagens',money(r['frete_viagens'])],['Custo das viagens',money(r['custo_viagens'])],['Lucro das viagens',money(r['lucro_viagens'])],['Folha',money(r['folha'])],['Combustível',money(r['combustivel'])],['Manutenção',money(r['manutencao'])]],[80*mm,88*mm])]
    if d['mensal']:
        nomes=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
        story += [Paragraph('Evolução financeira',st['R47H']),table(['Mês','Receita','Custos','Resultado'],[[nomes[x[0]-1],money(x[1]),money(x[2]),money(x[3])] for x in d['mensal']],[30*mm,46*mm,46*mm,46*mm])]
    story += [PageBreak(),Paragraph('Detalhamento operacional',st['R47H'])]
    if d['viagens']: story += [table(['ID','Saída','Veículo','Motorista','Receita','Custo','Lucro','Status'],[[x[0],x[1],x[2],x[3],money(x[4]),money(x[5]),money(x[6]),x[7]] for x in d['viagens']],[13*mm,22*mm,23*mm,29*mm,22*mm,22*mm,22*mm,25*mm])]
    else: story += [Paragraph('Nenhuma viagem detalhada disponível no período.',st['R47Small'])]
    story += [Paragraph('Ranking de clientes',st['R47H'])]
    if d['clientes']: story += [table(['Cliente','Notas','Frete','Mercadorias'],[[x[0],x[1],money(x[2]),money(x[3])] for x in d['clientes']],[70*mm,20*mm,38*mm,40*mm])]
    else: story += [Paragraph('Nenhum cliente com movimentação no período.',st['R47Small'])]
    story += [Paragraph('Frota',st['R47H'])]
    if d['veiculos']: story += [table(['ID','Placa','Modelo','Motorista','Média km/L'],[[x[0],x[1],x[2],x[3],x[4] if x[4] is not None else '—'] for x in d['veiculos']],[15*mm,32*mm,43*mm,50*mm,30*mm])]
    else: story += [Paragraph('Nenhum veículo cadastrado.',st['R47Small'])]
    story += [PageBreak(),Paragraph('Financeiro e folha de pagamento',st['R47H'])]
    if d['contas']: story += [table(['Descrição','Tipo','Valor','Vencimento','Status'],[[x[0],x[1],money(x[2]),x[3],x[4]] for x in d['contas']],[58*mm,28*mm,30*mm,30*mm,32*mm])]
    else: story += [Paragraph('Nenhuma conta encontrada no período.',st['R47Small'])]
    story += [Paragraph('Folha de pagamento',st['R47H'])]
    if d['folha']:
        story += [table(['Competência','Funcionário','Salário','Vale','Horas','Extra','Outros','Total','Status'],[[f'{x[0]}/{x[1]}',x[2],money(x[3]),money(x[4]),f'{float(x[5] or 0):,.2f}',money(x[7]),money(x[8]),money(x[9]),x[10]] for x in d['folha']],[18*mm,41*mm,25*mm,22*mm,21*mm,24*mm,24*mm,25*mm,20*mm])]
    else: story += [Paragraph('Nenhum lançamento de folha encontrado no período.',st['R47Small'])]
    story += [Paragraph('Abastecimentos',st['R47H'])]
    if d['combustivel']: story += [table(['Data','Veículo','KM','Litros','Valor','km/L','Custo/km'],[[x[0],x[1],f'{float(x[2] or 0):,.0f}',f'{float(x[3] or 0):,.1f}',money(x[4]),f'{float(x[5] or 0):,.2f}' if x[5] is not None else '—',money(x[6]) if x[6] is not None else '—'] for x in d['combustivel']],[25*mm,35*mm,25*mm,25*mm,28*mm,25*mm,28*mm])]
    else: story += [Paragraph('Nenhum abastecimento detalhado disponível.',st['R47Small'])]
    story += [Paragraph('Manutenções',st['R47H'])]
    if d['manutencoes']: story += [table(['Data','Veículo','Tipo','Descrição','Valor','Próx. KM','Status'],[[x[0],x[1],x[2],x[3],money(x[4]),x[5] if x[5] is not None else '—',x[6]] for x in d['manutencoes']],[24*mm,30*mm,25*mm,45*mm,25*mm,25*mm,23*mm])]
    else: story += [Paragraph('Nenhuma manutenção detalhada disponível.',st['R47Small'])]
    story += [Spacer(1,5*mm),Paragraph('Critério: o relatório consolida os registros ativos disponíveis no banco no momento da emissão. Não são realizados rateios, estimativas ou preenchimento de dados inexistentes. Os detalhes operacionais são limitados aos registros mais recentes para manter o PDF legível.',st['R47Note'])]
    def footer(canvas,doc):
        canvas.saveState(); canvas.setFont('Helvetica',7); canvas.setFillColor(colors.HexColor('#64748B')); canvas.drawString(12*mm,8*mm,'CW Transportadora · Relatório Gerencial Premium V84.7'); canvas.drawRightString(A4[0]-12*mm,8*mm,f'Página {doc.page}'); canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer); return str(path)

RelatoriosService.detalhes_premium = _v84_7_detalhes
RelatoriosService.gerar_pdf = _v84_7_pdf
