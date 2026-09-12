from __future__ import annotations

from services.seguranca_service import exigir_permissao
from utils.database import (
    listar_viagens,
    listar_notas_da_viagem,
    finalizar_viagem,
    finalizar_nota_entregue,
    finalizar_notas_entregues,
    buscar_detalhes_viagem,
)


class HistoricoService:
    def listar_viagens(self):
        return listar_viagens()

    def listar_notas_da_viagem(self, viagem_id):
        return listar_notas_da_viagem(viagem_id)

    def finalizar_viagem(self, viagem_id, data_retorno):
        exigir_permissao("historico", "editar")
        resultado = finalizar_viagem(viagem_id, data_retorno)
        from services.auditoria_service import auditoria_service
        auditoria_service.registrar("VIAGEM_FINALIZADA", "Histórico", registro_afetado=viagem_id, viagem_id=viagem_id, data_retorno=data_retorno)
        return resultado

    def finalizar_nota_entregue(self, nota_id):
        exigir_permissao("historico", "editar")
        resultado = finalizar_nota_entregue(nota_id)
        from services.auditoria_service import auditoria_service
        auditoria_service.registrar("NOTA_FINALIZADA", "Histórico", registro_afetado=nota_id, nota_id=nota_id)
        return resultado

    def finalizar_notas_entregues(self, notas_ids):
        exigir_permissao("historico", "editar")
        resultado = finalizar_notas_entregues(notas_ids)
        from services.auditoria_service import auditoria_service
        auditoria_service.registrar("NOTAS_FINALIZADAS", "Histórico", registro_afetado=','.join(map(str, notas_ids)), quantidade=resultado)
        return resultado

    def buscar_detalhes_viagem(self, viagem_id):
        return buscar_detalhes_viagem(viagem_id)


historico_service = HistoricoService()
