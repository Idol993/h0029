"""MySQL直连获取器：从performance_schema / sys 读取语句统计"""
from typing import List

import pymysql
import pymysql.cursors

from .models import SlowQueryRecord


CHECK_PERFORMANCE_SCHEMA = "SELECT @@performance_schema"

CHECK_CONSUMERS_ENABLED = """
SELECT COUNT(*)
FROM performance_schema.setup_consumers
WHERE NAME IN ('events_statements_history_long', 'events_statements_history', 'events_statements_current')
  AND ENABLED = 'YES'
"""

QUERY_DIGEST = """
SELECT
    DIGEST_TEXT AS sql_text,
    SCHEMA_NAME AS database,
    COUNT_STAR AS exec_count,
    SUM_TIMER_WAIT / 1000000000000 AS total_time,
    AVG_TIMER_WAIT / 1000000000000 AS avg_time,
    SUM_ROWS_EXAMINED AS rows_examined,
    SUM_ROWS_SENT AS rows_sent
FROM performance_schema.events_statements_summary_by_digest
WHERE DIGEST_TEXT IS NOT NULL
  AND SCHEMA_NAME IS NOT NULL
  AND COUNT_STAR > 0
ORDER BY SUM_TIMER_WAIT DESC
LIMIT %s
"""

QUERY_SYS_STATEMENTS = """
SELECT
    query AS sql_text,
    db AS database,
    exec_count,
    avg_latency / 1000000000000 AS avg_time,
    total_latency / 1000000000000 AS total_time,
    rows_examined,
    rows_sent
FROM sys.statements_with_runtimes_in_95th_percentile
WHERE query IS NOT NULL
  AND db IS NOT NULL
ORDER BY total_latency DESC
LIMIT %s
"""


class MySQLDirectFetcher:
    """MySQL直连获取器：通过performance_schema获取语句统计"""

    def __init__(self, host: str = "localhost", port: int = 3306,
                 user: str = "root", password: str = "",
                 database: str = "", limit: int = 200):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.limit = limit

    def fetch(self) -> List[SlowQueryRecord]:
        """从MySQL performance_schema获取语句统计"""
        conn = self._connect()

        try:
            self._check_performance_schema(conn)
            self._ensure_consumers(conn)
            records = self._fetch_digest_stats(conn)

            if not records:
                records = self._fetch_sys_stats(conn)

            return records
        finally:
            conn.close()

    def _connect(self) -> pymysql.Connection:
        """建立MySQL连接"""
        try:
            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database or None,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=10,
            )
            return conn
        except pymysql.err.OperationalError as e:
            raise ConnectionError(
                f"无法连接到MySQL服务器 {self.host}:{self.port}: {e}"
            )

    def _check_performance_schema(self, conn: pymysql.Connection):
        """检查performance_schema是否启用"""
        with conn.cursor() as cur:
            cur.execute(CHECK_PERFORMANCE_SCHEMA)
            row = cur.fetchone()
            ps_enabled = list(row.values())[0] if row else 0

        if not ps_enabled:
            raise RuntimeError(
                "目标MySQL实例未启用 performance_schema。\n"
                "请在 my.cnf 中添加:\n"
                "  [mysqld]\n"
                "  performance_schema=ON\n"
                "然后重启MySQL实例。"
            )

    def _ensure_consumers(self, conn: pymysql.Connection):
        """确保关键consumer已启用"""
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE performance_schema.setup_consumers
                SET ENABLED = 'YES'
                WHERE NAME IN ('events_statements_history_long', 'events_statements_history', 'events_statements_current')
            """)
            conn.commit()

    def _fetch_digest_stats(self, conn: pymysql.Connection) -> List[SlowQueryRecord]:
        """从events_statements_summary_by_digest获取统计"""
        try:
            with conn.cursor() as cur:
                cur.execute(QUERY_DIGEST, (self.limit,))
                rows = cur.fetchall()
        except pymysql.err.OperationalError as e:
            if e.args[0] == 1227:
                raise PermissionError(
                    "当前用户没有 performance_schema 的查询权限。\n"
                    f"请为用户 '{self.user}' 授予权限:\n"
                    f"  GRANT SELECT ON performance_schema.* TO '{self.user}'@'%';\n"
                    f"  FLUSH PRIVILEGES;"
                )
            raise

        records = []
        for row in rows:
            sql_text = str(row.get('sql_text', '')).strip()
            if not sql_text:
                continue

            record = SlowQueryRecord(
                sql=sql_text,
                exec_count=int(row.get('exec_count', 0) or 0),
                avg_time=float(row.get('avg_time', 0) or 0),
                total_time=float(row.get('total_time', 0) or 0),
                rows_examined=int(row.get('rows_examined', 0) or 0),
                rows_sent=int(row.get('rows_sent', 0) or 0),
                database=row.get('database'),
            )
            records.append(record)

        return records

    def _fetch_sys_stats(self, conn: pymysql.Connection) -> List[SlowQueryRecord]:
        """从sys.statements_with_runtimes_in_95th_percentile获取统计（备选）"""
        try:
            with conn.cursor() as cur:
                cur.execute(QUERY_SYS_STATEMENTS, (self.limit,))
                rows = cur.fetchall()
        except (pymysql.err.OperationalError, pymysql.err.ProgrammingError):
            return []

        records = []
        for row in rows:
            sql_text = str(row.get('sql_text', '')).strip()
            if not sql_text:
                continue

            record = SlowQueryRecord(
                sql=sql_text,
                exec_count=int(row.get('exec_count', 0) or 0),
                avg_time=float(row.get('avg_time', 0) or 0),
                total_time=float(row.get('total_time', 0) or 0),
                rows_examined=int(row.get('rows_examined', 0) or 0),
                rows_sent=int(row.get('rows_sent', 0) or 0),
                database=row.get('database'),
            )
            records.append(record)

        return records
