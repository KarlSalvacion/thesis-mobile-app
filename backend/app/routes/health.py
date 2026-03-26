from fastapi import APIRouter

from db.database import get_pending_compression_jobs

router = APIRouter()


@router.get('/health')
async def health_check():
    """Health check endpoint with memory usage for Render.com monitoring."""
    import psutil

    try:
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_available_mb = memory.available / (1024 * 1024)

        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_free_mb = disk.free / (1024 * 1024)

        queued_jobs = len(get_pending_compression_jobs())

        return {
            'status': 'healthy',
            'memory': {
                'percent': memory_percent,
                'available_mb': round(memory_available_mb, 1),
                'total_mb': round(memory.total / (1024 * 1024), 1),
            },
            'disk': {'percent': disk_percent, 'free_mb': round(disk_free_mb, 1)},
            'jobs': {'active': 0, 'queued': queued_jobs, 'total': queued_jobs},
            'render_plan': 'standard_2gb_1cpu',
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e), 'render_plan': 'standard_2gb_1cpu'}
