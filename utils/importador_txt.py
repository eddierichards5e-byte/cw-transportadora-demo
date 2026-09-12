import os
import re
import sys
import sqlite3
from utils.database._conexao import novo_id_global
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import criar_banco, conectar, registrar_sync

IMPORTADOR_VERSAO = "IMPORTADOR_TXT_VERSAO_2026_06_27_FINAL_COMPLETO"


def limpar_texto(texto):
    return " ".join(str(texto or "").strip().split())


def valor_txt(numero):
    try:
        numero = str(numero or "").strip()
        numero = "".join(filter(str.isdigit, numero))
        if not numero:
            return 0
        return int(numero) / 100
    except Exception:
        return 0


def ler_manifesto_txt(caminho_arquivo):
    """
    Cada linha 319 representa uma nota/CT-e do manifesto.
    Se o TXT tiver 22 linhas 319, retorna 22 notas.
    Se o TXT tiver 43 linhas 319, retorna 43 notas.
    """
    notas = []
    remetente_atual = {}
    destinatario_atual = {}

    with open(caminho_arquivo, "r", encoding="utf-8", errors="ignore") as arquivo:
        linhas = arquivo.readlines()

    for linha in linhas:
        linha = linha.rstrip("\n")
        codigo = linha[:3]

        if codigo == "311":
            remetente_atual = {
                "cnpj_remetente": limpar_texto(linha[3:17]),
                "cidade_origem": limpar_texto(linha[73:105]),
                "uf_origem": limpar_texto(linha[114:116]),
                "cliente": limpar_texto(linha[124:170]),
            }

        elif codigo == "312":
            destinatario_atual = {
                "destinatario": limpar_texto(linha[3:43]),
                "cnpj_destinatario": limpar_texto(linha[43:57]),
                "cidade_destino": limpar_texto(linha[112:145]),
                "uf_destino": limpar_texto(linha[166:168]),
            }

        elif codigo == "319":
            chaves_319 = re.findall(r"\d{44}", linha)
            chave_original = chaves_319[-1] if chaves_319 else str(uuid.uuid4())

            nota = {
                "numero_cte": chave_original,
                "chave_nfe": chave_original,
                "remetente_nome": remetente_atual.get("cliente", ""),
                "remetente_cnpj": remetente_atual.get("cnpj_remetente", ""),
                "destinatario_nome": destinatario_atual.get("destinatario", ""),
                "destinatario_cnpj": destinatario_atual.get("cnpj_destinatario", ""),
                "valor_mercadoria": valor_txt(linha[33:48]),
                "valor_frete": valor_txt(linha[153:168]),
                "peso": valor_txt(linha[3:18]),
                "origem": remetente_atual.get("cidade_origem", ""),
                "uf_origem": remetente_atual.get("uf_origem", ""),
                "destino": destinatario_atual.get("cidade_destino", ""),
                "uf_destino": destinatario_atual.get("uf_destino", ""),
                "status": "Disponível",
            }

            notas.append(nota)

    return notas


def buscar_cliente_por_cnpj_cursor(cursor, cnpj):
    cursor.execute(
        "SELECT id FROM clientes WHERE cnpj = ?",
        (cnpj,),
    )
    resultado = cursor.fetchone()
    if resultado:
        return resultado[0]
    return None


def criar_cliente_cursor(cursor, nome, cnpj, cidade="", uf=""):
    try:
        cursor.execute(
            """
            INSERT INTO clientes
            (id, nome, cnpj, cidade, uf)
            VALUES (?, ?, ?, ?, ?)
            """,
            (novo_id_global(), nome, cnpj, cidade, uf),
        )

        cliente_id = cursor.lastrowid
        registrar_sync(cursor, "clientes", cliente_id)
        return cliente_id

    except sqlite3.IntegrityError:
        cursor.execute(
            "SELECT id FROM clientes WHERE cnpj = ?",
            (cnpj,),
        )

        resultado = cursor.fetchone()

        if resultado:
            return resultado[0]

        raise


def obter_ou_criar_cliente_cursor(cursor, nome, cnpj, cidade="", uf=""):
    if not cnpj:
        cnpj = f"SEM_CNPJ_{uuid.uuid4().hex}"

    cliente_id = buscar_cliente_por_cnpj_cursor(cursor, cnpj)
    if cliente_id:
        return cliente_id

    return criar_cliente_cursor(cursor, nome, cnpj, cidade, uf)


def chave_existe_cursor(cursor, chave_nfe):
    cursor.execute(
        "SELECT id FROM notas WHERE chave_nfe = ?",
        (chave_nfe,),
    )
    return cursor.fetchone() is not None


def criar_chave_banco_unica(cursor, manifesto_id, indice):
    """
    Chave técnica interna para o banco.
    Não depende da chave original do TXT, então a importação nunca perde nota por UNIQUE.
    """
    while True:
        chave = f"M{manifesto_id}_N{indice}_{uuid.uuid4().hex}"
        if not chave_existe_cursor(cursor, chave):
            return chave


def manifesto_ja_importado(cursor, nome_arquivo):
    cursor.execute(
        "SELECT id FROM manifestos WHERE nome_arquivo = ?",
        (nome_arquivo,),
    )
    return cursor.fetchone() is not None


def importar_manifesto_txt(caminho_arquivo):
    print(f"🔎 Usando {IMPORTADOR_VERSAO}")

    criar_banco()

    nome_arquivo = os.path.basename(caminho_arquivo)
    notas = ler_manifesto_txt(caminho_arquivo)

    salvas = 0
    duplicadas = 0
    manifesto_id = None

    conn = conectar()
    cursor = conn.cursor()

    try:
        if manifesto_ja_importado(cursor, nome_arquivo):
            raise Exception(
                f"Este manifesto já foi importado:\n\n{nome_arquivo}"
            )

        cursor.execute(
            """
            INSERT INTO manifestos (id, nome_arquivo)
            VALUES (?, ?)
            """,
            (novo_id_global(), nome_arquivo),
        )

        manifesto_id = cursor.lastrowid
        registrar_sync(cursor, "manifestos", manifesto_id)

        originais_vistas = set()

        for indice, nota in enumerate(notas, start=1):
            chave_original = str(
                nota.get("chave_nfe")
                or nota.get("numero_cte")
                or uuid.uuid4()
            )

            if chave_original in originais_vistas:
                duplicadas += 1
            else:
                originais_vistas.add(chave_original)

            # A chave_nfe gravada no banco é sempre técnica e única.
            # Isso impede que o SQLite descarte nota por UNIQUE.
            chave_banco = criar_chave_banco_unica(cursor, manifesto_id, indice)
            numero_cte = nota.get("numero_cte") or chave_original or chave_banco

            remetente_id = obter_ou_criar_cliente_cursor(
                cursor,
                nota.get("remetente_nome", ""),
                nota.get("remetente_cnpj", ""),
                nota.get("origem", ""),
                nota.get("uf_origem", ""),
            )

            destinatario_id = obter_ou_criar_cliente_cursor(
                cursor,
                nota.get("destinatario_nome", ""),
                nota.get("destinatario_cnpj", ""),
                nota.get("destino", ""),
                nota.get("uf_destino", ""),
            )

            try:
                cursor.execute(
                    """
                    INSERT INTO notas (
                        id,
                        manifesto_id,
                        chave_nfe,
                        numero_cte,
                        remetente_id,
                        destinatario_id,
                        valor_mercadoria,
                        valor_frete,
                        peso,
                        origem,
                        destino,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        novo_id_global(),
                        manifesto_id,
                        chave_banco,
                        numero_cte,
                        remetente_id,
                        destinatario_id,
                        nota.get("valor_mercadoria", 0),
                        nota.get("valor_frete", 0),
                        nota.get("peso", 0),
                        nota.get("origem", ""),
                        nota.get("destino", ""),
                        nota.get("status", "Disponível"),
                    ),
                )

            except sqlite3.IntegrityError:
                # Proteção extra: se por algum motivo repetiu, gera outra chave e tenta novamente.
                chave_banco = criar_chave_banco_unica(cursor, manifesto_id, indice)
                cursor.execute(
                    """
                    INSERT INTO notas (
                        id,
                        manifesto_id,
                        chave_nfe,
                        numero_cte,
                        remetente_id,
                        destinatario_id,
                        valor_mercadoria,
                        valor_frete,
                        peso,
                        origem,
                        destino,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        novo_id_global(),
                        manifesto_id,
                        chave_banco,
                        numero_cte,
                        remetente_id,
                        destinatario_id,
                        nota.get("valor_mercadoria", 0),
                        nota.get("valor_frete", 0),
                        nota.get("peso", 0),
                        nota.get("origem", ""),
                        nota.get("destino", ""),
                        nota.get("status", "Disponível"),
                    ),
                )

            nota_id = cursor.lastrowid
            registrar_sync(cursor, "notas", nota_id)
            salvas += 1

        conn.commit()

    except sqlite3.OperationalError as erro:
        conn.rollback()
        raise Exception(
            "O banco está ocupado no momento. Feche outras janelas do sistema, aguarde alguns segundos e tente novamente.\n\n"
            f"Detalhe: {erro}"
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "manifesto_id": manifesto_id,
        "arquivo": nome_arquivo,
        "encontradas": len(notas),
        "salvas": salvas,
        "duplicadas": duplicadas,
        "versao_importador": IMPORTADOR_VERSAO,
    }

def apagar_manifesto_importado(manifesto_id=None, nome_arquivo=None):
    if manifesto_id is None and not nome_arquivo:
        raise Exception("Informe o manifesto que deseja apagar.")

    criar_banco()

    conn = conectar()
    cursor = conn.cursor()

    try:
        if manifesto_id is not None:
            cursor.execute(
                "SELECT id, nome_arquivo FROM manifestos WHERE id = ?",
                (manifesto_id,),
            )
        else:
            cursor.execute(
                "SELECT id, nome_arquivo FROM manifestos WHERE nome_arquivo = ?",
                (novo_id_global(), nome_arquivo),
            )

        manifesto = cursor.fetchone()

        if not manifesto:
            raise Exception("Manifesto não encontrado.")

        manifesto_id_encontrado = manifesto[0]
        nome_arquivo_encontrado = manifesto[1]

        cursor.execute(
            "SELECT COUNT(*) FROM notas WHERE manifesto_id = ?",
            (manifesto_id_encontrado,),
        )
        notas_apagadas = cursor.fetchone()[0]

        cursor.execute(
            "DELETE FROM notas WHERE manifesto_id = ?",
            (manifesto_id_encontrado,),
        )

        cursor.execute(
            "DELETE FROM manifestos WHERE id = ?",
            (manifesto_id_encontrado,),
        )

        conn.commit()

    except sqlite3.OperationalError as erro:
        conn.rollback()
        raise Exception(
            "O banco está ocupado no momento. Feche outras janelas do sistema, aguarde alguns segundos e tente novamente.\n\n"
            f"Detalhe: {erro}"
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "manifesto_id": manifesto_id_encontrado,
        "arquivo": nome_arquivo_encontrado,
        "notas_apagadas": notas_apagadas,
    }


if __name__ == "__main__":
    caminho = os.path.join("testes", "manifesto_teste.txt")
    resultado = importar_manifesto_txt(caminho)

    print(f"Notas encontradas: {resultado['encontradas']}")
    print(f"Notas salvas: {resultado['salvas']}")
    print(f"Notas duplicadas: {resultado['duplicadas']}")
    print(f"Versão: {resultado.get('versao_importador')}")