from pathlib import Path
import re
src=Path(__file__).resolve().parents[1]/'CW-Transportadora-Premium-Redesign-v84.8.3/utils/database/postgres_compat.py'
text=src.read_text()
start=text.index('def _sql'); end=text.index('\nclass PGCursor')
ns={'re':re}; exec(text[start:end], ns); _sql=ns['_sql']

def test_boolean_and_placeholder_translation():
    q=_sql('SELECT id FROM viagens WHERE COALESCE(v.deletado,0)=0 AND v.deletado=0 AND id=?')
    assert 'COALESCE(v.deletado, FALSE) IS FALSE' in q
    assert 'v.deletado = FALSE' in q
    assert 'id=%s' in q

def test_strftime_translation():
    q=_sql("SELECT * FROM contas WHERE strftime('%m',vencimento)=? AND strftime('%Y',vencimento)=?")
    assert "to_char(CAST(vencimento AS timestamp), 'MM')" in q
    assert "to_char(CAST(vencimento AS timestamp), 'YYYY')" in q

def test_permission_upsert():
    q=_sql('INSERT OR REPLACE INTO permissoes_usuario (usuario_id,modulo,pode_visualizar) VALUES (?,?,?)')
    assert 'ON CONFLICT (usuario_id, modulo) DO UPDATE' in q
