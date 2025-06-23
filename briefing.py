def send_briefing():
    print("📤 DEBUG - send_briefing: Starting to generate and send briefing")
    try:
        briefing = generate_briefing()
        print(f"DEBUG - send_briefing: Briefing content: {briefing}")

        smtp_server = "smtp.gmx.com"
        smtp_port = 587
        # Nutze SUBSTACK_MAIL für E-Mail-Adresse
        email_user = "action@gmx.com"  # Fallback, falls SUBSTACK_MAIL nur Passwort enthält
        email_password = os.getenv("SUBSTACK_MAIL")  # Passwort aus SUBSTACK_MAIL
        
        if not email_password:
            print("❌ ERROR - send_briefing: SUBSTACK_MAIL environment variable missing or empty")
            raise Exception("Missing SUBSTACK_MAIL")

        print(f"DEBUG - send_briefing: Using email user: {email_user}")
        msg = MIMEText(briefing)
        msg['Subject'] = "Daily China Briefing"
        msg['From'] = email_user
        msg['To'] = email_user

        print("DEBUG - send_briefing: Connecting to SMTP server")
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            print("DEBUG - send_briefing: Logging in to SMTP server")
            server.login(email_user, email_password)
            print("DEBUG - send_briefing: Sending email")
            server.send_message(msg)
            print("✅ DEBUG - send_briefing: Email sent successfully")
    except Exception as e:
        print(f"❌ ERROR - send_briefing: Failed to send email: {str(e)}")
        raise
