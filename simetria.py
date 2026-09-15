"""Restrições de cela: o que a extração omite, a simetria preenche."""

RESTRICAO_POR_SISTEMA = {
    "Cúbico": {"b": "a", "c": "a", "alpha": 90, "beta": 90, "gamma": 90},
    "Tetragonal": {"b": "a", "alpha": 90, "beta": 90, "gamma": 90},
    "Hexagonal": {"b": "a", "alpha": 90, "beta": 90, "gamma": 120},
    "Romboédrico": {"b": "a", "c": "a", "beta": "alpha", "gamma": "alpha"},
    "Ortorrômbico": {"alpha": 90, "beta": 90, "gamma": 90},
}

HM_PARA_SISTEMA = {
    "p4mm": "Tetragonal",
    "p4/mmm": "Tetragonal",
    "pm-3m": "Cúbico",
    "pm3m": "Cúbico",
    "fm-3m": "Cúbico",
    "fd-3m": "Cúbico",
    "r3c": "Romboédrico",
    "r3m": "Romboédrico",
    "r-3c": "Romboédrico",
    "r-3m": "Romboédrico",
    "pnma": "Ortorrômbico",
    "pbam": "Ortorrômbico",
    "p63/mmc": "Hexagonal",
}


def _n(valor):
    try:
        if valor is None or valor == "":
            return None
        n = float(valor)
        return None if n == 0 else n
    except (TypeError, ValueError):
        return None


def normalizar_hm(hm: str | None) -> str:
    if not hm:
        return ""
    return (
        hm.lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("−", "-")
        .replace("–", "-")
    )


def sistema_de_grupo(hm: str | None, sistema: str | None) -> str | None:
    if sistema:
        return sistema
    return HM_PARA_SISTEMA.get(normalizar_hm(hm))


def aplicar_restricao(medida: dict) -> dict:
    """Preenche b, c e ângulos que a simetria determina. Não inventa a."""
    out = dict(medida)
    sistema = sistema_de_grupo(out.get("grupo_espacial") or out.get("grupo_espacial_hm"), out.get("sistema_cristalino"))
    if sistema:
        out["sistema_cristalino"] = sistema
    r = RESTRICAO_POR_SISTEMA.get(sistema or "", {})
    a = _n(out.get("a"))
    if a is not None:
        out["a"] = a
    if r.get("b") == "a" and a is not None:
        out["b"] = a
    if r.get("c") == "a" and a is not None:
        out["c"] = a
    for angulo in ("alpha", "beta", "gamma"):
        alvo = r.get(angulo)
        if alvo == "alpha":
            out[angulo] = _n(out.get("alpha"))
        elif isinstance(alvo, (int, float)):
            out[angulo] = float(alvo)
    out["a"] = _n(out.get("a"))
    out["b"] = _n(out.get("b"))
    out["c"] = _n(out.get("c"))
    return out


def aplicar_em_material(item: dict) -> dict:
    item = dict(item)
    medidas = [aplicar_restricao(m) if isinstance(m, dict) else m for m in (item.get("medidas") or [])]
    item["medidas"] = medidas
    if medidas:
        item["sistema_cristalino"] = item.get("sistema_cristalino") or medidas[0].get("sistema_cristalino")
        item["grupo_espacial"] = item.get("grupo_espacial") or medidas[0].get("grupo_espacial")
    return item
