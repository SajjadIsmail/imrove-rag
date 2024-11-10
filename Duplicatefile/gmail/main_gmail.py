from email_handler_gmail import load_credentials, connect_to_email, fetch_unread_emails

# Load credentials
user, password = load_credentials()

# Connect to email and process unread emails
with connect_to_email(user, password) as mailbox:
    for email in fetch_unread_emails(mailbox):
        # Print the content of each unread email from INBOX
        print("Email Subject:", email['subject'])
        print("Sender:", email['sender'])
        print("Body:\n", email['body'])
        print("=" * 50)  # Separator for readability
