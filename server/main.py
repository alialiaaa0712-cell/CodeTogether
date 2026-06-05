from fastapi import FastAPI
from server.routers import agents

app = FastAPI(title="CodeTogether")
app.include_router(agents.router)
