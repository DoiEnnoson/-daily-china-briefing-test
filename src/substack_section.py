def parse_substack_articles(emails, substack_sources):
    output = ""
    for message in emails:
        subject = message.get("subject", "")
        sender = message.get("from", "")
        content = message.get("body", "")

        for source in substack_sources:
            if source["sender"] in sender and any(kw.lower() in content.lower() for kw in source["keywords"]):
                output += f"### {source['name']}\n"
                output += f"- {subject}\n\n"
                break
    return output

