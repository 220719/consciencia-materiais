from pathlib import Path

from apresentacao import linha_tabela_medida
from extracao import normalizar_materiais
from persistencia import linha_medida
from simetria import aplicar_restricao
from unidades import para_celsius, para_kelvin, sanitizar_medida


RAIZ = Path(__file__).resolve().parents[1]


def assert_par_t(celsius, kelvin):
    assert celsius not in (None, "None", "—")
    assert kelvin not in (None, "None", "—")
    assert abs(para_kelvin(celsius) - float(kelvin)) < 0.21


CO_BFO = {
    "materiais": [
        {
            "formula": "BiFe0.98Co0.02O3",
            "nome_comum": "BFO-2.0at%Co",
            "dopante": "Co",
            "percentual_dopagem": 2.0,
            "grupo_espacial": "R3c",
            "sistema_cristalino": "Romboédrico",
            "rota_sintese": {
                "metodo": "estado sólido + fast firing",
                "temp_sinterizacao": 890,
                "tempo_sinterizacao": 3,
                "atmosfera": "Ar",
            },
            "medidas": [{
                "a": 5.578,
                "c": 13.866,
                "grupo_espacial": "R3c",
                "tecnica_medicao": "DRX laboratório (Cu Kα)",
                "condicao": "2.0 at% Co",
            }],
        }
    ]
}


NAKATANI = {
    "materiais": [
        {
            "formula": "BaTiO3",
            "grupo_espacial": "P4mm",
            "rota_sintese": {"metodo": "Czochralski"},
            "medidas": [
                {"temperatura_k": 298, "a": 3.9925, "c": 4.0373, "grupo_espacial": "P4mm", "sistema_cristalino": "Tetragonal"},
                {"temperatura_k": 413, "a": 4.0097, "c": 4.0097, "grupo_espacial": "Pm-3m", "sistema_cristalino": "Cúbico"},
            ],
        }
    ]
}


def test_co_bfo_apos_normalizar_tem_t_celsius_e_kelvin():
    itens = normalizar_materiais(CO_BFO)
    m = itens[0]["medidas"][0]
    assert_par_t(m["temperatura_c"], m["temperatura_k"])
    assert m["temperatura_c"] == 890.0
    assert itens[0]["rota_sintese"]["tempo_sinterizacao"] == 3
    cela = aplicar_restricao(m)
    assert cela["alpha"] == 90 and cela["gamma"] == 120
    assert cela["c"] == 13.866


def test_tabela_co_bfo_nunca_mostra_none():
    itens = normalizar_materiais(CO_BFO)
    linha = linha_tabela_medida(itens[0]["medidas"][0], itens[0]["rota_sintese"])
    assert_par_t(linha["T (°C)"], linha["T (K)"])
    assert linha["T (°C)"] == 890.0
    for chave in ("T (°C)", "T (K)"):
        assert linha[chave] not in (None, "None", "—")
        assert str(linha[chave]) != "None"
    for valor in linha.values():
        assert str(valor) != "None"


def test_listagem_salva_sem_t_na_medida_usa_sinterizacao():
    """Como o PostgREST devolve: T nula na medida, 890 na rota."""
    linha = linha_tabela_medida(
        {"condicao": "2.0 at% Co", "a": 5.578, "c": 13.866, "grupo_espacial_hm": "R3c"},
        {"temp_sinterizacao": 890},
    )
    assert_par_t(linha["T (°C)"], linha["T (K)"])


def test_nakatani_kelvin_nao_e_substituido_pelo_forno():
    itens = normalizar_materiais(NAKATANI)
    t0 = itens[0]["medidas"][0]["temperatura_k"]
    t1 = itens[0]["medidas"][1]["temperatura_k"]
    assert t0 == 298
    assert t1 == 413
    linha = linha_tabela_medida(itens[0]["medidas"][0])
    assert_par_t(linha["T (°C)"], linha["T (K)"])
    assert linha["T (K)"] == 298


def test_persistencia_grava_kelvin_quando_artigo_so_tem_sinterizacao():
    linha = linha_medida(
        "amostra", "fonte", "pesq",
        {"a": 5.578, "c": 13.866, "grupo_espacial": "R3c"},
        rota={"temp_sinterizacao": 890},
    )
    assert linha["temperatura_k"] == 1163.15
    assert para_celsius(linha["temperatura_k"]) == 890.0


def test_25_ambiente_nao_sobrevive_se_artigo_tem_890():
    m = sanitizar_medida(
        {"temperatura_c": 25, "condicao": "room temperature", "a": 5.578},
        {"temp_sinterizacao": 890},
    )
    assert m["temperatura_c"] == 890.0


def test_rotulos_app_e_prompt():
    app = (RAIZ / "app.py").read_text(encoding="utf-8")
    extracao = (RAIZ / "extracao.py").read_text(encoding="utf-8")
    assert "T DRX" not in app
    assert "t sinterização (min)" in app
    assert "on_select" in app
    assert "montar_ficha" in app
    assert "t calcinação (min)" in app
    assert "t sinterização (h)" not in app
    assert "0,05 h" not in extracao
    assert "0.05 h" not in extracao
    assert "minutos" in extracao


def test_par_celsius_kelvin_e_simetrico():
    assert para_celsius(para_kelvin(890)) == 890.0
    assert para_kelvin(25) == 298.15
    assert para_celsius(298.15) == 25.0
