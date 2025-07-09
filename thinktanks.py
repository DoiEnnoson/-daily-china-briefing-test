import imaplib
import email
import os
import json
import logging
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import smtplib
from email.mime.text import MIMEText

# Logging einrichten (umfangreich für Debugging)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger()

# Basisverzeichnis
BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main", "daily-china-briefing-test")
THINKTANKS_JSON = os.path.join(BASE_DIR, "thinktanks.json")

def send_warning_email(subject, body, email_user, email_password, recipient):
    """Sendet eine Warn-E-Mail bei Fehlern."""
    logger.info(f"Sende Warn-E-Mail: {subject}")
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = email_user
        msg['To'] = recipient
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        logger.info("Warn-E-Mail erfolgreich gesendet")
    except Exception as e:
        logger.error(f"Fehler beim Senden der Warn-E-Mail: {str(e)}")

def load_thinktanks():
    """Lädt die Think Tanks aus der JSON-Datei."""
    logger.info(f"Lade Think Tanks aus {THINKTANKS_JSON}")
    try:
        with open(THINKTANKS_JSON, "r", encoding="utf-8") as f:
            thinktanks = json.load(f)
        logger.info(f"Geladen: {len(thinktanks)} Think Tanks")
        return thinktanks
    except FileNotFoundError:
        logger.error(f"{THINKTANKS_JSON} nicht gefunden")
        send_warning_email(
            "Fehler in thinktanks.py",
            f"{THINKTANKS_JSON} nicht gefunden",
            "", "", "dein_email@example.com"  # Ersetze mit deinem Empfänger
        )
        return []
    except json.JSONDecodeError:
        logger.error(f"{THINKTANKS_JSON} ist ungültig")
        send_warning_email(
            "Fehler in thinktanks.py",
            f"{THINKTANKS_JSON} ist ungültig",
            "", "", "dein_email@example.com"
        )
        return []

def fetch_merics_emails(email_user, email_password, recipient, days=30):
    """Holt alle E-Mails von MERICS-Absendern."""
    logger.info("Starte fetch_merics_emails")
    try:
        thinktanks = load_thinktanks()
        merics = next((tt for tt in thinktanks if tt["abbreviation"] == "MERICS"), None)
        if not merics:
            logger.error("MERICS nicht in thinktanks.json gefunden")
            send_warning_email(
                "Fehler in fetch_merics_emails",
                "MERICS nicht in thinktanks.json gefunden",
                email_user, email_password, recipient
            )
            return []

        email_senders = merics["email_senders"]
        logger.info(f"Verarbeite MERICS mit Absendern: {email_senders}")

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            mail.login(email_user, email_password)
            logger.info("IMAP-Login erfolgreich")
        except Exception as e:
            logger.error(f"IMAP-Login fehlgeschlagen: {str(e)}")
            send_warning_email(
                "Fehler in fetch_merics_emails",
                f"IMAP-Login fehlgeschlagen: {str(e)}",
                email_user, email_password, recipient
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
                send_warning_email(
                    "Fehler in fetch_merics_emails",
                    f"Fehler bei der Suche nach E-Mails von {sender}: {result}",
                    email_user, email_password, recipient
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
        send_warning_email(
            "Fehler in fetch_merics_emails",
            f"Fehler beim Abrufen von MERICS-E-Mails: {str(e)}",
            email_user, email_password, recipient
        )
        return []

def main():
    """Hauptfunktion zum Testen der MERICS-E-Mail-Suche."""
    logger.info("Starte Testskript für MERICS-E-Mail-Suche")
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        logger.error("SUBSTACK_MAIL Umgebungsvariable nicht gefunden")
        send_warning_email(
            "Fehler in thinktanks.py",
            "SUBSTACK_MAIL Umgebungsvariable nicht gefunden",
            "", "", "dein_email@example.com"  # Ersetze mit deinem Empfänger
        )
        return

    mail_config = dict(pair.split("=", 1) for pair in substack_mail.split(";") if "=" in pair)
    email_user = mail_config.get("GMAIL_USER")
    email_password = mail_config.get("GMAIL_PASS")
    recipient = mail_config.get("RECIPIENT", "dein_email@example.com")  # Ersetze mit deinem Empfänger
    if not email_user or not email_password:
        logger.error("GMAIL_USER oder GMAIL_PASS fehlt in SUBSTACK_MAIL")
        send_warning_email(
            "Fehler in thinktanks.py",
            "GMAIL_USER oder GMAIL_PASS fehlt in SUBSTACK_MAIL",
            email_user, email_password, recipient
        )
        return

    emails = fetch_merics_emails(email_user, email_password, recipient, days=30)
    markdown = ["## Think Tanks", "\n### MERICS"]
    if emails:
        markdown.append("Gefundene E-Mails:")
        markdown.extend(emails)
    else:
        markdown.append("Keine MERICS-E-Mails gefunden.")

    # Ausgabe in Datei
    output_file = os.path.join(BASE_DIR, "thinktanks_briefing.md")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown))
    logger.info(f"Ergebnisse in {output_file} gespeichert")

if __name__ == "__main__":
    main()
