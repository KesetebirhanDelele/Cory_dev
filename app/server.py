from fastapi import FastAPI
from app.web import webhook  # ✅ only imported here

app = FastAPI(title="Cory Admissions API")

# Register routes
app.include_router(webhook.router)
