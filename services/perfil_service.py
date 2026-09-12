"""
Serviço de perfil do usuário.
"""
import os
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any

from utils.database._conexao import conectar, get_connection
from config.settings import settings


class PerfilService:
    def __init__(self):
        # Fotos de perfil são dados do usuário: ficam fora da pasta da versão
        # para sobreviver a atualizações/reinstalações.
        self.avatar_dir = Path(settings.app_data_dir) / "avatars"
        self.avatar_dir.mkdir(parents=True, exist_ok=True)
        self.legacy_avatar_dir = Path(settings.base_dir) / "assets" / "avatars"
    
    def get_avatar_path(self, user_id) -> Optional[str]:
        """Retorna caminho do avatar do usuário."""
        try:
            avatar_path = self.avatar_dir / f"user_{user_id}.png"
            if avatar_path.exists():
                return str(avatar_path)
            # Compatibilidade: aproveita avatar antigo da pasta da aplicação
            # e migra para o armazenamento persistente na primeira leitura.
            legacy = self.legacy_avatar_dir / f"user_{user_id}.png"
            if legacy.exists():
                import shutil
                try:
                    shutil.copy2(legacy, avatar_path)
                    return str(avatar_path)
                except Exception:
                    return str(legacy)
            return None
        except Exception as e:
            print(f"[perfil_service] Erro ao obter avatar: {e}")
            return None
    
    def salvar_avatar(self, user_id, caminho_origem) -> Optional[str]:
        """Salva avatar do usuário."""
        try:
            import shutil
            destino = self.avatar_dir / f"user_{user_id}.png"
            shutil.copy2(caminho_origem, destino)
            return str(destino)
        except Exception as e:
            print(f"[perfil_service] Erro ao salvar avatar: {e}")
            return None
    
    def remove_avatar(self, user_id) -> bool:
        """Remove avatar do usuário."""
        try:
            avatar_path = self.avatar_dir / f"user_{user_id}.png"
            if avatar_path.exists():
                avatar_path.unlink()
            return True
        except Exception as e:
            print(f"[perfil_service] Erro ao remover avatar: {e}")
            return False
    
    def save_avatar(self, user_id, caminho_origem) -> bool:
        """Alias para salvar_avatar retornando bool."""
        return self.salvar_avatar(user_id, caminho_origem) is not None
    
    def get_user_info(self, user_id) -> Optional[Dict[str, Any]]:
        """Busca informações do usuário no banco."""
        try:
            conn = conectar()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, usuario, nome_completo, email, eh_mestre, created_at
                FROM usuarios WHERE id = ?
            """, (user_id,))
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return None
            
            return {
                "id": row[0],
                "usuario": row[1],
                "nome_completo": row[2] or "",
                "email": row[3] or "",
                "nivel": "mestre" if row[4] else "operador",
                "criado_em": row[5] or "",
            }
        except Exception as e:
            print(f"[perfil_service] Erro ao buscar usuário: {e}")
            return None
    
    def get_initials(self, nome: str) -> str:
        """Retorna iniciais do nome."""
        if not nome:
            return "?"
        parts = nome.strip().split()
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()
    
    def get_avatar_color(self, nome: str) -> str:
        """Gera uma cor determinística baseada no nome."""
        if not nome:
            return "#6366F1"
        hash_obj = hashlib.md5(nome.encode()).hexdigest()
        colors = [
            "#EF4444", "#F97316", "#F59E0B", "#84CC16", 
            "#10B981", "#06B6D4", "#3B82F6", "#6366F1",
            "#8B5CF6", "#D946EF", "#F43F5E", "#14B8A6"
        ]
        idx = int(hash_obj, 16) % len(colors)
        return colors[idx]
    
    def update_nome(self, user_id: int, novo_nome: str) -> bool:
        """Atualiza o nome completo do usuário."""
        try:
            conn = conectar()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuarios SET nome_completo = ? WHERE id = ?
            """, (novo_nome, user_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[perfil_service] Erro ao atualizar nome: {e}")
            return False


perfil_service = PerfilService()
