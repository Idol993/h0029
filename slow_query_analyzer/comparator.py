"""趋势对比模块：对比两个时间段的慢查询日志"""
from typing import List, Dict

from .models import SlowQueryRecord, ComparisonResult


class QueryComparator:
    """慢查询对比器"""

    WORSEN_THRESHOLD = 1.5
    IMPROVE_THRESHOLD = 0.67

    def compare(self, baseline: List[SlowQueryRecord], current: List[SlowQueryRecord]) -> ComparisonResult:
        """对比基线和当前的慢查询记录"""
        baseline_map: Dict[str, SlowQueryRecord] = {
            r.sql_fingerprint: r for r in baseline
        }
        current_map: Dict[str, SlowQueryRecord] = {
            r.sql_fingerprint: r for r in current
        }

        result = ComparisonResult()

        for fp, curr_rec in current_map.items():
            if fp not in baseline_map:
                result.added.append(curr_rec)
            else:
                base_rec = baseline_map[fp]
                ratio = curr_rec.total_time / max(base_rec.total_time, 0.001)
                if ratio >= self.WORSEN_THRESHOLD:
                    result.worsened.append((base_rec, curr_rec, ratio))
                elif ratio <= self.IMPROVE_THRESHOLD:
                    result.improved.append((base_rec, curr_rec, ratio))
                else:
                    result.unchanged.append((base_rec, curr_rec, ratio))

        for fp, base_rec in baseline_map.items():
            if fp not in current_map:
                result.removed.append(base_rec)

        sort_key = lambda r: r.severity_score if r.severity_score > 0 else r.total_time
        result.added.sort(key=sort_key, reverse=True)
        result.removed.sort(key=sort_key, reverse=True)
        result.worsened.sort(key=lambda x: x[2], reverse=True)
        result.improved.sort(key=lambda x: x[2])

        return result
