import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import os
import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import urllib.parse

# ~~~ SUCHPARAMETER ~~~
EMAIL_NIKKEI_ASIA = "nikkeiasia-d-nl@namail.nikkei.com"  # E-Mail-Adresse für Nikkei Asia Newsletter
EMAIL_CHINA_UP_CLOSE = "nikkeiasia-w-nl@namail.nikkei.com"  # E-Mail-Adresse für China Up Close Newsletter
SEARCH_DAYS = 7  # Zeitfenster für die Suche (letzte 7 Tage)

def send_warning_email(subject, body):
    """Sendet eine Warn-E-Mail an hadobrockmeyer@gmail.com."""
    try:
        substack_mail = os.getenv("SUBSTACK_MAIL")
        if not substack_mail:
            print("❌ ERROR - send_warning_email: SUBSTACK_MAIL nicht gesetzt")
            return
        user_part, pass_part = substack_mail.split(";")
        email_user = user_part.split("=")[1]
        email_password = pass_part.split("=")[1]
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = email_user
        msg["To"] = "hadobrockmeyer@gmail.com"
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        print(f"Warn-E-Mail gesendet: {subject}")
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
    except Exception:
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

def fetch_combined_china_articles():
    """Holt die Top-5 China-Artikel aus Nikkei Asia und China Up Close."""
    seen_posts = set()
    articles = []
    substack_mail = os.getenv("SUBSTACK_MAIL")
    
    if not substack_mail:
        print("❌ ERROR - fetch_combined_china_articles: SUBSTACK_MAIL nicht gesetzt")
        return []

    try:
        user_part, pass_part = substack_mail.split(";")
        email_user = user_part.split("=")[1]
        email_password = pass_part.split("=")[1]
    except (ValueError, IndexError) as e:
        print(f"❌ ERROR - fetch_combined_china_articles: SUBSTACK_MAIL Format ungültig: {str(e)}")
        return []

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(email_user, email_password)
    mail.select("INBOX")
    
    since_date = (datetime.now() - timedelta(days=SEARCH_DAYS)).strftime("%d-%b-%Y")
    
    # Nikkei Asia
    try:
        result, data = mail.search(None, f'FROM {EMAIL_NIKKEI_ASIA} SINCE {since_date}')
        print(f"Nikkei Asia: {len(data[0].split())} E-Mails gefunden")
        nikkei_count = 0
        
        for eid in data[0].split():
            result, msg_data = mail.fetch(eid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        html_content = part.get_payload(decode=True).decode(charset)
                    except UnicodeDecodeError:
                        html_content = part.get_payload(decode=True).decode('windows-1252', errors='replace')
                    soup = BeautifulSoup(html_content, "html.parser")
                    links = soup.find_all("a", href=True)
                    
                    for link in links:
                        href = link.get("href")
                        title = link.get_text(strip=True)
                        if not title or len(title) < 10 or "read more" in title.lower() or "subscribe" in title.lower():
                            continue
                        final_url = resolve_url(href)
                        if not final_url or "asia.nikkei.com" not in final_url:
                            continue
                        normalized_url = normalize_url(final_url)
                        if normalized_url in seen_posts:
                            continue
                        score, is_china, is_japan = score_nikkei_article(title)
                        if score > 0 and is_china:
                            articles.append((title, final_url, score, "Nikkei Asia"))
                            seen_posts.add(normalized_url)
                            nikkei_count += 1
        print(f"Nikkei Asia: {nikkei_count} Artikel hinzugefügt")
    except Exception as e:
        print(f"❌ ERROR - fetch_combined_china_articles: Fehler bei Nikkei Asia: {str(e)}")
        send_warning_email("Fehler beim Abrufen von Nikkei Asia-Artikeln", f"Unerwarteter Fehler: {str(e)}")

    # China Up Close
    try:
        result, data = mail.search(None, f'FROM {EMAIL_CHINA_UP_CLOSE} SINCE {since_date}')
        print(f"China Up Close: {len(data[0].split())} E-Mails gefunden")
        china_up_close_count = 0
        
        for eid in data[0].split():
            result, msg_data = mail.fetch(eid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        html_content = part.get_payload(decode=True).decode(charset)
                    except UnicodeDecodeError:
                        html_content = part.get_payload(decode=True).decode('windows-1252', errors='replace')
                    soup = BeautifulSoup(html_content, "html.parser")
                    links = soup.find_all("a", href=True)
                    
                    for link in links:
                        href = link.get("href")
                        title = link.get_text(strip=True)
                        if not title or len(title) < 10 or "read more" in title.lower() or "subscribe" in title.lower():
                            continue
                        if "This week's China Up Close focuses on" in title or "Read Katsuji Nakazawa's analysis here" in title:
                            continue
                        final_url = resolve_url(href)
                        if not final_url or "asia.nikkei.com" not in final_url:
                            continue
                        normalized_url = normalize_url(final_url)
                        if normalized_url in seen_posts:
                            continue
                        score, is_china, is_important, is_indepth, is_nonchina, is_footer = score_china_up_close_article(title)
                        if score > 0:
                            articles.append((title, final_url, score, "China Up Close"))
                            seen_posts.add(normalized_url)
                            china_up_close_count += 1
        print(f"China Up Close: {china_up_close_count} Artikel hinzugefügt")
    except Exception as e:
        print(f"❌ ERROR - fetch_combined_china_articles: Fehler bei China Up Close: {str(e)}")
        send_warning_email("Fehler beim Abrufen von China Up Close-Artikeln", f"Unerwarteter Fehler: {str(e)}")

    mail.logout()
    
    # Sortiere nach Score (absteigend) und wähle die Top-5
    articles.sort(key=lambda x: x[2], reverse=True)
    articles = articles[:5]
    print(f"Top-5 Artikel ausgewählt")
    return [f"• <a href=\"{url}\">{title}</a>" for title, url, score, source in articles]

def send_article_email(china_articles):
    """Sendet eine kombinierte E-Mail mit den Top-5 China-Artikeln."""
    try:
        substack_mail = os.getenv("SUBSTACK_MAIL")
        if not substack_mail:
            print("❌ ERROR - send_article_email: SUBSTACK_MAIL nicht gesetzt")
            return
        user_part, pass_part = substack_mail.split(";")
        email_user = user_part.split("=")[1]
        email_password = pass_part.split("=")[1]
        subject = f"Nikkei Top Artikel - {datetime.now().strftime('%Y-%m-%d')}"
        
        china_section = "<p><strong>## 📜 Nikkei Top Artikel:</strong></p>\n<ul>\n"
        if china_articles:
            china_section += "".join(f"<li>{article}</li>\n" for article in china_articles)
        else:
            china_section += "<li>Keine Nikkei-Artikel gefunden.</li>\n"
        china_section += "</ul>\n"
        
        body = china_section
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = email_user
        msg["To"] = "hadobrockmeyer@gmail.com"
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        print(f"Kombinierte E-Mail gesendet: {subject}")
    except Exception as e:
        print(f"❌ ERROR - send_article_email: Fehler beim Senden der kombinierten E-Mail: {str(e)}")
        send_warning_email("Fehler beim Senden der Nikkei Top Artikel-E-Mail", f"Unerwarteter Fehler: {str(e)}")

def main():
    print(f"Starte Nikkei Top Artikel um {datetime.now()}")
    china_articles = fetch_combined_china_articles()
    send_article_email(china_articles)
    print(f"Fertig um {datetime.now()}")

if __name__ == "__main__":
    main()
