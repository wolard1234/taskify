"""
Entry point for the Taskify web panel.
Run with: python run_web.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from database.db import init_db
from web.app import app

if __name__ == "__main__":
    init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
