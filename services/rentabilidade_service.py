"""Rentabilidade por viagem com atribuição explícita de custos."""
from utils.database._conexao import conectar
from services.seguranca_service import exigir_permissao

class RentabilidadeService:
    def por_viagem(self, viagem_id):
        exigir_permissao("dashboard", "visualizar")
        conn = conectar()
        try:
            v = conn.execute("SELECT id, frete_total, custo_combustivel, custo_pedagio, custo_motorista, custo_outros FROM viagens WHERE id=? AND COALESCE(deletado,0)=0", (int(viagem_id),)).fetchone()
            if not v:
                raise ValueError("Viagem não encontrada.")
            fuel_linked = float(conn.execute("SELECT COALESCE(SUM(valor_total),0) FROM abastecimentos WHERE viagem_id=? AND COALESCE(deletado,0)=0", (int(viagem_id),)).fetchone()[0] or 0)
            fuel_manual = float(v[2] or 0)
            fuel = fuel_linked if fuel_linked > 0 else fuel_manual
            manut = float(conn.execute("SELECT COALESCE(SUM(valor),0) FROM manutencoes WHERE viagem_id=? AND COALESCE(deletado,0)=0", (int(viagem_id),)).fetchone()[0] or 0)
            pagar = float(conn.execute("SELECT COALESCE(SUM(valor),0) FROM contas WHERE viagem_id=? AND LOWER(tipo) IN ('a pagar','pagar','saida') AND COALESCE(deletado,0)=0", (int(viagem_id),)).fetchone()[0] or 0)
            receber = float(conn.execute("SELECT COALESCE(SUM(valor),0) FROM contas WHERE viagem_id=? AND LOWER(tipo) IN ('a receber','receber','entrada') AND COALESCE(deletado,0)=0", (int(viagem_id),)).fetchone()[0] or 0)
            pedagio = float(v[3] or 0); motorista = float(v[4] or 0); outros = float(v[5] or 0)
            custo_total = fuel + manut + pagar + pedagio + motorista + outros
            receita_total = float(v[1] or 0) + receber
            lucro = receita_total - custo_total
            margem = (lucro / receita_total * 100) if receita_total else 0.0
            return {"viagem_id": int(v[0]), "frete": float(v[1] or 0), "contas_receber": receber, "combustivel": fuel,
                    "manutencao": manut, "contas_pagar": pagar, "pedagio": pedagio, "motorista": motorista, "outros": outros,
                    "custo_total": custo_total, "receita_total": receita_total, "lucro": lucro, "margem": margem,
                    "custos_vinculados": fuel_linked + manut + pagar, "combustivel_manual": fuel_manual}
        finally:
            conn.close()

rentabilidade_service = RentabilidadeService()

def rentabilidade_viagem(viagem_id):
    return rentabilidade_service.por_viagem(viagem_id)
