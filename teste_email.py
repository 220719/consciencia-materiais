from dotenv import load_dotenv
load_dotenv()

from emails import enviar_email_boas_vindas

destino = input("Cole o e-mail com que voce criou a conta Resend: ").strip()
sucesso = enviar_email_boas_vindas(destino, "Anuar")
print("Enviado!" if sucesso else "Falhou - confira a RESEND_API_KEY no .env.")
