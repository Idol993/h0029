"""MySQL慢查询日志解析器"""
import re
import os
from typing import List, Generator
from pathlib import Path
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, SpinnerColumn

from .models import SlowQueryRecord


class MySQLSlowLogParser:
    """MySQL慢查询日志解析器"""

    TIME_PATTERN = re.compile(r'^# Time:?\s*(.+)', re.IGNORECASE)
    USER_HOST_PATTERN = re.compile(r'^# User@Host:\s*(.+)', re.IGNORECASE)
    QUERY_TIME_PATTERN = re.compile(
        r'^# Query_time:\s*([\d.]+)\s+Lock_time:\s*([\d.]+)\s+Rows_sent:\s*(\d+)\s+Rows_examined:\s*(\d+)',
        re.IGNORECASE
    )
    QUERY_TIME_ALT_PATTERN = re.compile(
        r'^# Query_time:\s*([\d.]+)\s+Lock_time:\s*([\d.]+)\s+Rows_examined:\s*(\d+)\s+Rows_sent:\s*(\d+)',
        re.IGNORECASE
    )
    DB_PATTERN = re.compile(r'^use\s+([\w`]+);?', re.IGNORECASE)
    SET_TIMESTAMP_PATTERN = re.compile(r'^SET\s+timestamp\s*=\s*\d+;?', re.IGNORECASE)
    ADMIN_PATTERN = re.compile(r'^# administrator command:', re.IGNORECASE)
    VALID_SQL_PATTERN = re.compile(
        r'^\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|TRUNCATE|CALL|EXPLAIN|DESCRIBE|SHOW|BEGIN|COMMIT|ROLLBACK|SET|START|PREPARE|EXECUTE|DEALLOCATE|GRANT|REVOKE|FLUSH|KILL|RESET|REPAIR|OPTIMIZE|ANALYZE|CHECK|BACKUP|RESTORE)\b',
        re.IGNORECASE | re.DOTALL
    )

    def __init__(self, show_progress: bool = True):
        self.show_progress = show_progress

    def parse(self, log_path: str) -> List[SlowQueryRecord]:
        """解析慢查询日志文件，返回记录列表"""
        path = Path(log_path)
        if not path.exists():
            raise FileNotFoundError(f"日志文件不存在: {log_path}")

        file_size = path.stat().st_size
        raw_records = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]解析MySQL慢查询日志..."),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            disable=not self.show_progress,
        ) as progress:
            task = progress.add_task("parsing", total=file_size)

            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                current_entry = {}
                sql_lines = []
                in_sql = False

                for line in f:
                    progress.advance(task, len(line.encode('utf-8', errors='ignore')))

                    line_stripped = line.strip()

                    if not line_stripped:
                        if in_sql and sql_lines and 'query_time' in current_entry:
                            sql_text = '\n'.join(sql_lines)
                            if self._is_valid_sql(sql_text):
                                current_entry['sql'] = sql_text
                                raw_records.append(current_entry)
                            current_entry = {}
                            sql_lines = []
                            in_sql = False
                        continue

                    time_match = self.TIME_PATTERN.match(line_stripped)
                    if time_match:
                        if in_sql and sql_lines and 'query_time' in current_entry:
                            sql_text = '\n'.join(sql_lines)
                            if self._is_valid_sql(sql_text):
                                current_entry['sql'] = sql_text
                                raw_records.append(current_entry)
                        current_entry = {}
                        sql_lines = []
                        current_entry['timestamp'] = time_match.group(1).strip()
                        in_sql = False
                        continue

                    user_match = self.USER_HOST_PATTERN.match(line_stripped)
                    if user_match:
                        current_entry['user_host'] = user_match.group(1).strip()
                        in_sql = False
                        continue

                    qt_match = self.QUERY_TIME_PATTERN.match(line_stripped)
                    if qt_match:
                        current_entry['query_time'] = float(qt_match.group(1))
                        current_entry['lock_time'] = float(qt_match.group(2))
                        current_entry['rows_sent'] = int(qt_match.group(3))
                        current_entry['rows_examined'] = int(qt_match.group(4))
                        in_sql = False
                        continue

                    qt_alt_match = self.QUERY_TIME_ALT_PATTERN.match(line_stripped)
                    if qt_alt_match:
                        current_entry['query_time'] = float(qt_alt_match.group(1))
                        current_entry['lock_time'] = float(qt_alt_match.group(2))
                        current_entry['rows_examined'] = int(qt_alt_match.group(3))
                        current_entry['rows_sent'] = int(qt_alt_match.group(4))
                        in_sql = False
                        continue

                    if self.ADMIN_PATTERN.match(line_stripped):
                        continue

                    db_match = self.DB_PATTERN.match(line_stripped)
                    if db_match:
                        current_entry['database'] = db_match.group(1).strip('`')
                        continue

                    if self.SET_TIMESTAMP_PATTERN.match(line_stripped):
                        in_sql = True
                        continue

                    if line_stripped.startswith('#'):
                        continue

                    in_sql = True
                    sql_lines.append(line.rstrip('\n'))

                if in_sql and sql_lines and 'query_time' in current_entry:
                    current_entry['sql'] = '\n'.join(sql_lines)
                    raw_records.append(current_entry)

        return self._aggregate_records(raw_records)

    @staticmethod
    def _is_valid_sql(sql_text: str) -> bool:
        """检查是否为有效的SQL语句"""
        stripped = sql_text.strip()
        if not stripped:
            return False
        if stripped.startswith('/') or stripped.startswith('Tcp port:') or stripped.startswith('Time'):
            return False
        if MySQLSlowLogParser.VALID_SQL_PATTERN.match(stripped):
            return True
        return False

    def _aggregate_records(self, raw_records: List[dict]) -> List[SlowQueryRecord]:
        """按SQL指纹聚合记录"""
        record_map = {}

        for raw in raw_records:
            if 'sql' not in raw or not raw['sql'].strip():
                continue

            query_time = raw.get('query_time', 0)
            rows_examined = raw.get('rows_examined', 0)
            rows_sent = raw.get('rows_sent', 0)

            temp_record = SlowQueryRecord(
                sql=raw['sql'].strip(),
                total_time=query_time,
                rows_examined=rows_examined,
                rows_sent=rows_sent,
                database=raw.get('database'),
                timestamp=raw.get('timestamp'),
            )
            fp = temp_record.sql_fingerprint

            if fp in record_map:
                existing = record_map[fp]
                existing.exec_count += 1
                existing.total_time += query_time
                existing.rows_examined += rows_examined
                existing.rows_sent += rows_sent
            else:
                record_map[fp] = SlowQueryRecord(
                    sql=raw['sql'].strip(),
                    exec_count=1,
                    total_time=query_time,
                    rows_examined=rows_examined,
                    rows_sent=rows_sent,
                    database=raw.get('database'),
                    timestamp=raw.get('timestamp'),
                )

        result = []
        for rec in record_map.values():
            if rec.exec_count > 0:
                rec.avg_time = rec.total_time / rec.exec_count
            result.append(rec)

        return result
