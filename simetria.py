"""Restrições de cela: o que a extração omite, a simetria preenche."""

# Setting hexagonal para romboédrico (R3c/R3m em FullProf, GSAS, BiFeO3).
RESTRICAO_POR_SISTEMA = {
    "Cúbico": {"b": "a", "c": "a", "alpha": 90, "beta": 90, "gamma": 90},
    "Tetragonal": {"b": "a", "alpha": 90, "beta": 90, "gamma": 90},
    "Hexagonal": {"b": "a", "alpha": 90, "beta": 90, "gamma": 120},
    "Romboédrico": {"b": "a", "alpha": 90, "beta": 90, "gamma": 120},
    "Ortorrômbico": {"alpha": 90, "beta": 90, "gamma": 90},
    "Monoclínico": {"alpha": 90, "gamma": 90},
}

# Eixos romboédricos (a = b = c, α = β = γ), só se o artigo usar esse setting.
RESTRICAO_ROMBOEDRICO_EIXOS = {"b": "a", "c": "a", "beta": "alpha", "gamma": "alpha"}

HM_PARA_SISTEMA = {
    "p1": "Triclínico",
    "p-1": "Triclínico",
    "p21/c": "Monoclínico",
    "p21/n": "Monoclínico",
    "p21/a": "Monoclínico",
    "c2/c": "Monoclínico",
    "cc": "Monoclínico",
    "pc": "Monoclínico",
    "p2": "Monoclínico",
    "p21": "Monoclínico",
    "pbam": "Ortorrômbico",
    "pnma": "Ortorrômbico",
    "pbnm": "Ortorrômbico",
    "pna21": "Ortorrômbico",
    "ama2": "Ortorrômbico",
    "amm2": "Ortorrômbico",
    "pmmn": "Ortorrômbico",
    "p4mm": "Tetragonal",
    "p4/mmm": "Tetragonal",
    "i4/mmm": "Tetragonal",
    "p42nmc": "Tetragonal",
    "i4cm": "Tetragonal",
    "pm-3m": "Cúbico",
    "pm3m": "Cúbico",
    "fm-3m": "Cúbico",
    "fd-3m": "Cúbico",
    "ia-3d": "Cúbico",
    "r3c": "Romboédrico",
    "r3m": "Romboédrico",
    "r-3c": "Romboédrico",
    "r-3m": "Romboédrico",
    "p63/mmc": "Hexagonal",
    "p63mc": "Hexagonal",
    "p6/mmm": "Hexagonal",
    "p63cm": "Hexagonal",
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
    if sistema and sistema not in ("", "Selecione..."):
        return sistema
    return HM_PARA_SISTEMA.get(normalizar_hm(hm))


def restricao_de(sistema: str | None, setting: str | None = None) -> dict:
    if sistema == "Romboédrico" and setting == "romboedrico":
        return dict(RESTRICAO_ROMBOEDRICO_EIXOS)
    return dict(RESTRICAO_POR_SISTEMA.get(sistema or "", {}))


def campos_fixos(sistema: str | None, setting: str | None = None) -> set[str]:
    r = restricao_de(sistema, setting)
    fixos = set()
    if r.get("b") == "a":
        fixos.add("b")
    if r.get("c") == "a":
        fixos.add("c")
    for angulo in ("alpha", "beta", "gamma"):
        alvo = r.get(angulo)
        if isinstance(alvo, (int, float)) or alvo == "alpha":
            fixos.add(angulo)
    return fixos


def aplicar_restricao(medida: dict) -> dict:
    """Preenche b, c e ângulos que a simetria determina. Não inventa a."""
    out = dict(medida)
    sistema = sistema_de_grupo(
        out.get("grupo_espacial") or out.get("grupo_espacial_hm"),
        out.get("sistema_cristalino"),
    )
    if sistema:
        out["sistema_cristalino"] = sistema
    setting = out.get("setting")
    r = restricao_de(sistema, setting)
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
    sistema = sistema_de_grupo(item.get("grupo_espacial"), item.get("sistema_cristalino"))
    if sistema:
        item["sistema_cristalino"] = sistema
    return item
