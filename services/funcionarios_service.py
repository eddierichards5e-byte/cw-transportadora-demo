from __future__ import annotations

from typing import Any, List, Optional, Sequence

from utils.database import conectar, registrar_sync
from utils.database._conexao import novo_id_global
from services.seguranca_service import exigir_permissao


class FuncionariosService:
    def listar_funcionarios(self, busca: str):
        conn = conectar()
        cursor = conn.cursor()
        try:
            if busca:
                cursor.execute("""
                    SELECT
                        id,
                        nome,
                        cargo,
                        telefone,
                        data_admissao,
                        salario,
                        vale_refeicao,
                        status
                    FROM funcionarios
                    WHERE nome LIKE ? OR cargo LIKE ? OR telefone LIKE ?
                    ORDER BY nome
                """, (f"%{busca}%", f"%{busca}%", f"%{busca}%"))
            else:
                cursor.execute("""
                    SELECT
                        id,
                        nome,
                        cargo,
                        telefone,
                        data_admissao,
                        salario,
                        vale_refeicao,
                        status
                    FROM funcionarios
                    ORDER BY nome
                """)
            return cursor.fetchall()
        finally:
            conn.close()

    def obter_funcionario(self, funcionario_id: Any) -> Optional[Sequence[Any]]:
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    id,
                    nome,
                    cargo,
                    telefone,
                    data_admissao,
                    salario,
                    vale_refeicao,
                    status
                FROM funcionarios
                WHERE id = ?
            """, (funcionario_id,))
            return cursor.fetchone()
        finally:
            conn.close()

    def salvar_funcionario(self, funcionario_id: Any, dados: Sequence[Any]) -> Any:
        exigir_permissao("funcionarios", "editar" if funcionario_id else "criar")
        conn = conectar()
        cursor = conn.cursor()
        try:
            if funcionario_id:
                cursor.execute("""
                    UPDATE funcionarios
                    SET nome = ?,
                        cargo = ?,
                        telefone = ?,
                        data_admissao = ?,
                        salario = ?,
                        vale_refeicao = ?,
                        status = ?
                    WHERE id = ?
                """, tuple(dados) + (funcionario_id,))
                registrar_sync(cursor, "funcionarios", funcionario_id)
                registro_id = funcionario_id
            else:
                cursor.execute("""
                    INSERT INTO funcionarios
                    (
                        id,
                        nome,
                        cargo,
                        telefone,
                        data_admissao,
                        salario,
                        vale_refeicao,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (novo_id_global(), *tuple(dados)))
                registro_id = cursor.lastrowid
                registrar_sync(cursor, "funcionarios", registro_id)

            conn.commit()
            return registro_id
        finally:
            conn.close()

    def excluir_funcionario(self, funcionario_id: Any) -> None:
        exigir_permissao("funcionarios", "excluir")
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM folha_funcionarios WHERE funcionario_id = ?", (funcionario_id,))
            folha_ids = [item[0] for item in cursor.fetchall()]
            for folha_id in folha_ids:
                registrar_sync(cursor, "folha_funcionarios", folha_id, "DELETE")

            cursor.execute("DELETE FROM folha_funcionarios WHERE funcionario_id = ?", (funcionario_id,))
            registrar_sync(cursor, "funcionarios", funcionario_id, "DELETE")
            cursor.execute("DELETE FROM funcionarios WHERE id = ?", (funcionario_id,))
            conn.commit()
        finally:
            conn.close()

    def listar_folha_mes(self, mes: str, ano: str, busca: str):
        conn = conectar()
        cursor = conn.cursor()
        try:
            params = [mes, ano]
            filtro_busca = ""
            if busca:
                filtro_busca = "AND (funcionarios.nome LIKE ? OR funcionarios.cargo LIKE ?)"
                params.extend([f"%{busca}%", f"%{busca}%"])

            cursor.execute(f"""
                SELECT
                    funcionarios.id,
                    funcionarios.nome,
                    funcionarios.cargo,
                    folha_funcionarios.salario,
                    folha_funcionarios.vale_refeicao,
                    folha_funcionarios.qtd_horas_extra,
                    folha_funcionarios.valor_hora_extra,
                    folha_funcionarios.hora_extra,
                    folha_funcionarios.outros,
                    folha_funcionarios.total,
                    funcionarios.status
                FROM folha_funcionarios
                INNER JOIN funcionarios
                    ON funcionarios.id = folha_funcionarios.funcionario_id
                WHERE folha_funcionarios.mes = ?
                  AND folha_funcionarios.ano = ?
                  {filtro_busca}
                ORDER BY funcionarios.nome
            """, params)
            return cursor.fetchall()
        finally:
            conn.close()

    def listar_funcionarios_ativos(self):
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id, salario, vale_refeicao
                FROM funcionarios
                WHERE status = 'Ativo'
                ORDER BY nome
            """)
            return cursor.fetchall()
        finally:
            conn.close()

    def obter_folha_funcionario(self, funcionario_id: Any, mes: str, ano: str):
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    id,
                    salario,
                    vale_refeicao,
                    qtd_horas_extra,
                    valor_hora_extra,
                    hora_extra,
                    outros,
                    total
                FROM folha_funcionarios
                WHERE funcionario_id = ?
                  AND mes = ?
                  AND ano = ?
            """, (funcionario_id, mes, ano))
            return cursor.fetchone()
        finally:
            conn.close()

    def gerar_folha_todos(self, mes: str, ano: str) -> int:
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id, salario, vale_refeicao
                FROM funcionarios
                WHERE status = 'Ativo'
                ORDER BY nome
            """)
            funcionarios = cursor.fetchall()
            if not funcionarios:
                return 0

            for funcionario_id, salario, vale in funcionarios:
                cursor.execute("""
                    SELECT
                        id,
                        qtd_horas_extra,
                        valor_hora_extra,
                        hora_extra,
                        outros
                    FROM folha_funcionarios
                    WHERE funcionario_id = ?
                      AND mes = ?
                      AND ano = ?
                """, (funcionario_id, mes, ano))
                existente = cursor.fetchone()

                if existente:
                    folha_id = existente[0]
                    qtd_horas = float(existente[1] or 0)
                    valor_hora = float(existente[2] or 0)
                    hora_extra = float(existente[3] or 0)
                    outros = float(existente[4] or 0)
                    total = float(salario or 0) + float(vale or 0) + hora_extra + outros

                    cursor.execute("""
                        UPDATE folha_funcionarios
                        SET salario = ?,
                            vale_refeicao = ?,
                            qtd_horas_extra = ?,
                            valor_hora_extra = ?,
                            hora_extra = ?,
                            outros = ?,
                            total = ?
                        WHERE id = ?
                    """, (
                        float(salario or 0),
                        float(vale or 0),
                        qtd_horas,
                        valor_hora,
                        hora_extra,
                        outros,
                        total,
                        folha_id,
                    ))
                    registrar_sync(cursor, "folha_funcionarios", folha_id)
                else:
                    total = float(salario or 0) + float(vale or 0)
                    cursor.execute("""
                        INSERT INTO folha_funcionarios
                        (
                            id,
                            funcionario_id,
                            mes,
                            ano,
                            salario,
                            vale_refeicao,
                            qtd_horas_extra,
                            valor_hora_extra,
                            hora_extra,
                            outros,
                            total
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        novo_id_global(),
                        funcionario_id,
                        mes,
                        ano,
                        float(salario or 0),
                        float(vale or 0),
                        0,
                        0,
                        0,
                        0,
                        total,
                    ))
                    registrar_sync(cursor, "folha_funcionarios", cursor.lastrowid)

            conn.commit()
            return len(funcionarios)
        finally:
            conn.close()

    def salvar_hora_extra(
        self,
        funcionario_id: Any,
        mes: str,
        ano: str,
        qtd: float,
        valor_hora: float,
        outros: float,
    ) -> None:
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT
                    id,
                    salario,
                    vale_refeicao
                FROM folha_funcionarios
                WHERE funcionario_id = ?
                  AND mes = ?
                  AND ano = ?
            """, (funcionario_id, mes, ano))
            folha = cursor.fetchone()
            if not folha:
                return

            folha_id, salario, vale = folha
            total_hora_extra = qtd * valor_hora
            total = float(salario or 0) + float(vale or 0) + total_hora_extra + outros

            cursor.execute("""
                UPDATE folha_funcionarios
                SET qtd_horas_extra = ?,
                    valor_hora_extra = ?,
                    hora_extra = ?,
                    outros = ?,
                    total = ?
                WHERE id = ?
            """, (
                qtd,
                valor_hora,
                total_hora_extra,
                outros,
                total,
                folha_id,
            ))
            registrar_sync(cursor, "folha_funcionarios", folha_id)
            conn.commit()
        finally:
            conn.close()


    def salvar_folha(
        self,
        funcionario_id: Any,
        mes: str,
        ano: str,
        salario: float,
        vale_refeicao: float,
        qtd_horas_extra: float,
        valor_hora_extra: float,
        outros: float,
    ) -> Any:
        """Cria ou atualiza a folha mensal de um funcionário."""
        conn = conectar()
        cursor = conn.cursor()
        try:
            salario = float(salario or 0)
            vale_refeicao = float(vale_refeicao or 0)
            qtd_horas_extra = float(qtd_horas_extra or 0)
            valor_hora_extra = float(valor_hora_extra or 0)
            outros = float(outros or 0)
            hora_extra = qtd_horas_extra * valor_hora_extra
            total = salario + vale_refeicao + hora_extra + outros

            cursor.execute("""
                SELECT id FROM folha_funcionarios
                WHERE funcionario_id = ? AND mes = ? AND ano = ?
            """, (funcionario_id, mes, ano))
            existente = cursor.fetchone()
            if existente:
                folha_id = existente[0]
                cursor.execute("""
                    UPDATE folha_funcionarios
                    SET salario = ?, vale_refeicao = ?, qtd_horas_extra = ?,
                        valor_hora_extra = ?, hora_extra = ?, outros = ?, total = ?
                    WHERE id = ?
                """, (salario, vale_refeicao, qtd_horas_extra, valor_hora_extra,
                      hora_extra, outros, total, folha_id))
            else:
                cursor.execute("""
                    INSERT INTO folha_funcionarios
                    (id, funcionario_id, mes, ano, salario, vale_refeicao,
                     qtd_horas_extra, valor_hora_extra, hora_extra, outros, total)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (novo_id_global(), funcionario_id, mes, ano, salario, vale_refeicao,
                      qtd_horas_extra, valor_hora_extra, hora_extra, outros, total))
                folha_id = cursor.lastrowid
            registrar_sync(cursor, "folha_funcionarios", folha_id)
            conn.commit()
            return folha_id
        finally:
            conn.close()

    def remover_da_folha(self, funcionario_id: Any, mes: str, ano: str) -> None:
        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id
                FROM folha_funcionarios
                WHERE funcionario_id = ?
                  AND mes = ?
                  AND ano = ?
            """, (funcionario_id, mes, ano))
            folha = cursor.fetchone()
            if folha:
                registrar_sync(cursor, "folha_funcionarios", folha[0], "DELETE")
            cursor.execute("""
                DELETE FROM folha_funcionarios
                WHERE funcionario_id = ?
                  AND mes = ?
                  AND ano = ?
            """, (funcionario_id, mes, ano))
            conn.commit()
        finally:
            conn.close()


funcionarios_service = FuncionariosService()
