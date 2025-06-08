def parse_substack_articles(emails, substack_sources):
    """
    Liest die Emails aus, filtert nach Substack-Quellen aus substack_sources.yaml
    und formatiert die Artikel für das Briefing.

    emails: Liste von Emails (jeweils als Dict oder Objekt mit keys 'from', 'subject', 'body', 'link' etc.)
    substack_sources: Liste von Substack-Quellen aus der YAML-Datei, mit Feldern 'name', 'email', 'order' etc.

    Rückgabe: formatierter String für das Briefing
    """
    output = ""

    # sortiere Quellen nach 'order' für Reihenfolge im Briefing
    sorted_sources = sorted(substack_sources, key=lambda x: x.get('order', 99))

    for source in sorted_sources:
        source_name = source.get('name', 'Unknown')
        source_email = source.get('email', '').lower()

        # Filtere Emails, die von der Quelle stammen (Absender-Email stimmt überein)
        filtered_emails = [
            email for email in emails
            if email.get('from', '').lower().find(source_email) != -1
        ]

        if not filtered_emails:
            continue  # keine Artikel von dieser Quelle

        # Ausgabe der Überschrift für die Substack-Quelle
        output += f"### {source_name}\n\n"

        # für
