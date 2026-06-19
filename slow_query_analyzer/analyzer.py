"""智能分析模块：计算严重分数、SQL模式匹配、优化建议"""
import re
from typing import List, Tuple
import sqlparse

from .models import SlowQueryRecord, AnalysisResult


class QueryAnalyzer:
    """SQL查询分析器"""

    HIGH_SEVERITY_THRESHOLD = 1000000
    MEDIUM_SEVERITY_THRESHOLD = 100000

    PATTERNS = [
        {
            'name': 'SELECT *',
            'regex': re.compile(r'SELECT\s+\*\s+FROM', re.IGNORECASE),
            'suggestion': '避免使用 SELECT *，只查询需要的字段以减少数据传输和内存占用'
        },
        {
            'name': '全表扫描(大表)',
            'check_func': 'check_full_table_scan',
            'suggestion': '可能存在全表扫描，检查WHERE条件字段是否有合适索引'
        },
        {
            'name': '缺索引JOIN',
            'check_func': 'check_unindexed_join',
            'suggestion': '多表JOIN可能缺少索引，检查JOIN ON字段是否有索引'
        },
        {
            'name': 'LIKE前导通配符',
            'regex': re.compile(r"LIKE\s+['\"]%", re.IGNORECASE),
            'suggestion': 'LIKE前导通配符(%xxx)会导致全表扫描，考虑使用全文索引或反转字段'
        },
        {
            'name': 'WHERE字段函数运算',
            'regex': re.compile(r'WHERE\s+.*?\b\w+\s*\([^)]*\)\s*[=<>!]', re.IGNORECASE | re.DOTALL),
            'suggestion': '避免在WHERE条件中对字段使用函数，这会使索引失效'
        },
        {
            'name': '隐式类型转换',
            'regex': re.compile(r"WHERE\s+\w+\s*=\s*['\"]?\d+['\"]?\s*(?:AND|OR|$)", re.IGNORECASE),
            'suggestion': '检查是否存在隐式类型转换，确保比较两侧数据类型一致'
        },
        {
            'name': 'LIMIT缺失',
            'check_func': 'check_missing_limit',
            'suggestion': '查询可能返回大量数据，考虑添加LIMIT限制结果集大小'
        },
        {
            'name': 'ORDER BY + LIMIT可优化',
            'regex': re.compile(r'ORDER\s+BY\s+[\w\.]+\s+(?:ASC|DESC)?\s*(?:,|$)', re.IGNORECASE),
            'suggestion': 'ORDER BY字段建议建立索引以避免filesort'
        },
        {
            'name': 'GROUP BY非索引字段',
            'regex': re.compile(r'GROUP\s+BY\s+', re.IGNORECASE),
            'suggestion': 'GROUP BY字段建议建立索引以避免临时表和filesort'
        },
        {
            'name': 'DISTINCT使用',
            'regex': re.compile(r'SELECT\s+DISTINCT\s+', re.IGNORECASE),
            'suggestion': 'DISTINCT可能导致去重开销大，考虑是否可用GROUP BY或EXISTS替代'
        },
        {
            'name': '子查询',
            'regex': re.compile(r'\(\s*SELECT\s+', re.IGNORECASE),
            'suggestion': '子查询可能性能较差，考虑改写为JOIN连接查询'
        },
        {
            'name': 'OR条件',
            'regex': re.compile(r'\bOR\b', re.IGNORECASE),
            'suggestion': '多个OR条件可能影响索引使用，考虑改写为UNION或建立合适的复合索引'
        },
    ]

    def analyze(self, records: List[SlowQueryRecord]) -> AnalysisResult:
        """分析一组慢查询记录"""
        for record in records:
            record.severity_score = self._calc_severity_score(record)
            record.patterns, record.suggestions = self._analyze_patterns(record)

        records.sort(key=lambda r: r.severity_score, reverse=True)

        result = AnalysisResult(
            records=records,
            total_queries=len(records),
            total_time=sum(r.total_time for r in records),
        )

        for r in records:
            if r.severity_score >= self.HIGH_SEVERITY_THRESHOLD:
                result.high_severity_count += 1
            elif r.severity_score >= self.MEDIUM_SEVERITY_THRESHOLD:
                result.medium_severity_count += 1
            else:
                result.low_severity_count += 1

        return result

    def _calc_severity_score(self, record: SlowQueryRecord) -> float:
        """计算严重分数：执行次数 × 平均耗时(秒) × 扫描行数"""
        count_weight = record.exec_count
        time_weight = max(record.avg_time, 0.001)
        rows_weight = max(record.rows_examined, 1)
        return round(count_weight * time_weight * rows_weight, 2)

    def _analyze_patterns(self, record: SlowQueryRecord) -> Tuple[List[str], List[str]]:
        """分析SQL模式并返回匹配的模式和建议"""
        matched_patterns = []
        suggestions = []
        sql = record.sql

        for pattern in self.PATTERNS:
            if 'regex' in pattern and pattern['regex'].search(sql):
                matched_patterns.append(pattern['name'])
                suggestions.append(pattern['suggestion'])
            elif 'check_func' in pattern:
                check_fn = getattr(self, pattern['check_func'], None)
                if check_fn and check_fn(sql, record):
                    matched_patterns.append(pattern['name'])
                    suggestions.append(pattern['suggestion'])

        return matched_patterns, suggestions

    @staticmethod
    def check_full_table_scan(sql: str, record: SlowQueryRecord) -> bool:
        """检查是否可能全表扫描（扫描行数远大于返回行数且行数较多）"""
        if record.rows_examined >= 1000 and record.rows_sent > 0:
            ratio = record.rows_examined / max(record.rows_sent, 1)
            return ratio >= 10
        if record.rows_examined >= 10000:
            return True
        return False

    @staticmethod
    def check_unindexed_join(sql: str, record: SlowQueryRecord) -> bool:
        """检查是否可能缺少索引的JOIN"""
        has_join = bool(re.search(r'\b(JOIN|INNER\s+JOIN|LEFT\s+JOIN|RIGHT\s+JOIN)\b', sql, re.IGNORECASE))
        if not has_join:
            return False
        if record.rows_examined >= 5000:
            return True
        return False

    @staticmethod
    def check_missing_limit(sql: str, record: SlowQueryRecord) -> bool:
        """检查是否缺少LIMIT且返回行数较多"""
        has_limit = bool(re.search(r'\bLIMIT\s+\d+', sql, re.IGNORECASE))
        if has_limit:
            return False
        if record.rows_sent >= 100:
            return True
        return False

    @staticmethod
    def format_sql(sql: str) -> str:
        """格式化SQL"""
        return sqlparse.format(sql, reindent=True, keyword_case='upper')

    @staticmethod
    def get_severity_level(score: float) -> Tuple[str, str]:
        """获取严重级别和对应的颜色"""
        if score >= QueryAnalyzer.HIGH_SEVERITY_THRESHOLD:
            return ("严重", "red")
        elif score >= QueryAnalyzer.MEDIUM_SEVERITY_THRESHOLD:
            return ("中等", "yellow")
        else:
            return ("轻微", "green")
