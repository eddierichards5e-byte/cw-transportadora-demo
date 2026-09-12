from __future__ import annotations
import os
from datetime import datetime, timedelta
import logging
import secrets
import time
from pathlib import Path
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from services.auth_service import auth_service, CredenciaisInvalidasError, ContaBloqueadaError, ContaInativaError
from services.dashboard_service import dashboard_service
from services.notas_service import notas_service
from utils.database._conexao import conectar
from utils.database.viagens import criar_viagem as db_criar_viagem, alterar_status_viagem, apagar_viagem as db_apagar_viagem
from utils.database.caminhoes import listar_caminhoes, cadastrar_caminhao, excluir_caminhao, alterar_status_caminhao
from services.frota_service import frota_service
from services.financeiro_service import financeiro_service
from services.funcionarios_service import FuncionariosService

BASE = Path(__file__).resolve().parent
APP_VERSION = "2.8.0-web"
WEB_SECRET = os.getenv("CW_WEB_SECRET")
if not WEB_SECRET or len(WEB_SECRET) < 32:
    raise RuntimeError("CW_WEB_SECRET deve ser definido com pelo menos 32 caracteres em produção.")

# Persistência web: PostgreSQL é obrigatório quando a aplicação roda em produção.
# SQLite continua disponível somente para o aplicativo desktop/ambientes locais.
DATABASE_URL = os.getenv("CW_DATABASE_URL") or os.getenv("DATABASE_URL")
if os.getenv("CW_ENV", "development").lower() == "production" and not DATABASE_URL:
    raise RuntimeError("Banco de produção não configurado: defina CW_DATABASE_URL ou DATABASE_URL para PostgreSQL.")

# Hardening web: limites conservadores para a primeira implantação pública.
MAX_UPLOAD_BYTES = int(os.getenv("CW_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
LOGIN_WINDOW_SECONDS = int(os.getenv("CW_LOGIN_WINDOW_SECONDS", "900"))
LOGIN_MAX_ATTEMPTS = int(os.getenv("CW_LOGIN_MAX_ATTEMPTS", "10"))
LOGIN_RATE = {}
security_log = logging.getLogger("cw.web.security")

app = FastAPI(title="CW Transportadora Web", version=APP_VERSION, docs_url=None if os.getenv("CW_DISABLE_DOCS", "1") == "1" else "/docs", redoc_url=None)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        if os.getenv("CW_HTTPS_ONLY", "0") == "1":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def _client_key(request: Request) -> str:
    # Não confiamos em X-Forwarded-For diretamente: o proxy deve terminar TLS e
    # controlar os headers antes de repassar a requisição.
    return request.client.host if request.client else "unknown"

def _csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token

def _csrf_input(request: Request) -> str:
    from markupsafe import Markup
    return Markup(f'<input type="hidden" name="csrf_token" value="{_csrf_token(request)}">')

async def _validate_csrf(request: Request) -> bool:
    # Todas as mutações da aplicação web são feitas por formulários.
    form = await request.form()
    sent = str(form.get("csrf_token") or "")
    expected = str(request.session.get("csrf_token") or "")
    return bool(sent and expected and secrets.compare_digest(sent, expected))

class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method == "GET":
            _csrf_token(request)
            return await call_next(request)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            content_type = request.headers.get("content-type", "")
            # APIs externas futuras devem usar autenticação própria; atualmente
            # todos os endpoints mutáveis web são forms, inclusive multipart.
            if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
                if not await _validate_csrf(request):
                    return HTMLResponse("<h1>Requisição inválida</h1>", status_code=403)
        return await call_next(request)

# A ordem de adição é invertida pelo Starlette: Session deve ser o middleware externo
# para que CSRF possa acessar request.session.
app.add_middleware(CSRFProtectionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SessionMiddleware, secret_key=WEB_SECRET, max_age=60*60*8, same_site="lax", https_only=os.getenv("CW_HTTPS_ONLY", "0") == "1")

templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals["csrf_input"] = _csrf_input
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

def _ensure_postgres_schema():
    if not DATABASE_URL:
        return
    schema_path = BASE / "migrations" / "001_postgres_schema.sql"
    import psycopg
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_path.read_text(encoding="utf-8"))
        conn.commit()

if DATABASE_URL:
    _ensure_postgres_schema()
def current_user(request: Request):
    if hasattr(request.state, "current_user"):
        return request.state.current_user
    session_user = request.session.get("user")
    if not session_user or not session_user.get("id"):
        request.state.current_user = None
        return None
    conn = None
    try:
        conn = conectar()
        row = conn.execute("SELECT id,nome_completo,usuario,nivel_acesso,ativo,deve_alterar_senha FROM usuarios WHERE id=?", (session_user["id"],)).fetchone()
        if not row or not row[4]:
            request.session.clear()
            request.state.current_user = None
            return None
        permissoes = auth_service._carregar_permissoes(conn, row[0], row[3])
        user = {"id": row[0], "nome_completo": row[1], "usuario": row[2], "nivel_acesso": row[3],
                "ativo": bool(row[4]), "deve_alterar_senha": bool(row[5]),
                "eh_mestre": row[3] == "mestre", "permissoes": permissoes}
        request.state.current_user = user
        return user
    except Exception:
        request.state.current_user = None
        return None
    finally:
        if conn is not None:
            conn.close()


def protected(request: Request):
    return current_user(request)


def can(user, module: str, action: str = "visualizar") -> bool:
    if user.get("eh_mestre"):
        return True
    return bool(user.get("permissoes", {}).get(module, {}).get(action, False))


def redirect_if_denied(request, module, action="visualizar"):
    user = protected(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can(user, module, action):
        return HTMLResponse("<h1>Acesso negado</h1>", status_code=403)
    return None


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, usuario: str = Form(...), senha: str = Form(...)):
    now = time.monotonic(); key = _client_key(request)
    attempts = [t for t in LOGIN_RATE.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Muitas tentativas. Aguarde alguns minutos."}, status_code=429)
    try:
        user = auth_service.login(usuario, senha)
        LOGIN_RATE.pop(key, None)
        # Regenera a sessão e o token CSRF após autenticação bem-sucedida.
        request.session.clear()
        request.session["csrf_token"] = secrets.token_urlsafe(32)
        request.session["user"] = {
            "id": user["id"], "usuario": user["usuario"], "nome_completo": user["nome_completo"],
            "nivel_acesso": user["nivel_acesso"], "eh_mestre": user["eh_mestre"], "permissoes": user["permissoes"],
        }
        return RedirectResponse("/", status_code=303)
    except (CredenciaisInvalidasError, ContaBloqueadaError, ContaInativaError) as exc:
        attempts.append(now); LOGIN_RATE[key] = attempts
        security_log.warning("Falha de login para usuario=%s origem=%s tipo=%s", (usuario or "")[:80], key, type(exc).__name__)
        return templates.TemplateResponse("login.html", {"request": request, "error": str(exc)}, status_code=401)


@app.post("/logout")
def logout(request: Request):
    auth_service.logout()
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = protected(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user,
        "kpis": dashboard_service.calcular_kpis(),
        "status": dashboard_service.resumo_fretes_status(),
        "ranking_clientes": dashboard_service.ranking_clientes_rentabilidade(5),
        "ranking_veiculos": dashboard_service.ranking_veiculos(5),
        "alertas": dashboard_service.viagens_alertas_rentabilidade(5),
    })


@app.get("/viagens", response_class=HTMLResponse)
def viagens_page(request: Request, erro: str | None = None):
    denied = redirect_if_denied(request, "historico", "visualizar")
    if denied: return denied
    user = current_user(request)
    conn = conectar()
    try:
        viagens = conn.execute("""
            SELECT v.id,v.data_saida,v.data_retorno,v.motorista,v.status,v.peso_total,v.frete_total,
                   v.custo_total,v.lucro_total, c.placa,c.modelo,
                   COUNT(vn.nota_id) total_notas
            FROM viagens v
            LEFT JOIN caminhoes c ON c.id=v.caminhao_id
            LEFT JOIN viagem_notas vn ON vn.viagem_id=v.id AND COALESCE(vn.deletado,0)=0
            WHERE COALESCE(v.deletado,0)=0
            GROUP BY v.id ORDER BY v.id DESC LIMIT 200
        """).fetchall()
        caminhoes = conn.execute("SELECT id,placa,modelo,motorista,capacidade_kg,status FROM caminhoes WHERE COALESCE(status,'ATIVO') NOT IN ('INATIVO','BAIXADO') ORDER BY placa").fetchall()
        notas = conn.execute("""
            SELECT n.id,n.numero_cte,n.origem,n.destino,n.valor_frete,n.peso,n.status,
                   r.nome remetente,d.nome destinatario
            FROM notas n LEFT JOIN clientes r ON r.id=n.remetente_id LEFT JOIN clientes d ON d.id=n.destinatario_id
            WHERE lower(COALESCE(n.status,'')) IN ('disponível','disponivel')
              AND NOT EXISTS (SELECT 1 FROM viagem_notas vn WHERE vn.nota_id=n.id AND COALESCE(vn.deletado,0)=0)
            ORDER BY n.id DESC LIMIT 300
        """).fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("viagens.html", {"request":request,"user":user,"viagens":viagens,"caminhoes":caminhoes,"notas":notas,"erro":erro})


@app.post("/viagens/criar")
def criar_viagem_web(request: Request, caminhao_id: int = Form(...), motorista: str = Form(...), data_saida: str = Form(...), notas_ids: str = Form(...)):
    denied = redirect_if_denied(request, "operacoes", "criar")
    if denied: return denied
    try:
        ids = [int(x.strip()) for x in notas_ids.split(",") if x.strip()]
        data = data_saida.replace("T", " ")
        db_criar_viagem(caminhao_id, ids, data, motorista)
        return RedirectResponse("/viagens", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/viagens?erro={"Falha ao processar a operação."}", status_code=303)


@app.post("/viagens/{viagem_id}/status")
def status_viagem_web(request: Request, viagem_id: int, novo_status: str = Form(...)):
    denied = redirect_if_denied(request, "historico", "editar")
    if denied: return denied
    try:
        alterar_status_viagem(viagem_id, novo_status)
    except Exception as exc:
        return RedirectResponse(f"/viagens?erro={"Falha ao processar a operação."}", status_code=303)
    return RedirectResponse("/viagens", status_code=303)


@app.post("/viagens/{viagem_id}/excluir")
def excluir_viagem_web(request: Request, viagem_id: int):
    denied = redirect_if_denied(request, "historico", "excluir")
    if denied: return denied
    try:
        db_apagar_viagem(viagem_id)
    except Exception as exc:
        return RedirectResponse(f"/viagens?erro={"Falha ao processar a operação."}", status_code=303)
    return RedirectResponse("/viagens", status_code=303)


@app.get("/api/dashboard")
def api_dashboard(request: Request):
    if not protected(request): return JSONResponse({"detail":"Não autenticado"}, status_code=401)
    return {"kpis":dashboard_service.calcular_kpis(),"status":dashboard_service.resumo_fretes_status(),"clientes":dashboard_service.ranking_clientes_rentabilidade(10),"veiculos":dashboard_service.ranking_veiculos(10),"alertas":dashboard_service.viagens_alertas_rentabilidade(10)}


@app.get("/api/viagens")
def api_viagens(request: Request):
    denied = redirect_if_denied(request, "historico", "visualizar")
    if denied: return denied
    conn = conectar()
    try:
        rows = conn.execute("""SELECT v.id,v.data_saida,v.data_retorno,v.motorista,v.status,v.peso_total,v.frete_total,v.custo_total,v.lucro_total, c.placa,c.modelo FROM viagens v LEFT JOIN caminhoes c ON c.id=v.caminhao_id WHERE COALESCE(v.deletado,0)=0 ORDER BY v.id DESC LIMIT 200""").fetchall()
        return [dict(r) if hasattr(r,'keys') else dict(zip(['id','data_saida','data_retorno','motorista','status','peso_total','frete_total','custo_total','lucro_total','placa','modelo'],r)) for r in rows]
    finally: conn.close()



@app.get("/notas", response_class=HTMLResponse)
def notas_page(request: Request, erro: str | None = None, ok: str | None = None, manifesto_id: int | None = None):
    denied = redirect_if_denied(request, "notas", "visualizar")
    if denied: return denied
    user = current_user(request)
    manifestos = notas_service.listar_manifestos()
    notas = notas_service.listar_notas()
    detalhes = notas_service.listar_notas_por_manifesto(manifesto_id) if manifesto_id else []
    return templates.TemplateResponse("notas.html", {"request":request,"user":user,"manifestos":manifestos,"notas":notas,"detalhes":detalhes,"manifesto_id":manifesto_id,"erro":erro,"ok":ok})


@app.post("/notas/importar")
async def importar_notas_web(request: Request, arquivo: UploadFile = File(...)):
    denied = redirect_if_denied(request, "notas", "criar")
    if denied: return denied
    if not arquivo.filename:
        return RedirectResponse("/notas?erro=Arquivo nao informado", status_code=303)
    import tempfile
    if Path(arquivo.filename).suffix.lower() != ".txt":
        return RedirectResponse("/notas?erro=Somente+arquivos+TXT+sao+aceitos", status_code=303)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        total = 0
        while True:
            chunk = await arquivo.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                tmp.close()
                try: os.unlink(tmp.name)
                except OSError: pass
                return RedirectResponse("/notas?erro=Arquivo+excede+o+limite+permitido", status_code=303)
            tmp.write(chunk)
        caminho = tmp.name
    try:
        resultado = notas_service.importar_manifesto(caminho)
        msg = f"Importação concluída: {resultado['salvas']} notas salvas, {resultado['duplicadas']} duplicadas."
        return RedirectResponse("/notas?ok=" + msg.replace(" ", "+"), status_code=303)
    except Exception as exc:
        return RedirectResponse("/notas?erro=" + "Falha ao processar a operação.", status_code=303)
    finally:
        try: os.unlink(caminho)
        except OSError: pass


@app.post("/notas/manifestos/{manifesto_id}/excluir")
def excluir_manifesto_web(request: Request, manifesto_id: int):
    denied = redirect_if_denied(request, "notas", "excluir")
    if denied: return denied
    try:
        notas_service.apagar_manifesto(manifesto_id)
        return RedirectResponse("/notas?ok=Manifesto+excluído", status_code=303)
    except Exception as exc:
        return RedirectResponse("/notas?erro=" + "Falha ao processar a operação.", status_code=303)


@app.get("/notas/manifestos/{manifesto_id}", response_class=HTMLResponse)
def manifesto_detalhes(request: Request, manifesto_id: int):
    denied = redirect_if_denied(request, "notas", "visualizar")
    if denied: return denied
    return notas_page(request, manifesto_id=manifesto_id)


@app.get("/api/notas")
def api_notas(request: Request):
    denied = redirect_if_denied(request, "notas", "visualizar")
    if denied: return denied
    rows = notas_service.listar_notas()
    return [dict(r) if hasattr(r, "keys") else list(r) for r in rows]


@app.get("/api/manifestos")
def api_manifestos(request: Request):
    denied = redirect_if_denied(request, "notas", "visualizar")
    if denied: return denied
    rows = notas_service.listar_manifestos()
    return [dict(r) if hasattr(r, "keys") else list(r) for r in rows]

@app.get("/frota", response_class=HTMLResponse)
def frota_page(request: Request, erro: str | None = None, ok: str | None = None):
    denied = redirect_if_denied(request, "frota", "visualizar")
    if denied: return denied
    user = current_user(request)
    rows = listar_caminhoes()
    caminhoes = []
    for r in rows:
        caminhoes.append({"id":r[0],"placa":r[1],"modelo":r[2],"motorista":r[3],"capacidade_kg":r[4],"media_km_l":r[5],"status": (r[6] if len(r) > 6 else "ATIVO")})
    ativos = sum(1 for v in caminhoes if str(v["status"] or "ATIVO").upper() == "ATIVO")
    return templates.TemplateResponse("frota.html", {"request":request,"user":user,"caminhoes":caminhoes,"ativos":ativos,"erro":erro,"ok":ok})

@app.post("/frota/criar")
def frota_criar(request: Request, placa: str = Form(...), modelo: str = Form(...), motorista: str = Form(""), capacidade_kg: float = Form(...), media_km_l: float = Form(0)):
    denied = redirect_if_denied(request, "frota", "criar")
    if denied: return denied
    try:
        cadastrar_caminhao(placa.strip().upper(), modelo.strip(), motorista.strip(), capacidade_kg, media_km_l)
        return RedirectResponse("/frota?ok=Veículo+cadastrado", status_code=303)
    except Exception as exc:
        return RedirectResponse("/frota?erro=" + "Falha ao processar a operação.", status_code=303)

@app.post("/frota/{caminhao_id}/status")
def frota_status(request: Request, caminhao_id: int, novo_status: str = Form(...)):
    denied = redirect_if_denied(request, "frota", "editar")
    if denied: return denied
    try:
        alterar_status_caminhao(caminhao_id, novo_status)
        return RedirectResponse("/frota?ok=Status+atualizado", status_code=303)
    except Exception as exc:
        return RedirectResponse("/frota?erro=" + "Falha ao processar a operação.", status_code=303)

@app.post("/frota/{caminhao_id}/excluir")
def frota_excluir(request: Request, caminhao_id: int):
    denied = redirect_if_denied(request, "frota", "excluir")
    if denied: return denied
    try:
        excluir_caminhao(caminhao_id)
        return RedirectResponse("/frota?ok=Veículo+excluído", status_code=303)
    except Exception as exc:
        return RedirectResponse("/frota?erro=" + "Falha ao processar a operação.", status_code=303)

@app.get("/api/frota")
def api_frota(request: Request):
    denied = redirect_if_denied(request, "frota", "visualizar")
    if denied: return denied
    rows = listar_caminhoes()
    return [{"id":r[0],"placa":r[1],"modelo":r[2],"motorista":r[3],"capacidade_kg":r[4],"media_km_l":r[5],"status":r[6] if len(r)>6 else "ATIVO"} for r in rows]



@app.get("/combustivel", response_class=HTMLResponse)
def combustivel_page(request: Request, erro: str | None = None, ok: str | None = None, busca: str = ""):
    denied = redirect_if_denied(request, "combustivel", "visualizar")
    if denied: return denied
    user = current_user(request)
    rows = frota_service.listar_abastecimentos("Geral", "", "", busca)
    abastecimentos = []
    for r in rows:
        abastecimentos.append({"id":r[0],"data":r[1],"veiculo":r[2],"motorista":r[3],"km":r[4],"litros":r[5],"valor_litro":r[6],"valor_total":r[7],"media":r[8],"custo_km":r[9],"posto":r[10],"observacao":r[11]})
    caminhoes = listar_caminhoes()
    veiculos = [{"placa":r[1],"modelo":r[2],"motorista":r[3]} for r in caminhoes]
    total_litros = sum(float(x["litros"] or 0) for x in abastecimentos)
    total_custo = sum(float(x["valor_total"] or 0) for x in abastecimentos)
    media = (sum(float(x["media"] or 0) for x in abastecimentos if float(x["media"] or 0) > 0) / max(1, sum(1 for x in abastecimentos if float(x["media"] or 0) > 0)))
    return templates.TemplateResponse("combustivel.html", {"request":request,"user":user,"abastecimentos":abastecimentos,"veiculos":veiculos,"total_litros":total_litros,"total_custo":total_custo,"media":media,"erro":erro,"ok":ok,"busca":busca})

@app.post("/combustivel/criar")
def combustivel_criar(request: Request, data_abastecimento: str = Form(...), veiculo: str = Form(...), motorista: str = Form(""), km_atual: float = Form(...), litros: float = Form(...), valor_litro: float = Form(...), valor_total: float = Form(...), posto: str = Form(""), observacao: str = Form("")):
    denied = redirect_if_denied(request, "combustivel", "criar")
    if denied: return denied
    try:
        total = valor_total if valor_total > 0 else litros * valor_litro
        media, custo_km = frota_service.calcular_media_e_custo(veiculo.strip(), km_atual, litros, total)
        frota_service.salvar_abastecimento(None, (data_abastecimento, veiculo.strip(), motorista.strip(), km_atual, litros, valor_litro, total, media, custo_km, posto.strip(), observacao.strip()))
        return RedirectResponse("/combustivel?ok=Abastecimento+registrado", status_code=303)
    except Exception as exc:
        return RedirectResponse("/combustivel?erro=" + "Falha ao processar a operação.", status_code=303)

@app.post("/combustivel/{abastecimento_id}/excluir")
def combustivel_excluir(request: Request, abastecimento_id: int):
    denied = redirect_if_denied(request, "combustivel", "excluir")
    if denied: return denied
    try:
        frota_service.excluir_abastecimento(abastecimento_id)
        return RedirectResponse("/combustivel?ok=Abastecimento+excluído", status_code=303)
    except Exception as exc:
        return RedirectResponse("/combustivel?erro=" + "Falha ao processar a operação.", status_code=303)

@app.get("/api/combustivel")
def api_combustivel(request: Request):
    denied = redirect_if_denied(request, "combustivel", "visualizar")
    if denied: return denied
    rows = frota_service.listar_abastecimentos("Geral", "", "", "")
    keys=['id','data_abastecimento','veiculo','motorista','km_atual','litros','valor_litro','valor_total','media_km_l','custo_km','posto','observacao']
    return [dict(zip(keys,r)) for r in rows]


@app.get("/manutencao", response_class=HTMLResponse)
def manutencao_page(request: Request, erro: str | None = None, ok: str | None = None, busca: str = ""):
    denied = redirect_if_denied(request, "manutencao", "visualizar")
    if denied: return denied
    user = current_user(request)
    rows = frota_service.listar_manutencoes("Geral", "", "", busca)
    manutencoes = []
    for r in rows:
        manutencoes.append({"id":r[0],"data":r[1],"veiculo":r[2],"km":r[3],"tipo":r[4],"descricao":r[5],"oficina":r[6],"valor":r[7],"proxima_revisao_km":r[8],"status":r[9] or "Pendente","observacao":r[10]})
    caminhoes = listar_caminhoes()
    veiculos = [{"placa":r[1],"modelo":r[2]} for r in caminhoes]
    total = len(manutencoes)
    custo = sum(float(x["valor"] or 0) for x in manutencoes)
    abertos = sum(1 for x in manutencoes if str(x["status"]).strip().lower() in {"pendente","aberta","aberto","em andamento","atrasada","atrasado"})
    return templates.TemplateResponse("manutencao.html", {"request":request,"user":user,"manutencoes":manutencoes,"veiculos":veiculos,"total":total,"custo":custo,"abertos":abertos,"erro":erro,"ok":ok,"busca":busca})

@app.post("/manutencao/criar")
def manutencao_criar(request: Request, data_manutencao: str = Form(...), veiculo: str = Form(...), km_atual: float = Form(0), tipo: str = Form(""), descricao: str = Form(""), oficina: str = Form(""), valor: float = Form(0), proxima_revisao_km: float = Form(0), status: str = Form("Pendente"), observacao: str = Form("")):
    denied = redirect_if_denied(request, "manutencao", "criar")
    if denied: return denied
    try:
        frota_service.salvar_manutencao(None, (data_manutencao, veiculo.strip(), km_atual, tipo.strip(), descricao.strip(), oficina.strip(), valor, proxima_revisao_km, status.strip(), observacao.strip()))
        return RedirectResponse("/manutencao?ok=Manutenção+registrada", status_code=303)
    except Exception as exc:
        return RedirectResponse("/manutencao?erro=" + "Falha ao processar a operação.", status_code=303)

@app.post("/manutencao/{manutencao_id}/status")
def manutencao_status(request: Request, manutencao_id: int, status: str = Form(...)):
    denied = redirect_if_denied(request, "manutencao", "editar")
    if denied: return denied
    try:
        atual = frota_service.obter_manutencao(manutencao_id)
        if not atual: raise ValueError("Manutenção não encontrada.")
        valores = list(atual[1:])
        valores[8] = status
        frota_service.salvar_manutencao(manutencao_id, valores)
        return RedirectResponse("/manutencao?ok=Status+atualizado", status_code=303)
    except Exception as exc:
        return RedirectResponse("/manutencao?erro=" + "Falha ao processar a operação.", status_code=303)

@app.post("/manutencao/{manutencao_id}/excluir")
def manutencao_excluir(request: Request, manutencao_id: int):
    denied = redirect_if_denied(request, "manutencao", "excluir")
    if denied: return denied
    try:
        frota_service.excluir_manutencao(manutencao_id)
        return RedirectResponse("/manutencao?ok=Manutenção+excluída", status_code=303)
    except Exception as exc:
        return RedirectResponse("/manutencao?erro=" + "Falha ao processar a operação.", status_code=303)

@app.post("/manutencao/{manutencao_id}/vincular")
def manutencao_vincular(request: Request, manutencao_id: int, viagem_id: int | None = Form(None)):
    denied = redirect_if_denied(request, "manutencao", "editar")
    if denied: return denied
    try:
        frota_service.vincular_manutencao_viagem(manutencao_id, viagem_id)
        return RedirectResponse("/manutencao?ok=Vínculo+atualizado", status_code=303)
    except Exception as exc:
        return RedirectResponse("/manutencao?erro=" + "Falha ao processar a operação.", status_code=303)

@app.get("/api/manutencao")
def api_manutencao(request: Request):
    denied = redirect_if_denied(request, "manutencao", "visualizar")
    if denied: return denied
    rows = frota_service.listar_manutencoes("Geral", "", "", "")
    keys=['id','data_manutencao','veiculo','km_atual','tipo','descricao','oficina','valor','proxima_revisao_km','status','observacao']
    return [dict(zip(keys,r)) for r in rows]

@app.get("/financeiro", response_class=HTMLResponse)
def financeiro_page(request: Request, erro: str | None = None, ok: str | None = None, busca: str = "", tipo: str = "", status: str = ""):
    denied = redirect_if_denied(request, "contas", "visualizar")
    if denied: return denied
    user = current_user(request)
    dados = financeiro_service.listar_contas(tipo=tipo or None, status=status or None, pagina=1, por_pagina=200)
    contas = dados["items"]
    if busca:
        termo = busca.strip().lower()
        contas = [c for c in contas if termo in " ".join(str(c.get(k) or "") for k in ("descricao","pessoa","categoria","observacao")).lower()]
    resumo = financeiro_service.resumo_financeiro()
    return templates.TemplateResponse("financeiro.html", {"request":request,"user":user,"contas":contas,"resumo":resumo,"erro":erro,"ok":ok,"busca":busca,"tipo":tipo,"status":status})

@app.post("/financeiro/criar")
def financeiro_criar(request: Request, tipo: str = Form(...), descricao: str = Form(...), pessoa: str = Form(""), categoria: str = Form("Outros"), valor: float = Form(...), vencimento: str = Form(...), pagamento: str = Form(""), status: str = Form("Pendente"), observacao: str = Form(""), viagem_id: str = Form("")):
    denied = redirect_if_denied(request, "contas", "criar")
    if denied: return denied
    try:
        dados = {"tipo":tipo,"descricao":descricao,"pessoa":pessoa,"categoria":categoria,"valor":valor,"vencimento":vencimento,"pagamento":pagamento or None,"status":status,"observacao":observacao,"viagem_id":int(viagem_id) if viagem_id.strip() else None}
        financeiro_service.criar_conta(dados)
        return RedirectResponse("/financeiro?ok=Lançamento+criado", status_code=303)
    except Exception as exc:
        return RedirectResponse("/financeiro?erro=" + "Falha ao processar a operação.", status_code=303)

@app.post("/financeiro/{conta_id}/pagar")
def financeiro_pagar(request: Request, conta_id: int, pagamento: str = Form("")):
    denied = redirect_if_denied(request, "contas", "editar")
    if denied: return denied
    try:
        financeiro_service.marcar_pago(conta_id, pagamento or None)
        return RedirectResponse("/financeiro?ok=Conta+marcada+como+paga", status_code=303)
    except Exception as exc:
        return RedirectResponse("/financeiro?erro=" + "Falha ao processar a operação.", status_code=303)

@app.post("/financeiro/{conta_id}/status")
def financeiro_status(request: Request, conta_id: int, status: str = Form(...)):
    denied = redirect_if_denied(request, "contas", "editar")
    if denied: return denied
    try:
        conn = conectar(); row = conn.execute("SELECT tipo,descricao,pessoa,categoria,valor,vencimento,pagamento,status,observacao FROM contas WHERE id=? AND COALESCE(deletado,0)=0", (conta_id,)).fetchone(); conn.close()
        if not row: raise ValueError("Conta não encontrada.")
        financeiro_service.atualizar_conta(conta_id, {"tipo":row[0],"descricao":row[1],"pessoa":row[2],"categoria":row[3],"valor":row[4],"vencimento":row[5],"pagamento":row[6],"status":status,"observacao":row[8]})
        return RedirectResponse("/financeiro?ok=Status+atualizado", status_code=303)
    except Exception as exc:
        return RedirectResponse("/financeiro?erro=" + "Falha ao processar a operação.", status_code=303)

@app.post("/financeiro/{conta_id}/excluir")
def financeiro_excluir(request: Request, conta_id: int):
    denied = redirect_if_denied(request, "contas", "excluir")
    if denied: return denied
    try:
        financeiro_service.excluir_conta(conta_id)
        return RedirectResponse("/financeiro?ok=Lançamento+excluído", status_code=303)
    except Exception as exc:
        return RedirectResponse("/financeiro?erro=" + "Falha ao processar a operação.", status_code=303)

@app.get("/api/financeiro")
def api_financeiro(request: Request, tipo: str = "", status: str = ""):
    denied = redirect_if_denied(request, "contas", "visualizar")
    if denied: return denied
    return {"resumo":financeiro_service.resumo_financeiro(),"fluxo":financeiro_service.fluxo_caixa(),"contas":financeiro_service.listar_contas(tipo=tipo or None,status=status or None,pagina=1,por_pagina=200)["items"]}


funcionarios_service = FuncionariosService()

@app.get("/funcionarios", response_class=HTMLResponse)
def funcionarios_page(request: Request, busca: str = "", mes: str = "", ano: str = "", erro: str | None = None, ok: str | None = None):
    denied = redirect_if_denied(request, "funcionarios", "visualizar")
    if denied: return denied
    user = current_user(request)
    agora = datetime.now()
    mes = mes or f"{agora.month:02d}"; ano = ano or str(agora.year)
    funcionarios = funcionarios_service.listar_funcionarios(busca)
    folha = funcionarios_service.listar_folha_mes(mes, ano, busca)
    ativos = sum(1 for f in funcionarios if str(f[7]).lower() == "ativo")
    total_folha = sum(float(f[9] or 0) for f in folha)
    return templates.TemplateResponse("funcionarios.html", {"request":request,"user":user,"funcionarios":funcionarios,"folha":folha,"ativos":ativos,"total_folha":total_folha,"busca":busca,"mes":mes,"ano":ano,"erro":erro,"ok":ok})

@app.post("/funcionarios/salvar")
def funcionario_criar(request: Request, nome: str = Form(...), cargo: str = Form(...), telefone: str = Form(""), data_admissao: str = Form(""), salario: float = Form(0), vale_refeicao: float = Form(0), status: str = Form("Ativo")):
    denied = redirect_if_denied(request, "funcionarios", "criar")
    if denied: return denied
    try:
        funcionarios_service.salvar_funcionario(None, (nome,cargo,telefone,data_admissao or None,salario,vale_refeicao,status))
        return RedirectResponse("/funcionarios?ok=Funcion%C3%A1rio+criado", status_code=303)
    except Exception as exc: return RedirectResponse("/funcionarios?erro="+"Falha ao processar a operação.".replace(" ","+"), status_code=303)

@app.get("/funcionarios/{funcionario_id}", response_class=HTMLResponse)
def funcionario_edit_page(request: Request, funcionario_id: int, mes: str = "", ano: str = "", erro: str | None = None, ok: str | None = None):
    denied = redirect_if_denied(request, "funcionarios", "visualizar")
    if denied: return denied
    f = funcionarios_service.obter_funcionario(funcionario_id)
    if not f: return HTMLResponse("<h1>Funcionário não encontrado</h1>", status_code=404)
    agora=datetime.now(); mes=mes or f"{agora.month:02d}"; ano=ano or str(agora.year)
    folha=funcionarios_service.obter_folha_funcionario(funcionario_id,mes,ano)
    return templates.TemplateResponse("funcionario_edit.html", {"request":request,"user":current_user(request),"f":f,"folha":folha,"mes":mes,"ano":ano,"erro":erro,"ok":ok})

@app.post("/funcionarios/{funcionario_id}/salvar")
def funcionario_salvar(request: Request, funcionario_id: int, nome: str = Form(...), cargo: str = Form(...), telefone: str = Form(""), data_admissao: str = Form(""), salario: float = Form(0), vale_refeicao: float = Form(0), status: str = Form("Ativo")):
    denied = redirect_if_denied(request, "funcionarios", "editar")
    if denied: return denied
    try:
        funcionarios_service.salvar_funcionario(funcionario_id,(nome,cargo,telefone,data_admissao or None,salario,vale_refeicao,status))
        return RedirectResponse(f"/funcionarios/{funcionario_id}?ok=Funcion%C3%A1rio+atualizado",status_code=303)
    except Exception as exc: return RedirectResponse(f"/funcionarios/{funcionario_id}?erro="+"Falha ao processar a operação.".replace(" ","+"),status_code=303)

@app.post("/funcionarios/{funcionario_id}/excluir")
def funcionario_excluir(request: Request, funcionario_id: int):
    denied = redirect_if_denied(request, "funcionarios", "excluir")
    if denied: return denied
    try: funcionarios_service.excluir_funcionario(funcionario_id); return RedirectResponse("/funcionarios?ok=Funcion%C3%A1rio+exclu%C3%ADdo",status_code=303)
    except Exception as exc: return RedirectResponse("/funcionarios?erro="+"Falha ao processar a operação.".replace(" ","+"),status_code=303)

@app.post("/funcionarios/folha/gerar")
def folha_gerar(request: Request, mes: str = Form(...), ano: str = Form(...)):
    denied = redirect_if_denied(request, "funcionarios", "editar")
    if denied: return denied
    try: n=funcionarios_service.gerar_folha_todos(mes,ano); return RedirectResponse(f"/funcionarios?mes={mes}&ano={ano}&ok={n}+folha(s)+gerada(s)",status_code=303)
    except Exception as exc: return RedirectResponse("/funcionarios?erro="+"Falha ao processar a operação.".replace(" ","+"),status_code=303)

@app.post("/funcionarios/{funcionario_id}/folha")
def folha_salvar(request: Request, funcionario_id: int, mes: str = Form(...), ano: str = Form(...), salario: float = Form(0), vale_refeicao: float = Form(0), qtd_horas_extra: float = Form(0), valor_hora_extra: float = Form(0), outros: float = Form(0)):
    denied = redirect_if_denied(request, "funcionarios", "editar")
    if denied: return denied
    try:
        funcionarios_service.salvar_folha(funcionario_id,mes,ano,salario,vale_refeicao,qtd_horas_extra,valor_hora_extra,outros)
        return RedirectResponse(f"/funcionarios/{funcionario_id}?mes={mes}&ano={ano}&ok=Folha+salva",status_code=303)
    except Exception as exc: return RedirectResponse(f"/funcionarios/{funcionario_id}?mes={mes}&ano={ano}&erro="+"Falha ao processar a operação.".replace(" ","+"),status_code=303)

@app.get("/api/funcionarios")
def api_funcionarios(request: Request, busca: str = ""):
    denied=redirect_if_denied(request,"funcionarios","visualizar")
    if denied: return denied
    keys=['id','nome','cargo','telefone','data_admissao','salario','vale_refeicao','status']
    return [dict(zip(keys,r)) for r in funcionarios_service.listar_funcionarios(busca)]

@app.get("/modulos/{modulo}", response_class=HTMLResponse)
def modulo(request: Request, modulo: str):
    user = protected(request)
    if not user: return RedirectResponse("/login", status_code=303)
    if modulo in {"operacoes","viagens","historico"}: return RedirectResponse("/viagens", status_code=303)
    if modulo == "frota": return RedirectResponse("/frota", status_code=303)
    if modulo == "combustivel": return RedirectResponse("/combustivel", status_code=303)
    if modulo == "manutencao": return RedirectResponse("/manutencao", status_code=303)
    if modulo == "notas": return RedirectResponse("/notas", status_code=303)
    if modulo == "financeiro": return RedirectResponse("/financeiro", status_code=303)
    if modulo == "funcionarios": return RedirectResponse("/funcionarios", status_code=303)
    if modulo == "relatorios": return RedirectResponse("/relatorios", status_code=303)
    if not can(user, modulo, "visualizar"): return HTMLResponse("<h1>Acesso negado</h1>", status_code=403)
    return templates.TemplateResponse("module.html", {"request":request,"user":user,"modulo":modulo})


@app.get("/api/health")
def health():
    status = {"ok": True, "service": "cw-transportadora-web", "version": APP_VERSION, "time": datetime.now().isoformat()}
    conn = None
    try:
        conn = conectar(); row = conn.execute("SELECT 1").fetchone()
        status["database"] = "postgresql" if DATABASE_URL else "sqlite"
        status["database_ok"] = bool(row and row[0] == 1)
        status["ok"] = status["database_ok"]
    except Exception:
        status["ok"] = False; status["database"] = "error"; status["database_ok"] = False
    finally:
        if conn is not None:
            conn.close()
    return status

# V1.8: Relatórios web usando o RelatoriosService original.
from services.relatorios_service import RelatoriosService
relatorios_service = RelatoriosService()

@app.get("/relatorios", response_class=HTMLResponse)
def relatorios_page(request: Request, tipo: str = "Mês", mes: int | None = None, ano: int | None = None):
    denied = redirect_if_denied(request, "relatorios", "visualizar")
    if denied: return denied
    agora = datetime.now(); mes = mes or agora.month; ano = ano or agora.year
    if tipo not in {"Mês", "Ano", "Total"}: tipo = "Mês"
    resumo = relatorios_service.carregar_resumo(tipo, str(mes), str(ano))
    detalhes = relatorios_service.detalhes_premium(tipo, mes, ano, limite=25)
    return templates.TemplateResponse("relatorios.html", {"request":request,"user":current_user(request),"tipo":tipo,"mes":mes,"ano":ano,"resumo":resumo,"detalhes":detalhes})

@app.get("/relatorios/pdf")
def relatorios_pdf(request: Request, tipo: str = "Mês", mes: int | None = None, ano: int | None = None):
    denied = redirect_if_denied(request, "relatorios", "visualizar")
    if denied: return denied
    agora=datetime.now(); mes=mes or agora.month; ano=ano or agora.year
    if tipo not in {"Mês","Ano","Total"}: tipo="Mês"
    import tempfile
    fd, caminho = tempfile.mkstemp(prefix="cw_relatorio_", suffix=".pdf"); os.close(fd)
    try:
        relatorios_service.gerar_pdf(caminho, tipo, mes, ano)
        return FileResponse(caminho, media_type="application/pdf", filename=f"CW_Relatorio_{ano}_{mes:02d}.pdf", background=None)
    except Exception as exc:
        try: os.unlink(caminho)
        except OSError: pass
        return HTMLResponse(f"<h1>Erro ao gerar relatório</h1><p>Não foi possível gerar o relatório.</p>", status_code=500)

@app.get("/api/relatorios")
def api_relatorios(request: Request, tipo: str = "Mês", mes: int | None = None, ano: int | None = None):
    denied = redirect_if_denied(request, "relatorios", "visualizar")
    if denied: return denied
    agora=datetime.now(); mes=mes or agora.month; ano=ano or agora.year
    return {"resumo": relatorios_service.carregar_resumo(tipo, str(mes), str(ano)), "detalhes": relatorios_service.detalhes_premium(tipo, mes, ano, limite=25)}

# V1.9: Configurações, usuários/permissões e perfil web.
from services.config_service import config_service
from services.usuario_service import usuario_service, MODULOS_PERMISSOES, validar_forca_senha, SenhaFracaError

@app.get('/configuracoes', response_class=HTMLResponse)
def configuracoes_page(request: Request, erro: str | None = None, ok: str | None = None):
    denied = redirect_if_denied(request, 'configuracoes', 'visualizar')
    if denied: return denied
    cfg = dict(config_service.carregar_configuracoes())
    info = config_service.info_banco()
    return templates.TemplateResponse('configuracoes.html', {'request':request,'user':current_user(request),'cfg':cfg,'info':info,'erro':erro,'ok':ok})

@app.post('/configuracoes/salvar')
def configuracoes_salvar(request: Request, empresa: str=Form(...), cnpj: str=Form(''), telefone: str=Form(''), email: str=Form(''), cidade: str=Form(''), uf: str=Form(''), meta_lucro: str=Form('0'), imposto_percentual: str=Form('0'), pasta_relatorios: str=Form('relatorios_gerados')):
    denied = redirect_if_denied(request, 'configuracoes', 'editar')
    if denied: return denied
    try:
        config_service.salvar_configuracoes({'empresa':empresa.strip(),'cnpj':cnpj.strip(),'telefone':telefone.strip(),'email':email.strip(),'cidade':cidade.strip(),'uf':uf.strip().upper(),'meta_lucro':meta_lucro,'imposto_percentual':imposto_percentual,'pasta_relatorios':pasta_relatorios.strip() or 'relatorios_gerados'})
        return RedirectResponse('/configuracoes?ok=Configurações+salvas', status_code=303)
    except Exception as exc:
        return RedirectResponse('/configuracoes?erro='+"Falha ao processar a operação.".replace(' ','+'), status_code=303)

@app.post('/configuracoes/backup')
def configuracoes_backup(request: Request):
    denied = redirect_if_denied(request, 'configuracoes', 'criar')
    if denied: return denied
    try:
        destino = config_service.fazer_backup()
        return RedirectResponse('/configuracoes?ok=Backup+criado+com+sucesso', status_code=303)
    except Exception as exc:
        return RedirectResponse('/configuracoes?erro='+"Falha ao processar a operação.".replace(' ','+'), status_code=303)

@app.get('/api/configuracoes')
def api_configuracoes(request: Request):
    denied = redirect_if_denied(request, 'configuracoes', 'visualizar')
    if denied: return denied
    cfg = dict(config_service.carregar_configuracoes())
    for k in ('supabase_key','supabase_sync_token','github_token','update_server_password'):
        cfg.pop(k, None)
    return {'configuracoes':cfg,'banco':config_service.info_banco()}

@app.get('/usuarios', response_class=HTMLResponse)
def usuarios_page(request: Request, erro: str | None=None, ok: str | None=None):
    denied = redirect_if_denied(request, 'usuarios', 'visualizar')
    if denied: return denied
    return templates.TemplateResponse('usuarios.html', {'request':request,'user':current_user(request),'usuarios':usuario_service.listar_usuarios(),'erro':erro,'ok':ok})

@app.post('/usuarios/criar')
def usuarios_criar(request: Request, nome_completo: str=Form(...), usuario: str=Form(...), senha: str=Form(...), nivel_acesso: str=Form('comum')):
    denied = redirect_if_denied(request, 'usuarios', 'criar')
    if denied: return denied
    try:
        err = validar_forca_senha(senha)
        if err: raise ValueError(err)
        if nivel_acesso not in ('mestre','operacional','comum'): raise ValueError('Nível de acesso inválido.')
        conn=conectar()
        try:
            u=usuario.strip().lower()
            if conn.execute('SELECT id FROM usuarios WHERE usuario=?',(u,)).fetchone(): raise ValueError('Usuário já existe.')
            salt=auth_service.gerar_salt(); senha_hash=auth_service.hash_senha(senha,salt)
            cur=conn.execute('INSERT INTO usuarios (nome_completo,usuario,senha_hash,senha_salt,nivel_acesso,ativo,criado_por,criado_em,atualizado_em) VALUES (?,?,?,?,?,1,?,?,?)',(nome_completo.strip(),u,senha_hash,salt.hex(),nivel_acesso,current_user(request)['id'],datetime.now().strftime('%Y-%m-%d %H:%M:%S'),datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            novo_id=cur.lastrowid
            conn.commit()
        finally: conn.close()
        return RedirectResponse('/usuarios?ok=Usuário+criado',status_code=303)
    except Exception as exc: return RedirectResponse('/usuarios?erro='+"Falha ao processar a operação.".replace(' ','+'),status_code=303)

@app.get('/usuarios/{usuario_id}', response_class=HTMLResponse)
def usuario_edit_page(request: Request, usuario_id: int, erro: str|None=None, ok: str|None=None):
    denied=redirect_if_denied(request,'usuarios','visualizar')
    if denied:return denied
    u=usuario_service.obter_usuario(usuario_id)
    if not u:return HTMLResponse('<h1>Usuário não encontrado</h1>',status_code=404)
    return templates.TemplateResponse('usuario_edit.html',{'request':request,'user':current_user(request),'u':u,'permissoes':usuario_service.obter_permissoes(usuario_id),'modulos':MODULOS_PERMISSOES,'acoes':['visualizar','criar','editar','excluir','exportar','sincronizar'],'erro':erro,'ok':ok})

@app.post('/usuarios/{usuario_id}/status')
def usuario_status(request: Request, usuario_id:int, ativo:int=Form(...)):
    denied=redirect_if_denied(request,'usuarios','editar')
    if denied:return denied
    try:
        if usuario_id == current_user(request)['id'] and not ativo: raise ValueError('Não é possível desativar o próprio usuário.')
        conn=conectar(); conn.execute('UPDATE usuarios SET ativo=?,atualizado_em=CURRENT_TIMESTAMP WHERE id=?',(1 if ativo else 0,usuario_id)); conn.commit(); conn.close()
        return RedirectResponse('/usuarios?ok=Status+atualizado',status_code=303)
    except Exception as exc:return RedirectResponse('/usuarios?erro='+"Falha ao processar a operação.".replace(' ','+'),status_code=303)

@app.post('/usuarios/{usuario_id}/excluir')
def usuario_excluir(request: Request, usuario_id:int):
    denied=redirect_if_denied(request,'usuarios','excluir')
    if denied:return denied
    try:
        if usuario_id == current_user(request)['id']: raise ValueError('Não é possível excluir o próprio usuário.')
        conn=conectar(); conn.execute('DELETE FROM permissoes_usuario WHERE usuario_id=?',(usuario_id,)); conn.execute('DELETE FROM usuarios WHERE id=?',(usuario_id,)); conn.commit(); conn.close()
        return RedirectResponse('/usuarios?ok=Usuário+excluído',status_code=303)
    except Exception as exc:return RedirectResponse('/usuarios?erro='+"Falha ao processar a operação.".replace(' ','+'),status_code=303)

@app.post('/usuarios/{usuario_id}/dados')
def usuario_dados(request: Request, usuario_id:int, nome_completo:str=Form(...), nivel_acesso:str=Form(...)):
    denied=redirect_if_denied(request,'usuarios','editar')
    if denied:return denied
    try:
        if nivel_acesso not in ('mestre','operacional','comum'): raise ValueError('Nível inválido.')
        conn=conectar(); conn.execute('UPDATE usuarios SET nome_completo=?,nivel_acesso=?,atualizado_em=CURRENT_TIMESTAMP WHERE id=?',(nome_completo.strip(),nivel_acesso,usuario_id)); conn.commit(); conn.close()
        return RedirectResponse(f'/usuarios/{usuario_id}?ok=Dados+atualizados',status_code=303)
    except Exception as exc:return RedirectResponse(f'/usuarios/{usuario_id}?erro='+"Falha ao processar a operação.".replace(' ','+'),status_code=303)

@app.post('/usuarios/{usuario_id}/senha')
def usuario_redefinir_senha(request: Request, usuario_id:int):
    denied=redirect_if_denied(request,'usuarios','editar')
    if denied:return denied
    try:
        # Fazemos a operação diretamente para manter a sessão web isolada por usuário.
        import secrets,string
        chars=string.ascii_letters+string.digits+'!@#$%&*'; senha='A'+secrets.choice(string.ascii_lowercase)+secrets.choice(string.digits)+secrets.choice('!@#$%&*')+''.join(secrets.choice(chars) for _ in range(8))
        salt=auth_service.gerar_salt(); h=auth_service.hash_senha(senha,salt)
        conn=conectar(); conn.execute('UPDATE usuarios SET senha_hash=?,senha_salt=?,deve_alterar_senha=1,tentativas_falhas=0,bloqueado_ate=NULL,atualizado_em=CURRENT_TIMESTAMP WHERE id=?',(h,salt.hex(),usuario_id)); conn.commit(); conn.close()
        return RedirectResponse(f'/usuarios/{usuario_id}?ok=Senha+temporária:+{senha}',status_code=303)
    except Exception as exc:return RedirectResponse(f'/usuarios/{usuario_id}?erro='+"Falha ao processar a operação.".replace(' ','+'),status_code=303)

@app.post('/usuarios/{usuario_id}/permissoes')
def usuario_permissoes(request: Request, usuario_id:int):
    denied=redirect_if_denied(request,'usuarios','editar')
    if denied:return denied
    try:
        form=request._form if False else None
        # Form síncrono via Starlette é async; endpoint convertido para async abaixo não é possível aqui.
        raise RuntimeError('Use o endpoint assíncrono de permissões.')
    except RuntimeError:
        return RedirectResponse(f'/usuarios/{usuario_id}?erro=Falha+ao+salvar+permissões',status_code=303)

@app.post('/usuarios/{usuario_id}/permissoes-async')
async def usuario_permissoes_async(request: Request, usuario_id:int):
    denied=redirect_if_denied(request,'usuarios','editar')
    if denied:return denied
    try:
        form=await request.form(); permissoes={}
        for modulo in MODULOS_PERMISSOES:
            permissoes[modulo]={acao: (f'{modulo}__{acao}' in form) for acao in ['visualizar','criar','editar','excluir','exportar','sincronizar']}
        conn=conectar(); conn.execute('DELETE FROM permissoes_usuario WHERE usuario_id=?',(usuario_id,))
        for modulo,acoes in permissoes.items():
            conn.execute('INSERT OR REPLACE INTO permissoes_usuario (usuario_id,modulo,pode_visualizar,pode_criar,pode_editar,pode_excluir,pode_exportar,pode_sincronizar) VALUES (?,?,?,?,?,?,?,?)',(usuario_id,modulo,int(acoes['visualizar']),int(acoes['criar']),int(acoes['editar']),int(acoes['excluir']),int(acoes['exportar']),int(acoes['sincronizar'])))
        conn.commit(); conn.close()
        return RedirectResponse(f'/usuarios/{usuario_id}?ok=Permissões+salvas',status_code=303)
    except Exception as exc:return RedirectResponse(f'/usuarios/{usuario_id}?erro='+"Falha ao processar a operação.".replace(' ','+'),status_code=303)

@app.get('/perfil', response_class=HTMLResponse)
def perfil_page(request: Request, erro: str|None=None, ok: str|None=None):
    if not current_user(request): return RedirectResponse('/login',status_code=303)
    return templates.TemplateResponse('perfil.html',{'request':request,'user':current_user(request),'erro':erro,'ok':ok})

@app.post('/perfil/senha')
def perfil_senha(request: Request, senha_atual:str=Form(...), nova_senha:str=Form(...), confirmacao:str=Form(...)):
    user=current_user(request)
    if not user:return RedirectResponse('/login',status_code=303)
    try:
        erro=validar_forca_senha(nova_senha)
        if erro: raise ValueError(erro)
        if nova_senha != confirmacao: raise ValueError('A confirmação da nova senha não confere.')
        conn=conectar(); row=conn.execute('SELECT senha_hash,senha_salt FROM usuarios WHERE id=?',(user['id'],)).fetchone()
        if not row or not auth_service.verificar_senha(senha_atual,row[0],row[1]): raise ValueError('Senha atual incorreta.')
        if senha_atual==nova_senha: raise ValueError('A nova senha deve ser diferente da atual.')
        salt=auth_service.gerar_salt(); h=auth_service.hash_senha(nova_senha,salt)
        conn.execute('UPDATE usuarios SET senha_hash=?,senha_salt=?,deve_alterar_senha=0,atualizado_em=CURRENT_TIMESTAMP WHERE id=?',(h,salt.hex(),user['id'])); conn.commit(); conn.close()
        return RedirectResponse('/perfil?ok=Senha+alterada+com+sucesso',status_code=303)
    except Exception as exc:return RedirectResponse('/perfil?erro='+"Falha ao processar a operação.".replace(' ','+'),status_code=303)
