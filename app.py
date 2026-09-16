import os
from datetime import datetime
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

import streamlit as st
from supabase import create_client, ClientOptions
from supabase_auth.helpers import generate_pkce_challenge, generate_pkce_verifier

from extracao import (
    listar_locais_openaccess,
    baixar_pdf_bytes,
    baixar_texto_pdf,
    texto_de_pdf_bytes,
    extrair_campos_com_claude,
    obter_token_publico_orcid,
    listar_publicacoes_orcid,
)
from persistencia import garantir_fonte, salvar_amostra
from simetria import aplicar_em_material, aplicar_restricao
from unidades import para_celsius, para_kelvin, temperatura_medida_para_k

SISTEMAS_CRISTALINOS = ["Selecione...", "Cúbico", "Tetragonal", "Ortorrômbico", "Romboédrico",
                         "Hexagonal", "Monoclínico", "Triclínico"]
TECNICAS_MEDICAO = ["Selecione...", "DRX laboratório (Cu Kα)", "Síncrotron", "Nêutrons", "Monocristal", "Outra"]
ATMOSFERAS = ["Selecione...", "Ar", "O2", "N2", "Vácuo"]
SITES_SUBSTITUICAO = ["Selecione...", "A", "B", "ambos"]


BRASILIA = ZoneInfo("America/Sao_Paulo")


def formatar_criado_em(valor) -> str:
    if not valor:
        return "—"
    if isinstance(valor, datetime):
        dt = valor
    else:
        texto = str(valor).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(texto)
        except ValueError:
            return str(valor)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(BRASILIA).strftime("%d/%m/%Y %H:%M")


def _get_secret(name: str, default: str | None = None) -> str | None:
    valor = os.environ.get(name)
    if valor:
        return valor
    try:
        return str(st.secrets[name])
    except Exception:
        return default


@st.cache_resource
def get_supabase_client():
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    try:
        return create_client(
            url,
            key,
            options=ClientOptions(flow_type="pkce"),
        )
    except Exception:
        return None


@st.cache_resource
def get_token_orcid_publico():
    # Token de leitura pública do ORCID: não é específico de nenhum professor,
    # então é seguro compartilhar entre todas as sessões via cache_resource.
    return obter_token_publico_orcid()


st.set_page_config(page_title="Rede de Materiais", page_icon="🧪", layout="wide")
st.markdown(
    """
    <style>
      .block-container {
        max-width: 100% !important;
        padding-top: 1rem;
        padding-bottom: 1.5rem;
        padding-left: 2rem;
        padding-right: 2rem;
      }
      div[data-testid="stForm"] {
        border: 1px solid rgba(49, 51, 63, 0.15);
        padding: 0.8rem 1rem 1rem;
      }
      [data-testid="stHorizontalBlock"] { gap: 1.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

supabase = get_supabase_client()


def _numero(valor, padrao=0.0) -> float:
    try:
        if valor is None or valor == "":
            return float(padrao)
        return float(valor)
    except (TypeError, ValueError):
        return float(padrao)


def _numero_ou_none(valor) -> float | None:
    try:
        if valor is None or valor == "":
            return None
        return float(valor)
    except (TypeError, ValueError):
        return None


def registrar_extracao(materiais: list[dict]):
    materiais = [aplicar_em_material(m) for m in (materiais or []) if isinstance(m, dict)]
    if not materiais:
        st.warning("O artigo foi lido, mas nenhum material foi identificado no texto.")
        return
    st.session_state["extraidos"] = materiais
    medidas = sum(len(m.get("medidas") or []) for m in materiais)
    st.success(
        f"{len(materiais)} material(is) e {medidas} medida(s) encontrados. "
        "Revise antes de salvar."
    )


def cliente_da_sessao():
    """Cliente por rerun — set_session no client compartilhado vaza token entre usuários no Cloud."""
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    client = create_client(url, key, options=ClientOptions(flow_type="pkce"))
    client.auth.set_session(
        st.session_state["access_token"],
        st.session_state["refresh_token"],
    )
    return client


def url_publica() -> str:
    """Origem atual (local ou Cloud). Não depende de memória do processo."""
    atual = getattr(st.context, "url", None)
    if atual:
        partes = urlparse(atual)
        if partes.scheme and partes.netloc:
            return f"{partes.scheme}://{partes.netloc}"
    return _get_secret("REDIRECT_URL", "http://localhost:8502") or "http://localhost:8502"


def supabase_auth_acessivel(url: str) -> bool:
    """Qualquer resposta HTTP do Auth (inclui 401 sem apikey) significa que o host está no ar."""
    headers = {}
    chave = _get_secret("SUPABASE_ANON_KEY")
    if chave:
        headers["apikey"] = chave
        headers["Authorization"] = f"Bearer {chave}"
    try:
        resp = requests.get(
            f"{url.rstrip('/')}/auth/v1/settings",
            headers=headers,
            timeout=8,
        )
        return resp.status_code < 500
    except requests.RequestException:
        return False


def montar_url_login_orcid() -> str:
    """PKCE próprio; o verifier vai em ?cv= no retorno. Não usar `state` — o ORCID/Supabase validam o deles."""
    url_supabase = _get_secret("SUPABASE_URL")
    if not url_supabase:
        raise RuntimeError("SUPABASE_URL ausente")
    verifier = generate_pkce_verifier()
    params = {
        "provider": "custom:orcid",
        "redirect_to": f"{url_publica()}/?cv={verifier}",
        "code_challenge": generate_pkce_challenge(verifier),
        "code_challenge_method": "s256",
    }
    return f"{url_supabase.rstrip('/')}/auth/v1/authorize?{urlencode(params)}"


def idx_selectbox(opcoes, valor):
    if valor and valor in opcoes:
        return opcoes.index(valor)
    return 0


def cabecalho_institucional():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("assets/logo_gddm.png", width="stretch")

    st.markdown(
        """
        <div style="text-align: center; margin-top: -8px; margin-bottom: 20px;">
            <div style="font-size: 15px; font-weight: 600; color: #1a1a2e; letter-spacing: 0.4px;">
                Universidade Estadual de Maringá
            </div>
            <div style="font-size: 13px; color: #555555; margin-top: 2px;">
                Departamento de Física
            </div>
            <div style="font-size: 12px; color: #888888; margin-top: 4px; letter-spacing: 0.3px;">
                Grupo de Desenvolvimento e Inovação em Dispositivos Multifuncionais (GDDM)
            </div>
        </div>
        <hr style="border: none; border-top: 1px solid #e5e5e5; margin: 8px 0 28px 0;">
        """,
        unsafe_allow_html=True,
    )


def fazer_login():
    cabecalho_institucional()

    st.title("🧪 Rede de Materiais")
    st.caption("Entre com seu ORCID para cadastrar materiais.")

    url_supabase = _get_secret("SUPABASE_URL") or ""
    if not url_supabase or not supabase_auth_acessivel(url_supabase):
        st.error(
            "O servidor de autenticação do Supabase está fora do ar "
            "(DNS ou Auth sem resposta). O ORCID não consegue completar o login assim."
        )
        st.markdown(
            "Abra o projeto no dashboard, restaure se estiver pausado/inexistente "
            "e confira se a URL em `SUPABASE_URL` (`.env` e secrets do Cloud) é a atual:"
        )
        if url_supabase:
            ref = urlparse(url_supabase).hostname or ""
            ref = ref.replace(".supabase.co", "")
            if ref:
                st.link_button(
                    "Abrir dashboard do Supabase",
                    f"https://supabase.com/dashboard/project/{ref}",
                )
        if st.button("Verificar de novo"):
            st.rerun()
        return

    try:
        st.link_button("Entrar com ORCID", montar_url_login_orcid(), type="primary")
    except Exception as e:
        st.error(f"Não consegui gerar o login ORCID/Supabase: {e}")
        if st.button("Tentar novamente"):
            st.rerun()


def processar_callback():
    erro_oauth = st.query_params.get("error_description") or st.query_params.get("error")
    if erro_oauth and not st.query_params.get("code"):
        st.session_state.pop("auth_url", None)
        st.error(f"ORCID/Supabase recusou o login: {erro_oauth}")
        if st.button("Tentar login novamente"):
            st.query_params.clear()
            st.rerun()
        return True

    code = st.query_params.get("code")
    if not code:
        return False

    verifier = st.query_params.get("cv")
    if not verifier:
        st.query_params.clear()
        st.error("O retorno do login chegou sem o verificador PKCE. Clique em Entrar com ORCID de novo.")
        if st.button("Tentar login novamente"):
            st.rerun()
        return True

    try:
        destino = f"{url_publica()}/?cv={verifier}"
        result = supabase.auth.exchange_code_for_session({
            "auth_code": code,
            "code_verifier": verifier,
            "redirect_to": destino,
        })
        if not result.session:
            raise RuntimeError("Supabase não devolveu sessão após o ORCID.")
        st.session_state["access_token"] = result.session.access_token
        st.session_state["refresh_token"] = result.session.refresh_token

        nome = " ".join(filter(None, [
            (result.user.user_metadata or {}).get("given_name"),
            (result.user.user_metadata or {}).get("family_name"),
        ])) or None

        row = {
            "user_id": result.user.id,
            "email": result.user.email or None,
            "nome": nome,
            "orcid_id": (result.user.user_metadata or {}).get("sub"),
        }
        supabase.table("pesquisadores").upsert(row, on_conflict="user_id").execute()
        try:
            supabase.table("professores").upsert(row, on_conflict="user_id").execute()
        except Exception:
            pass

        st.query_params.clear()
        st.rerun()
    except Exception as e:
        # Limpa o código morto da URL e força gerar um link novo na próxima tentativa
        st.query_params.clear()
        st.session_state.pop("auth_url", None)
        st.error(f"Erro ao validar login: {e}")
        st.caption("O link de autorização anterior expirou ou já foi usado.")
        if st.button("Tentar login novamente"):
            st.rerun()
    return True


def encerrar_sessao():
    st.session_state.pop("access_token", None)
    st.session_state.pop("refresh_token", None)
    st.session_state.pop("auth_url", None)
    st.session_state.pop("extraidos", None)
    st.session_state.pop("fonte_id", None)
    st.session_state.pop("fonte_titulo", None)
    st.session_state.pop("publicacoes_orcid", None)


def get_pesquisador_logado():
    try:
        client = cliente_da_sessao()
        if client is None:
            encerrar_sessao()
            return None
        user = client.auth.get_user().user
        if not user:
            encerrar_sessao()
            return None
        resp = (
            client.table("pesquisadores")
            .select("id, nome, email, orcid_id, aprovado")
            .eq("user_id", user.id)
            .single()
            .execute()
        )
        return resp.data
    except Exception:
        encerrar_sessao()
        return None


def anexar_e_extrair(pesquisador, *, doi=None, pdf_bytes=None, nome_arquivo=None):
    """Garante a fonte (DOI único), guarda o PDF e preenche a extração."""
    client = cliente_da_sessao()
    if client is None:
        raise RuntimeError("Sessão inválida.")

    bytes_pdf = pdf_bytes
    if bytes_pdf is None and doi:
        for url in listar_locais_openaccess(doi):
            bytes_pdf = baixar_pdf_bytes(url)
            if bytes_pdf:
                break
    texto = texto_de_pdf_bytes(bytes_pdf) if bytes_pdf else None
    if texto is None and doi:
        # fallback: às vezes o Unpaywall devolve HTML e o texto já tinha sido extraído por URL
        for url in listar_locais_openaccess(doi):
            texto = baixar_texto_pdf(url)
            if texto:
                break
    if texto is None:
        st.warning(
            "Não consegui ler o texto do artigo (editora bloqueou ou PDF escaneado). "
            "Tente enviar o PDF na aba 'Enviar PDF'."
        )
        return

    fonte, ja_existia = garantir_fonte(
        client,
        pesquisador["id"],
        doi=doi,
        pdf_bytes=bytes_pdf,
        nome_arquivo=nome_arquivo,
    )
    st.session_state["fonte_id"] = fonte["id"]
    st.session_state["fonte_titulo"] = fonte.get("titulo") or doi or nome_arquivo
    if ja_existia:
        quem = (fonte.get("pesquisadores") or {}) if isinstance(fonte.get("pesquisadores"), dict) else {}
        nome = quem.get("nome") or "outro pesquisador"
        st.info(
            f"Este artigo já está na base (DOI único). "
            f"PDF e metadados reutilizados. Você pode cadastrar amostras nele. "
            f"Anexado originalmente por {nome}."
        )
    else:
        st.caption("Artigo armazenado no acervo do grupo.")

    registrar_extracao(extrair_campos_com_claude(texto))
    st.rerun()


def secao_extracao_automatica(pesquisador):
    with st.expander("📄 Preencher automaticamente a partir de um artigo", expanded=False):
        tab_doi, tab_upload, tab_orcid = st.tabs(["Colar DOI", "Enviar PDF", "Meus artigos (ORCID)"])

        with tab_doi:
            doi = st.text_input("DOI do artigo", key="doi_input")
            if st.button("Buscar e extrair", key="btn_doi") and doi.strip():
                with st.spinner("Buscando o artigo, guardando o PDF e extraindo os dados..."):
                    try:
                        anexar_e_extrair(pesquisador, doi=doi.strip())
                    except Exception as e:
                        st.error(f"Erro na extração: {e}")

        with tab_upload:
            arquivo = st.file_uploader("PDF do artigo", type="pdf", key="upload_input")
            doi_upload = st.text_input("DOI (se souber)", key="doi_upload")
            if arquivo and st.button("Extrair campos", key="btn_upload"):
                with st.spinner("Armazenando o PDF e extraindo os dados..."):
                    try:
                        anexar_e_extrair(
                            pesquisador,
                            doi=doi_upload.strip() or None,
                            pdf_bytes=arquivo.getvalue(),
                            nome_arquivo=arquivo.name,
                        )
                    except Exception as e:
                        st.error(f"Erro na extração: {e}")

        with tab_orcid:
            if not pesquisador.get("orcid_id"):
                st.info("Seu ORCID iD não foi encontrado no cadastro. Saia e faça login novamente.")
            else:
                if st.button("Carregar meus artigos do ORCID"):
                    with st.spinner("Buscando publicações no ORCID..."):
                        try:
                            token = get_token_orcid_publico()
                            st.session_state["publicacoes_orcid"] = listar_publicacoes_orcid(
                                pesquisador["orcid_id"], token
                            )
                        except Exception as e:
                            st.error(f"Erro ao buscar publicações: {e}")

                publicacoes = st.session_state.get("publicacoes_orcid", [])
                if not publicacoes:
                    st.caption("Clique no botão acima para carregar sua lista de publicações.")
                for i, pub in enumerate(publicacoes):
                    col_t, col_b = st.columns([4, 1])
                    with col_t:
                        titulo = pub["titulo"] or "(sem título)"
                        ano = f" ({pub['ano']})" if pub["ano"] else ""
                        st.write(f"{titulo}{ano}")
                        st.caption(f"DOI: {pub['doi']}" if pub["doi"] else "Sem DOI cadastrado no ORCID")
                    with col_b:
                        if pub["doi"] and st.button("Extrair", key=f"extrair_orcid_{i}"):
                            with st.spinner("Buscando, guardando e extraindo..."):
                                try:
                                    anexar_e_extrair(pesquisador, doi=pub["doi"])
                                except Exception as e:
                                    st.error(f"Erro na extração: {e}")


def campo_num(label: str, valor, fmt: str = "%.2f", minimo: float | None = 0.0, maximo: float | None = None):
    """Number input vazio quando a extração não trouxe valor — não mascara ausência com 0,00."""
    n = _numero_ou_none(valor)
    kwargs = {"label": label, "value": n, "format": fmt, "placeholder": "—"}
    if minimo is not None:
        kwargs["min_value"] = minimo
    if maximo is not None:
        kwargs["max_value"] = maximo
    return st.number_input(**kwargs)


def coletar_campos_material(extraido: dict, pr: dict, rs: dict) -> dict:
    # Sem `key=` nos widgets: com key, o Streamlit guarda o valor antigo na sessão
    # e ignora o `value=` vindo da extração automática.
    cela = aplicar_restricao({
        "a": extraido.get("a") or pr.get("a"),
        "b": extraido.get("b") or pr.get("b"),
        "c": extraido.get("c") or pr.get("c"),
        "alpha": extraido.get("alpha") or pr.get("alpha"),
        "beta": extraido.get("beta") or pr.get("beta"),
        "gamma": extraido.get("gamma") or pr.get("gamma"),
        "sistema_cristalino": extraido.get("sistema_cristalino"),
        "grupo_espacial": extraido.get("grupo_espacial") or pr.get("grupo_espacial"),
    })

    ident, rede, exp = st.columns([1.15, 1, 1.1])
    with ident:
        st.markdown("**Identidade**")
        formula = st.text_input("Fórmula química *", value=extraido.get("formula") or "", placeholder="Bi0.9Nd0.1FeO3")
        nome_comum = st.text_input("Nome comum", value=extraido.get("nome_comum") or "", placeholder="BFO, BTO")
        c1, c2 = st.columns(2)
        with c1:
            sistema_cristalino = st.selectbox(
                "Sistema cristalino",
                SISTEMAS_CRISTALINOS,
                index=idx_selectbox(SISTEMAS_CRISTALINOS, extraido.get("sistema_cristalino")),
            )
        with c2:
            grupo_espacial = st.text_input(
                "Grupo espacial",
                value=extraido.get("grupo_espacial") or "",
                placeholder="R3c, P4mm",
            )
        d1, d2 = st.columns(2)
        with d1:
            dopante = st.text_input("Dopante", value=extraido.get("dopante") or "", placeholder="Sm, Co, Nd")
        with d2:
            percentual_dopagem = campo_num("Dopagem (%)", extraido.get("percentual_dopagem"), "%.2f", 0.0, 100.0)
        site_substituicao = st.selectbox(
            "Sítio de substituição",
            SITES_SUBSTITUICAO,
            index=idx_selectbox(SITES_SUBSTITUICAO, extraido.get("site_substituicao")),
        )
        familia_estrutural = st.text_input(
            "Família estrutural",
            value=extraido.get("familia_estrutural") or "",
            placeholder="Perovskita",
        )
        aplicacao_alvo = st.text_input(
            "Aplicação-alvo",
            value=extraido.get("aplicacao_alvo") or "",
            placeholder="Multiferróico",
        )

    with rede:
        st.markdown("**Cela unitária**")
        a = campo_num("a (Å)", cela.get("a"), "%.4f")
        b = campo_num("b (Å)", cela.get("b"), "%.4f")
        c = campo_num("c (Å)", cela.get("c"), "%.4f")
        alpha = campo_num("α (°)", cela.get("alpha"), "%.2f", 0.0, 180.0)
        beta = campo_num("β (°)", cela.get("beta"), "%.2f", 0.0, 180.0)
        gamma = campo_num("γ (°)", cela.get("gamma"), "%.2f", 0.0, 180.0)

    with exp:
        st.markdown("**Medida e síntese**")
        tecnica_medicao = st.selectbox(
            "Técnica",
            TECNICAS_MEDICAO,
            index=idx_selectbox(TECNICAS_MEDICAO, pr.get("tecnica_medicao")),
        )
        temperatura_c = campo_num(
            "T da medida (°C)",
            para_celsius(pr.get("temperatura_k")),
            "%.1f",
            -273.15,
            3000.0,
        )
        equiv_k = para_kelvin(temperatura_c)
        if equiv_k is not None:
            st.caption(f"{equiv_k:.1f} K")
        metodo_sintese = st.text_input(
            "Método de síntese",
            value=rs.get("metodo") or "",
            placeholder="Sol-gel, Czochralski, estado sólido",
        )
        precursores = st.text_area(
            "Precursores",
            value=rs.get("precursores") or "",
            placeholder="Bi2O3, Nd2O3, Fe2O3",
            height=70,
        )
        atmosfera = st.selectbox(
            "Atmosfera",
            ATMOSFERAS,
            index=idx_selectbox(ATMOSFERAS, rs.get("atmosfera")),
        )

    st.markdown("**Forno**")
    f1, f2, f3, f4, f5, f6 = st.columns(6)
    with f1:
        temp_calcinacao = campo_num("T calcinação (°C)", rs.get("temp_calcinacao"), "%.1f")
    with f2:
        tempo_calcinacao = campo_num("t calcinação (h)", rs.get("tempo_calcinacao"), "%.2f")
    with f3:
        temp_sinterizacao = campo_num("T sinterização (°C)", rs.get("temp_sinterizacao"), "%.1f")
    with f4:
        tempo_sinterizacao = campo_num("t sinterização (h)", rs.get("tempo_sinterizacao"), "%.2f")
    with f5:
        taxa_aquecimento = campo_num("Aquecimento (°C/min)", rs.get("taxa_aquecimento"), "%.2f")
    with f6:
        taxa_resfriamento = campo_num("Resfriamento (°C/min)", rs.get("taxa_resfriamento"), "%.2f")
    observacao = st.text_input(
        "Observação da síntese",
        value=rs.get("observacao") or "",
        placeholder="Fast firing, esfera 140 µm, cristal comercial 99.99%",
    )

    return {
        "formula": formula.strip(),
        "nome_comum": nome_comum.strip() or None,
        "sistema_cristalino": sistema_cristalino,
        "grupo_espacial": grupo_espacial.strip() or None,
        "familia_estrutural": familia_estrutural.strip() or None,
        "aplicacao_alvo": aplicacao_alvo.strip() or None,
        "dopante": dopante.strip() or None,
        "percentual_dopagem": percentual_dopagem,
        "site_substituicao": None if site_substituicao == "Selecione..." else site_substituicao,
        "a": a, "b": b, "c": c,
        "alpha": alpha, "beta": beta, "gamma": gamma,
        "tecnica_medicao": None if tecnica_medicao == "Selecione..." else tecnica_medicao,
        "temperatura_k": para_kelvin(temperatura_c),
        "metodo": metodo_sintese.strip() or None,
        "precursores": precursores.strip() or None,
        "temp_calcinacao": temp_calcinacao,
        "tempo_calcinacao": tempo_calcinacao,
        "temp_sinterizacao": temp_sinterizacao,
        "tempo_sinterizacao": tempo_sinterizacao,
        "taxa_aquecimento": taxa_aquecimento,
        "taxa_resfriamento": taxa_resfriamento,
        "atmosfera": None if atmosfera == "Selecione..." else atmosfera,
        "observacao": observacao.strip() or None,
    }


def validar_campos_material(campos: dict) -> str | None:
    if not campos["formula"]:
        return "A fórmula química é obrigatória."
    if campos["sistema_cristalino"] == "Selecione...":
        return "Selecione o sistema cristalino."
    return None


def dados_tabela_material(pesquisador_id, campos: dict) -> dict:
    return campos


def salvar_material(client, pesquisador_id, campos: dict, medidas: list[dict] | None = None):
    fonte_id = st.session_state.get("fonte_id")
    campos = aplicar_restricao(campos)
    salvar_amostra(client, pesquisador_id, campos, medidas, fonte_id)


def campos_de_extraido(item: dict) -> dict:
    """Achata um material extraído (primeira medida + rota) no formato usado para gravar."""
    medidas = item.get("medidas") or []
    pr = medidas[0] if medidas else {}
    rs = item.get("rota_sintese") or {}
    sistema = item.get("sistema_cristalino") or pr.get("sistema_cristalino")
    tecnica = pr.get("tecnica_medicao")
    atmosfera = rs.get("atmosfera")
    sim = aplicar_restricao({**pr, "sistema_cristalino": sistema, "grupo_espacial": item.get("grupo_espacial") or pr.get("grupo_espacial")})
    return {
        "formula": (item.get("formula") or "").strip(),
        "nome_comum": (item.get("nome_comum") or "").strip() or None,
        "sistema_cristalino": sim.get("sistema_cristalino") if sim.get("sistema_cristalino") in SISTEMAS_CRISTALINOS[1:] else None,
        "grupo_espacial": (item.get("grupo_espacial") or pr.get("grupo_espacial") or "").strip() or None,
        "familia_estrutural": (item.get("familia_estrutural") or "").strip() or None,
        "aplicacao_alvo": (item.get("aplicacao_alvo") or "").strip() or None,
        "dopante": (item.get("dopante") or "").strip() or None,
        "percentual_dopagem": _numero_ou_none(item.get("percentual_dopagem")),
        "x_nominal": _numero_ou_none(item.get("x_nominal")),
        "site_substituicao": item.get("site_substituicao") if item.get("site_substituicao") in SITES_SUBSTITUICAO[1:] else None,
        "a": _numero_ou_none(sim.get("a")),
        "b": _numero_ou_none(sim.get("b")),
        "c": _numero_ou_none(sim.get("c")),
        "alpha": _numero_ou_none(sim.get("alpha")),
        "beta": _numero_ou_none(sim.get("beta")),
        "gamma": _numero_ou_none(sim.get("gamma")),
        "tecnica_medicao": tecnica if tecnica in TECNICAS_MEDICAO[1:] else None,
        "temperatura_k": temperatura_medida_para_k(pr),
        "metodo": (rs.get("metodo") or "").strip() or None,
        "precursores": (rs.get("precursores") or "").strip() or None,
        "temp_calcinacao": _numero_ou_none(rs.get("temp_calcinacao")),
        "tempo_calcinacao": _numero_ou_none(rs.get("tempo_calcinacao")),
        "temp_sinterizacao": _numero_ou_none(rs.get("temp_sinterizacao")),
        "tempo_sinterizacao": _numero_ou_none(rs.get("tempo_sinterizacao")),
        "taxa_aquecimento": _numero_ou_none(rs.get("taxa_aquecimento")),
        "taxa_resfriamento": _numero_ou_none(rs.get("taxa_resfriamento")),
        "atmosfera": atmosfera if atmosfera in ATMOSFERAS[1:] else None,
        "observacao": (rs.get("observacao") or "").strip() or None,
    }


def resumo_medidas(medidas: list[dict]) -> list[dict]:
    return [
        {
            "Condição": m.get("condicao") or "—",
            "T (°C)": para_celsius(m.get("temperatura_k")),
            "T (K)": m.get("temperatura_k"),
            "Sistema": m.get("sistema_cristalino"),
            "Grupo": m.get("grupo_espacial"),
            "a (Å)": m.get("a"),
            "b (Å)": m.get("b"),
            "c (Å)": m.get("c"),
        }
        for m in medidas
    ]


def rotulo_extraido(i: int, item: dict) -> str:
    partes = [item.get("formula") or "(sem fórmula)"]
    if item.get("dopante") and item.get("percentual_dopagem") is not None:
        partes.append(f"{item['dopante']} {item['percentual_dopagem']}%")
    medidas = item.get("medidas") or []
    partes.append(f"{len(medidas)} medida(s)" if medidas else "sem medidas")
    return f"{i + 1}. " + " — ".join(partes)


def secao_extraidos() -> tuple[int, dict]:
    """Mostra o que foi extraído do artigo e devolve (índice, material) escolhido para o formulário."""
    extraidos = st.session_state.get("extraidos") or []
    if not extraidos:
        return -1, {}

    col_info, col_limpar = st.columns([4, 1])
    with col_info:
        st.info(
            f"{len(extraidos)} material(is) extraído(s) do artigo — revise antes de salvar."
        )
    with col_limpar:
        if st.button("Limpar"):
            del st.session_state["extraidos"]
            st.rerun()

    indice = 0
    if len(extraidos) > 1:
        rotulos = [rotulo_extraido(i, m) for i, m in enumerate(extraidos)]
        escolha = st.selectbox("Material do artigo a revisar", rotulos)
        indice = rotulos.index(escolha)
    atual = extraidos[indice]

    medidas = atual.get("medidas") or []
    if len(medidas) > 1:
        st.caption(
            f"Este material tem {len(medidas)} medidas. O formulário mostra a primeira; "
            "ao salvar, todas são gravadas."
        )
        st.dataframe(resumo_medidas(medidas), hide_index=True, width="stretch")

    return indice, atual


def salvar_todos_extraidos(client, pesquisador):
    extraidos = st.session_state.get("extraidos") or []
    if not extraidos:
        return
    total_medidas = sum(len(m.get("medidas") or []) for m in extraidos)
    if not st.button(
        f"Salvar os {len(extraidos)} materiais do artigo ({total_medidas} medidas)",
        type="primary",
    ):
        return

    salvos, pulados, falhas = 0, [], []
    for item in extraidos:
        campos = campos_de_extraido(item)
        if not campos["formula"]:
            falhas.append("material sem fórmula")
            continue
        if not (item.get("medidas") or item.get("rota_sintese")):
            pulados.append(campos["formula"])
            continue
        try:
            salvar_material(client, pesquisador["id"], campos, item.get("medidas"))
            salvos += 1
        except Exception as e:
            falhas.append(f"{campos['formula']}: {e}")

    if pulados:
        st.info(
            "Sem dados para registrar (só a fórmula, provavelmente citação do artigo): "
            + ", ".join(pulados)
        )
    for erro in falhas:
        st.error(f"Não salvei — {erro}")
    if salvos:
        st.success(f"{salvos} material(is) salvo(s).")
        del st.session_state["extraidos"]
        st.rerun()


def _como_dict(valor) -> dict:
    if isinstance(valor, list):
        return valor[0] if valor else {}
    return valor or {}


def _como_lista(valor) -> list:
    if valor is None:
        return []
    if isinstance(valor, dict):
        return [valor]
    return list(valor)


def rotulo_artigo(fonte: dict) -> str:
    if fonte.get("doi"):
        return fonte["doi"]
    if fonte.get("arquivo_nome_original"):
        return fonte["arquivo_nome_original"]
    if fonte.get("titulo"):
        return fonte["titulo"]
    return "—"


def url_assinada_pdf(client, caminho: str | None) -> str | None:
    if not caminho:
        return None
    try:
        resp = client.storage.from_("artigos").create_signed_url(caminho, 3600)
        return resp.get("signedURL") or resp.get("signedUrl")
    except Exception:
        return None


def listar_materiais(client) -> list[dict]:
    try:
        resp = (
            client.table("amostras")
            .select(
                "id, rotulo, criado_em, inserido_por, "
                "composicoes(formula, nome_comum, dopante, percentual_dopagem), "
                "pesquisadores(nome, email), "
                "fontes(doi, titulo, arquivo_path, arquivo_nome_original), "
                "medidas_estruturais(condicao, temperatura_k, sistema_cristalino, "
                "grupo_espacial_hm, a, b, c, tecnica_medicao)"
            )
            .order("criado_em", desc=True)
            .execute()
        )
        dados = resp.data or []
    except Exception:
        resp = (
            client.table("amostras")
            .select("id, rotulo, criado_em, composicao_id, inserido_por, fonte_id")
            .order("criado_em", desc=True)
            .execute()
        )
        dados = resp.data or []
        linhas = []
        for m in dados:
            linhas.append({
                "id": m["id"],
                "formula": m.get("rotulo"),
                "nome_comum": None,
                "sistema_cristalino": None,
                "grupo_espacial": None,
                "n_medidas": 0,
                "doi": None,
                "artigo": "—",
                "pdf": False,
                "arquivo_path": None,
                "medidas": [],
                "criado_em": m.get("criado_em"),
                "pesquisador": "—",
            })
        return linhas
    linhas = []
    for m in dados:
        comp = _como_dict(m.get("composicoes"))
        pesq = _como_dict(m.get("pesquisadores"))
        fonte = _como_dict(m.get("fontes"))
        medidas = _como_lista(m.get("medidas_estruturais"))
        medidas = sorted(
            medidas,
            key=lambda x: (x.get("temperatura_k") is None, x.get("temperatura_k") or 0),
        )
        primeira = medidas[0] if medidas else {}
        linhas.append({
            "id": m["id"],
            "formula": (comp or {}).get("formula") or m.get("rotulo"),
            "nome_comum": (comp or {}).get("nome_comum"),
            "sistema_cristalino": primeira.get("sistema_cristalino"),
            "grupo_espacial": primeira.get("grupo_espacial_hm"),
            "n_medidas": len(medidas),
            "doi": fonte.get("doi"),
            "artigo": rotulo_artigo(fonte),
            "pdf": bool(fonte.get("arquivo_path")),
            "arquivo_path": fonte.get("arquivo_path"),
            "medidas": medidas,
            "criado_em": m.get("criado_em"),
            "pesquisador": pesq.get("nome") or pesq.get("email") or "—",
        })
    return linhas


def secao_acervo(client):
    st.subheader("Materiais cadastrados")
    try:
        linhas = listar_materiais(client)
    except Exception as e:
        st.warning(f"Não consegui listar os materiais no Supabase: {e}")
        return

    if not linhas:
        st.info("Nenhum material cadastrado ainda.")
        return

    col_f, col_s, col_p = st.columns(3)
    with col_f:
        termo = st.text_input("Buscar fórmula / nome / grupo", key="filtro_texto")
    with col_s:
        sistemas = ["Todos"] + sorted({m.get("sistema_cristalino") for m in linhas if m.get("sistema_cristalino")})
        sistema = st.selectbox("Sistema cristalino", sistemas, key="filtro_sistema")
    with col_p:
        autores = ["Todos"] + sorted({m.get("pesquisador") for m in linhas if m.get("pesquisador") and m.get("pesquisador") != "—"})
        autor = st.selectbox("Pesquisador", autores, key="filtro_pesquisador")

    filtradas = linhas
    if termo.strip():
        q = termo.strip().lower()
        filtradas = [
            m for m in filtradas
            if q in (m.get("formula") or "").lower()
            or q in (m.get("nome_comum") or "").lower()
            or q in (m.get("grupo_espacial") or "").lower()
            or q in (m.get("artigo") or "").lower()
        ]
    if sistema != "Todos":
        filtradas = [m for m in filtradas if m.get("sistema_cristalino") == sistema]
    if autor != "Todos":
        filtradas = [m for m in filtradas if m.get("pesquisador") == autor]

    st.caption(f"{len(filtradas)} de {len(linhas)} material(is)")
    visivel = [
        {
            "Fórmula": m.get("formula"),
            "Nome": m.get("nome_comum") or "—",
            "Sistema": m.get("sistema_cristalino") or "—",
            "Grupo": m.get("grupo_espacial") or "—",
            "Medidas": m.get("n_medidas") or 0,
            "Artigo": m.get("artigo") or "—",
            "PDF": "sim" if m.get("pdf") else "não",
            "Pesquisador": m.get("pesquisador"),
            "Criado em": formatar_criado_em(m.get("criado_em")),
        }
        for m in filtradas
    ]
    st.dataframe(visivel, hide_index=True, width="stretch")

    if not filtradas:
        return

    rotulos = [
        f"{m.get('formula')} — {m.get('n_medidas') or 0} medida(s) — {m.get('artigo')}"
        for m in filtradas
    ]
    escolha = st.selectbox("Ver medidas de", rotulos, key="acervo_detalhe")
    atual = filtradas[rotulos.index(escolha)]
    medidas = atual.get("medidas") or []

    col_info, col_pdf = st.columns([3, 1])
    with col_info:
        st.caption(
            f"{atual.get('formula')} · {atual.get('nome_comum') or 'sem nome comum'} · "
            f"{'PDF no Storage' if atual.get('pdf') else 'sem PDF'}"
        )
    with col_pdf:
        url = url_assinada_pdf(client, atual.get("arquivo_path")) if atual.get("pdf") else None
        if url:
            st.link_button("Abrir PDF", url)

    if not medidas:
        st.info("Esta amostra não tem parâmetros de rede gravados (só fórmula/citação).")
        return

    st.dataframe(
        [
            {
                "Condição": m.get("condicao") or "—",
                "T (°C)": para_celsius(m.get("temperatura_k")),
                "T (K)": m.get("temperatura_k"),
                "Sistema": m.get("sistema_cristalino") or "—",
                "Grupo": m.get("grupo_espacial_hm") or "—",
                "a (Å)": m.get("a"),
                "b (Å)": m.get("b"),
                "c (Å)": m.get("c"),
                "Técnica": m.get("tecnica_medicao") or "—",
            }
            for m in medidas
        ],
        hide_index=True,
        width="stretch",
    )


def formulario_material(pesquisador):
    st.title("🧪 Rede de Materiais")
    col_a, col_b = st.columns([4, 1])
    with col_a:
        st.caption(f"Logado como {pesquisador['nome'] or pesquisador['email'] or 'pesquisador'}")
        if st.session_state.get("fonte_titulo"):
            st.caption(f"Artigo anexado: {st.session_state['fonte_titulo']}")
    with col_b:
        if st.button("Sair"):
            encerrar_sessao()
            st.session_state.clear()
            st.rerun()

    st.divider()
    st.subheader("Cadastrar amostra")

    secao_extracao_automatica(pesquisador)

    indice, extraido = secao_extraidos()
    medidas = extraido.get("medidas") or []
    pr = medidas[0] if medidas else {}
    rs = extraido.get("rota_sintese") or {}
    if extraido:
        # Sistema e grupo às vezes vêm só na medida; o formulário mostra o que existir.
        extraido = {
            **extraido,
            "sistema_cristalino": extraido.get("sistema_cristalino") or pr.get("sistema_cristalino"),
            "grupo_espacial": extraido.get("grupo_espacial") or pr.get("grupo_espacial"),
        }

    client = cliente_da_sessao()
    if client is None:
        st.warning("Sessão inválida. Entre novamente com o ORCID.")
        return

    if len(st.session_state.get("extraidos") or []) > 1:
        salvar_todos_extraidos(client, pesquisador)

    with st.form("form_material", clear_on_submit=True):
        campos = coletar_campos_material(extraido, pr, rs)
        enviado = st.form_submit_button("Salvar material")

        if enviado:
            erro = validar_campos_material(campos)
            if erro:
                st.error(erro)
                return
            try:
                salvar_material(client, pesquisador["id"], campos, medidas)
            except Exception as e:
                st.error(f"Erro ao salvar no Supabase: {e}")
                return

            restantes = list(st.session_state.get("extraidos") or [])
            if 0 <= indice < len(restantes):
                restantes.pop(indice)
            if restantes:
                st.session_state["extraidos"] = restantes
            else:
                st.session_state.pop("extraidos", None)
            st.success(f"Amostra '{campos['formula']}' salva com sucesso!")
            st.rerun()

    st.divider()
    secao_acervo(client)


# ---------- Roteamento principal ----------

if supabase is None:
    cabecalho_institucional()
    st.title("🧪 Rede de Materiais")
    st.error(
        "Não foi possível conectar ao Supabase. "
        "Confira SUPABASE_URL e SUPABASE_ANON_KEY no .env (local) "
        "ou nos secrets do Streamlit Cloud."
    )
    st.stop()

if processar_callback():
    st.stop()

if "access_token" in st.session_state:
    pesquisador = get_pesquisador_logado()
    if pesquisador and pesquisador.get("aprovado") is False:
        cabecalho_institucional()
        st.title("🧪 Rede de Materiais")
        st.info(
            "Sua conta foi criada e aguarda aprovação. "
            "Quando for liberada, você poderá cadastrar amostras."
        )
        if st.button("Sair"):
            encerrar_sessao()
            st.rerun()
    elif pesquisador:
        formulario_material(pesquisador)
    else:
        st.warning("Sessão expirada ou inválida. Entre novamente com o ORCID.")
        fazer_login()
else:
    fazer_login()

