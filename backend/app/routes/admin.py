from fastapi import APIRouter, HTTPException, Query
from psycopg2.extras import RealDictCursor

from db.database import get_db_connection, init_db, reset_compact_tables

router = APIRouter()


@router.post('/admin/reset-compact-tables')
async def admin_reset_compact_tables(confirm: bool = Query(False, description='Set true to confirm reset')):
    if not confirm:
        raise HTTPException(status_code=400, detail='Confirmation required: set confirm=true')
    reset_compact_tables()
    return {'message': 'Compact tables reset: srt_tracks, heatmaps'}


@router.post('/admin/reset-db')
async def admin_reset_db(confirm: bool = Query(False, description='Set true to confirm full DB reset (drop all tables)')):
    if not confirm:
        raise HTTPException(status_code=400, detail='Confirmation required: set confirm=true')
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            tables = ['processing_jobs', 'detection_details', 'heatmaps', 'srt_tracks', 'detections']
            for table in tables:
                cursor.execute(f'DROP TABLE IF EXISTS {table} CASCADE')
            conn.commit()
        init_db()
        return {'message': 'Database tables dropped and recreated'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to reset database: {e}')


@router.post('/admin/drop-tables')
async def admin_drop_tables(
    tables: str = Query('', description='Comma-separated table names to drop'),
    confirm: bool = Query(False),
):
    if not confirm:
        raise HTTPException(status_code=400, detail='Confirmation required: set confirm=true')
    if not tables:
        raise HTTPException(status_code=400, detail='Provide table names via tables query param')
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            dropped = []
            for name in [t.strip() for t in tables.split(',') if t.strip()]:
                cursor.execute(f'DROP TABLE IF EXISTS {name} CASCADE')
                dropped.append(name)
            conn.commit()
            return {'message': 'Dropped tables', 'dropped': dropped}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
