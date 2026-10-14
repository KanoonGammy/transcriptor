import os
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    BASE_DIR,
    HOST,
    PORT,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_ADMIN_PASSWORD,
)
from app.database import init_db
from app.storage_manager import run_retention_cleanup
from app.routes import (
    auth as auth_router,
    transcriptions as transcriptions_router,
    users as users_router,
    settings as settings_router,
    logs as logs_router,
)

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("transcriptor")

async def periodic_cleanup_scheduler():
    """Background task running every 6 hours to enforce retention policy."""
    while True:
        try:
            await asyncio.sleep(6 * 3600)
            logger.info("Executing scheduled storage retention cleanup...")
            res = run_retention_cleanup()
            logger.info("Periodic cleanup finished: freed %d files", res.get("deleted_files", 0))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in storage cleanup loop: %s", e)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully.")
    
    # Run initial retention cleanup once
    try:
        run_retention_cleanup()
    except Exception as e:
        logger.warning("Initial cleanup check warning: %s", e)

    # Launch background retention scheduler
    cleanup_task = asyncio.create_task(periodic_cleanup_scheduler())

    yield

    # Shutdown
    cleanup_task.cancel()
    logger.info("Server shutting down.")

app = FastAPI(
    title="Transcriptor Pro",
    description="Professional Speech-to-Text Web Application powered by ElevenLabs Scribe",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(auth_router.router)
app.include_router(transcriptions_router.router)
app.include_router(users_router.router)
app.include_router(settings_router.router)
app.include_router(logs_router.router)

# Mount static files
static_dir = BASE_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Mount templates / index.html
templates_dir = BASE_DIR / "templates"
templates_dir.mkdir(parents=True, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = templates_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>Transcriptor Pro is running</h1><p>Frontend template not found.</p>")

@app.get("/health")
def health_check():
    return {"status": "ok", "app": "Transcriptor Pro"}

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Transcriptor Pro on http://%s:%s", HOST, PORT)
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
