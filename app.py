import os
from urllib.parse import urlencode, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

import streamlit as st
from supabase import create_client, ClientOptions
from supabase_auth.helpers import generate_pkce_challenge, generate_pkce_verifier

from extracao import (
    listar_locais_openaccess,
    baixar_texto_pdf,
    texto_de_pdf_bytes,
    extrair_campos_com_claude,
    obter_token_publico_orcid,
    listar_publicacoes_orcid,
)

SISTEMAS_CRISTALINOS = ["Selecione...", "Cúbico", "Tetragonal", "Ortorrômbico", "Romboédrico",
                         "Hexagonal", "Monoclínico", "Triclínico"]
TECNICAS_MEDICAO = ["Selecione...", "DRX laboratório (Cu Kα)", "Síncrotron", "Nêutrons", "Outra"]
ATMOSFERAS = ["Selecione...", "Ar", "O2", "N2", "Vácuo"]


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


st.set_page_config(page_title="Rede de Materiais", page_icon="🧪", layout="centered")

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
    materiais = [m for m in (materiais or []) if isinstance(m, dict)]
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

        supabase.table("professores").upsert(
            {
                "user_id": result.user.id,
                "email": result.user.email or None,
                "nome": nome,
                "orcid_id": (result.user.user_metadata or {}).get("sub"),
            },
            on_conflict="user_id",
        ).execute()

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
    st.session_state.pop("publicacoes_orcid", None)


def get_professor_logado():
    try:
        client = cliente_da_sessao()
        if client is None:
            encerrar_sessao()
            return None
        user = client.auth.get_user().user
        if not user:
            encerrar_sessao()
            return None
        professor = (
            client.table("professores")
            .select("id, nome, email, orcid_id, aprovado")
            .eq("user_id", user.id)
            .single()
            .execute()
        )
        return professor.data
    except Exception:
        encerrar_sessao()
        return None


def executar_extracao_por_doi(doi):
    urls = listar_locais_openaccess(doi)
    texto = None
    for url in urls:
        texto = baixar_texto_pdf(url)
        if texto:
            break
    if texto is None:
        st.warning(
            "Não consegui acessar o texto completo automaticamente "
            "(provável bloqueio da editora). Tente enviar o PDF na aba 'Enviar PDF'."
        )
        return
    registrar_extracao(extrair_campos_com_claude(texto))
    st.rerun()


def secao_extracao_automatica(professor):
    with st.expander("📄 Preencher automaticamente a partir de um artigo", expanded=False):
        tab_doi, tab_upload, tab_orcid = st.tabs(["Colar DOI", "Enviar PDF", "Meus artigos (ORCID)"])

        with tab_doi:
            doi = st.text_input("DOI do artigo", key="doi_input")
            if st.button("Buscar e extrair", key="btn_doi") and doi.strip():
                with st.spinner("Buscando o artigo e extraindo os dados..."):
                    try:
                        executar_extracao_por_doi(doi)
                    except Exception as e:
                        st.error(f"Erro na extração: {e}")

        with tab_upload:
            arquivo = st.file_uploader("PDF do artigo", type="pdf", key="upload_input")
            if arquivo and st.button("Extrair campos", key="btn_upload"):
                with st.spinner("Extraindo os dados do PDF..."):
                    try:
                        texto = texto_de_pdf_bytes(arquivo.read())
                        if texto is None:
                            st.warning("Não consegui ler texto desse PDF (pode ser um PDF escaneado).")
                        else:
                            registrar_extracao(extrair_campos_com_claude(texto))
                            st.rerun()
                    except Exception as e:
                        st.error(f"Erro na extração: {e}")

        with tab_orcid:
            if not professor.get("orcid_id"):
                st.info("Seu ORCID iD não foi encontrado no cadastro. Saia e faça login novamente.")
            else:
                if st.button("Carregar meus artigos do ORCID"):
                    with st.spinner("Buscando publicações no ORCID..."):
                        try:
                            token = get_token_orcid_publico()
                            st.session_state["publicacoes_orcid"] = listar_publicacoes_orcid(
                                professor["orcid_id"], token
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
                            with st.spinner("Buscando e extraindo..."):
                                try:
                                    executar_extracao_por_doi(pub["doi"])
                                except Exception as e:
                                    st.error(f"Erro na extração: {e}")


def coletar_campos_material(extraido: dict, pr: dict, rs: dict) -> dict:
    # Sem `key=` nos widgets: com key, o Streamlit guarda o valor antigo na sessão
    # e ignora o `value=` vindo da extração automática.
    st.markdown("**Dados essenciais**")
    col1, col2 = st.columns(2)
    with col1:
        formula = st.text_input(
            "Fórmula química *",
            value=extraido.get("formula") or "",
            placeholder="Ex: Bi0.9Nd0.1FeO3",
        )
        nome_comum = st.text_input(
            "Nome comum (opcional)",
            value=extraido.get("nome_comum") or "",
        )
        sistema_cristalino = st.selectbox(
            "Sistema cristalino",
            SISTEMAS_CRISTALINOS,
            index=idx_selectbox(SISTEMAS_CRISTALINOS, extraido.get("sistema_cristalino")),
        )
        grupo_espacial = st.text_input(
            "Grupo espacial",
            value=extraido.get("grupo_espacial") or "",
            placeholder="Ex: R3c",
        )
    with col2:
        a = st.number_input("a (Å)", min_value=0.0, value=_numero(pr.get("a")), format="%.4f")
        b = st.number_input("b (Å)", min_value=0.0, value=_numero(pr.get("b")), format="%.4f")
        c = st.number_input("c (Å)", min_value=0.0, value=_numero(pr.get("c")), format="%.4f")
        alpha = st.number_input("α (°)", min_value=0.0, max_value=180.0, value=_numero(pr.get("alpha"), 90.0), format="%.2f")
        beta = st.number_input("β (°)", min_value=0.0, max_value=180.0, value=_numero(pr.get("beta"), 90.0), format="%.2f")
        gamma = st.number_input("γ (°)", min_value=0.0, max_value=180.0, value=_numero(pr.get("gamma"), 90.0), format="%.2f")

    tecnica_medicao = st.selectbox(
        "Técnica de medição dos parâmetros de rede",
        TECNICAS_MEDICAO,
        index=idx_selectbox(TECNICAS_MEDICAO, pr.get("tecnica_medicao")),
    )
    metodo_sintese = st.text_input(
        "Rota de síntese (resumo)",
        value=rs.get("metodo") or "",
        placeholder="Ex: Reação de estado sólido",
    )

    with st.expander("+ Mais detalhes do material"):
        familia_estrutural = st.text_input(
            "Família estrutural",
            value=extraido.get("familia_estrutural") or "",
            placeholder="Ex: Perovskita",
        )
        aplicacao_alvo = st.text_input(
            "Aplicação-alvo",
            value=extraido.get("aplicacao_alvo") or "",
            placeholder="Ex: Multiferróico",
        )
        col3, col4 = st.columns(2)
        with col3:
            dopante = st.text_input("Dopante", value=extraido.get("dopante") or "", placeholder="Ex: Nd")
        with col4:
            percentual_dopagem = st.number_input(
                "Percentual de dopagem (%)",
                min_value=0.0,
                max_value=100.0,
                value=_numero(extraido.get("percentual_dopagem")),
                format="%.2f",
            )

    with st.expander("+ Mais detalhes da síntese"):
        precursores = st.text_area(
            "Precursores",
            value=rs.get("precursores") or "",
            placeholder="Ex: Bi2O3, Nd2O3, Fe2O3",
        )
        col5, col6 = st.columns(2)
        with col5:
            temp_calcinacao = st.number_input(
                "Temperatura de calcinação (°C)", min_value=0.0,
                value=_numero(rs.get("temp_calcinacao")), format="%.1f",
            )
            taxa_aquecimento = st.number_input(
                "Taxa de aquecimento (°C/min)", min_value=0.0,
                value=_numero(rs.get("taxa_aquecimento")), format="%.2f",
            )
            atmosfera = st.selectbox(
                "Atmosfera", ATMOSFERAS,
                index=idx_selectbox(ATMOSFERAS, rs.get("atmosfera")),
            )
        with col6:
            tempo_calcinacao = st.number_input(
                "Tempo de calcinação (h)", min_value=0.0,
                value=_numero(rs.get("tempo_calcinacao")), format="%.1f",
            )
            taxa_resfriamento = st.number_input(
                "Taxa de resfriamento (°C/min)", min_value=0.0,
                value=_numero(rs.get("taxa_resfriamento")), format="%.2f",
            )

    return {
        "formula": formula.strip(),
        "nome_comum": nome_comum.strip() or None,
        "sistema_cristalino": sistema_cristalino,
        "grupo_espacial": grupo_espacial.strip() or None,
        "familia_estrutural": familia_estrutural.strip() or None,
        "aplicacao_alvo": aplicacao_alvo.strip() or None,
        "dopante": dopante.strip() or None,
        "percentual_dopagem": percentual_dopagem or None,
        "a": a or None, "b": b or None, "c": c or None,
        "alpha": alpha, "beta": beta, "gamma": gamma,
        "tecnica_medicao": None if tecnica_medicao == "Selecione..." else tecnica_medicao,
        "metodo": metodo_sintese.strip() or None,
        "precursores": precursores.strip() or None,
        "temp_calcinacao": temp_calcinacao or None,
        "tempo_calcinacao": tempo_calcinacao or None,
        "taxa_aquecimento": taxa_aquecimento or None,
        "taxa_resfriamento": taxa_resfriamento or None,
        "atmosfera": None if atmosfera == "Selecione..." else atmosfera,
    }


def validar_campos_material(campos: dict) -> str | None:
    if not campos["formula"]:
        return "A fórmula química é obrigatória."
    if campos["sistema_cristalino"] == "Selecione...":
        return "Selecione o sistema cristalino."
    return None


def dados_tabela_material(professor_id, campos: dict) -> dict:
    return {
        "professor_id": professor_id,
        "formula": campos["formula"],
        "nome_comum": campos["nome_comum"],
        "sistema_cristalino": campos["sistema_cristalino"],
        "grupo_espacial": campos["grupo_espacial"],
        "familia_estrutural": campos["familia_estrutural"],
        "aplicacao_alvo": campos["aplicacao_alvo"],
        "dopante": campos["dopante"],
        "percentual_dopagem": campos["percentual_dopagem"],
    }


COLUNAS_CONDICAO = ("condicao", "temperatura_k")


def inserir_parametros_rede(client, linhas: list[dict]):
    """Grava as medidas. Se o banco ainda não tem as colunas de condição, regrava sem elas."""
    if not linhas:
        return
    try:
        client.table("parametros_rede").insert(linhas).execute()
    except Exception:
        simples = [
            {k: v for k, v in linha.items() if k not in COLUNAS_CONDICAO}
            for linha in linhas
        ]
        client.table("parametros_rede").insert(simples).execute()


def linha_de_medida(material_id, medida: dict) -> dict | None:
    a = _numero_ou_none(medida.get("a"))
    b = _numero_ou_none(medida.get("b"))
    c = _numero_ou_none(medida.get("c"))
    if not (a or b or c):
        return None
    tecnica = medida.get("tecnica_medicao")
    return {
        "material_id": material_id,
        "a": a, "b": b, "c": c,
        "alpha": _numero_ou_none(medida.get("alpha")),
        "beta": _numero_ou_none(medida.get("beta")),
        "gamma": _numero_ou_none(medida.get("gamma")),
        "tecnica_medicao": tecnica if tecnica in TECNICAS_MEDICAO[1:] else None,
        "condicao": medida.get("condicao") or None,
        "temperatura_k": _numero_ou_none(medida.get("temperatura_k")),
    }


def gravar_filhos_material(client, material_id, campos: dict, medidas: list[dict] | None = None):
    medidas = list(medidas or [])
    linhas = []

    if campos["a"] or campos["b"] or campos["c"]:
        principal = {
            "material_id": material_id,
            "a": campos["a"], "b": campos["b"], "c": campos["c"],
            "alpha": campos["alpha"], "beta": campos["beta"], "gamma": campos["gamma"],
            "tecnica_medicao": campos["tecnica_medicao"],
            "condicao": (medidas[0].get("condicao") if medidas else None) or None,
            "temperatura_k": _numero_ou_none(medidas[0].get("temperatura_k")) if medidas else None,
        }
        linhas.append(principal)

    # A primeira medida já foi para o formulário; as demais entram como estavam no artigo.
    for medida in medidas[1:]:
        linha = linha_de_medida(material_id, medida)
        if linha:
            linhas.append(linha)

    inserir_parametros_rede(client, linhas)

    rota = {
        "metodo": campos["metodo"],
        "precursores": campos["precursores"],
        "temp_calcinacao": campos["temp_calcinacao"],
        "tempo_calcinacao": campos["tempo_calcinacao"],
        "taxa_aquecimento": campos["taxa_aquecimento"],
        "taxa_resfriamento": campos["taxa_resfriamento"],
        "atmosfera": campos["atmosfera"],
    }
    existente_rs = (
        client.table("rota_sintese").select("id").eq("material_id", material_id).limit(1).execute()
    )
    tem_rota = campos["metodo"] or campos["precursores"]
    if tem_rota or existente_rs.data:
        if existente_rs.data:
            client.table("rota_sintese").update(rota).eq("id", existente_rs.data[0]["id"]).execute()
        elif tem_rota:
            client.table("rota_sintese").insert({"material_id": material_id, **rota}).execute()


def campos_de_extraido(item: dict) -> dict:
    """Achata um material extraído (primeira medida + rota) no formato usado para gravar."""
    medidas = item.get("medidas") or []
    pr = medidas[0] if medidas else {}
    rs = item.get("rota_sintese") or {}
    sistema = item.get("sistema_cristalino") or pr.get("sistema_cristalino")
    tecnica = pr.get("tecnica_medicao")
    atmosfera = rs.get("atmosfera")
    return {
        "formula": (item.get("formula") or "").strip(),
        "nome_comum": (item.get("nome_comum") or "").strip() or None,
        "sistema_cristalino": sistema if sistema in SISTEMAS_CRISTALINOS[1:] else None,
        "grupo_espacial": (item.get("grupo_espacial") or pr.get("grupo_espacial") or "").strip() or None,
        "familia_estrutural": (item.get("familia_estrutural") or "").strip() or None,
        "aplicacao_alvo": (item.get("aplicacao_alvo") or "").strip() or None,
        "dopante": (item.get("dopante") or "").strip() or None,
        "percentual_dopagem": _numero_ou_none(item.get("percentual_dopagem")),
        "a": _numero_ou_none(pr.get("a")),
        "b": _numero_ou_none(pr.get("b")),
        "c": _numero_ou_none(pr.get("c")),
        "alpha": _numero_ou_none(pr.get("alpha")),
        "beta": _numero_ou_none(pr.get("beta")),
        "gamma": _numero_ou_none(pr.get("gamma")),
        "tecnica_medicao": tecnica if tecnica in TECNICAS_MEDICAO[1:] else None,
        "metodo": (rs.get("metodo") or "").strip() or None,
        "precursores": (rs.get("precursores") or "").strip() or None,
        "temp_calcinacao": _numero_ou_none(rs.get("temp_calcinacao")),
        "tempo_calcinacao": _numero_ou_none(rs.get("tempo_calcinacao")),
        "taxa_aquecimento": _numero_ou_none(rs.get("taxa_aquecimento")),
        "taxa_resfriamento": _numero_ou_none(rs.get("taxa_resfriamento")),
        "atmosfera": atmosfera if atmosfera in ATMOSFERAS[1:] else None,
    }


def salvar_material(client, professor_id, campos: dict, medidas: list[dict] | None = None):
    material = client.table("materiais").insert(
        dados_tabela_material(professor_id, campos)
    ).execute()
    gravar_filhos_material(client, material.data[0]["id"], campos, medidas)


def resumo_medidas(medidas: list[dict]) -> list[dict]:
    return [
        {
            "Condição": m.get("condicao") or "—",
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


def salvar_todos_extraidos(client, professor):
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
            # Composto apenas citado no artigo: só a fórmula, nada a registrar.
            pulados.append(campos["formula"])
            continue
        try:
            salvar_material(client, professor["id"], campos, item.get("medidas"))
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


def listar_materiais(client) -> list[dict]:
    try:
        resp = (
            client.table("materiais")
            .select(
                "id, professor_id, formula, nome_comum, sistema_cristalino, "
                "grupo_espacial, criado_em, professores(nome, email)"
            )
            .order("criado_em", desc=True)
            .execute()
        )
        linhas = []
        for m in resp.data or []:
            prof = m.get("professores") or {}
            if isinstance(prof, list):
                prof = prof[0] if prof else {}
            linhas.append({
                "id": m["id"],
                "professor_id": m["professor_id"],
                "formula": m.get("formula"),
                "nome_comum": m.get("nome_comum"),
                "sistema_cristalino": m.get("sistema_cristalino"),
                "grupo_espacial": m.get("grupo_espacial"),
                "criado_em": m.get("criado_em"),
                "professor": (prof or {}).get("nome") or (prof or {}).get("email") or "—",
            })
        return linhas
    except Exception:
        resp = (
            client.table("materiais")
            .select("id, professor_id, formula, nome_comum, sistema_cristalino, grupo_espacial, criado_em")
            .order("criado_em", desc=True)
            .execute()
        )
        return [{**m, "professor": "—"} for m in (resp.data or [])]


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
        professores = ["Todos"] + sorted({m.get("professor") for m in linhas if m.get("professor") and m.get("professor") != "—"})
        autor = st.selectbox("Professor", professores, key="filtro_professor")

    filtradas = linhas
    if termo.strip():
        q = termo.strip().lower()
        filtradas = [
            m for m in filtradas
            if q in (m.get("formula") or "").lower()
            or q in (m.get("nome_comum") or "").lower()
            or q in (m.get("grupo_espacial") or "").lower()
        ]
    if sistema != "Todos":
        filtradas = [m for m in filtradas if m.get("sistema_cristalino") == sistema]
    if autor != "Todos":
        filtradas = [m for m in filtradas if m.get("professor") == autor]

    st.caption(f"{len(filtradas)} de {len(linhas)} material(is)")
    visivel = [
        {
            "Fórmula": m.get("formula"),
            "Nome": m.get("nome_comum"),
            "Sistema": m.get("sistema_cristalino"),
            "Grupo": m.get("grupo_espacial"),
            "Professor": m.get("professor"),
            "Criado em": m.get("criado_em"),
        }
        for m in filtradas
    ]
    st.dataframe(visivel, hide_index=True, width="stretch")


def formulario_material(professor):
    st.title("🧪 Rede de Materiais")
    col_a, col_b = st.columns([4, 1])
    with col_a:
        st.caption(f"Logado como {professor['nome'] or professor['email'] or 'professor'}")
    with col_b:
        if st.button("Sair"):
            encerrar_sessao()
            st.session_state.clear()
            st.rerun()

    st.divider()
    st.subheader("Cadastrar material")

    secao_extracao_automatica(professor)

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
        salvar_todos_extraidos(client, professor)

    with st.form("form_material", clear_on_submit=True):
        campos = coletar_campos_material(extraido, pr, rs)
        enviado = st.form_submit_button("Salvar material")

        if enviado:
            erro = validar_campos_material(campos)
            if erro:
                st.error(erro)
                return
            try:
                salvar_material(client, professor["id"], campos, medidas)
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
            st.success(f"Material '{campos['formula']}' salvo com sucesso!")
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
    professor = get_professor_logado()
    if professor and professor.get("aprovado") is False:
        cabecalho_institucional()
        st.title("🧪 Rede de Materiais")
        st.info(
            "Sua conta foi criada e aguarda aprovação. "
            "Quando for liberada, você poderá cadastrar materiais."
        )
        if st.button("Sair"):
            encerrar_sessao()
            st.rerun()
    elif professor:
        formulario_material(professor)
    else:
        st.warning("Sessão expirada ou inválida. Entre novamente com o ORCID.")
        fazer_login()
else:
    fazer_login()

