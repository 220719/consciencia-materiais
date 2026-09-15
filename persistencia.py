"""Gravação na base v2: fonte única, PDF no Storage, amostras colaborativas."""
from __future__ import annotations

import hashlib

from extracao import buscar_metadados_crossref, normalizar_doi
from simetria import aplicar_restricao, normalizar_hm


def _n(valor):
    try:
        if valor is None or valor == "":
            return None
        n = float(valor)
        return None if n == 0 else n
    except (TypeError, ValueError):
        return None


def sha256_bytes(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def buscar_fonte_por_doi(client, doi: str) -> dict | None:
    chave = normalizar_doi(doi)
    if not chave:
        return None
    resp = (
        client.table("fontes")
        .select("id, doi, doi_normalizado, titulo, autores, periodico, ano, arquivo_path, inserido_por, pesquisadores(nome)")
        .eq("doi_normalizado", chave)
        .limit(1)
        .execute()
    )
    return (resp.data or [None])[0]


def buscar_fonte_por_hash(client, digest: str) -> dict | None:
    resp = (
        client.table("fontes")
        .select("id, doi, titulo, arquivo_path, inserido_por")
        .eq("arquivo_sha256", digest.lower())
        .limit(1)
        .execute()
    )
    return (resp.data or [None])[0]


def garantir_fonte(
    client,
    pesquisador_id: str,
    *,
    doi: str | None = None,
    pdf_bytes: bytes | None = None,
    nome_arquivo: str | None = None,
) -> tuple[dict, bool]:
    """Devolve (fonte, ja_existia). Nunca cria segundo registro para o mesmo DOI/PDF."""
    if doi:
        existente = buscar_fonte_por_doi(client, doi)
        if existente:
            return existente, True
    digest = sha256_bytes(pdf_bytes) if pdf_bytes else None
    if digest:
        existente = buscar_fonte_por_hash(client, digest)
        if existente:
            return existente, True

    meta = buscar_metadados_crossref(doi) if doi else None
    payload = {
        "tipo": "artigo" if doi or pdf_bytes else "laboratorio",
        "doi": normalizar_doi(doi) if doi else None,
        "titulo": (meta or {}).get("titulo"),
        "autores": (meta or {}).get("autores"),
        "periodico": (meta or {}).get("periodico"),
        "ano": (meta or {}).get("ano"),
        "inserido_por": pesquisador_id,
        "arquivo_sha256": digest,
        "arquivo_nome_original": nome_arquivo,
        "arquivo_mime": "application/pdf" if pdf_bytes else None,
        "arquivo_bytes": len(pdf_bytes) if pdf_bytes else None,
    }
    try:
        criada = client.table("fontes").insert(payload).execute()
        fonte = criada.data[0]
    except Exception:
        if doi:
            existente = buscar_fonte_por_doi(client, doi)
            if existente:
                return existente, True
        if digest:
            existente = buscar_fonte_por_hash(client, digest)
            if existente:
                return existente, True
        raise

    if pdf_bytes:
        caminho = f"{fonte['id']}/original.pdf"
        try:
            client.storage.from_("artigos").upload(
                caminho,
                pdf_bytes,
                {"content-type": "application/pdf", "upsert": "false"},
            )
            client.table("fontes").update({"arquivo_path": caminho}).eq("id", fonte["id"]).execute()
            fonte["arquivo_path"] = caminho
        except Exception:
            # Fonte já está gravada; o PDF pode ser reenviado depois.
            pass
    return fonte, False


def resolver_grupo(client, hm: str | None) -> str | None:
    if not hm:
        return None
    alvo = normalizar_hm(hm)
    grupos = client.table("grupos_espaciais").select("id, hm").execute().data or []
    for g in grupos:
        if normalizar_hm(g.get("hm")) == alvo or normalizar_hm(g.get("hm")).replace(" ", "") == alvo:
            return g["id"]
    return None


def garantir_composicao(client, campos: dict) -> dict:
    formula = (campos.get("formula") or "").strip()
    x = _n(campos.get("x_nominal"))
    if x is None and campos.get("percentual_dopagem"):
        x = _n(campos["percentual_dopagem"])
        if x is not None and x > 1:
            x = x / 100.0
    q = client.table("composicoes").select("id").eq("formula", formula)
    if x is None:
        q = q.is_("x_nominal", "null")
    else:
        q = q.eq("x_nominal", x)
    existente = q.limit(1).execute().data
    if existente:
        return existente[0]
    ins = client.table("composicoes").insert({
        "formula": formula,
        "formula_geral": campos.get("formula_geral") or None,
        "nome_comum": campos.get("nome_comum"),
        "familia_estrutural": campos.get("familia_estrutural"),
        "aplicacao_alvo": campos.get("aplicacao_alvo"),
        "dopante": campos.get("dopante"),
        "site_substituicao": campos.get("site_substituicao"),
        "x_nominal": x,
        "percentual_dopagem": _n(campos.get("percentual_dopagem")),
    }).execute()
    return ins.data[0]


def linha_medida(amostra_id, fonte_id, pesquisador_id, medida: dict, grupo_id=None) -> dict | None:
    m = aplicar_restricao(medida)
    a, b, c = _n(m.get("a")), _n(m.get("b")), _n(m.get("c"))
    if not (a or b or c):
        return None
    tecnica = m.get("tecnica_medicao")
    if tecnica not in ("DRX laboratório (Cu Kα)", "Síncrotron", "Nêutrons", "Monocristal", "Outra"):
        tecnica = None
    hm = m.get("grupo_espacial") or m.get("grupo_espacial_hm")
    setting = m.get("setting")
    if setting not in ("hexagonal", "romboedrico"):
        setting = None
        if normalizar_hm(hm) in {"r3c", "r3m", "r-3c", "r-3m"}:
            setting = "hexagonal"
    return {
        "amostra_id": amostra_id,
        "fonte_id": fonte_id,
        "condicao": m.get("condicao") or None,
        "temperatura_k": _n(m.get("temperatura_k")),
        "grupo_espacial_id": grupo_id,
        "grupo_espacial_hm": hm,
        "setting": setting,
        "sistema_cristalino": m.get("sistema_cristalino"),
        "a": a, "b": b, "c": c,
        "alpha": _n(m.get("alpha")),
        "beta": _n(m.get("beta")),
        "gamma": _n(m.get("gamma")),
        "tecnica_medicao": tecnica,
        "status": "extraido",
        "inserido_por": pesquisador_id,
    }


def salvar_amostra(client, pesquisador_id: str, campos: dict, medidas: list[dict] | None, fonte_id: str | None):
    composicao = garantir_composicao(client, campos)
    try:
        amostra = client.table("amostras").insert({
            "composicao_id": composicao["id"],
            "fonte_id": fonte_id,
            "rotulo": campos.get("rotulo") or campos.get("formula"),
            "forma": campos.get("forma"),
            "inserido_por": pesquisador_id,
        }).execute().data[0]
    except Exception as e:
        texto = str(e)
        if "amostras_fonte_composicao_pesquisador_uidx" in texto or "duplicate" in texto.lower():
            raise RuntimeError(
                "Você já cadastrou esta composição neste artigo. "
                "Outro pesquisador ainda pode cadastrar a amostra dele."
            ) from e
        raise

    rs = {
        "metodo": campos.get("metodo"),
        "precursores": campos.get("precursores"),
        "temp_calcinacao": _n(campos.get("temp_calcinacao")),
        "tempo_calcinacao": _n(campos.get("tempo_calcinacao")),
        "temp_sinterizacao": _n(campos.get("temp_sinterizacao")),
        "tempo_sinterizacao": _n(campos.get("tempo_sinterizacao")),
        "taxa_aquecimento": _n(campos.get("taxa_aquecimento")),
        "taxa_resfriamento": _n(campos.get("taxa_resfriamento")),
        "atmosfera": campos.get("atmosfera"),
        "observacao": campos.get("observacao"),
    }
    if any(v not in (None, "") for v in rs.values()):
        client.table("rotas_sintese").insert({"amostra_id": amostra["id"], **rs}).execute()

    lista = list(medidas or [])
    if campos.get("a") or campos.get("b") or campos.get("c"):
        principal = {
            "a": campos.get("a"), "b": campos.get("b"), "c": campos.get("c"),
            "alpha": campos.get("alpha"), "beta": campos.get("beta"), "gamma": campos.get("gamma"),
            "sistema_cristalino": campos.get("sistema_cristalino"),
            "grupo_espacial": campos.get("grupo_espacial"),
            "tecnica_medicao": campos.get("tecnica_medicao"),
            "condicao": (lista[0].get("condicao") if lista else None),
            "temperatura_k": campos.get("temperatura_k") or (lista[0].get("temperatura_k") if lista else None),
        }
        linhas_src = [principal] + lista[1:]
    else:
        linhas_src = lista

    linhas = []
    for m in linhas_src:
        grupo_id = resolver_grupo(client, m.get("grupo_espacial") or m.get("grupo_espacial_hm") or campos.get("grupo_espacial"))
        linha = linha_medida(amostra["id"], fonte_id, pesquisador_id, m, grupo_id)
        if linha:
            linhas.append(linha)
    if linhas:
        client.table("medidas_estruturais").insert(linhas).execute()
    return amostra
