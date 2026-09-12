"""
Servico de viagem.
"""
from datetime import datetime
from utils.database.viagens import (
    criar_viagem as db_criar_viagem,
    listar_viagens as db_listar_viagens,
    listar_notas_da_viagem,
    buscar_detalhes_viagem,
    finalizar_viagem,
    apagar_viagem as db_apagar_viagem,
    alterar_status_viagem,
)
from utils.database.notas import calcular_resumo_notas
from utils.database.caminhoes import listar_caminhoes
from utils.database.clientes import buscar_clientes_por_nome


from services.seguranca_service import exigir_permissao
from services.auditoria_service import auditoria_service, ACAO_CONFIG_ALTERADA
from domain.capacidade import validar_capacidade as validar_capacidade_dominio
from domain.frota import validar_uso_em_viagem
from domain.financeiro import calcular_rentabilidade

class ViagemService:
    def listar_caminhoes_disponiveis(self):
        """
        Retorna lista de tuplas:
        [(id, placa, modelo, motorista, capacidade_kg), ...]
        """
        caminhoes = listar_caminhoes()
        resultado = []
        for c in caminhoes:
            # O banco retorna tupla: (id, placa, modelo, motorista, capacidade_kg)
            if isinstance(c, (list, tuple)) and len(c) >= 5:
                resultado.append((
                    c[0], c[1] or "", c[2] or "", c[3] or "", c[4] or 0,
                    c[5] if len(c) > 5 else "ATIVO",
                ))
        return resultado

    def validar_capacidade(self, cam_id, notas_ids):
        if not notas_ids:
            return True, "Sem notas", None

        resumo = calcular_resumo_notas(notas_ids)
        peso_total = resumo.get("peso_total", 0)

        caminhoes = self.listar_caminhoes_disponiveis()
        caminhao = next((c for c in caminhoes if c[0] == cam_id), None)
        if not caminhao:
            return False, "Caminhão não encontrado", None

        capacidade = caminhao[4]
        validar_uso_em_viagem(caminhao[5] if len(caminhao) > 5 else "ATIVO")
        try:
            validar_capacidade_dominio(peso_total=peso_total, capacidade_kg=capacidade)
        except ValueError as exc:
            return False, str(exc), None
        return True, "OK", None

    def criar_viagem_com_notas(self, cam_id, notas_ids, motorista, data_saida=None):
        exigir_permissao("criar_viagem", "criar")
        data_saida = data_saida or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        viagem_id = db_criar_viagem(cam_id, notas_ids, data_saida, motorista)
        auditoria_service.registrar(ACAO_CONFIG_ALTERADA, "viagens", registro_afetado=viagem_id, operacao="CRIAR", caminhao_id=cam_id, notas=len(notas_ids))
        return viagem_id

    def listar_viagens(self, filtros=None):
        return db_listar_viagens()

    def obter_viagem(self, viagem_id):
        return buscar_detalhes_viagem(viagem_id)

    def buscar_clientes(self, termo):
        """
        Retorna lista de tuplas:
        [(id, nome, cnpj, cidade, uf), ...]
        """
        clientes = buscar_clientes_por_nome(termo)
        resultado = []
        for c in clientes:
            if isinstance(c, dict):
                resultado.append((
                    c.get("id"),
                    c.get("nome", ""),
                    c.get("cnpj", ""),
                    c.get("cidade", ""),
                    c.get("uf", ""),
                ))
            elif isinstance(c, (list, tuple)) and len(c) >= 5:
                resultado.append((c[0], c[1] or "", c[2] or "", c[3] or "", c[4] or ""))
        return resultado

    def listar_manifestos(self):
        from utils.database.notas import listar_manifestos
        return listar_manifestos("Geral")

    def listar_notas_cliente(
        self, cliente_id, apenas_disponiveis=True, excluir_vinculadas=True,
        manifesto_id=None, termo=""
    ):
        from utils.database.notas import listar_notas_por_cliente
        return listar_notas_por_cliente(
            cliente_id, apenas_disponiveis, excluir_vinculadas, manifesto_id, termo
        )

    def calcular_resumo_selecao(self, notas_ids):
        return calcular_resumo_notas(notas_ids)

    def alterar_status(self, viagem_id, novo_status):
        exigir_permissao("historico", "editar")
        resultado = alterar_status_viagem(viagem_id, novo_status)
        auditoria_service.registrar(ACAO_CONFIG_ALTERADA, "viagens", registro_afetado=viagem_id, operacao="ALTERAR_STATUS", novo_status=novo_status)
        return resultado


    def obter_rentabilidade(self, viagem_id):
        """Retorna a rentabilidade consolidada com custos explicitamente vinculados."""
        from services.rentabilidade_service import rentabilidade_service
        return rentabilidade_service.por_viagem(viagem_id)

    def registrar_custos(self, viagem_id, *, combustivel=0, pedagio=0, motorista=0, outros=0):
        """Registra custos da viagem e recalcula custo, lucro e margem atomically."""
        exigir_permissao("historico", "editar")
        from utils.database._conexao import conectar, registrar_sync
        from datetime import datetime
        conn = conectar()
        try:
            row = conn.execute("SELECT frete_total FROM viagens WHERE id=?", (int(viagem_id),)).fetchone()
            if not row:
                raise ValueError("Viagem não encontrada.")
            rent = calcular_rentabilidade(
                frete_recebido=row[0], combustivel=combustivel, pedagio=pedagio, motorista=motorista, outros=outros
            )
            conn.execute("""
                UPDATE viagens SET custo_combustivel=?, custo_pedagio=?, custo_motorista=?, custo_outros=?,
                    custo_total=?, lucro_total=?, margem_percentual=?, atualizado_em=? WHERE id=?
            """, (combustivel, pedagio, motorista, outros, rent["custo_total"], rent["lucro"], rent["margem_percentual"], datetime.now().isoformat(timespec="seconds"), int(viagem_id)))
            registrar_sync(conn.cursor(), "viagens", int(viagem_id))
            conn.commit()
            auditoria_service.registrar(ACAO_CONFIG_ALTERADA, "viagens", registro_afetado=viagem_id, operacao="REGISTRAR_CUSTOS", **rent)
            return rent
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def apagar_viagem(self, viagem_id):
        exigir_permissao("historico", "excluir")
        resultado = db_apagar_viagem(viagem_id)
        auditoria_service.registrar(ACAO_CONFIG_ALTERADA, "viagens", registro_afetado=viagem_id, operacao="EXCLUIR", notas_liberadas=resultado)
        return resultado

    def apagar_todos_dados_exceto_usuarios(self):
        exigir_permissao("configuracoes", "excluir")
        """Executa o reset operacional completo, preservando usuários e permissões."""
        from utils.database import resetar_dados_operacionais
        resetar_dados_operacionais()
        return True


viagem_service = ViagemService()
