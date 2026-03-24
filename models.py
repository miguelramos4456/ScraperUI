from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Numeric, Text
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
    plan_id    = Column(Integer, ForeignKey("plans.id"), default=1, nullable=False, server_default="1")
    plan       = relationship("Plan", back_populates="users")
    saved_resources = relationship("SavedResource", back_populates="user", cascade="all, delete-orphan")

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

class SavedResource(Base):
    __tablename__ = "saved_resources"
    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    title       = Column(String, nullable=False)
    url         = Column(String, nullable=False)
    source      = Column(String)
    type        = Column(String)          # pdf / article / practice
    description = Column(Text)
    query       = Column(String)          # what search query found this
    created_at  = Column(DateTime, server_default=func.now())
    user = relationship("User", back_populates="saved_resources")
