import os
import imaplib
import email
import smtplib
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from datetime import datetime
import json

def fetch_substack_from_email(email_user, email_password, folder="INBOX", max_results_per_sender=1):
    """Liest Substack-Mails von mehreren Absendern aus einer Gmail-Adresse."""
    posts = []
    
    # Substack-Liste aus JSON laden
    try:
        with open("substacks.json", "r") as f:
            substack_senders = json.load(f)
        # Nach order sortieren
        substack_senders = sorted(substack_senders, key=lambda x: x["order"])
    except FileNotFoundError:
        print("❌ Fehler: substacks.json nicht gefunden!")
        return [("Allgemein", "❌ Fehler: substacks.json nicht gefunden.")]
    except json.JSONDecodeError:
        print("❌ Fehler: substacks.json ungültig!")
        return [("Allgemein", "❌ Fehler: substacks.json ungültig.")]
    
    try:
        # Verbindung zu Gmail herstellen
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(email_user, email_password)
        imap.select(folder)

        # Für jeden Absender suchen
        for sender in substack_senders:
            sender_email = sender.get("email")
            sender_name = sender.get("name")
            if not sender_email:
                posts.append((sender_name, f"❌ Keine E-Mail-Adresse für {sender_name} angegeben."))
                continue

            try:
                search_query = f'(UNSEEN FROM "{sender_email}")'
                print(f"Debug - Suche nach: {search_query}")
                typ, data = imap.search(None, search_query)
                if typ != "OK":
                    posts.append((sender_name, f"❌ Fehler beim Suchen nach Mails von {sender_name} ({sender_email})."))
                    continue

                email_ids = data[0].split()[-max_results_per_sender:]
                if not email_ids:
                    posts.append((sender_name, f"📭 Keine neuen Mails von {sender_name} gefunden."))
                    continue

                # Verarbeite jede Mail
                for eid in reversed(email_ids):
                    typ, msg_data = imap.fetch(eid, "(RFC822)")
                    if typ != "OK":
                        posts.append((sender_name, f"❌ Fehler beim Abrufen der Mail {eid} von {sender_name}."))
                        continue

                    msg = email.message_from_bytes(msg_data[0][1])
                    html = None

                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/html":
                                html = part.get_payload(decode=True).decode()
                                break
                    elif msg.get_content_type() == "text/html":
                        html = msg.get_payload(decode=True).decode()

                    if not html:
                        posts.append((sender_name, f"❌ Kein HTML-Inhalt in der Mail {eid} von {sender_name}."))
                        continue

                    soup = BeautifulSoup(html, "html.parser")

                    # Titel (nur h1 oder h2)
                    title_tag = soup.find("h1") or soup.find("h2")
                    title = title_tag.text.strip() if title_tag else "Unbenannter Beitrag"

                    # Link (priorisieren: /post/ oder app-link/post)
                    link_tag = soup.find("a", href=lambda x: x and ("app-link/post" in x or "/post/" in x))
                    if not link_tag:
                        link_tag = soup.find("a", href=lambda x: x and "https://" in x)  # Fallback
                    link = link_tag["href"].strip() if link_tag else "#"

                    # Teaser (nach Titel überspringen, längere Absätze)
                    teaser = ""
                    if title_tag:
                        content_candidates = title_tag.find_all_next(string=True)
                        found_title = False
                        for text in content_candidates:
                            stripped = text.strip()
                            if not found_title and stripped and stripped in title:
                                found_title = True
                                continue
                            if found_title and 50 < len(stripped) < 500 and "dear reader" not in stripped.lower() and "subscribe" not in stripped.lower():
                                teaser = stripped
                                break

                    # Ergebnis formatieren
                    posts.append((sender_name, title, link, teaser))

            except Exception as e:
                posts.append((sender_name, f"❌ Fehler bei der Verarbeitung von {sender_name} ({sender_email}): {str(e)}"))

        imap.logout()

    except Exception as e:
        posts.append(("Allgemein", f"❌ Fehler beim Verbinden mit Gmail: {str(e)}"))

    return posts if posts else [("Allgemein", "Keine neuen Substack-Mails gefunden.")]

def send_email(sender, password, recipient, subject, body, smtp_host, smtp_port):
    """Sendet eine HTML-E-Mail über SMTP."""
    try:
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        print("📧 E-Mail erfolgreich gesendet!")
    except Exception as e:
        print(f"❌ Fehler beim Senden der E-Mail: {str(e)}")
        raise

def generate_briefing():
    date_str = datetime.now().strftime("%d. %B %Y")
    briefing = [f"Hallo Hado, das ist dein Substack-Test\n\n🗓️ {date_str}\n"]

    # Substack-Mails abrufen
    substack_mail = os.getenv("SUBSTACK_MAIL")
    print(f"Debug - SUBSTACK_MAIL: {substack_mail}")
    if not substack_mail:
        briefing.append("❌ Fehler: SUBSTACK_MAIL Umgebungsvariable nicht gefunden!")
        return f"""\
<html>
  <body>
    <pre style="font-family: system-ui, sans-serif">
{chr(10).join(briefing)}
    </pre>
  </body>
</html>"""

    try:
        mail_pairs = substack_mail.split(";")
        print(f"Debug - mail_pairs: {mail_pairs}")
        mail_config = {}
        for pair in mail_pairs:
            if "=" in pair:
                key, value = pair.split("=", 1)
                mail_config[key] = value
            else:
                print(f"Debug - Ungültiges Paar übersprungen: {pair}")
        print(f"Debug - mail_config keys: {list(mail_config.keys())}")
        
        if "GMAIL_USER" not in mail_config or "GMAIL_PASS" not in mail_config:
            missing_keys = [k for k in ["GMAIL_USER", "GMAIL_PASS"] if k not in mail_config]
            briefing.append(f"❌ Fehler: Fehlende Schlüssel in SUBSTACK_MAIL: {', '.join(missing_keys)}")
            return f"""\
<html>
  <body>
    <pre style="font-family: system-ui, sans-serif">
{chr(10).join(briefing)}
    </pre>
  </body>
</html>"""

        email_user = mail_config["GMAIL_USER"]
        email_password = mail_config["GMAIL_PASS"]
    except ValueError as e:
        briefing.append(f"❌ Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}")
        return f"""\
<html>
  <body>
    <pre style="font-family: system-ui, sans-serif">
{chr(10).join(briefing)}
    </pre>
  </body>
</html>"""

    briefing.append("\n## 📬 Substack-Updates")
    posts = fetch_substack_from_email(email_user, email_password)
    
    for post in posts:
        sender_name = post[0]
        if len(post) == 2:  # Fehlermeldung
            briefing.append(f"\n### {sender_name}\n{post[1]}")
        else:  # Beitrag
            title, link, teaser = post[1], post[2], post[3]
            briefing.append(f"\n### {sender_name}\n<strong><a href=\"{link}\">{title}</a></strong>\n{teaser}")

    briefing.append("\nDer Test war erfolgreich 🌟")
    
    return f"""\
<html>
  <body>
    <pre style="font-family: system-ui, sans-serif">
{chr(10).join(briefing)}
    </pre>
  </body>
</html>"""

def main():
    print("🧠 Erzeuge Briefing...")

    # Config für E-Mail-Versand laden
    config = os.getenv("CONFIG")
    print(f"Debug - CONFIG: {config}")
    if not config:
        print("❌ Fehler: CONFIG Umgebungsvariable nicht gefunden!")
        return

    try:
        config_pairs = config.split(";")
        print(f"Debug - config_pairs: {config_pairs}")
        config_dict = {}
        for pair in config_pairs:
            if "=" in pair:
                key, value = pair.split("=", 1)
                config_dict[key] = value
            else:
                print(f"Debug - Ungültiges Paar übersprungen: {pair}")
        print(f"Debug - config_dict keys: {list(config_dict.keys())}")
        
        required_keys = ["EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_TO", "EMAIL_HOST", "EMAIL_PORT"]
        missing_keys = [k for k in required_keys if k not in config_dict]
        if missing_keys:
            print(f"❌ Fehler: Fehlende Schlüssel in CONFIG: {', '.join(missing_keys)}")
            return

        email_user = config_dict["EMAIL_USER"]
        email_password = config_dict["EMAIL_PASSWORD"]
        email_to = config_dict["EMAIL_TO"]
        smtp_host = config_dict["EMAIL_HOST"]
        smtp_port = int(config_dict["EMAIL_PORT"])
    except (KeyError, ValueError) as e:
        print(f"❌ Fehler beim Parsen von CONFIG: {str(e)}")
        return

    # Briefing generieren
    briefing_content = generate_briefing()

    # E-Mail senden
    subject = f"Substack-Test Briefing - {datetime.now().strftime('%d. %B %Y')}"
    send_email(email_user, email_password, email_to, subject, briefing_content, smtp_host, smtp_port)

if __name__ == "__main__":
    main()
