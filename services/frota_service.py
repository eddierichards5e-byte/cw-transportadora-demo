from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from services.seguranca_service import exigir_permissao
from utils.database import conectar, listar_caminhoes, registrar_sync
from utils.database._conexao import novo_id_global
from utils.database.caminhoes import alterar_status_caminhao
from utils.date_utils import sql_date_month, sql_date_year
from utils.logger import get_logger

logger = get_logger(__name__)


class FrotaService:
    def alterar_status(self, caminhao_id, novo_status):
        """Altera o status operacional e registra a mudança para auditoria."""
        exigir_permissao("frota", "editar")
        status = alterar_status_caminhao(caminhao_id, novo_status)
        from services.auditoria_service import auditoria_service
        auditoria_service.registrar(
            "FROTA_STATUS_ALTERADO",
            "Frota",
            registro_afetado=caminhao_id,
            caminhao_id=caminhao_id,
            novo_status=status,
        )
        return status


    def listar_viagens_para_vinculo(self, veiculo=None):
        """Lista viagens para vincular custos, filtrando pelo veículo quando informado."""
        conn = conectar()
        try:
            sql = """SELECT v.id, v.data_saida, v.status, c.placa, c.modelo
                     FROM viagens v LEFT JOIN caminhoes c ON c.id=v.caminhao_id
                     WHERE COALESCE(v.deletado,0)=0"""
            params=[]
            if veiculo:
                sql += " AND (c.placa=? OR c.modelo=? OR (COALESCE(c.placa,'') || ' · ' || COALESCE(c.modelo,''))=?)"
                params.extend([veiculo, veiculo, veiculo])
            sql += " ORDER BY v.id DESC"
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def obter_viagem_vinculada(self, tabela, registro_id):
        if tabela not in {"abastecimentos", "manutencoes"}:
            raise ValueError("Tipo de custo não permitido.")
        conn = conectar()
        try:
            row = conn.execute(f"SELECT viagem_id FROM {tabela} WHERE id=?", (int(registro_id),)).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def vincular_abastecimento_viagem(self, abastecimento_id, viagem_id):
        exigir_permissao("combustivel", "editar")
        return self._vincular_custo("abastecimentos", abastecimento_id, viagem_id)

    def vincular_manutencao_viagem(self, manutencao_id, viagem_id):
        exigir_permissao("manutencao", "editar")
        return self._vincular_custo("manutencoes", manutencao_id, viagem_id)

    def desvincular_abastecimento_viagem(self, abastecimento_id):
        exigir_permissao("combustivel", "editar")
        return self._vincular_custo("abastecimentos", abastecimento_id, None)

    def desvincular_manutencao_viagem(self, manutencao_id):
        exigir_permissao("manutencao", "editar")
        return self._vincular_custo("manutencoes", manutencao_id, None)

    def _vincular_custo(self, tabela, registro_id, viagem_id):
        if tabela not in {"abastecimentos", "manutencoes"}:
            raise ValueError("Tipo de custo não permitido.")
        conn = conectar()
        try:
            row = conn.execute(f"SELECT id, veiculo, viagem_id FROM {tabela} WHERE id=?", (int(registro_id),)).fetchone()
            if not row:
                raise ValueError("Registro de custo não encontrado.")
            if viagem_id is not None:
                viagem = conn.execute("""SELECT v.id, c.placa, c.modelo
                    FROM viagens v LEFT JOIN caminhoes c ON c.id=v.caminhao_id
                    WHERE v.id=? AND COALESCE(v.deletado,0)=0""", (int(viagem_id),)).fetchone()
                if not viagem:
                    raise ValueError("Viagem não encontrada.")
                veiculo = str(row[1] or '').strip().lower()
                identificadores = {str(viagem[1] or '').strip().lower(), str(viagem[2] or '').strip().lower()}
                if veiculo and veiculo not in identificadores:
                    raise ValueError("O custo só pode ser vinculado à viagem do mesmo veículo.")
            conn.execute(f"UPDATE {tabela} SET viagem_id=? WHERE id=?", (None if viagem_id is None else int(viagem_id), int(registro_id)))
            registrar_sync(conn.cursor(), tabela, int(registro_id))
            conn.commit()
            from services.auditoria_service import auditoria_service
            auditoria_service.registrar("CUSTO_VIAGEM_VINCULADO" if viagem_id is not None else "CUSTO_VIAGEM_DESVINCULADO", tabela, registro_afetado=registro_id, viagem_id=viagem_id)
            return viagem_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def listar_abastecimentos(self, tipo_periodo: str, mes: str, ano: str, busca: str):
        where = []
        params = []

        if tipo_periodo == "Mês":
            where.append("CASE WHEN instr(COALESCE(data_abastecimento,''), '/') > 0 THEN substr(COALESCE(data_abastecimento,''), 4, 2) ELSE substr(COALESCE(data_abastecimento,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(data_abastecimento,''), '/') > 0 THEN substr(COALESCE(data_abastecimento,''), 7, 4) ELSE substr(COALESCE(data_abastecimento,''), 1, 4) END = ?")
            params.extend([mes, ano])
        elif tipo_periodo == "Ano":
            where.append("CASE WHEN instr(COALESCE(data_abastecimento,''), '/') > 0 THEN substr(COALESCE(data_abastecimento,''), 7, 4) ELSE substr(COALESCE(data_abastecimento,''), 1, 4) END = ?")
            params.append(ano)

        if busca:
            where.append("(veiculo LIKE ? OR motorista LIKE ? OR posto LIKE ?)")
            params.extend([f"%{busca}%", f"%{busca}%", f"%{busca}%"])

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(f"""
                SELECT
                    id,
                    data_abastecimento,
                    veiculo,
                    motorista,
                    km_atual,
                    litros,
                    valor_litro,
                    valor_total,
                    media_km_l,
                    custo_km,
                    posto,
                    observacao
                FROM abastecimentos
                {where_sql}
                ORDER BY id DESC
            """, params)
            return cursor.fetchall()
        finally:
            conn.close()

    def obter_abastecimento(self, abastecimento_id: Any):
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    id,
                    data_abastecimento,
                    veiculo,
                    motorista,
                    km_atual,
                    litros,
                    valor_litro,
                    valor_total,
                    media_km_l,
                    custo_km,
                    posto,
                    observacao
                FROM abastecimentos
                WHERE id = ?
            """, (abastecimento_id,))
            return cursor.fetchone()
        finally:
            conn.close()

    def salvar_abastecimento(self, abastecimento_id: Any, valores: Sequence[Any]) -> Any:
        exigir_permissao("combustivel", "editar" if abastecimento_id else "criar")
        conn = conectar()
        cursor = conn.cursor()
        try:
            if abastecimento_id:
                cursor.execute("""
                    UPDATE abastecimentos
                    SET data_abastecimento = ?,
                        veiculo = ?,
                        motorista = ?,
                        km_atual = ?,
                        litros = ?,
                        valor_litro = ?,
                        valor_total = ?,
                        media_km_l = ?,
                        custo_km = ?,
                        posto = ?,
                        observacao = ?
                    WHERE id = ?
                """, tuple(valores) + (abastecimento_id,))
                registrar_sync(cursor, "abastecimentos", abastecimento_id)
                registro_id = abastecimento_id
            else:
                cursor.execute("""
                    INSERT INTO abastecimentos (
                        id,
                        data_abastecimento,
                        veiculo,
                        motorista,
                        km_atual,
                        litros,
                        valor_litro,
                        valor_total,
                        media_km_l,
                        custo_km,
                        posto,
                        observacao
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (novo_id_global(), *tuple(valores)))
                registro_id = cursor.lastrowid
                registrar_sync(cursor, "abastecimentos", registro_id)

            conn.commit()
            from services.auditoria_service import auditoria_service
            auditoria_service.registrar("ABASTECIMENTO_ATUALIZADO" if abastecimento_id else "ABASTECIMENTO_CRIADO", "Combustível", registro_afetado=registro_id)
            return registro_id
        finally:
            conn.close()

    def excluir_abastecimento(self, abastecimento_id: Any) -> None:
        exigir_permissao("combustivel", "excluir")
        conn = conectar()
        cursor = conn.cursor()
        try:
            registrar_sync(cursor, "abastecimentos", abastecimento_id, "DELETE")
            cursor.execute("DELETE FROM abastecimentos WHERE id = ?", (abastecimento_id,))
            conn.commit()
            from services.auditoria_service import auditoria_service
            auditoria_service.registrar("ABASTECIMENTO_EXCLUIDO", "Combustível", registro_afetado=abastecimento_id)
        finally:
            conn.close()

    def calcular_media_e_custo(
        self,
        veiculo: str,
        km_atual: float,
        litros: float,
        valor_total: float,
        abastecimento_id: Any = None,
    ) -> Tuple[float, float]:
        conn = conectar()
        cursor = conn.cursor()
        try:
            if abastecimento_id:
                cursor.execute("""
                    SELECT km_atual
                    FROM abastecimentos
                    WHERE veiculo = ?
                      AND id != ?
                      AND km_atual < ?
                    ORDER BY km_atual DESC
                    LIMIT 1
                """, (veiculo, abastecimento_id, km_atual))
            else:
                cursor.execute("""
                    SELECT km_atual
                    FROM abastecimentos
                    WHERE veiculo = ?
                      AND km_atual < ?
                    ORDER BY km_atual DESC
                    LIMIT 1
                """, (veiculo, km_atual))
            anterior = cursor.fetchone()
        finally:
            conn.close()

        if not anterior:
            return 0, 0

        km_rodado = km_atual - float(anterior[0] or 0)
        if km_rodado <= 0 or litros <= 0:
            return 0, 0

        media = km_rodado / litros
        custo_km = valor_total / km_rodado
        return media, custo_km

    def listar_manutencoes(self, tipo_periodo: str, mes: str, ano: str, busca: str):
        where = []
        params = []

        if tipo_periodo == "Mês":
            where.append("CASE WHEN instr(COALESCE(data_manutencao,''), '/') > 0 THEN substr(COALESCE(data_manutencao,''), 4, 2) ELSE substr(COALESCE(data_manutencao,''), 6, 2) END = ? AND CASE WHEN instr(COALESCE(data_manutencao,''), '/') > 0 THEN substr(COALESCE(data_manutencao,''), 7, 4) ELSE substr(COALESCE(data_manutencao,''), 1, 4) END = ?")
            params.extend([mes, ano])
        elif tipo_periodo == "Ano":
            where.append("CASE WHEN instr(COALESCE(data_manutencao,''), '/') > 0 THEN substr(COALESCE(data_manutencao,''), 7, 4) ELSE substr(COALESCE(data_manutencao,''), 1, 4) END = ?")
            params.append(ano)

        if busca:
            where.append("(veiculo LIKE ? OR oficina LIKE ? OR tipo LIKE ? OR descricao LIKE ?)")
            params.extend([f"%{busca}%", f"%{busca}%", f"%{busca}%", f"%{busca}%"])

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(f"""
                SELECT
                    id,
                    data_manutencao,
                    veiculo,
                    km_atual,
                    tipo,
                    descricao,
                    oficina,
                    valor,
                    proxima_revisao_km,
                    status,
                    observacao
                FROM manutencoes
                {where_sql}
                ORDER BY id DESC
            """, params)
            return cursor.fetchall()
        finally:
            conn.close()

    def obter_manutencao(self, manutencao_id: Any):
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    id,
                    data_manutencao,
                    veiculo,
                    km_atual,
                    tipo,
                    descricao,
                    oficina,
                    valor,
                    proxima_revisao_km,
                    status,
                    observacao
                FROM manutencoes
                WHERE id = ?
            """, (manutencao_id,))
            return cursor.fetchone()
        finally:
            conn.close()

    def salvar_manutencao(self, manutencao_id: Any, valores: Sequence[Any]) -> Any:
        exigir_permissao("manutencao", "editar" if manutencao_id else "criar")
        conn = conectar()
        cursor = conn.cursor()
        try:
            if manutencao_id:
                cursor.execute("""
                    UPDATE manutencoes
                    SET data_manutencao = ?,
                        veiculo = ?,
                        km_atual = ?,
                        tipo = ?,
                        descricao = ?,
                        oficina = ?,
                        valor = ?,
                        proxima_revisao_km = ?,
                        status = ?,
                        observacao = ?
                    WHERE id = ?
                """, tuple(valores) + (manutencao_id,))
                registrar_sync(cursor, "manutencoes", manutencao_id)
                registro_id = manutencao_id
            else:
                cursor.execute("""
                    INSERT INTO manutencoes (
                        id,
                        data_manutencao,
                        veiculo,
                        km_atual,
                        tipo,
                        descricao,
                        oficina,
                        valor,
                        proxima_revisao_km,
                        status,
                        observacao
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (novo_id_global(), *tuple(valores)))
                registro_id = cursor.lastrowid
                registrar_sync(cursor, "manutencoes", registro_id)

            conn.commit()
            from services.auditoria_service import auditoria_service
            auditoria_service.registrar("MANUTENCAO_ATUALIZADA" if manutencao_id else "MANUTENCAO_CRIADA", "Manutenção", registro_afetado=registro_id)
            return registro_id
        finally:
            conn.close()

    def excluir_manutencao(self, manutencao_id: Any) -> None:
        exigir_permissao("manutencao", "excluir")
        conn = conectar()
        cursor = conn.cursor()
        try:
            registrar_sync(cursor, "manutencoes", manutencao_id, "DELETE")
            cursor.execute("DELETE FROM manutencoes WHERE id = ?", (manutencao_id,))
            conn.commit()
            from services.auditoria_service import auditoria_service
            auditoria_service.registrar("MANUTENCAO_EXCLUIDA", "Manutenção", registro_afetado=manutencao_id)
        finally:
            conn.close()

    # Tabelas permitidas para consulta de veículos — whitelist explícita para evitar SQL injection
    _TABELAS_VEICULOS_PERMITIDAS = frozenset({"abastecimentos", "manutencoes"})

    def listar_veiculos_disponiveis(self, tabela_historico: str) -> List[str]:
        if tabela_historico not in self._TABELAS_VEICULOS_PERMITIDAS:
            raise ValueError(f"Tabela não permitida: {tabela_historico!r}")

        nomes: List[str] = []

        # Uma unica conexao compartilhada pelas duas consultas desta operacao
        # (antes eram 2 conexoes SQLite abertas em sequencia).
        conn = conectar()
        try:
            for caminhao in listar_caminhoes(conn=conn):
                modelo = caminhao[2] or ""
                placa = caminhao[1] or ""
                nome = f"{modelo} - {placa}" if placa else modelo
                if nome.strip() and nome not in nomes:
                    nomes.append(nome)
        except Exception as erro:
            logger.warning(f"Erro ao listar caminhões para veículos disponíveis: {erro}")

        cursor = conn.cursor()
        try:
            # tabela_historico validada pela whitelist acima — seguro usar f-string
            cursor.execute(f"""
                SELECT DISTINCT veiculo
                FROM {tabela_historico}
                WHERE veiculo IS NOT NULL
                  AND veiculo != ''
                ORDER BY veiculo
            """)
            for item in cursor.fetchall():
                nome = item[0]
                if nome and nome not in nomes:
                    nomes.append(nome)
        except Exception as erro:
            logger.warning(f"Erro ao listar veículos históricos da tabela {tabela_historico}: {erro}")
        finally:
            conn.close()

        # Não inventar veículos quando a frota real estiver vazia.
        # A tela deve refletir somente veículos efetivamente cadastrados ou
        # presentes em históricos reais.
        return nomes



    def inteligencia_frota(self, limite=20):
        """Indicadores reais por veículo: uso, custos, km/L e manutenção.

        Só calcula métricas quando há dados suficientes; não inventa quilometragem
        ou custo por km. Veículos sem histórico continuam visíveis.
        """
        conn = conectar()
        try:
            caminhoes = conn.execute("""
                SELECT id, placa, modelo, motorista, capacidade_kg, media_km_l
                FROM caminhoes
                ORDER BY id
            """).fetchall()
            resultado = []
            for c in caminhoes:
                cid, placa, modelo, motorista, capacidade, media_cadastrada = c
                viagens = conn.execute("""
                    SELECT COUNT(*), COALESCE(SUM(frete_total),0), COALESCE(SUM(custo_total),0),
                           COALESCE(SUM(lucro_total),0)
                    FROM viagens
                    WHERE caminhao_id=? AND COALESCE(deletado,0)=0
                """, (cid,)).fetchone()
                qtd, receita, custo_viagens, lucro_viagens = viagens

                # Combustível legado é identificado pelo texto do veículo.
                termos = [x for x in (placa, modelo) if x]
                fuel_rows = []
                if termos:
                    fuel_rows = conn.execute("""
                        SELECT km_atual, litros, valor_total
                        FROM abastecimentos
                        WHERE COALESCE(deletado,0)=0
                          AND (veiculo LIKE ? OR veiculo LIKE ?)
                        ORDER BY km_atual
                    """, (f"%{placa or ''}%", f"%{modelo or ''}%")).fetchall()
                km_l = 0.0
                custo_km = 0.0
                if len(fuel_rows) >= 2:
                    km = float(fuel_rows[-1][0] or 0) - float(fuel_rows[0][0] or 0)
                    litros = sum(float(r[1] or 0) for r in fuel_rows)
                    gasto = sum(float(r[2] or 0) for r in fuel_rows)
                    if km > 0 and litros > 0:
                        km_l = km / litros
                        custo_km = gasto / km

                manut = conn.execute("""
                    SELECT COUNT(*), COALESCE(SUM(valor),0),
                           COALESCE(SUM(CASE WHEN proxima_revisao_km>0 THEN 1 ELSE 0 END),0)
                    FROM manutencoes
                    WHERE COALESCE(deletado,0)=0 AND (veiculo LIKE ? OR veiculo LIKE ?)
                """, (f"%{placa or ''}%", f"%{modelo or ''}%")).fetchone()
                manut_qtd, manut_custo, revisoes = manut

                ultima_km = None
                if fuel_rows:
                    ultima_km = float(fuel_rows[-1][0] or 0)
                proxima = conn.execute("""
                    SELECT MIN(proxima_revisao_km) FROM manutencoes
                    WHERE COALESCE(deletado,0)=0 AND proxima_revisao_km>0
                      AND (veiculo LIKE ? OR veiculo LIKE ?)
                """, (f"%{placa or ''}%", f"%{modelo or ''}%")).fetchone()[0]
                revisao_alerta = bool(ultima_km and proxima and ultima_km >= float(proxima))

                margem = (float(lucro_viagens or 0) / float(receita) * 100) if receita else 0.0
                resultado.append({
                    "id": cid, "placa": placa or "—", "modelo": modelo or "—",
                    "motorista": motorista or "—", "viagens": int(qtd or 0),
                    "receita": round(float(receita or 0),2), "custo_viagens": round(float(custo_viagens or 0),2),
                    "lucro": round(float(lucro_viagens or 0),2), "margem": round(margem,2),
                    "km_l": round(km_l or float(media_cadastrada or 0),2), "custo_km": round(custo_km,4),
                    "manutencoes": int(manut_qtd or 0), "custo_manutencao": round(float(manut_custo or 0),2),
                    "revisao_alerta": revisao_alerta,
                })
            resultado.sort(key=lambda x: (x["margem"], x["lucro"]), reverse=True)
            return resultado[:int(limite)]
        finally:
            conn.close()


frota_service = FrotaService()
