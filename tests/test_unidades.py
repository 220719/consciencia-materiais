from apresentacao import linha_tabela_medida
from simetria import aplicar_restricao, campos_fixos, sistema_de_grupo
from unidades import (
    para_celsius,
    para_kelvin,
    par_celsius_kelvin,
    sanitizar_material,
    sanitizar_medida,
    sanitizar_rota,
    temperatura_medida_para_k,
    tempo_para_minutos,
)


def test_celsius_kelvin_ida_e_volta():
    assert para_celsius(298.15) == 25.0
    assert para_kelvin(25) == 298.15
    assert para_celsius(None) is None


def test_artigo_em_celsius_preenche_os_dois():
    c, k = par_celsius_kelvin({"temperatura_c": 890})
    assert c == 890.0
    assert k == 1163.15


def test_artigo_em_kelvin_preenche_os_dois():
    c, k = par_celsius_kelvin({"temperatura_k": 413})
    assert k == 413
    assert c == para_celsius(413)
    assert c is not None and k is not None


def test_temperatura_c_do_artigo_vira_kelvin():
    assert temperatura_medida_para_k({"temperatura_c": 200}) == 473.15


def test_nakatani_em_kelvin_nao_converte_de_novo():
    assert temperatura_medida_para_k({"temperatura_k": 298}) == 298


def test_nao_inventar_25_quando_condicao_e_ambiente_usa_forno():
    m = sanitizar_medida(
        {"temperatura_c": 25, "condicao": "temperatura ambiente", "a": 5.578},
        {"temp_sinterizacao": 890},
    )
    assert m["temperatura_c"] == 890.0
    assert m["temperatura_k"] == 1163.15
    assert m["condicao"] is None


def test_890_do_artigo_preenche_celsius_e_kelvin():
    m = sanitizar_medida(
        {"temperatura_c": 890, "a": 5.578, "c": 13.867},
        {"temp_sinterizacao": 890},
    )
    assert m["temperatura_c"] == 890.0
    assert m["temperatura_k"] == 1163.15


def test_sem_t_na_medida_usa_sinterizacao():
    m = sanitizar_medida({"a": 5.578, "c": 13.867}, {"temp_sinterizacao": 890})
    assert m["temperatura_c"] == 890.0
    assert m["temperatura_k"] == 1163.15


def test_serie_vs_t_em_kelvin_permanece():
    m = sanitizar_medida(
        {"temperatura_k": 413, "condicao": "413 K", "a": 4.01},
        {"temp_sinterizacao": 890},
    )
    assert m["temperatura_k"] == 413
    assert m["temperatura_c"] == para_celsius(413)


def test_tempo_3_min_nao_vira_fracao_de_hora():
    assert tempo_para_minutos(3) == 3
    assert tempo_para_minutos(3, "min") == 3


def test_tempo_em_horas_vira_minutos():
    assert tempo_para_minutos(2, "h") == 120
    assert tempo_para_minutos(0.05, "h") == 3
    assert tempo_para_minutos(0.05) == 3


def test_rota_co_bfo_3_min_e_890_c():
    rota = sanitizar_rota({
        "temp_sinterizacao": 890,
        "tempo_sinterizacao": 3,
        "tempo_sinterizacao_unidade": "min",
    })
    assert rota["temp_sinterizacao"] == 890
    assert rota["tempo_sinterizacao"] == 3


def test_legado_0_05_hora_vira_3_min():
    rota = sanitizar_rota({"tempo_sinterizacao": 0.05})
    assert rota["tempo_sinterizacao"] == 3


def test_artigo_co_bfo_tem_temperatura_em_celsius():
    item = sanitizar_material({
        "formula": "BiFe0.99Co0.01O3",
        "rota_sintese": {"temp_sinterizacao": 890, "tempo_sinterizacao": 3},
        "medidas": [{
            "a": 5.578, "c": 13.867, "grupo_espacial": "R3c",
            "temperatura_c": 25, "condicao": "temperatura ambiente",
        }],
    })
    assert item["rota_sintese"]["tempo_sinterizacao"] == 3
    assert item["medidas"][0]["temperatura_c"] == 890.0
    assert item["medidas"][0]["temperatura_k"] == 1163.15


def test_tabela_mostra_par_celsius_kelvin_nunca_none():
    rota = {"temp_sinterizacao": 890}
    linha = linha_tabela_medida(
        {
            "condicao": "2.0 at% Co",
            "sistema_cristalino": "Romboédrico",
            "grupo_espacial_hm": "R3c",
            "a": 5.578, "b": 5.578, "c": 13.866,
            "tecnica_medicao": "DRX laboratório (Cu Kα)",
        },
        rota,
    )
    assert linha["T (°C)"] == 890.0
    assert linha["T (K)"] == 1163.15
    assert "None" not in str(linha["T (°C)"])
    assert "None" not in str(linha["T (K)"])
    assert all("DRX" not in chave for chave in linha)
    assert linha["Técnica"] == "DRX laboratório (Cu Kα)"


def test_ficha_acervo_mostra_angulos_e_tempo_forno():
    from apresentacao import montar_ficha

    ficha = montar_ficha(
        {
            "formula": "BiFe0.98Co0.02O3",
            "nome_comum": "BiFeO3 2.0 at% Co",
            "dopante": "Co",
            "percentual_dopagem": 2.0,
            "familia_estrutural": "Perovskita",
        },
        {
            "condicao": "2.0 at% Co",
            "temperatura_k": 1163.15,
            "sistema_cristalino": "Romboédrico",
            "grupo_espacial_hm": "R3c",
            "a": 5.578,
            "b": 5.578,
            "c": 13.866,
            "alpha": 90,
            "beta": 90,
            "gamma": 120,
            "tecnica_medicao": "DRX laboratório (Cu Kα)",
        },
        {
            "metodo": "estado sólido + fast firing",
            "temp_sinterizacao": 890,
            "tempo_sinterizacao": 3,
            "atmosfera": "Ar",
        },
    )
    assert ficha["cela"]["α (°)"] == "90"
    assert ficha["cela"]["γ (°)"] == "120"
    assert ficha["cela"]["a (Å)"] == "5.578"
    assert ficha["forno"]["T sinterização (°C)"] == "890"
    assert ficha["forno"]["t sinterização (min)"] == "3"
    assert ficha["medida"]["Técnica"] == "DRX laboratório (Cu Kα)"
    assert "None" not in str(ficha)


def test_r3c_preenche_angulos_hexagonais_e_nao_copia_c():
    cela = aplicar_restricao({"grupo_espacial": "R3c", "a": 5.578, "c": 13.867})
    assert sistema_de_grupo("R3c", None) == "Romboédrico"
    assert cela["alpha"] == 90 and cela["beta"] == 90 and cela["gamma"] == 120
    assert cela["b"] == 5.578
    assert cela["c"] == 13.867
    assert "alpha" in campos_fixos("Romboédrico")
