import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db.database import close_connection_pool, init_db

from app.routes.admin import router as admin_router
from app.routes.detections import router as detections_router
from app.routes.health import router as health_router
from app.routes.jobs import router as jobs_router
from app.routes.maps_reports import router as maps_reports_router
from app.routes.uploads import router as uploads_router

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

UPLOAD_DIR = os.getenv('UPLOAD_DIR', 'uploads')
if os.path.isdir(UPLOAD_DIR):
    try:
        app.mount('/uploads', StaticFiles(directory=UPLOAD_DIR), name='uploads')
    except Exception:
        pass

init_db()

app.include_router(uploads_router)
app.include_router(jobs_router)
app.include_router(health_router)
app.include_router(detections_router)
app.include_router(admin_router)
app.include_router(maps_reports_router)


@app.on_event('shutdown')
def shutdown_event() -> None:
    close_connection_pool()


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=8000)
