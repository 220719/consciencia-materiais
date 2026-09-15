"""
Módulo de extração automática de dados de materiais a partir de artigos.
Fluxo: DOI -> CrossRef (metadados) -> Unpaywall (PDF open access) -> Claude (extração estruturada)
"""
import io
import json
import os

import requests
from anthropic import Anthropic
from pypdf import PdfReader

CLAUDE_MODEL = "claude-sonnet-5"


def _secret(name: str, default: str = "") -> str:
    valor = os.environ.get(name)
    if valor:
        return valor
    try:
        import streamlit as st
        return str(st.secrets[name])
    except Exception:
        return default


def normalizar_doi(doi: str) -> str:
    doi = doi.strip()
    for prefixo in ("https://doi.org/", "http://doi.org/", "doi.org/"):
        if doi.lower().startswith(prefixo):
            return doi[len(prefixo):]
    return doi


def buscar_metadados_crossref(doi: str) -> dict | None:
    doi = normalizar_doi(doi)
    url = f"https://api.crossref.org/works/{doi}"
    email = _secret("CROSSREF_EMAIL")
    params = {"mailto": email} if email else {}
    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code != 200:
        return None

    msg = resp.json()["message"]
    autores = [
        f"{a.get('given', '')} {a.get('family', '')}".strip()
        for a in msg.get("author", [])
    ]
    ano = None
    for campo in ("published-print", "published-online", "created"):
        if campo in msg and "date-parts" in msg[campo]:
            ano = msg[campo]["date-parts"][0][0]
            break

    return {
        "titulo": (msg.get("title") or [None])[0],
        "autores": ", ".join(autores) if autores else None,
        "periodico": (msg.get("container-title") or [None])[0],
        "ano": ano,
        "doi": doi,
    }


def listar_locais_openaccess(doi: str) -> list[str]:
    doi = normalizar_doi(doi)
    email = _secret("CROSSREF_EMAIL")
    if not email:
        raise ValueError("CROSSREF_EMAIL precisa estar definido no .env ou nos secrets.")
    url = f"https://api.unpaywall.org/v2/{doi}"
    resp = requests.get(url, params={"email": email}, timeout=15)
    if resp.status_code != 200:
        return []

    data = resp.json()
    candidatos = []
    best = data.get("best_oa_location")
    if best:
        candidatos.append(best)
    for loc in data.get("oa_locations", []):
        if loc not in candidatos:
            candidatos.append(loc)

    urls = []
    for loc in candidatos:
        if loc.get("url_for_pdf"):
            urls.append(loc["url_for_pdf"])
        elif loc.get("url"):
            urls.append(loc["url"])
    return urls


def baixar_pdf_bytes(pdf_url: str) -> bytes | None:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ConsciênciaDeMateriais/1.0)"}
    resp = requests.get(pdf_url, headers=headers, timeout=30, allow_redirects=True)
    content_type = resp.headers.get("Content-Type", "")
    parece_pdf = "pdf" in content_type.lower() or resp.content.startswith(b"%PDF")
    if resp.status_code != 200 or not parece_pdf:
        return None
    return resp.content


def baixar_texto_pdf(pdf_url: str) -> str | None:
    conteudo = baixar_pdf_bytes(pdf_url)
    return texto_de_pdf_bytes(conteudo) if conteudo else None



def texto_de_pdf_bytes(pdf_bytes: bytes) -> str | None:
    try:
        leitor = PdfReader(io.BytesIO(pdf_bytes))
        texto = "\n".join(pagina.extract_text() or "" for pagina in leitor.pages)
        return texto.strip() or None
    except Exception:
        return None


PROMPT_EXTRACAO = """Leia o texto de artigo científico de ciência de materiais abaixo e chame a
ferramenta "registrar_materiais_do_artigo" com tudo que você conseguir identificar.

Um artigo quase nunca descreve um único conjunto de dados. Não resuma: registre todas as
composições, todas as medidas estruturais e a rota de síntese.

Como separar materiais de medidas:
- Cada COMPOSIÇÃO química distinta é um material próprio. Séries de dopagem (x = 0,01; 0,05; 0,10 ...)
  geram um material por valor de x, cada um com sua fórmula, dopante, x_nominal (fração) e
  percentual_dopagem (em %, ou seja 1,0 para x=0,01 — nunca grave a fração no campo de percentual).
- A MESMA composição medida em condições diferentes (temperaturas, fases, pressões, técnicas)
  é um único material com várias entradas em "medidas".
- Se o artigo traz uma tabela com N temperaturas, registre as N medidas, não apenas a primeira.
  Em "condicao", identifique a medida como o artigo a identifica (ex.: "298 K", "fase cúbica a 473 K").

Síntese — preencha rota_sintese sempre que o experimental existir:
- metodo: sol-gel, estado sólido, Czochralski, moagem de alta energia, etc.
- precursores: lista de reagentes (Bi2O3, Fe2O3, nitratos, etilenoglicol...).
- Distinga calcinação de sinterização. Co-BFO 890 °C / 3 min é sinterização, não calcinação.
- atmosfera: Ar, O2, N2 ou Vácuo. Cristal comercial / Czochralski: metodo preenchido;
  deixe temperaturas de forno de fora se o artigo não calcinou/sinterizou o pó.
- observacao: detalhes (esfera 140 µm, fast firing, cristal 99.99%).

Dopagem:
- dopante = elemento (Sm, Co, Nd). Composto puro: omita dopante e percentual.
- site_substituicao = A, B ou ambos (Sm no Bi = A; Co no Fe = B).

Outras regras:
- Registre apenas os materiais preparados ou caracterizados neste trabalho. Compostos citados
  só como referência, comparação ou contexto histórico não entram na lista.
- Se um valor não aparecer explicitamente no texto, deixe o campo de fora (não invente, não use 0).
- A técnica de medida normalmente vale para a série inteira: repita o mesmo valor de
  "tecnica_medicao" em todas as medidas. DRX de monocristal = "Monocristal".
- Parâmetros de rede em Ångström (Å), ângulos em graus.
- Temperatura de medida em kelvin; temperaturas de síntese em Celsius; tempos em horas
  (3 min = 0,05 h).

Texto do artigo:
{texto}
"""

SISTEMAS = ["Cúbico", "Tetragonal", "Ortorrômbico", "Romboédrico",
            "Hexagonal", "Monoclínico", "Triclínico"]
TECNICAS = ["DRX laboratório (Cu Kα)", "Síncrotron", "Nêutrons", "Monocristal", "Outra"]

ESQUEMA_MEDIDA = {
    "type": "object",
    "description": "Um conjunto de parâmetros de rede medido em uma condição específica.",
    "properties": {
        "condicao": {
            "type": "string",
            "description": "Como o artigo identifica esta medida. Ex: '298 K', 'fase tetragonal', 'após sinterização'.",
        },
        "temperatura_k": {"type": "number", "description": "Temperatura da medida, em kelvin."},
        "sistema_cristalino": {"type": "string", "enum": SISTEMAS},
        "grupo_espacial": {"type": "string"},
        "a": {"type": "number"},
        "b": {"type": "number"},
        "c": {"type": "number"},
        "alpha": {"type": "number"},
        "beta": {"type": "number"},
        "gamma": {"type": "number"},
        "tecnica_medicao": {"type": "string", "enum": TECNICAS},
    },
}

ESQUEMA_MATERIAL = {
    "type": "object",
    "properties": {
        "formula": {"type": "string"},
        "nome_comum": {"type": "string"},
        "sistema_cristalino": {"type": "string", "enum": SISTEMAS},
        "grupo_espacial": {"type": "string"},
        "familia_estrutural": {"type": "string"},
        "aplicacao_alvo": {"type": "string"},
        "dopante": {"type": "string", "description": "Elemento dopante. Omitir se o composto for puro."},
        "percentual_dopagem": {
            "type": "number",
            "description": "Dopagem em porcentagem atômica (1.0 para x=0.01). Não use a fração x aqui.",
        },
        "x_nominal": {"type": "number", "description": "Fração estequiométrica x (0.01, 0.12)."},
        "site_substituicao": {"type": "string", "enum": ["A", "B", "ambos"]},
        "medidas": {"type": "array", "items": ESQUEMA_MEDIDA},
        "rota_sintese": {
            "type": "object",
            "properties": {
                "metodo": {"type": "string"},
                "precursores": {"type": "string"},
                "temp_calcinacao": {"type": "number", "description": "°C"},
                "tempo_calcinacao": {"type": "number", "description": "horas"},
                "temp_sinterizacao": {"type": "number", "description": "°C"},
                "tempo_sinterizacao": {"type": "number", "description": "horas"},
                "taxa_aquecimento": {"type": "number", "description": "°C/min"},
                "taxa_resfriamento": {"type": "number", "description": "°C/min"},
                "atmosfera": {"type": "string", "enum": ["Ar", "O2", "N2", "Vácuo"]},
                "observacao": {"type": "string"},
            },
        },
    },
    "required": ["formula"],
}

FERRAMENTA_EXTRACAO = {
    "name": "registrar_materiais_do_artigo",
    "description": "Registra todos os materiais e todas as medidas estruturais relatados em um artigo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "materiais": {"type": "array", "items": ESQUEMA_MATERIAL},
        },
        "required": ["materiais"],
    },
}


def normalizar_materiais(payload: dict) -> list[dict]:
    """Aceita o formato novo (lista de materiais) e o antigo (um material com parametros_rede)."""
    materiais = payload.get("materiais") if isinstance(payload, dict) else None
    if materiais is None:
        materiais = [payload] if payload else []

    normalizados = []
    for item in materiais:
        if not isinstance(item, dict):
            continue
        medidas = [m for m in (item.get("medidas") or []) if isinstance(m, dict)]
        if not medidas and item.get("parametros_rede"):
            medidas = [item["parametros_rede"]]
        normalizados.append({**item, "medidas": medidas})
    return normalizados


def extrair_campos_com_claude(texto_artigo: str) -> list[dict]:
    client = Anthropic()
    texto_truncado = texto_artigo[:60000]

    resposta = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        tools=[FERRAMENTA_EXTRACAO],
        tool_choice={"type": "tool", "name": "registrar_materiais_do_artigo"},
        messages=[
            {"role": "user", "content": PROMPT_EXTRACAO.replace("{texto}", texto_truncado)}
        ],
    )

    for bloco in resposta.content:
        if bloco.type == "tool_use":
            return normalizar_materiais(bloco.input)

    raise ValueError("A resposta do Claude não contém uma chamada de ferramenta.")

def obter_token_publico_orcid() -> str:
    """Obtém um token de leitura pública do ORCID (client_credentials, não depende
    do login de nenhum professor — token de longa duração, da própria aplicação)."""
    resp = requests.post(
        "https://orcid.org/oauth/token",
        data={
            "client_id": _secret("ORCID_CLIENT_ID"),
            "client_secret": _secret("ORCID_CLIENT_SECRET"),
            "grant_type": "client_credentials",
            "scope": "/read-public",
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def listar_publicacoes_orcid(orcid_id: str, token: str) -> list[dict]:
    """Lista as publicações públicas de um ORCID iD, com título, ano e DOI (quando existir)."""
    resp = requests.get(
        f"https://pub.orcid.org/v3.0/{orcid_id}/works",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=15,
    )
    if resp.status_code != 200:
        return []

    data = resp.json()
    publicacoes = []
    for grupo in data.get("group", []):
        resumo = (grupo.get("work-summary") or [None])[0]
        if not resumo:
            continue
        titulo = ((resumo.get("title") or {}).get("title") or {}).get("value")
        ano_info = resumo.get("publication-date") or {}
        ano = (ano_info.get("year") or {}).get("value")
        doi = None
        for ext_id in ((resumo.get("external-ids") or {}).get("external-id") or []):
            if ext_id.get("external-id-type") == "doi":
                doi = ext_id.get("external-id-value")
                break
        publicacoes.append({"titulo": titulo, "ano": ano, "doi": doi})
    return publicacoes