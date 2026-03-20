import os
import re
import anthropic
import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Lead, User
from pydantic import BaseModel
from writer import scrape_website
from auth import get_current_user, require_plan

router = APIRouter()


class ScrapeRequest(BaseModel):
    niche:    str
    location: str
    count:    int = 5


# ── Outreach generator ─────────────────────────────────────────────────────────

async def generate_outreach(name: str, niche: str, website: str) -> str:
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"Write a short 3 sentence cold outreach email for a business called '{name}' "
                    f"in the '{niche}' niche. Website: {website}. "
                    f"Be friendly, specific, and end with a call to action. "
                    f"Just the email body, no subject line."
                )
            }]
        )
        return message.content[0].text
    except Exception:
        return f"Hi {name}, I'd love to discuss how we can help grow your business. Would you be open to a quick call this week?"


# ── Search helpers ─────────────────────────────────────────────────────────────

SKIP_DOMAINS = [
    'google.', 'youtube.', 'facebook.', 'twitter.', 'instagram.',
    'wikipedia.', 'maps.', 'apple.', 'bing.', 'duckduckgo.',
    'microsoft.', 'reddit.', 'amazon.', 'yelp.', 'zocdoc.',
    'healthgrades.', 'vitals.', 'findlaw.', 'avvo.', 'yellowpages.',
    'bbb.org', 'thumbtack.', 'angieslist.', 'houzz.', 'tripadvisor.',
    'linkedin.', 'nextdoor.', 'webmd.', 'psychology-today.',
]

DDG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://duckduckgo.com/",
}

BING_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def clean_domain(url: str) -> str:
    return re.sub(r'https?://(www\.)?', '', url).split('/')[0]


async def _search_duckduckgo(niche: str, location: str, count: int) -> list:
    queries = [
        f"{niche} {location}",
        f"{niche} {location} contact",
        f"{niche} near {location}",
    ]
    businesses = []
    seen = set()

    for query in queries:
        if len(businesses) >= count:
            break
        try:
            url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}&kl=us-en"
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                resp = await c.get(url, headers=DDG_HEADERS)
                soup = BeautifulSoup(resp.text, "lxml")
                for a in soup.find_all('a', class_='result__a'):
                    href  = a.get('href', '')
                    title = a.get_text().strip()
                    m     = re.search(r'uddg=(https?[^&]+)', href)
                    real  = m.group(1) if m else href
                    real  = real.replace('%3A', ':').replace('%2F', '/').replace('%3F', '?')
                    if not real.startswith('http'):
                        continue
                    if any(s in real for s in SKIP_DOMAINS):
                        continue
                    domain = clean_domain(real)
                    if not domain or domain in seen:
                        continue
                    seen.add(domain)
                    businesses.append({"name": title or domain, "url": f"https://{domain}"})
                    if len(businesses) >= count:
                        break
        except Exception as e:
            print(f"[DDG] {e}")
    return businesses


async def _search_bing(niche: str, location: str, count: int) -> list:
    query = f"{niche} {location}"
    url   = f"https://www.bing.com/search?q={query.replace(' ', '+')}&count={count * 3}"
    businesses = []
    seen = set()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            resp = await c.get(url, headers=BING_HEADERS)
            soup = BeautifulSoup(resp.text, "lxml")
            for result in soup.find_all('li', class_='b_algo'):
                h2 = result.find('h2')
                a  = h2.find('a') if h2 else None
                if not a:
                    continue
                href  = a.get('href', '')
                title = a.get_text().strip()
                if not href.startswith('http') or any(s in href for s in SKIP_DOMAINS):
                    continue
                domain = clean_domain(href)
                if not domain or domain in seen:
                    continue
                seen.add(domain)
                businesses.append({"name": title or domain, "url": f"https://{domain}"})
                if len(businesses) >= count:
                    break
    except Exception as e:
        print(f"[Bing] {e}")
    return businesses


async def find_business_urls(niche: str, location: str, count: int) -> list:
    results = await _search_duckduckgo(niche, location, count)
    if results:
        return results
    print("[Search] DDG empty, trying Bing...")
    results = await _search_bing(niche, location, count)
    if results:
        return results
    print("[Search] Both search engines failed.")
    return []


# ── /scrape  (all plans — scraping is always available) ───────────────────────

@router.post("/scrape")
async def scrape_leads(
    data: ScrapeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)   # must be logged in
):
    user_plan = current_user.plan.name if current_user.plan else "basic"
    results   = []

    businesses = await find_business_urls(data.niche, data.location, data.count)
    if not businesses:
        raise HTTPException(
            status_code=404,
            detail="Could not find any businesses. Try a different niche or location."
        )

    for biz in businesses[:data.count]:
        scraped  = await scrape_website(biz["url"])
        leads    = scraped.get("leads", [])
        emails   = scraped.get("emails_found", [])
        phones   = scraped.get("phones_found", [])

        if leads:
            lead_data = leads[0]
            name  = lead_data.get("name")  or biz["name"]
            email = lead_data.get("email") or (emails[0] if emails else "")
            phone = lead_data.get("phone") or (phones[0] if phones else "")
        else:
            name  = biz["name"]
            email = emails[0] if emails else ""
            phone = phones[0] if phones else ""

        outreach = await generate_outreach(name, data.niche, biz["url"])

        # Only persist to DB if user is Pro or Premium
        # Basic users still get results shown in the UI — just not saved
        if user_plan in ("pro", "premium"):
            lead = Lead(
                user_id=current_user.id,
                name=name,
                email=email,
                phone=phone,
                website=biz["url"],
                outreach=outreach,
                niche=data.niche
            )
            db.add(lead)
            db.commit()
            db.refresh(lead)
            lead_id = lead.id
        else:
            lead_id = None   # Basic — not saved

        results.append({
            "id":         lead_id,
            "name":       name,
            "email":      email,
            "phone":      phone,
            "website":    biz["url"],
            "outreach":   outreach,
            "niche":      data.niche,
            "location":   data.location,
            "source":     biz["url"],
            "all_emails": emails,
            "all_phones": phones,
            "saved":      lead_id is not None,
        })

    return {
        "leads": results,
        "count": len(results),
        "plan":  user_plan,
        "saved": user_plan in ("pro", "premium")
    }


# ── GET saved leads  (Pro+ only) ───────────────────────────────────────────────

@router.get("/")
def get_leads(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_plan("pro"))
):
    leads = db.query(Lead).filter(Lead.user_id == current_user.id).all()
    return {"leads": [
        {
            "id":       l.id,
            "name":     l.name,
            "email":    l.email,
            "phone":    l.phone,
            "website":  l.website,
            "niche":    l.niche,
            "outreach": l.outreach,
        }
        for l in leads
    ]}


# ── POST save a lead manually  (Pro+ only) ────────────────────────────────────

@router.post("/")
def save_lead(
    lead_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_plan("pro"))
):
    lead = Lead(
        user_id=current_user.id,
        name=lead_data.get("name"),
        email=lead_data.get("email"),
        phone=lead_data.get("phone"),
        website=lead_data.get("website"),
        outreach=lead_data.get("outreach"),
        niche=lead_data.get("niche"),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return {"status": "saved", "id": lead.id}


# ── DELETE a lead  (Pro+ only) ─────────────────────────────────────────────────

@router.delete("/{lead_id}")
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_plan("pro"))
):
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.user_id == current_user.id   # users can only delete their own leads
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    db.delete(lead)
    db.commit()
    return {"status": "deleted"}
