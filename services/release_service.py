"""
Serviço de Publicação de Versões - CW Transportadora

Gerencia o processo completo de publicação de atualizações no servidor próprio.
Seguindo princípios SOLID para baixo acoplamento e alta coesão.

Features:
- Publicação de versões em servidor próprio (HTTP/HTTPS, local, SMB, FTP)
- Upload via HTTP/HTTPS com autenticação
- Cálculo automático de SHA-256
- Validação de integridade
- Histórico de publicações
- Suporte a múltiplos canais (stable, beta, dev)
- Auditoria completa
- Barra de progresso com callbacks
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import requests

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class ServerType(Enum):
    """Tipos de servidor de atualizações suportados."""
    LOCAL = "local"
    SMB = "smb"
    HTTP = "http"
    FTP = "ftp"


class Channel(Enum):
    """Canais de atualização."""
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
class ReleaseInfo:
    """Informações de uma versão publicada."""
    version: str
    channel: str
    release_date: str
    installer_filename: str
    installer_size: int
    sha256: str
    release_notes: str
    published_by: str
    server_type: str
    server_path: str
    status: str
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReleaseInfo":
        return cls(**data)


class ReleaseService:
    """Serviço para gerenciar publicações de versões."""
    
    def __init__(self):
        self.updates_dir = settings.updates_dir
        self.server_type = ServerType(settings.update_server_type)
        self.server_path = settings.update_server_path
        self.username = settings.update_server_username
        self.password = settings.update_server_password
        self.channel = settings.update_channel
        
        # Criar diretórios necessários
        self._setup_directories()
    
    def _setup_directories(self) -> None:
        """Cria a estrutura de diretórios para o servidor de atualizações."""
        try:
            # Diretório raiz de atualizações
            self.updates_dir.mkdir(parents=True, exist_ok=True)
            
            # Diretórios por canal
            for channel in Channel:
                channel_dir = self.updates_dir / channel.value
                channel_dir.mkdir(parents=True, exist_ok=True)
            
            # Diretório de histórico
            history_dir = self.updates_dir / "history"
            history_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info("Diretórios de atualizações configurados com sucesso")
        except Exception as e:
            logger.error(f"Erro ao configurar diretórios: {e}")
            raise
    
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
        # Padrão esperado: CW_Transportadora_vX.X.X_Setup.exe
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
    
    def _copy_to_server(
        self,
        source: Path,
        destination: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, str]:
        """Copia o arquivo para o servidor de atualizações (local ou HTTP)."""
        if self.server_type == ServerType.HTTP:
            return self._upload_to_http(source, destination, progress_callback)
        return self._copy_to_local(source, destination, progress_callback)
    
    def _copy_to_local(
        self,
        source: Path,
        destination: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, str]:
        """Copia o arquivo para o servidor local."""
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            
            total_size = source.stat().st_size
            copied = 0
            
            with open(source, "rb") as src, open(destination, "wb") as dst:
                while chunk := src.read(8192):
                    dst.write(chunk)
                    copied += len(chunk)
                    if progress_callback:
                        progress_callback(copied, total_size)
            
            return True, str(destination)
        except Exception as e:
            logger.error(f"Erro ao copiar arquivo local: {e}")
            return False, str(e)
    
    def _upload_to_http(
        self,
        source: Path,
        destination: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, str]:
        """Faz upload do arquivo para servidor HTTP/HTTPS."""
        try:
            # Construir URL de upload
            # destination é relativo ao canal, ex: stable/CW_Transportadora_v1.0.0_Setup.exe
            url = f"{self.server_path.rstrip('/')}/{destination.parent.name}/{destination.name}"
            
            logger.info(f"Iniciando upload para: {url}")
            
            # Preparar autenticação se configurada
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            
            # Ler arquivo
            with open(source, "rb") as f:
                files = {"file": (destination.name, f, "application/octet-stream")}
                
                # Fazer upload com progresso
                total_size = source.stat().st_size
                uploaded = 0
                
                def upload_progress(chunk):
                    nonlocal uploaded
                    uploaded += len(chunk)
                    if progress_callback:
                        progress_callback(uploaded, total_size)
                
                response = requests.post(
                    url,
                    files=files,
                    auth=auth,
                    timeout=300,  # 5 minutos timeout para upload
                    verify=True  # Validar certificado HTTPS
                )
                
                response.raise_for_status()
            
            logger.info(f"Upload concluído com sucesso: {url}")
            return True, url
            
        except requests.exceptions.SSLError as e:
            logger.error(f"Erro de SSL no upload: {e}")
            return False, f"Erro de SSL: {e}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de conexão no upload: {e}")
            return False, f"Erro de conexão: {e}"
        except Exception as e:
            logger.error(f"Erro no upload: {e}")
            return False, str(e)
    
    def _validate_copy_integrity(self, source: Path, destination: Path) -> bool:
        """Valida se a cópia foi realizada com sucesso comparando SHA-256."""
        try:
            source_sha = self._calculate_sha256(source)
            dest_sha = self._calculate_sha256(destination)
            return source_sha == dest_sha
        except Exception as e:
            logger.error(f"Erro ao validar integridade: {e}")
            return False
    
    def _generate_version_json(self, release_info: ReleaseInfo) -> Dict[str, Any]:
        """Gera o conteúdo do arquivo version.json."""
        return {
            "versao": release_info.version,
            "nome": "CW Transportadora",
            "data": release_info.release_date,
            "canal": release_info.channel,
            "installer_filename": release_info.installer_filename,
            "installer_size": release_info.installer_size,
            "sha256": release_info.sha256,
            "release_notes": release_info.release_notes,
            "published_by": release_info.published_by,
            "published_at": release_info.created_at,
        }
    
    def _save_version_json(self, channel_dir: Path, version_data: Dict[str, Any]) -> None:
        """Salva o arquivo version.json no diretório do canal ou via HTTP."""
        if self.server_type == ServerType.HTTP:
            self._upload_version_json_http(channel_dir, version_data)
        else:
            self._save_version_json_local(channel_dir, version_data)
    
    def _save_version_json_local(self, channel_dir: Path, version_data: Dict[str, Any]) -> None:
        """Salva o arquivo version.json localmente."""
        version_file = channel_dir / "version.json"
        with open(version_file, "w", encoding="utf-8") as f:
            json.dump(version_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Arquivo version.json salvo localmente: {version_file}")
    
    def _upload_version_json_http(self, channel_dir: Path, version_data: Dict[str, Any]) -> None:
        """Faz upload do version.json para servidor HTTP."""
        try:
            # Construir URL para upload do version.json
            url = f"{self.server_path.rstrip('/')}/{channel_dir.name}/version.json"
            
            logger.info(f"Fazendo upload de version.json para: {url}")
            
            # Preparar autenticação se configurada
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            
            # Fazer upload
            response = requests.post(
                url,
                json=version_data,
                auth=auth,
                timeout=30,
                verify=True
            )
            
            response.raise_for_status()
            logger.info(f"version.json enviado com sucesso para: {url}")
            
        except Exception as e:
            logger.error(f"Erro ao fazer upload de version.json: {e}")
            # Salvar localmente como fallback
            self._save_version_json_local(channel_dir, version_data)
    
    def _save_to_history(self, release_info: ReleaseInfo) -> None:
        """Salva a informação da publicação no histórico."""
        history_file = self.updates_dir / "history" / f"release_{release_info.version}_{release_info.channel}.json"
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(release_info.to_dict(), f, ensure_ascii=False, indent=4)
        logger.info(f"Publicação salva no histórico: {history_file}")
    
    def _get_history(self) -> List[ReleaseInfo]:
        """Retorna o histórico completo de publicações."""
        history_dir = self.updates_dir / "history"
        history = []
        
        if not history_dir.exists():
            return history
        
        for file_path in history_dir.glob("release_*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    history.append(ReleaseInfo.from_dict(data))
            except Exception as e:
                logger.error(f"Erro ao ler arquivo de histórico {file_path}: {e}")
        
        # Ordenar por data de criação (mais recente primeiro)
        history.sort(key=lambda x: x.created_at, reverse=True)
        return history
    
    def _get_latest_release(self, channel: Channel) -> Optional[ReleaseInfo]:
        """Retorna a versão mais recente de um canal."""
        history = self._get_history()
        channel_releases = [r for r in history if r.channel == channel.value and r.status == ReleaseStatus.SUCCESS.value]
        
        if channel_releases:
            return channel_releases[0]
        return None
    
    def publish_release(
        self,
        installer_path: Path,
        version: Optional[str] = None,
        release_notes: str = "",
        channel: Channel = Channel.STABLE,
        published_by: str = "Sistema",
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> Tuple[bool, ReleaseInfo, str]:
        """
        Publica uma nova versão no servidor de atualizações.
        
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
            # 1. Validar instalador
            if progress_callback:
                progress_callback("Validando instalador...", 0, 100)
            
            valid, validation_msg = self._validate_installer(installer_path)
            if not valid:
                return False, None, validation_msg
            
            # 2. Extrair versão se não informada
            if not version:
                version = self._extract_version_from_filename(installer_path.name)
                if not version:
                    return False, None, "Não foi possível extrair a versão do nome do arquivo. Informe manualmente."
            
            # 3. Calcular SHA-256
            if progress_callback:
                progress_callback("Calculando hash SHA-256...", 10, 100)
            
            sha256 = self._calculate_sha256(installer_path)
            size = installer_path.stat().st_size
            size_mb = self._get_file_size_mb(installer_path)
            
            # 4. Determinar diretório de destino
            if progress_callback:
                progress_callback("Preparando diretório de destino...", 20, 100)
            
            channel_dir = self.updates_dir / channel.value
            channel_dir.mkdir(parents=True, exist_ok=True)
            
            destination = channel_dir / installer_path.name
            
            # 5. Copiar arquivo para o servidor
            if progress_callback:
                progress_callback("Copiando arquivo para o servidor...", 30, 100)
            
            def copy_progress(copied: int, total: int) -> None:
                if progress_callback:
                    progress_percent = 30 + int((copied / total) * 40)
                    progress_callback(f"Copiando arquivo... ({copied / (1024*1024):.1f} MB / {total / (1024*1024):.1f} MB)", progress_percent, 100)
            
            success, result = self._copy_to_server(installer_path, destination, copy_progress)
            if not success:
                return False, None, f"Erro ao copiar arquivo: {result}"
            
            # 6. Validar integridade da cópia (apenas para local)
            if self.server_type != ServerType.HTTP:
                if progress_callback:
                    progress_callback("Validando integridade da cópia...", 70, 100)
                
                if not self._validate_copy_integrity(installer_path, destination):
                    destination.unlink()  # Remover arquivo corrompido
                    return False, None, "Falha na validação de integridade após cópia"
            else:
                if progress_callback:
                    progress_callback("Upload concluído com sucesso!", 70, 100)
            
            # 7. Criar ReleaseInfo
            if progress_callback:
                progress_callback("Gerando metadados...", 80, 100)
            
            release_info = ReleaseInfo(
                version=version,
                channel=channel.value,
                release_date=datetime.now().strftime("%d/%m/%Y"),
                installer_filename=installer_path.name,
                installer_size=size,
                sha256=sha256,
                release_notes=release_notes,
                published_by=published_by,
                server_type=self.server_type.value,
                server_path=self.server_path if self.server_type == ServerType.HTTP else str(self.updates_dir),
                status=ReleaseStatus.SUCCESS.value,
                created_at=datetime.now().isoformat()
            )
            
            # 8. Gerar e salvar version.json
            if progress_callback:
                progress_callback("Atualizando version.json...", 90, 100)
            
            version_data = self._generate_version_json(release_info)
            self._save_version_json(channel_dir, version_data)
            
            # 9. Salvar no histórico
            if progress_callback:
                progress_callback("Salvando no histórico...", 95, 100)
            
            self._save_to_history(release_info)
            
            # 10. Finalizar
            if progress_callback:
                progress_callback("Publicação concluída com sucesso!", 100, 100)
            
            logger.info(f"Versão {version} publicada com sucesso no canal {channel.value}")
            return True, release_info, ""
            
        except Exception as e:
            error_msg = f"Erro durante publicação: {e}"
            logger.error(error_msg)
            
            # Salvar como falha se houver release_info parcial
            if release_info:
                release_info.status = ReleaseStatus.FAILED.value
                self._save_to_history(release_info)
            
            return False, release_info, error_msg
    
    def get_latest_version_info(self, channel: Channel = Channel.STABLE) -> Optional[Dict[str, Any]]:
        """
        Retorna informações da versão mais recente de um canal.
        Usado pelo update_service para verificar atualizações.
        Busca via HTTP se configurado, local caso contrário.
        """
        if self.server_type == ServerType.HTTP:
            return self._get_latest_version_info_http(channel)
        return self._get_latest_version_info_local(channel)
    
    def _get_latest_version_info_local(self, channel: Channel = Channel.STABLE) -> Optional[Dict[str, Any]]:
        """Retorna informações da versão mais recente do servidor local."""
        try:
            channel_dir = self.updates_dir / channel.value
            version_file = channel_dir / "version.json"
            
            if not version_file.exists():
                return None
            
            with open(version_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao ler version.json local: {e}")
            return None
    
    def _get_latest_version_info_http(self, channel: Channel = Channel.STABLE) -> Optional[Dict[str, Any]]:
        """Retorna informações da versão mais recente via HTTP."""
        try:
            # Verificar se o server_path está configurado
            if not self.server_path or not self.server_path.strip():
                logger.warning("Server path não configurado para HTTP, usando fallback local")
                return self._get_latest_version_info_local(channel)
            
            url = f"{self.server_path.rstrip('/')}/{channel.value}/version.json"
            
            # Verificar se a URL tem um esquema válido (http:// ou https://)
            if not url.startswith(("http://", "https://")):
                logger.warning(f"URL inválida (sem esquema): {url}, usando fallback local")
                return self._get_latest_version_info_local(channel)
            
            logger.info(f"Buscando version.json via HTTP: {url}")
            
            # Preparar autenticação se configurada
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            
            response = requests.get(
                url,
                auth=auth,
                timeout=30,
                verify=True
            )
            
            if response.status_code == 404:
                logger.info(f"version.json não encontrado: {url}")
                return None
            
            response.raise_for_status()
            
            version_info = response.json()
            logger.info(f"version.json obtido com sucesso: {version_info.get('versao', 'unknown')}")
            
            return version_info
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao buscar version.json via HTTP: {e}")
            # Fallback para local
            return self._get_latest_version_info_local(channel)
        except Exception as e:
            logger.error(f"Erro ao ler version.json: {e}")
            return None
    
    def get_installer_path(self, channel: Channel = Channel.STABLE) -> Optional[str]:
        """
        Retorna o caminho ou URL do instalador mais recente de um canal.
        Retorna URL HTTP se configurado, caminho local caso contrário.
        """
        version_info = self.get_latest_version_info(channel)
        if not version_info:
            return None
        
        installer_filename = version_info.get("installer_filename")
        if not installer_filename:
            return None
        
        if self.server_type == ServerType.HTTP:
            # Retornar URL HTTP
            return f"{self.server_path.rstrip('/')}/{channel.value}/{installer_filename}"
        else:
            # Retornar caminho local
            channel_dir = self.updates_dir / channel.value
            installer_path = channel_dir / installer_filename
            
            if installer_path.exists():
                return str(installer_path)
            
            return None
    
    def get_history(self, limit: int = 50) -> List[ReleaseInfo]:
        """Retorna o histórico de publicações."""
        history = self._get_history()
        return history[:limit]
    
    def get_admin_panel_data(self) -> Dict[str, Any]:
        """
        Retorna dados para o painel de administração de atualizações.
        """
        history = self._get_history()
        
        # Versão atual instalada
        current_version = "0.0.0"
        version_file = settings.project_dir / "versao.json"
        if version_file.exists():
            try:
                with open(version_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    current_version = data.get("versao", "0.0.0")
            except Exception:
                pass
        
        # Última versão publicada por canal
        latest_by_channel = {}
        for channel in Channel:
            latest = self._get_latest_release(channel)
            latest_by_channel[channel.value] = latest
        
        return {
            "current_version": current_version,
            "latest_by_channel": latest_by_channel,
            "history": history,
            "server_type": self.server_type.value,
            "server_path": str(self.updates_dir),
            "total_releases": len(history),
            "successful_releases": len([r for r in history if r.status == ReleaseStatus.SUCCESS.value]),
            "failed_releases": len([r for r in history if r.status == ReleaseStatus.FAILED.value]),
        }


# Instância singleton do serviço
release_service = ReleaseService()
