import os

from dotenv import load_dotenv

load_dotenv()

import streamlit as st
from supabase import create_client, ClientOptions

from extracao import (
    listar_locais_openaccess,
    baixar_texto_pdf,
    texto_de_pdf_bytes,
    extrair_campos_com_claude,
    obter_token_publico_orcid,
    listar_publicacoes_orcid,
)

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
# Local usa localhost por padrão; no Streamlit Cloud, definimos REDIRECT_URL
# nos secrets apontando para a URL pública do app.
REDIRECT_URL = os.environ.get("REDIRECT_URL", "http://localhost:8502")

SISTEMAS_CRISTALINOS = ["Selecione...", "Cúbico", "Tetragonal", "Ortorrômbico", "Romboédrico",
                         "Hexagonal", "Monoclínico", "Triclínico"]
TECNICAS_MEDICAO = ["Selecione...", "DRX laboratório (Cu Kα)", "Síncrotron", "Nêutrons", "Outra"]
ATMOSFERAS = ["Selecione...", "Ar", "O2", "N2", "Vácuo"]


@st.cache_resource
def get_supabase_client():
    return create_client(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        options=ClientOptions(flow_type="pkce"),
    )


@st.cache_resource
def get_token_orcid_publico():
    # Token de leitura pública do ORCID: não é específico de nenhum professor,
    # então é seguro compartilhar entre todas as sessões via cache_resource.
    return obter_token_publico_orcid()


supabase = get_supabase_client()

st.set_page_config(page_title="Rede de Materiais", page_icon="🧪", layout="centered")


def idx_selectbox(opcoes, valor):
    if valor and valor in opcoes:
        return opcoes.index(valor)
    return 0


def cabecalho_institucional():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("assets/logo_gddm.png", use_container_width=True)

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

    if "auth_url" not in st.session_state:
        auth_url, _ = supabase.auth._get_url_for_provider(
            f"{supabase.auth._url}/authorize",
            "custom:orcid",
            {"redirect_to": REDIRECT_URL},
        )
        st.session_state["auth_url"] = auth_url

    st.link_button("Entrar com ORCID", st.session_state["auth_url"])


def processar_callback():
    code = st.query_params.get("code")
    if not code:
        return False

    try:
        result = supabase.auth.exchange_code_for_session({"auth_code": code})
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


def get_professor_logado():
    supabase.auth.set_session(
        st.session_state["access_token"],
        st.session_state["refresh_token"],
    )
    user = supabase.auth.get_user().user
    professor = (
        supabase.table("professores")
        .select("id, nome, email, orcid_id")
        .eq("user_id", user.id)
        .single()
        .execute()
    )
    professor = (
        supabase.table("professores")
        .select("id, nome, email, orcid_id, aprovado")
        .eq("user_id", user.id)
        .single()
        .execute()
    )
    return professor.data


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
    st.session_state["extraido"] = extrair_campos_com_claude(texto)
    st.success("Dados extraídos! Revise no formulário abaixo antes de salvar.")
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
                            st.session_state["extraido"] = extrair_campos_com_claude(texto)
                            st.success("Dados extraídos! Revise no formulário abaixo antes de salvar.")
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


def formulario_material(professor):
    st.title("🧪 Rede de Materiais")
    col_a, col_b = st.columns([4, 1])
    with col_a:
        st.caption(f"Logado como {professor['nome'] or professor['email'] or 'professor'}")
    with col_b:
        if st.button("Sair"):
            supabase.auth.sign_out()
            st.session_state.clear()
            st.rerun()

    st.divider()
    st.subheader("Cadastrar material")

    secao_extracao_automatica(professor)

    extraido = st.session_state.get("extraido", {}) or {}
    pr = extraido.get("parametros_rede") or {}
    rs = extraido.get("rota_sintese") or {}

    if extraido:
        col_info, col_limpar = st.columns([4, 1])
        with col_info:
            st.info("Campos pré-preenchidos automaticamente — revise antes de salvar.")
        with col_limpar:
            if st.button("Limpar"):
                del st.session_state["extraido"]
                st.rerun()

    with st.form("form_material", clear_on_submit=True):
        st.markdown("**Dados essenciais**")

        col1, col2 = st.columns(2)
        with col1:
            formula = st.text_input("Fórmula química *", value=extraido.get("formula") or "",
                                     placeholder="Ex: Bi0.9Nd0.1FeO3")
            nome_comum = st.text_input("Nome comum (opcional)", value=extraido.get("nome_comum") or "")
            sistema_cristalino = st.selectbox(
                "Sistema cristalino", SISTEMAS_CRISTALINOS,
                index=idx_selectbox(SISTEMAS_CRISTALINOS, extraido.get("sistema_cristalino")),
            )
            grupo_espacial = st.text_input("Grupo espacial", value=extraido.get("grupo_espacial") or "",
                                            placeholder="Ex: R3c")

        with col2:
            a = st.number_input("a (Å)", min_value=0.0, value=float(pr.get("a") or 0.0), format="%.4f")
            b = st.number_input("b (Å)", min_value=0.0, value=float(pr.get("b") or 0.0), format="%.4f")
            c = st.number_input("c (Å)", min_value=0.0, value=float(pr.get("c") or 0.0), format="%.4f")
            alpha = st.number_input("α (°)", min_value=0.0, max_value=180.0, value=float(pr.get("alpha") or 90.0), format="%.2f")
            beta = st.number_input("β (°)", min_value=0.0, max_value=180.0, value=float(pr.get("beta") or 90.0), format="%.2f")
            gamma = st.number_input("γ (°)", min_value=0.0, max_value=180.0, value=float(pr.get("gamma") or 90.0), format="%.2f")

        tecnica_medicao = st.selectbox(
            "Técnica de medição dos parâmetros de rede", TECNICAS_MEDICAO,
            index=idx_selectbox(TECNICAS_MEDICAO, pr.get("tecnica_medicao")),
        )

        metodo_sintese = st.text_input("Rota de síntese (resumo)", value=rs.get("metodo") or "",
                                        placeholder="Ex: Reação de estado sólido")

        with st.expander("+ Mais detalhes do material"):
            familia_estrutural = st.text_input("Família estrutural", value=extraido.get("familia_estrutural") or "",
                                                placeholder="Ex: Perovskita")
            aplicacao_alvo = st.text_input("Aplicação-alvo", value=extraido.get("aplicacao_alvo") or "",
                                            placeholder="Ex: Multiferróico")
            col3, col4 = st.columns(2)
            with col3:
                dopante = st.text_input("Dopante", value=extraido.get("dopante") or "", placeholder="Ex: Nd")
            with col4:
                percentual_dopagem = st.number_input(
                    "Percentual de dopagem (%)", min_value=0.0, max_value=100.0,
                    value=float(extraido.get("percentual_dopagem") or 0.0), format="%.2f",
                )

        with st.expander("+ Mais detalhes da síntese"):
            precursores = st.text_area("Precursores", value=rs.get("precursores") or "",
                                        placeholder="Ex: Bi2O3, Nd2O3, Fe2O3")
            col5, col6 = st.columns(2)
            with col5:
                temp_calcinacao = st.number_input("Temperatura de calcinação (°C)", min_value=0.0,
                                                   value=float(rs.get("temp_calcinacao") or 0.0), format="%.1f")
                taxa_aquecimento = st.number_input("Taxa de aquecimento (°C/min)", min_value=0.0, format="%.2f")
                atmosfera = st.selectbox("Atmosfera", ATMOSFERAS, index=idx_selectbox(ATMOSFERAS, rs.get("atmosfera")))
            with col6:
                tempo_calcinacao = st.number_input("Tempo de calcinação (h)", min_value=0.0,
                                                     value=float(rs.get("tempo_calcinacao") or 0.0), format="%.1f")
                taxa_resfriamento = st.number_input("Taxa de resfriamento (°C/min)", min_value=0.0, format="%.2f")

        enviado = st.form_submit_button("Salvar material")

        if enviado:
            if not formula.strip():
                st.error("A fórmula química é obrigatória.")
                return
            if sistema_cristalino == "Selecione...":
                st.error("Selecione o sistema cristalino.")
                return

            material = supabase.table("materiais").insert({
                "professor_id": professor["id"],
                "formula": formula.strip(),
                "nome_comum": nome_comum.strip() or None,
                "sistema_cristalino": sistema_cristalino,
                "grupo_espacial": grupo_espacial.strip() or None,
                "familia_estrutural": familia_estrutural.strip() or None,
                "aplicacao_alvo": aplicacao_alvo.strip() or None,
                "dopante": dopante.strip() or None,
                "percentual_dopagem": percentual_dopagem or None,
            }).execute()

            material_id = material.data[0]["id"]

            if a or b or c:
                supabase.table("parametros_rede").insert({
                    "material_id": material_id,
                    "a": a or None, "b": b or None, "c": c or None,
                    "alpha": alpha, "beta": beta, "gamma": gamma,
                    "tecnica_medicao": None if tecnica_medicao == "Selecione..." else tecnica_medicao,
                }).execute()

            if metodo_sintese.strip() or precursores.strip():
                supabase.table("rota_sintese").insert({
                    "material_id": material_id,
                    "metodo": metodo_sintese.strip() or None,
                    "precursores": precursores.strip() or None,
                    "temp_calcinacao": temp_calcinacao or None,
                    "tempo_calcinacao": tempo_calcinacao or None,
                    "taxa_aquecimento": taxa_aquecimento or None,
                    "taxa_resfriamento": taxa_resfriamento or None,
                    "atmosfera": None if atmosfera == "Selecione..." else atmosfera,
                }).execute()

            if "extraido" in st.session_state:
                del st.session_state["extraido"]

            st.success(f"Material '{formula}' salvo com sucesso!")

    st.divider()
    st.subheader("Materiais cadastrados (todos os professores)")

    materiais = (
        supabase.table("materiais")
        .select("formula, nome_comum, sistema_cristalino, grupo_espacial, criado_em")
        .order("criado_em", desc=True)
        .execute()
    )
    if materiais.data:
        st.dataframe(materiais.data, hide_index=True, use_container_width=True)
    else:
        st.info("Nenhum material cadastrado ainda.")


# ---------- Roteamento principal ----------

# ---------- Roteamento principal ----------

if processar_callback():
    st.stop()

if "access_token" in st.session_state:
    professor = get_professor_logado()
    formulario_material(professor)
else:
    fazer_login()

