from fastapi import APIRouter, Depends
from app.api.endpoints import standalone, sequences, chain, auth
from app.api.deps import get_current_user

api_router = APIRouter()

# Public / Authentication router (Login endpoint is open; admin routes inside auth.py check admin dependency)
api_router.include_router(
    auth.router, 
    prefix="/auth", 
    tags=["Authentication & Client Management"]
)

# Protected Business Routers: Enforce valid Bearer JWT on all endpoints as per RBI Cyber Security / DPDP guidelines
api_router.include_router(
    standalone.router, 
    prefix="/standalone", 
    tags=["Standalone Services"],
    dependencies=[Depends(get_current_user)]
)

api_router.include_router(
    sequences.router, 
    prefix="/sequences", 
    tags=["Sequence Recipes"],
    dependencies=[Depends(get_current_user)]
)

api_router.include_router(
    chain.router, 
    prefix="/chain", 
    tags=["Chain Orchestration"],
    dependencies=[Depends(get_current_user)]
)
