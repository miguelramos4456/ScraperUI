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
        "User-Agent": "Mozilla/5.0 (Windows NT
