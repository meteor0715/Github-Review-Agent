from fastapi import FastAPI
from app.webhook_handler import router

app = FastAPI(title="GitHub Review Agent")

app.include_router(router)


@app.get("/ping")
async def ping():
    return {"status": "ok"}
