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
    c = _n(medida.get("temperatura_c"))
    if c is not None:
        return para_kelvin(c)
    k = _n(medida.get("temperatura_k"))
    if k is None:
        return None
    unidade = str(medida.get("temperatura_unidade") or "K").strip().upper()
    unidade = (
        unidade.replace("°", "")
        .replace("CELSIUS", "C")
        .replace("KELVIN", "K")
    )
    if unidade.startswith("C"):
        return para_kelvin(k)
    return k


def par_celsius_kelvin(medida: dict | None = None, rota: dict | None = None) -> tuple[float | None, float | None]:
    """Se o artigo der °C ou K, devolve os dois. Sem número, (None, None)."""
    k = temperatura_medida_para_k(medida)
    if k is None:
        rota = rota or {}
        t_forno = _n(rota.get("temp_sinterizacao")) or _n(rota.get("temp_calcinacao"))
        if t_forno is not None:
            k = para_kelvin(t_forno)
    if k is None:
        return None, None
    return para_celsius(k), k


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


def sanitizar_medida(medida: dict | None, rota: dict | None = None) -> dict:
    """Garante um par °C/K. Descarta só 25 °C inventado como 'ambiente'."""
    m = dict(medida or {})
    rota = rota or {}
    k = temperatura_medida_para_k(m)
    c = para_celsius(k)
    condicao = str(m.get("condicao") or "").strip().lower()
    if c is not None and condicao in CONDICOES_AMBIENTE and abs(c - 25) < 0.2:
        k = None
        m["condicao"] = None
    c, k = par_celsius_kelvin({**m, "temperatura_k": k, "temperatura_c": None}, rota)
    m["temperatura_k"] = k
    if c is not None:
        m["temperatura_c"] = c
    else:
        m.pop("temperatura_c", None)
    return m


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
