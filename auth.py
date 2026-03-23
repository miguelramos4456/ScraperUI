from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models import User, Plan
from jose import jwt, JWTError
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional
import bcrypt
import os

router = APIRouter()
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey123")
ALGORITHM  = "HS256"
bearer_scheme = HTTPBearer(auto_error=False)

# ── Schemas ────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name:     str = ""
    email:    str
    password: str
    plan:     str = "basic"

class LoginRequest(BaseModel):
    email:    str
    password: str

class ChangePlanRequest(BaseModel):
    plan: str   # basic | pro | premium

# ── Helpers ────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_token(user_id: int, email: str, plan: str) -> str:
    expire = datetime.utcnow() + timedelta(days=7)
    return jwt.encode(
        {"sub": email, "user_id": user_id, "plan": plan, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM
    )

# ── Auth dependency ────────────────────────────────────────────────────────────

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_plan(required: str):
    RANK = {"basic": 1, "pro": 2, "premium": 3}

    def checker(current_user: User = Depends(get_current_user)) -> User:
        user_plan = current_user.plan.name if current_user.plan else "basic"
        if RANK.get(user_plan, 0) < RANK.get(required, 99):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This feature requires the '{required}' plan or higher. You are on '{user_plan}'."
            )
        return current_user

    return checker

# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    plan_name = data.plan if data.plan in ("basic", "pro", "premium") else "basic"
    plan = db.query(Plan).filter(Plan.name == plan_name).first()
    if not plan:
        plan = db.query(Plan).filter(Plan.name == "basic").first()
    if not plan:
        raise HTTPException(status_code=500, detail="Plans not configured. Run the seed SQL first.")

    user = User(
        email=data.email,
        name=data.name,
        password=hash_password(data.password),
        plan_id=plan.id
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id, user.email, plan.name)
    return {
        "message": "Account created",
        "access_token": token,
        "name": data.name,
        "email": user.email,
        "plan": plan.name
    }


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    plan_name = user.plan.name if user.plan else "basic"
    token = create_token(user.id, user.email, plan_name)

    return {
        "message": "Login successful",
        "access_token": token,
        "name": user.name or user.email,
        "email": user.email,
        "plan": plan_name
    }


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    plan_name = current_user.plan.name if current_user.plan else "basic"
    return {
        "id":    current_user.id,
        "name":  current_user.name,
        "email": current_user.email,
        "plan":  plan_name,
    }


@router.patch("/plan")
def change_plan(
    data: ChangePlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Allow a logged-in user to switch their plan without logging out."""
    plan_name = data.plan if data.plan in ("basic", "pro", "premium") else "basic"
    plan = db.query(Plan).filter(Plan.name == plan_name).first()
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found")

    current_user.plan_id = plan.id
    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)

    # Issue a fresh token with the new plan embedded
    new_token = create_token(current_user.id, current_user.email, plan.name)

    return {
        "message": f"Plan updated to {plan.label}",
        "plan": plan.name,
        "access_token": new_token
    }
