"""Configurações persistentes do CW Transportadora."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

try:
    import keyring
except Exception:  # pragma: no cover - ambiente sem backend de credenciais
    keyring = None

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent
_KEYRING_SERVICE = "CW Transportadora"
_KEYRING_TOKEN_USER = "supabase_sync_token"
_DEFAULT_SUPABASE_URL = "https://gmpswvvchkoghtztkldd.supabase.co"

def _diretorio_dados_usuario() -> Path:
    raiz = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    return Path(raiz) / "CW Transportadora" if raiz else BASE_DIR / "data"

class Settings:
    def __init__(self):
        self.base_dir=BASE_DIR
        self.app_data_dir=_diretorio_dados_usuario()
        self.dados_dir=self.app_data_dir/"data"
        self.db_path=self.dados_dir/"cw_transportadora.db"
        self.config_path=self.dados_dir/"configuracoes.json"
        self.sync_config_path=self.dados_dir/"sync_config.json"
        self.backup_auto_dir=self.app_data_dir/"backups"/"auto"
        self.backup_dir=self.app_data_dir/"backups"
        self.logs_dir=self.app_data_dir/"logs"
        self.primeiro_acesso_dir=self.app_data_dir/"auth"
        self.project_dir=BASE_DIR
        self.pasta_relatorios="relatorios_gerados"
        self.relatorios_dir=self.app_data_dir/self.pasta_relatorios
        self.intervalo_sync_ms=300000
        self.github_repo_owner="brunogaspere27-ai"
        self.github_repo_name="atualizacoes-sistema"
        self.github_token=""
        self.github_release_branch="ui/premium-redesign-v3"
        self.github_use_cdn=False
        self.enable_auto_update=False
        self.configuracoes=self._config_padrao()
        self.reload()

    # Compatibilidade com telas/serviços legados que ainda acessam
    # atributos diretamente. A fonte oficial continua sendo configuracoes.
    @property
    def empresa(self): return str(self.configuracoes.get("empresa") or "CW TRANSPORTADORA")
    @empresa.setter
    def empresa(self, valor): self.configuracoes["empresa"] = str(valor or "CW TRANSPORTADORA")
    @property
    def meta_lucro(self):
        try: return float(self.configuracoes.get("meta_lucro") or 0)
        except (TypeError, ValueError): return 0.0
    @meta_lucro.setter
    def meta_lucro(self, valor): self.configuracoes["meta_lucro"] = str(valor)
    @property
    def imposto_percentual(self):
        try: return float(self.configuracoes.get("imposto_percentual") or 0)
        except (TypeError, ValueError): return 0.0
    @imposto_percentual.setter
    def imposto_percentual(self, valor): self.configuracoes["imposto_percentual"] = str(valor)

    def _config_padrao(self):
        return {
            "empresa":"CW TRANSPORTADORA","cnpj":"","telefone":"","email":"","cidade":"","uf":"",
            "meta_lucro":"10000","imposto_percentual":"3","pasta_relatorios":"relatorios_gerados",
            "alerta_revisao":"8000","revisao_obrigatoria":"10000","tema":"Premium Escuro","cor_tema":"Vermelho",
            "update_server_type":"http","update_server_path":"","update_server_username":"","update_server_password":"",
            "update_channel":"stable","enable_auto_update":False,"update_url":"","update_timeout":10,
            "github_repo_owner":"brunogaspere27-ai","github_repo_name":"atualizacoes-sistema","github_token":"","github_use_cdn":True,"github_release_branch":"ui/premium-redesign-v3",
            "supabase_url":os.getenv("SUPABASE_URL") or _DEFAULT_SUPABASE_URL,
            "supabase_key":os.getenv("SUPABASE_KEY",""),
            # O token é segredo operacional e, na V15, é armazenado no
            # Gerenciador de Credenciais do Windows quando keyring está disponível.
            "supabase_sync_token":os.getenv("SUPABASE_SYNC_TOKEN","")
        }

    def reload(self):
        load_dotenv(override=True)
        dados=self._config_padrao()
        if self.config_path.exists():
            try:
                dados.update(json.loads(self.config_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        self.configuracoes=dados
        self.pasta_relatorios=str(dados.get("pasta_relatorios") or "relatorios_gerados").strip()
        # Dados gerados pela empresa ficam fora da pasta da versão instalada.
        # Caminhos absolutos continuam sendo respeitados para quem escolheu
        # explicitamente uma pasta externa (servidor, rede, etc.).
        pasta_relatorios=Path(self.pasta_relatorios)
        self.relatorios_dir=(pasta_relatorios if pasta_relatorios.is_absolute()
                             else self.app_data_dir/pasta_relatorios)
        self.enable_auto_update=bool(dados.get("enable_auto_update", False))
        self.github_use_cdn=bool(dados.get("github_use_cdn", True))
        self.github_repo_owner=str(dados.get("github_repo_owner") or "brunogaspere27-ai").strip()
        self.github_repo_name=str(dados.get("github_repo_name") or "atualizacoes-sistema").strip()
        self.github_token=str(dados.get("github_token") or "").strip()
        self.github_release_branch=str(dados.get("github_release_branch") or "ui/premium-redesign-v3").strip()
        self.supabase_url = str(dados.get("supabase_url") or _DEFAULT_SUPABASE_URL).strip()
        self.supabase_key = str(dados.get("supabase_key") or "").strip()
        token = str(dados.get("supabase_sync_token") or os.getenv("SUPABASE_SYNC_TOKEN") or "").strip()
        # Migração transparente: tokens antigos gravados no JSON são reaproveitados
        # e, quando possível, movidos para o Gerenciador de Credenciais.
        if not token and keyring is not None:
            try:
                token = str(keyring.get_password(_KEYRING_SERVICE, _KEYRING_TOKEN_USER) or "").strip()
            except Exception:
                token = ""
        elif token and keyring is not None:
            try:
                keyring.set_password(_KEYRING_SERVICE, _KEYRING_TOKEN_USER, token)
            except Exception:
                pass
        self.supabase_sync_token = token
        self.supabase_enabled=bool(self.supabase_url and self.supabase_key and self.supabase_sync_token)
        return self.configuracoes

    def salvar_configuracoes(self,dados):
        self.dados_dir.mkdir(parents=True,exist_ok=True)
        dados = dict(dados or {})
        token = str(dados.get("supabase_sync_token") or "").strip()
        if token:
            if keyring is not None:
                try:
                    keyring.set_password(_KEYRING_SERVICE, _KEYRING_TOKEN_USER, token)
                    # Não deixar o segredo em texto puro no configuracoes.json.
                    dados.pop("supabase_sync_token", None)
                except Exception:
                    # Compatibilidade: se o backend de credenciais não estiver
                    # disponível, preserva o comportamento antigo.
                    pass
        atual=self._config_padrao(); atual.update(self.configuracoes); atual.update(dados)
        if keyring is not None:
            # O segredo nunca precisa permanecer no arquivo persistente quando
            # o Gerenciador de Credenciais está disponível.
            atual.pop("supabase_sync_token", None)
        self.config_path.write_text(json.dumps(atual,ensure_ascii=False,indent=2),encoding="utf-8")
        self.reload()
        return self.configuracoes

    def restaurar_padrao(self):
        dados=self._config_padrao()
        self.config_path.write_text(json.dumps(dados,ensure_ascii=False,indent=2),encoding="utf-8")
        self.reload()
        return self.configuracoes

    def resource_path(self,relative_path): return BASE_DIR/relative_path

settings=Settings()
