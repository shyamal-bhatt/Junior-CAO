"""
api/v1/router.py
────────────────
Central v1 router — aggregates all endpoint routers into one.
main.py includes this single router under /api/v1.

To add a new feature:
  1. Create app/api/v1/endpoints/your_feature.py
  2. Import and include its router here.
"""

from fastapi import APIRouter
from app.api.v1.endpoints import chat

router = APIRouter()

router.include_router(chat.router)
