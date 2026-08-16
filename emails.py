"""
Módulo de envio de e-mails transacionais via Resend.
"""
import os

import resend

resend.api_key = os.environ.get("RESEND_API_KEY", "")

# Enquanto não tivermos domínio próprio verificado no Resend, o remetente
# precisa ser esse — e só chega em quem criou a conta Resend.
REMETENTE = "Consciência de Materiais <onboarding@resend.dev>"


def enviar_email_boas_vindas(destinatario: str, nome: str | None) -> bool:
    """Envia o e-mail de confirmação de cadastro. Retorna True/False;
    uma falha aqui nunca deve travar o login do professor, é só um extra."""
    saudacao = f"Olá, {nome}!" if nome else "Olá!"
    try:
        resend.Emails.send({
            "from": REMETENTE,
            "to": destinatario,
            "subject": "Sua conta na Consciência de Materiais foi criada",
            "html": f"""
                <p>{saudacao}</p>
                <p>Sua conta na plataforma <strong>Consciência de Materiais</strong> foi criada com sucesso.</p>
                <p>Assim que sua conta for aprovada, você poderá cadastrar seus materiais e parâmetros de rede.</p>
            """,
        })
        return True
    except Exception:
        return False
