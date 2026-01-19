import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.config import LIVEKIT_URL

# 1. Initialize FastAPI with production metadata
# This unified backend handles both PPT processing and AI coordination.
app = FastAPI(
    title="Unified Dia AI Presenter API",
    description="Backend for PPT processing and LiveKit Avatar integration.",
    version="2.0.0",
)

# 2. Configure CORS (Cross-Origin Resource Sharing)
# Using "*" allows all origins (including localhost:3000 and 5500) to communicate.
# This resolves potential 'OPTIONS 400' or CORS errors in browser requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# 3. Include Slide & Token Routes
# This router handles the logic for /upload-ppt and /livekit/token.
app.include_router(router)


# 4. System Health Check (Root)
@app.get("/", tags=["System"])
async def root():
    """
    Standard health check for cloud load balancers.
    """
    return {
        "status": "online",
        "service": "Unified AI Presenter",
        "livekit_url": LIVEKIT_URL,
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


# 5. Dedicated Health Check Endpoint
# Added specifically to satisfy cloud monitors (like Render) looking for /health.
@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "service": "api-routes-dia"}


# 6. Production Server Entrypoint
if __name__ == "__main__":
    # Use the port assigned by the environment (e.g., Render) or default to 8000
    port = int(os.getenv("PORT", 8000))

    # Enable auto-reload only in development mode
    is_dev = os.getenv("ENVIRONMENT", "development") == "development"

    print(f"🚀 Starting Unified Server on port {port} (Dev Mode: {is_dev})")

    uvicorn.run(
        "app.api.main:app",
        host="0.0.0.0",
        port=port,
        reload=is_dev,
        workers=int(os.getenv("WEB_CONCURRENCY", 1)),
    )
