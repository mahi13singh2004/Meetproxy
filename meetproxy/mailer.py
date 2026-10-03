import os, smtplib, ssl
from email.message import EmailMessage


def send_mail(subject: str, body: str, attachment: tuple[str, str] | None = None):
    msg = EmailMessage()
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["MAIL_TO"]
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        name, text = attachment
        msg.add_attachment(text.encode(), maintype="text", subtype="plain", filename=name)
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"),
                          int(os.environ.get("SMTP_PORT", 465)),
                          context=ssl.create_default_context(), timeout=30) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
