"""
Serviço de Publicação de Versões no GitHub - CW Transportadora

Gerencia o processo completo de publicação de atualizações no GitHub como CDN.
Fluxo Admin: automatiza o envio de novas versões para o repositório.

Features:
- Criação de releases no GitHub
- Upload de instaladores
- Atualização automática do release.json
- Autenticação via Personal Access Token
- Suporte a repositórios privados
- Cálculo automático de SHA-256
- Validação de integridade
- Histórico de publicações
- Suporte a múltiplos canais (stable, beta, dev)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

import requests

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class GitHubChannel(Enum):
    """Canais de atualização no GitHub."""
    STABLE = "stable"
    BETA = "beta"
    DEV = "dev"


class ReleaseStatus(Enum):
    """Status de uma publicação."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class GitHubReleaseInfo:
    """Informações de uma versão publicada no GitHub."""
    version: str
    channel: str
    release_date: str
    installer_filename: str
    installer_size: int
    sha256: str
    release_notes: str
    published_by: str
    github_tag: str
    github_release_url: str
    github_download_url: str
    status: str
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GitHubReleaseInfo":
        return cls(**data)


class GitHubReleaseService:
    """Serviço para gerenciar publicações de versões no GitHub."""
    
    # API base URL
    GITHUB_API_BASE = "https://api.github.com"
    
    def __init__(self):
        self.repo_owner = settings.github_repo_owner
        self.repo_name = settings.github_repo_name
        self.token = settings.github_token
        self.use_cdn = settings.github_use_cdn
        self.release_branch = settings.github_release_branch
        
        # Validar configuração
        if not self.repo_owner or not self.repo_name:
            logger.warning("Configuração do GitHub incompleta. Configure github_repo_owner e github_repo_name.")
        
        if not self.token:
            logger.warning("Token do GitHub não configurado. Configure github_token para repositórios privados.")
    
    def _get_headers(self) -> Dict[str, str]:
        """Retorna headers para requisições à API do GitHub."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers
    
    def _get_api_url(self, endpoint: str) -> str:
        """Constrói URL completa para endpoint da API."""
        return f"{self.GITHUB_API_BASE}/repos/{self.repo_owner}/{self.repo_name}/{endpoint}"
    
    def _calculate_sha256(self, file_path: Path) -> str:
        """Calcula o hash SHA-256 de um arquivo."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    def _get_file_size_mb(self, file_path: Path) -> float:
        """Retorna o tamanho do arquivo em MB."""
        return file_path.stat().st_size / (1024 * 1024)
    
    def _extract_version_from_filename(self, filename: str) -> Optional[str]:
        """Extrai a versão do nome do arquivo do instalador."""
        try:
            if "v" in filename:
                version_part = filename.split("v")[1].split("_")[0]
                return version_part
        except Exception:
            pass
        return None
    
    def _validate_installer(self, installer_path: Path) -> Tuple[bool, str]:
        """Valida se o arquivo é um instalador válido."""
        if not installer_path.exists():
            return False, "Arquivo não encontrado"
        
        if installer_path.stat().st_size == 0:
            return False, "Arquivo vazio"
        
        if not installer_path.suffix.lower() == ".exe":
            return False, "Arquivo não é um executável .exe"
        
        return True, "Arquivo válido"
    
    def _create_github_release(
        self,
        tag: str,
        title: str,
        notes: str,
        prerelease: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Cria um release no GitHub."""
        try:
            url = self._get_api_url("releases")
            
            data = {
                "tag_name": tag,
                "target_commitish": self.release_branch,
                "name": title,
                "body": notes,
                "draft": False,
                "prerelease": prerelease,
            }
            
            response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
            response.raise_for_status()
            
            release_data = response.json()
            logger.info(f"Release criado no GitHub: {tag}")
            return True, "Release criado com sucesso", release_data
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Erro ao criar release no GitHub: {e}"
            logger.error(error_msg)
            return False, error_msg, {}
        except Exception as e:
            error_msg = f"Erro inesperado ao criar release: {e}"
            logger.error(error_msg)
            return False, error_msg, {}
    
    def _upload_asset_to_github(
        self,
        upload_url: str,
        file_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, str]:
        """Faz upload de um asset para o release no GitHub."""
        try:
            logger.info(f"Iniciando upload do asset: {file_path.name}")
            
            # A URL de upload precisa ter parâmetros limpos
            upload_url = upload_url.split("{")[0]
            
            file_size = file_path.stat().st_size
            
            with open(file_path, "rb") as f:
                headers = self._get_headers()
                headers["Content-Type"] = "application/octet-stream"
                
                response = requests.post(
                    upload_url,
                    headers=headers,
                    data=f,
                    timeout=300  # 5 minutos para upload
                )
                response.raise_for_status()
            
            logger.info(f"Upload concluído: {file_path.name}")
            return True, "Upload concluído com sucesso"
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Erro ao fazer upload: {e}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Erro inesperado no upload: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def _update_release_json(self, release_info: GitHubReleaseInfo) -> None:
        """Atualiza o arquivo release.json no repositório."""
        try:
            # Gerar conteúdo do release.json
            release_json = {
                "versao": release_info.version,
                "nome": "CW Transportadora",
                "data": release_info.release_date,
                "canal": release_info.channel,
                "installer_filename": release_info.installer_filename,
                "installer_size": release_info.installer_size,
                "sha256": release_info.sha256,
                "release_notes": release_info.release_notes,
                "published_by": release_info.published_by,
                "github_tag": release_info.github_tag,
                "github_release_url": release_info.github_release_url,
                "github_download_url": release_info.github_download_url,
                "published_at": release_info.created_at,
            }
            
            # Salvar localmente
            release_json_path = settings.project_dir / "release.json"
            with open(release_json_path, "w", encoding="utf-8") as f:
                json.dump(release_json, f, ensure_ascii=False, indent=4)
            
            logger.info(f"release.json atualizado localmente: {release_json_path}")
            
            # Commit e push do release.json (se configurado)
            self._commit_and_push_release_json(release_json_path)
            
        except Exception as e:
            logger.error(f"Erro ao atualizar release.json: {e}")
    
    def _commit_and_push_release_json(self, file_path: Path) -> None:
        """Faz commit e push do release.json para o repositório."""
        try:
            # Verificar se estamos em um repositório git
            git_dir = settings.project_dir / ".git"
            if not git_dir.exists():
                logger.warning("Não está em um repositório git. Pulando commit/push do release.json.")
                return
            
            # Adicionar arquivo
            subprocess.run(
                ["git", "add", str(file_path)],
                cwd=settings.project_dir,
                check=True,
                capture_output=True
            )
            
            # Commit
            commit_msg = f"Update release.json to version {file_path.parent.name}"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=settings.project_dir,
                check=True,
                capture_output=True
            )
            
            # Push
            subprocess.run(
                ["git", "push"],
                cwd=settings.project_dir,
                check=True,
                capture_output=True
            )
            
            logger.info("release.json commitado e enviado para o repositório")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Erro no git commit/push: {e}")
        except Exception as e:
            logger.error(f"Erro ao fazer commit/push: {e}")
    
    def _save_to_history(self, release_info: GitHubReleaseInfo) -> None:
        """Salva a informação da publicação no histórico local."""
        try:
            history_dir = settings.dados_dir / "github_releases_history"
            history_dir.mkdir(parents=True, exist_ok=True)
            
            history_file = history_dir / f"release_{release_info.version}_{release_info.channel}.json"
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(release_info.to_dict(), f, ensure_ascii=False, indent=4)
            
            logger.info(f"Publicação salva no histórico: {history_file}")
        except Exception as e:
            logger.error(f"Erro ao salvar no histórico: {e}")
    
    def publish_release(
        self,
        installer_path: Path,
        version: Optional[str] = None,
        release_notes: str = "",
        channel: GitHubChannel = GitHubChannel.STABLE,
        published_by: str = "Sistema",
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> Tuple[bool, GitHubReleaseInfo, str]:
        """
        Publica uma nova versão no GitHub.
        
        Args:
            installer_path: Caminho do instalador .exe
            version: Versão (opcional, será extraída do nome do arquivo se não informada)
            release_notes: Notas da versão
            channel: Canal de publicação (stable, beta, dev)
            published_by: Usuário responsável pela publicação
            progress_callback: Callback(status_message, progress, total)
        
        Returns:
            Tuple (success, release_info, error_message)
        """
        release_info = None
        error_msg = ""
        
        try:
            # 1. Validar configuração
            if not self.repo_owner or not self.repo_name:
                return False, None, "Configuração do GitHub incompleta. Configure github_repo_owner e github_repo_name."
            
            if progress_callback:
                progress_callback("Validando configuração...", 0, 100)
            
            # 2. Validar instalador
            if progress_callback:
                progress_callback("Validando instalador...", 5, 100)
            
            valid, validation_msg = self._validate_installer(installer_path)
            if not valid:
                return False, None, validation_msg
            
            # 3. Extrair versão se não informada
            if not version:
                version = self._extract_version_from_filename(installer_path.name)
                if not version:
                    return False, None, "Não foi possível extrair a versão do nome do arquivo. Informe manualmente."
            
            # 4. Calcular SHA-256
            if progress_callback:
                progress_callback("Calculando hash SHA-256...", 10, 100)
            
            sha256 = self._calculate_sha256(installer_path)
            size = installer_path.stat().st_size
            size_mb = self._get_file_size_mb(installer_path)
            
            # 5. Determinar tag e pré-release
            if progress_callback:
                progress_callback("Preparando release...", 15, 100)
            
            tag = f"v{version}"
            prerelease = channel != GitHubChannel.STABLE
            
            title = f"CW Transportadora v{version}"
            if channel == GitHubChannel.BETA:
                title += " (Beta)"
            elif channel == GitHubChannel.DEV:
                title += " (Dev)"
            
            # 6. Criar release no GitHub
            if progress_callback:
                progress_callback("Criando release no GitHub...", 20, 100)
            
            success, msg, release_data = self._create_github_release(tag, title, release_notes, prerelease)
            if not success:
                return False, None, f"Erro ao criar release: {msg}"
            
            upload_url = release_data.get("upload_url", "")
            release_url = release_data.get("html_url", "")
            
            # 7. Upload do instalador
            if progress_callback:
                progress_callback("Fazendo upload do instalador...", 30, 100)
            
            success, msg = self._upload_asset_to_github(upload_url, installer_path, progress_callback)
            if not success:
                return False, None, f"Erro no upload: {msg}"
            
            if progress_callback:
                progress_callback("Upload concluído!", 80, 100)
            
            # 8. Construir URL de download
            download_url = f"https://github.com/{self.repo_owner}/{self.repo_name}/releases/download/{tag}/{installer_path.name}"
            
            # 9. Criar ReleaseInfo
            if progress_callback:
                progress_callback("Gerando metadados...", 85, 100)
            
            release_info = GitHubReleaseInfo(
                version=version,
                channel=channel.value,
                release_date=datetime.now().strftime("%d/%m/%Y"),
                installer_filename=installer_path.name,
                installer_size=size,
                sha256=sha256,
                release_notes=release_notes,
                published_by=published_by,
                github_tag=tag,
                github_release_url=release_url,
                github_download_url=download_url,
                status=ReleaseStatus.SUCCESS.value,
                created_at=datetime.now().isoformat()
            )
            
            # 10. Atualizar release.json
            if progress_callback:
                progress_callback("Atualizando release.json...", 90, 100)
            
            self._update_release_json(release_info)
            
            # 11. Salvar no histórico
            if progress_callback:
                progress_callback("Salvando no histórico...", 95, 100)
            
            self._save_to_history(release_info)
            
            # 12. Finalizar
            if progress_callback:
                progress_callback("Publicação concluída com sucesso!", 100, 100)
            
            logger.info(f"Versão {version} publicada com sucesso no GitHub (canal {channel.value})")
            return True, release_info, ""
            
        except Exception as e:
            error_msg = f"Erro durante publicação: {e}"
            logger.error(error_msg)
            
            # Salvar como falha se houver release_info parcial
            if release_info:
                release_info.status = ReleaseStatus.FAILED.value
                self._save_to_history(release_info)
            
            return False, release_info, error_msg
    
    def get_latest_release_info(self, channel: GitHubChannel = GitHubChannel.STABLE) -> Optional[Dict[str, Any]]:
        """
        Retorna informações da versão mais recente de um canal.
        Busca via API do GitHub.
        """
        try:
            # Para stable, usa o endpoint latest
            if channel == GitHubChannel.STABLE:
                url = self._get_api_url("releases/latest")
            else:
                # Para beta/dev, lista releases e filtra
                url = self._get_api_url("releases")
            
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            
            if response.status_code == 404:
                logger.info(f"Nenhum release encontrado no canal {channel.value}")
                return None
            
            response.raise_for_status()
            
            if channel == GitHubChannel.STABLE:
                release_data = response.json()
            else:
                releases = response.json()
                if not releases:
                    return None
                
                # Filtrar por canal
                if channel == GitHubChannel.BETA:
                    release_data = next((r for r in releases if r.get("prerelease")), releases[0])
                else:  # DEV
                    release_data = releases[0]
            
            # Extrair informações relevantes
            version = release_data.get("tag_name", "").lstrip("v")
            assets = release_data.get("assets", [])
            
            download_url = None
            installer_size = 0
            sha256 = ""
            
            if assets:
                asset = assets[0]
                download_url = asset.get("browser_download_url")
                installer_size = asset.get("size", 0)
            
            return {
                "versao": version,
                "data": release_data.get("published_at", "")[:10],
                "notas": release_data.get("body", ""),
                "download_url": download_url,
                "installer_size": installer_size,
                "sha256": sha256,
                "github_tag": release_data.get("tag_name"),
                "github_release_url": release_data.get("html_url"),
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao buscar release no GitHub: {e}")
            return None
        except Exception as e:
            logger.error(f"Erro ao ler release: {e}")
            return None
    
    def get_history(self, limit: int = 50) -> List[GitHubReleaseInfo]:
        """Retorna o histórico de publicações local."""
        try:
            history_dir = settings.dados_dir / "github_releases_history"
            if not history_dir.exists():
                return []
            
            history = []
            for file_path in history_dir.glob("release_*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        history.append(GitHubReleaseInfo.from_dict(data))
                except Exception as e:
                    logger.error(f"Erro ao ler arquivo de histórico {file_path}: {e}")
            
            # Ordenar por data de criação (mais recente primeiro)
            history.sort(key=lambda x: x.created_at, reverse=True)
            return history[:limit]
            
        except Exception as e:
            logger.error(f"Erro ao ler histórico: {e}")
            return []


# Instância singleton do serviço
github_release_service = GitHubReleaseService()
