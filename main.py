from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine
import models
from auth import router as auth_router
from leads import router as leads_router

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