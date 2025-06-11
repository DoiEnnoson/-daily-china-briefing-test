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

                    # Ergebnis formatieren
                    line = f'• <a href="{link}">{title}</a> (von {sender
