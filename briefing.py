import os
import imaplib
import email
import smtplib
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from datetime import datetime

def fetch_substack_from_email(email_user, email_password, folder="INBOX", max_results_per_sender=1):
    """Liest Substack-Mails von mehreren Absendern aus einer Gmail-Adresse."""
    posts = []
    
    # Liste der Substack-Absender (E-Mail-Adresse: Substack-Name)
    substack_senders = {
        "yuzhehe@substack.com": "Read China",
        "sinica+trivium-china@substack.com": "Sinica Podcast",
        "thechinaweek@substack.com": "The China Week",
        "techbuzzchina@substack.com": "Tech Buzz China Insider",
        "sinicalchina@substack.com": "Sinical China",
        "fredgao@substack.com": "Inside China",
        "dexter@substack.com": "Trade War",
        "chinai@substack.com": "ChinAI",
        "investinginchina@substack.com": "The Great Wall Street - Investing in China",
        "interconnect@substack.com": "Interconnected!",
        "aseanwonk@substack.com": "ASEAN Wonk Newsletter",
        "eastisread@substack.com": "The East is Read",
        "moneyhk@substack.com": "Hong Kong Money Never Sleeps",
        "trackingpeoplesdaily@substack.com": "Tracking People's Daily",
        "baiguan@substack.com": "Baiguan",
        "bambooworks@substack.com": "Bamboo Works",
        "lijingjing@substack.com": "China Up Close",
        "chinapolicy@substack.com": "CHINA POLICY",
        "chinatalk@substack.com": "ChinaTalk",
        "robotic@substack.com": "Interconnects",
        "chinaarticles@substack.com": "China Articles",
        "treo@substack.com": "Rare Earth Observer",
        "bill@sinocism.com": "Sinocism",
        "beijingscroll@substack.com": "Beijing Scroll",
        "gingerriver@substack.com": "Ginger River Review (GRR)",
        "pekingnology@substack.com": "Pekingnology/CCG",
        "chinabusinessspotlight@substack.com": "China Business Spotlight",
        # Füge "Bert’s Newsletter" hinzu, wenn du die E-Mail-Adresse hast
    }
    
    try:
        # Verbindung zu Gmail herstellen
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(email_user, email_password)
        imap.select(folder)

        # Für jeden Absender suchen
        for sender_email, sender_name in substack_senders.items():
            try:
                search_query = f'(UNSEEN FROM "{sender_email}")'
                print(f"Debug - Suche nach: {search_query}")
                typ, data = imap.search(None, search_query)
                if typ != "OK":
                    posts.append(f"❌ Fehler beim Suchen nach Mails von {sender_name} ({sender_email}).")
                    continue

                email_ids = data[0].split()[-max_results_per_sender:]
                if not email_ids:
                    posts.append(f"📭 Keine neuen Mails von {sender_name} gefunden.")
                    continue

                # Verarbeite jede Mail
                for eid in reversed(email_ids):
                    typ, msg_data = imap.fetch(eid, "(RFC822)")
                    if typ != "OK":
                        posts.append(f"❌ Fehler beim Abrufen der Mail {eid} von {sender_name}.")
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
                        posts.append(f"❌ Kein HTML-Inhalt in der Mail {eid} von {sender_name}.")
                        continue

                    soup = BeautifulSoup(html, "html.parser")

                    # Titel
                    title_tag = soup.find("h1")
                    title = title_tag.text.strip() if title_tag else "Unbenannter Beitrag"

                    # Link
                    link_tag = soup.find("a", href=lambda x: x and "https://" in x)
                    link = link_tag["href"].strip() if link_tag else "#"

                    # Teaser
                    teaser = ""
                    if title_tag:
                        content_candidates = title_tag.find_all_next(string=True)
                        for text in content_candidates:
                            stripped = text.strip()
                            if 30 < len(stripped) < 300 and "dear reader" not in stripped.lower():
                                teaser = stripped
                                break

                    # Ergebnis formatieren (KORRIGIERTE ZEILE)
                    line = f'• <a href="{link}">{title}</a> (von {sender_name})'
                    if teaser:
                        line += f" – {teaser}"
                    posts.append(line)

            except Exception as e:
                posts.append(f"❌ Fehler bei der Verarbeitung von {sender_name} ({sender_email}): {str(e)}")

        imap.logout()

    except Exception as e:
        posts.append(f"❌ Fehler beim Verbinden mit Gmail: {str(e)}")

    return posts if posts else ["Keine neuen Substack-Mails gefunden."]

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
    briefing.extend(fetch_substack_from_email(email_user, email_password))

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
