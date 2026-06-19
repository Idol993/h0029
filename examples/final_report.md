# 慢查询分析报告

**生成时间**: 2026-06-19 11:51:30

## 概览

| 指标 | 值 |
|------|-----|
| 慢查询总数 | 6 |
| 总耗时(秒) | 28.89 |
| 严重级别 | 4 |
| 中等级别 | 1 |
| 轻微级别 | 1 |

## Top 慢查询

| 排名 | 严重级别 | 分数 | 执行次数 | 平均耗时(s) | 总耗时(s) | 扫描行数 | 返回行数 | SQL |
|------|----------|------|----------|-------------|-----------|----------|----------|-----|
| 1 | 严重 | 312500000 | 1 | 12.5000 | 12.50 | 25,000,000 | 1,000 | `SELECT o.id, o.total, u.name, u.email FROM orders o LEFT JOIN users u ON o.user_id = u.id WHERE o.cr...` |
| 2 | 严重 | 44493820 | 1 | 5.2346 | 5.23 | 8,500,000 | 1 | `SELECT COUNT(*) FROM users WHERE email LIKE '%@example.com';` |
| 3 | 严重 | 18157222 | 3 | 1.9877 | 5.96 | 3,045,000 | 125 | `SELECT * FROM orders WHERE user_id = 12345 AND status = 'pending' ORDER BY created_at DESC;` |
| 4 | 严重 | 6913578 | 1 | 3.4568 | 3.46 | 2,000,000 | 10 | `SELECT id, name FROM users WHERE id IN (SELECT user_id FROM orders WHERE total > 10000);` |
| 5 | 中等 | 123400 | 1 | 1.2340 | 1.23 | 100,000 | 100 | `SELECT DISTINCT category FROM products WHERE YEAR(created_at) = 2026 OR status = 1;` |
| 6 | 轻微 | 25000 | 1 | 0.5000 | 0.50 | 50,000 | 50 | `SELECT * FROM products ORDER BY RAND() LIMIT 50;` |

## 详细分析

### #1

```sql
SELECT o.id,
       o.total,
       u.name,
       u.email
FROM orders o
LEFT JOIN users u ON o.user_id = u.id
WHERE o.created_at > '2026-01-01'
GROUP BY o.id
ORDER BY o.total DESC;
```

- **严重分数**: 312500000
- **执行次数**: 1
- **平均耗时**: 12.5000s
- **总耗时**: 12.50s
- **扫描行数**: 25,000,000
- **返回行数**: 1,000
- **数据库**: production_db
- **匹配模式**: 全表扫描(大表), 缺索引JOIN, LIMIT缺失, GROUP BY非索引字段
- **优化建议**:
  - 可能存在全表扫描，检查WHERE条件字段是否有合适索引
  - 多表JOIN可能缺少索引，检查JOIN ON字段是否有索引
  - 查询可能返回大量数据，考虑添加LIMIT限制结果集大小
  - GROUP BY字段建议建立索引以避免临时表和filesort

### #2

```sql
SELECT COUNT(*)
FROM users
WHERE email LIKE '%@example.com';
```

- **严重分数**: 44493820
- **执行次数**: 1
- **平均耗时**: 5.2346s
- **总耗时**: 5.23s
- **扫描行数**: 8,500,000
- **返回行数**: 1
- **匹配模式**: 全表扫描(大表), LIKE前导通配符
- **优化建议**:
  - 可能存在全表扫描，检查WHERE条件字段是否有合适索引
  - LIKE前导通配符(%xxx)会导致全表扫描，考虑使用全文索引或反转字段

### #3

```sql
SELECT *
FROM orders
WHERE user_id = 12345
  AND status = 'pending'
ORDER BY created_at DESC;
```

- **严重分数**: 18157222
- **执行次数**: 3
- **平均耗时**: 1.9877s
- **总耗时**: 5.96s
- **扫描行数**: 3,045,000
- **返回行数**: 125
- **数据库**: production_db
- **匹配模式**: SELECT *, 全表扫描(大表), 隐式类型转换, LIMIT缺失
- **优化建议**:
  - 避免使用 SELECT *，只查询需要的字段以减少数据传输和内存占用
  - 可能存在全表扫描，检查WHERE条件字段是否有合适索引
  - 检查是否存在隐式类型转换，确保比较两侧数据类型一致
  - 查询可能返回大量数据，考虑添加LIMIT限制结果集大小

### #4

```sql
SELECT id,
       name
FROM users
WHERE id IN
    (SELECT user_id
     FROM orders
     WHERE total > 10000);
```

- **严重分数**: 6913578
- **执行次数**: 1
- **平均耗时**: 3.4568s
- **总耗时**: 3.46s
- **扫描行数**: 2,000,000
- **返回行数**: 10
- **匹配模式**: 全表扫描(大表), 子查询
- **优化建议**:
  - 可能存在全表扫描，检查WHERE条件字段是否有合适索引
  - 子查询可能性能较差，考虑改写为JOIN连接查询

### #5

```sql
SELECT DISTINCT category
FROM products
WHERE YEAR(created_at) = 2026
  OR status = 1;
```

- **严重分数**: 123400
- **执行次数**: 1
- **平均耗时**: 1.2340s
- **总耗时**: 1.23s
- **扫描行数**: 100,000
- **返回行数**: 100
- **匹配模式**: 全表扫描(大表), WHERE字段函数运算, LIMIT缺失, DISTINCT使用, OR条件
- **优化建议**:
  - 可能存在全表扫描，检查WHERE条件字段是否有合适索引
  - 避免在WHERE条件中对字段使用函数，这会使索引失效
  - 查询可能返回大量数据，考虑添加LIMIT限制结果集大小
  - DISTINCT可能导致去重开销大，考虑是否可用GROUP BY或EXISTS替代
  - 多个OR条件可能影响索引使用，考虑改写为UNION或建立合适的复合索引

### #6

```sql
SELECT *
FROM products
ORDER BY RAND()
LIMIT 50;
```

- **严重分数**: 25000
- **执行次数**: 1
- **平均耗时**: 0.5000s
- **总耗时**: 0.50s
- **扫描行数**: 50,000
- **返回行数**: 50
- **匹配模式**: SELECT *, 全表扫描(大表)
- **优化建议**:
  - 避免使用 SELECT *，只查询需要的字段以减少数据传输和内存占用
  - 可能存在全表扫描，检查WHERE条件字段是否有合适索引
