from fastapi import APIRouter

from app.api.routes import dashboard, imports, quotes


api_router = APIRouter()
api_router.include_router(imports.router, prefix="/imports", tags=["imports"])
api_router.include_router(quotes.router, prefix="/quotes", tags=["quotes"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
