def fetch_merics_emails(email_user, email_password, days=30, max_articles=10):
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
            return [], 0

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
            return [], 0

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
                subject = decode_header(msg.get("Subject", "Kein Betreff"))
                date = msg.get("Date", "Kein Datum")
                try:
                    date = parsedate_to_datetime(date)
                except:
                    date = datetime.now()
                logger.info(f"E-Mail Betreff: {subject}, Datum: {date.strftime('%Y-%m-%d %H:%M')}")

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
                            final_url = resolve_merics_url(href)
                            if final_url.startswith("mailto:"):
                                logger.info(f"Link übersprungen: Mailto-URL {final_url}")
                                continue
                            if not title or len(title) < 10 or any(kw in title.lower() for kw in ["subscribe", "unsubscribe", "donate", "legal notice", "privacy policy", "website", "read in browser", "profile", "pdf here", "on our website", "as a pdf"]):
                                if "merics.org" in final_url and "/sites/default/files/" in final_url:
                                    title = extract_pdf_title(final_url)
                                    logger.info(f"PDF-Titel aus Dateinamen: {title}")
                                elif "merics.org" in final_url and "/report/" in final_url:
                                    web_title = scrape_web_title(final_url)
                                    title = web_title if web_title else subject
                                    logger.info(f"Web-Titel: {title}")
                                else:
                                    logger.info(f"Link übersprungen: Titel zu kurz oder unerwünscht")
                                    continue
                            normalized_url = normalize_url(final_url)
                            if normalized_url in seen_urls:
                                logger.info(f"Link übersprungen: URL bereits gesehen")
                                continue
                            score = score_thinktank_article(title, final_url)
                            if score > 0:
                                logger.info(f"Artikel hinzugefügt: {title} (URL: {final_url}, Score: {score})")
                                # Änderung: HTML-Links statt Markdown
                                articles.append((score, f'• <a href="{final_url}">{title}</a>'))
                                seen_urls.add(normalized_url)

        mail.logout()
        logger.info("IMAP-Logout erfolgreich")

        articles.sort(key=lambda x: x[0], reverse=True)
        unique_articles = []
        seen_urls.clear()
        for score, article in articles[:max_articles]:
            url_match = re.search(r'href="(.*?)"', article)
            if url_match:
                url = url_match.group(1)
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
