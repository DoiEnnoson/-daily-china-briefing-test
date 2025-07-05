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
import urllib.parse

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

def normalize_url(url):
    """Entfernt Tracking-Parameter aus der URL."""
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

def resolve_url(url):
    """Löst die ursprüngliche URL zu einer asia.nikkei.com-URL auf."""
    try:
        response = requests.get(url, allow_redirects=True, timeout=5)
        final_url = response.url
        if "asia.nikkei.com" in final_url:
            return final_url
        return None
    except Exception as e:
        print(f"DEBUG - resolve_url: Fehler beim Auflösen der URL {url}: {str(e)}")
        return None

def score_nikkei_article(title):
    """Bewertet einen Artikel auf China-Relevanz."""
    score = 0
    china_keywords = ["china", "chinese", "hong kong", "taiwan", "xi jinping", "beijing", "shanghai"]
    japan_keywords = ["japan", "japanese", "tokyo"]
    has_china = any(keyword in title.lower() for keyword in china_keywords)
    has_japan = any(keyword in title.lower() for keyword in japan_keywords)
    
    if has_china:
        score += 5
    if has_japan:
        score -= 3
    if not has_china and not has_japan:
        score -= 1
    return score, has_china, has_japan

def score_china_up_close_article(title):
    """Bewertet einen China Up Close-Artikel."""
    score = 0
    is_china = any(keyword in title.lower() for keyword in ["china", "chinese", "hong kong", "taiwan", "xi jinping"])
    is_important = any(keyword in title.lower() for keyword in ["xi jinping", "politburo", "policy"])
    is_indepth = any(keyword in title.lower() for keyword in ["analysis", "in depth", "cover"])
    is_nonchina = any(keyword in title.lower() for keyword in ["japan", "india", "us", "europe"])
    is_footer = any(keyword in title.lower() for keyword in ["subscribe", "newsletter", "app"])
    
    if is_china:
        score += 5
    if is_important:
        score += 3
    if is_indepth:
        score += 3
    if is_nonchina:
        score -= 2
    if is_footer:
        score -= 5
    return score, is_china, is_important, is_indepth, is_nonchina, is_footer

def fetch_nikkei_from_email():
    """Holt Nikkei Asia-Artikel aus E-Mails."""
    seen_posts = set()
    articles = []
    try:
        substack_mail = os.getenv("SUBSTACK_MAIL")
        if not substack_mail:
            print("❌ ERROR - fetch_nikkei_from_email: SUBSTACK_MAIL nicht gesetzt")
            return articles
        user_part, pass_part = substack_mail.split(";")
        email_user = user_part.split("=")[1]
        email_password = pass_part.split("=")[1]
        
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_user, email_password)
        mail.select("INBOX")
        
        since_date = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        result, data = mail.search(None, f'FROM nikkeiasia-d-nl@namail.nikkei.com SINCE {since_date}')
        print(f"DEBUG - fetch_nikkei_from_email: Suche: FROM nikkeiasia-d-nl@namail.nikkei.com SINCE {since_date}")
        print(f"DEBUG - fetch_nikkei_from_email: Gefundene E-Mail-IDs: {len(data[0].split())}")
        
        for eid in data[0].split():
            result, msg_data = mail.fetch(eid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = decode_header(msg["subject"])[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()
            print(f"DEBUG - fetch_nikkei_from_email: Verarbeite E-Mail b'{eid}', Betreff: {subject}")
            
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        html_content = part.get_payload(decode=True).decode(charset)
                    except UnicodeDecodeError:
                        print(f"DEBUG - fetch_nikkei_from_email: UnicodeDecodeError mit {charset}, versuche windows-1252")
                        html_content = part.get_payload(decode=True).decode('windows-1252', errors='replace')
                    with open(f"nikkei_email_{eid.decode()}.html", "w", encoding="utf-8") as f:
                        f.write(html_content)
                    print(f"DEBUG - fetch_nikkei_from_email: HTML für E-Mail b'{eid}' gespeichert: nikkei_email_{eid.decode()}.html")
                    
                    soup = BeautifulSoup(html_content, "html.parser")
                    links = soup.find_all("a", href=True)
                    print(f"DEBUG - fetch_nikkei_from_email: Gefundene Links mit 'nikkei.com': {len([l for l in links if 'nikkei.com' in l.get('href')])}")
                    
                    for link in links:
                        href = link.get("href")
                        title = link.get_text(strip=True)
                        if not title or len(title) < 10 or "read more" in title.lower() or "subscribe" in title.lower():
                            print(f"DEBUG - fetch_nikkei_from_email: Überspringe Titel '{title}' (zu kurz oder generisch)")
                            continue
                        final_url = resolve_url(href)
                        if not final_url or "asia.nikkei.com" not in final_url:
                            print(f"DEBUG - fetch_nikkei_from_email: Überspringe nicht-asia.nikkei.com URL: {final_url}")
                            continue
                        normalized_url = normalize_url(final_url)
                        if normalized_url in seen_posts:
                            print(f"DEBUG - fetch_nikkei_from_email: Überspringe Duplikat URL: {normalized_url}")
                            continue
                        score, is_china, is_japan = score_nikkei_article(title)
                        if score > 0 and is_china:
                            articles.append((title, final_url, score))
                            seen_posts.add(normalized_url)
                            print(f"DEBUG - fetch_nikkei_from_email: Artikel hinzugefügt: '{title[:50]}...', Score: {score}")
        
        mail.logout()
        articles.sort(key=lambda x: x[2], reverse=True)
        articles = articles[:5]
        print(f"DEBUG - fetch_nikkei_from_email: Rückgabe von {len(articles)} Artikeln")
        return [f"• <a href=\"{url}\">{title}</a>" for title, url, score in articles]
    except Exception as e:
        print(f"❌ ERROR - fetch_nikkei_from_email: Fehler: {str(e)}")
        send_warning_email("Fehler beim Abrufen von Nikkei-Artikeln", f"Unerwarteter Fehler: {str(e)}")
        return []

def fetch_china_up_close_from_email():
    """Holt China Up Close-Artikel aus E-Mails."""
    seen_posts = set()
    articles = []
    try:
        substack_mail = os.getenv("SUBSTACK_MAIL")
        if not substack_mail:
            print("❌ ERROR - fetch_china_up_close_from_email: SUBSTACK_MAIL nicht gesetzt")
            return articles
        user_part, pass_part = substack_mail.split(";")
        email_user = user_part.split("=")[1]
        email_password = pass_part.split("=")[1]
        
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_user, email_password)
        mail.select("INBOX")
        
        since_date = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        result, data = mail.search(None, f'FROM nikkeiasia-w-nl@namail.nikkei.com SINCE {since_date}')
        print(f"DEBUG - fetch_china_up_close_from_email: Suche: FROM nikkeiasia-w-nl@namail.nikkei.com SINCE {since_date}")
        print(f"DEBUG - fetch_china_up_close_from_email: Gefundene E-Mail-IDs: {len(data[0].split())}")
        
        for eid in data[0].split():
            result, msg_data = mail.fetch(eid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = decode_header(msg["subject"])[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()
            print(f"DEBUG - fetch_china_up_close_from_email: Verarbeite E-Mail b'{eid}', Betreff: {subject}")
            
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        html_content = part.get_payload(decode=True).decode(charset)
                    except UnicodeDecodeError:
                        print(f"DEBUG - fetch_china_up_close_from_email: UnicodeDecodeError mit {charset}, versuche windows-1252")
                        html_content = part.get_payload(decode=True).decode('windows-1252', errors='replace')
                    with open(f"china_up_close_email_{eid.decode()}.html", "w", encoding="utf-8") as f:
                        f.write(html_content)
                    print(f"DEBUG - fetch_china_up_close_from_email: HTML für E-Mail b'{eid}' gespeichert: china_up_close_email_{eid.decode()}.html")
                    
                    soup = BeautifulSoup(html_content, "html.parser")
                    links = soup.find_all("a", href=True)
                    print(f"DEBUG - fetch_china_up_close_from_email: Gefundene Links mit 'nikkei.com': {len([l for l in links if 'nikkei.com' in l.get('href')])}")
                    
                    for link in links:
                        href = link.get("href")
                        title = link.get_text(strip=True)
                        if not title or len(title) < 10 or "read more" in title.lower() or "subscribe" in title.lower():
                            print(f"DEBUG - fetch_china_up_close_from_email: Überspringe Titel '{title}' (zu kurz oder generisch)")
                            continue
                        if "This week's China Up Close focuses on" in title or "Read Katsuji Nakazawa's analysis here" in title:
                            print(f"DEBUG - fetch_china_up_close_from_email: Überspringe Einleitungstext '{title[:50]}...'")
                            continue
                        final_url = resolve_url(href)
                        if not final_url or "asia.nikkei.com" not in final_url:
                            print(f"DEBUG - fetch_china_up_close_from_email: Überspringe nicht-asia.nikkei.com URL: {final_url}")
                            continue
                        normalized_url = normalize_url(final_url)
                        if normalized_url in seen_posts:
                            print(f"DEBUG - fetch_china_up_close_from_email: Überspringe Duplikat URL: {normalized_url}")
                            continue
                        score, is_china, is_important, is_indepth, is_nonchina, is_footer = score_china_up_close_article(title)
                        if score > 0:
                            articles.append((title, final_url, score))
                            seen_posts.add(normalized_url)
                            print(f"DEBUG - fetch_china_up_close_from_email: Artikel hinzugefügt: '{title[:50]}...', Score: {score}")
        
        mail.logout()
        articles.sort(key=lambda x: x[2], reverse=True)
        articles = articles[:5]
        print(f"DEBUG - fetch_china_up_close_from_email: Rückgabe von {len(articles)} Artikeln")
        return [f"• <a href=\"{url}\">{title}</a>" for title, url, score in articles]
    except Exception as e:
        print(f"❌ ERROR - fetch_china_up_close_from_email: Fehler: {str(e)}")
        send_warning_email("Fehler beim Abrufen von China Up Close-Artikeln", f"Unerwarteter Fehler: {str(e)}")
        return []

def send_article_email(nikkei_posts, china_posts):
    """Sendet eine kombinierte E-Mail mit Nikkei Asia Briefing und China Up Close Artikeln."""
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
        subject = f"Nikkei Asia Briefing & China Up Close - {datetime.now().strftime('%Y-%m-%d')}"
        
        nikkei_section = "<p><strong>## 📜 Nikkei Asia – Top-Themen:</strong></p>\n<ul>\n"
        if nikkei_posts:
            nikkei_section += "".join(f"<li>{post}</li>\n" for post in nikkei_posts)
        else:
            nikkei_section += "<li>Keine Nikkei-Artikel gefunden.</li>\n"
        nikkei_section += "</ul>\n"
        
        china_section = "<p><strong>## 📜 Nikkei China Up Close:</strong></p>\n<ul>\n"
        if china_posts:
            china_section += "".join(f"<li>{post}</li>\n" for post in china_posts)
        else:
            china_section += "<li>Keine China Up Close-Artikel gefunden.</li>\n"
        china_section += "</ul>\n"
        
        body = nikkei_section + "<br>\n" + china_section
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = email_user
        msg["To"] = "hadobrockmeyer@gmail.com"
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        print(f"DEBUG - send_article_email: Kombinierte E-Mail gesendet: {subject}")
    except Exception as e:
        print(f"❌ ERROR - send_article_email: Fehler beim Senden der kombinierten E-Mail: {str(e)}")
        send_warning_email("Fehler beim Senden der Nikkei-E-Mail", f"Unerwarteter Fehler: {str(e)}")

def main():
    print(f"DEBUG - main: Starte Nikkei-Test um {datetime.now()}")
    print("DEBUG - main: Starte Nikkei Asia Briefing")
    nikkei_posts = fetch_nikkei_from_email()
    print("DEBUG - main: Starte China Up Close")
    china_posts = fetch_china_up_close_from_email()
    send_article_email(nikkei_posts, china_posts)

if __name__ == "__main__":
    main()
