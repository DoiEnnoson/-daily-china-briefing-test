import imaplib
import email
import os
import json
import logging
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import smtplib
from email.mime.text import MIMEText
import re
import urllib.parse
import json as json_parser
from bs4 import BeautifulSoup
import requests

# Logging einrichten (umfangreich für Debugging)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger()

# Basisverzeichnis (Repository-Root)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
THINKTANKS_JSON = os.path.join(BASE_DIR, "thinktanks.json")

def send_email(subject, body, email_user, email_password, recipient="hadobrockmeyer@gmail.com"):
    """Sendet eine E-Mail (Warnung oder Status)."""
    logger.info(f"Sende E-Mail: {subject} an {recipient}")
    if not email_user or not email_password:
        logger.error("E-Mail-Credentials fehlen, überspringe E-Mail")
        return
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = email_user
        msg['To'] = recipient
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        logger.info(f"E-Mail erfolgreich an {recipient} gesendet")
    except Exception as e:
        logger.error(f"Fehler beim Senden der E-Mail an {recipient}: {str(e)}")

def load_thinktanks():
    """Lädt die Think Tanks aus der JSON-Datei."""
    logger.info(f"Aktuelles Arbeitsverzeichnis: {os.getcwd()}")
    logger.info(f"Lade Think Tanks aus {THINKTANKS_JSON}")
    logger.info(f"Inhalt von {BASE_DIR}:")
    try:
        for item in os.listdir(BASE_DIR):
            logger.info(f" - {item}")
    except Exception as e:
        logger.error(f"Konnte Verzeichnis nicht auflisten: {str(e)}")
    if not os.path.exists(THINKTANKS_JSON):
        logger.error(f"{THINKTANKS_JSON} nicht gefunden")
        send_email(
            "Fehler in thinktanks.py",
            f"{THINKTANKS_JSON} nicht gefunden",
            os.getenv("GMAIL_USER", ""), os.getenv("GMAIL_PASS", "")
        )
        return []
    try:
        with open(THINKTANKS_JSON, "r", encoding="utf-8") as f:
            thinktanks = json.load(f)
        logger.info(f"Geladen: {len(thinktanks)} Think Tanks")
        logger.info(f"Inhalt von thinktanks.json: {json.dumps(thinktanks, indent=2)}")
        return thinktanks
    except json.JSONDecodeError:
        logger.error(f"{THINKTANKS_JSON} ist ungültig")
        send_email(
            "Fehler in thinktanks.py",
            f"{THINKTANKS_JSON} ist ungültig",
            os.getenv("GMAIL_USER", ""), os.getenv("GMAIL_PASS", "")
        )
        return []

def extract_email_address(sender):
    """Extrahiert die E-Mail-Adresse aus einem Sender-String."""
    logger.info(f"Extrahiere E-Mail-Adresse aus: {sender}")
    match = re.search(r'<([^>]+)>', sender)
    if match:
        email_addr = match.group(1)
        logger.info(f"E-Mail-Adresse gefunden: {email_addr}")
        return email_addr
    email_addr = sender.strip()
    logger.info(f"E-Mail-Adresse (Fallback): {email_addr}")
    return email_addr

def normalize_url(url):
    """Entfernt Tracking-Parameter aus der URL."""
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

def resolve_merics_url(url):
    """Löst MERICS-Tracking-URLs auf die Ziel-URL auf."""
    logger.info(f"Auflösen der URL: {url}")
    if "public-eur.mkt.dynamics.com" in url:
        try:
            parsed = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed.query)
            target = query_params.get("target", [None])[0]
            if target:
                target_data = json_parser.loads(target)
                target_url = urllib.parse.unquote(target_data["TargetUrl"])
                logger.info(f"Ziel-URL gefunden: {target_url}")
                return target_url
        except Exception as e:
            logger.warning(f"Konnte MERICS-URL nicht auflösen: {url}, Fehler: {str(e)}")
    try:
        response = requests.get(url, allow_redirects=True, timeout=5)
        return response.url
    except Exception as e:
        logger.warning(f"Konnte URL nicht auflösen: {url}, Fehler: {str(e)}")
        return url

def score_thinktank_article(title):
    """Bewertet einen Artikel auf China-Relevanz."""
    logger.info(f"Bewerte Think Tank Artikel: {title}")
    title_lower = title.lower()
    score = 0
    must_have_keywords = [
        "china", "chinese", "xi jinping", "beijing", "shanghai", "hong kong", "taiwan",
        "prc", "communist party", "cpc", "byd", "alibaba", "tencent", "huawei", "li qiang",
        "brics", "belt and road", "macau", "pla"
    ]
    important_keywords = [
        "economy", "policy", "trade", "geopolitics", "technology", "ai", "semiconductors",
        "military", "diplomacy", "sanctions", "energy", "climate", "infrastructure"
    ]
    positive_modifiers = [
        "analysis", "report", "brief", "commentary", "working paper", "policy brief",
        "in depth", "research", "study"
    ]
    negative_keywords = [
        "subscribe", "donate", "event", "webinar", "conference", "membership",
        "newsletter", "signup", "registration", "legal notice", "privacy policy",
        "website", "pdf here"
    ]
    if any(kw in title_lower for kw in must_have_keywords):
        score += 5
    if any(kw in title_lower for kw in important_keywords):
        score += 3
    if any(kw in title_lower for kw in positive_modifiers):
        score += 2
    if any(kw in title_lower for kw in negative_keywords):
        score -= 5
    logger.info(f"Score für '{title}': {score}")
    return max(score, 0)

def fetch_merics_emails(email_user, email_password, days=30, max_articles=10):
    """Holt alle E-Mails von MERICS-Absendern und extrahiert Artikel."""
    logger.info("Starte fetch_merics_emails")
    try:
        thinktanks = load_thinktanks()
        merics = next((tt for tt in thinktanks if tt["abbreviation"] == "MERICS"), None)
        if not merics:
            logger.error("MERICS nicht in thinktanks.json gefunden")
            send_email(
                "Fehler in fetch_merics_emails",
                "MERICS nicht in thinktanks.json gefunden",
                email_user, email_password
            )
            return []

        email_senders = merics["email_senders"]
        logger.info(f"Verarbeite MERICS mit Absendern: {email_senders}")
        email_senders = [extract_email_address(sender) for sender in email_senders]
        logger.info(f"Bereinigte Absender: {email_senders}")

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            logger.info(f"Versuche IMAP-Login mit Benutzer: {email_user}")
            mail.login(email_user, email_password)
            logger.info("IMAP-Login erfolgreich")
        except Exception as e:
            logger.error(f"IMAP-Login fehlgeschlagen: {str(e)}")
            send_email(
                "Fehler in fetch_merics_emails",
                f"IMAP-Login fehlgeschlagen: {str(e)}",
                email_user, email_password
            )
            return []

        mail.select("inbox")
        articles = []
        seen_urls = set()
        email_count = 0
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        logger.info(f"Suche nach E-Mails seit: {since_date}")

        for sender in email_senders:
            logger.info(f"Suche nach E-Mails von: {sender}")
            result, data = mail.search(None, f'FROM "{sender}" SINCE {since_date}')
            if result != "OK":
                logger.warning(f"Fehler bei der Suche nach E-Mails von {sender}: {result}")
                send_email(
                    "Fehler in fetch_merics_emails",
                    f"Fehler bei der Suche nach E-Mails von {sender}: {result}",
                    email_user, email_password
                )
                continue

            email_ids = data[0].split()
            email_count += len(email_ids)
            logger.info(f"Anzahl gefundener E-Mails von {sender}: {len(email_ids)}")
            for email_id in email_ids:
                logger.info(f"Verarbeite E-Mail ID: {email_id}")
                result, msg_data = mail.fetch(email_id, "(RFC822)")
                if result != "OK":
                    logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                subject = msg.get("Subject", "Kein Betreff")
                date = msg.get("Date", "Kein Datum")
                try:
                    date = parsedate_to_datetime(date).strftime("%Y-%m-%d %H:%M:%S")
                except:
                    date = "Unbekanntes Datum"
                logger.info(f"E-Mail Betreff: {subject}, Datum: {date}")

                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            html_content = part.get_payload(decode=True).decode(charset)
                        except UnicodeDecodeError:
                            html_content = part.get_payload(decode=True).decode("windows-1252", errors="replace")
                        soup = BeautifulSoup(html_content, "lxml")
                        links = soup.find_all("a", href=True)
                        logger.info(f"Anzahl gefundener Links: {len(links)}")

                        for link in links:
                            href = link.get("href")
                            title = link.get_text(strip=True)
                            logger.info(f"Verarbeite Link: {title} (href: {href})")
                            if not title or len(title) < 10 or any(kw in title.lower() for kw in ["subscribe", "unsubscribe", "donate", "legal notice", "privacy policy", "website"]):
                                logger.info(f"Link übersprungen: Titel zu kurz oder unerwünscht")
                                continue
                            final_url = resolve_merics_url(href)
                            normalized_url = normalize_url(final_url)
                            if normalized_url in seen_urls:
                                logger.info(f"Link übersprungen: URL bereits gesehen")
                                continue
                            score = score_thinktank_article(title)
                            if score > 0:
                                logger.info(f"Artikel hinzugefügt: {title} (URL: {final_url}, Score: {score})")
                                articles.append((score, f'• <a href="{final_url}">{title}</a>'))
                                seen_urls.add(normalized_url)

        mail.logout()
        logger.info("IMAP-Logout erfolgreich")

        # Sortiere nach Score und begrenze auf max_articles
        articles.sort(reverse=True)
        unique_articles = []
        seen_urls.clear()
        for score, article in articles[:max_articles]:
            url = article.split('href="')[1].split('">')[0]
            if url not in seen_urls:
                unique_articles.append(article)
                seen_urls.add(url)

        logger.info(f"Anzahl eindeutiger MERICS-Artikel: {len(unique_articles)}")
        return unique_articles, email_count
    except Exception as e:
        logger.error(f"Fehler in fetch_merics_emails: {str(e)}")
        send_email(
            "Fehler in fetch_merics_emails",
            f"Fehler beim Abrufen von MERICS-E-Mails: {str(e)}",
            email_user, email_password
        )
        return [], 0

def main():
    """Hauptfunktion zum Testen der MERICS-Artikel-Extraktion."""
    logger.info("Starte Testskript für MERICS-Artikel-Extraktion")
    logger.info(f"Aktuelles Arbeitsverzeichnis: {os.getcwd()}")
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        logger.error("SUBSTACK_MAIL Umgebungsvariable nicht gefunden")
        send_email(
            "Fehler in thinktanks.py",
            "SUBSTACK_MAIL Umgebungsvariable nicht gefunden",
            "", ""
        )
        return

    logger.info(f"SUBSTACK_MAIL gefunden, parse Inhalt")
    try:
        mail_config = dict(pair.split("=", 1) for pair in substack_mail.split(";") if "=" in pair)
        email_user = mail_config.get("GMAIL_USER")
        email_password = mail_config.get("GMAIL_PASS")
        logger.info(f"Geparsed: GMAIL_USER={email_user}")
        if not email_user or not email_password:
            logger.error("GMAIL_USER oder GMAIL_PASS fehlt in SUBSTACK_MAIL")
            send_email(
                "Fehler in thinktanks.py",
                "GMAIL_USER oder GMAIL_PASS fehlt in SUBSTACK_MAIL",
                email_user, email_password
            )
            return
    except Exception as e:
        logger.error(f"Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}")
        send_email(
            "Fehler in thinktanks.py",
            f"Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}",
            "", ""
        )
        return

    articles, email_count = fetch_merics_emails(email_user, email_password, days=30, max_articles=10)
    markdown = ["## Think Tanks", "\n### MERICS"]
    if articles:
        markdown.extend(articles)
    else:
        markdown.append("Keine relevanten MERICS-Artikel gefunden.")

    output_file = os.path.join(BASE_DIR, "main", "daily-china-briefing-test", "thinktanks_briefing.md")
    logger.info(f"Schreibe Ergebnisse nach {output_file}")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown))
    logger.info(f"Ergebnisse in {output_file} gespeichert")

    # Status-E-Mail senden
    status_message = f"#Think Tanks\n({email_count} Mails von MERICS gefunden, {len(articles)} Artikel extrahiert)"
    send_email(
        "Think Tanks Status",
        status_message,
        email_user, email_password
    )

if __name__ == "__main__":
    main()
