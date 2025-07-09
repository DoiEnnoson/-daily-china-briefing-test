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
    """Extrahiert die E-Mail-Adresse aus einem Sender-String (z. B. 'MERICS <publications@merics.de>')."""
    logger.info(f"Extrahiere E-Mail-Adresse aus: {sender}")
    match = re.search(r'<([^>]+)>', sender)
    if match:
        email_addr = match.group(1)
        logger.info(f"E-Mail-Adresse gefunden: {email_addr}")
        return email_addr
    email_addr = sender.strip()
    logger.info(f"E-Mail-Adresse (Fallback): {email_addr}")
    return email_addr

def fetch_merics_emails(email_user, email_password, days=30):
    """Holt alle E-Mails von MERICS-Absendern."""
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
        emails = []
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
                emails.append(f"Betreff: {subject}, Datum: {date}")

        mail.logout()
        logger.info("IMAP-Logout erfolgreich")
        return emails
    except Exception as e:
        logger.error(f"Fehler in fetch_merics_emails: {str(e)}")
        send_email(
            "Fehler in fetch_merics_emails",
            f"Fehler beim Abrufen von MERICS-E-Mails: {str(e)}",
            email_user, email_password
        )
        return []

def main():
    """Hauptfunktion zum Testen der MERICS-E-Mail-Suche."""
    logger.info("Starte Testskript für MERICS-E-Mail-Suche")
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

    emails = fetch_merics_emails(email_user, email_password, days=30)
    markdown = ["## Think Tanks", "\n### MERICS"]
    if emails:
        markdown.append("Gefundene E-Mails:")
        markdown.extend(emails)
    else:
        markdown.append("Keine MERICS-E-Mails gefunden.")

    output_file = os.path.join(BASE_DIR, "main", "daily-china-briefing-test", "thinktanks_briefing.md")
    logger.info(f"Schreibe Ergebnisse nach {output_file}")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown))
    logger.info(f"Ergebnisse in {output_file} gespeichert")

    # Status-E-Mail senden
    status_message = f"#Think Tanks\n({'keine Mail von MERICS gefunden' if not emails else f'{len(emails)} Mails von MERICS gefunden'})"
    send_email(
        "Think Tanks Status",
        status_message,
        email_user, email_password
    )

if __name__ == "__main__":
    main()
