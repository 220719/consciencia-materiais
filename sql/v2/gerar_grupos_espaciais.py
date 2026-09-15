"""Gera o seed da tabela grupos_espaciais a partir das tabelas de simetria do gemmi.

A restrição da cela não é digitada: ela é derivada das operações de simetria do
próprio grupo. Para cada grupo, o tensor métrico G é simetrizado sobre todas as
rotações (G_sym = média de Rᵀ G R). As igualdades que sobrevivem para vários G
genéricos são as restrições reais daquele setting — o que resolve de uma vez o
eixo único do monoclínico e a diferença entre R3c hexagonal e romboédrico.

Uso:
    uv run --with gemmi --with numpy python sql/v2/gerar_grupos_espaciais.py > 002_seed.sql
"""

import json
import sys

import gemmi
import numpy as np

TOL = 1e-9
N_TESTES = 6


def rotacoes(sg: gemmi.SpaceGroup) -> list[np.ndarray]:
    den = float(gemmi.Op.DEN)
    vistas = {}
    for op in sg.operations():
        r = np.array(op.rot, dtype=float) / den
        vistas[r.tobytes()] = r
    return list(vistas.values())


def metrica_generica(rng: np.random.Generator) -> np.ndarray:
    """Tensor métrico genérico (simétrico, definido positivo, sem simetria acidental)."""
    m = rng.uniform(0.7, 1.4, size=(3, 3))
    return m @ m.T


def restricao_da_cela(sg: gemmi.SpaceGroup) -> dict:
    """Descobre quais parâmetros da cela são determinados pelos outros."""
    rots = rotacoes(sg)
    rng = np.random.default_rng(20260914)
    amostras = []
    for _ in range(N_TESTES):
        g = metrica_generica(rng)
        g_sym = sum(r.T @ g @ r for r in rots) / len(rots)
        amostras.append(g_sym)

    def sempre(f) -> bool:
        return all(abs(f(g)) < TOL * max(1.0, abs(g).max()) for g in amostras)

    restricao: dict[str, object] = {}

    b_igual_a = sempre(lambda g: g[0, 0] - g[1, 1])
    c_igual_a = sempre(lambda g: g[0, 0] - g[2, 2])
    if b_igual_a:
        restricao["b"] = "a"
    if c_igual_a:
        restricao["c"] = "a"

    # Ângulos: cos(alpha) ∝ G[1,2], cos(beta) ∝ G[0,2], cos(gamma) ∝ G[0,1].
    pares = (("alpha", (1, 2)), ("beta", (0, 2)), ("gamma", (0, 1)))
    reto = {}
    for nome, (i, j) in pares:
        reto[nome] = sempre(lambda g, i=i, j=j: g[i, j])
        if reto[nome]:
            restricao[nome] = 90

    # Hexagonal: gamma = 120 significa G[0,1] = -a²/2 com a = b.
    if not reto["gamma"] and b_igual_a and sempre(lambda g: g[0, 1] + g[0, 0] / 2):
        restricao["gamma"] = 120

    # Romboédrico: a = b = c e alpha = beta = gamma, todos livres.
    if b_igual_a and c_igual_a and not any(reto.values()):
        if sempre(lambda g: g[1, 2] - g[0, 2]) and sempre(lambda g: g[1, 2] - g[0, 1]):
            restricao["beta"] = "alpha"
            restricao["gamma"] = "alpha"

    return restricao


def sql_literal(valor) -> str:
    if valor is None:
        return "NULL"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return "'" + str(valor).replace("'", "''") + "'"


def normalizar_ext(sg: gemmi.SpaceGroup) -> str:
    """gemmi devolve NUL ou espaço quando o grupo não tem extensão de setting."""
    return (sg.ext or "").strip("\x00 ")


def main() -> None:
    vistos = set()
    linhas = []
    for sg in gemmi.spacegroup_table():
        ext = normalizar_ext(sg)
        chave = (sg.number, ext)
        if chave in vistos:
            continue
        if not sg.is_reference_setting() and not ext:
            continue  # settings alternativos sem extensão não entram no seed base
        vistos.add(chave)

        restricao = restricao_da_cela(sg)
        linhas.append(
            "  ({}, {}, {}, {}, {}, {}, {}, {}, {}::jsonb)".format(
                sg.number,
                sql_literal(ext),
                sql_literal(sg.hm),
                sql_literal(sg.xhm()),
                sql_literal(sg.hall),
                sql_literal(sg.crystal_system_str()),
                sql_literal(sg.laue_str()),
                sql_literal(gemmi.SpaceGroup(sg.xhm()).operations().is_centrosymmetric()),
                sql_literal(json.dumps(restricao, sort_keys=True)),
            )
        )

    print("-- Gerado por sql/v2/gerar_grupos_espaciais.py — não editar à mão.")
    print(f"-- gemmi {gemmi.__version__}; {len(linhas)} settings.")
    print("insert into public.grupos_espaciais")
    print("  (numero, ext, hm, xhm, hall, sistema_cristalino, classe_laue,")
    print("   centrossimetrico, restricao_cela)")
    print("values")
    print(",\n".join(linhas))
    print("on conflict (numero, ext) do nothing;")
    print(f"-- fim: {len(linhas)} linhas", file=sys.stderr)


if __name__ == "__main__":
    main()
