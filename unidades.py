"""Temperatura da medida estrutural: a base guarda kelvin; a UI trabalha em °C."""
from __future__ import annotations

ZERO_C_EM_K = 273.15


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
