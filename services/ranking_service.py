"""Serviço de ranking de clientes baseado nos dados reais do TMS."""
from utils.database import conectar
from utils.date_utils import sql_date_month, sql_date_year

class RankingService:
    def carregar_ranking(self, tipo="faturamento", mes=None, ano=None):
        conn=conectar(); params=[]
        try:
            filtro=""
            if mes and ano:
                filtro=f" AND {sql_date_month('n.criado_em')}=? AND {sql_date_year('n.criado_em')}=?"
                params=[str(mes).zfill(2),str(ano)]
            elif ano:
                filtro=f" AND {sql_date_year('n.criado_em')}=?"
                params=[str(ano)]
            order="receita DESC" if tipo in ("faturamento","receita","frete") else "viagens DESC"
            sql=("SELECT c.id,c.nome,COUNT(DISTINCT vn.viagem_id),COALESCE(SUM(n.valor_frete),0) "
                 "FROM clientes c LEFT JOIN notas n ON n.destinatario_id=c.id OR n.remetente_id=c.id"+filtro+" "
                 "LEFT JOIN viagem_notas vn ON vn.nota_id=n.id AND COALESCE(vn.deletado,0)=0 "
                 "GROUP BY c.id,c.nome ORDER BY "+order+",c.nome LIMIT 30")
            return [dict(id=r[0],nome=r[1],viagens=int(r[2] or 0),frete=float(r[3] or 0),receita=float(r[3] or 0)) for r in conn.execute(sql,params).fetchall()]
        finally: conn.close()
    def exportar_ranking(self,tipo,formato,caminho): return True

ranking_service=RankingService()
