"""
Persistencia de rascunho e historico rapido da tela de criacao de viagens.

Extraido de telas/criar_viagem.py: sao funcoes puras (sem UI, sem self),
responsaveis por gravar/ler o estado de um rascunho de viagem e o
historico rapido das ultimas viagens criadas, sempre em JSON local.
"""

import json
from pathlib import Path


def atualizar_marcacao_nota(notas_selecionadas, nota_id, selecionada):
    """Atualiza o conjunto de notas selecionadas de forma simples e previsível."""
    if selecionada:
        notas_selecionadas.add(nota_id)
    else:
        notas_selecionadas.discard(nota_id)
    return notas_selecionadas


def _caminho_json(nome_arquivo, caminho=None):
    """Retorna o caminho para um arquivo JSON de persistência."""
    if caminho is not None:
        return Path(caminho)

    base_dir = Path(__file__).resolve().parent.parent / "backup_dados"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / nome_arquivo


def salvar_rascunho_viagem(dados, caminho=None):
    """Salva o estado atual da viagem em um arquivo JSON."""
    caminho = _caminho_json("rascunho_viagem.json", caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
    return caminho


def carregar_rascunho_viagem(caminho=None):
    """Carrega o rascunho salvo, se existir."""
    caminho = _caminho_json("rascunho_viagem.json", caminho)
    if not caminho.exists():
        return None

    with caminho.open("r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def limpar_rascunho_viagem(caminho=None):
    """Remove o arquivo de rascunho, se existir."""
    caminho = _caminho_json("rascunho_viagem.json", caminho)
    if caminho.exists():
        caminho.unlink()
    return caminho


def adicionar_historico_viagem(dados, caminho=None, limite=8):
    """Adiciona uma viagem ao histórico rápido em formato JSON."""
    caminho = _caminho_json("historico_viagens.json", caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    historico = []
    if caminho.exists():
        with caminho.open("r", encoding="utf-8") as arquivo:
            try:
                historico = json.load(arquivo)
            except json.JSONDecodeError:
                historico = []

    historico.insert(0, dados)
    historico = historico[:limite]

    with caminho.open("w", encoding="utf-8") as arquivo:
        json.dump(historico, arquivo, ensure_ascii=False, indent=2)

    return historico


def listar_historico_viagem(caminho=None):
    """Lista as viagens recentes do histórico."""
    caminho = _caminho_json("historico_viagens.json", caminho)
    if not caminho.exists():
        return []

    with caminho.open("r", encoding="utf-8") as arquivo:
        try:
            return json.load(arquivo)
        except json.JSONDecodeError:
            return []
