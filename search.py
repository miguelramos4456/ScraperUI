import os
import re
import json
import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User, SavedResource
from auth import require_plan
from pydantic import BaseModel

router = APIRouter()

TRUSTED_SITES = {
    "pdfs": [
        "site:mit.edu filetype:pdf",
        "site:arxiv.org",
        "site:researchgate.net",
        "site:academia.edu",
        "site:openstax.org",
        "site:pdfdrive.com",
    ],
    "articles": [
        "site:khanacademy.org",
        "site:coursera.org",
        "site:edx.org",
        "site:wikipedia.org",
        "site:britannica.com",
        "site:towardsdatascience.com",
    ],
    "practice": [
        "site:khanacademy.org",
        "site:brilliant.org",
        "site:wolframalpha.com",
        "site:geeksforgeeks.org",
        "site:leetcode.com",
        "site:quizlet.com",
    ],
}

SITE_LABELS = {
    "mit.edu": "MIT", "arxiv.org": "arXiv", "researchgate.net": "ResearchGate",
    "academia.edu": "Academia.edu", "openstax.org": "OpenStax",
    "khanacademy.org": "Khan Academy", "coursera.org": "Coursera",
    "edx.org": "edX", "wikipedia.org": "Wikipedia", "britannica.com": "Britannica",
    "brilliant.org": "Brilliant", "geeksforgeeks.org": "GeeksForGeeks",
    "leetcode.com": "LeetCode", "quizlet.com": "Quizlet",
    "wolframalpha.com": "Wolfram Alpha", "towardsdatascience.com": "Towards Data Science",
    "pdfdrive.com": "PDF Drive",
}


class SearchRequest(BaseModel):
    query: str
    types: list[str] = ["pdfs", "articles", "practice"]


class SaveResourceRequest(BaseModel):
    title: str
    url: str
    source: str = ""
    type: str = "article"
    description: str = ""
    query: str = ""


def get_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=api_key)


def label_for_url(url: str) -> str:
    for domain, label in SITE_LABELS.items():
        if domain in url:
            return label
    return "Resource"


@router.post("/search")
async def search_resources(
    data: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_plan("premium"))
):
    if not data.query.strip():
        raise HTTPException(status_code=400, detail="Please enter a search query.")
    if len(data.query) > 200:
        raise HTTPException(status_code=400, detail="Query is too long.")

    client = get_client()

    site_filters = []
    for t in data.types:
        if t in TRUSTED_SITES:
            site_filters.extend(TRUSTED_SITES[t])
    top_sites = " OR ".join(site_filters[:6])
    search_query = f"{data.query} ({top_sites})"

    system_prompt = """You are an educational resource finder. Use web search to find learning materials.
After searching, return ONLY a valid JSON array (no markdown, no explanation):
[
  {
    "title": "Resource title",
    "url": "https://...",
    "source": "MIT / arXiv / Khan Academy etc.",
    "type": "pdf | article | practice",
    "description": "One sentence describing what this resource covers."
  }
]
Rules:
- Return 6-10 results maximum
- Only include results from reputable educational sources
- NO random blogs, NO paywalled sites, NO piracy sites
- If a result is a PDF, set type to "pdf"
- Prefer free, openly accessible resources
- Return [] if nothing relevant found"""

    try:
        messages = [{"role": "user", "content": f"Find educational resources for: {search_query}"}]

        while True:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                system=system_prompt,
                messages=messages
            )
            if response.stop_reason == "end_turn":
                break
            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": ""
                        })
                messages.append({"role": "user", "content": tool_results})
            else:
                break

        text_blocks = [b.text for b in response.content if hasattr(b, "text") and b.text]
        raw = " ".join(text_blocks).strip()
        raw = re.sub(r'^```json\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()

        array_match = re.search(r'\[[\s\S]*\]', raw)
        if not array_match:
            return {"results": [], "query": data.query, "count": 0}

        results = json.loads(array_match.group(0))
        for r in results:
            if not r.get("source") and r.get("url"):
                r["source"] = label_for_url(r["url"])

        return {"results": results, "query": data.query, "count": len(results)}

    except json.JSONDecodeError:
        return {"results": [], "query": data.query, "count": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/save")
def save_resource(
    data: SaveResourceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_plan("premium"))
):
    existing = db.query(SavedResource).filter_by(
        user_id=current_user.id, url=data.url
    ).first()
    if existing:
        return {"message": "Already saved", "id": existing.id, "already_saved": True}

    resource = SavedResource(
        user_id=current_user.id,
        title=data.title,
        url=data.url,
        source=data.source,
        type=data.type,
        description=data.description,
        query=data.query,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return {"message": "Saved", "id": resource.id, "already_saved": False}


@router.get("/search/saved")
def get_saved_resources(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_plan("premium"))
):
    resources = (
        db.query(SavedResource)
        .filter_by(user_id=current_user.id)
        .order_by(SavedResource.created_at.desc())
        .all()
    )
    return {
        "resources": [
            {
                "id": r.id,
                "title": r.title,
                "url": r.url,
                "source": r.source,
                "type": r.type,
                "description": r.description,
                "query": r.query,
                "saved_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in resources
        ],
        "count": len(resources)
    }


@router.delete("/search/saved/{resource_id}")
def delete_saved_resource(
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_plan("premium"))
):
    resource = db.query(SavedResource).filter_by(
        id=resource_id, user_id=current_user.id
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    db.delete(resource)
    db.commit()
    return {"message": "Deleted"}
