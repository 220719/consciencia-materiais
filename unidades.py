"""Unidades da interface: T da medida em °C (base em K); tempo de forno em minutos."""
from __future__ import annotations

ZERO_C_EM_K = 273.15
CONDICOES_AMBIENTE = {
    "temperatura ambiente",
    "room temperature",
    "ambiente",
    "rt",
    "t.a.",
    "ta",
}


def _n(valor) -> float | None:
    try:
        if valor is None or valor == "":
            return None
        return float(valor)
    except (TypeError, ValueError):
        return None


def para_celsius(kelvin) -> float | None:
    k = _n(kelvin)
    if k is None:
        return None
    return round(k - ZERO_C_EM_K, 1)


def para_kelvin(celsius) -> float | None:
    c = _n(celsius)
    if c is None:
        return None
    return round(c + ZERO_C_EM_K, 2)


def temperatura_medida_para_k(medida: dict | None) -> float | None:
    """Converte o que veio do artigo/formulário para kelvin.

    Prefere temperatura_c. Se só houver temperatura_k, respeita
    temperatura_unidade ('C' ou 'K'; padrão K).
    """
    if not medida:
        return None
    k = _n(medida.get("temperatura_k"))
    if k is not None:
        unidade = str(medida.get("temperatura_unidade") or "K").strip().upper()
        unidade = (
            unidade.replace("°", "")
            .replace("CELSIUS", "C")
            .replace("KELVIN", "K")
        )
        if unidade.startswith("C"):
            return para_kelvin(k)
        return k
    c = _n(medida.get("temperatura_c"))
    if c is not None:
        return para_kelvin(c)
    return None


def par_celsius_kelvin(medida: dict | None = None, rota: dict | None = None) -> tuple[float | None, float | None]:
    """Par °C/K só da medida estrutural. T de forno não entra aqui."""
    _ = rota
    k = temperatura_medida_para_k(medida)
    if k is None:
        return None, None
    return para_celsius(k), k


def _parece_ambiente(condicao: str) -> bool:
    texto = (condicao or "").strip().lower()
    return any(p in texto for p in CONDICOES_AMBIENTE)


def _t_forno_c(rota: dict | None) -> list[float]:
    rota = rota or {}
    valores = []
    for chave in ("temp_sinterizacao", "temp_calcinacao"):
        n = _n(rota.get(chave))
        if n is not None:
            valores.append(n)
    return valores


def _condicao_cita_t(condicao: str, celsius: float | None, kelvin: float | None) -> bool:
    """'413 K' ou '890 °C' na condição conta como T da medida, não do forno."""
    texto = (condicao or "").lower()
    if not texto:
        return False
    candidatos = []
    if celsius is not None:
        candidatos.append(str(int(round(celsius))))
    if kelvin is not None:
        candidatos.append(str(int(round(kelvin))))
    tem_unidade = any(u in texto for u in ("k", "c", "°"))
    return tem_unidade and any(n in texto.replace(" ", "") or n in texto for n in candidatos)


def sanitizar_medida(medida: dict | None, rota: dict | None = None) -> dict:
    """T da cela só se o artigo der T da medida. Forno fica na rota."""
    m = dict(medida or {})
    rota = rota or {}
    k = temperatura_medida_para_k(m)
    c = para_celsius(k)
    condicao = str(m.get("condicao") or "")
    if c is not None and _parece_ambiente(condicao) and abs(c - 25) < 0.2:
        k = None
        c = None
        if condicao.strip().lower() in CONDICOES_AMBIENTE:
            m["condicao"] = None
    if c is not None and not _condicao_cita_t(condicao, c, k):
        for t_forno in _t_forno_c(rota):
            if abs(c - t_forno) < 0.6:
                k = None
                c = None
                break
    if k is None:
        m["temperatura_k"] = None
        m.pop("temperatura_c", None)
        return m
    c, k = par_celsius_kelvin({"temperatura_k": k})
    m["temperatura_k"] = k
    if c is not None:
        m["temperatura_c"] = c
    else:
        m.pop("temperatura_c", None)
    return m


def tempo_para_minutos(valor, unidade: str | None = None) -> float | None:
    """Tempo de forno em minutos. 3 min → 3; 2 h → 120; legado 0,05 h → 3."""
    n = _n(valor)
    if n is None:
        return None
    u = str(unidade or "").strip().lower()
    u = u.replace("horas", "h").replace("hora", "h").replace("hours", "h").replace("hour", "h")
    u = u.replace("minutos", "min").replace("minuto", "min").replace("minutes", "min")
    if u.startswith("h"):
        return round(n * 60.0, 2)
    if u.startswith("min"):
        return round(n, 2)
    if 0 < n < 1:
        return round(n * 60.0, 2)
    return round(n, 2)


def sanitizar_rota(rota: dict | None) -> dict:
    r = dict(rota or {})
    r["tempo_calcinacao"] = tempo_para_minutos(
        r.get("tempo_calcinacao"), r.get("tempo_calcinacao_unidade")
    )
    r["tempo_sinterizacao"] = tempo_para_minutos(
        r.get("tempo_sinterizacao"), r.get("tempo_sinterizacao_unidade")
    )
    return r


def sanitizar_material(item: dict) -> dict:
    out = dict(item)
    if out.get("rota_sintese"):
        out["rota_sintese"] = sanitizar_rota(out["rota_sintese"])
    rota = out.get("rota_sintese") or {}
    medidas = []
    for m in out.get("medidas") or []:
        if isinstance(m, dict):
            medidas.append(sanitizar_medida(m, rota))
    out["medidas"] = medidas
    return out
