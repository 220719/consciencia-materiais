"""
Script de backup do banco de dados Supabase.
Roda semanalmente via GitHub Actions, salva um dump JSON de cada tabela.
"""
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

TABELAS = [
    "professores",
    "materiais",
    "parametros_rede",
    "rota_sintese",
    "caracterizacoes",
    "propriedades_fisicas",
    "publicacoes",
]


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    pasta = Path("backups") / date.today().isoformat()
    pasta.mkdir(parents=True, exist_ok=True)

    resumo = {}
    for tabela in TABELAS:
        resultado = supabase.table(tabela).select("*").execute()
        caminho = pasta / f"{tabela}.json"
        caminho.write_text(
            json.dumps(resultado.data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        resumo[tabela] = len(resultado.data)
        print(f"{tabela}: {len(resultado.data)} registros salvos")

    (pasta / "_resumo.json").write_text(
        json.dumps({
            "data": datetime.now(timezone.utc).isoformat(),
            "contagem": resumo,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
