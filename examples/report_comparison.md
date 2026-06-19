# 慢查询对比报告

**生成时间**: 2026-06-19 11:30:08
**对比**: mysql_slow_baseline.log → mysql_slow.log

## 对比概览

| 类别 | 数量 |
|------|------|
| 新增 | 3 |
| 消失 | 1 |
| 恶化 | 3 |
| 改善 | 1 |
| 无显著变化 | 0 |

## 新增慢查询

| SQL | 执行次数 | 平均耗时(s) | 总耗时(s) |
|-----|----------|-------------|-----------|
| `SELECT o.id, o.total, u.name, u.email FROM orders o LEFT JOIN users u ON o.user_id = u.id WHERE o.cr...` | 1 | 12.5000 | 12.50 |
| `SELECT id, name FROM users WHERE id IN (SELECT user_id FROM orders WHERE total > 10000);` | 1 | 3.4568 | 3.46 |
| `SELECT * FROM products ORDER BY RAND() LIMIT 50;` | 1 | 0.5000 | 0.50 |

## 已消失慢查询

| SQL | 执行次数 | 平均耗时(s) | 总耗时(s) |
|-----|----------|-------------|-----------|
| `SELECT * FROM logs WHERE level = 'ERROR' AND DATE(created_at) = '2026-06-17';` | 1 | 8.5000 | 8.50 |
