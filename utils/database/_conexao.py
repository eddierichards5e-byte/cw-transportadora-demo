"""
Camada de conexao, schema e rastreamento de sincronizacao (sync_log).
"""

import os
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Iterator
from pathlib import Path

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

DB_NAME = str(settings.db_path)
APP_DIR = Path(__file__).resolve().parents[2]

TABELAS_SYNC = [
    "manifestos", "clientes", "funcionarios", "folha_funcionarios",
    "notas", "caminhoes", "viagens", "viagem_notas",
    "operacoes_sp", "contas", "abastecimentos", "manutencoes"
]


def _quantidade_dados(caminho: Path) -> int:
    """Mede dados operacionais de um banco candidato à migração."""
    if not caminho.exists() or not caminho.is_file():
        return 0
    conn = None
    total = 0
    try:
        conn = sqlite3.connect(str(caminho), timeout=5)
        tabelas = (
            "manifestos", "clientes", "notas", "caminhoes", "viagens",
            "operacoes_sp", "contas", "abastecimentos", "manutencoes",
        )
        for tabela in tabelas:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()
                total += int(row[0] or 0)
            except sqlite3.Error:
                continue
    except Exception:
        return 0
    finally:
        if conn is not None:
            conn.close()
    return total


def _quantidade_usuarios(caminho: Path) -> int:
    """Conta usuários para nunca preferir um banco sem autenticação válida."""
    if not caminho.exists() or not caminho.is_file():
        return 0
    conn = None
    try:
        conn = sqlite3.connect(str(caminho), timeout=5)
        row = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0
    finally:
        if conn is not None:
            conn.close()


def _tem_tabela(caminho: Path, tabela: str) -> bool:
    if not caminho.exists() or not caminho.is_file():
        return False
    conn = None
    try:
        conn = sqlite3.connect(str(caminho), timeout=5)
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (tabela,),
        ).fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def _copiar_banco_sqlite(origem: Path, destino: Path) -> None:
    """Copia um SQLite de forma consistente usando a API Backup."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    origem_conn = sqlite3.connect(str(origem), timeout=30)
    destino_conn = sqlite3.connect(str(destino), timeout=30)
    try:
        origem_conn.backup(destino_conn)
        destino_conn.commit()
    finally:
        destino_conn.close()
        origem_conn.close()




def diagnostico_banco() -> dict:
    """Retorna diagnóstico seguro do banco efetivamente usado pela aplicação."""
    caminho = Path(DB_NAME)
    info = {
        "caminho": str(caminho.resolve()),
        "existe": caminho.exists(),
        "tamanho_bytes": 0,
        "usuarios": 0,
        "banco_persistente": caminho.resolve() == Path(settings.db_path).resolve(),
    }
    try:
        if caminho.exists():
            info["tamanho_bytes"] = caminho.stat().st_size
            info["usuarios"] = _quantidade_usuarios(caminho)
    except OSError:
        pass
    return info


def _legacy_com_usuario() -> list[Path]:
    """Localiza bancos legados que ainda possuem usuários."""
    oficial = Path(DB_NAME).resolve()
    candidatos = [
        APP_DIR / "cw_transportadora.db",
        APP_DIR / "data" / "cw_transportadora.db",
        Path.cwd() / "cw_transportadora.db",
        Path.cwd() / "data" / "cw_transportadora.db",
    ]
    resultado = []
    vistos = set()
    for caminho in candidatos:
        try:
            resolvido = caminho.resolve()
        except Exception:
            resolvido = caminho
        if resolvido in vistos or resolvido == oficial:
            continue
        vistos.add(resolvido)
        if caminho.exists() and caminho.is_file() and _quantidade_usuarios(caminho) > 0:
            resultado.append(caminho)
    return resultado

def migrar_banco_antigo() -> None:
    """Migra o banco legado para o diretório persistente uma única vez.

    Regra crítica: se o banco persistente já existe, ele é a fonte oficial e
    NUNCA é sobrescrito por outro SQLite encontrado na pasta do programa ou no
    diretório de trabalho. Essa regra elimina a causa de usuários/senhas mudarem
    quando uma nova versão é instalada em outra pasta.
    """
    banco_oficial = Path(DB_NAME)
    legacy_candidates = [
        APP_DIR / "cw_transportadora.db",
        APP_DIR / "data" / "cw_transportadora.db",
        Path.cwd() / "cw_transportadora.db",
        Path.cwd() / "data" / "cw_transportadora.db",
    ]
    unicos = []
    vistos = set()
    for caminho in legacy_candidates:
        try:
            chave = str(caminho.resolve())
        except Exception:
            chave = str(caminho)
        if chave not in vistos and Path(chave) != banco_oficial:
            vistos.add(chave)
            unicos.append(Path(chave))

    try:
        banco_oficial.parent.mkdir(parents=True, exist_ok=True)

        # Banco persistente já existe: jamais trocar pelo candidato com mais
        # registros operacionais. O login pertence a este banco.
        if banco_oficial.exists() and banco_oficial.stat().st_size > 0:
            logger.info("[BANCO] Banco persistente oficial: %s", banco_oficial)
            return

        candidatos_existentes = [p for p in unicos if p.exists() and p.is_file()]
        if not candidatos_existentes:
            logger.info("[BANCO] Banco persistente ainda não existe; será criado em %s.", banco_oficial)
            return

        # Prioridade: banco que já contém usuários. Entre os demais, maior
        # quantidade de dados operacionais. Em empate, arquivo mais recente.
        melhor = max(
            candidatos_existentes,
            key=lambda p: (
                1 if _quantidade_usuarios(p) > 0 else 0,
                _quantidade_usuarios(p),
                _quantidade_dados(p),
                p.stat().st_mtime,
            ),
        )
        usuarios = _quantidade_usuarios(melhor)
        operacional = _quantidade_dados(melhor)
        _copiar_banco_sqlite(melhor, banco_oficial)
        logger.warning(
            "[BANCO] Migração única do banco legado %s -> %s (%s usuários, %s registros operacionais).",
            melhor, banco_oficial, usuarios, operacional,
        )
    except Exception as erro:
        logger.error("[BANCO] Erro ao localizar/migrar banco: %s", erro, exc_info=True)


def migrar_marcadores_primeiro_acesso() -> None:
    """Move os marcadores antigos para a área persistente, sem sobrescrever."""
    destino = Path(settings.primeiro_acesso_dir)
    destino.mkdir(parents=True, exist_ok=True)
    for nome in ("primeiro_acesso.txt", "primeiro_acesso.status"):
        novo = destino / nome
        if novo.exists():
            continue
        antigo = Path(settings.base_dir) / nome
        if antigo.exists():
            try:
                shutil.copy2(antigo, novo)
                logger.info("[AUTH] Marcador legado migrado para %s", novo)
            except OSError as erro:
                logger.warning("[AUTH] Não foi possível migrar %s: %s", antigo, erro)


def _create_connection():
    # A aplicação desktop permanece em SQLite. A aplicação web pode selecionar
    # PostgreSQL de forma explícita via CW_DATABASE_URL/DATABASE_URL.
    if os.getenv("CW_DATABASE_URL") or os.getenv("DATABASE_URL"):
        from utils.database.postgres_compat import connect_postgres
        return connect_postgres()
    Path(DB_NAME).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = _create_connection()
    try:
        yield conn
    except Exception as e:
        logger.error(f"Erro na conexao com banco: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_connection_rows() -> Iterator[sqlite3.Connection]:
    conn = _create_connection()
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    except Exception as e:
        logger.error(f"Erro na conexao com banco: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def conectar() -> sqlite3.Connection:
    return _create_connection()


def agora_sync() -> str:
    """Timestamp de sincronização com precisão de microssegundos.

    Em um ambiente com vários PCs, segundos não são suficientes para ordenar
    duas alterações feitas quase simultaneamente.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def novo_id_global() -> int:
    """Gera um ID inteiro praticamente impossível de colidir entre máquinas.

    O sistema usa IDs inteiros também como chaves de relacionamento. Como há
    múltiplos PCs/notebooks criando registros, AUTOINCREMENT local poderia
    gerar o mesmo ID em máquinas diferentes. O ID abaixo deriva de UUID e
    permanece dentro do limite de INTEGER do SQLite/PostgreSQL.
    """
    return 10**15 + (uuid.uuid4().int % 900_000_000_000_000)


def _coluna_existe(cursor, tabela, coluna):
    if postgres_configured():
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s AND column_name=%s",
            (tabela, coluna),
        )
        return cursor.fetchone() is not None
    cursor.execute(f"PRAGMA table_info({tabela})")
    return any(row[1] == coluna for row in cursor.fetchall())


def _tabela_existe(cursor, tabela):
    if postgres_configured():
        cursor.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=%s",
            (tabela,),
        )
        return cursor.fetchone() is not None
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tabela,)
    )
    return cursor.fetchone() is not None


def _migrar_schema(cursor):
    """Migra schema antigo para novo automaticamente."""
    if _tabela_existe(cursor, "manifestos"):
        if not _coluna_existe(cursor, "manifestos", "nome_arquivo"):
            try:
                cursor.execute("ALTER TABLE manifestos ADD COLUMN nome_arquivo TEXT")
                logger.info("[MIGRACAO] Coluna nome_arquivo adicionada em manifestos")
            except Exception as e:
                logger.warning(f"[MIGRACAO] Erro ao adicionar nome_arquivo: {e}")
        if not _coluna_existe(cursor, "manifestos", "data_importacao"):
            try:
                cursor.execute("ALTER TABLE manifestos ADD COLUMN data_importacao TEXT DEFAULT CURRENT_TIMESTAMP")
                logger.info("[MIGRACAO] Coluna data_importacao adicionada em manifestos")
            except Exception as e:
                logger.warning(f"[MIGRACAO] Erro ao adicionar data_importacao: {e}")
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manifestos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_arquivo TEXT,
                data_importacao TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

    if _tabela_existe(cursor, "notas_viagem") and not _tabela_existe(cursor, "viagem_notas"):
        try:
            cursor.execute("ALTER TABLE notas_viagem RENAME TO viagem_notas")
            logger.info("[MIGRACAO] Tabela notas_viagem renomeada para viagem_notas")
        except Exception as e:
            logger.warning(f"[MIGRACAO] Erro ao renomear notas_viagem: {e}")

    if not _tabela_existe(cursor, "viagem_notas"):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS viagem_notas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                viagem_id INTEGER,
                nota_id INTEGER,
                sync_id TEXT,
                sincronizado INTEGER DEFAULT 0,
                atualizado_em TEXT,
                deletado INTEGER DEFAULT 0
            )
        """)
        logger.info("[MIGRACAO] Tabela viagem_notas criada")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, cnpj TEXT UNIQUE,
            cidade TEXT, uf TEXT, razao_social TEXT, fantasia TEXT, cpf TEXT,
            telefone TEXT, codigo TEXT, criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for col in [("razao_social", "TEXT"), ("fantasia", "TEXT"), ("cpf", "TEXT"), ("telefone", "TEXT"), ("codigo", "TEXT"), ("prioridade", "TEXT DEFAULT 'normal'")]:
        if not _coluna_existe(cursor, "clientes", col[0]):
            try:
                cursor.execute(f"ALTER TABLE clientes ADD COLUMN {col[0]} {col[1]}")
            except Exception:
                pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, manifesto_id INTEGER,
            chave_nfe TEXT UNIQUE, numero_cte TEXT, remetente_id INTEGER,
            destinatario_id INTEGER, valor_mercadoria REAL, valor_frete REAL,
            peso REAL, origem TEXT, destino TEXT, status TEXT DEFAULT 'Disponivel',
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for col in [("cubagem_m3", "REAL DEFAULT 0"), ("tipo_carga", "TEXT")]:
        if not _coluna_existe(cursor, "notas", col[0]):
            try:
                cursor.execute(f"ALTER TABLE notas ADD COLUMN {col[0]} {col[1]}")
            except Exception:
                pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS caminhoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, placa TEXT, modelo TEXT,
            motorista TEXT, capacidade_kg REAL, media_km_l REAL
        )
    """)
    for col in [("status", "TEXT DEFAULT 'ATIVO'"), ("capacidade_m3", "REAL DEFAULT 0"), ("tipos_carga_permitidos", "TEXT")]:
        if not _coluna_existe(cursor, "caminhoes", col[0]):
            try:
                cursor.execute(f"ALTER TABLE caminhoes ADD COLUMN {col[0]} {col[1]}")
            except Exception:
                pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT, caminhao_id INTEGER,
            data_saida TEXT, data_retorno TEXT, motorista TEXT, status TEXT,
            peso_total REAL DEFAULT 0, frete_total REAL DEFAULT 0,
            custo_total REAL DEFAULT 0, lucro_total REAL DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS funcionarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, cargo TEXT,
            status TEXT DEFAULT 'Ativo', salario REAL DEFAULT 0, telefone TEXT,
            data_admissao TEXT, vale_refeicao REAL DEFAULT 0,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for col in [("salario", "REAL DEFAULT 0"), ("telefone", "TEXT"), ("data_admissao", "TEXT"), ("vale_refeicao", "REAL DEFAULT 0")]:
        if not _coluna_existe(cursor, "funcionarios", col[0]):
            try:
                cursor.execute(f"ALTER TABLE funcionarios ADD COLUMN {col[0]} {col[1]}")
            except Exception:
                pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS folha_funcionarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, funcionario_id INTEGER, mes TEXT,
            ano TEXT, salario REAL DEFAULT 0, vale_refeicao REAL DEFAULT 0,
            hora_extra REAL DEFAULT 0, outros REAL DEFAULT 0, total REAL DEFAULT 0,
            qtd_horas_extra REAL DEFAULT 0, valor_hora_extra REAL DEFAULT 0,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for col in [("qtd_horas_extra", "REAL DEFAULT 0"), ("valor_hora_extra", "REAL DEFAULT 0")]:
        if not _coluna_existe(cursor, "folha_funcionarios", col[0]):
            try:
                cursor.execute(f"ALTER TABLE folha_funcionarios ADD COLUMN {col[0]} {col[1]}")
            except Exception:
                pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operacoes_sp (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data_operacao TEXT,
            nome_caminhao TEXT, placa TEXT, motorista TEXT, valor_notas REAL DEFAULT 0,
            frete_carreta REAL DEFAULT 0, pedagio_carreta REAL DEFAULT 0,
            outros_custos REAL DEFAULT 0, custo_total REAL DEFAULT 0,
            liquido REAL DEFAULT 0, criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, descricao TEXT,
            pessoa TEXT, categoria TEXT, valor REAL DEFAULT 0, vencimento TEXT,
            pagamento TEXT, status TEXT DEFAULT 'Pendente', observacao TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS abastecimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data_abastecimento TEXT,
            veiculo TEXT, motorista TEXT, km_atual REAL DEFAULT 0, litros REAL DEFAULT 0,
            valor_litro REAL DEFAULT 0, valor_total REAL DEFAULT 0, media_km_l REAL DEFAULT 0,
            custo_km REAL DEFAULT 0, posto TEXT, observacao TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data_manutencao TEXT, veiculo TEXT,
            km_atual REAL DEFAULT 0, tipo TEXT, descricao TEXT, oficina TEXT,
            valor REAL DEFAULT 0, proxima_revisao_km REAL DEFAULT 0,
            status TEXT DEFAULT 'Pendente', observacao TEXT
        )
    """)
    # V66/V70: vínculo explícito dos custos operacionais à viagem.
    for tabela in ("contas", "abastecimentos", "manutencoes"):
        if not _coluna_existe(cursor, tabela, "viagem_id"):
            try:
                cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN viagem_id INTEGER")
            except sqlite3.Error:
                pass

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_contas_viagem_id ON contas(viagem_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_abastecimentos_viagem_id ON abastecimentos(viagem_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_manutencoes_viagem_id ON manutencoes(viagem_id)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tabela TEXT, registro_id TEXT,
            operacao TEXT DEFAULT 'UPSERT', status TEXT DEFAULT 'PENDENTE',
            tentativas INTEGER DEFAULT 0, erro TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP, sincronizado_em TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_estado (
            chave TEXT PRIMARY KEY, valor TEXT
        )
    """)
    # Migração incremental: a fila precisa preservar o timestamp original de
    # uma exclusão mesmo depois de o registro local ser removido.
    if not _coluna_existe(cursor, "sync_log", "atualizado_em"):
        try:
            cursor.execute("ALTER TABLE sync_log ADD COLUMN atualizado_em TEXT")
        except sqlite3.Error:
            pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome_completo TEXT NOT NULL,
            usuario TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL, senha_salt TEXT NOT NULL,
            nivel_acesso TEXT NOT NULL DEFAULT 'comum', ativo INTEGER NOT NULL DEFAULT 1,
            deve_alterar_senha INTEGER NOT NULL DEFAULT 0, tentativas_falhas INTEGER NOT NULL DEFAULT 0,
            bloqueado_ate TEXT, ultimo_login TEXT, criado_por INTEGER,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP, atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS permissoes_usuario (
            id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL,
            modulo TEXT NOT NULL, pode_visualizar INTEGER DEFAULT 1,
            pode_criar INTEGER DEFAULT 0, pode_editar INTEGER DEFAULT 0,
            pode_excluir INTEGER DEFAULT 0, pode_exportar INTEGER DEFAULT 0,
            pode_sincronizar INTEGER DEFAULT 0,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id), UNIQUE(usuario_id, modulo)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER, usuario_nome TEXT,
            acao TEXT NOT NULL, modulo TEXT, registro_afetado TEXT, detalhes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    indices = [
        ("idx_clientes_nome", "clientes", "nome"), ("idx_clientes_cnpj", "clientes", "cnpj"),
        ("idx_notas_status", "notas", "status"), ("idx_notas_manifesto", "notas", "manifesto_id"),
        ("idx_notas_chave_nfe", "notas", "chave_nfe"), ("idx_viagens_caminhao", "viagens", "caminhao_id"),
        ("idx_viagens_status", "viagens", "status"), ("idx_viagem_notas_viagem", "viagem_notas", "viagem_id"),
        ("idx_viagem_notas_nota", "viagem_notas", "nota_id"), ("idx_caminhoes_placa", "caminhoes", "placa"),
        ("idx_sync_log_tabela", "sync_log", "tabela"), ("idx_sync_log_status", "sync_log", "status"),
        ("idx_usuarios_usuario", "usuarios", "usuario"), ("idx_auditoria_criado_em", "auditoria", "criado_em"),
    ]
    for idx_name, tabela, coluna in indices:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {tabela}({coluna})")
        except Exception:
            pass

    _garantir_integridade_relacional(cursor)

    colunas_sync = [("sync_id", "TEXT"), ("sincronizado", "INTEGER DEFAULT 0"), ("atualizado_em", "TEXT"), ("deletado", "INTEGER DEFAULT 0")]
    for tabela in TABELAS_SYNC:
        if not _tabela_existe(cursor, tabela):
            continue
        for coluna_nome, coluna_tipo in colunas_sync:
            if not _coluna_existe(cursor, tabela, coluna_nome):
                try:
                    cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna_nome} {coluna_tipo}")
                    logger.info(f"[MIGRACAO] Coluna {coluna_nome} adicionada em {tabela}")
                except sqlite3.OperationalError:
                    pass
        try:
            cursor.execute(f"""
                UPDATE {tabela}
                SET sync_id = COALESCE(NULLIF(sync_id, ''), '{tabela}:' || CAST(id AS TEXT)),
                    atualizado_em = COALESCE(NULLIF(atualizado_em, ''), ?),
                    sincronizado = COALESCE(sincronizado, 0),
                    deletado = COALESCE(deletado, 0)
                WHERE sync_id IS NULL OR sync_id = '' OR atualizado_em IS NULL OR atualizado_em = ''
            """, (agora_sync(),))
        except Exception:
            pass
        try:
            cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{tabela}_sync_id ON {tabela}(sync_id)")
        except Exception:
            pass



def _garantir_integridade_relacional(cursor) -> None:
    """Adiciona proteções relacionais sem reconstruir tabelas existentes.

    SQLite não permite adicionar FOREIGN KEY via ALTER TABLE. Para não colocar
    em risco bancos já utilizados, usamos triggers equivalentes e índices nas
    colunas de relacionamento. Os triggers bloqueiam novos órfãos e exclusões
    que deixariam filhos pendurados. Dados antigos não são apagados
    automaticamente; são diagnosticados e registrados no log.
    """
    relacionamentos = [
        ("notas", "manifesto_id", "manifestos", "id", "nota_manifesto"),
        ("notas", "remetente_id", "clientes", "id", "nota_remetente"),
        ("notas", "destinatario_id", "clientes", "id", "nota_destinatario"),
        ("viagens", "caminhao_id", "caminhoes", "id", "viagem_caminhao"),
        ("folha_funcionarios", "funcionario_id", "funcionarios", "id", "folha_funcionario"),
        ("viagem_notas", "viagem_id", "viagens", "id", "viagem_notas_viagem"),
        ("viagem_notas", "nota_id", "notas", "id", "viagem_notas_nota"),
    ]

    for child, child_col, parent, parent_col, nome in relacionamentos:
        if not (_tabela_existe(cursor, child) and _tabela_existe(cursor, parent)):
            continue

        # Índice dedicado ao lado filho para joins, validações e exclusões.
        try:
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fk_{nome} ON {child}({child_col})"
            )
        except sqlite3.Error as erro:
            logger.warning("[DB] Não foi possível criar índice FK %s: %s", nome, erro)

        # NULL significa relacionamento opcional; quando preenchido, deve existir.
        trigger_insert = f"trg_fk_{nome}_insert"
        trigger_update = f"trg_fk_{nome}_update"
        trigger_delete = f"trg_fk_{nome}_delete"
        try:
            cursor.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {trigger_insert}
                BEFORE INSERT ON {child}
                WHEN NEW.{child_col} IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM {parent} WHERE {parent_col} = NEW.{child_col}
                 )
                BEGIN
                    SELECT RAISE(ABORT, 'Relacionamento inválido: {child}.{child_col}');
                END;
            """)
            cursor.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {trigger_update}
                BEFORE UPDATE OF {child_col} ON {child}
                WHEN NEW.{child_col} IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM {parent} WHERE {parent_col} = NEW.{child_col}
                 )
                BEGIN
                    SELECT RAISE(ABORT, 'Relacionamento inválido: {child}.{child_col}');
                END;
            """)
            cursor.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {trigger_delete}
                BEFORE DELETE ON {parent}
                WHEN EXISTS (
                    SELECT 1 FROM {child}
                    WHERE {child_col} = OLD.{parent_col}
                )
                BEGIN
                    SELECT RAISE(ABORT, 'Exclusão bloqueada: registro possui dependências');
                END;
            """)
        except sqlite3.Error as erro:
            logger.warning("[DB] Não foi possível criar proteção FK %s: %s", nome, erro)

    # Uma nota não pode estar em duas viagens ativas ao mesmo tempo.
    # O trigger complementa a validação transacional do serviço e protege
    # também inserções feitas diretamente no SQLite.
    if _tabela_existe(cursor, "viagem_notas"):
        try:
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_viagem_nota_unica_ativa
                BEFORE INSERT ON viagem_notas
                WHEN COALESCE(NEW.deletado,0)=0
                 AND EXISTS (
                    SELECT 1 FROM viagem_notas vn
                    WHERE vn.nota_id=NEW.nota_id AND COALESCE(vn.deletado,0)=0
                 )
                BEGIN
                    SELECT RAISE(ABORT, 'Nota já vinculada a uma viagem ativa');
                END;
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_viagem_nota_unica_ativa_update
                BEFORE UPDATE OF nota_id, deletado ON viagem_notas
                WHEN COALESCE(NEW.deletado,0)=0
                 AND EXISTS (
                    SELECT 1 FROM viagem_notas vn
                    WHERE vn.nota_id=NEW.nota_id AND COALESCE(vn.deletado,0)=0 AND vn.id<>NEW.id
                 )
                BEGIN
                    SELECT RAISE(ABORT, 'Nota já vinculada a uma viagem ativa');
                END;
            """)
        except sqlite3.Error as erro:
            logger.warning("[DB] Não foi possível criar proteção de nota duplicada: %s", erro)

    # Diagnóstico: não altera nem remove dados legados automaticamente.
    verificacoes = [
        ("notas.manifesto_id", "SELECT COUNT(*) FROM notas n LEFT JOIN manifestos m ON m.id=n.manifesto_id WHERE n.manifesto_id IS NOT NULL AND m.id IS NULL"),
        ("notas.remetente_id", "SELECT COUNT(*) FROM notas n LEFT JOIN clientes c ON c.id=n.remetente_id WHERE n.remetente_id IS NOT NULL AND c.id IS NULL"),
        ("notas.destinatario_id", "SELECT COUNT(*) FROM notas n LEFT JOIN clientes c ON c.id=n.destinatario_id WHERE n.destinatario_id IS NOT NULL AND c.id IS NULL"),
        ("viagens.caminhao_id", "SELECT COUNT(*) FROM viagens v LEFT JOIN caminhoes c ON c.id=v.caminhao_id WHERE v.caminhao_id IS NOT NULL AND c.id IS NULL"),
        ("folha_funcionarios.funcionario_id", "SELECT COUNT(*) FROM folha_funcionarios f LEFT JOIN funcionarios x ON x.id=f.funcionario_id WHERE f.funcionario_id IS NOT NULL AND x.id IS NULL"),
        ("viagem_notas.viagem_id", "SELECT COUNT(*) FROM viagem_notas vn LEFT JOIN viagens v ON v.id=vn.viagem_id WHERE vn.viagem_id IS NOT NULL AND v.id IS NULL"),
        ("viagem_notas.nota_id", "SELECT COUNT(*) FROM viagem_notas vn LEFT JOIN notas n ON n.id=vn.nota_id WHERE vn.nota_id IS NOT NULL AND n.id IS NULL"),
    ]
    for nome, sql in verificacoes:
        try:
            quantidade = int(cursor.execute(sql).fetchone()[0] or 0)
            if quantidade:
                logger.warning("[DB] Integridade: %s possui %d registro(s) órfão(s).", nome, quantidade)
        except sqlite3.Error as erro:
            logger.debug("[DB] Diagnóstico de integridade ignorado para %s: %s", nome, erro)


def marcar_registro_para_sync(cursor, tabela, registro_id, operacao="UPSERT"):
    if tabela == "sync_log" or registro_id is None or str(registro_id).strip().lower() in ("", "none"):
        return
    timestamp = agora_sync()
    try:
        if operacao.upper() == "UPSERT":
            cursor.execute(f"""
                UPDATE {tabela}
                SET atualizado_em = ?, sincronizado = 0, deletado = 0,
                    sync_id = COALESCE(NULLIF(sync_id, ''), ?)
                WHERE id = ?
            """, (timestamp, str(uuid.uuid4()), registro_id))
        else:
            cursor.execute(f"""
                UPDATE {tabela}
                SET atualizado_em = ?, sincronizado = 0, deletado = 1
                WHERE id = ?
            """, (timestamp, registro_id))
    except sqlite3.OperationalError as erro:
        logger.debug(f"Tabela {tabela} sem colunas de sync: {erro}")


def criar_tabela_sync_conflitos(conn):
    """Cria a trilha local de conflitos sem depender do schema da nuvem."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_conflitos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tabela TEXT NOT NULL,
            registro_id TEXT NOT NULL,
            versao_local TEXT,
            versao_nuvem TEXT,
            decisao TEXT NOT NULL,
            detalhes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)


def obter_referencia_sync(cursor, tabela, registro_id, operacao="UPSERT"):
    try:
        cursor.execute(f"SELECT sync_id FROM {tabela} WHERE id = ?", (registro_id,))
        row = cursor.fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    return str(registro_id)


def registrar_sync(cursor, tabela, registro_id, operacao="UPSERT"):
    if tabela == "sync_log" or registro_id is None or str(registro_id).strip().lower() in ("", "none"):
        return
    try:
        marcar_registro_para_sync(cursor, tabela, registro_id, operacao)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tabela TEXT, registro_id TEXT,
                operacao TEXT DEFAULT 'UPSERT', status TEXT DEFAULT 'PENDENTE',
                tentativas INTEGER DEFAULT 0, erro TEXT,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP, sincronizado_em TEXT,
                atualizado_em TEXT
            )
        """)
        # Bancos criados antes da V62.1 podem não ter a coluna.
        if not _coluna_existe(cursor, "sync_log", "atualizado_em"):
            try:
                cursor.execute("ALTER TABLE sync_log ADD COLUMN atualizado_em TEXT")
            except sqlite3.Error:
                pass
        referencia_sync = obter_referencia_sync(cursor, tabela, registro_id, operacao)
        try:
            row_ts = cursor.execute(f"SELECT atualizado_em FROM {tabela} WHERE id=?", (registro_id,)).fetchone()
            timestamp_sync = row_ts[0] if row_ts and row_ts[0] else agora_sync()
        except Exception:
            timestamp_sync = agora_sync()
        referencias = [referencia_sync, str(registro_id)]
        placeholders = ",".join(["?"] * len(referencias))
        cursor.execute(f"""
            UPDATE sync_log SET status='PENDENTE', operacao=?, tentativas=0, erro=NULL, registro_id=?, atualizado_em=?
            WHERE tabela=? AND registro_id IN ({placeholders}) AND status='OK'
        """, [operacao, referencia_sync, timestamp_sync, tabela, *referencias])
        if cursor.rowcount > 0:
            return
        cursor.execute(f"""
            SELECT id FROM sync_log WHERE tabela=? AND registro_id IN ({placeholders}) AND status='PENDENTE'
        """, [tabela, *referencias])
        if cursor.fetchone():
            return
        cursor.execute("""
            INSERT INTO sync_log (tabela, registro_id, operacao, status, tentativas, atualizado_em)
            VALUES (?, ?, ?, 'PENDENTE', 0, ?)
        """, (tabela, referencia_sync, operacao, timestamp_sync))
    except Exception as erro:
        logger.error(f"Erro ao registrar sync {tabela} {registro_id}: {erro}")


def criar_banco():
    """Cria/atualiza o banco de dados com migrações automáticas."""
    logger.info("Verificando estrutura do banco de dados em %s...", DB_NAME)
    migrar_banco_antigo()
    migrar_marcadores_primeiro_acesso()
    conn = conectar()
    cursor = conn.cursor()
    try:
        _migrar_schema(cursor)
        conn.commit()
    finally:
        conn.close()

    # A migração V83 precisa fazer parte da inicialização do banco, e não
    # somente da janela principal. Assim qualquer serviço/teste que inicialize
    # um banco legado recebe as colunas financeiras antes de executar consultas.
    try:
        from utils.database.v83_migration import aplicar_v83_indices
        aplicar_v83_indices()
    except Exception as erro:
        logger.error("[MIGRACAO V83] Falha ao aplicar schema complementar: %s", erro, exc_info=True)
        raise

    logger.info("Banco de dados verificado com sucesso!")


def tabela_existe_sqlite(cursor, tabela):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabela,))
    return cursor.fetchone() is not None


def criar_backup_manual() -> Path:
    """Cria um backup íntegro do banco atual na pasta persistente de backups."""
    origem = Path(DB_NAME)
    if not origem.exists():
        raise FileNotFoundError("Banco de dados não encontrado.")
    destino_dir = Path(settings.backup_dir)
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / f"cw_transportadora_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    origem_conn = sqlite3.connect(str(origem), timeout=30)
    destino_conn = sqlite3.connect(str(destino), timeout=30)
    try:
        origem_conn.backup(destino_conn)
        destino_conn.commit()
        # Um backup só é considerado válido depois de uma checagem SQLite.
        resultado = destino_conn.execute("PRAGMA integrity_check").fetchone()
        if not resultado or str(resultado[0]).lower() != "ok":
            raise RuntimeError(f"Backup inválido: {resultado[0] if resultado else 'sem resultado'}")
    finally:
        destino_conn.close(); origem_conn.close()
    logger.info("[BACKUP] Backup manual criado e validado: %s", destino)
    return destino


def listar_backups_manuais() -> list[Path]:
    pasta = Path(settings.backup_dir)
    if not pasta.exists(): return []
    return sorted(pasta.glob("cw_transportadora_backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)


def resetar_dados_operacionais() -> Path:
    """Reseta dados operacionais para testes, preservando usuários/permissões.

    Um backup automático é criado antes do reset, permitindo restauração integral.
    """
    backup = criar_backup_manual()
    conn = conectar(); cur = conn.cursor()
    # O banco possui triggers de proteção relacional. Em um reset destrutivo de
    # ambiente de testes eles precisam ser suspensos temporariamente; caso
    # contrário, qualquer registro órfão/legado pode bloquear a exclusão do
    # cliente e fazer o reset parecer concluído sem realmente limpar tudo.
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_fk_%'")
        triggers = [row[0] for row in cur.fetchall()]
        for trigger in triggers:
            cur.execute(f"DROP TRIGGER IF EXISTS {trigger}")

        # Filhos primeiro e clientes depois. Isso cobre também dados legados.
        tabelas = [
            # Rastreamentos também precisam ser zerados: se permanecerem,
            # sincronização/cache pode reintroduzir registros apagados.
            "sync_log", "auditoria",
            # Filhos antes dos pais para respeitar relacionamentos.
            "viagem_notas", "viagens", "operacoes_sp", "notas",
            "manifestos", "abastecimentos", "manutencoes", "contas",
            "caminhoes", "folha_funcionarios", "funcionarios", "clientes",
        ]
        for tabela in tabelas:
            if not _tabela_existe(cur, tabela):
                continue
            cur.execute(f"DELETE FROM {tabela}")

        # Reinicia IDs das tabelas operacionais quando possível.
        nomes_seq = [t for t in tabelas if _tabela_existe(cur, t)]
        if nomes_seq and _tabela_existe(cur, "sqlite_sequence"):
            cur.execute("DELETE FROM sqlite_sequence WHERE name IN (%s)" % ",".join("?" for _ in nomes_seq), nomes_seq)

        # O reset não pode terminar silenciosamente se algum dado operacional
        # permanecer.
        restantes = []
        for tabela in tabelas:
            if _tabela_existe(cur, tabela):
                cur.execute(f"SELECT COUNT(*) FROM {tabela}")
                total = int(cur.fetchone()[0])
                if total:
                    restantes.append(f"{tabela}={total}")
        if restantes:
            raise RuntimeError("Reset incompleto: " + ", ".join(restantes))
    except Exception:
        conn.rollback()
        conn.close()
        raise
    try:
        cur.execute("DELETE FROM sqlite_sequence WHERE name IN (%s)" % ",".join("?" for _ in tabelas), tabelas)
    except sqlite3.Error:
        pass
    conn.commit()
    conn.close()

    # Recria as proteções relacionais removidas temporariamente pelo reset.
    conn2 = conectar()
    try:
        _garantir_integridade_relacional(conn2.cursor())
        conn2.commit()
    finally:
        conn2.close()
    logger.warning("[RESET] Dados operacionais resetados. Clientes incluídos. Backup: %s", backup)
    return backup


def restaurar_backup(caminho) -> None:
    """Restaura o banco completo a partir de um backup SQLite."""
    backup = Path(caminho)
    if not backup.exists(): raise FileNotFoundError(str(backup))
    destino = Path(DB_NAME)
    tmp = destino.with_suffix('.restore.tmp.db')
    src = sqlite3.connect(str(backup), timeout=30)
    dst = sqlite3.connect(str(tmp), timeout=30)
    try:
        src.backup(dst); dst.commit()
    finally:
        dst.close(); src.close()
    os.replace(str(tmp), str(destino))
    logger.warning("[BACKUP] Banco restaurado de: %s", backup)
