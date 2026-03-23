import os
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User, Plan
from auth import get_current_user
from datetime import datetime
from pydantic import BaseModel

router = APIRouter()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PRICE_IDS = {
    "pro":     os.getenv("STRIPE_PRO_PRICE_ID",     "price_1TE4J3FAS3axAm4bdteGechZ"),
    "premium": os.getenv("STRIPE_PREMIUM_PRICE_ID", "price_1TE4JlFAS3axAm4bc7m3N2Wx"),
}

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ramosdata.dev")


class CheckoutRequest(BaseModel):
    plan: str   # "pro" or "premium"


# ── Create Checkout Session ────────────────────────────────────────────────────

@router.post("/checkout")
def create_checkout(
    data: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    plan_name = data.plan.lower()

    if plan_name not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid plan. Choose 'pro' or 'premium'.")

    current_plan = current_user.plan.name if current_user.plan else "basic"
    if current_plan == plan_name:
        raise HTTPException(status_code=400, detail=f"You are already on the {plan_name} plan.")

    price_id = PRICE_IDS[plan_name]

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            # Pass user info so we can identify them in the webhook
            metadata={
                "user_id":    str(current_user.id),
                "user_email": current_user.email,
                "plan":       plan_name,
            },
            customer_email=current_user.email,
            success_url=f"{FRONTEND_URL}/scraper-dashboard.html?payment=success&plan={plan_name}",
            cancel_url=f"{FRONTEND_URL}/scraper-index.html?payment=cancelled#pricing",
        )
        return {"checkout_url": session.url, "session_id": session.id}

    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=str(e.user_message or e))


# ── Stripe Webhook ─────────────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    if not webhook_secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ── Handle checkout.session.completed ─────────────────────────────────────
    if event["type"] == "checkout.session.completed":
        session  = event["data"]["object"]
        metadata = session.get("metadata", {})

        user_email = metadata.get("user_email") or session.get("customer_email")
        plan_name  = metadata.get("plan")

        if not user_email or not plan_name:
            return JSONResponse({"status": "missing metadata"}, status_code=200)

        # Find the user
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            return JSONResponse({"status": "user not found"}, status_code=200)

        # Find the plan
        plan = db.query(Plan).filter(Plan.name == plan_name).first()
        if not plan:
            return JSONResponse({"status": "plan not found"}, status_code=200)

        # Upgrade the user
        user.plan_id    = plan.id
        user.updated_at = datetime.utcnow()
        db.commit()

        print(f"[Stripe] Upgraded {user_email} to {plan_name}")

    return JSONResponse({"status": "ok"}, status_code=200)


# ── Cancel subscription ────────────────────────────────────────────────────────

@router.post("/cancel")
def cancel_subscription(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Downgrade user back to basic (cancel subscription logic)."""
    plan = db.query(Plan).filter(Plan.name == "basic").first()
    if not plan:
        raise HTTPException(status_code=500, detail="Basic plan not found")

    current_user.plan_id    = plan.id
    current_user.updated_at = datetime.utcnow()
    db.commit()

    return {"message": "Subscription cancelled. You have been moved to the Basic plan."}
