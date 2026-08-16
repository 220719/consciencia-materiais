import os

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, ClientOptions

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
REDIRECT_URL = "http://localhost:8502"


@st.cache_resource
def get_supabase_client():
    return create_client(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        options=ClientOptions(flow_type="pkce"),
    )


supabase = get_supabase_client()

st.set_page_config(page_title="Consciência de Materiais", page_icon="🧪", layout="centered")


def fazer_login():
    st.title("🧪 Consciência de Materiais")
    st.caption("Entre com seu ORCID para cadastrar materiais.")

    auth_url, _ = supabase.auth._get_url_for_provider(
        f"{supabase.auth._url}/authorize",
        "custom:orcid",
        {"redirect_to": REDIRECT_URL},
    )
    st.link_button("Entrar com ORCID", auth_url)


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
        st.error(f"Erro ao validar login: {e}")
    return True


def get_professor_logado():
    supabase.auth.set_session(
        st.session_state["access_token"],
        st.session_state["refresh_token"],
    )
    user = supabase.auth.get_user().user
    professor = (
        supabase.table("professores")
        .select("id, nome, email")
        .eq("user_id", user.id)
        .single()
        .execute()
    )
    return professor.data


def formulario_material(professor):
    st.title("🧪 Consciência de Materiais")
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

    with st.form("form_material", clear_on_submit=True):
        st.markdown("**Dados essenciais**")

        col1, col2 = st.columns(2)
        with col1:
            formula = st.text_input("Fórmula química *", placeholder="Ex: Bi0.9Nd0.1FeO3")
            nome_comum = st.text_input("Nome comum (opcional)")
            sistema_cristalino = st.selectbox(
                "Sistema cristalino",
                ["Selecione...", "Cúbico", "Tetragonal", "Ortorrômbico", "Romboédrico",
                 "Hexagonal", "Monoclínico", "Triclínico"],
            )
            grupo_espacial = st.text_input("Grupo espacial", placeholder="Ex: R3c")

        with col2:
            a = st.number_input("a (Å)", min_value=0.0, format="%.4f")
            b = st.number_input("b (Å)", min_value=0.0, format="%.4f")
            c = st.number_input("c (Å)", min_value=0.0, format="%.4f")
            alpha = st.number_input("α (°)", min_value=0.0, max_value=180.0, value=90.0, format="%.2f")
            beta = st.number_input("β (°)", min_value=0.0, max_value=180.0, value=90.0, format="%.2f")
            gamma = st.number_input("γ (°)", min_value=0.0, max_value=180.0, value=90.0, format="%.2f")

        tecnica_medicao = st.selectbox(
            "Técnica de medição dos parâmetros de rede",
            ["Selecione...", "DRX laboratório (Cu Kα)", "Síncrotron", "Nêutrons", "Outra"],
        )

        metodo_sintese = st.text_input(
            "Rota de síntese (resumo)",
            placeholder="Ex: Reação de estado sólido",
        )

        with st.expander("+ Mais detalhes do material"):
            familia_estrutural = st.text_input("Família estrutural", placeholder="Ex: Perovskita")
            aplicacao_alvo = st.text_input("Aplicação-alvo", placeholder="Ex: Multiferróico")
            col3, col4 = st.columns(2)
            with col3:
                dopante = st.text_input("Dopante", placeholder="Ex: Nd")
            with col4:
                percentual_dopagem = st.number_input("Percentual de dopagem (%)", min_value=0.0, max_value=100.0, format="%.2f")

        with st.expander("+ Mais detalhes da síntese"):
            precursores = st.text_area("Precursores", placeholder="Ex: Bi2O3, Nd2O3, Fe2O3")
            col5, col6 = st.columns(2)
            with col5:
                temp_calcinacao = st.number_input("Temperatura de calcinação (°C)", min_value=0.0, format="%.1f")
                taxa_aquecimento = st.number_input("Taxa de aquecimento (°C/min)", min_value=0.0, format="%.2f")
                atmosfera = st.selectbox("Atmosfera", ["Selecione...", "Ar", "O2", "N2", "Vácuo"])
            with col6:
                tempo_calcinacao = st.number_input("Tempo de calcinação (h)", min_value=0.0, format="%.1f")
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

if processar_callback():
    st.stop()

if "access_token" in st.session_state:
    professor = get_professor_logado()
    formulario_material(professor)
else:
    fazer_login()
