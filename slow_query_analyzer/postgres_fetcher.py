"""PostgreSQL pg_stat_statements 数据获取器"""
from typing import List, Optional

from .models import SlowQueryRecord


PG_STAT_QUERY = """
SELECT
    query,
    calls AS exec_count,
    mean_exec_time / 1000.0 AS avg_time,
    total_exec_time / 1000.0 AS total_time,
    COALESCE(rows, 0) AS rows_sent,
    COALESCE(shared_blks_hit + shared_blks_read + shared_blks_dirtied + shared_blks_written +
             local_blks_hit + local_blks_read + local_blks_dirtied + local_blks_written, 0) AS rows_examined,
    datname AS database
FROM pg_stat_statements
JOIN pg_database ON pg_stat_statements.dbid = pg_database.oid
WHERE query IS NOT NULL
  AND query !~* '^(BEGIN|COMMIT|ROLLBACK|SET|SHOW|BEGIN|COMMIT)'
ORDER BY total_exec_time DESC
LIMIT %s
"""


class PostgresStatsFetcher:
    """PostgreSQL pg_stat_statements 数据获取器"""

    def __init__(self, host: str = "localhost", port: int = 5432,
                 user: str = "postgres", password: str = "",
                 database: str = "postgres", limit: int = 200,
                 show_progress: bool = True):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.limit = limit
        self.show_progress = show_progress

    def fetch(self) -> List[SlowQueryRecord]:
        """从pg_stat_statements获取慢查询数据"""
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise ImportError(
                "需要安装 psycopg2-binary 包: pip install psycopg2-binary"
            )

        conn = None
        try:
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
            )

            self._ensure_extension(conn)

            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(PG_STAT_QUERY, (self.limit,))
                rows = cur.fetchall()

            records = []
            for row in rows:
                sql = str(row['query']).strip()
                if not sql:
                    continue

                record = SlowQueryRecord(
                    sql=sql,
                    exec_count=int(row['exec_count'] or 0),
                    avg_time=float(row['avg_time'] or 0),
                    total_time=float(row['total_time'] or 0),
                    rows_examined=int(row['rows_examined'] or 0),
                    rows_sent=int(row['rows_sent'] or 0),
                    database=row['database'],
                )
                records.append(record)

            return records

        finally:
            if conn:
                conn.close()

    def _ensure_extension(self, conn):
        """确保pg_stat_statements扩展已启用"""
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'")
            if not cur.fetchone():
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
                conn.commit()
