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

CROSSREF_EMAIL = os.environ.get("CROSSREF_EMAIL", "")
CLAUDE_MODEL = "claude-sonnet-5"
ORCID_CLIENT_ID = os.environ.get("ORCID_CLIENT_ID", "")
ORCID_CLIENT_SECRET = os.environ.get("ORCID_CLIENT_SECRET", "")


def normalizar_doi(doi: str) -> str:
    doi = doi.strip()
    for prefixo in ("https://doi.org/", "http://doi.org/", "doi.org/"):
        if doi.lower().startswith(prefixo):
            return doi[len(prefixo):]
    return doi


def buscar_metadados_crossref(doi: str) -> dict | None:
    doi = normalizar_doi(doi)
    url = f"https://api.crossref.org/works/{doi}"
    params = {"mailto": CROSSREF_EMAIL} if CROSSREF_EMAIL else {}
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
    if not CROSSREF_EMAIL:
        raise ValueError("CROSSREF_EMAIL precisa estar definido no .env.")
    url = f"https://api.unpaywall.org/v2/{doi}"
    resp = requests.get(url, params={"email": CROSSREF_EMAIL}, timeout=15)
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


def baixar_texto_pdf(pdf_url: str) -> str | None:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ConsciênciaDeMateriais/1.0)"}
    resp = requests.get(pdf_url, headers=headers, timeout=30, allow_redirects=True)
    content_type = resp.headers.get("Content-Type", "")
    if resp.status_code != 200 or "pdf" not in content_type.lower():
        return None
    return texto_de_pdf_bytes(resp.content)


def texto_de_pdf_bytes(pdf_bytes: bytes) -> str | None:
    try:
        leitor = PdfReader(io.BytesIO(pdf_bytes))
        texto = "\n".join(pagina.extract_text() or "" for pagina in leitor.pages)
        return texto.strip() or None
    except Exception:
        return None


PROMPT_EXTRACAO = """Leia o texto de artigo científico de ciência de materiais abaixo e chame a
ferramenta "registrar_dados_material" com os campos que você conseguir identificar.

Regras importantes:
- Se um valor não aparecer explicitamente no texto, deixe o campo de fora (não invente ou estime valores).
- Parâmetros de rede em Ångström (Å), ângulos em graus, temperaturas em Celsius, tempos em horas.
- Se o artigo descrever mais de um material, extraia apenas o material principal/protagonista do estudo.

Texto do artigo:
{texto}
"""

FERRAMENTA_EXTRACAO = {
    "name": "registrar_dados_material",
    "description": "Registra os dados estruturados de um material extraídos de um artigo científico.",
    "input_schema": {
        "type": "object",
        "properties": {
            "formula": {"type": "string"},
            "nome_comum": {"type": "string"},
            "sistema_cristalino": {
                "type": "string",
                "enum": ["Cúbico", "Tetragonal", "Ortorrômbico", "Romboédrico",
                         "Hexagonal", "Monoclínico", "Triclínico"],
            },
            "grupo_espacial": {"type": "string"},
            "familia_estrutural": {"type": "string"},
            "aplicacao_alvo": {"type": "string"},
            "dopante": {"type": "string"},
            "percentual_dopagem": {"type": "number"},
            "parametros_rede": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                    "c": {"type": "number"},
                    "alpha": {"type": "number"},
                    "beta": {"type": "number"},
                    "gamma": {"type": "number"},
                    "tecnica_medicao": {
                        "type": "string",
                        "enum": ["DRX laboratório (Cu Kα)", "Síncrotron", "Nêutrons", "Outra"],
                    },
                },
            },
            "rota_sintese": {
                "type": "object",
                "properties": {
                    "metodo": {"type": "string"},
                    "precursores": {"type": "string"},
                    "temp_calcinacao": {"type": "number"},
                    "tempo_calcinacao": {"type": "number"},
                    "atmosfera": {"type": "string", "enum": ["Ar", "O2", "N2", "Vácuo"]},
                },
            },
        },
    },
}


def extrair_campos_com_claude(texto_artigo: str) -> dict:
    client = Anthropic()
    texto_truncado = texto_artigo[:60000]

    resposta = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        tools=[FERRAMENTA_EXTRACAO],
        tool_choice={"type": "tool", "name": "registrar_dados_material"},
        messages=[
            {"role": "user", "content": PROMPT_EXTRACAO.replace("{texto}", texto_truncado)}
        ],
    )

    for bloco in resposta.content:
        if bloco.type == "tool_use":
            return bloco.input

    raise ValueError("A resposta do Claude não contém uma chamada de ferramenta.")

def obter_token_publico_orcid() -> str:
    """Obtém um token de leitura pública do ORCID (client_credentials, não depende
    do login de nenhum professor — token de longa duração, da própria aplicação)."""
    resp = requests.post(
        "https://orcid.org/oauth/token",
        data={
            "client_id": ORCID_CLIENT_ID,
            "client_secret": ORCID_CLIENT_SECRET,
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