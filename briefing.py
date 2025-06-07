import os
import smtplib
import feedparser
from collections import defaultdict
import requests
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import imaplib
import email


# === Substack Mail-Konfiguration laden ===
substack_mail = os.getenv("SUBSTACK_MAIL")
if not substack_mail:
    raise ValueError("SUBSTACK_MAIL environment variable not found!")

mail_pairs = substack_mail.split(";")
mail_config = dict(pair.split("=", 1) for pair in mail_pairs)


# === 🧠 Wirtschaftskalendar (Dummy) ===

def fetch_china_economic_events():
    # Platzhalterfunktion – liefert statischen Dummy-Text zurück
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

# === Google Mapping  ===
source_categories = {
    # EN/US/UK
    "Wall Street Journal": "EN",
    "Financial Times": "EN",
    "Reuters": "EN",
    "The Guardian": "EN",
    "New York Times": "EN",
    "Bloomberg": "EN",
    "Politico": "EN",
    
    # Deutschsprachig
    "FAZ": "DE",
    "Welt": "DE",
    "Tagesspiegel": "DE",
    "NZZ": "DE",
    "Finanzmarktwelt": "DE",
    "Der Standard": "DE",
    "Frankfurter Rundschau": "DE",

    # Französisch
    "Le Monde": "FR",
    "Les Echos": "FR",
    "Le Figaro": "FR",

    # Asiatisch
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

# === Substack-Feeds: Bleibt noch als als Ruecfalloption - Substacks werden per Mail abgerufen ===
feeds_substack = {
    "Sinocism – Bill Bishop": "https://sinocism.com/feed",
    "ChinaTalk – Jordan Schneider": "https://chinatalk.substack.com/feed",
    "Pekingology": "https://pekingnology.substack.com/feed",
    "The Rare Earth Observer": "https://treo.substack.com/feed",
    "Baiguan": "https://www.baiguan.news/feed",
    "Bert’s Newsletter": "https://berthofman.substack.com/feed",
    "Hong Kong Money Never Sleeps": "https://moneyhk.substack.com/feed",
    "Tracking People’s Daily": "https://trackingpeoplesdaily.substack.com/feed",
    "Interconnected": "https://interconnect.substack.com/feed",
    "Ginger River Review": "https://www.gingerriver.com/feed",
    "The East is Read": "https://www.eastisread.com/feed",
    "Inside China – Fred Gao": "https://www.fredgao.com/feed",
    "China Business Spotlight": "https://chinabusinessspotlight.substack.com/feed",
    "ChinAI Newsletter": "https://chinai.substack.com/feed",
    "Tech Buzz China Insider": "https://techbuzzchina.substack.com/feed",
    "Sinical China": "https://www.sinicalchina.com/feed",
    "Observing China": "https://www.observingchina.org.uk/feed"
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
    """Bewertet Artikel anhand von China-Relevanz im Titel – nicht nur generisch."""
    title = title.lower()
    summary = summary.lower()
    content = f"{title} {summary}"

    # Diese Begriffe müssen im Titel vorkommen – sonst kein China-Bezug
    must_have_in_title = [
        "china", "chinese", "xi", "beijing", "shanghai", "hong kong", "taiwan", "prc",
        "communist party", "cpc", "byd", "alibaba", "tencent", "huawei", "li qiang", "brics", 
        "belt and road", "macau", "pla"
    ]

    # Wenn nichts davon im Titel, gibt's gar keinen Score
    if not any(kw in title for kw in must_have_in_title):
        return 0

    # Danach Scoring nach wirtschaftlicher/geopolitischer Relevanz
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
        "dating", "weird", "quiz", "elon musk", "rapid", "lask", "bundesliga", "eurovision", "basketball", "nba", "mlb", "nfl", "liberty", "yankees", "tournament", "playoffs", "finale", "score", "blowout" 
    
    ]

    score = 1  # Basisscore, wenn Titel China-relevant ist

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
    """Holt Artikel, bewertet Relevanz und gibt die besten top_n zurück."""
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
    """Wendet denselben Bewertungsfilter wie fetch_news an, speziell für SCMP & Yicai."""
    return fetch_news(feed_url, max_items=max_items, top_n=top_n)

# === Google News Extraction ===

def extract_source(title):
    known_sources = [
        "Bloomberg", "Reuters", "Financial Times", "Wall Street Journal", "WSJ",
        "The Guardian", "New York Post", "Yahoo Finance", "Yahoo News", "AP News",
        "CNN", "NBC", "MSNBC", "Fox News", "South China Morning Post", "SCMP",
        "JURIST", "Global Times", "CSIS", "Al Jazeera", "ION Analytics", "ABC News",
        "Deseret News", "Nasdaq", "Pork Business", "Focus Taiwan", "Hawaii News Now",
        "France 24", "Le Monde", "Zonebourse", "China.org.cn", "Telepolis", 
        "Spiegel", "NZZ", "Handelsblatt", "FAZ", "Zeit Online", "T-Online", 
        "Finanzen.net", "Wallstreet Online", "MSN", "BörsenNEWS.de", "Börse Online",
        "ComputerBase", "Vietnam.vn", "OneFootball", "ARD Mediathek"
    ]

    for source in known_sources:
        if source.lower() in title.lower():
            return source

    # Fallback: entferne " – Quelle" am Ende
    if " – " in title:
        return title.split(" – ")[-1].strip()
    if "-" in title and len(title.split("-")[-1]) < 40:
        return title.split("-")[-1].strip()

    return "Unbekannt"


# === Substack Mail-Konfiguration laden ===
substack_mail = os.getenv("SUBSTACK_MAIL")
if not substack_mail:
    raise ValueError("SUBSTACK_MAIL environment variable not found!")

mail_pairs = substack_mail.split(";")
mail_config = dict(pair.split("=", 1) for pair in mail_pairs)


# === Substack via Gmail abrufen ===
def fetch_substack_from_email(email_user, email_password, folder="INBOX", max_results=1):
    """Liest Substack-Mails aus Gmail, extrahiert Titel + echten Teaser + Link."""
    import imaplib
    import email
    from bs4 import BeautifulSoup

    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(email_user, email_password)
    imap.select(folder)

    typ, data = imap.search(None, '(UNSEEN FROM "China Business Spotlight")')
    if typ != "OK":
        return ["❌ Fehler beim Suchen nach Substack-Mails."]

    posts = []
    email_ids = data[0].split()[-max_results:]
    for eid in reversed(email_ids):
        typ, msg_data = imap.fetch(eid, "(RFC822)")
        if typ != "OK":
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
            continue

        soup = BeautifulSoup(html, "html.parser")

        # Titel
        title_tag = soup.find("h1")
        title = title_tag.text.strip() if title_tag else "Unbenannter Beitrag"

        # Link (erstes <a> mit "https" im href)
        link_tag = soup.find("a", href=lambda x: x and "https://" in x)
        link = link_tag["href"].strip() if link_tag else "#"

        # Teaser: Versuche, echten Artikeltext unter dem Titel zu finden
        teaser = ""
        if title_tag:
            content_candidates = title_tag.find_all_next(string=True)
            for text in content_candidates:
                stripped = text.strip()
                if 30 < len(stripped) < 300 and "dear reader" not in stripped.lower():
                    teaser = stripped
                    break

        # Ergebnis zusammenbauen
        line = f'• <a href="{link}">{title}</a>'
        if teaser:
            line += f" – {teaser}"
        posts.append(line)

    imap.logout()
    return posts if posts else ["Keine neuen Substack-Mails gefunden."]




# === NBS-Daten abrufen ===
def fetch_latest_nbs_data():
    url = "https://www.stats.gov.cn/sj/zxfb/"
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

# === Börsendaten abrufen ===
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

    briefing.append("\n## 📊 Börsenindizes China (08:00 Uhr MESZ)")
    briefing.extend(fetch_index_data())

    # === Top 5 China-Stories laut Google News ===
    briefing.append("\n## 🏆 Top 5 China-Stories laut Google News")
    for source, url in feeds_topchina.items():
        briefing.append(f"\n### {source}")
        briefing.extend(fetch_news(url, max_items=30, top_n=5))

    briefing.append("\n## 📈 NBS – Nationale Statistikdaten")
    briefing.extend(fetch_latest_nbs_data())

    briefing.append("\n## 📡 Stimmen & Perspektiven von X")
    for acc in x_accounts:
        briefing.extend(fetch_recent_x_posts(acc["account"], acc["name"], acc["url"]))

    # === 🌍 Google News – Nach Sprache & Quelle sortiert ===
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

            # Titel bereinigen (entferne Quelle am Anfang oder Ende)
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

    briefing.append("\n## 📬 China-Fokus: Substack-Briefings")
    briefing.append("Aktuell im Testbetrieb: China Business Spotlight per Mail. Weitere Substack-Feeds folgen.")


    briefing.append("\n## SCMP – Top-Themen")
    briefing.extend(fetch_ranked_articles(feeds_scmp_yicai["SCMP"]))

    briefing.append("\n## Yicai Global – Top-Themen")
    briefing.extend(fetch_ranked_articles(feeds_scmp_yicai["Yicai Global"]))

        # === Testlauf für Mail-Briefing China Business Spotlight ===
    briefing.append("\n## 🧪 Test: China Business Spotlight per Mail")
    briefing.extend(fetch_substack_from_email(
        email_user=mail_config["GMAIL_USER"],
        email_password=mail_config["GMAIL_PASS"]
    ))


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
