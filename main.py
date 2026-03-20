from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
import models
from auth import router as auth_router
from leads import router as leads_router
from writer import scrape_website
from writer import generate_outreach

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="LeadGen API")

# Allow frontend to talk to the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(leads_router, prefix="/leads", tags=["Leads"])

@app.get("/")
def root():
    return {"status": "LeadGen API is running"}

@app.get("/health")
def health():
    return {"status": "ok"}
# ENSURE NO SPACES BEFORE THESE TWO LINES
@app.post("/generate-lead")
async def generate_lead(url: str, user_id: int):
    # 1. Run the new advanced scraper
    data = await scrape_website(url)
    
    if not data.get("leads"):
        return {"status": "No leads found", "url": url}

    processed_leads = []

    # 2. Iterate through the leads the AI found
    for lead in data["leads"]:
        lead_context = {"raw_text": data["raw_text"], "title": data["title"]}
        ai_draft = await generate_outreach(lead_context)
        
        # 3. Save each lead to PostgreSQL
        query = """
        INSERT INTO leads (user_id, name, email, phone, role, company, ai_draft, source_url)
        VALUES (:u, :n, :e, :p, :r, :c, :a, :s)
        """
        values = {
            "u": user_id,
            "n": lead.get("name"),
            "e": lead.get("email"),
            "p": lead.get("phone"),
            "r": lead.get("role"),
            "c": lead.get("company"),
            "a": ai_draft,
            "s": url
        }
        await database.execute(query=query, values=values)
        processed_leads.append({"name": lead.get("name"), "draft": ai_draft})

    return {"status": "Leads processed", "data": processed_leads}
