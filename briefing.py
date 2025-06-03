import os
import smtplib
from email.mime.text import MIMEText

# CONFIG auslesen
config = os.getenv("CONFIG")
pairs = config.split(";")
config_dict = dict(pair.split("=", 1) for pair in pairs)

email_host = config_dict["EMAIL_HOST"]
email_port = int(config_dict["EMAIL_PORT"])
email_user = config_dict["EMAIL_USER"]
email_password = config_dict["EMAIL_PASSWORD"]
email_to = config_dict["EMAIL_TO"]

# Platzhalter-Inhalt
content = "Guten Morgen!\n\nDas ist dein automatisiertes China-Briefing (Platzhalter)."

msg = MIMEText(content)
msg["Subject"] = "📰 Daily China Briefing"
msg["From"] = email_user
msg["To"] = email_to

with smtplib.SMTP(email_host, email_port) as server:
    server.starttls()
    server.login(email_user, email_password)
    server.send_message(msg)

print("Briefing gesendet an:", email_to)

