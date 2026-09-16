"""Rótulos da tabela de medidas. Temperatura é só T, sem DRX."""

from unidades import par_celsius_kelvin


def _celula(valor):
    return valor if valor is not None else "—"


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
        "Técnica": m.get("tecnica_medicao") or "—",
    }
