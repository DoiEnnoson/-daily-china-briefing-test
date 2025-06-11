import os
import imaplib
import email
from bs4 import BeautifulSoup
from datetime import datetime

def fetch_substack_from_email(email_user, email_password, folder="INBOX", max_results=1):
    """Liest Substack-Mails von China Business Spotlight aus einer Gmail-Adresse."""
    posts = []
    
    try:
        # Verbindung zu Gmail herstellen
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(email_user, email_password)
        imap.select(folder)

        # Nur nach China Business Spotlight suchen
        sender = "China Business Spotlight"
        try:
            search_query = f'(UNSEEN FROM "{sender}")'
            print(f"Debug - Suche nach: {search_query}")
            typ, data = imap.search(None, search_query)
            if typ != "OK":
                posts.append(f"❌ Fehler beim Suchen nach Mails von {sender}.")
                imap.logout()
                return posts

            email_ids = data[0].split()[-max_results:]
            if not email_ids:
                posts.append(f"📭 Keine neuen Mails von {sender} gefunden.")
                imap.logout()
                return posts

            # Verarbeite jede Mail
            for eid in reversed(email_ids):
                typ, msg_data = imap.fetch(eid, "(RFC822)")
                if typ != "OK":
                    posts.append(f"❌ Fehler beim Abrufen der Mail {eid} von {sender}.")
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
                    posts.append(f"❌ Kein HTML-Inhalt in der Mail {eid} von {sender}.")
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

                # Ergebnis formatieren
                line = f'• <a href="{link}">{title}</a>'
                if teaser:
                    line += f" – {teaser}"
                posts.append(line)

        except Exception as e:
            posts.append(f"❌ Fehler bei der Verarbeitung von {sender}: {str(e)}")

        imap.logout()

    except Exception as e:
        posts.append(f"❌ Fehler beim Verbinden mit Gmail: {str(e)}")

    return posts if posts else ["Keine neuen Substack-Mails gefunden."]

def generate_briefing():
    date_str = datetime.now().strftime("%d. %B %Y")
    briefing = [f"Hallo Hado, das ist dein Substack-Test\n\n🗓️ {date_str}\n"]

    # Substack-Mails abrufen
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        briefing.append("❌ Fehler: SUBSTACK_MAIL Umgebungsvariable nicht gefunden!")
        return briefing

    try:
        mail_pairs = substack_mail.split(";")
        mail_config = dict(pair.split("=", 1) for pair in mail_pairs)
        email_user = mail_config["GMAIL_USER"]
        email_password = mail_config["GMAIL_PASS"]
    except (KeyError, ValueError) as e:
        briefing.append(f"❌ Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}")
        return briefing

    briefing.append("\n## 📬 China Business Spotlight")
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
    briefing_content = generate_briefing()
    print("\n📬 Ausgabe:")
    print(briefing_content)

if __name__ == "__main__":
    main()
