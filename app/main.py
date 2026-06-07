from fastapi import FastAPI
from app.routes import tts, ws

app = FastAPI(title="TTS Colab Server")

app.include_router(tts.router, tags=["TTS"])
app.include_router(ws.router, tags=["WebSocket"])

@app.get("/")
async def root():
    return {"message": "TTS Server is running"}
