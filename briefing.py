import os
import json
from datetime import date, datetime, timedelta
import smtplib
import feedparser
from collections import defaultdict
import requests
from email.mime.text import MIMEText
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import imaplib
import email
import time
from email.utils import parsedate_to_datetime
import warnings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Pfad zu den Holiday JSON Dateien (relativ zum Script-Verzeichnis)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHINA_HOLIDAY_FILE = os.path.join(BASE_DIR, "holiday_cache", "china.json")
HK_HOLIDAY_FILE = os.path.join(BASE_DIR, "holiday_cache", "hk.json")

def load_holidays(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(item["date"] for item in data.get("holidays", []))
    except Exception as e:
        print(f"Fehler beim Laden der Feiertage aus {filepath}: {e}")
        return set()

def is_holiday(today_str, holidays_set):
    return today_str in holidays_set

def is_weekend():
    return date.today().weekday() >= 5

# Werte vorladen (global)
today_str = date.today().isoformat()
china_holidays = load_holidays(CHINA_HOLIDAY_FILE)
hk_holidays = load_holidays(HK_HOLIDAY_FILE)
is_holiday_china = is_holiday(today_str, china_holidays)
is_holiday_hk = is_holiday(today_str, hk_holidays)
is_weekend_day = is_weekend()

# === 🧠 Wirtschaftskalendar (Dummy) ===
def fetch_china_economic_events():
    return [
        "• 03.06. (Di) 03:45 – Caixin Manufacturing PMI (Mai) | Prognose: 50.6 | Vorher: 50.4",
        "• 05.06. (Do) 03:45 – Caixin Services PMI (Mai) | Prognose: 51.1 | Vorher: 50.7",
        "• 05.06. (Do) 03:45 – Caixin Composite PMI (Mai) | Prognose: 50.7 | Vorher: 51.1",
        "• 07.06. (Sa) 10:00 – Foreign Exchange Reserves (Mai) | Prognose: $3.35T | Vorher: $3.282T"
    ]

# === 🔐 Konfiguration aus ENV-Variable ===
config = os.getenv("CONFIG")
if not config:
    raise ValueError("CONFIG environment variable not found!")
pairs = config.split(";")
config_dict = dict(pair.split("=", 1) for pair in pairs)

# === Google Mapping ===
source_categories = {
    "Wall Street Journal": "EN",
    "Financial Times": "EN",
    "Reuters": "EN",
    "The Guardian": "EN",
    "New York Times": "EN",
    "Bloomberg": "EN",
    "Politico": "EN",
    "FAZ": "DE",
    "Welt": "DE",
    "Tagesspiegel": "DE",
    "NZZ": "DE",
    "Finanzmarktwelt": "DE",
    "Der Standard": "DE",
    "Frankfurter Rundschau": "DE",
    "Le Monde": "FR",
    "Les Echos": "FR",
    "Le Figaro": "FR",
    "SCMP": "ASIA",
    "Nikkei Asia": "ASIA",
    "Yicai": "ASIA"
}

# === Google-News: Feed-Definition ===
feeds_google_news = {
    "EN": "https://news.google.com/rss/search?q=china+when:1d&hl=en&gl=US&ceid=US:en",
    "DE": "https://news.google.com/rss/search?q=china+when:1d&hl=de&gl=DE&ceid=DE:de",
    "FR": "https://news.google.com/rss/search?q=china+when:1d&hl=fr&gl=FR&ceid=FR:fr"
}

# === Think Tanks & Institute ===
feeds_thinktanks = {
    "MERICS": "https://merics.org/en/rss.xml",
    "CSIS": "https://www.csis.org/rss.xml",
    "CREA (Energy & Clean Air)": "https://energyandcleanair.org/feed/",
    "Brookings": "https://www.brookings.edu/feed/",
    "Peterson Institute": "https://www.piie.com/rss/all",
    "CFR – Council on Foreign Relations": "https://www.cfr.org/rss.xml",
    "RAND Corporation": "https://www.rand.org/rss.xml",
    "Chatham House": "https://www.chathamhouse.org/rss.xml",
    "Lowy Institute": "https://www.lowyinstitute.org/the-interpreter/rss.xml"
}

# === Google News China Top-Stories ===
feeds_topchina = {
    "Google News – China": "https://news.google.com/rss/search?q=china+when:1d&hl=en&gl=US&ceid=US:en"
}

# === SCMP & Yicai ===
feeds_scmp_yicai = {
    "SCMP": "https://www.scmp.com/rss/91/feed",
    "Yicai Global": "https://www.yicaiglobal.com/rss/news"
}

# === China-Filter & Score-Funktionen ===
def score_article(title, summary=""):
    title = title.lower()
    summary = summary.lower()
    content = f"{title} {summary}"
    must_have_in_title = [
        "china", "chinese", "xi", "beijing", "shanghai", "hong kong", "taiwan", "prc",
        "communist party", "cpc", "byd", "alibaba", "tencent", "huawei", "li qiang", "brics",
        "belt and road", "macau", "pla"
    ]
    if not any(kw in title for kw in must_have_in_title):
        return 0
    important_keywords = [
        "gdp", "exports", "imports", "tariffs", "real estate", "economy", "policy", "ai",
        "semiconductors", "pmi", "cpi", "housing", "foreign direct investment", "tech",
        "military", "sanctions", "trade", "data", "manufacturing", "industrial"
    ]
    positive_modifiers = [
        "analysis", "explainer", "comment", "feature", "official", "report", "statement"
    ]
    negative_keywords = [
        "celebrity", "gossip", "dog", "baby", "fashion", "movie", "series", "bizarre",
        "dating", "weird", "quiz", "elon musk", "rapid", "lask", "bundesliga", "eurovision",
        "basketball", "nba", "mlb", "nfl", "liberty", "yankees", "tournament", "playoffs",
        "finale", "score", "blowout"
    ]
    score = 1
    for word in important_keywords:
        if word in content:
            score += 2
    for word in positive_modifiers:
        if word in content:
            score += 1
    for word in negative_keywords:
        if word in content:
            score -= 3
    return score

# === News-Artikel filtern & bewerten ===
def fetch_news(feed_url, max_items=20, top_n=5):
    feed = feedparser.parse(feed_url)
    scored = []
    for entry in feed.entries[:max_items]:
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        link = entry.get("link", "")
        score = score_article(title, summary)
        if score > 0:
            scored.append((score, f'• <a href="{link.strip()}">{title.strip()}</a>'))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [item[1] for item in scored[:top_n]] or ["Keine aktuellen China-Artikel gefunden."]

# === SCMP & Yicai Ranking-Wrapper ===
def fetch_ranked_articles(feed_url, max_items=20, top_n=5):
    return fetch_news(feed_url, max_items=max_items, top_n=top_n)

# === Neue Funktion: extract_source (für Google News) ===
def extract_source(title):
    """Extrahiert den Quellennamen aus dem Titel (z. B. '– Reuters')."""
    for source in source_categories:
        if f"– {source}" in title or f"- {source}" in title or title.lower().endswith(source.lower()):
            return source
    return "Unknown Source"

# === Substack aus E-Mails abrufen ===
def fetch_substack_from_email(email_user, email_password, folder="INBOX", max_results_per_sender=5):
    """Liest Substack-Mails von mehreren Absendern aus Gmail, robuste Version."""
    posts = []
    
    try:
        print(f"Debug - Aktuelles Arbeitsverzeichnis: {os.getcwd()}")
        print(f"Debug - Existiert substacks.json?: {os.path.exists('substacks.json')}")
        with open("substacks.json", "r") as f:
            substack_senders = json.load(f)
        substack_senders = sorted(substack_senders, key=lambda x: x["order"])
        # Prüfe auf doppelte E-Mail-Adressen
        email_counts = defaultdict(int)
        for sender in substack_senders:
            email_counts[sender.get("email")] += 1
        duplicates = [email for email, count in email_counts.items() if count > 1 and email]
        if duplicates:
            print(f"⚠️ Warnung: Doppelte E-Mail-Adressen in substacks.json: {duplicates}")
    except FileNotFoundError:
        print("❌ Fehler: substacks.json nicht gefunden! Verwende leere Liste.")
        substack_senders = []
        posts.append(("Allgemein", "❌ Fehler: substacks.json nicht gefunden.", "#", "", 999))
    except json.JSONDecodeError:
        print("❌ Fehler: substacks.json ungültig!")
        substack_senders = []
        posts.append(("Allgemein", "❌ Fehler: substacks.json ungültig.", "#", "", 999))
    
    # Retry-Logik für Gmail-Verbindung
    for attempt in range(3):
        try:
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(email_user, email_password)
            imap.select(folder)
            break
        except Exception as e:
            print(f"❌ Verbindung zu Gmail fehlgeschlagen (Versuch {attempt+1}/3): {str(e)}")
            if attempt == 2:
                return [("Allgemein", f"❌ Fehler beim Verbinden mit Gmail nach 3 Versuchen: {str(e)}", "#", "", 999)]
            time.sleep(2)
    
    try:
        # Datumsfilter: Letzte 3 Tage
        since_date = (datetime.now() - timedelta(days=3)).strftime("%d-%b-%Y")
        for sender in substack_senders:
            sender_email = sender.get("email")
            sender_name = sender.get("name")
            sender_order = sender.get("order", 999)  # Fallback für fehlenden order-Wert
            if not sender_email:
                posts.append((sender_name, f"❌ Keine E-Mail-Adresse für {sender_name} angegeben.", "#", "", sender_order))
                continue
            try:
                # Suche: Alle Mails seit since_date von Absender
                search_query = f'(FROM "{sender_email}" SINCE {since_date})'
                print(f"Debug - Suche nach: {search_query}")
                typ, data = imap.search(None, search_query)
                if typ != "OK":
                    print(f"Debug - IMAP-Suchfehler für {sender_name} ({sender_email}): {data}")
                    posts.append((sender_name, f"❌ Fehler beim Suchen nach Mails von {sender_name} ({sender_email}).", "#", "", sender_order))
                    continue
                email_ids = data[0].split()[-max_results_per_sender:]
                print(f"Debug - Gefundene Mail-IDs für {sender_name}: {email_ids}")
                if not email_ids:
                    posts.append((sender_name, f"📭 Keine Mails von {sender_name} in den letzten 3 Tagen gefunden.", "#", "", sender_order))
                    continue
                # Temporäre Liste für Beiträge dieses Senders
                sender_posts = []
                for eid in email_ids:
                    typ, msg_data = imap.fetch(eid, "(RFC822)")
                    if typ != "OK":
                        sender_posts.append((sender_name, f"❌ Fehler beim Abrufen der Mail {eid} von {sender_name}.", "#", "", sender_order, None))
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    date_str = msg["Date"]
                    mail_date = None
                    if date_str:
                        try:
                            mail_date = parsedate_to_datetime(date_str)
                            print(f"Debug - Datum für Mail {eid} von {sender_name}: {mail_date}")
                        except (TypeError, ValueError) as e:
                            print(f"Debug - Ungültiges Datum in Mail {eid} von {sender_name}: {date_str}, Fehler: {str(e)}")
                    else:
                        print(f"Debug - Kein Datum in Mail {eid} von {sender_name}")
                    html = None
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/html":
                                html = part.get_payload(decode=True).decode(errors="ignore")
                                break
                    elif msg.get_content_type() == "text/html":
                        html = msg.get_payload(decode=True).decode(errors="ignore")
                    if not html:
                        sender_posts.append((sender_name, f"❌ Kein HTML-Inhalt in der Mail {eid} von {sender_name}.", "#", "", sender_order, mail_date))
                        continue
                    soup = BeautifulSoup(html, "lxml")
                    # Erweiterte Titel-Suche
                    title_tag = (soup.find("h1") or 
                                soup.find("h2") or 
                                soup.find("h3") or 
                                soup.find("p", class_=lambda x: x and "title" in x.lower()) or
                                soup.find("div", class_=lambda x: x and "title" in x.lower()) or
                                soup.find("span", class_=lambda x: x and "title" in x.lower()))
                    if not title_tag:
                        link_tag = soup.find("a", href=lambda x: x and "/post/" in x)
                        if link_tag and link_tag.text.strip():
                            title = link_tag.text.strip()
                        else:
                            title = msg["Subject"].strip() if msg["Subject"] else "Unbenannter Beitrag"
                    else:
                        title = title_tag.text.strip()
                    print(f"Debug - Titel für {sender_name}: {title}")
                    # Link-Suche
                    link_tag = soup.find("a", href=lambda x: x and ("app-link/post" in x or "/post/" in x))
                    if not link_tag:
                        link_tag = soup.find("a", href=lambda x: x and "https://" in x)
                    link = link_tag["href"].strip() if link_tag else "#"
                    # Verbesserte Teaser-Suche
                    teaser = ""
                    if title_tag or link_tag:
                        start_tag = title_tag or link_tag
                        content_candidates = start_tag.find_all_next(string=True)
                        found_title = False
                        teaser_parts = []
                        for text in content_candidates:
                            stripped = text.strip()
                            if not found_title and stripped and (stripped in title or stripped in link):
                                found_title = True
                                continue
                            if (found_title and 30 < len(stripped) < 500 and 
                                "dear reader" not in stripped.lower() and 
                                "subscribe" not in stripped.lower() and 
                                "view in browser" not in stripped.lower()):
                                teaser_parts.append(stripped)
                                if len(" ".join(teaser_parts)) > 100:
                                    break
                        teaser = " ".join(teaser_parts).strip()[:300]
                    print(f"Debug - Teaser für {sender_name}: {teaser}")
                    sender_posts.append((sender_name, title, link, teaser, sender_order, mail_date))
                # Sortiere Beiträge nach Datum (neuester zuerst)
                sender_posts.sort(key=lambda x: x[5] or datetime(1970, 1, 1), reverse=True)
                # Füge sortierte Beiträge zu posts hinzu
                posts.extend(sender_posts)
            except Exception as e:
                posts.append((sender_name, f"❌ Fehler bei der Verarbeitung von {sender_name} ({sender_email}): {str(e)}", "#", "", sender_order))
        imap.logout()
    except Exception as e:
        posts.append(("Allgemein", f"❌ Fehler beim Verbinden mit Gmail: {str(e)}", "#", "", 999))
    return posts if posts else [("Allgemein", "Keine neuen Substack-Mails gefunden.", "#", "", 999)]

# === Substack-Posts rendern ===
def render_markdown(posts):
    """Erzeugt Markdown für Substack-Beiträge, mit einer Überschrift pro Substack."""
    if not posts:
        return ["Keine neuen Substack-Artikel gefunden."]
    
    # Gruppiere Beiträge nach sender_name und speichere den order-Wert
    grouped_posts = defaultdict(list)
    sender_orders = {}
    for post in posts:
        sender_name = post[0]
        sender_order = post[4] if len(post) > 4 else 999  # sender_order ist an Position 4
        grouped_posts[sender_name].append(post)
        sender_orders[sender_name] = min(sender_orders.get(sender_name, 999), sender_order)
    
    # Sortiere Substacks nach sender_order
    sorted_senders = sorted(grouped_posts.keys(), key=lambda x: sender_orders.get(x, 999))
    
    markdown = []
    for sender_name in sorted_senders:
        markdown.append(f"### {sender_name}")
        for post in grouped_posts[sender_name]:
            if len(post) == 2:  # Fehlerfall (z. B. "📭 Keine Mails")
                markdown.append(f"{post[1]}\n")
            else:  # Normaler Beitrag
                title, link, teaser = post[1], post[2], post[3]
                markdown.append(f"• <a href=\"{link}\">{title}</a>")
                if teaser:
                    markdown.append(f"{teaser}")
                markdown.append("")
    
    return markdown

# === NBS-Daten abrufen ===
def fetch_latest_nbs_data():
    url = "http://www.stats.gov.cn/english/PressRelease/rss.xml"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for li in soup.select("ul.list_009 li")[:5]:
            a = li.find("a")
            if a and a.text:
                title = a.text.strip()
                link = "https://www.stats.gov.cn" + a["href"]
                items.append(f"• {title} ({link})")
        return items or ["Keine aktuellen Veröffentlichungen gefunden."]
    except Exception as e:
        return [f"❌ Fehler beim Abrufen der NBS-Daten: {e}"]

# === Börsendaten & Wechselkurse abrufen ===
def fetch_index_data():
    indices = {
        "Hang Seng Index (HSI)": "^HSI",
        "Hang Seng China Enterprises (HSCEI)": "^HSCE",
        "SSE Composite Index (Shanghai)": "000001.SS",
        "Shenzhen Component Index": "399001.SZ"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    results = []
    for name, symbol in indices.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            if len(closes) < 2 or not all(closes[-2:]):
                results.append(f"❌ {name}: Keine gültigen Kursdaten verfügbar.")
                continue
            prev_close = closes[-2]
            last_close = closes[-1]
            change = last_close - prev_close
            pct = (change / prev_close) * 100
            arrow = "→" if abs(pct) < 0.01 else "↑" if change > 0 else "↓"
            results.append(f"• {name}: {round(last_close,2)} {arrow} ({pct:+.2f} %)")
        except Exception as e:
            results.append(f"❌ {name}: Fehler beim Abrufen ({e})")
    return results

def fetch_currency_data():
    currencies = {
        "USDCNY": "USDCNY=X",
        "USDCNH": "USDCNH=X",
        "HKDUSD": "HKDUSD=X",
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    results = {}
    for name, symbol in currencies.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            if not data.get("chart") or not data["chart"].get("result"):
                results[name] = f"❌ {name}: Keine Daten in der API-Antwort."
                continue
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            prev_close = result.get("meta", {}).get("chartPreviousClose")
            if not closes or len(closes) == 0 or prev_close is None:
                results[name] = f"❌ {name}: Keine gültigen Kursdaten verfügbar (closes={closes}, prev_close={prev_close})."
                continue
            last_close = closes[-1]
            if len(closes) == 1:
                change = last_close - prev_close
                pct = (change / prev_close) * 100 if prev_close != 0 else 0
            else:
                prev_close = closes[-2]
                change = last_close - prev_close
                pct = (change / prev_close) * 100 if prev_close != 0 else 0
            arrow = "→" if abs(pct) < 0.01 else "↑" if change > 0 else "↓"
            results[name] = (last_close, arrow, pct)
        except Exception as e:
            results[name] = f"❌ {name}: Unerwarteter Fehler ({str(e)})"
    return results

# === Stimmen von X ===
x_accounts = [
    {"account": "Sino_Market", "name": "CN Wire", "url": "https://x.com/Sino_Market"},
    {"account": "tonychinaupdate", "name": "China Update", "url": "https://x.com/tonychinaupdate"},
    {"account": "YuanTalks", "name": "YUAN TALKS", "url": "https://x.com/YuanTalks"},
    {"account": "Brad_Setser", "name": "Brad Setser", "url": "https://x.com/Brad_Setser"},
    {"account": "KennedyCSIS", "name": "Scott Kennedy", "url": "https://x.com/KennedyCSIS"},
]

def fetch_recent_x_posts(account, name, url):
    return [f"• {name} (@{account}) → {url}"]

# === Briefing generieren ===
def generate_briefing():
    date_str = datetime.now().strftime("%d. %B %Y")
    briefing = [f"Guten Morgen, Hado!\n\n🗓️ {date_str}\n\n📬 Dies ist dein tägliches China-Briefing.\n"]

    # Börsenindizes
    briefing.append("\n## 📊 Börsenindizes China (08:00 Uhr MESZ)")
    if is_weekend_day or is_holiday_china:
        briefing.append("📈 Heute kein Handelstag an den chinesischen Börsen.")
    else:
        briefing.extend(fetch_index_data())
    if is_weekend_day or is_holiday_hk:
        briefing.append("📈 Heute kein Handelstag an der Börse Hongkong.")

    # Wechselkurse
    briefing.append("\n## 💱 Wechselkurse (08:00 Uhr MESZ)")
    if is_weekend_day or is_holiday_china or is_holiday_hk:
        briefing.append("📉 Heute keine aktuellen Wechselkurse.")
    else:
        currency_data = fetch_currency_data()
        if isinstance(currency_data.get("HKDUSD"), tuple):
            val, arrow, pct = currency_data["HKDUSD"]
            val_inv = 1 / val
            pct_inv = -pct
            arrow_inv = "→" if abs(pct_inv) < 0.01 else "↑" if pct_inv > 0 else "↓"
            briefing.append(f"• CPR (HKD/USD): {val_inv:.4f} {arrow_inv} ({pct_inv:+.2f} %)")
        else:
            briefing.append(currency_data.get("HKDUSD"))
        if isinstance(currency_data.get("USDCNY"), tuple):
            val_cny, arrow_cny, pct_cny = currency_data["USDCNY"]
            briefing.append(f"• USD/CNY (Onshore): {val_cny:.4f} {arrow_cny} ({pct_cny:+.2f} %)")
        else:
            briefing.append(currency_data.get("USDCNY"))
        if isinstance(currency_data.get("USDCNH"), tuple):
            val_cnh, arrow_cnh, pct_cnh = currency_data["USDCNH"]
            briefing.append(f"• USD/CNH (Offshore): {val_cnh:.4f} {arrow_cnh} ({pct_cnh:+.2f} %)")
        else:
            briefing.append(currency_data.get("USDCNH"))
        if isinstance(currency_data.get("USDCNY"), tuple) and isinstance(currency_data.get("USDCNH"), tuple):
            val_cny = currency_data["USDCNY"][0]
            val_cnh = currency_data["USDCNH"][0]
            spread = val_cnh - val_cny
            briefing.append(f"• Spread CNH–CNY: {spread:+.4f}")

    # Top 5 China-Stories
    briefing.append("\n## 🏆 Top 5 China-Stories laut Google News")
    for source, url in feeds_topchina.items():
        briefing.append(f"\n### {source}")
        briefing.extend(fetch_news(url, max_items=30, top_n=5))

    # NBS-Daten
    briefing.append("\n## 📈 NBS – Nationale Statistikdaten")
    briefing.extend(fetch_latest_nbs_data())

    # X-Stimmen
    briefing.append("\n## 📡 Stimmen & Perspektiven von X")
    for acc in x_accounts:
        briefing.extend(fetch_recent_x_posts(acc["account"], acc["name"], acc["url"]))

    # Google News nach Sprache/Quelle
    briefing.append("\n## 🌍 Google News – Nach Sprache & Quelle sortiert")
    all_articles = {
        "EN": defaultdict(list),
        "DE": defaultdict(list),
        "FR": defaultdict(list),
        "ASIA": defaultdict(list),
        "OTHER": defaultdict(list)
    }
    for lang, url in feeds_google_news.items():
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            score = score_article(title, summary)
            if score <= 0:
                continue
            source = extract_source(title)
            category = source_categories.get(source, lang if lang in ["EN", "DE", "FR"] else "OTHER")
            if source in ["SCMP", "Nikkei Asia", "Yicai"]:
                category = "ASIA"
            clean_title = title
            if f"– {source}" in title:
                clean_title = title.split(f"– {source}")[0].strip()
            elif f"- {source}" in title:
                clean_title = title.split(f"- {source}")[0].strip()
            if clean_title.lower().endswith(source.lower()):
                clean_title = clean_title[:-(len(source))].strip("-:—– ").strip()
            all_articles[category][source].append((score, f'• <a href="{link}">{clean_title}</a>'))
    category_titles = {
        "EN": "🇺🇸 Englischsprachige Medien",
        "DE": "🇩🇪 Deutschsprachige Medien",
        "FR": "🇫🇷 Französische Medien",
        "ASIA": "🌏 Asiatische Medien",
        "OTHER": "🧪 Sonstige Quellen"
    }
    for cat_key, sources in all_articles.items():
        if not sources:
            continue
        briefing.append(f"\n## {category_titles.get(cat_key, cat_key)}")
        for source_name, articles in sorted(sources.items()):
            if not articles:
                continue
            briefing.append(f"\n### {source_name}")
            top_articles = sorted(articles, reverse=True)[:5]
            briefing.extend([a[1] for a in top_articles])

    # SCMP
    briefing.append("\n## SCMP – Top-Themen")
    briefing.extend(fetch_ranked_articles(feeds_scmp_yicai["SCMP"]))

    # Yicai
    briefing.append("\n## Yicai Global – Top-Themen")
    briefing.extend(fetch_ranked_articles(feeds_scmp_yicai["Yicai Global"]))

    # Neuer Substack-Abschnitt
    briefing.append("\n## 📬 Aktuelle Substack-Artikel")
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        briefing.append("❌ Fehler: SUBSTACK_MAIL Umgebungsvariable nicht gefunden!")
    else:
        try:
            mail_pairs = substack_mail.split(";")
            mail_config = {}
            for pair in mail_pairs:
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    mail_config[key] = value
            if "GMAIL_USER" not in mail_config or "GMAIL_PASS" not in mail_config:
                missing_keys = [k for k in ["GMAIL_USER", "GMAIL_PASS"] if k not in mail_config]
                briefing.append(f"❌ Fehler: Fehlende Schlüssel in SUBSTACK_MAIL: {', '.join(missing_keys)}")
            else:
                email_user = mail_config["GMAIL_USER"]
                email_password = mail_config["GMAIL_PASS"]
                posts = fetch_substack_from_email(email_user, email_password)
                briefing.extend(render_markdown(posts))
        except ValueError as e:
            briefing.append(f"❌ Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}")

    briefing.append("\nEinen erfolgreichen Tag! 🌟")

    return f"""\
<html>
  <body>
    <pre style="font-family: system-ui, sans-serif">
{chr(10).join(briefing)}
    </pre>
  </body>
</html>"""

# === E-Mail senden ===
print("🧠 Erzeuge Briefing...")
briefing_content = generate_briefing()

msg = MIMEText(briefing_content, "html", "utf-8")
msg["Subject"] = "📰 Dein tägliches China-Briefing"
msg["From"] = config_dict["EMAIL_USER"]
msg["To"] = config_dict["EMAIL_TO"]

print("📤 Sende E-Mail...")
try:
    with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
        server.starttls()
        server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
        server.send_message(msg)
    print("✅ E-Mail wurde gesendet!")
except Exception as e:
    print("❌ Fehler beim Senden der E-Mail:", str(e))
