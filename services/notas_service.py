"""
Servico de notas/manifestos.
Delega importacao TXT para utils.importador_txt (que ja funciona).
"""
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, Optional

from utils.importador_txt import importar_manifesto_txt, apagar_manifesto_importado
from utils.database.notas import (
    listar_manifestos as db_listar_manifestos,
    listar_notas_por_manifesto as db_listar_notas_por_manifesto,
    listar_notas,
    calcular_resumo_notas,
)
from utils.database.viagens import apagar_viagem


class NotasService:
    def listar_manifestos(self, tipo_periodo="Geral", mes=None, ano=None):
        return db_listar_manifestos(tipo_periodo, mes, ano)
    
    def listar_notas_por_manifesto(self, manifesto_id):
        return db_listar_notas_por_manifesto(manifesto_id)
    
    def importar_manifesto(self, caminho: str) -> Dict[str, Any]:
        """
        Delega para o importador TXT que ja funciona.
        Retorna dict com: arquivo, encontradas, salvas, duplicadas
        """
        resultado = importar_manifesto_txt(caminho)
        return {
            "arquivo": resultado["arquivo"],
            "encontradas": resultado["encontradas"],
            "salvas": resultado["salvas"],
            "duplicadas": resultado["duplicadas"],
        }
    
    def exportar_manifesto_xml(self, manifesto_id: int, caminho_destino: str) -> bool:
        """
        Exporta um manifesto e suas notas para XML no formato padrao de transporte.
        """
        try:
            notas = db_listar_notas_por_manifesto(manifesto_id)
            if not notas:
                return False
            
            from utils.database._conexao import conectar
            conn = conectar()
            cursor = conn.cursor()
            cursor.execute("SELECT nome_arquivo, data_importacao FROM manifestos WHERE id = ?", (manifesto_id,))
            manifesto_row = cursor.fetchone()
            conn.close()
            
            manifesto_nome = manifesto_row[0] if manifesto_row else f"MANIFESTO_{manifesto_id}"
            data_manifesto = manifesto_row[1] if manifesto_row else datetime.now().isoformat()
            
            root = ET.Element("manifesto")
            ET.SubElement(root, "id").text = str(manifesto_id)
            ET.SubElement(root, "nome_arquivo").text = manifesto_nome
            ET.SubElement(root, "data_geracao").text = datetime.now().isoformat()
            ET.SubElement(root, "data_importacao").text = str(data_manifesto)
            
            notas_elem = ET.SubElement(root, "notas")
            
            for nota in notas:
                # nota: (id, chave_nfe, numero_cte, remetente, destinatario, origem, destino, valor_mercadoria, valor_frete, peso, status)
                n_elem = ET.SubElement(notas_elem, "nota")
                ET.SubElement(n_elem, "id").text = str(nota[0])
                ET.SubElement(n_elem, "chave_nfe").text = str(nota[1] or "")
                ET.SubElement(n_elem, "numero_cte").text = str(nota[2] or "")
                ET.SubElement(n_elem, "remetente").text = str(nota[3] or "")
                ET.SubElement(n_elem, "destinatario").text = str(nota[4] or "")
                ET.SubElement(n_elem, "origem").text = str(nota[5] or "")
                ET.SubElement(n_elem, "destino").text = str(nota[6] or "")
                ET.SubElement(n_elem, "valor_mercadoria").text = str(nota[7] or 0)
                ET.SubElement(n_elem, "valor_frete").text = str(nota[8] or 0)
                ET.SubElement(n_elem, "peso").text = str(nota[9] or 0)
                ET.SubElement(n_elem, "status").text = str(nota[10] or "")
            
            tree = ET.ElementTree(root)
            ET.indent(tree, space="  ", level=0)
            tree.write(caminho_destino, encoding='utf-8', xml_declaration=True)
            return True
            
        except Exception as e:
            print(f"[notas_service] Erro ao exportar XML: {e}")
            return False
    
    def apagar_manifesto(self, manifesto_id):
        """Delega para o importador que ja gerencia sync e relacionamentos."""
        resultado = apagar_manifesto_importado(manifesto_id=manifesto_id)
        return True
    
    def apagar_viagem(self, viagem_id):
        return apagar_viagem(viagem_id)
    
    def cadastrar_caminhao(self, placa, modelo, motorista, capacidade, media):
        from utils.database import cadastrar_caminhao
        cadastrar_caminhao(placa, modelo, motorista, capacidade, media)
    
    def calcular_resumo_notas(self, notas_ids):
        return calcular_resumo_notas(notas_ids)


notas_service = NotasService()
