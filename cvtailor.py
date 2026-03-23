import os
import re
import json
import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User
from auth import require_plan
from pydantic import BaseModel

router = APIRouter()


class FetchJobRequest(BaseModel):
    url: str


class TailorRequest(BaseModel):
    job_title:   str
    job_company: str = ""
    job_desc:    str = ""
    hard_skills: list[str] = []
    soft_skills: list[str] = []
    requirements: list[str] = []
    keywords:    list[str] = []
    cv_text:     str


def get_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=api_key)


# ── Fetch & parse job listing ──────────────────────────────────────────────────

@router.post("/fetch-job")
async def fetch_job(
    data: FetchJobRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_plan("premium"))
):
    if not data.url.startswith("http"):
        raise HTTPException(status_code=400, detail="Please provide a valid URL starting with http/https")

    client = get_client()

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            system="""You are a job listing parser. Fetch the job listing from the given URL and extract the details.
Return ONLY valid JSON with exactly this structure, no markdown fences, no explanation:
{
  "title": "Job title",
  "company": "Company name",
  "location": "Location or Remote",
  "description": "Full job description summarised in 3-5 sentences",
  "hard_skills": ["skill1","skill2","skill3"],
  "soft_skills": ["skill1","skill2"],
  "requirements": ["req1","req2","req3"],
  "keywords": ["keyword1","keyword2","keyword3","keyword4","keyword5"]
}""",
            messages=[{"role": "user", "content": f"Fetch and parse this job listing: {data.url}"}]
        )

        text_blocks = [b.text for b in message.content if hasattr(b, "text") and b.text]
        raw = " ".join(text_blocks)

        # Extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            raise ValueError("No JSON found in response")

        parsed = json.loads(json_match.group(0))

        if not parsed.get("title"):
            raise ValueError("Could not extract job title from the URL")

        return parsed

    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Could not parse job details. Try pasting the job description manually instead.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Tailor CV ─────────────────────────────────────────────────────────────────

@router.post("/tailor")
async def tailor_cv(
    data: TailorRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_plan("premium"))
):
    if len(data.cv_text.strip()) < 100:
        raise HTTPException(status_code=400, detail="CV is too short. Please paste your full CV.")

    client = get_client()

    job_context = f"""Job Title: {data.job_title}
Company: {data.job_company}
Key Skills Required: {', '.join(data.hard_skills)}
Keywords: {', '.join(data.keywords)}
Requirements: {'; '.join(data.requirements)}
Description: {data.job_desc}"""

    try:
        # ── 1. Tailor CV
        cv_msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system="""You are an expert CV writer and career coach.
Rewrite and tailor the provided CV to match the job listing.
Rules:
- Rewrite bullet points to include the job's keywords naturally
- Reorder sections so the most relevant experience appears first
- Highlight skills that match the job requirements
- Keep the same factual information — never invent experience or skills
- Use strong action verbs
- Keep the overall structure but optimise the language
- Output the complete rewritten CV as plain text only, ready to copy""",
            messages=[{"role": "user", "content": f"{job_context}\n\nORIGINAL CV:\n{data.cv_text}\n\nPlease rewrite the CV to best match this job."}]
        )
        tailored_cv = cv_msg.content[0].text

        # ── 2. Cover Letter
        cover_msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system="""You are an expert career coach writing a compelling cover letter.
Write a professional, concise cover letter (3-4 paragraphs) that:
- Opens with a strong hook mentioning the specific role
- Highlights the most relevant experience from the CV that matches the job
- Explains why the candidate is excited about this company
- Closes with a confident call to action
- Feels personal and authentic, not generic
Output plain text only.""",
            messages=[{"role": "user", "content": f"{job_context}\n\nCANDIDATE CV:\n{data.cv_text}"}]
        )
        cover_letter = cover_msg.content[0].text

        # ── 3. Tips & match score
        tips_msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system="""You are a career coach giving honest, actionable advice.
Analyse the CV against the job requirements and provide:
1. A match score out of 100 (just the number on its own line first, e.g. "78")
2. Top 3-5 matched keywords/skills (label section "MATCHED SKILLS:")
3. Top 3-5 missing keywords/skills (label section "MISSING SKILLS:")
4. 5 specific actionable tips to improve the application (label section "TIPS:")
Format as plain text with clear section labels.""",
            messages=[{"role": "user", "content": f"Job Requirements:\n{chr(10).join(data.requirements)}\nRequired Skills: {', '.join(data.hard_skills)}\n\nCV:\n{data.cv_text}"}]
        )
        tips = tips_msg.content[0].text

        # Parse score
        score_match = re.search(r'^(\d{1,3})', tips, re.MULTILINE)
        score = int(score_match.group(1)) if score_match else None

        # Parse matched/missing skills from tips
        matched = []
        missing = []

        matched_section = re.search(r'MATCHED SKILLS?:(.*?)(?:MISSING|TIPS|$)', tips, re.DOTALL | re.IGNORECASE)
        missing_section = re.search(r'MISSING SKILLS?:(.*?)(?:TIPS|$)', tips, re.DOTALL | re.IGNORECASE)

        if matched_section:
            matched = [l.strip().lstrip('-•*123456789. ') for l in matched_section.group(1).strip().split('\n') if l.strip()]
        if missing_section:
            missing = [l.strip().lstrip('-•*123456789. ') for l in missing_section.group(1).strip().split('\n') if l.strip()]

        return {
            "tailored_cv":   tailored_cv,
            "cover_letter":  cover_letter,
            "tips":          tips,
            "score":         score,
            "matched_skills": matched[:5],
            "missing_skills": missing[:5],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI processing failed: {str(e)}")
