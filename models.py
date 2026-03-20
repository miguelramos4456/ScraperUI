from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Plan(Base):
    __tablename__ = "plans"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, unique=True, nullable=False)   # basic / pro / premium
    label      = Column(String, nullable=False)
    price_usd  = Column(Numeric(10, 2), default=0)
    created_at = Column(DateTime, server_default=func.now())

    users = relationship("User", back_populates="plan")


class User(Base):
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    email      = Column(String, unique=True, index=True, nullable=False)
    name       = Column(String, nullable=True)
    password   = Column(String, nullable=False)
    credits    = Column(Integer, default=10)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # FK to plans — default 1 = basic
    plan_id    = Column(Integer, ForeignKey("plans.id"), default=1, nullable=False, server_default="1")
    plan       = relationship("Plan", back_populates="users")


class Lead(Base):
    __tablename__ = "leads"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    name       = Column(String)
    email      = Column(String)
    phone      = Column(String)
    website    = Column(String)
    outreach   = Column(String)
    niche      = Column(String)
    created_at = Column(DateTime, server_default=func.now())
