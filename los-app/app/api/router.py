from fastapi import APIRouter
from app.api.endpoints import standalone, sequences, chain, auth

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication & Client Management"])
api_router.include_router(standalone.router, prefix="/standalone", tags=["Standalone Services"])
api_router.include_router(sequences.router, prefix="/sequences", tags=["Sequence Recipes"])
api_router.include_router(chain.router, prefix="/chain", tags=["Chain Orchestration"])
