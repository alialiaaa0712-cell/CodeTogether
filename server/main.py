from fastapi import FastAPI
from server.routers import agents, events, chat, memory

app = FastAPI(title="CodeTogether")
app.include_router(agents.router)
app.include_router(events.router)
app.include_router(chat.router)
app.include_router(memory.router)
