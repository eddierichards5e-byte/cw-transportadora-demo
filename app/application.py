"""
CW Transportadora - Sistema de Gestão Logística
Versão PySide6 (Qt6) - Interface Moderna 2026

Camada de aplicação: bootstrap, sessão, nuvem, sincronização e ciclo de vida.
Migração de CustomTkinter para PySide6 mantendo 100% da funcionalidade.
"""

print("[FILE_LOAD] main_pyside6.py started loading", flush=True)
import os
import sys
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QMessageBox, QInputDialog, QSplashScreen, QLabel,
    QLineEdit
)

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QIcon, QFont, QKeySequence, QShortcut

from config.settings import settings
from services.sync_service import sync_service
from services.github_update_service import github_update_service
from services.financeiro_service import financeiro_service
from services.auth_service import auth_service
from services.auditoria_service import auditoria_service, ACAO_LOGOUT
from utils.database import criar_banco, remover_caminhoes_demonstracao, diagnostico_banco
from utils.sync import contar_pendencias_sync
from utils.logger import get_logger
from utils.preparar_distribuicao import preparar_base_para_distribuicao
from utils.env_check import verificar_configuracao_env
from ui.modernize import modernize_screen
from ui.theme.cw_theme import cw_theme
try:
    from utils.command_palette import command_registry
except Exception:
    command_registry = None
try:
    from services.search_service import search_service
except Exception:
    search_service = None

# Telas efetivamente usadas pela distribuição CW Enterprise.
# As demais telas antigas foram removidas da V15.

logger = get_logger(__name__)


# ------------------------------------------------------------------ Instrumentação
import time as _time
_START_TIME = _time.time()


def _log_step(msg: str) -> None:
    """Log com timestamp desde o boot, tanto no stdout quanto no logger.

    Usado para diagnóstico de startup lento. Se algo travar, o último `_log_step`
    impresso mostra onde.
    """
    elapsed = _time.time() - _START_TIME
    line = f"[STARTUP +{elapsed:6.2f}s] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        logger.info(line)
    except Exception:
        pass


class App(QMainWindow):
    # Resultado de sync emitido da thread de trabalho para a thread Qt principal.
    sync_resultado = Signal(object, bool, float)

    """Aplicação principal CW Transportadora em PySide6."""

    # Sinal usado para propagar resultados do bootstrap de volta à UI thread.
    # QTimer.singleShot() NÃO é thread-safe quando chamado de threads não-Qt;
    # emitir um Signal é a forma correta de cruzar a barreira de thread em Qt.
    _bootstrap_concluido = Signal(object)  # payload: diagnóstico do bootstrap
    _bootstrap_erro = Signal(str)
    _online_gate_resultado = Signal(object)

    def __init__(self):
        super().__init__()
        _log_step("App.__init__: início")

        # Conectar sinais do bootstrap antes de disparar a thread
        self._bootstrap_concluido.connect(self._on_bootstrap_concluido)
        self._bootstrap_erro.connect(self._on_bootstrap_erro)
        self._online_gate_resultado.connect(self._on_online_gate_resultado)
        self._sessao_online = False
        self._online_gate_busy = False
        self._online_watchdog_busy = False

        # Carregar configurações
        settings.reload()
        self.config = settings.configuracoes
        _log_step("App.__init__: settings.reload() ok")

        # Configurar tema CW
        if cw_theme is not None:
            self.cores = cw_theme.colors
        else:
            self.cores = {}
        _log_step("App.__init__: tema CW aplicado")

        # Estado da aplicação
        self.ultima_sync_texto = "Ainda não sincronizado"
        self.tela_atual = "dashboard"
        self.splash = None  # deprecated - mantido só pra compat

        # Configurar janela principal
        self._setup_window()
        _log_step("App.__init__: _setup_window ok")

        # Inicializar componentes
        self._init_components()
        _log_step("App.__init__: _init_components ok")

        # Mostrar login IMEDIATAMENTE (sem splash, sem espera)
        self._show_login()
        _log_step("App.__init__: _show_login ok (login criado)")

        # Preparar ambiente em THREAD REAL (banco, bcrypt, cloud check).
        # Aguardamos 50ms para garantir que o primeiro paint do login foi feito.
        QTimer.singleShot(50, self._start_background_bootstrap)
        _log_step("App.__init__: bootstrap agendado. __init__ concluído.")

    def _start_background_bootstrap(self):
        """Dispara o bootstrap em thread separada."""
        _log_step("bootstrap: disparando thread")
        threading.Thread(
            target=self._background_bootstrap,
            daemon=True,
            name="cw-bootstrap",
        ).start()

    def _background_bootstrap(self):
        """Roda inicialização pesada em thread separada (banco, cloud, etc).

        IMPORTANTE: nunca chamar QTimer.singleShot() daqui — não é thread-safe.
        Usamos Signal para despachar de volta para a UI thread.
        """
        try:
            _log_step("bootstrap[thread]: iniciando _prepare_environment")
            self._prepare_environment()
            _log_step("bootstrap[thread]: _prepare_environment concluído")
            # Emitir sinal — Qt enfileira a chamada na UI thread automaticamente
            self._bootstrap_concluido.emit({"banco": diagnostico_banco()})
        except Exception as erro:
            logger.error(f"Falha no bootstrap: {erro}", exc_info=True)
            self._bootstrap_erro.emit(str(erro))

    def _on_bootstrap_concluido(self, resultado: object):
        """Chamado na UI thread quando o bootstrap termina com sucesso."""
        if isinstance(resultado, dict):
            banco = resultado.get("banco") or {}
        else:
            banco = diagnostico_banco()

        self._diagnostico_banco = banco
        _log_step(
            "bootstrap: banco efetivo=%s | usuarios=%s | persistente=%s"
            % (banco.get("caminho"), banco.get("usuarios"), banco.get("banco_persistente"))
        )
        try:
            if getattr(self, "login_widget", None) is not None:
                self.login_widget.definir_diagnostico_inicial(banco)
        except Exception as exc:
            logger.warning("Não foi possível exibir diagnóstico do banco no login: %s", exc)

        # Configurar atalhos agora que estamos na UI thread
        self._setup_shortcuts()
        cloud_msg = getattr(self, "_cloud_warning_msg", None)
        if cloud_msg:
            # V15: uma instalação nova não pode chegar ao login sem a nuvem
            # configurada. O assistente valida o endpoint antes de aceitar
            # credenciais locais e grava a configuração na área persistente.
            QTimer.singleShot(250, self._garantir_configuracao_nuvem)
            return
        self._check_saved_session()

    def _on_bootstrap_erro(self, mensagem: str):
        """Chamado na UI thread quando o bootstrap falha."""
        logger.error(f"Bootstrap falhou: {mensagem}")
        # Mesmo em caso de erro no bootstrap, o login ainda funciona normalmente
        self._check_saved_session()
    
    def _setup_window(self):
        """Configura a janela principal."""
        self.setWindowTitle("CW TRANSPORTADORA V8 — Sistema de Gestão Logística")
        self.setMinimumSize(1400, 800)
        self.resize(1600, 950)

        # Aplicar stylesheet do tema CW
        if cw_theme is not None:
            self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {cw_theme.colors['bg_primary']};
            }}
            QWidget {{
                border: none;
                outline: none;
            }}
            """)
        else:
            self.setStyleSheet("""
            QMainWindow { background-color: #07090c; }
            QWidget {
                border: none;
                outline: none;
            }
            """)

        # Ícone da aplicação
        logo_path = str(settings.resource_path("assets/logo_cw.jpg"))
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))
    
    def _init_components(self):
        """Inicializa os componentes da UI."""
        # Container principal
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Layout principal
        self.main_layout = QHBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.central_widget.setLayout(self.main_layout)

        # Stacked widget principal para alternar entre login e interface principal
        self.main_stacked_widget = QStackedWidget()
        self.main_layout.addWidget(self.main_stacked_widget)

        # Container para interface principal (sidebar + right panel)
        self.main_interface_container = QWidget()
        self.main_interface_layout = QHBoxLayout()
        self.main_interface_layout.setContentsMargins(0, 0, 0, 0)
        self.main_interface_layout.setSpacing(0)
        self.main_interface_container.setLayout(self.main_interface_layout)

        # Sidebar (será criada após login)
        self.sidebar = None

        # Right panel: topbar + content
        self.right_panel = QWidget()
        self.right_panel.setObjectName("rightPanel")
        if cw_theme is not None:
            self.right_panel.setStyleSheet(f"""
            QWidget#rightPanel {{
                background-color: {cw_theme.colors['bg_primary']};
            }}
            """)
        else:
            self.right_panel.setStyleSheet("QWidget#rightPanel { background-color: #07090c; }")
        self.right_layout = QVBoxLayout()
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(0)
        self.right_panel.setLayout(self.right_layout)

        # TopBar (será criada após login)
        self.topbar = None

        # Área de conteúdo
        self.content_area = QWidget()
        self.content_area.setObjectName("contentArea")
        if cw_theme is not None:
            self.content_area.setStyleSheet(f"""
            QWidget#contentArea {{
                background-color: {cw_theme.colors['bg_primary']};
            }}
            """)
        else:
            self.content_area.setStyleSheet("QWidget#contentArea { background-color: #07090c; }")
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        self.content_area.setLayout(self.content_layout)

        # Stacked widget para telas
        self.stacked_widget = QStackedWidget()
        self.content_layout.addWidget(self.stacked_widget)

        # Adicionar right panel ao container da interface principal
        self.main_interface_layout.addWidget(self.right_panel, 1)

        # Tela de login (inicialmente)
        self.login_widget = None

        # Adicionar container da interface principal ao stacked widget (índice 0)
        self.main_stacked_widget.addWidget(self.main_interface_container)

        # Referências para telas
        self.telas = {}

        # Botões opcionais
        self.btn_sync = None
        # Se uma alteração local acontecer enquanto outra sincronização estiver
        # em andamento, guardamos a solicitação para iniciar uma segunda rodada
        # assim que a primeira terminar. Isso evita que um lançamento recém-criado
        # fique aguardando o próximo ciclo automático.
        self._sync_requested_again = False
        self._sync_requested_message = False
        self.sync_resultado.connect(self._receber_resultado_sync)

        # Títulos das telas (icônes usados em placeholders)
        self.titulos_telas = {
            "dashboard": ("PAINEL PRINCIPAL", "Controle operacional, financeiro e logístico da frota", "dashboard"),
            "operacoes": ("NOVA OPERAÇÃO", "Registro de transferências SP → Cascavel", "operations"),
            "notas": ("NOTAS IMPORTADAS", "Importação de manifestos TXT e gestão de notas", "notes"),
            "criar_viagem": ("CRIAR VIAGEM", "Montagem de viagens por cliente e seleção de notas", "truck"),
            "historico": ("VIAGENS", "Histórico, acompanhamento e finalização de viagens", "trips"),
            "ranking_clientes": ("RANKING DE CLIENTES", "Desempenho e volume por cliente", "ranking"),
            "combustivel": ("COMBUSTÍVEL", "Abastecimentos, consumo e média km/L", "fuel"),
            "contas": ("CONTAS", "Contas a pagar, a receber e fluxo financeiro", "accounts"),
            "relatorios": ("RELATÓRIOS", "Relatórios gerenciais e exportação em PDF", "reports"),
            "manutencao": ("MANUTENÇÃO", "Registro e controle de manutenção da frota", "maintenance"),
            "funcionarios": ("FUNCIONÁRIOS", "Cadastro de equipe e folha de pagamento", "employees"),
            "configuracoes": ("CONFIGURAÇÕES", "Empresa, backup, tema e preferências do sistema", "settings"),
            "historico_versoes": ("HISTÓRICO DE VERSÕES", "Informações de atualizações e releases do sistema", "history"),
            "minha_conta": ("MINHA CONTA", "Preferências e alteração de senha", "user"),
            "usuarios": ("GERENCIAR USUÁRIOS", "Administração de usuários e permissões", "admin"),
            "auditoria": ("AUDITORIA", "Registro de ações do sistema", "audit"),
            "publicar_versao": ("PUBLICAR VERSÃO", "Distribuir nova versão para todos os computadores", "upload"),
            "admin_atualizacoes": ("ADMIN. DE ATUALIZAÇÕES", "Gerencie publicações e visualize histórico de versões", "sync"),
        }
    
    def _create_splash(self):
        """Deprecated: não usamos mais splash - o login é mostrado direto."""
        self.splash = None
    
    def _prepare_environment(self) -> Optional[str]:
        """Prepara o ambiente do sistema (banco, cloud, backup).

        O bootstrap não gera nem exibe senha mestre. A credencial mestre é
        definida pelo fluxo estável de autenticação e pode ser alterada depois
        pelo administrador.

        IMPORTANTE: este método roda em thread de background.
        NÃO chamar QTimer.singleShot() aqui — use Signals para comunicar
        resultados de volta à UI thread.
        """
        # Criar banco de dados
        _log_step("prepare_env: criando banco...")
        criar_banco()
        try:
            _log_step("prepare_env: índices V83 aplicados")
        except Exception as exc:
            logger.warning("Migração V83 não crítica não aplicada: %s", exc)
        _log_step("prepare_env: banco pronto")

        _log_step("prepare_env: removendo veículos de demonstração legados...")
        removidos_frota = remover_caminhoes_demonstracao()
        _log_step(f"prepare_env: frota real preservada; demonstração removida={removidos_frota}")

        # Garantir usuário mestre (PBKDF2 pode levar ~250ms — ok aqui em background)
        _log_step("prepare_env: garantindo usuário mestre...")
        auth_service.garantir_usuario_mestre()
        _log_step("prepare_env: usuário mestre ok")

        # Verificar configuração de nuvem usando a configuração persistente do
        # aplicativo. A V54 não deve depender de um .env ficar ao lado do
        # executável, porque o configurador grava as credenciais no perfil
        # persistente do Windows (%LOCALAPPDATA%\CW Transportadora).
        _log_step("prepare_env: verificando configuração cloud persistente...")
        settings.reload()
        _cloud_ok = bool(settings.supabase_enabled)
        _cloud_msg = (
            "OK" if _cloud_ok else
            "Supabase não configurado. Use Configurações > Nuvem Supabase."
        )
        _log_step(f"prepare_env: cloud check -> ok={_cloud_ok}")
        if not _cloud_ok:
            # Armazena para exibir na UI thread via _on_bootstrap_concluido
            self._cloud_warning_msg = _cloud_msg
        else:
            self._cloud_warning_msg = None

        # Backup automático em sub-thread (não bloqueia o bootstrap)
        threading.Thread(target=self.backup_automatico, daemon=True).start()

        _log_step("prepare_env: concluído")
        return None
    
    def _check_saved_session(self):
        """Verifica sessão salva, mas nunca entra sem validar a nuvem."""
        usuario_salvo = auth_service.verificar_sessao_salva()
        if usuario_salvo:
            QTimer.singleShot(300, lambda: self._validar_nuvem_e_entrar(usuario_salvo, "sessão salva"))

    def _validar_nuvem_e_entrar(self, usuario_dados: Dict[str, Any], origem: str = "login"):
        """Gate obrigatório: autenticação local + conexão com a nuvem.

        Importante: a sincronização completa NÃO é executada durante o login.
        O login só valida que o Supabase está acessível. A sincronização fica
        disponível para execução explícita e não pode travar a abertura da UI.
        """
        if self._online_gate_busy:
            return
        self._online_gate_busy = True

        def tarefa():
            try:
                if not settings.supabase_enabled:
                    raise RuntimeError("A nuvem Supabase não está configurada nesta instalação. O CW está configurado para não operar offline.")

                from utils.supabase_db import SupabaseClient
                client = SupabaseClient(timeout=8)
                try:
                    client.health_check()
                finally:
                    client.close()

                logger.info("[ONLINE GATE] nuvem validada; sincronização automática no login desativada")
                self._online_gate_resultado.emit({"ok": True, "usuario": usuario_dados, "origem": origem})
            except Exception as exc:
                logger.error("[ONLINE GATE] acesso bloqueado: %s", exc)
                self._online_gate_resultado.emit({"ok": False, "erro": str(exc), "origem": origem})

        threading.Thread(target=tarefa, daemon=True, name="cw-online-gate").start()

    def _on_online_gate_resultado(self, resultado: object):
        if not isinstance(resultado, dict):
            return
        if resultado.get("watchdog"):
            self._online_watchdog_busy = False
            if not resultado.get("ok") and self._sessao_online:
                self._sessao_online = False
                try:
                    auth_service.logout()
                except Exception:
                    pass
                self.main_stacked_widget.setCurrentIndex(1)
                QMessageBox.critical(
                    self,
                    "Conexão perdida",
                    "A conexão com a nuvem foi perdida.\n\nO CW foi bloqueado para impedir alterações fora de sincronização.\n\n"
                    + str(resultado.get("erro") or "Reconecte a internet e entre novamente."),
                )
            else:
                self._iniciar_watchdog_online()
            return
        self._online_gate_busy = False
        if resultado.get("ok"):
            self._sessao_online = True
            self._init_main_interface()
            self._iniciar_watchdog_online()
            return

        self._sessao_online = False
        try:
            auth_service.logout()
        except Exception:
            pass
        if self.login_widget:
            self.main_stacked_widget.setCurrentIndex(1)
            self.login_widget.show()
        QMessageBox.critical(
            self,
            "Conexão obrigatória",
            "O CW não pode ser utilizado sem conexão com a nuvem.\n\n"
            + str(resultado.get("erro") or "Verifique sua internet e a configuração do Supabase.")
            + "\n\nNenhum dado local será enviado enquanto a conexão não for validada.",
        )

    def _iniciar_watchdog_online(self):
        """Confirma periodicamente que a sessão continua online."""
        QTimer.singleShot(60000, self._executar_watchdog_online)

    def _executar_watchdog_online(self):
        if not self._sessao_online or self._online_watchdog_busy:
            return
        self._online_watchdog_busy = True

        def tarefa():
            ok = False
            erro = ""
            try:
                if not settings.supabase_enabled:
                    raise RuntimeError("Supabase não configurado")
                from utils.supabase_db import SupabaseClient
                client = SupabaseClient(timeout=8)
                try:
                    client.health_check()
                finally:
                    client.close()
                ok = True
            except Exception as exc:
                erro = str(exc)
            self._online_gate_resultado.emit({"watchdog": True, "ok": ok, "erro": erro})

        threading.Thread(target=tarefa, daemon=True, name="cw-online-watchdog").start()

    

    def _show_cloud_warning(self, mensagem: str):
        """Mostra aviso sobre sincronização desativada."""
        QMessageBox.warning(
            self,
            "⚠️ Sincronização Desativada",
            mensagem
        )

    def _garantir_configuracao_nuvem(self):
        """Abre o assistente de nuvem na primeira execução da instalação."""
        try:
            from telas.configuracao_nuvem_dialog import ConfiguracaoNuvemDialog
            dialog = ConfiguracaoNuvemDialog(self)
            if dialog.exec() == ConfiguracaoNuvemDialog.DialogCode.Accepted:
                settings.reload()
                if settings.supabase_enabled:
                    self._cloud_warning_msg = None
                    self._check_saved_session()
                    return
            # Cancelar ou sair sem uma nuvem válida encerra a aplicação, pois
            # esta edição foi explicitamente configurada para não operar offline.
            QMessageBox.warning(
                self,
                "Nuvem obrigatória",
                "O CW será encerrado porque a conexão com a nuvem não foi configurada.\n\n"
                "Configure o Supabase na próxima abertura para continuar."
            )
            self.close()
        except Exception as exc:
            logger.exception("Falha no assistente de configuração da nuvem")
            QMessageBox.critical(self, "Configuração da nuvem", f"Não foi possível abrir o assistente de nuvem.\n\n{exc}")
            self.close()
    
    def _show_login(self):
        """Mostra a tela de login imediatamente como overlay fullscreen."""
        # Se já existe login, não duplicar
        if self.login_widget is not None:
            return

        from telas.login_pyside6 import TelaLogin
        self.login_widget = TelaLogin()
        self.login_widget.login_sucesso.connect(self._on_login_success)

        # Configurar para ocupar toda a janela
        from PySide6.QtWidgets import QSizePolicy
        self.login_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )

        # Adicionar login ao stacked widget principal (índice 1)
        self.main_stacked_widget.addWidget(self.login_widget)

        # Mostrar login (índice 1, interface principal é índice 0)
        self.main_stacked_widget.setCurrentIndex(1)

        # Fechar splash se ainda estiver visível (compat)
        self._close_splash()

    def _close_splash(self):
        """Fecha o splash com segurança (idempotente)."""
        splash = getattr(self, "splash", None)
        if splash is None:
            return
        try:
            if splash.isVisible():
                splash.close()
        except RuntimeError:
            # splash já destruído
            pass

    def _splash_message(self, texto: str):
        """Atualiza a mensagem do splash se ele ainda existir."""
        splash = getattr(self, "splash", None)
        if splash is None:
            return
        try:
            if splash.isVisible():
                splash.showMessage(
                    texto,
                    Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
                    Qt.GlobalColor.white,
                )
        except RuntimeError:
            pass
    
    def _on_login_success(self, usuario_dados: Dict[str, Any]):
        """Callback quando login é bem-sucedido."""
        if usuario_dados.get("deve_alterar_senha"):
            from telas.alterar_senha_pyside6 import DialogoAlterarSenha
            dialogo = DialogoAlterarSenha(obrigatoria=True, parent=self)
            if dialogo.exec() != DialogoAlterarSenha.DialogCode.Accepted:
                auth_service.logout()
                if self.login_widget:
                    self.login_widget.show()
                return
        self._validar_nuvem_e_entrar(usuario_dados, "login")
    
    def _init_main_interface(self):
        """Inicializa a interface principal após login."""
        QApplication.processEvents()

        # Criar sidebar + topbar
        self._create_sidebar()

        # Adicionar content area ao right panel (após topbar)
        self.right_layout.addWidget(self.content_area, 1)
        self.content_area.show()

        # Switch para interface principal (índice 0)
        self.main_stacked_widget.setCurrentIndex(0)

        # Carregar dashboard
        QTimer.singleShot(0, self._load_dashboard)

        # Atualizar status de sync
        self.atualizar_ultima_sync(sync_service.ultimo_resultado)

        # Iniciar sincronização em background
        QTimer.singleShot(500, lambda: self.sincronizar_nuvem(mostrar_mensagem=False, reparar_fila=True))
        self.iniciar_sync_automatico()

        # Verificar atualizações em background
        QTimer.singleShot(1500, self.verificar_atualizacao_inicio)
    
    def _create_sidebar(self):
        """Cria a sidebar de navegação CW com novo Design System."""
        # Garante que a busca esteja pronta mesmo se o login ocorrer antes
        # da conclusão do bootstrap em segundo plano.
        command_registry.build_default_commands(self._on_navigation, self)
        command_registry.set_search_provider(self._global_search_commands)

        # --- Header CW ---
        self.topbar = CWHeader()
        usuario = auth_service.usuario_atual or {}
        nome_usuario = usuario.get("nome_completo", "Usuário")
        self.topbar.set_user(nome_usuario)
        self.topbar.profile_requested.connect(lambda: self._on_navigation("minha_conta"))
        self.topbar.settings_requested.connect(lambda: self._on_navigation("configuracoes"))
        self.topbar.search_requested.connect(self._open_global_search)
        self.right_layout.addWidget(self.topbar)

        # --- Sidebar CW ---
        self.sidebar = CWSidebar()
        self.sidebar.item_clicked.connect(self._on_navigation)

        # Menu sections
        self.sidebar.add_section("Principal", [
            {'id': 'dashboard', 'label': 'Dashboard', 'icon': 'home'}
        ])

        self.sidebar.add_section("Operacional", [
            {'id': 'operacoes', 'label': 'Nova Operação', 'icon': 'operations'},
            {'id': 'notas', 'label': 'Notas', 'icon': 'notes'},
            {'id': 'criar_viagem', 'label': 'Criar Viagem', 'icon': 'truck'},
            {'id': 'historico', 'label': 'Viagens', 'icon': 'trips'},
            {'id': 'ranking_clientes', 'label': 'Ranking', 'icon': 'ranking'},
        ])

        self.sidebar.add_section("Frota", [
            {'id': 'combustivel', 'label': 'Combustível', 'icon': 'fuel'},
            {'id': 'manutencao', 'label': 'Manutenção', 'icon': 'maintenance'},
        ])

        self.sidebar.add_section("Financeiro", [
            {'id': 'contas', 'label': 'Contas', 'icon': 'accounts'},
            {'id': 'relatorios', 'label': 'Relatórios', 'icon': 'reports'},
        ])

        self.sidebar.add_section("RH", [
            {'id': 'funcionarios', 'label': 'Funcionários', 'icon': 'employees'},
        ])

        self.sidebar.add_section("Sistema", [
            {'id': 'configuracoes', 'label': 'Configurações', 'icon': 'settings'},
        ])

        admin_items = []
        if auth_service.pode("usuarios", "visualizar"): admin_items.append({'id': 'usuarios', 'label': 'Usuários', 'icon': 'admin'})
        if auth_service.pode("auditoria", "visualizar"): admin_items.append({'id': 'auditoria', 'label': 'Auditoria', 'icon': 'audit'})
        if auth_service.pode("historico_versoes", "visualizar"): admin_items.append({'id': 'historico_versoes', 'label': 'Versões', 'icon': 'history'})
        if admin_items:
            self.sidebar.add_section("Administração", admin_items)

        # Sincronização é uma ação de infraestrutura do aplicativo e deve ficar
        # sempre acessível no sidebar quando a nuvem estiver configurada.
        # A versão anterior escondia o botão dependendo de permissões de módulos
        # operacionais, fazendo parecer que não existia sincronização manual.
        sync_btn = CWButton("☁️ Sincronizar Nuvem", ButtonVariant.SECONDARY, ButtonSize.MD)
        sync_btn.setEnabled(auth_service.pode("configuracoes", "sincronizar"))
        sync_btn.clicked.connect(lambda: self.sincronizar_nuvem(mostrar_mensagem=True, reparar_fila=True))
        self.btn_sync = sync_btn
        self.sidebar.add_bottom_widget(sync_btn)
        
        logout_btn = CWButton("Sair", ButtonVariant.GHOST, ButtonSize.MD)
        logout_btn.clicked.connect(self.fazer_logout)
        self.sidebar.add_bottom_widget(logout_btn)

        # Insert sidebar at the beginning of main_layout
        self.main_layout.insertWidget(0, self.sidebar)
        self.sidebar.set_active_item('dashboard')
        self._update_breadcrumb('dashboard')
    
    def _create_header(self):
        """Deprecated: cada tela agora possui seu próprio cabeçalho."""
        return None

    def _on_navigation(self, tela: str):
        """Manipula navegação entre telas, respeitando autorização."""
        if tela != "minha_conta" and not auth_service.pode(tela, "visualizar"):
            QMessageBox.warning(self, "Acesso negado", "Seu perfil não possui permissão para acessar este módulo.")
            return
        self.sidebar.set_active_item(tela)
        self._load_tela(tela)
        self._update_breadcrumb(tela)

    def _on_navigation_with_cliente(self, tela: str, cliente_data: tuple):
        """Manipula navegação para tela criar_viagem com cliente pré-selecionado."""
        if not auth_service.pode(tela, "visualizar"):
            QMessageBox.warning(self, "Acesso negado", "Seu perfil não possui permissão para acessar este módulo.")
            return
        self.sidebar.set_active_item(tela)
        self._load_tela(tela, cliente_data=cliente_data)
        self._update_breadcrumb(tela)

    def _open_global_search(self, query: str = ""):
        """Abre a busca global a partir da barra superior ou do atalho Ctrl+K."""
        command_registry.open(self, query)

    def _global_search_commands(self, query: str):
        """Converte resultados locais em ações navegáveis da paleta global."""
        from utils.command_palette import Command
        try:
            results = search_service.search(query)
            commands = []
            for result in results:
                # Para clientes, passar dados para pré-seleção na tela criar_viagem
                if result.categoria == "Clientes" and result.tela == "criar_viagem":
                    # Usar closure com captura do valor específico
                    def make_action(cliente_data):
                        return lambda: self._on_navigation_with_cliente("criar_viagem", cliente_data)
                    action = make_action(result.cliente_data)
                else:
                    action = lambda screen=result.tela: self._on_navigation(screen)
                
                commands.append(Command(
                    id=f"record:{result.categoria}:{result.registro_id}",
                    label=result.titulo,
                    description=result.descricao,
                    icon=result.icon,
                    category=result.categoria,
                    action=action,
                ))
            return commands
        except Exception as e:
            print(f"Erro na busca global: {e}")
            return []

    def _update_breadcrumb(self, tela: str):
        """Atualiza o breadcrumb da TopBar."""
        if not self.topbar:
            return
        section_map = {
            "dashboard": ("Principal", "Dashboard"),
            "operacoes": ("Operacional", "Nova Operação"),
            "notas": ("Operacional", "Notas"),
            "criar_viagem": ("Operacional", "Criar Viagem"),
            "historico": ("Operacional", "Viagens"),
            "ranking_clientes": ("Operacional", "Ranking"),
            "combustivel": ("Frota", "Combustível"),
            "manutencao": ("Frota", "Manutenção"),
            "contas": ("Financeiro", "Contas"),
            "relatorios": ("Financeiro", "Relatórios"),
            "funcionarios": ("RH", "Funcionários"),
            "configuracoes": ("Sistema", "Configurações"),
            "minha_conta": ("Sistema", "Meu Perfil"),
            "usuarios": ("Administração", "Usuários"),
            "auditoria": ("Administração", "Auditoria"),
            "historico_versoes": ("Administração", "Versões"),
        }
        section, page = section_map.get(tela, ("", tela.replace("_", " ").title()))
        self.topbar.set_breadcrumb(section, page)

    def _load_tela(self, tela: str, cliente_data: tuple = None):
        """Carrega uma tela específica (com placeholder polido para telas não migradas)."""
        self.tela_atual = tela

        # Despachar para o método específico de cada tela
        loaders = {
            "dashboard": self._load_dashboard,
            "operacoes": self._load_operacoes,
            "notas": self._load_notas,
            "ranking_clientes": self._load_ranking_clientes,
            "historico_versoes": self._load_historico_versoes,
            "criar_viagem": lambda: self._load_criar_viagem(cliente_data),
            "historico": self._load_historico,
            "combustivel": self._load_combustivel,
            "manutencao": self._load_manutencao,
            "contas": self._load_contas,
            "relatorios": self._load_relatorios,
            "funcionarios": self._load_funcionarios,
            "configuracoes": self._load_configuracoes,
            "usuarios": self._load_usuarios,
            "auditoria": self._load_auditoria,
            "minha_conta": self._load_perfil,
        }

        loader = loaders.get(tela)
        if loader:
            loader()
            return

        # Fallback: placeholder para telas ainda não migradas
        if tela not in self.telas:
            titulo, subtitulo, icone = self.titulos_telas.get(
                tela, (tela.upper(), "Tela em desenvolvimento", "settings")
            )

            # Criar placeholder simples com tema CW
            placeholder = QWidget()
            pl = QVBoxLayout()
            title_label = QLabel(titulo)
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            subtitle_label = QLabel(subtitulo)
            subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            subtitle_label.setWordWrap(True)
            if cw_theme is not None:
                placeholder.setStyleSheet(f"background-color: {cw_theme.colors['bg_primary']};")
                pl.setContentsMargins(cw_theme.spacing._3XL, cw_theme.spacing._3XL, cw_theme.spacing._3XL, cw_theme.spacing._3XL)
                pl.setSpacing(cw_theme.spacing.LG)
                title_label.setFont(cw_theme.get_font(cw_theme.typography.FONT_SIZE_2XL, bold=True))
                title_label.setStyleSheet(f"color: {cw_theme.colors['text_primary']}; background: transparent;")
                subtitle_label.setFont(cw_theme.get_font(cw_theme.typography.FONT_SIZE_MD))
                subtitle_label.setStyleSheet(f"color: {cw_theme.colors['text_secondary']}; background: transparent;")
            else:
                placeholder.setStyleSheet("background-color: #07090c;")
                pl.setContentsMargins(40, 40, 40, 40)
                pl.setSpacing(16)
                title_label.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
                title_label.setStyleSheet("color: #FFFFFF; background: transparent;")
                subtitle_label.setFont(QFont("Segoe UI", 14))
                subtitle_label.setStyleSheet("color: #A0AEC0; background: transparent;")
            pl.addWidget(title_label)

            subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            subtitle_label.setWordWrap(True)
            pl.addWidget(subtitle_label)
            
            placeholder.setLayout(pl)

            self.telas[tela] = placeholder
            self.stacked_widget.addWidget(placeholder)

        self.stacked_widget.setCurrentWidget(self.telas[tela])
    
    def _load_dashboard(self):
        self._load_tela("dashboard")

    def _carregar_tela_generica(self, chave: str, classe, cliente_data: tuple = None):
        """Carrega uma tela PySide6 de forma genérica com tratamento de erro."""
        if chave not in self.telas:
            try:
                # Passar cliente_data se disponível (para tela criar_viagem)
                if cliente_data and chave == "criar_viagem":
                    self.telas[chave] = classe(cliente_pre_selecionado=cliente_data)
                else:
                    self.telas[chave] = classe()
                modernize_screen(self.telas[chave])
            except Exception as erro:
                logger.error(f"Falha ao carregar tela '{chave}': {erro}")
                # Criar placeholder de erro com tema CW
                error_placeholder = QWidget()
                epl = QVBoxLayout()
                if cw_theme is not None:
                    error_placeholder.setStyleSheet(f"background-color: {cw_theme.colors['bg_primary']};")
                    epl.setContentsMargins(cw_theme.spacing._3XL, cw_theme.spacing._3XL, cw_theme.spacing._3XL, cw_theme.spacing._3XL)
                    epl.setSpacing(cw_theme.spacing.LG)
                else:
                    error_placeholder.setStyleSheet("background-color: #07090c;")
                    epl.setContentsMargins(40, 40, 40, 40)
                    epl.setSpacing(16)
                
                title_label = QLabel(f"Erro ao carregar {chave}")
                if cw_theme is not None:
                    title_label.setFont(cw_theme.get_font(cw_theme.typography.FONT_SIZE_XL, bold=True))
                    title_label.setStyleSheet(f"color: {cw_theme.colors['error']}; background: transparent;")
                else:
                    title_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
                    title_label.setStyleSheet("color: #EF4444; background: transparent;")
                title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                epl.addWidget(title_label)

                subtitle_label = QLabel(f"Não foi possível carregar esta tela.\n{erro}")
                if cw_theme is not None:
                    subtitle_label.setFont(cw_theme.get_font(cw_theme.typography.FONT_SIZE_MD))
                    subtitle_label.setStyleSheet(f"color: {cw_theme.colors['text_secondary']}; background: transparent;")
                else:
                    subtitle_label.setFont(QFont("Segoe UI", 14))
                    subtitle_label.setStyleSheet("color: #A0AEC0; background: transparent;")
                subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                subtitle_label.setWordWrap(True)
                epl.addWidget(subtitle_label)
                
                error_placeholder.setLayout(epl)

                self.telas[chave] = error_placeholder
            self.stacked_widget.addWidget(self.telas[chave])
        self.stacked_widget.setCurrentWidget(self.telas[chave])
        self.tela_atual = chave

    def _load_operacoes(self):
        self._load_tela("operacoes")

    def _load_notas(self):
        from telas.notas_manifestos_tms_pyside6 import NotasManifestosTMS
        self._carregar_tela_generica("notas", NotasManifestosTMS)

    def _load_ranking_clientes(self):
        self._load_tela("ranking_clientes")

    def _load_historico_versoes(self):
        self._load_tela("historico_versoes")

    def _load_criar_viagem(self, cliente_data=None):
        self._load_tela("criar_viagem")

    def _load_historico(self):
        self._load_tela("historico")

    def _load_combustivel(self):
        self._load_tela("combustivel")

    def _load_manutencao(self):
        self._load_tela("manutencao")

    def _load_contas(self):
        self._load_tela("contas")

    def _load_relatorios(self):
        self._load_tela("relatorios")

    def _load_funcionarios(self):
        self._load_tela("funcionarios")

    def _load_configuracoes(self):
        self._load_tela("configuracoes")

    def _load_usuarios(self):
        self._load_tela("usuarios")

    def _load_perfil(self):
        self._load_tela("perfil")

    def _load_auditoria(self):
        self._load_tela("auditoria")

    def fazer_logout(self):
        """Faz logout do usuário."""
        usuario = auth_service.usuario_atual
        if usuario:
            auditoria_service.registrar(
                ACAO_LOGOUT, "auth", usuario["usuario"],
                usuario_id=usuario["id"],
                usuario_nome=usuario["nome_completo"],
            )
        auth_service.logout()

        # Limpar sidebar e topbar
        if self.sidebar:
            self.main_interface_layout.removeWidget(self.sidebar)
            self.sidebar.deleteLater()
            self.sidebar = None

        if self.topbar:
            self.right_layout.removeWidget(self.topbar)
            self.topbar.deleteLater()
            self.topbar = None

        # Remover área de conteúdo e limpar telas cacheadas
        if self.content_area.parent() is self.right_panel:
            self.right_layout.removeWidget(self.content_area)
            self.content_area.setParent(None)

        for nome, widget in list(self.telas.items()):
            self.stacked_widget.removeWidget(widget)
            widget.deleteLater()
        self.telas.clear()

        self.btn_sync = None

        # Switch para tela de login (índice 1)
        self.main_stacked_widget.setCurrentIndex(1)
    
    def backup_automatico(self):
        """Executa backup automático do banco de dados."""
        try:
            pasta_backup = settings.backup_auto_dir
            origem_db = settings.db_path
            
            if not origem_db.exists():
                return
            
            if not pasta_backup.exists():
                pasta_backup.mkdir(parents=True, exist_ok=True)
            
            nome_backup = f"backup_auto_{datetime.now().strftime('%d%m%Y_%H%M%S')}.db"
            destino_db = pasta_backup / nome_backup
            
            shutil.copy2(origem_db, destino_db)
            
            # Manter apenas os últimos 20 backups
            backups = sorted(
                pasta_backup.glob("*.db"),
                key=lambda item: item.stat().st_mtime,
                reverse=True
            )
            
            for backup_antigo in backups[20:]:
                backup_antigo.unlink(missing_ok=True)
        
        except Exception as erro:
            logger.error(f"Erro no backup automático: {erro}")
    
    def preparar_distribuicao(self):
        """Prepara a base para distribuição."""
        if sync_service.sincronizando:
            QMessageBox.warning(
                self,
                "Sincronização em andamento",
                "Aguarde a sincronização terminar antes de preparar a distribuição."
            )
            return
        
        confirmar, ok = QInputDialog.getText(
            self,
            "Preparar Distribuição",
            "ATENÇÃO!\n\n"
            "Isso vai apagar TODOS os dados locais e da nuvem.\n\n"
            "Digite ZERAR para confirmar:",
            QLineEdit.EchoMode.Normal,
            "",
        )
        
        if not ok or confirmar != "ZERAR":
            return
        
        criar_backup = QMessageBox.question(
            self,
            "Backup",
            "Deseja criar um backup antes de limpar?\n\n"
            "Sim = cria backup\n"
            "Não = limpa sem backup",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )
        
        if criar_backup == QMessageBox.StandardButton.Cancel:
            return
        
        try:
            backup = preparar_base_para_distribuicao(
                criar_backup=(criar_backup == QMessageBox.StandardButton.Yes)
            )
            
            if backup:
                mensagem = f"Base zerada com sucesso!\n\nBackup criado em:\n{backup}"
            else:
                mensagem = "Base zerada com sucesso!\n\nNenhum backup foi criado."
            
            QMessageBox.information(self, "Preparação concluída", mensagem)
        
        except Exception as erro:
            QMessageBox.critical(
                self,
                "Erro ao preparar distribuição",
                f"Não foi possível concluir a preparação da distribuição.\n\nDetalhes: {str(erro)}"
            )
    
    def sincronizar_nuvem(self, mostrar_mensagem=False, reparar_fila=True):
        """Sincroniza dados com a nuvem.

        Se uma alteração local pedir sincronização enquanto outra já estiver
        rodando, a solicitação fica marcada e uma nova rodada é disparada
        automaticamente ao término da atual.
        """
        if sync_service.sincronizando:
            self._sync_requested_again = True
            self._sync_requested_message = self._sync_requested_message or bool(mostrar_mensagem)
            logger.info("[SYNC UI] sincronização já em andamento; nova rodada enfileirada")
            return
        
        inicio = datetime.now()
        
        if self.btn_sync:
            self.btn_sync.setText("☁️ Sincronizando...")
            self.btn_sync.setEnabled(False)
        
        def tarefa():
            try:
                resultado = sync_service.executar(reparar_fila=reparar_fila)
                
                cor = resultado.get("status")
                if resultado.get("offline"):
                    cor = "offline"
                elif resultado.get("status") == "partial":
                    cor = "partial"
                elif resultado.get("status") == "error":
                    cor = "error"
                
                duracao = (datetime.now() - inicio).total_seconds()
                
                # Entrega o resultado por Signal: QTimer.singleShot chamado
                # dentro da thread de trabalho pode não executar porque ela não
                # possui event loop Qt. O Signal garante o slot na thread principal.
                logger.info("[SYNC UI] resultado=%s enviados=%s baixados=%s erros=%s pendencias=%s detalhes=%s",
                            resultado.get("status"), resultado.get("enviados", 0),
                            resultado.get("baixados", 0), resultado.get("erros", 0),
                            resultado.get("pendencias", 0), resultado.get("detalhes") or [])
                self.sync_resultado.emit(resultado, mostrar_mensagem, duracao)
                
            except Exception as erro:
                logger.exception("[SYNC UI] exceção na thread de sincronização")
                self.sync_resultado.emit({"status": "error", "mensagem": str(erro), "detalhes": [str(erro)]}, mostrar_mensagem, 0.0)
            finally:
                # O slot principal também libera o botão.
                pass
        
        threading.Thread(target=tarefa, daemon=True).start()
    
    def _receber_resultado_sync(self, resultado, mostrar_mensagem, duracao):
        cor = resultado.get("status")
        if resultado.get("offline"):
            cor = "offline"
        self._atualizar_status_sync(resultado, cor, duracao)
        self._reset_sync_button()
        if mostrar_mensagem:
            mensagem = resultado.get("mensagem", "Sincronização concluída!")
            detalhes = resultado.get("detalhes") or []
            diagnostico = resultado.get("diagnostico") or []
            if detalhes:
                mensagem += "\n\nDetalhes:\n" + "\n".join(str(x) for x in detalhes[:12])
            if diagnostico:
                mensagem += "\n\nDiagnóstico por tabela:\n" + "\n".join(str(x) for x in diagnostico[:20])
            QMessageBox.information(self, "Sincronização", mensagem)

        # Uma conta/nota/cliente pode ter sido criada enquanto a rodada anterior
        # ainda estava enviando dados. Nesse caso, garante uma nova rodada agora.
        if self._sync_requested_again:
            nova_mensagem = self._sync_requested_message
            self._sync_requested_again = False
            self._sync_requested_message = False
            logger.info("[SYNC UI] executando nova rodada enfileirada após alteração local")
            QTimer.singleShot(150, lambda: self.sincronizar_nuvem(mostrar_mensagem=nova_mensagem, reparar_fila=True))

    def _atualizar_status_sync(self, resultado, cor, duracao):
        """Atualiza o status de sincronização na UI."""
        self.atualizar_ultima_sync(resultado)
        
        if self.btn_sync:
            texto = "☁️ Sincronizar Nuvem" if settings.supabase_enabled else "☁️ Configurar Nuvem"
            self.btn_sync.setText(texto)
    
    def _mostrar_erro_sync(self, erro, mostrar_mensagem):
        """Mostra erro de sincronização."""
        if self.btn_sync:
            self.btn_sync.setText("☁️ Sincronizar Nuvem")
        
        if mostrar_mensagem:
            QMessageBox.critical(
                self,
                "Erro ao sincronizar",
                f"A sincronização não pôde ser concluída.\n\nDetalhes: {str(erro)}"
            )
    
    def _reset_sync_button(self):
        """Reseta o botão de sincronização."""
        if self.btn_sync:
            texto = "☁️ Sincronizar Nuvem" if settings.supabase_enabled else "☁️ Configurar Nuvem"
            self.btn_sync.setText(texto)
            self.btn_sync.setEnabled(True)
    
    def atualizar_ultima_sync(self, resultado=None):
        """Atualiza informações da última sincronização."""
        resultado = resultado or {}
        pendencias = resultado.get("pendencias", contar_pendencias_sync())
        ultima_sync = resultado.get("ultima_sync")
        offline = resultado.get("offline", False)
        
        if offline:
            self.ultima_sync_texto = "⚪ Nuvem não configurada"
        else:
            agora_txt = ultima_sync or datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            self.ultima_sync_texto = f"🟢 Online - Última sync: {agora_txt}"
        
        # TODO: Atualizar label na sidebar quando implementado
    
    def iniciar_sync_automatico(self):
        """Inicia sincronização automática em intervalos regulares."""
        intervalo = settings.intervalo_sync_ms
        QTimer.singleShot(intervalo, self.executar_sync_automatico)
    
    def executar_sync_automatico(self):
        """Executa sincronização automática enquanto a sessão estiver online."""
        if self._sessao_online and not sync_service.sincronizando:
            self.sincronizar_nuvem(mostrar_mensagem=False, reparar_fila=True)
        
        intervalo = settings.intervalo_sync_ms
        QTimer.singleShot(intervalo, self.executar_sync_automatico)
    
    def verificar_atualizacao_inicio(self):
        """Verifica atualizações em background ao iniciar."""
        def tarefa():
            try:
                resultado = github_update_service.check_for_updates()
                
                if resultado.get("has_update") and resultado.get("download_url"):
                    QTimer.singleShot(0, lambda: self._mostrar_dialogo_atualizacao(resultado))
            except Exception as e:
                logger.error(f"Erro ao verificar atualização ao iniciar: {e}")
        
        threading.Thread(target=tarefa, daemon=True).start()
    
    def _mostrar_dialogo_atualizacao(self, resultado):
        """Mostra diálogo de atualização disponível."""
        # TODO: Implementar tela de atualização PySide6
        QMessageBox.information(
            self,
            "Atualização Disponível",
            f"Nova versão disponível: {resultado.get('version', 'N/A')}\n\n"
            f"Detalhes: {resultado.get('mensagem', 'Consulte o histórico de versões.')}"
        )
    
    def _setup_shortcuts(self):
        """Configura atalhos de teclado."""
        # A referência é mantida na janela para evitar que o Qt descarte o atalho.
        self._shortcut_busca_global = QShortcut(QKeySequence("Ctrl+K"), self)
        self._shortcut_busca_global.activated.connect(self._open_global_search)
        command_registry.build_default_commands(self._on_navigation, self)
    
    def closeEvent(self, event):
        """Manipula o evento de fechamento da janela."""
        # Backup automático ao fechar
        self.backup_automatico()
        
        # Confirmar fechamento
        reply = QMessageBox.question(
            self,
            "Fechar Sistema",
            "Deseja realmente fechar o CW Transportadora?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()

