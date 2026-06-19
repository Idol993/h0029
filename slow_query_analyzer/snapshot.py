"""快照序列化模块：保存/加载慢查询记录快照，支持跨数据源基线对比"""
import json
from datetime import datetime
from pathlib import Path
from typing import List

from .models import SlowQueryRecord


def records_to_snapshot(records: List[SlowQueryRecord], source: str = "") -> dict:
    """将记录列表序列化为快照字典"""
    items = []
    for r in records:
        items.append({
            'sql': r.sql,
            'sql_fingerprint': r.sql_fingerprint,
            'exec_count': r.exec_count,
            'avg_time': r.avg_time,
            'total_time': r.total_time,
            'rows_examined': r.rows_examined,
            'rows_sent': r.rows_sent,
            'database': r.database,
            'timestamp': r.timestamp,
        })
    return {
        'version': '1.0',
        'created_at': datetime.now().isoformat(),
        'source': source,
        'record_count': len(records),
        'records': items,
    }


def snapshot_to_records(snapshot: dict) -> List[SlowQueryRecord]:
    """从快照字典反序列化为记录列表"""
    items = snapshot.get('records', [])
    records = []
    for item in items:
        record = SlowQueryRecord(
            sql=item['sql'],
            exec_count=item.get('exec_count', 1),
            avg_time=item.get('avg_time', 0),
            total_time=item.get('total_time', 0),
            rows_examined=item.get('rows_examined', 0),
            rows_sent=item.get('rows_sent', 0),
            database=item.get('database'),
            timestamp=item.get('timestamp'),
        )
        if item.get('sql_fingerprint'):
            record.sql_fingerprint = item['sql_fingerprint']
        records.append(record)
    return records


def save_snapshot(records: List[SlowQueryRecord], output_path: str, source: str = "") -> str:
    """保存快照到JSON文件"""
    snapshot = records_to_snapshot(records, source)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)


def load_snapshot(snapshot_path: str) -> List[SlowQueryRecord]:
    """从JSON文件加载快照"""
    path = Path(snapshot_path)
    if not path.exists():
        raise FileNotFoundError(f"快照文件不存在: {snapshot_path}")

    content = path.read_text(encoding='utf-8')
    snapshot = json.loads(content)

    version = snapshot.get('version', '')
    if not version:
        raise ValueError(f"无效的快照文件格式: {snapshot_path}")

    return snapshot_to_records(snapshot)


def is_snapshot_file(path: str) -> bool:
    """判断路径是否为JSON快照文件"""
    return Path(path).suffix.lower() == '.json'
