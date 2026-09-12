"""Operações de contas financeiras fora da camada de interface."""
from __future__ import annotations
from datetime import datetime
from utils.database import conectar, registrar_sync
from utils.database._conexao import novo_id_global

class ContasService:
    def listar(self):
        conn=conectar()
        try:
            return conn.execute("SELECT id,vencimento,descricao,tipo,pessoa,categoria,valor,pagamento,status,observacao FROM contas ORDER BY id DESC").fetchall()
        finally: conn.close()
    def obter(self, conta_id):
        conn=conectar()
        try: return conn.execute("SELECT id,tipo,descricao,pessoa,categoria,valor,vencimento,pagamento,status,observacao FROM contas WHERE id=?",(conta_id,)).fetchone()
        finally: conn.close()
    def marcar_paga(self, conta_id):
        conn=conectar()
        try:
            conn.execute("UPDATE contas SET status='Pago', pagamento=? WHERE id=?",(datetime.now().strftime('%Y-%m-%d'),int(conta_id)))
            registrar_sync(conn.cursor(),'contas',int(conta_id)); conn.commit()
        finally: conn.close()
    def salvar(self, conta_id, dados):
        conn=conectar()
        try:
            if conta_id:
                conn.execute("UPDATE contas SET tipo=?,descricao=?,pessoa=?,categoria=?,valor=?,vencimento=?,pagamento=?,status=?,observacao=? WHERE id=?",tuple(dados)+(int(conta_id),)); novo_id=int(conta_id)
            else:
                cur=conn.cursor(); cur.execute("INSERT INTO contas(id,tipo,descricao,pessoa,categoria,valor,vencimento,pagamento,status,observacao) VALUES(?,?,?,?,?,?,?,?,?,?)",(novo_id_global(),)+tuple(dados)); novo_id=int(cur.lastrowid)
            registrar_sync(conn.cursor(),'contas',novo_id); conn.commit(); return novo_id
        finally: conn.close()
    def excluir(self, conta_id):
        conn=conectar()
        try:
            registrar_sync(conn.cursor(),'contas',int(conta_id),'DELETE'); conn.execute('DELETE FROM contas WHERE id=?',(int(conta_id),)); conn.commit()
        finally: conn.close()

contas_service=ContasService()
