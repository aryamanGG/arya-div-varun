import json
import re
import time
import os
from pathlib import Path
from html import escape

import requests  # pip3 install requests
from resend import Resend  # pip3 install resend

# ---------- CONFIG ----------
JSON_PATH = Path("output.json")
TEMPLATE_PATH = Path("template_base.html")

HTML_OUTPUT_PATH = Path("newsletter_issue_0001.html")
CONTEXT_OUTPUT_PATH = Path("contexts.txt")
EMAILS_FILE_PATH = Path("emails.txt")

ISSUE_DATE = "November 26, 2025"
ISSUE_NUMBER = "0001"

OLLAMA_MODEL = "llama3.2"
MAX_CHARS_FOR_AI = 2000

# Test mode (limit number of articles while developing)
TEST_MODE = True
TEST_COUNT = 20

# Email configuration
SEND_EMAILS = False  # Set to True to enable email sending
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")  # Get from environment variable
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "newsletter@yourdomain.com")  # Your verified domain email
SENDER_NAME = "The M&A Letter"
EMAIL_SUBJECT = f"The M&A Letter - Issue {ISSUE_NUMBER} ({ISSUE_DATE})"


# ---------- LOAD ARTICLES ----------
def load_articles(json_path: Path):
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------- DATE HANDLING ----------
MONTH_MAP = {
    "Jan.": "Jan", "January": "Jan",
    "Feb.": "Feb", "February": "Feb",
    "Mar.": "Mar", "March": "Mar",
    "Apr.": "Apr", "April": "Apr",
    "May": "May",
    "Jun.": "Jun", "June": "Jun",
    "Jul.": "Jul", "July": "Jul",
    "Aug.": "Aug", "August": "Aug",
    "Sep.": "Sep", "Sept.": "Sep", "September": "Sep",
    "Oct.": "Oct", "October": "Oct",
    "Nov.": "Nov", "November": "Nov",
    "Dec.": "Dec", "December": "Dec",
}


def normalize_month(month_str: str) -> str:
    return MONTH_MAP.get(month_str, month_str)


def extract_date_from_timestamp_list(timestamp_list):
    if not timestamp_list:
        return ""
    ts = timestamp_list[0]
    m = re.search(r"([A-Z][a-z]{2,9}\.?)[ ]+(\d{1,2}),[ ]*(\d{4})", ts)
    if m:
        month_raw, day, year = m.groups()
        return f"{normalize_month(month_raw)} {int(day)}, {year}"
    return ""


def extract_date_from_content(content: str) -> str:
    text = " ".join(content.split())
    m = re.search(r"([A-Z][a-z]{2,9}\.?)[ ]+(\d{1,2}),[ ]*(\d{4})", text)
    if not m:
        return ""
    month_raw, day, year = m.groups()
    return f"{normalize_month(month_raw)} {int(day)}, {year}"


def get_pretty_date(article: dict) -> str:
    ts_date = extract_date_from_timestamp_list(article.get("timestamp", []))
    if ts_date:
        return ts_date
    return extract_date_from_content(article.get("content", "") or "")


# ---------- FALLBACK SUMMARY ----------
def strip_prnewswire_boilerplate(content: str) -> str:
    text = " ".join(content.split())
    marker = "/PRNewswire"
    idx = text.find(marker)
    if idx != -1:
        dash_idx = text.find("--", idx)
        if dash_idx != -1:
            return text[dash_idx + 2:].strip()
        return text[idx + len(marker):].strip()
    return text


def simple_summary(content: str, max_chars=400):
    """
    Deterministic 1–2 sentence summary, directly from the press release (no AI).
    """
    core = strip_prnewswire_boilerplate(content)
    if not core:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", core)
    summary = " ".join(sentences[:2]).strip()
    if len(summary) > max_chars:
        short = summary[:max_chars]
        last = short.rfind(" ")
        if last > 0:
            short = short[:last]
        summary = short + "..."
    return summary


# ---------- AI SUMMARY (CONTEXT, DATAVISION STYLE, NO DATE PREFIX) ----------
def ai_summarise_with_ollama(content: str, date_str: str) -> str:
    """
    Produce a 2–3 sentence summary in the style of the sample M&A Letter.

    IMPORTANT:
    - Do NOT start the summary with the date. The date will be shown separately in the layout.
    - First sentence should start with the buyer or key company name where possible.
    """
    if not content:
        return ""
    content_for_ai = content[:MAX_CHARS_FOR_AI]

    prompt = f"""
You are an expert M&A and corporate development analyst.

Write ONE concise news-style summary of the following M&A press release,
in the style of a professional deals newsletter.

CONTEXT (not for display):
- The announcement date is: {date_str}
- The date will be displayed separately in the newsletter layout.

STRUCTURE:
- The output MUST be 2 or 3 sentences in total.
- DO NOT begin the text with a date like "{date_str}," or "Nov 3, 2025".
- Prefer to start the first sentence with the main company or buyer name.
  Example pattern: "Altimetrik completed the acquisition of SLK Software, creating ..."

- First sentence: clearly classify the transaction (e.g., acquisition, strategic investment, merger,
  buyback, joint venture) and name the key parties and the sector or space.
- Second and (if needed) third sentence: describe scale and strategic rationale:
  * scale examples: number of employees, countries, customers, segments, or (only if in the text) deal value
  * rationale examples: expanding into new markets, strengthening AI/digital capabilities,
    deepening presence in specific verticals, improving operational efficiency, providing liquidity to employees, etc.

NUMBERS AND DEAL VALUE:
- ONLY mention a specific financial amount (e.g., "USD 240 million") if that exact or equivalent value
  is explicitly stated in the article text.
- If there is no clear deal value mentioned, DO NOT invent or approximate any number.
- DO NOT use placeholders like "$X million" or "an undisclosed amount".

STYLE:
- Tone: analytical, concise, business-like (no hype, no marketing adjectives).
- Do NOT mention "/PRNewswire/", cities, or phrases like "according to the press release".
- No bullet points; keep everything as continuous prose in 2–3 sentences.

Press release:
\"\"\"{content_for_ai}\"\"\"
"""
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return (resp.json().get("response") or "").strip()
    except Exception:
        return ""


# ---------- SANITY CHECK: DOES SUMMARY MATCH TITLE? ----------
def summary_matches_title(summary: str, title: str) -> bool:
    """
    Heuristic check: ensure AI summary at least mentions some key word from the title.
    If not, we consider it unreliable and fall back to simple_summary.
    """
    if not summary or not title:
        return False

    summary_l = summary.lower()
    # Take significant tokens from the title (no stopwords / tiny words)
    tokens = [
        t.strip(" ,.&()/-")
        for t in title.split()
        if len(t.strip(" ,.&()/-")) >= 4  # ignore very short words
    ]

    if not tokens:
        return False

    for t in tokens:
        if t.lower() in summary_l:
            return True

    return False


def get_context_text(article: dict) -> str:
    """
    Try AI summary first, but only keep it if it clearly matches the deal title.
    Otherwise fall back to deterministic summary from the press release.
    """
    content = article.get("content", "") or ""
    pretty_date = get_pretty_date(article)
    title = article.get("title", "") or ""

    # 1) Try AI
    if content:
        ai_line = ai_summarise_with_ollama(content, pretty_date)
        if ai_line and summary_matches_title(ai_line, title):
            return ai_line

    # 2) Fallback: deterministic summary from text
    fallback = simple_summary(content)
    return fallback


# ---------- DEAL VALUE FROM TEXT (NO AI) ----------
def extract_deal_value_from_text(content: str) -> str:
    """
    Extract a deal value only if it actually appears in the text.
    Patterns like:
      - USD 600 million
      - $140 million
      - EUR 2.5 billion
      - C$3.4 billion
    If nothing found -> "NA".
    """
    if not content:
        return "NA"

    text = " ".join(content.split())

    pattern = r"""(
        (?:USD|US\$|\$|EUR|€|GBP|£|C\$|CAD|INR|Rs\.?)
        \s*
        [0-9][0-9,]*(?:\.\d+)?
        \s*
        (?:million|billion|bn|mn|m|M|B)?
    )"""

    m = re.search(pattern, text, re.IGNORECASE | re.VERBOSE)
    if not m:
        return "NA"

    value = m.group(1).strip()

    value = value.replace("US$", "USD ")
    value = value.replace("$", "USD ")

    value = re.sub(r"\s+", " ", value).strip()
    return value


# ---------- AI METADATA EXTRACTION (ADVISOR + LEADERS, STRICT) ----------
def ai_extract_deal_metadata(content: str) -> dict:
    """
    - deal_value: regex from text (no AI hallucination)
    - AI proposes:
        investor_or_pe, buyer, seller, advisor_firm,
        buyer_lead_name, buyer_lead_role,
        investor_lead_name, investor_lead_role,
        seller_lead_name, seller_lead_role
      We keep values only if they appear in the article text.
      Roles are NOT normalized (e.g., Partner stays Partner, not CEO).
    """
    if not content:
        return {
            "deal_value": "NA",
            "deal_advisor": "NA",
            "investor_or_pe": "NA",
            "buyer": "NA",
            "seller": "NA",
            "buyer_lead_name": "NA",
            "buyer_lead_role": "NA",
            "investor_lead_name": "NA",
            "investor_lead_role": "NA",
            "seller_lead_name": "NA",
            "seller_lead_role": "NA",
        }

    deal_value = extract_deal_value_from_text(content)
    content_norm = " ".join(content.split()).lower()

    content_for_ai = content[:MAX_CHARS_FOR_AI]

    prompt = f"""
You are an M&A analyst. Read the following press release and identify the key firms and their senior representatives.

Return ONLY a JSON object with this exact shape:

{{
  "investor_or_pe": "...",
  "buyer": "...",
  "seller": "...",
  "advisor_firm": "...",
  "buyer_lead_name": "...",
  "buyer_lead_role": "...",
  "investor_lead_name": "...",
  "investor_lead_role": "...",
  "seller_lead_name": "...",
  "seller_lead_role": "..."
}}

Definitions and rules:
- "investor_or_pe" = private equity or VC firm(s). If multiple, join with " & ".
- "buyer" = acquiring company. If multiple, join with " & ".
- "seller" = target company. If multiple, join with " & ".
- "advisor_firm" = investment bank / advisory firm(s). If multiple, join with " & ".
- "buyer_lead_name" = main quoted executive for the buyer (e.g., CEO, Founder, Managing Director).
- "buyer_lead_role" = that person's role EXACTLY as written (e.g., "CEO", "Partner", "Founder & CEO",
  "Managing Partner"). DO NOT change or normalize the role.
- "investor_lead_name" = main quoted executive for the investor/PE (if any).
- "investor_lead_role" = their role EXACTLY as written.
- "seller_lead_name" = main quoted executive for the seller/target (if any).
- "seller_lead_role" = their role EXACTLY as written.
- If something is not clearly available, use "NA".

Important:
- DO NOT upgrade or relabel roles. For example, if the text says "Partner", keep "Partner" (do NOT change it to "CEO").
- Values must be short, clean names or titles (no surrounding sentences, no labels like "CEO of", no company names mixed in).
- If unsure, use "NA".
    
Press release:
\"\"\"{content_for_ai}\"\"\"
"""
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        raw = (resp.json().get("response") or "").strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("JSON not found in AI response")
        data = json.loads(match.group(0))
    except Exception:
        data = {}

    def clean(val: str) -> str:
        if not val:
            return "NA"
        s = val.strip()
        return s if s else "NA"

    investor_or_pe = clean(data.get("investor_or_pe", "NA"))
    buyer = clean(data.get("buyer", "NA"))
    seller = clean(data.get("seller", "NA"))
    advisor_firm = clean(data.get("advisor_firm", "NA"))

    buyer_lead_name = clean(data.get("buyer_lead_name", "NA"))
    buyer_lead_role = clean(data.get("buyer_lead_role", "NA"))
    investor_lead_name = clean(data.get("investor_lead_name", "NA"))
    investor_lead_role = clean(data.get("investor_lead_role", "NA"))
    seller_lead_name = clean(data.get("seller_lead_name", "NA"))
    seller_lead_role = clean(data.get("seller_lead_role", "NA"))

    # validate org-like names: require at least one token to appear in text
    def validate_org(name: str) -> str:
        if name == "NA":
            return "NA"
        parts = [p.strip() for p in re.split(r"&|,|/| and ", name) if p.strip()]
        for p in parts:
            if p.lower() in content_norm:
                return name
        return "NA"

    # validate person names: check any non-trivial token in content
    def validate_person(name: str) -> str:
        if name == "NA":
            return "NA"
        tokens = [t for t in re.split(r"\s+", name) if len(t) > 2]
        for t in tokens:
            if t.lower() in content_norm:
                return name
        return "NA"

    # validate roles: ensure at least one token appears in text (to avoid hallucinations)
    def validate_role(role: str) -> str:
        if role == "NA":
            return "NA"
        tokens = [t for t in re.split(r"[\s/&,-]+", role) if len(t) > 2]
        for t in tokens:
            if t.lower() in content_norm:
                return role
        return "NA"

    investor_or_pe = validate_org(investor_or_pe)
    advisor_firm = validate_org(advisor_firm)
    buyer = validate_org(buyer)
    seller = validate_org(seller)

    buyer_lead_name = validate_person(buyer_lead_name)
    investor_lead_name = validate_person(investor_lead_name)
    seller_lead_name = validate_person(seller_lead_name)

    buyer_lead_role = validate_role(buyer_lead_role)
    investor_lead_role = validate_role(investor_lead_role)
    seller_lead_role = validate_role(seller_lead_role)

    # Preference: investor -> advisor -> buyer -> seller -> NA
    if investor_or_pe != "NA":
        deal_advisor = investor_or_pe
    elif advisor_firm != "NA":
        deal_advisor = advisor_firm
    elif buyer != "NA":
        deal_advisor = buyer
    elif seller != "NA":
        deal_advisor = seller
    else:
        deal_advisor = "NA"

    return {
        "deal_value": deal_value,
        "deal_advisor": deal_advisor,
        "investor_or_pe": investor_or_pe,
        "buyer": buyer,
        "seller": seller,
        "buyer_lead_name": buyer_lead_name,
        "buyer_lead_role": buyer_lead_role,
        "investor_lead_name": investor_lead_name,
        "investor_lead_role": investor_lead_role,
        "seller_lead_name": seller_lead_name,
        "seller_lead_role": seller_lead_role,
    }


# ---------- DEAL BLOCK (HEADLINE AS LINK + LEADERSHIP ROW) ----------
def build_deal_block(article: dict) -> str:
    title = article.get("title", "Untitled deal")
    context_text = article.get("context", "")
    url = article.get("url", "#")
    pretty_date = get_pretty_date(article)

    title_html = escape(title)
    body_html = escape(context_text)
    url_html = escape(url)
    date_html = escape(pretty_date)

    deal_advisor = escape(article.get("deal_advisor", "NA"))
    deal_value = escape(article.get("deal_value", "NA"))

    buyer = article.get("buyer", "NA")
    seller = article.get("seller", "NA")
    investor_or_pe = article.get("investor_or_pe", "NA")

    buyer_lead_name = article.get("buyer_lead_name", "NA")
    buyer_lead_role = article.get("buyer_lead_role", "NA")
    investor_lead_name = article.get("investor_lead_name", "NA")
    investor_lead_role = article.get("investor_lead_role", "NA")
    seller_lead_name = article.get("seller_lead_name", "NA")
    seller_lead_role = article.get("seller_lead_role", "NA")

    labels = []

    # Buyer leadership
    if buyer != "NA" and buyer_lead_name != "NA":
        text = f"{buyer} – {buyer_lead_name}"
        if buyer_lead_role != "NA":
            text += f" ({buyer_lead_role})"
        labels.append(text)

    # Investor leadership (or just firm if no person)
    if investor_or_pe != "NA":
        if investor_lead_name != "NA":
            text = f"{investor_or_pe} – {investor_lead_name}"
            if investor_lead_role != "NA":
                text += f" ({investor_lead_role})"
        else:
            text = f"Investor – {investor_or_pe}"
        labels.append(text)

    # Seller leadership
    if seller != "NA" and seller_lead_name != "NA":
        text = f"{seller} – {seller_lead_name}"
        if seller_lead_role != "NA":
            text += f" ({seller_lead_role})"
        labels.append(text)

    footer_row_html = ""
    if labels:
        items_html = "".join(
            f'<div class="deal-footer-item">{escape(lbl)}</div>'
            for lbl in labels
        )
        footer_row_html = f"""
      <div class="deal-footer-row">
        {items_html}
      </div>
    """

    return f"""
    <div class="deal-block">
      <div class="deal-title-main">
        <a href="{url_html}" target="_blank" style="color: #000; text-decoration: none;">
          {title_html}
        </a>
      </div>

      <div class="deal-meta-row">
        <div class="deal-meta-left">{date_html}</div>
        <div class="deal-meta-center"><span class="deal-meta-label">Deal Advisor:</span> {deal_advisor}</div>
        <div class="deal-meta-right"><span class="deal-meta-label">Deal Value:</span> {deal_value}</div>
      </div>

      <div class="deal-body">{body_html}</div>
      {footer_row_html}
    </div>
    """


# ---------- HTML / TXT OUTPUT ----------
def load_template(template_path: Path) -> str:
    with template_path.open("r", encoding="utf-8") as f:
        return f.read()


def build_newsletter_html(articles):
    blocks_html = "\n".join(build_deal_block(a) for a in articles)
    template = load_template(TEMPLATE_PATH)
    return (
        template
        .replace("{{ISSUE_DATE}}", ISSUE_DATE)
        .replace("{{ISSUE_NUMBER}}", ISSUE_NUMBER)
        .replace("{{DEAL_BLOCKS}}", blocks_html)
    )


def build_context_entry(article: dict) -> str:
    return f"{article.get('url','')}\n\n{article.get('context','')}\n\n"


def build_contexts_text(articles):
    return "".join(build_context_entry(a) for a in articles if a.get("url"))


# ---------- EMAIL FUNCTIONALITY ----------
def load_emails_from_file(emails_path: Path) -> list[str]:
    """
    Read email addresses from a text file.
    Expected format: one email per line, empty lines and lines starting with # are ignored.
    """
    if not emails_path.exists():
        print(f"⚠️  Emails file not found: {emails_path}")
        return []
    
    emails = []
    with emails_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            # Basic email validation
            if "@" in line and "." in line:
                emails.append(line)
            else:
                print(f"⚠️  Skipping invalid email format: {line}")
    
    return emails


def send_newsletter_email(resend_client: Resend, recipient_email: str, html_content: str, subject: str) -> bool:
    """
    Send newsletter email to a single recipient using Resend API.
    Returns True if successful, False otherwise.
    """
    try:
        params = {
            "from": f"{SENDER_NAME} <{SENDER_EMAIL}>",
            "to": [recipient_email],
            "subject": subject,
            "html": html_content,
        }
        
        response = resend_client.emails.send(params)
        
        # Handle different response formats
        if isinstance(response, dict):
            email_id = response.get('id') or response.get('data', {}).get('id', 'N/A')
        else:
            email_id = getattr(response, 'id', 'N/A')
        
        print(f"   ✔ Sent to {recipient_email} (ID: {email_id})")
        return True
    except Exception as e:
        print(f"   ✗ Failed to send to {recipient_email}: {str(e)}")
        return False


def send_newsletters_to_all(html_content: str, emails: list[str], subject: str) -> dict:
    """
    Send newsletter to all email addresses.
    Returns a dictionary with success/failure statistics.
    """
    if not RESEND_API_KEY:
        print("❌ RESEND_API_KEY not set. Please set it as an environment variable.")
        return {"success": 0, "failed": 0, "total": len(emails)}
    
    resend_client = Resend(api_key=RESEND_API_KEY)
    
    print(f"\n📧 Sending newsletters to {len(emails)} recipients...")
    print(f"   From: {SENDER_EMAIL}")
    print(f"   Subject: {subject}\n")
    
    success_count = 0
    failed_count = 0
    
    for idx, email in enumerate(emails, start=1):
        print(f"[{idx}/{len(emails)}] Sending to {email}...", end=" ")
        if send_newsletter_email(resend_client, email, html_content, subject):
            success_count += 1
        else:
            failed_count += 1
        # Small delay to avoid rate limiting
        time.sleep(0.5)
    
    print(f"\n📊 Email sending summary:")
    print(f"   ✅ Successful: {success_count}")
    print(f"   ❌ Failed: {failed_count}")
    print(f"   📧 Total: {len(emails)}")
    
    return {
        "success": success_count,
        "failed": failed_count,
        "total": len(emails)
    }


# ---------- MAIN ----------
def main():
    articles = load_articles(JSON_PATH)
    total_raw = len(articles)

    if TEST_MODE:
        articles = articles[:TEST_COUNT]
        print(f"🧪 TEST MODE — {TEST_COUNT} of {total_raw} articles\n")
    else:
        print(f"Found {total_raw} articles\n")

    enriched = []

    for idx, article in enumerate(articles, start=1):
        print(f"=== [{idx}/{len(articles)}] {article.get('title','Untitled')[:70]}")

        start = time.time()
        context = get_context_text(article)
        print(f"   ✔ Summary OK ({time.time() - start:.1f}s)")

        print("   🔍 Extracting deal metadata...")
        start = time.time()
        meta = ai_extract_deal_metadata(article.get("content", "") or "")
        print(f"   ✔ Metadata OK ({time.time() - start:.1f}s)\n")

        enriched.append({
            **article,
            "context": context,
            **meta,
        })

    html = build_newsletter_html(enriched)
    HTML_OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"\n📄 HTML: {HTML_OUTPUT_PATH.resolve()}")

    contexts = build_contexts_text(enriched)
    CONTEXT_OUTPUT_PATH.write_text(contexts, encoding="utf-8")
    print(f"🗒 Contexts: {CONTEXT_OUTPUT_PATH.resolve()}")

    # Send emails if enabled
    if SEND_EMAILS:
        emails = load_emails_from_file(EMAILS_FILE_PATH)
        if emails:
            send_newsletters_to_all(html, emails, EMAIL_SUBJECT)
        else:
            print("\n⚠️  No emails found to send. Please check emails.txt file.")
    else:
        print("\n💡 Email sending is disabled. Set SEND_EMAILS = True to enable.")

    print("\n🚀 Completed")


if __name__ == "__main__":
    main()
