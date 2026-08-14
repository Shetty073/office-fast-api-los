from fastapi import FastAPI
from database import engine, Base
from routes import router
import services  # Imports package to execute registration decorators for all services

# Automate DB table schema migrations/creations at startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SCF LOS API Engine",
    description="Backend onboarding engine orchestrating standalone and chained third-party API calls.",
    version="1.0.0"
)

app.include_router(router)

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "SCF LOS Backend Engine is running successfully.",
        "registered_services": services.ServiceRegistry.list_services()
    }
