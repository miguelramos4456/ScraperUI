from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
import models
from auth import router as auth_router
from leads import router as leads_router
from payments import router as payments_router
from cv_tailor import router as cv_router
from writer import scrape_website
from writer import generate_outreach

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Scraper UI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ramosdata.dev",
        "https://www.ramosdata.dev",
        "http://localhost:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router,     prefix="/auth",     tags=["Auth"])
app.include_router(leads_router,    prefix="/leads",    tags=["Leads"])
app.include_router(payments_router, prefix="/payments", tags=["Payments"])
app.include_router(cv_router,       prefix="/cv",       tags=["CV Tailor"])

@app.get("/")
def root():
    return {"status": "Scraper UI is running"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/generate-lead")
async def generate_lead(url: str, user_id: int):
    data = await scrape_website(url)
    if not data.get("leads"):
        return {"status": "No leads found", "url": url}
    processed_leads = []
    for lead in data["leads"]:
        lead_context = {"raw_text": data["raw_text"], "title": data["title"]}
        ai_draft = await generate_outreach(lead_context)
        processed_leads.append({"name": lead.get("name"), "draft": ai_draft})
    return {"status": "Leads processed", "data": processed_leads}
