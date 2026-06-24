#!/usr/bin/env python3
from pathlib import Path
from sqlalchemy import text
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from utils.database import init_db


def run_migration():
    migration_path = Path(__file__).resolve().parent / 'migrations' / 'add_school_id_multitenancy.sql'
    sql = migration_path.read_text()
    session = init_db()
    try:
        for statement in [chunk.strip() for chunk in sql.split(';') if chunk.strip()]:
            session.execute(text(statement))
        session.commit()
        print('✅ school_id multitenancy migration applied successfully')
    except Exception as exc:
        session.rollback()
        print(f'❌ school_id multitenancy migration failed: {exc}')
        raise
    finally:
        session.close()


if __name__ == '__main__':
    run_migration()
