"""Rótulos da tabela de medidas. Temperatura é só T, sem DRX."""

from unidades import para_celsius


def linha_tabela_medida(m: dict) -> dict:
    return {
        "Condição": m.get("condicao") or "—",
        "T (°C)": para_celsius(m.get("temperatura_k")),
        "T (K)": m.get("temperatura_k"),
        "Sistema": m.get("sistema_cristalino") or "—",
        "Grupo": m.get("grupo_espacial") or m.get("grupo_espacial_hm") or "—",
        "a (Å)": m.get("a"),
        "b (Å)": m.get("b"),
        "c (Å)": m.get("c"),
        "Técnica": m.get("tecnica_medicao") or "—",
    }
