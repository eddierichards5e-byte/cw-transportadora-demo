"""Serviço único de atualização do CW Transportadora.

A V83 mantém este módulo como fachada de compatibilidade para código legado,
mas a fonte de atualização é o serviço GitHub oficial.
"""
from __future__ import annotations

import json
from pathlib import Path

CANAL_ESTAVEL = "estavel"
CANAL_BETA = "beta"
CANAL_DEV = "dev"


class UpdateService:
    def __init__(self):
        self.channel = CANAL_ESTAVEL

    def check_for_updates(self):
        from services.github_update_service import github_update_service
        return github_update_service.check_for_updates()

    def obter_versao_instalada(self):
        path = Path(__file__).resolve().parents[1] / "versao.json"
        versao = "0.0.0"
        data = ""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            versao = str(payload.get("versao", versao))
            data = str(payload.get("data", data))
        except (OSError, ValueError, TypeError):
            pass
        return {"versao": versao, "data": data, "nome": "CW Transportadora"}

    def obter_historico_versoes(self, limit=20):
        return [{"versao": self.obter_versao_instalada()["versao"], "data": self.obter_versao_instalada()["data"], "notas": "V83 — Fundação Limpa", "prerelease": False}]

    def download_and_install(self, version, canal=CANAL_ESTAVEL):
        from services.github_update_service import github_update_service
        return github_update_service.download_and_install(version, canal)


update_service = UpdateService()
