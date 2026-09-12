"""Auditoria persistente e centralizada das acoes administrativas do CW."""
from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from utils.database import conectar

ACAO_LOGIN = "LOGIN"
ACAO_LOGOUT = "LOGOUT"
ACAO_LOGIN_FALHOU = "LOGIN_FALHOU"
ACAO_PERMISSAO_ALTERADA = "PERMISSAO_ALTERADA"
ACAO_USUARIO_CRIADO = "USUARIO_CRIADO"
ACAO_USUARIO_ATUALIZADO = "USUARIO_ATUALIZADO"
ACAO_USUARIO_EXCLUIDO = "USUARIO_EXCLUIDO"
ACAO_USUARIO_ATIVADO = "USUARIO_ATIVADO"
ACAO_USUARIO_DESATIVADO = "USUARIO_DESATIVADO"
ACAO_SYNC = "SYNC"
ACAO_BACKUP = "BACKUP"
ACAO_UPDATE = "UPDATE"
ACAO_CONFIG_ALTERADA = "CONFIG_ALTERADA"
ACAO_RESET = "RESET"
ACAO_RESTAURACAO = "RESTAURACAO_BACKUP"
ACAO_ACESSO_NEGADO = "ACESSO_NEGADO"
ACAO_SYNC_INICIADA = "SYNC_INICIADA"
ACAO_SYNC_CONCLUIDA = "SYNC_CONCLUIDA"
ACAO_SYNC_CONFLITO = "SYNC_CONFLITO"
ACAO_SYNC_ERRO = "SYNC_ERRO"


class AuditoriaService:
    """Registra auditoria no SQLite e mantém cache de compatibilidade."""

    def __init__(self):
        self._registros: list[dict[str, Any]] = []
        self._hostname = socket.gethostname()

    def registrar(self, acao: str, modulo: str, usuario: Optional[str] = None, **kwargs):
        user = usuario or "Sistema"
        usuario_id = kwargs.pop("usuario_id", None)
        usuario_nome = kwargs.pop("usuario_nome", None) or user
        registro_afetado = kwargs.pop("registro_afetado", None)
        detalhes = kwargs
        agora = datetime.now().isoformat(timespec="seconds")
        try:
            conn = conectar()
            try:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO auditoria
                    (usuario_id, usuario_nome, acao, modulo, registro_afetado, detalhes, criado_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (usuario_id, usuario_nome, acao, modulo,
                     None if registro_afetado is None else str(registro_afetado),
                     json.dumps({**detalhes, "computador": self._hostname}, ensure_ascii=False, default=str),
                     agora),
                )
                conn.commit()
                registro_id = cur.lastrowid
            finally:
                conn.close()
        except Exception:
            # Auditoria nunca deve derrubar uma operacao de negocio por falha de log.
            registro_id = len(self._registros) + 1

        registro = {
            "id": registro_id, "acao": acao, "modulo": modulo, "usuario": user,
            "data_hora": agora, "detalhes": detalhes, "computador": self._hostname
        }
        self._registros.append(registro)
        return registro

    def registrar_acao(self, acao, descricao, usuario_id=None):
        user = "Sistema"
        try:
            from services.auth_service import auth_service
            if auth_service.usuario_atual:
                user = auth_service.usuario_atual.get("usuario") or user
                usuario_id = usuario_id or auth_service.usuario_atual.get("id")
        except Exception:
            pass
        return self.registrar(acao, "Geral", usuario=user, usuario_id=usuario_id, descricao=descricao)

    def listar(self, filtros=None, data_inicio=None, data_fim=None, pagina=1, por_pagina=50, acao=None, modulo=None):
        pagina = max(1, int(pagina or 1)); por_pagina = min(200, max(1, int(por_pagina or 50)))
        where, params = ["1=1"], []
        if acao:
            where.append("acao=?"); params.append(acao)
        if modulo:
            where.append("modulo=?"); params.append(modulo)
        if data_inicio:
            where.append("date(criado_em) >= date(?)"); params.append(str(data_inicio)[:10])
        if data_fim:
            where.append("date(criado_em) <= date(?)"); params.append(str(data_fim)[:10])
        if filtros:
            if filtros.get("usuario"):
                where.append("usuario_nome=?"); params.append(filtros["usuario"])
        conn = conectar()
        try:
            base = " FROM auditoria WHERE " + " AND ".join(where)
            total = int(conn.execute("SELECT COUNT(*)" + base, params).fetchone()[0])
            offset = (pagina - 1) * por_pagina
            rows = conn.execute(
                "SELECT id,usuario_id,usuario_nome,acao,modulo,registro_afetado,detalhes,criado_em"
                + base + " ORDER BY id DESC LIMIT ? OFFSET ?",
                (*params, por_pagina, offset),
            ).fetchall()
            registros = []
            for r in rows:
                try: detalhes = json.loads(r[6] or "{}")
                except Exception: detalhes = {"texto": r[6]}
                registros.append({
                    "id": r[0], "usuario_id": r[1], "usuario": r[2] or "Sistema",
                    "acao": r[3], "modulo": r[4] or "Geral", "registro_afetado": r[5],
                    "detalhes": detalhes, "data_hora": r[7],
                })
            return {"registros": registros, "total": total, "pagina": pagina,
                    "por_pagina": por_pagina, "total_paginas": (total + por_pagina - 1) // por_pagina}
        finally:
            conn.close()

    def listar_registros(self, filtros=None, pagina=1, por_pagina=50):
        return self.listar(filtros=filtros, pagina=pagina, por_pagina=por_pagina)

    def exportar_csv(self, caminho):
        import csv
        dados = self.listar(pagina=1, por_pagina=200).get("registros", [])
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["ID", "Data/Hora", "Usuário", "Ação", "Módulo", "Registro", "Detalhes"])
            for r in dados:
                w.writerow([r["id"], r["data_hora"], r["usuario"], r["acao"], r["modulo"], r.get("registro_afetado") or "", json.dumps(r.get("detalhes", {}), ensure_ascii=False)])
        return caminho

    def exportar_pdf(self, caminho):
        # PDF opcional; a tela pode usar CSV quando reportlab não estiver instalado.
        try:
            from reportlab.pdfgen import canvas
            dados = self.listar(pagina=1, por_pagina=200).get("registros", [])
            c = canvas.Canvas(str(caminho)); y = 800
            c.setFont("Helvetica", 9)
            for r in dados:
                texto = f'{r["data_hora"]} | {r["usuario"]} | {r["acao"]} | {r["modulo"]}'
                c.drawString(30, y, texto[:130]); y -= 14
                if y < 30: c.showPage(); c.setFont("Helvetica", 9); y = 800
            c.save(); return caminho
        except Exception:
            return False


auditoria_service = AuditoriaService()
