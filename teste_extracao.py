import json

from dotenv import load_dotenv
load_dotenv()

from extracao import listar_locais_openaccess, baixar_texto_pdf, extrair_campos_com_claude

doi = input("Cole o mesmo DOI de antes: ").strip()

print("\n--- Locais de acesso aberto encontrados ---")
urls = listar_locais_openaccess(doi)
print(f"{len(urls)} opção(ões) encontrada(s):")
for u in urls:
    print(" -", u)

texto = None
for url in urls:
    print(f"\nTentando: {url}")
    texto = baixar_texto_pdf(url)
    if texto:
        print("Consegui ler este!")
        break
    print("Não deu, tentando o próximo...")

if texto is None:
    print("\nNenhuma cópia aberta ficou acessível. Cenário de fallback: upload manual do PDF.")
else:
    print(f"\nTexto extraído: {len(texto)} caracteres.")
    print("\n--- Enviando para o Claude extrair os campos ---")
    campos = extrair_campos_com_claude(texto)
    print(json.dumps(campos, indent=2, ensure_ascii=False))
