import json

from dotenv import load_dotenv
load_dotenv()

from extracao import texto_de_pdf_bytes, extrair_campos_com_claude


def normalizar_caminho(caminho: str) -> str:
    caminho = caminho.strip().strip('"').strip("'")
    if len(caminho) > 1 and caminho[1] == ":":
        letra_drive = caminho[0].lower()
        resto = caminho[2:].replace("\\", "/")
        caminho = f"/mnt/{letra_drive}{resto}"
    return caminho


caminho = normalizar_caminho(input("Cole o caminho do PDF salvo no seu computador: "))
print(f"Lendo: {caminho}")

with open(caminho, "rb") as f:
    pdf_bytes = f.read()

texto = texto_de_pdf_bytes(pdf_bytes)

if texto is None:
    print("Não consegui extrair texto desse PDF (pode ser um PDF escaneado/imagem).")
else:
    print(f"Texto extraído: {len(texto)} caracteres.")
    print("\n--- Enviando para o Claude extrair os campos ---")
    campos = extrair_campos_com_claude(texto)
    print(json.dumps(campos, indent=2, ensure_ascii=False))
