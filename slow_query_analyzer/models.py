"""数据模型定义"""
from dataclasses import dataclass, field
from typing import List, Optional
import hashlib


@dataclass
class SlowQueryRecord:
    """慢查询记录"""
    sql: str
    exec_count: int = 1
    avg_time: float = 0.0
    total_time: float = 0.0
    rows_examined: int = 0
    rows_sent: int = 0
    database: Optional[str] = None
    timestamp: Optional[str] = None
    severity_score: float = 0.0
    patterns: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    sql_fingerprint: str = ""

    def __post_init__(self):
        if not self.sql_fingerprint and self.sql:
            self.sql_fingerprint = self._generate_fingerprint(self.sql)
        if self.total_time == 0 and self.avg_time > 0 and self.exec_count > 0:
            self.total_time = self.avg_time * self.exec_count
        if self.avg_time == 0 and self.total_time > 0 and self.exec_count > 0:
            self.avg_time = self.total_time / self.exec_count

    @staticmethod
    def _generate_fingerprint(sql: str) -> str:
        """生成SQL指纹（归一化后的哈希）"""
        import re
        normalized = sql.strip().lower()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = re.sub(r"'[^']*'", '?', normalized)
        normalized = re.sub(r'"[^"]*"', '?', normalized)
        normalized = re.sub(r'\b\d+\b', '?', normalized)
        normalized = re.sub(r'\b\d+\.\d+\b', '?', normalized)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()


@dataclass
class AnalysisResult:
    """分析结果"""
    records: List[SlowQueryRecord]
    total_queries: int = 0
    total_time: float = 0.0
    high_severity_count: int = 0
    medium_severity_count: int = 0
    low_severity_count: int = 0


@dataclass
class ComparisonResult:
    """对比结果"""
    added: List[SlowQueryRecord] = field(default_factory=list)
    removed: List[SlowQueryRecord] = field(default_factory=list)
    worsened: List[tuple] = field(default_factory=list)
    improved: List[tuple] = field(default_factory=list)
    unchanged: List[tuple] = field(default_factory=list)
