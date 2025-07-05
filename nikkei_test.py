import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import os
import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import time

def send_warning_email(subject, body):
    """Sendet eine Warn-E-Mail an hadobrockmeyer@gmail.com."""
    try:
        substack_mail = os.getenv("SUBSTACK_MAIL")
        if not substack_mail:
            print("❌ ERROR - send_warning_email: SUBSTACK_MAIL nicht gesetzt")
            return
        try:
            user_part, pass_part = substack_mail.split(";")
            email_user = user_part.split("=")[1]
            email_password = pass_part.split("=")[1]
        except (ValueError, IndexError) as e:
            print(f"❌ ERROR - send_warning_email: SUBSTACK_MAIL Format ungültig (erwartet: GMAIL_USER=email;GMAIL_PASS=pass, bekommen: {substack_mail})")
            return
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = email_user
        msg["To"] = "hadobrockmeyer@gmail.com"
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        print(f"DEBUG - send_warning_email: Warn-E-Mail gesendet: {subject}")
    except Exception as e:
        print(f"❌ ERROR - send_warning_email: Fehler beim Senden der Warn-E-Mail: {str(e)}")

def send_article_email(posts, newsletter_type="Nikkei Asia Briefing"):
    """Sendet eine E-Mail mit den gefundenen Artikeln an hadobrockmeyer@gmail.com."""
    try:
        substack_mail = os.getenv("SUBSTACK_MAIL")
        if not substack_mail:
            print("❌ ERROR - send_article_email: SUBSTACK_MAIL nicht gesetzt")
            return
        try:
            user_part, pass_part = substack_mail.split(";")
            email_user = user_part.split("=")[1]
            email_password = pass_part.split("=")[1]
        except (ValueError, IndexError) as e:
            print(f"❌ ERROR - send_article_email: SUBSTACK_MAIL Format ungültig (erwartet: GMAIL_USER=email;GMAIL_PASS=pass, bekommen: {substack_mail})")
            return
        subject = f"{newsletter_type} - {datetime.now().strftime('%Y-%m-%d')}"
        if posts:
            formatted_posts = []
            for post in posts:
                soup = BeautifulSoup(post, "lxml")
                link_tag = soup.find("a")
                if link_tag:
                    title = link_tag.get_text(strip=True)
                    url = link_tag.get("href", "#")
                    formatted_posts.append(f'• <a href="{url}">{title}</a><br>')
            header = f"## 📜 {newsletter_type}:"
            body = f"<p>{header}</p>\n" + "".join(formatted_posts)
        else:
            body = f"<p>Keine {newsletter_type}-Artikel gefunden.</p>"
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = email_user
        msg["To"] = "hadobrockmeyer@gmail.com"
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        print(f"DEBUG - send_article_email: E-Mail mit Artikeln gesendet: {subject}")
    except Exception as e:
        print(f"❌ ERROR - send_article_email: Fehler beim Senden der Artikel-E-Mail: {str(e)}")

def score_nikkei_article(title):
    """Bewertet einen Artikel auf China-Relevanz."""
    title_lower = title.lower()
    must_have_keywords = [
        "china", "chinese", "xi", "beijing", "shanghai", "hong kong", "taiwan", "prc",
        "communist party", "cpc", "byd", "alibaba", "tencent", "huawei", "li qiang", "brics",
        "belt and road", "macau", "pla", "guangdong", "shenzhen"
    ]
    important_keywords = [
        "gdp", "exports", "imports", "tariffs", "real estate", "economy", "policy", "ai",
        "semiconductors", "pmi", "cpi", "housing", "foreign direct investment", "tech",
        "military", "sanctions", "trade", "data", "manufacturing", "industrial", "ev"
    ]
    positive_modifiers = [
        "analysis", "explainer", "comment", "feature", "official", "report", "statement",
        "in depth", "commentary", "deep dive"
    ]
    negative_keywords = [
        "japan", "tokyo", "nikkei 225", "yen", "korea", "seoul", "india", "asean",
        "celebrity", "gossip", "dog", "baby", "fashion", "movie", "series", "bizarre",
        "dating", "weird", "quiz", "elon musk", "rapid", "lask", "bundesliga", "eurovision",
        "basketball", "nba", "mlb", "nfl", "liberty", "yankees", "tournament", "playoffs",
        "finale", "score", "blowout", "thai", "us", "usa", "america"
    ]
    footer_phrases = [
        "subscribe", "unsubscribe", "nikkei asia", "newsletters", "mobile apps", "sign up",
        "read online", "enjoy unlimited access"
    ]
    score = 0
    has_china = any(kw in title_lower for kw in must_have_keywords)
    has_japan = any(kw in title_lower for kw in negative_keywords if kw in ["japan", "tokyo", "yen", "nikkei 225"])
    if has_china:
        score += 3
    if has_china and has_japan:
        score += 2  # Bonus für China-Japan-Beziehungen
    if any(kw in title_lower for kw in important_keywords):
        score += 2
    if any(kw in title_lower for kw in positive_modifiers):
        score += 1
    if any(kw in title_lower for kw in negative_keywords):
        score -= 3
    if any(kw in title_lower for kw in footer_phrases):
        score = 0
    print(f"DEBUG - score_nikkei_article: Titel '{title[:50]}...': Score {score}, China: {has_china}, Japan: {has_japan}")
    return max(score, 0)

def fetch_nikkei_from_email(email_user, email_password, folder="INBOX", max_results=5):
    """Holt Nikkei Asia Briefing-Artikel aus E-Mails."""
    print(f"DEBUG - fetch_nikkei_from_email: Start fetching Nikkei emails at {datetime.now()}")
    today = datetime.now()
    is_weekend = today.weekday() >= 5  # Samstag (5) oder Sonntag (6)
    if is_weekend:
        print("DEBUG - fetch_nikkei_from_email: Wochenende, überspringe Nikkei-Abschnitt")
        return []
    
    if not email_user or not email_password:
        print("❌ ERROR - fetch_nikkei_from_email: E-Mail oder Passwort fehlt")
        send_warning_email("Keine Nikkei-Artikel gefunden", "Fehler: E-Mail oder Passwort fehlt.")
        return []

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        for attempt in range(3):
            try:
                imap.login(email_user, email_password)
                imap.select(folder)
                print(f"DEBUG - fetch_nikkei_from_email: Erfolgreich bei Gmail eingeloggt, Ordner {folder} ausgewählt")
                break
            except Exception as e:
                print(f"❌ ERROR - fetch_nikkei_from_email: Gmail-Verbindung fehlgeschlagen (Versuch {attempt+1}/3): {str(e)}")
                if attempt == 2:
                    send_warning_email("Keine Nikkei-Artikel gefunden", f"Fehler: Konnte nicht mit Gmail verbinden: {str(e)}")
                    return []
                time.sleep(2)
    except Exception as e:
        print(f"❌ ERROR - fetch_nikkei_from_email: Verbindungsfehler: {str(e)}")
        send_warning_email("Keine Nikkei-Artikel gefunden", f"Fehler: Konnte nicht mit Gmail verbinden: {str(e)}")
        return []

    try:
        since_date = (today - timedelta(days=1)).strftime("%d-%b-%Y")
        sender = "nikkeiasia-d-nl@namail.nikkei.com"
        search_query = f'FROM {sender} SINCE {since_date}'
        print(f"DEBUG - fetch_nikkei_from_email: Suche: {search_query}")
        typ, data = imap.search(None, search_query.encode('utf-8'))
        if typ != "OK":
            print(f"❌ ERROR - fetch_nikkei_from_email: IMAP-Suche fehlgeschlagen: {data}")
            send_warning_email("Keine Nikkei-Artikel gefunden", "Fehler: Keine E-Mails gefunden.")
            imap.logout()
            return []
        
        email_ids = data[0].split()
        print(f"DEBUG - fetch_nikkei_from_email: Gefundene E-Mail-IDs: {len(email_ids)}")
        if not email_ids:
            send_warning_email("Keine Nikkei-Artikel gefunden", "Keine E-Mails in den letzten 24 Stunden gefunden.")
            imap.logout()
            return []

        scored_posts = []
        generic_titles = {"read more", "click here", "learn more", "view online", "subscribe now", "full story", "continue reading", "nikkei asia", "newsletters"}
        for eid in email_ids[:5]:
            typ, msg_data = imap.fetch(eid, "(RFC822)")
            if typ != "OK":
                print(f"❌ ERROR - fetch_nikkei_from_email: Fehler beim Abrufen von E-Mail {eid}")
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = decode_header(msg.get("Subject", "No Subject"))[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()
            print(f"DEBUG - fetch_nikkei_from_email: Verarbeite E-Mail {eid}, Betreff: {subject}")

            html = None
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html = part.get_payload(decode=True).decode(errors="ignore")
                        break
            elif msg.get_content_type() == "text/html":
                html = msg.get_payload(decode=True).decode(errors="ignore")
            if not html:
                print(f"❌ ERROR - fetch_nikkei_from_email: Kein HTML-Inhalt in E-Mail {eid}")
                continue
            
            with open(f"nikkei_email_{eid}.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"DEBUG - fetch_nikkei_from_email: HTML für E-Mail {eid} gespeichert: nikkei_email_{eid}.html")

            soup = BeautifulSoup(html, "lxml")
            links = soup.find_all("a", href=lambda x: x and "nikkei.com" in x.lower())
            print(f"DEBUG - fetch_nikkei_from_email: Gefundene Links mit 'nikkei.com': {len(links)}")

            for link_tag in links:
                title = link_tag.get_text(strip=True)
                title_lower = title.lower()
                if not title or len(title) < 10 or title_lower in generic_titles or len(title.split()) < 5:
                    print(f"DEBUG - fetch_nikkei_from_email: Überspringe Titel '{title}' (zu kurz oder generisch)")
                    continue
                better_title = None
                parent = link_tag.find_parent(["p", "h1", "h2", "h3", "div"])
                if parent:
                    title_tag = parent.find_previous(["h1", "h2", "h3", "p"]) or parent
                    candidate = title_tag.get_text(strip=True)
                    candidate_lower = candidate.lower()
                    if candidate and len(candidate) >= 10 and len(candidate.split()) >= 5 and candidate_lower not in generic_titles:
                        better_title = candidate
                        print(f"DEBUG - fetch_nikkei_from_email: Besserer Titel gefunden: '{better_title[:50]}...'")
                final_title = better_title or title or subject
                if final_title.lower() in generic_titles or len(final_title.split()) < 5:
                    print(f"DEBUG - fetch_nikkei_from_email: Überspringe finalen Titel '{final_title[:50]}...' (generisch oder zu kurz)")
                    continue
                link = link_tag.get("href", "#").strip()
                if not link or link == "#" or "unsubscribe" in link.lower():
                    print(f"DEBUG - fetch_nikkei_from_email: Überspringe ungültigen Link: {link}")
                    continue
                try:
                    response = requests.head(link, allow_redirects=True, timeout=5)
                    final_url = response.url
                    print(f"DEBUG - fetch_nikkei_from_email: URL aufgelöst: {link[:50]}... zu {final_url[:50]}...")
                except Exception as e:
                    print(f"DEBUG - fetch_nikkei_from_email: URL-Auflösung fehlgeschlagen: {link[:50]}...: {str(e)}")
                    final_url = link
                if "nikkei.com" not in final_url.lower():
                    print(f"DEBUG - fetch_nikkei_from_email: Überspringe nicht-nikkei.com URL: {final_url[:50]}...")
                    continue
                score = score_nikkei_article(final_title)
                if score > 0:
                    scored_posts.append((score, f'• <a href="{final_url}">{final_title}</a>'))
                    print(f"DEBUG - fetch_nikkei_from_email: Artikel hinzugefügt: '{final_title[:50]}...', Score: {score}")
        
        scored_posts.sort(reverse=True, key=lambda x: x[0])
        posts = [item[1] for item in scored_posts[:max_results]]
        if not posts:
            send_warning_email("Keine Nikkei-Artikel gefunden", "Keine China-relevanten Artikel in den E-Mails gefunden.")
        imap.logout()
        print(f"DEBUG - fetch_nikkei_from_email: Rückgabe von {len(posts)} Artikeln")
        return posts
    except Exception as e:
        print(f"❌ ERROR - fetch_nikkei_from_email: Unerwarteter Fehler: {str(e)}")
        send_warning_email("Keine Nikkei-Artikel gefunden", f"Unerwarteter Fehler: {str(e)}")
        imap.logout()
        return []

def fetch_china_up_close_from_email(email_user, email_password, folder="INBOX", max_results=5):
    """Holt China Up Close-Artikel aus E-Mails."""
    print(f"DEBUG - fetch_china_up_close_from_email: Start fetching China Up Close emails at {datetime.now()}")
    
    if not email_user or not email_password:
        print("❌ ERROR - fetch_china_up_close_from_email: E-Mail oder Passwort fehlt")
        send_warning_email("Keine China Up Close-Artikel gefunden", "Fehler: E-Mail oder Passwort fehlt.")
        return []

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        for attempt in range(3):
            try:
                imap.login(email_user, email_password)
                imap.select(folder)
                print(f"DEBUG - fetch_china_up_close_from_email: Erfolgreich bei Gmail eingeloggt, Ordner {folder} ausgewählt")
                break
            except Exception as e:
                print(f"❌ ERROR - fetch_china_up_close_from_email: Gmail-Verbindung fehlgeschlagen (Versuch {attempt+1}/3): {str(e)}")
                if attempt == 2:
                    send_warning_email("Keine China Up Close-Artikel gefunden", f"Fehler: Konnte nicht mit Gmail verbinden: {str(e)}")
                    return []
                time.sleep(2)
    except Exception as e:
        print(f"❌ ERROR - fetch_china_up_close_from_email: Verbindungsfehler: {str(e)}")
        send_warning_email("Keine China Up Close-Artikel gefunden", f"Fehler: Konnte nicht mit Gmail verbinden: {str(e)}")
        return []

    try:
        since_date = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")  # Letzte 7 Tage, da wöchentlich
        sender = "nikkeiasia-d-nl@namail.nikkei.com"  # Annahme, gleicher Absender
        search_query = f'FROM {sender} "China Up Close" SINCE {since_date}'
        print(f"DEBUG - fetch_china_up_close_from_email: Suche: {search_query}")
        typ, data = imap.search(None, search_query.encode('utf-8'))
        if typ != "OK":
            print(f"❌ ERROR - fetch_china_up_close_from_email: IMAP-Suche fehlgeschlagen: {data}")
            send_warning_email("Keine China Up Close-Artikel gefunden", "Fehler: Keine E-Mails gefunden.")
            imap.logout()
            return []
        
        email_ids = data[0].split()
        print(f"DEBUG - fetch_china_up_close_from_email: Gefundene E-Mail-IDs: {len(email_ids)}")
        if not email_ids:
            send_warning_email("Keine China Up Close-Artikel gefunden", "Keine E-Mails in den letzten 7 Tagen gefunden.")
            imap.logout()
            return []

        scored_posts = []
        generic_titles = {"read more", "click here", "learn more", "view online", "subscribe now", "full story", "continue reading", "nikkei asia", "newsletters"}
        for eid in email_ids[:5]:
            typ, msg_data = imap.fetch(eid, "(RFC822)")
            if typ != "OK":
                print(f"❌ ERROR - fetch_china_up_close_from_email: Fehler beim Abrufen von E-Mail {eid}")
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = decode_header(msg.get("Subject", "No Subject"))[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()
            print(f"DEBUG - fetch_china_up_close_from_email: Verarbeite E-Mail {eid}, Betreff: {subject}")

            html = None
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html = part.get_payload(decode=True).decode(errors="ignore")
                        break
            elif msg.get_content_type() == "text/html":
                html = msg.get_payload(decode=True).decode(errors="ignore")
            if not html:
                print(f"❌ ERROR - fetch_china_up_close_from_email: Kein HTML-Inhalt in E-Mail {eid}")
                continue
            
            with open(f"china_up_close_email_{eid}.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"DEBUG - fetch_china_up_close_from_email: HTML für E-Mail {eid} gespeichert: china_up_close_email_{eid}.html")

            soup = BeautifulSoup(html, "lxml")
            links = soup.find_all("a", href=lambda x: x and "nikkei.com" in x.lower())
            print(f"DEBUG - fetch_china_up_close_from_email: Gefundene Links mit 'nikkei.com': {len(links)}")

            for link_tag in links:
                title = link_tag.get_text(strip=True)
                title_lower = title.lower()
                if not title or len(title) < 10 or title_lower in generic_titles or len(title.split()) < 5:
                    print(f"DEBUG - fetch_china_up_close_from_email: Überspringe Titel '{title}' (zu kurz oder generisch)")
                    continue
                better_title = None
                parent = link_tag.find_parent(["p", "h1", "h2", "h3", "div"])
                if parent:
                    title_tag = parent.find_previous(["h1", "h2", "h3", "p"]) or parent
                    candidate = title_tag.get_text(strip=True)
                    candidate_lower = candidate.lower()
                    if candidate and len(candidate) >= 10 and len(candidate.split()) >= 5 and candidate_lower not in generic_titles:
                        better_title = candidate
                        print(f"DEBUG - fetch_china_up_close_from_email: Besserer Titel gefunden: '{better_title[:50]}...'")
                final_title = better_title or title or subject
                if final_title.lower() in generic_titles or len(final_title.split()) < 5:
                    print(f"DEBUG - fetch_china_up_close_from_email: Überspringe finalen Titel '{final_title[:50]}...' (generisch oder zu kurz)")
                    continue
                link = link_tag.get("href", "#").strip()
                if not link or link == "#" or "unsubscribe" in link.lower():
                    print(f"DEBUG - fetch_china_up_close_from_email: Überspringe ungültigen Link: {link}")
                    continue
                try:
                    response = requests.head(link, allow_redirects=True, timeout=5)
                    final_url = response.url
                    print(f"DEBUG - fetch_china_up_close_from_email: URL aufgelöst: {link[:50]}... zu {final_url[:50]}...")
                except Exception as e:
                    print(f"DEBUG - fetch_china_up_close_from_email: URL-Auflösung fehlgeschlagen: {link[:50]}...: {str(e)}")
                    final_url = link
                if "nikkei.com" not in final_url.lower():
                    print(f"DEBUG - fetch_china_up_close_from_email: Überspringe nicht-nikkei.com URL: {final_url[:50]}...")
                    continue
                score = score_nikkei_article(final_title)
                if score > 0:
                    scored_posts.append((score, f'• <a href="{final_url}">{final_title}</a>'))
                    print(f"DEBUG - fetch_china_up_close_from_email: Artikel hinzugefügt: '{final_title[:50]}...', Score: {score}")
        
        scored_posts.sort(reverse=True, key=lambda x: x[0])
        posts = [item[1] for item in scored_posts[:max_results]]
        if not posts:
            send_warning_email("Keine China Up Close-Artikel gefunden", "Keine China-relevanten Artikel in den E-Mails gefunden.")
        imap.logout()
        print(f"DEBUG - fetch_china_up_close_from_email: Rückgabe von {len(posts)} Artikeln")
        return posts
    except Exception as e:
        print(f"❌ ERROR - fetch_china_up_close_from_email: Unerwarteter Fehler: {str(e)}")
        send_warning_email("Keine China Up Close-Artikel gefunden", f"Unerwarteter Fehler: {str(e)}")
        imap.logout()
        return []

def main():
    """Hauptfunktion zum Testen."""
    print(f"DEBUG - main: Starte Nikkei-Test um {datetime.now()}")
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        print("❌ ERROR - main: SUBSTACK_MAIL nicht gesetzt")
        send_warning_email("Keine Nikkei-Artikel gefunden", "Fehler: SUBSTACK_MAIL nicht gesetzt.")
        return
    try:
        user_part, pass_part = substack_mail.split(";")
        email_user = user_part.split("=")[1]
        email_password = pass_part.split("=")[1]
    except (ValueError, IndexError) as e:
        print(f"❌ ERROR - main: SUBSTACK_MAIL Format ungültig (erwartet: GMAIL_USER=email;GMAIL_PASS=pass, bekommen: {substack_mail})")
        send_warning_email("Keine Nikkei-Artikel gefunden", f"Fehler: SUBSTACK_MAIL Format ungültig: {str(e)}")
        return
    
    # Nikkei Asia Briefing
    print("\nDEBUG - main: Starte Nikkei Asia Briefing")
    nikkei_posts = fetch_nikkei_from_email(email_user, email_password)
    print("\n## 📜 Nikkei Asia – Top-Themen:")
    if nikkei_posts:
        for post in nikkei_posts:
            print(post)
        send_article_email(nikkei_posts, "Nikkei Asia Briefing")
    else:
        print("Keine Nikkei-Artikel gefunden.")
        send_warning_email("Keine Nikkei-Artikel gefunden", "Keine China-relevanten Artikel in den E-Mails gefunden.")

    # China Up Close
    print("\nDEBUG - main: Starte China Up Close")
    china_posts = fetch_china_up_close_from_email(email_user, email_password)
    print("\n## 📜 Nikkei China Up Close:")
    if china_posts:
        for post in china_posts:
            print(post)
        send_article_email(china_posts, "Nikkei China Up Close")
    else:
        print("Keine China Up Close-Artikel gefunden.")
        send_warning_email("Keine China Up Close-Artikel gefunden", "Keine China-relevanten Artikel in den E-Mails gefunden.")

if __name__ == "__main__":
    main()
