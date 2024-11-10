from imap_tools import MailBox, AND
import yaml
import html2text


def load_credentials():
    with open("credentials.yml") as f:
        content = yaml.load(f, Loader=yaml.FullLoader)
    return content["user_gmail"], content["password_gmail"]


def connect_to_email(user, password):
    # Connect to the mailbox
    mailbox = MailBox('imap.gmail.com').login(user, password)
    return mailbox

def fetch_unread_emails(mailbox):
    # Fetch unread emails and yield their main details
    for email in mailbox.fetch(AND(seen=False)):
        yield {
            'subject': email.subject,
            'sender': email.from_,
            'body': extract_email_body(email.obj)  # Extract only the main body
        }

def extract_email_body(email_message):
    """
    Extracts and returns only the main text content of an email,
    handling both plain text and HTML parts.
    """
    main_body = ""
    if email_message.is_multipart():
        for part in email_message.walk():
            # Process only text or HTML parts
            if part.get_content_type() in ["text/plain", "text/html"]:
                # Decode the content
                content = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8')
                # Convert HTML to plain text if needed
                if part.get_content_type() == "text/html":
                    content = html2text.html2text(content)
                main_body += content + "\n\n"  # Append each part with a separator
    else:
        # Single-part email
        main_body = email_message.get_payload(decode=True).decode(email_message.get_content_charset() or 'utf-8')

    return main_body.strip()  # Clean up any extra whitespace
