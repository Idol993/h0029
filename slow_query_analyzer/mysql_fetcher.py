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
        self.warnings = []

    def fetch(self) -> List[SlowQueryRecord]:
        """从MySQL performance_schema获取语句统计"""
        self.warnings = []
        conn = self._connect()

        try:
            self._check_performance_schema(conn)
            self._ensure_consumers(conn)
            records = self._fetch_digest_stats(conn)

            if not records:
                records = self._fetch_sys_stats(conn)

            if not records:
                hints = self._get_empty_result_hints(conn)
                self.warnings.append(hints)

            return records
        finally:
            conn.close()

    def get_warnings(self) -> List[str]:
        """获取检查过程中的警告/提示信息"""
        return self.warnings

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
        """尝试开启关键consumer，权限不足时警告但不中断"""
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE performance_schema.setup_consumers
                    SET ENABLED = 'YES'
                    WHERE NAME IN ('events_statements_history_long', 'events_statements_history', 'events_statements_current')
                """)
                conn.commit()
        except (pymysql.err.OperationalError, pymysql.err.InternalError) as e:
            if e.args[0] in (1227, 1142):
                self.warnings.append(
                    "当前账号缺少修改 setup_consumers 的权限，无法自动开启语句事件消费者。"
                    f"若需要请执行: GRANT UPDATE ON performance_schema.setup_consumers TO '{self.user}'@'%';"
                )
            else:
                self.warnings.append(f"尝试开启consumer时出现非致命警告: {e}")

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

    def _get_empty_result_hints(self, conn: pymysql.Connection) -> str:
        """构造无统计时的排查建议"""
        check_items = []

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT NAME, ENABLED
                    FROM performance_schema.setup_consumers
                    WHERE NAME LIKE 'events_statements_%'
                """)
                consumers = cur.fetchall()
                disabled = [
                    r['NAME'] for r in consumers
                    if r.get('ENABLED', '').upper() != 'YES'
                ]
                if disabled:
                    check_items.append(
                        f"- 以下 consumer 未启用: {', '.join(disabled)}\n"
                        f"  请执行: UPDATE performance_schema.setup_consumers "
                        f"SET ENABLED='YES' WHERE NAME IN ({', '.join(repr(d) for d in disabled)});"
                    )
        except Exception:
            pass

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT NAME, ENABLED, TIMED
                    FROM performance_schema.setup_instruments
                    WHERE NAME LIKE 'statement/sql/%'
                    LIMIT 5
                """)
                instruments = cur.fetchall()
                disabled = [
                    r['NAME'] for r in instruments
                    if r.get('ENABLED', '').upper() != 'YES' or r.get('TIMED', '').upper() != 'YES'
                ]
                if disabled:
                    check_items.append(
                        f"- 部分 statement 采集器未启用或未计时\n"
                        f"  请执行: UPDATE performance_schema.setup_instruments "
                        f"SET ENABLED='YES', TIMED='YES' WHERE NAME LIKE 'statement/sql/%';"
                    )
        except Exception:
            pass

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM performance_schema.events_statements_summary_by_digest")
                total = cur.fetchone()
                if total and list(total.values())[0] == 0:
                    check_items.append(
                        "- events_statements_summary_by_digest 内无数据，可能是:\n"
                        "  a) MySQL刚重启，尚无足够查询流量\n"
                        "  b) digest_consumers 未开启\n"
                        "  c) 应用连接的账号默认schema为NULL导致无法归类"
                    )
        except Exception:
            pass

        check_items.append(
            "- 确认业务是否有真实SQL流量，或尝试查看: SHOW GLOBAL STATUS LIKE 'Questions';"
        )
        check_items.append(
            "- 查看慢日志是否有记录: SHOW VARIABLES LIKE 'slow_query_log'"
        )

        return (
            "performance_schema / sys 视图中暂无可分析的语句统计。\n"
            "建议按以下步骤排查:\n"
            + "\n".join(check_items)
        )
