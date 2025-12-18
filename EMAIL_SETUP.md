# Email Newsletter Setup Guide

This guide explains how to set up automated newsletter email sending using the Resend API.

## Prerequisites

1. **Resend Account**: Sign up at [https://resend.com](https://resend.com)
2. **Verified Domain**: Add and verify your domain in Resend dashboard
3. **API Key**: Get your API key from Resend dashboard

## Installation

1. Install required Python packages:
```bash
pip install -r requirements.txt
```

## Configuration

### 1. Set Environment Variables

Set your Resend API key and sender email as environment variables:

**On macOS/Linux:**
```bash
export RESEND_API_KEY="re_your_api_key_here"
export SENDER_EMAIL="newsletter@yourdomain.com"
```

**On Windows:**
```cmd
set RESEND_API_KEY=re_your_api_key_here
set SENDER_EMAIL=newsletter@yourdomain.com
```

**Or create a `.env` file** (recommended):
```
RESEND_API_KEY=re_your_api_key_here
SENDER_EMAIL=newsletter@yourdomain.com
```

### 2. Add Customer Emails

Edit `emails.txt` and add one email address per line:
```
customer1@example.com
customer2@example.com
customer3@example.com
```

Lines starting with `#` are treated as comments and will be ignored.

### 3. Enable Email Sending

In `generate_newsletter.py`, change:
```python
SEND_EMAILS = False  # Set to True to enable email sending
```

to:
```python
SEND_EMAILS = True  # Set to True to enable email sending
```

## Usage

1. Generate the newsletter HTML:
```bash
python generate_newsletter.py
```

2. If `SEND_EMAILS = True`, the script will automatically:
   - Read emails from `emails.txt`
   - Send the newsletter to all recipients
   - Display sending progress and summary

## Email Configuration Options

You can customize these settings in `generate_newsletter.py`:

- `SENDER_NAME`: Display name for the sender (default: "The M&A Letter")
- `EMAIL_SUBJECT`: Email subject line (default: includes issue number and date)
- `SENDER_EMAIL`: Your verified domain email address

## Troubleshooting

### "RESEND_API_KEY not set"
- Make sure you've set the environment variable or updated the `.env` file
- Restart your terminal/IDE after setting environment variables

### "Emails file not found"
- Ensure `emails.txt` exists in the same directory as the script
- Check that the file has at least one valid email address

### "Failed to send" errors
- Verify your domain is properly configured in Resend
- Check that `SENDER_EMAIL` matches a verified domain in Resend
- Ensure your Resend account has sufficient credits

## Rate Limiting

The script includes a 0.5 second delay between emails to avoid rate limiting. For large lists, consider using Resend's batch API (up to 100 emails per request).

## Security Notes

- Never commit your `RESEND_API_KEY` to version control
- Use environment variables or a `.env` file (add `.env` to `.gitignore`)
- Keep your API keys secure and rotate them periodically

