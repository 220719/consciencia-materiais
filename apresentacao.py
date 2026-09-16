"""Rótulos da tabela de medidas e da ficha do acervo. Temperatura é só T, sem DRX."""

from unidades import para_celsius, par_celsius_kelvin


def _celula(valor):
    return valor if valor is not None else "—"


def texto_ficha(valor) -> str:
    if valor is None or valor == "":
        return "—"
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return format(n, ".7f").rstrip("0").rstrip(".")


def linha_tabela_medida(m: dict, rota: dict | None = None) -> dict:
    celsius, kelvin = par_celsius_kelvin(m, rota)
    return {
        "Condição": m.get("condicao") or "—",
        "T (°C)": _celula(celsius),
        "T (K)": _celula(kelvin),
        "Sistema": m.get("sistema_cristalino") or "—",
        "Grupo": m.get("grupo_espacial") or m.get("grupo_espacial_hm") or "—",
        "a (Å)": _celula(m.get("a")),
        "b (Å)": _celula(m.get("b")),
        "c (Å)": _celula(m.get("c")),
        "α (°)": _celula(m.get("alpha")),
        "β (°)": _celula(m.get("beta")),
        "γ (°)": _celula(m.get("gamma")),
        "Técnica": m.get("tecnica_medicao") or "—",
    }


def montar_ficha(amostra: dict, medida: dict | None = None, rota: dict | None = None) -> dict:
    """Mesmos blocos do cadastro: identidade, cela, medida/síntese e forno."""
    medida = medida or {}
    rota = rota or (amostra.get("rota") or {})
    t_k = medida.get("temperatura_k")
    t_c = para_celsius(t_k)
    dopagem = amostra.get("percentual_dopagem")
    return {
        "identidade": {
            "Fórmula química": texto_ficha(amostra.get("formula")),
            "Nome comum": texto_ficha(amostra.get("nome_comum")),
            "Sistema cristalino": texto_ficha(
                medida.get("sistema_cristalino") or amostra.get("sistema_cristalino")
            ),
            "Grupo espacial": texto_ficha(
                medida.get("grupo_espacial")
                or medida.get("grupo_espacial_hm")
                or amostra.get("grupo_espacial")
            ),
            "Dopante": texto_ficha(amostra.get("dopante")),
            "Dopagem (%)": texto_ficha(dopagem),
            "Sítio de substituição": texto_ficha(amostra.get("site_substituicao")),
            "Família estrutural": texto_ficha(amostra.get("familia_estrutural")),
            "Aplicação-alvo": texto_ficha(amostra.get("aplicacao_alvo")),
        },
        "cela": {
            "a (Å)": texto_ficha(medida.get("a")),
            "b (Å)": texto_ficha(medida.get("b")),
            "c (Å)": texto_ficha(medida.get("c")),
            "α (°)": texto_ficha(medida.get("alpha")),
            "β (°)": texto_ficha(medida.get("beta")),
            "γ (°)": texto_ficha(medida.get("gamma")),
        },
        "medida": {
            "Condição": texto_ficha(medida.get("condicao")),
            "Técnica": texto_ficha(medida.get("tecnica_medicao")),
            "T da medida (°C)": texto_ficha(t_c),
            "T da medida (K)": texto_ficha(t_k),
            "Método de síntese": texto_ficha(rota.get("metodo")),
            "Precursores": texto_ficha(rota.get("precursores")),
            "Atmosfera": texto_ficha(rota.get("atmosfera")),
        },
        "forno": {
            "T calcinação (°C)": texto_ficha(rota.get("temp_calcinacao")),
            "t calcinação (min)": texto_ficha(rota.get("tempo_calcinacao")),
            "T sinterização (°C)": texto_ficha(rota.get("temp_sinterizacao")),
            "t sinterização (min)": texto_ficha(rota.get("tempo_sinterizacao")),
            "Aquecimento (°C/min)": texto_ficha(rota.get("taxa_aquecimento")),
            "Resfriamento (°C/min)": texto_ficha(rota.get("taxa_resfriamento")),
        },
        "observacao": texto_ficha(rota.get("observacao")),
        "artigo": {
            "DOI": texto_ficha(amostra.get("doi")),
            "Título": texto_ficha(amostra.get("titulo")),
            "Arquivo": texto_ficha(amostra.get("arquivo_nome")),
        },
    }
