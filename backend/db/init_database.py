from backend.db.database import init_db

init_db()

# RUN " python -m backend.db.init_database "
# on the project root to initialize the database tables. 
# This is automatically called when the FastAPI app starts,
# but you can run it manually if needed.