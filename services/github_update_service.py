"""Cliente GitHub de atualização; sem placeholders de versões antigas."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from config.settings import settings


class GitHubUpdateService:
    def _repo_base(self):
        return f"https://api.github.com/repos/{settings.github_repo_owner}/{settings.github_repo_name}"

    def _headers(self):
        h = {"Accept": "application/vnd.github+json", "User-Agent": "CW-Transportadora"}
        if settings.github_token:
            h["Authorization"] = f"Bearer {settings.github_token}"
        return h

    def _installed_version(self):
        path = Path(__file__).resolve().parents[1] / "versao.json"
        try:
            return str(json.loads(path.read_text(encoding="utf-8")).get("versao", "0.0.0"))
        except (OSError, ValueError, TypeError):
            return "0.0.0"

    @staticmethod
    def _version_tuple(value):
        try:
            return tuple(int(x) for x in str(value).strip().lstrip("vV").split(".")[:3])
        except (ValueError, TypeError):
            return (0, 0, 0)

    def check_for_updates(self):
        if not settings.github_repo_owner or not settings.github_repo_name:
            return {"has_update": False, "version": self._installed_version(), "download_url": None}
        try:
            req = Request(f"{self._repo_base()}/releases/latest", headers=self._headers())
            with urlopen(req, timeout=8) as response:
                release = json.loads(response.read().decode("utf-8"))
            remote = str(release.get("tag_name") or "").lstrip("vV")
            installed = self._installed_version()
            asset = next((a for a in release.get("assets", []) if str(a.get("name", "")).lower().endswith(".exe")), None)
            return {
                "has_update": bool(remote and self._version_tuple(remote) > self._version_tuple(installed)),
                "version": remote or installed,
                "download_url": asset.get("browser_download_url") if asset else None,
                "mensagem": str(release.get("name") or release.get("body") or "Nova versão disponível."),
            }
        except Exception:
            return {"has_update": False, "version": self._installed_version(), "download_url": None}

    def download_and_install(self, version, canal="estavel"):
        # O instalador continua sendo executado pelo fluxo administrativo.
        # Não simulamos sucesso quando não há implementação real.
        raise NotImplementedError("A instalação automática está desativada por segurança. Baixe e execute manualmente o instalador da nova versão.")


GitHubUpdateService = GitHubUpdateService
github_update_service = GitHubUpdateService()
