from apresentacao import montar_ficha
from extracao import extrair_doi_do_texto, normalizar_doi


CABECALHO_JALCOM = """
https://doi.org/10.1016/j.jallcom.2026.186070
Received 24 September 2025; Received in revised form 5 January 2026; Accepted 7 January 2026
Available online 20 January 2026
0925-8388/© 2026 The Authors. Published by Elsevier B.V.
"""


def test_normaliza_url_doi():
    assert normalizar_doi("https://doi.org/10.1016/j.jallcom.2026.186070") == (
        "10.1016/j.jallcom.2026.186070"
    )
    assert normalizar_doi("DOI: 10.1016/j.jallcom.2026.186070") == (
        "10.1016/j.jallcom.2026.186070"
    )


def test_extrai_doi_do_cabecalho_elsevier():
    assert extrair_doi_do_texto(CABECALHO_JALCOM) == "10.1016/j.jallcom.2026.186070"


def test_nao_inventa_doi_sem_texto():
    assert extrair_doi_do_texto("") is None
    assert extrair_doi_do_texto(None) is None


def test_ficha_mostra_doi_do_artigo():
    ficha = montar_ficha(
        {
            "formula": "BiFe0.98Co0.02O3",
            "doi": "10.1016/j.jallcom.2026.186070",
            "titulo": "Co-doped BiFeO3",
            "arquivo_nome": "2_ARTIGO_2026.pdf",
        },
        {"a": 5.578, "c": 13.866, "alpha": 90, "gamma": 120},
        {},
    )
    assert ficha["artigo"]["DOI"] == "10.1016/j.jallcom.2026.186070"
    assert ficha["artigo"]["Arquivo"] == "2_ARTIGO_2026.pdf"
