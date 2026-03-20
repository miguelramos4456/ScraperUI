import httpx
import re
import json
import os
import anthropic
from bs4 import BeautifulSoup

def extract_emails(text: str) -> list:
    pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    emails = re.findall(pattern, text)
    filtered = [
        e for e in emails
        if not e.endswith(('.png', '.jpg', '.gif', '.css', '.js', '.svg', '.woff'))
        and 'example' not in e and 'sentry' not in e and '@2x' not in e
    ]
    return list(set(filtered))

def extract_phones(text: str) -> list:
    pattern = r'(\+?1?\s?[\(\-]?\d{3}[\)\-\s]?\s?\d{3}[\-\s]?\d{4})'
    matches = re.findall(pattern, text)
    cleaned = [re.sub(r'\s+', ' ', m.strip()) for m in matches]
    return list(set([p for p in cleaned if len(re.sub(r'\D', '', p)) >= 10]))

def extract_social_links(soup: BeautifulSoup) -> dict:
    socials = {}
    for a in soup.find_all('a', href=True):
        href = a['href'].lower()
        if 'linkedin.com' in href: socials['linkedin'] = a['href']
        elif 'twitter.com' in href or 'x.com' in href: socials['twitter'] = a['href']
        elif 'facebook.com' in href: socials['facebook'] = a['href']
    return socials

def clean_text(soup: BeautifulSoup) -> str:
    for tag in soup(['script', 'style', 'nav', 'footer', 'head', 'noscript']):
        tag.decompose()
    text = soup.get_text(separator=' ')
    return re.sub(r'\s+', ' ', text).strip()[:4000]

def extract_with_ai(raw_text: str, url: str) -> list:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[AI extraction] No ANTHROPIC_API_KEY set, skipping.")
        return []
    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a lead extraction assistant. Given this webpage text from {url}, "
                    f"extract all people or businesses mentioned.\n\n"
                    f"Return ONLY a valid JSON array. Each object should have: "
                    f"name, role, email, phone, company, location (empty string if unknown).\n"
                    f"If no people found, return [].\n\n"
                    f"Webpage text:\n{raw_text}\n\nJSON array:"
                )
            }]
        )
        content = message.content[0].text.strip()
        content = re.sub(r'^```json\s*|\s*```$', '', content, flags=re.MULTILINE).strip()
        leads = json.loads(content)
        return leads if isinstance(leads, list) else []
    except Exception as e:
        print(f"[AI extraction error] {e}")
        return []

async def scrape_website(url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as http:
            resp = await http.get(url, headers=headers)
            soup = BeautifulSoup(resp.text, "lxml")
            emails = extract_emails(resp.text)
            phones = extract_phones(soup.get_text())
            socials = extract_social_links(soup)
            title = soup.title.string.strip() if soup.title else ""
            raw_text = clean_text(soup)
            ai_leads = extract_with_ai(raw_text, url)
            if ai_leads:
                for i, lead in enumerate(ai_leads):
                    if not lead.get('email') and i < len(emails):
                        lead['email'] = emails[i]
                    if not lead.get('phone') and i < len(phones):
                        lead['phone'] = phones[i]
                    lead['source'] = url
            else:
                ai_leads = []
                for email in emails:
                    ai_leads.append({
                        "name": "", "role": "", "email": email,
                        "phone": phones[0] if phones else "",
                        "company": title, "location": "", "source": url
                    })
                if not ai_leads and phones:
                    ai_leads.append({
                        "name": "", "role": "", "email": "",
                        "phone": phones[0], "company": title,
                        "location": "", "source": url
                    })
            return {
                "url": url, "title": title, "leads": ai_leads,
                "emails_found": emails, "phones_found": phones,
                "socials": socials, "raw_text": raw_text
            }
    except Exception as e:
        print(f"[Scrape error] {url}: {e}")
        return {
            "url": url, "title": "", "leads": [],
            "emails_found": [], "phones_found": [],
            "socials": {}, "raw_text": "", "error": str(e)
        }

async def generate_outreach(lead_context: dict) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "Hi, I'd love to discuss how we can help your business grow!"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"Write a short 3 sentence cold outreach email for a business titled "
                    f"'{lead_context.get('title', 'this company')}'. "
                    f"Context: {lead_context.get('raw_text', '')[:1000]}. "
                    f"Be friendly and end with a call to action. Just the email body."
                )
            }]
        )
        return message.content[0].text
    except Exception as e:
        print(f"[Outreach error] {e}")
        return "Hi, I'd love to discuss how we can help your business grow!"
