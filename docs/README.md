# SCF LOS API Engine Documentation Index

Welcome to the comprehensive technical and operational documentation for the **Supply Chain Finance (SCF) Loan Origination System (LOS) API Engine**.

---

## Documentation Sections

### 1. [FastAPI Core Service (`los-app/`)](file:///f:/office-fast-api-los/docs/fastapi/overview.md)
Detailed walkthrough of the FastAPI web application, API gateways, security middlewares, SQLAlchemy connection pool tuning, and automatic column migrations.
- [FastAPI Overview & Middlewares](file:///f:/office-fast-api-los/docs/fastapi/overview.md)

### 2. [Orchestration Service (`orchestration-service/`)](file:///f:/office-fast-api-los/docs/orchestrator/overview.md)
Complete breakdown of the ARQ asynchronous background execution worker, DAG execution engine, `TokenManager`, dynamic JSON transformations, Saga rollbacks, and rate limit handlers.
- [Orchestrator Overview & Worker Mechanics](file:///f:/office-fast-api-los/docs/orchestrator/overview.md)

### 3. [How-To Guides (Junior Developer Onboarding)](file:///f:/office-fast-api-los/docs/how_to/guides.md)
Practical, copy-pasteable step-by-step guides for:
- [Adding a New Standalone Service](file:///f:/office-fast-api-los/docs/how_to/guides.md#guide-1-how-to-add-a-new-standalone-service)
- [Creating and Registering Sequence Recipes](file:///f:/office-fast-api-los/docs/how_to/guides.md#guide-2-how-to-create-and-register-a-new-sequence-recipe)
- [Triggering Workflows and Checking Live Status](file:///f:/office-fast-api-los/docs/how_to/guides.md#guide-3-how-to-trigger-a-sequence-and-query-its-status)
- [Resuming Workflows from Point of Failure](file:///f:/office-fast-api-los/docs/how_to/guides.md#guide-4-how-to-resume-a-failed-sequence-from-point-of-failure)

### 4. [Technical Architecture & Enterprise Scaling (Architect Pitch)](file:///f:/office-fast-api-los/docs/architecture/overview.md)
High-to-low architectural review, process-level execution walkthrough, AWS ECS production deployment blueprint, and deep comparison matrix of **FastAPI + ARQ vs FastAPI + Celery**.
- [Architecture & Enterprise Scaling](file:///f:/office-fast-api-los/docs/architecture/overview.md)
