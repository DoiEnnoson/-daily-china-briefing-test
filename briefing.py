import email
import feedparser
import imaplib
import json
import os
import re
import requests
import smtplib
import time
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Pfad zu den Holiday JSON Dateien, CPR-Cache und Economic Calendar CSV (relativ zum Script-Verzeichnis)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHINA_HOLIDAY_FILE = os.path.join(BASE_DIR, "holiday_cache", "china.json")
HK_HOLIDAY_FILE = os.path.join(BASE_DIR, "holiday_cache", "hk.json")
CPR_CACHE_FILE = os.path.join(BASE_DIR, "cpr_cache.json")
ECONOMIC_CALENDAR_FILE = os.path.join(BASE_DIR, "data", "economic_calendar.csv")

def load_holidays(filepath):
    print(f"DEBUG - load_holidays: Loading holidays from {filepath}")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            holidays = set(item["date"] for item in data.get("holidays", []))
            print(f"DEBUG - load_holidays: Loaded {len(holidays)} holidays")
            return holidays
    except Exception as e:
        print(f"ERROR - load_holidays: Failed to load holidays from {filepath}: {str(e)}")
        return set()

def is_holiday(today_str, holidays_set):
    return today_str in holidays_set

def is_weekend():
    return date.today().weekday() >= 5

# CPR-Cache laden
def load_cpr_cache():
    print(f"DEBUG - load_cpr_cache: Starting to load cache from {CPR_CACHE_FILE}")
    try:
        if os.path.exists(CPR_CACHE_FILE):
            with open(CPR_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                print(f"DEBUG - load_cpr_cache: Successfully loaded cache: {cache}")
                return cache
        else:
            print(f"DEBUG - load_cpr_cache: No cache file found at {CPR_CACHE_FILE}")
            return {}
    except Exception as e:
        print(f"ERROR - load_cpr_cache: {e}")
        return {}

# CPR-Cache speichern
def save_cpr_cache(cache):
    print(f"DEBUG - save_cpr_cache: Starting to save cache to {CPR_CACHE_FILE}")
    print(f"DEBUG - save_cpr_cache: Cache content: {cache}")
    try:
        os.makedirs(os.path.dirname(CPR_CACHE_FILE), exist_ok=True)
        with open(CPR_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        print(f"DEBUG - save_cpr_cache: Successfully wrote cache to {CPR_CACHE_FILE}")
        with open(CPR_CACHE_FILE, "r", encoding="utf-8") as f:
            saved_cache = json.load(f)
            print(f"DEBUG - save_cpr_cache: Verified cache content: {saved_cache}")
    except Exception as e:
        print(f"ERROR - save_cpr_cache: Failed to save cache to {CPR_CACHE_FILE}: {str(e)}")
        raise

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

# === Wirtschaftskalender aus CSV ===
def fetch_economic_calendar():
    print("DEBUG - fetch_economic_calendar: Starting to fetch economic calendar")
    try:
        if not os.path.exists(ECONOMIC_CALENDAR_FILE):
            print(f"ERROR - fetch_economic_calendar: File {ECONOMIC_CALENDAR_FILE} not found")
            return ["### 📅 Was wichtig wird:", "", "❌ No calendar data available (file not found)."]

        df = pd.read_csv(ECONOMIC_CALENDAR_FILE, encoding="utf-8")
        print(f"DEBUG - fetch_economic_calendar: Loaded {len(df)} events from CSV")

        required_columns = ["Date", "Event", "Organisation", "Priority"]
        if not all(col in df.columns for col in required_columns):
            missing = [col for col in required_columns if col not in df.columns]
            print(f"ERROR - fetch_economic_calendar: Missing columns: {missing}")
            return ["### 📅 Was wichtig wird:", "", "❌ Invalid calendar data (missing columns)."]

        try:
            df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y")
        except Exception as e:
            print(f"ERROR - fetch_economic_calendar: Date parsing failed: {str(e)}")
            return ["### 📅 Was wichtig wird:", "", "❌ Invalid date format."]

        today = datetime.now().date()
        end_date = today + timedelta(days=7)
        df = df[(df["Date"].dt.date >= today) & (df["Date"].dt.date <= end_date)]

        if df.empty:
            today_str = today.strftime("%d/%m")
            weekday = today.strftime("%a")[:2]
            return ["### 📅 Was wichtig wird:", "", f"**📅 {weekday} {today_str}**", "- Keine Events heute."]

        # Priorität sortieren
        priority_order = {"High": 1, "Medium": 2, "Low": 3}
        df["PriorityOrder"] = df["Priority"].map(priority_order).fillna(4)
        df = df.sort_values(by=["Date", "PriorityOrder"])
        df = df.drop(columns=["PriorityOrder"])

        markdown = ["### 📅 Was wichtig wird:", ""]

        grouped = df.groupby(df["Date"])
        for date_obj, group in grouped:
            date_str = date_obj.strftime("%d/%m")
            weekday = date_obj.strftime("%a")[:2]
            markdown.append(f"**📅 {weekday} {date_str}**")  # Fettes Datum
            for _, row in group.iterrows():
                event = str(row['Event'])
                org = str(row['Organisation'])
                prio = str(row['Priority'])
                line = f"- {event} ({org}, {prio})"
                markdown.append(line)
            markdown.append("")  # Leerzeile nach jedem Datum

        print(f"DEBUG - fetch_economic_calendar: Generated {len(markdown)-2} lines")
        return markdown

    except Exception as e:
        print(f"ERROR - fetch_economic_calendar: Unexpected error: {str(e)}")
        return ["### 📅 Was wichtig wird:", "", "❌ Error fetching calendar data."]

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
    for source in source_categories:
        if f"– {source}" in title or f"- {source}" in title or title.lower().endswith(source.lower()):
            return source
    return "Unknown Source"

# === Substack aus E-Mails abrufen ===
def fetch_substack_from_email(email_user, email_password, folder="INBOX", max_results_per_sender=5):
    print(f"DEBUG - fetch_substack_from_email: Starting to fetch Substack emails")
    posts = []
    try:
        print(f"DEBUG - fetch_substack_from_email: Current working directory: {os.getcwd()}")
        print(f"DEBUG - fetch_substack_from_email: Does substacks.json exist?: {os.path.exists('substacks.json')}")
        with open("substacks.json", "r") as f:
            substack_senders = json.load(f)
        substack_senders = sorted(substack_senders, key=lambda x: x["order"])
        email_counts = defaultdict(int)
        for sender in substack_senders:
            email_counts[sender.get("email")] += 1
        duplicates = [email for email, count in email_counts.items() if count > 1 and email]
        if duplicates:
            print(f"⚠️ Warning: Duplicate email addresses in substacks.json: {duplicates}")
    except FileNotFoundError:
        print("❌ ERROR: substacks.json not found! Using empty list.")
        substack_senders = []
        posts.append(("Allgemein", "❌ Fehler: substacks.json nicht gefunden.", "#", "", 999))
    except json.JSONDecodeError:
        print("❌ ERROR: substacks.json invalid!")
        substack_senders = []
        posts.append(("Allgemein", "❌ Fehler: substacks.json ungültig.", "#", "", 999))
    
    for attempt in range(3):
        try:
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(email_user, email_password)
            imap.select(folder)
            break
        except Exception as e:
            print(f"❌ ERROR: Gmail connection failed (Attempt {attempt+1}/3): {str(e)}")
            if attempt == 2:
                return [("Allgemein", f"❌ Fehler beim Verbinden mit Gmail nach 3 Versuchen: {str(e)}", "#", "", 999)]
            time.sleep(2)
    
    try:
        since_date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
        for sender in substack_senders:
            sender_email = sender.get("email")
            sender_name = sender.get("name")
            sender_order = sender.get("order", 999)
            if not sender_email:
                print(f"❌ ERROR: Keine E-Mail-Adresse für {sender_name} angegeben.")
                continue
            try:
                search_query = f'(FROM "{sender_email}" SINCE {since_date})'
                print(f"DEBUG - fetch_substack_from_email: Searching for: {search_query}")
                typ, data = imap.search(None, search_query)
                if typ != "OK":
                    print(f"DEBUG - fetch_substack_from_email: IMAP search error for {sender_name} ({sender_email}): {data}")
                    continue
                email_ids = data[0].split()[-max_results_per_sender:]
                print(f"DEBUG - fetch_substack_from_email: Found email IDs for {sender_name}: {email_ids}")
                if not email_ids:
                    print(f"DEBUG - fetch_substack_from_email: No emails found for {sender_name} in the last 2 days.")
                    continue
                sender_posts = []
                for eid in email_ids:
                    typ, msg_data = imap.fetch(eid, "(RFC822)")
                    if typ != "OK":
                        print(f"DEBUG - fetch_substack_from_email: Error fetching mail {eid} for {sender_name}.")
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    date_str = msg["Date"]
                    mail_date = None
                    if date_str:
                        try:
                            mail_date = parsedate_to_datetime(date_str)
                            print(f"DEBUG - fetch_substack_from_email: Date for mail {eid} from {sender_name}: {mail_date}")
                        except (TypeError, ValueError) as e:
                            print(f"DEBUG - fetch_substack_from_email: Invalid date in mail {eid} from {sender_name}: {date_str}, Error: {str(e)}")
                    html = None
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/html":
                                html = part.get_payload(decode=True).decode(errors="ignore")
                                break
                    elif msg.get_content_type() == "text/html":
                        html = msg.get_payload(decode=True).decode(errors="ignore")
                    if not html:
                        print(f"DEBUG - fetch_substack_from_email: No HTML content in mail {eid} from {sender_name}.")
                        continue
                    soup = BeautifulSoup(html, "lxml")
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
                    print(f"DEBUG - fetch_substack_from_email: Title for {sender_name}: {title}")
                    link_tag = soup.find("a", href=lambda x: x and ("app-link/post" in x or "/post/" in x))
                    if not link_tag:
                        link_tag = soup.find("a", href=lambda x: x and "https://" in x)
                    link = link_tag["href"].strip() if link_tag else "#"
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
                    print(f"DEBUG - fetch_substack_from_email: Teaser for {sender_name}: {teaser}")
                    sender_posts.append((sender_name, title, link, teaser, sender_order, mail_date))
                sender_posts.sort(key=lambda x: x[5] or datetime(1970, 1, 1), reverse=True)
                posts.extend(sender_posts)
            except Exception as e:
                print(f"❌ ERROR: Error processing {sender_name} ({sender_email}): {str(e)}")
                continue
        imap.logout()
    except Exception as e:
        posts.append(("Allgemein", f"❌ Fehler beim Verbinden mit Gmail: {str(e)}", "#", "", 999))
    return posts if posts else [("Allgemein", "Keine neuen Substack-Mails gefunden.", "#", "", 999)]

# === Substack-Posts rendern ===
def render_markdown(posts):
    print(f"DEBUG - render_markdown: Rendering {len(posts)} Substack posts")
    if not posts:
        return ["Keine neuen Substack-Artikel gefunden."]
    
    grouped_posts = defaultdict(list)
    sender_orders = {}
    for post in posts:
        sender_name = post[0]
        sender_order = post[4] if len(post) > 4 else 999
        grouped_posts[sender_name].append(post)
        sender_orders[sender_name] = min(sender_orders.get(sender_name, 999), sender_order)
    
    sorted_senders = sorted(grouped_posts.keys(), key=lambda x: sender_orders.get(x, 999))
    
    markdown = []
    for sender_name in sorted_senders:
        markdown.append(f"### {sender_name}")
        for post in grouped_posts[sender_name]:
            if len(post) == 2:
                markdown.append(f"{post[1]}\n")
            else:
                title, link, teaser = post[1], post[2], post[3]
                markdown.append(f"• <a href=\"{link}\">{title}</a>")
                if teaser:
                    markdown.append(f"{teaser}")
                markdown.append("")
    
    return markdown
    
# === China Update aus YT abrufen ===
def fetch_youtube_endpoint():
    print("DEBUG - fetch_youtube_endpoint: Fetching latest China Update episode via API")
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        print("❌ ERROR - fetch_youtube_endpoint: YOUTUBE_API_KEY not found in environment variables")
        return []
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        request = youtube.search().list(
            part="snippet",
            channelId="UCy287hC44mRWpFLj4hK8gKA",
            maxResults=1,
            order="date",
            type="video"
        )
        response = request.execute()
        print(f"DEBUG - fetch_youtube_endpoint: Full API response: {response}")
        if not response.get("items"):
            print("DEBUG - fetch_youtube_endpoint: No videos found in API response")
            return []
        video = response["items"][0]
        title = video["snippet"]["title"].strip()
        video_id = video["id"]["videoId"]
        link = f"https://youtu.be/{video_id}"  # Verkürzter YouTube-Link
        thumbnail = video["snippet"].get("thumbnails", {}).get("high", {}).get("url", "")
        if not thumbnail:
            thumbnail = video["snippet"].get("thumbnails", {}).get("medium", {}).get("url", "")
        if not thumbnail:
            thumbnail = video["snippet"].get("thumbnails", {}).get("default", {}).get("url", "")
        date_str = video["snippet"]["publishedAt"]
        try:
            pub_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
            two_days_ago = datetime.now() - timedelta(days=2)
            print(f"DEBUG - fetch_youtube_endpoint: Parsed date: {pub_date}, Two days ago: {two_days_ago}")
            if pub_date < two_days_ago:
                print(f"DEBUG - fetch_youtube_endpoint: Latest video ({title}) is older than 2 days")
                return []
        except ValueError as e:
            print(f"DEBUG - fetch_youtube_endpoint: Invalid date format: {date_str}, Error: {str(e)}")
            return []
        print(f"DEBUG - fetch_youtube_endpoint: Found episode: {title} ({link}), Thumbnail: {thumbnail}")
        return [{
            "title": title,
            "link": link,
            "thumbnail": thumbnail
        }]
    except HttpError as e:
        print(f"❌ ERROR - fetch_youtube_endpoint: HTTP error from YouTube API: {str(e)}")
        return []
    except Exception as e:
        print(f"❌ ERROR - fetch_youtube_endpoint: Failed to fetch YouTube episode: {str(e)}")
        return []

# === NBS-Daten abrufen ===
def fetch_latest_nbs_data():
    print("DEBUG - fetch_latest_nbs_data: Fetching NBS data")
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
        print(f"DEBUG - fetch_latest_nbs_data: Found {len(items)} NBS items")
        return items or ["Keine aktuellen Veröffentlichungen gefunden."]
    except Exception as e:
        print(f"ERROR - fetch_latest_nbs_data: Failed to fetch NBS data: {str(e)}")
        return [f"❌ Fehler beim Abrufen der NBS-Daten: {e}"]

# === Börsendaten & Wechselkurse abrufen ===
def fetch_index_data():
    print("DEBUG - fetch_index_data: Fetching index data")
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
    print(f"DEBUG - fetch_index_data: Retrieved {len(results)} index results")
    return results

# Interpretation für USD/CNY-Spread
def interpret_usd_cny_spread(spread_pips):
    if spread_pips <= -100:
        return "CPR stark unter Markterwartungen: starker Abwertungsdruck"
    elif -99 <= spread_pips <= -20:
        return "CPR leicht stärker als Markterwartungen: leichter Abwertungsdruck"
    elif -19 <= spread_pips <= 19:
        return "CPR liegt innerhalb der Markterwartungen"
    elif 20 <= spread_pips <= 99:
        return "CPR leicht schwächer als Markterwartungen: Markt erwartet stärkeren Yuan"
    else:
        return "CPR stark über Markterwartungen: Markt drängt auf Yuan-Stärke"

# Interpretation für CNH–CNY-Spread
def interpret_cnh_cny_spread(spread_pips):
    if spread_pips <= -50:
        return "Starke CNY-Aufwertung"
    elif -49 <= spread_pips <= -10:
        return "Leichte CNY-Stärke"
    elif -9 <= spread_pips <= 9:
        return "Stabile Marktbedingungen"
    elif 10 <= spread_pips <= 49:
        return "Leichte CNY-Schwäche"
    else:
        return "Starke CNY-Abwertung"

def fetch_cpr_forexlive():
    print("DEBUG - fetch_cpr_forexlive: Starting to fetch CPR from ForexLive")
    urls = [
        "https://www.forexlive.com/CentralBanks",
        "https://www.forexlive.com/"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            articles = soup.find_all(["h2", "h3", "div"], class_=lambda x: x and ("card__title" in x or "article" in x) if x else False)
            print(f"DEBUG - fetch_cpr_forexlive: Found {len(articles)} articles on {url}")
            for article in articles:
                title = article.text.strip().lower()
                print(f"DEBUG - fetch_cpr_forexlive: Checking article: {title[:50]}...")
                if "pboc" in title and ("usd/cny" in title or "cny" in title or "reference rate" in title or "yuan" in title):
                    match = re.search(r"\d+\.\d{4}", title)
                    if match:
                        cpr = float(match.group())
                        estimate_match = re.search(r"estimate at (\d+\.\d{4})|vs\. (\d+\.\d{4})|vs\. estimate (\d+\.\d{4})", title)
                        estimate = float(estimate_match.group(1) or estimate_match.group(2) or estimate_match.group(3)) if estimate_match else None
                        if estimate is not None:
                            pips_diff = int((cpr - estimate) * 10000)
                        else:
                            pips_diff = None
                        print(f"✅ DEBUG - fetch_cpr_forexlive: Found CPR: USD/CNY = {cpr}, Estimate = {estimate}, Pips = {pips_diff}")
                        return cpr, estimate, pips_diff
            print(f"❌ DEBUG - fetch_cpr_forexlive: No CPR article found on {url}")
            print(f"DEBUG - fetch_cpr_forexlive: Sample articles: {[a.text.strip()[:50] for a in articles[:5]]}")
        except Exception as e:
            print(f"❌ ERROR - fetch_cpr_forexlive: Failed to fetch from {url}: {str(e)}")
    return None, None, None

def fetch_cpr_from_x():
    print("DEBUG - fetch_cpr_from_x: Starting to fetch CPR from X")
    headers = {"User-Agent": "Mozilla/5.0"}
    accounts = ["ForexLive", "Sino_Market"]
    for account in accounts:
        try:
            search_url = f"https://x.com/search?q=from:{account}%20PBOC%20USD/CNY%20reference%20rate"
            r = requests.get(search_url, headers=headers, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            tweets = soup.find_all("div", attrs={"data-testid": "tweetText"})
            print(f"DEBUG - fetch_cpr_from_x: Found {len(tweets)} tweets from @{account}")
            for tweet in tweets[:3]:
                text = tweet.text.strip().lower()
                print(f"DEBUG - fetch_cpr_from_x: Checking tweet: {text[:50]}...")
                if "pboc" in text and ("usd/cny" in text or "cny" in text or "reference rate" in text):
                    match = re.search(r"\d+\.\d{4}", text)
                    if match:
                        cpr = float(match.group())
                        estimate_match = re.search(r"estimate at (\d+\.\d{4})|vs\. (\d+\.\d{4})|vs\. estimate (\d+\.\d{4})", text)
                        estimate = float(estimate_match.group(1) or estimate_match.group(2) or estimate_match.group(3)) if estimate_match else 7.1820
                        pips_diff = int((cpr - estimate) * 10000)
                        print(f"✅ DEBUG - fetch_cpr_from_x: Found CPR from @{account}: USD/CNY = {cpr}, Estimate = {estimate}, Pips = {pips_diff}")
                        return cpr, estimate, pips_diff
            print(f"❌ DEBUG - fetch_cpr_from_x: No CPR post found from @{account}")
        except Exception as e:
            print(f"❌ ERROR - fetch_cpr_from_x: Failed to fetch from @{account}: {str(e)}")
    return None, None, None

def fetch_cpr_usdcny():
    print("DEBUG - fetch_cpr_usdcny: Starting to fetch CPR")
    cpr_cache = load_cpr_cache()
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    print(f"DEBUG - fetch_cpr_usdcny: Today: {today_str}, Yesterday: {yesterday_str}")

    print("DEBUG - fetch_cpr_usdcny: Trying CFETS")
    url = "https://www.chinamoney.com.cn/english/bmkcpr/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            print("❌ ERROR - fetch_cpr_usdcny: No tables found on CFETS page")
            print(f"DEBUG - fetch_cpr_usdcny: HTML excerpt: {soup.prettify()[:500]}")
        else:
            for table in tables:
                for row in table.find_all("tr")[1:]:
                    cells = row.find_all("td")
                    if len(cells) >= 2 and cells[0].text.strip() == "USD/CNY":
                        cpr_text = cells[1].text.strip()
                        try:
                            cpr = float(cpr_text)
                            print(f"✅ DEBUG - fetch_cpr_usdcny: Found CPR from CFETS: USD/CNY = {cpr}")
                            cpr_cache[today_str] = cpr
                            save_cpr_cache(cpr_cache)
                            prev_cpr = cpr_cache.get(yesterday_str)
                            return cpr, None, None, prev_cpr
                        except ValueError:
                            print(f"❌ ERROR - fetch_cpr_usdcny: Invalid CPR value '{cpr_text}'")
        print("❌ ERROR - fetch_cpr_usdcny: USD/CNY CPR not found in CFETS tables")
    except Exception as e:
        print(f"❌ ERROR - fetch_cpr_usdcny: Failed to fetch CPR from CFETS: {str(e)}")

    print("⚠️ DEBUG - fetch_cpr_usdcny: CFETS failed, trying ForexLive")
    cpr, estimate, pips_diff = fetch_cpr_forexlive()
    if cpr is not None:
        print(f"DEBUG - fetch_cpr_usdcny: Storing CPR {cpr} from ForexLive")
        cpr_cache[today_str] = cpr
        save_cpr_cache(cpr_cache)
        prev_cpr = cpr_cache.get(yesterday_str)
        return cpr, estimate, pips_diff, prev_cpr

    print("⚠️ DEBUG - fetch_cpr_usdcny: ForexLive failed, trying X posts")
    cpr, estimate, pips_diff = fetch_cpr_from_x()
    if cpr is not None:
        print(f"DEBUG - fetch_cpr_usdcny: Storing CPR {cpr} from X")
        cpr_cache[today_str] = cpr
        save_cpr_cache(cpr_cache)
        prev_cpr = cpr_cache.get(yesterday_str)
        return cpr, estimate, pips_diff, prev_cpr

    print("⚠️ DEBUG - fetch_cpr_usdcny: All sources failed, using cache or Reuters estimate")
    cpr = cpr_cache.get(today_str)
    prev_cpr = cpr_cache.get(yesterday_str)
    if cpr is not None:
        print(f"DEBUG - fetch_cpr_usdcny: Using cached CPR for today: {cpr}")
        return cpr, None, None, prev_cpr
    print("DEBUG - fetch_cpr_usdcny: No cached CPR found, using Reuters estimate")
    return None, 7.1820, None, prev_cpr

def fetch_currency_data():
    print("DEBUG - fetch_currency_data: Starting to fetch currency data")
    currencies = {
        "USDCNY": "USDCNY=X",
        "USDCNH": "USDCNH=X",
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    results = {}
    
    cpr, estimate, pips_diff, prev_cpr = fetch_cpr_usdcny()
    if cpr is not None:
        results["CPR"] = (cpr, estimate, pips_diff, prev_cpr)
    else:
        results["CPR"] = ("❌ CPR (CNY/USD): Keine Daten verfügbar.", estimate, pips_diff, prev_cpr)
    
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
    print(f"DEBUG - fetch_currency_data: Retrieved currency data: {results}")
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
    print(f"DEBUG - fetch_recent_x_posts: Fetching posts for {name} (@{account})")
    return [f"• {name} (@{account}) → {url}"]

# === Briefing generieren ===
def generate_briefing():
    print("DEBUG - generate_briefing: Starting to generate briefing")
    date_str = datetime.now().strftime("%d. %B %Y")
    briefing = [f"Guten Morgen, Hado!\n\n🗓️ {date_str}\n\n📬 Dies ist dein tägliches China-Briefing.\n"]

    # Börsenindizes
    briefing.append("\n## 📊 Börsenindizes China (08:00 Uhr MESZ)")
    if is_weekend_day or is_holiday_china:
        briefing.append("📈 Heute kein Handelstag an den chinesischen Börsen.")
    else:
        briefing.extend(fetch_index_data())
    if is_weekend_day or is_holiday_hk:
        briefing.append("📈 Heute kein Handelstag an der Hongkonger Börse.")

    # Wechselkurse
    briefing.append("\n## 💱 Wechselkurse (08:00 Uhr MESZ)")
    if is_weekend_day or is_holiday_china or is_holiday_hk:
        briefing.append("📉 Heute keine aktuellen Wechselkurse.")
    else:
        currency_data = fetch_currency_data()
        print(f"DEBUG - generate_briefing: Currency data: {currency_data}")
        try:
            with open(CPR_CACHE_FILE, "r", encoding="utf-8") as f:
                cache_content = json.load(f)
                print(f"DEBUG - generate_briefing: Cache content after fetch: {cache_content}")
        except Exception as e:
            print(f"ERROR - generate_briefing: Failed to read cache after fetch: {str(e)}")
        cpr_data = currency_data.get("CPR")
        if isinstance(cpr_data, tuple) and isinstance(cpr_data[0], float):
            cpr, estimate, pips_diff, prev_cpr = cpr_data
            print(f"DEBUG - generate_briefing: CPR={cpr}, estimate={estimate}, pips_diff={pips_diff}, prev_cpr={prev_cpr}")
            if estimate is not None:
                pips_formatted = f"Spread: CPR vs Est {pips_diff:+d} pips"
                spread_arrow = "↓" if pips_diff <= -20 else "↑" if pips_diff >= 20 else "→"
                usd_cny_interpretation = interpret_usd_cny_spread(pips_diff)
                if prev_cpr is not None:
                    pct_change = ((cpr - prev_cpr) / prev_cpr) * 100 if prev_cpr != 0 else 0
                    cpr_line = f"• CPR (CNY/USD): {cpr:.4f} ({pct_change:+.2f} %) vs. Est.: {estimate:.4f} ({pips_formatted} {spread_arrow}, {usd_cny_interpretation})"
                    print(f"DEBUG - generate_briefing: CPR line with pct_change: {cpr_line}")
                else:
                    cpr_line = f"• CPR (CNY/USD): {cpr:.4f} vs. Est.: {estimate:.4f} ({pips_formatted} {spread_arrow}, {usd_cny_interpretation})"
                    print(f"DEBUG - generate_briefing: CPR line without pct_change: {cpr_line}")
                briefing.append(cpr_line)
            else:
                if prev_cpr is not None:
                    pct_change = ((cpr - prev_cpr) / prev_cpr) * 100 if prev_cpr != 0 else 0
                    cpr_line = f"• CPR (CNY/USD): {cpr:.4f} ({pct_change:+.2f} %)"
                    print(f"DEBUG - generate_briefing: CPR line with prev_cpr: {cpr_line}")
                    briefing.append(cpr_line)
                else:
                    cpr_line = f"• CPR (CNY/USD): {cpr:.4f}"
                    print(f"DEBUG - generate_briefing: CPR line without prev_cpr: {cpr_line}")
                    briefing.append(cpr_line)
        else:
            briefing.append(str(cpr_data[0]))
            if cpr_data[1] is not None:
                briefing.append(f"  - Estimate: {cpr_data[1]:.4f}")
        if isinstance(currency_data.get("USDCNY"), tuple):
            val_cny, arrow_cny, pct_cny = currency_data["USDCNY"]
            briefing.append(f"• CNY/USD (Onshore): {val_cny:.4f} {arrow_cny} ({pct_cny:+.2f} %)")
        else:
            briefing.append(currency_data.get("USDCNY"))
        if isinstance(currency_data.get("USDCNH"), tuple):
            val_cnh, arrow_cnh, pct_cnh = currency_data["USDCNH"]
            briefing.append(f"• CNH/USD (Offshore): {val_cnh:.4f} {arrow_cnh} ({pct_cnh:+.2f} %)")
        else:
            briefing.append(currency_data.get("USDCNH"))
        if isinstance(currency_data.get("USDCNY"), tuple) and isinstance(currency_data.get("USDCNH"), tuple):
            val_cny = currency_data["USDCNY"][0]
            val_cnh = currency_data["USDCNH"][0]
            spread = val_cnh - val_cny
            spread_pips = int(spread * 10000)
            cnh_cny_interpretation = interpret_cnh_cny_spread(spread_pips)
            spread_arrow = "↓" if spread_pips <= -10 else "↑" if spread_pips >= 10 else "→"
            briefing.append(f"• Spread CNH–CNY: {spread:+.4f} {spread_arrow} ({cnh_cny_interpretation})")

    # Wirtschaftskalender
    briefing.append("")  # Leerzeile für Abstand
    briefing.extend(fetch_economic_calendar())
    
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
    briefing.append("\n## 🌎 Google News – Nach Sprache & Quelle sortiert")
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
                clean_title = clean_title[:-(len(source))].strip("- :— ").strip()
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
        briefing.append(f"\n### {category_titles.get(cat_key)}")
        for source_name, articles in sorted(sources.items()):
            if not articles:
                continue
            briefing.append(f"\n{source_name}")
            top_articles = sorted(articles, reverse=True)[:5]
            briefing.extend([a[1] for a in top_articles])

    # SCMP
    briefing.append("\n## 📺 SCMP – Top-Themen")
    briefing.extend(fetch_ranked_articles(feeds_scmp_yicai["SCMP"]))

    # Yicai
    briefing.append("\n## 📜 Yicai Global – Top-Themen")
    briefing.extend(fetch_ranked_articles(feeds_scmp_yicai["Yicai Global"]))

    # China Update YouTube
    youtube_episodes = fetch_youtube_endpoint()
    if youtube_episodes:
        briefing.append("\n### China Update")
        for episode in youtube_episodes:
            title = episode["title"]
            link = episode["link"]
            thumbnail = episode["thumbnail"]
            if thumbnail:
                # Maskierter Link mit JS-Umleitung
                briefing.append(f'<a href="#" onclick="window.location.href=\'{link}\'; return false;"><img src="{thumbnail}" alt="{title}" style="max-width: 320px; height: auto; display: block; margin: 10px 0; border: none;" class="no-preview"></a>')
            else:
                briefing.append(f'• <a href="{link}">{title}</a>')

    # Substack-Abschnitt
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
                briefing.append(f"❌ Fehler: Fehlende Schlüssel in SUBSTACK:{', '.join(missing_keys)}")
            else:
                email_user = mail_config["GMAIL_USER"]
                email_password = mail_config["GMAIL_PASS"]
                posts = fetch_substack_from_email(email_user, email_password)
                briefing.extend(render_markdown(posts))
        except ValueError as e:
            briefing.append(f"❌ Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}")

    briefing.append("\nEinen erfolgreichen Tag! 🌟")

    print("DEBUG - generate_briefing: Briefing generated successfully")
    # Debugging: HTML-Output speichern
    with open("newsletter.html", "w", encoding="utf-8") as f:
        f.write(f"""\
<html>
<head>
    <meta charset="UTF-8">
    <meta name="robots" content="noindex, nofollow, noarchive">
    <meta property="og:image" content="">
    <meta property="og:image:secure_url" content="">
    <meta property="og:image:type" content="">
    <meta property="og:image:width" content="">
    <meta property="og:image:height" content="">
    <meta property="og:type" content="website">
    <meta property="og:title" content="Daily China Briefing">
    <meta property="og:description" content="">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:image" content="">
    <meta name="twitter:image:alt" content="">
    <meta name="twitter:title" content="Daily China Briefing">
    <meta name="twitter:description" content="">
    <style>
        .no-preview {{ pointer-events: auto; }}
        a[href="#"] img {{ border: none !important; }}
    </style>
</head>
<body style="margin: 0; padding: 0;">
    <div style="background-color: #ffffff; padding: 20px;">
        <pre style="font-family: Arial, sans-serif; margin: 0;">
{chr(10).join(briefing)}\n
        </pre>
    </div>
</body>
</html>""")
    return f"""\
<html>
<head>
    <meta charset="UTF-8">
    <meta name="robots" content="noindex, nofollow, noarchive">
    <meta property="og:image" content="">
    <meta property="og:image:secure_url" content="">
    <meta property="og:image:type" content="">
    <meta property="og:image:width" content="">
    <meta property="og:image:height" content="">
    <meta property="og:type" content="website">
    <meta property="og:title" content="Daily China Briefing">
    <meta property="og:description" content="">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:image" content="">
    <meta name="twitter:image:alt" content="">
    <meta name="twitter:title" content="Daily China Briefing">
    <meta name="twitter:description" content="">
    <style>
        .no-preview {{ pointer-events: auto; }}
        a[href="#"] img {{ border: none !important; }}
    </style>
</head>
<body style="margin: 0; padding: 0;">
    <div style="background-color: #ffffff; padding: 20px;">
        <pre style="font-family: Arial, sans-serif; margin: 0;">
{chr(10).join(briefing)}\n
        </pre>
    </div>
</body>
</html>"""

# === E-Mail senden ===
def send_briefing():
    print("🧠 DEBUG - send_briefing: Starting to generate and send briefing")
    briefing_content = generate_briefing()

    msg = MIMEText(briefing_content, "html", "utf-8")
    msg["Subject"] = "📰 Dein tägliches China-Briefing"
    msg["From"] = config_dict["EMAIL_USER"]
    msg["To"] = config_dict["EMAIL_TO"]

    print("📤 DEBUG - send_briefing: Sending email")
    try:
        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        print("✅ DEBUG - send_briefing: Email sent successfully")
    except Exception as e:
        print(f"❌ ERROR - send_briefing: Failed to send email: {str(e)}")

# === Hauptskript ===
if __name__ == "__main__":
    send_briefing()
