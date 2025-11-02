# PostgreSQL Migration Guide

## Overview

This application has been migrated from SQLite to PostgreSQL for better performance, scalability, and concurrent access support.

## Setup Instructions

### 1. Install PostgreSQL

**Windows:**
- Download from https://www.postgresql.org/download/windows/
- Run the installer and follow the prompts
- Remember your postgres superuser password

**macOS:**
```bash
brew install postgresql
brew services start postgresql
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

### 2. Create Database

**Local Development:**
```bash
# Access PostgreSQL prompt
psql -U postgres

# Create database
CREATE DATABASE weed_detection;

# Create user (optional)
CREATE USER weed_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE weed_detection TO weed_user;

# Exit
\q
```

### 3. Configure Environment Variables

**Option A: Create `.env` file in backend folder:**
```env
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/weed_detection
```

**Option B: Set environment variable directly:**

Windows PowerShell:
```powershell
$env:DATABASE_URL="postgresql://postgres:your_password@localhost:5432/weed_detection"
```

Linux/macOS:
```bash
export DATABASE_URL="postgresql://postgres:your_password@localhost:5432/weed_detection"
```

### 4. Install Python Dependencies

```bash
cd backend
pip install -r requirements.txt
```

This will install `psycopg2-binary` (PostgreSQL adapter) along with other dependencies.

### 5. Run the Application

```bash
# From project root
cd backend
uvicorn backend.main:app --reload
```

The application will automatically:
- Create a connection pool
- Initialize all database tables
- Create indexes for optimal performance

## For Render.com Deployment

### 1. Create PostgreSQL Database

1. Go to Render Dashboard → New → PostgreSQL
2. Choose a name (e.g., `weed-detection-db`)
3. Select region and instance type
4. Click "Create Database"

### 2. Get Connection String

From your PostgreSQL dashboard, copy the **Internal Database URL** (starts with `postgresql://`).

### 3. Configure Web Service

In your Render Web Service settings:
1. Go to Environment tab
2. Add environment variable:
   - Key: `DATABASE_URL`
   - Value: (paste your Internal Database URL)

### 4. Deploy

Render will automatically:
- Install `psycopg2-binary` from requirements.txt
- Connect to PostgreSQL using the DATABASE_URL
- Initialize tables on first run

## Key Differences from SQLite

| Feature | SQLite | PostgreSQL |
|---------|--------|-----------|
| Connection | File-based | Client-server |
| Concurrency | Limited | Excellent |
| Placeholders | `?` | `%s` |
| Auto-increment | `AUTOINCREMENT` | `SERIAL` |
| Boolean | 0/1 | TRUE/FALSE |
| Connection Pool | None | Built-in |

## Database Schema

The migration preserves all existing tables:

- `detections` - Main detection sessions
- `detection_details` - Individual weed detections per frame
- `srt_tracks` - GPS trajectory data
- `heatmaps` - Aggregated heatmap grids
- `processing_jobs` - Background job queue

## Configuration

Edit `backend/config.py` to adjust:

```python
# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://...')

# Connection pool settings
DB_POOL_MIN_CONN = 1  # Minimum connections
DB_POOL_MAX_CONN = 10  # Maximum connections
DB_POOL_TIMEOUT = 30  # Connection timeout in seconds
```

## Troubleshooting

### Connection Errors

**Error:** `could not connect to server`

**Solution:** Make sure PostgreSQL service is running:
```bash
# Windows
net start postgresql-x64-14

# macOS
brew services start postgresql

# Linux
sudo systemctl start postgresql
```

### Authentication Failed

**Error:** `password authentication failed`

**Solution:** 
1. Check your DATABASE_URL has the correct password
2. Reset password if needed:
```bash
psql -U postgres
ALTER USER postgres WITH PASSWORD 'new_password';
```

### Database Does Not Exist

**Error:** `database "weed_detection" does not exist`

**Solution:** Create it:
```bash
psql -U postgres -c "CREATE DATABASE weed_detection;"
```

### Permission Issues

**Error:** `permission denied for table detections`

**Solution:** Grant permissions:
```bash
psql -U postgres -d weed_detection
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO your_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO your_user;
```

## Migrating Existing SQLite Data (Optional)

If you have existing SQLite data you want to migrate:

### Option 1: Using pgloader (Recommended)

```bash
# Install pgloader
sudo apt install pgloader  # Linux
brew install pgloader      # macOS

# Run migration
pgloader backend/weed_detection.db postgresql://postgres:password@localhost/weed_detection
```

### Option 2: Manual Export/Import

```bash
# Export from SQLite
sqlite3 backend/weed_detection.db .dump > dump.sql

# Edit dump.sql to convert SQLite syntax to PostgreSQL
# - Change AUTOINCREMENT to SERIAL
# - Change ? to %s in parameterized queries
# - Change TEXT to VARCHAR or TEXT as needed

# Import to PostgreSQL
psql -U postgres -d weed_detection < dump.sql
```

## Backup and Restore

### Backup
```bash
pg_dump -U postgres weed_detection > backup.sql
```

### Restore
```bash
psql -U postgres -d weed_detection < backup.sql
```

## Performance Tips

1. **Connection Pooling**: Already configured (1-10 connections)
2. **Indexes**: Automatically created on first run
3. **Analyze**: Run periodically for query optimization
   ```sql
   ANALYZE detections;
   ANALYZE detection_details;
   ```

## Support

For issues or questions:
1. Check PostgreSQL logs: `tail -f /var/log/postgresql/postgresql-14-main.log`
2. Enable debug logging in FastAPI
3. Check Render logs if deployed

## References

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [psycopg2 Documentation](https://www.psycopg.org/docs/)
- [Render PostgreSQL Guide](https://render.com/docs/databases)
