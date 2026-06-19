"""报告输出模块：rich终端彩色表格 + Markdown导出"""
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from .models import AnalysisResult, ComparisonResult, SlowQueryRecord
from .analyzer import QueryAnalyzer


class ReportGenerator:
    """报告生成器"""

    MAX_SQL_DISPLAY_LEN = 100

    def __init__(self):
        self.console = Console()

    def print_terminal_report(self, result: AnalysisResult, title: str = "慢查询分析报告"):
        """在终端打印rich彩色报告"""
        self._print_summary(result, title)
        self._print_query_table(result)
        self._print_details(result)

    def print_comparison_report(self, comp_result: ComparisonResult,
                                 baseline_name: str = "基线",
                                 current_name: str = "当前"):
        """在终端打印对比报告"""
        self._print_comparison_summary(comp_result, baseline_name, current_name)

        if comp_result.added:
            self._print_simple_query_table(
                comp_result.added,
                f"[green]新增慢查询 ({len(comp_result.added)})[/green]",
                border_style="green"
            )

        if comp_result.removed:
            self._print_simple_query_table(
                comp_result.removed,
                f"[red]已消失慢查询 ({len(comp_result.removed)})[/red]",
                border_style="red"
            )

        if comp_result.worsened:
            self._print_change_table(
                comp_result.worsened,
                f"[yellow]性能恶化 ({len(comp_result.worsened)})[/yellow]",
                border_style="yellow",
                show_ratio=True
            )

        if comp_result.improved:
            self._print_change_table(
                comp_result.improved,
                f"[cyan]性能改善 ({len(comp_result.improved)})[/cyan]",
                border_style="cyan",
                show_ratio=True
            )

    def export_markdown(self, result: AnalysisResult, output_path: str,
                        title: str = "慢查询分析报告") -> str:
        """导出Markdown格式报告"""
        lines = []
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        lines.append("## 概览")
        lines.append("")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 慢查询总数 | {result.total_queries} |")
        lines.append(f"| 总耗时(秒) | {result.total_time:.2f} |")
        lines.append(f"| 严重级别 | {result.high_severity_count} |")
        lines.append(f"| 中等级别 | {result.medium_severity_count} |")
        lines.append(f"| 轻微级别 | {result.low_severity_count} |")
        lines.append("")

        lines.append("## Top 慢查询")
        lines.append("")
        lines.append("| 排名 | 严重级别 | 分数 | 执行次数 | 平均耗时(s) | 总耗时(s) | 扫描行数 | 返回行数 | SQL |")
        lines.append("|------|----------|------|----------|-------------|-----------|----------|----------|-----|")

        for idx, rec in enumerate(result.records[:50], 1):
            level, _ = QueryAnalyzer.get_severity_level(rec.severity_score)
            short_sql = self._truncate_sql(rec.sql)
            safe_sql = short_sql.replace('|', '\\|').replace('\n', ' ')
            lines.append(
                f"| {idx} | {level} | {rec.severity_score:.0f} | {rec.exec_count} | "
                f"{rec.avg_time:.4f} | {rec.total_time:.2f} | {rec.rows_examined:,} | "
                f"{rec.rows_sent:,} | `{safe_sql}` |"
            )
        lines.append("")

        lines.append("## 详细分析")
        lines.append("")
        for idx, rec in enumerate(result.records[:50], 1):
            lines.append(f"### #{idx}")
            lines.append("")
            lines.append("```sql")
            lines.append(QueryAnalyzer.format_sql(rec.sql))
            lines.append("```")
            lines.append("")
            lines.append(f"- **严重分数**: {rec.severity_score:.0f}")
            lines.append(f"- **执行次数**: {rec.exec_count}")
            lines.append(f"- **平均耗时**: {rec.avg_time:.4f}s")
            lines.append(f"- **总耗时**: {rec.total_time:.2f}s")
            lines.append(f"- **扫描行数**: {rec.rows_examined:,}")
            lines.append(f"- **返回行数**: {rec.rows_sent:,}")
            if rec.database:
                lines.append(f"- **数据库**: {rec.database}")
            if rec.patterns:
                lines.append(f"- **匹配模式**: {', '.join(rec.patterns)}")
            if rec.suggestions:
                lines.append("- **优化建议**:")
                for s in rec.suggestions:
                    lines.append(f"  - {s}")
            lines.append("")

        output = '\n'.join(lines)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding='utf-8')
        return str(path)

    def export_comparison_markdown(self, comp_result: ComparisonResult, output_path: str,
                                    baseline_name: str = "基线",
                                    current_name: str = "当前") -> str:
        """导出对比Markdown报告"""
        lines = []
        lines.append(f"# 慢查询对比报告")
        lines.append("")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**对比**: {baseline_name} → {current_name}")
        lines.append("")

        lines.append("## 对比概览")
        lines.append("")
        lines.append("| 类别 | 数量 |")
        lines.append("|------|------|")
        lines.append(f"| 新增 | {len(comp_result.added)} |")
        lines.append(f"| 消失 | {len(comp_result.removed)} |")
        lines.append(f"| 恶化 | {len(comp_result.worsened)} |")
        lines.append(f"| 改善 | {len(comp_result.improved)} |")
        lines.append(f"| 无显著变化 | {len(comp_result.unchanged)} |")
        lines.append("")

        if comp_result.added:
            lines.append("## 新增慢查询")
            lines.append("")
            lines.append("| SQL | 执行次数 | 平均耗时(s) | 总耗时(s) |")
            lines.append("|-----|----------|-------------|-----------|")
            for rec in comp_result.added:
                short_sql = self._truncate_sql(rec.sql).replace('|', '\\|').replace('\n', ' ')
                lines.append(f"| `{short_sql}` | {rec.exec_count} | {rec.avg_time:.4f} | {rec.total_time:.2f} |")
            lines.append("")

        if comp_result.removed:
            lines.append("## 已消失慢查询")
            lines.append("")
            lines.append("| SQL | 执行次数 | 平均耗时(s) | 总耗时(s) |")
            lines.append("|-----|----------|-------------|-----------|")
            for rec in comp_result.removed:
                short_sql = self._truncate_sql(rec.sql).replace('|', '\\|').replace('\n', ' ')
                lines.append(f"| `{short_sql}` | {rec.exec_count} | {rec.avg_time:.4f} | {rec.total_time:.2f} |")
            lines.append("")

        output = '\n'.join(lines)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding='utf-8')
        return str(path)

    def _print_summary(self, result: AnalysisResult, title: str):
        """打印概览面板"""
        summary_text = Text()
        summary_text.append(f"慢查询总数: ", style="bold")
        summary_text.append(f"{result.total_queries}", style="cyan")
        summary_text.append("    ")
        summary_text.append(f"总耗时: ", style="bold")
        summary_text.append(f"{result.total_time:.2f}s", style="cyan")
        summary_text.append("\n")
        summary_text.append(f"严重: ", style="bold")
        summary_text.append(f"{result.high_severity_count}", style="red")
        summary_text.append("    ")
        summary_text.append(f"中等: ", style="bold")
        summary_text.append(f"{result.medium_severity_count}", style="yellow")
        summary_text.append("    ")
        summary_text.append(f"轻微: ", style="bold")
        summary_text.append(f"{result.low_severity_count}", style="green")

        self.console.print(Panel(summary_text, title=f"[bold]{title}[/bold]", border_style="blue"))

    def _print_comparison_summary(self, comp_result: ComparisonResult,
                                   baseline_name: str, current_name: str):
        """打印对比概览"""
        summary_text = Text()
        summary_text.append(f"对比: ", style="bold")
        summary_text.append(f"{baseline_name}", style="cyan")
        summary_text.append(" → ", style="dim")
        summary_text.append(f"{current_name}", style="cyan")
        summary_text.append("\n\n")
        summary_text.append(f"新增: ", style="bold")
        summary_text.append(f"{len(comp_result.added)}", style="green")
        summary_text.append("    ")
        summary_text.append(f"消失: ", style="bold")
        summary_text.append(f"{len(comp_result.removed)}", style="red")
        summary_text.append("    ")
        summary_text.append(f"恶化: ", style="bold")
        summary_text.append(f"{len(comp_result.worsened)}", style="yellow")
        summary_text.append("    ")
        summary_text.append(f"改善: ", style="bold")
        summary_text.append(f"{len(comp_result.improved)}", style="cyan")
        summary_text.append("    ")
        summary_text.append(f"无变化: ", style="bold")
        summary_text.append(f"{len(comp_result.unchanged)}", style="dim")

        self.console.print(Panel(summary_text, title="[bold]慢查询趋势对比[/bold]", border_style="magenta"))

    def _print_query_table(self, result: AnalysisResult):
        """打印查询详情表格"""
        if not result.records:
            self.console.print("[yellow]没有找到慢查询记录[/yellow]")
            return

        table = Table(
            title="[bold]Top 慢查询 (按严重分数排序)[/bold]",
            box=box.ROUNDED,
            border_style="blue",
            show_lines=False,
        )

        table.add_column("#", justify="right", style="dim", width=4)
        table.add_column("级别", width=6)
        table.add_column("分数", justify="right", width=8)
        table.add_column("次数", justify="right", width=6)
        table.add_column("平均耗时(s)", justify="right", width=10)
        table.add_column("总耗时(s)", justify="right", width=10)
        table.add_column("扫描行数", justify="right", width=10)
        table.add_column("返回行数", justify="right", width=10)
        table.add_column("SQL", overflow="fold")

        for idx, rec in enumerate(result.records[:20], 1):
            level, color = QueryAnalyzer.get_severity_level(rec.severity_score)
            short_sql = self._truncate_sql(rec.sql)
            table.add_row(
                str(idx),
                f"[{color}]{level}[/{color}]",
                f"{rec.severity_score:.0f}",
                str(rec.exec_count),
                f"{rec.avg_time:.4f}",
                f"{rec.total_time:.2f}",
                f"{rec.rows_examined:,}",
                f"{rec.rows_sent:,}",
                short_sql,
            )

        self.console.print(table)

    def _print_simple_query_table(self, records, title: str, border_style: str = "blue"):
        """打印简单的查询表格"""
        table = Table(title=title, box=box.ROUNDED, border_style=border_style)
        table.add_column("#", justify="right", style="dim", width=4)
        table.add_column("次数", justify="right", width=6)
        table.add_column("平均耗时(s)", justify="right", width=10)
        table.add_column("总耗时(s)", justify="right", width=10)
        table.add_column("SQL", overflow="fold")

        for idx, rec in enumerate(records[:10], 1):
            short_sql = self._truncate_sql(rec.sql)
            table.add_row(
                str(idx),
                str(rec.exec_count),
                f"{rec.avg_time:.4f}",
                f"{rec.total_time:.2f}",
                short_sql,
            )
        self.console.print(table)

    def _print_change_table(self, pairs, title: str, border_style: str, show_ratio: bool = True):
        """打印变化对比表格"""
        table = Table(title=title, box=box.ROUNDED, border_style=border_style)
        table.add_column("#", justify="right", style="dim", width=4)
        if show_ratio:
            table.add_column("变化比", justify="right", width=8)
        table.add_column("基线耗时(s)", justify="right", width=10)
        table.add_column("当前耗时(s)", justify="right", width=10)
        table.add_column("SQL", overflow="fold")

        for idx, (base, curr, ratio) in enumerate(pairs[:10], 1):
            short_sql = self._truncate_sql(curr.sql)
            if show_ratio:
                table.add_row(
                    str(idx),
                    f"{ratio:.2f}x",
                    f"{base.total_time:.2f}",
                    f"{curr.total_time:.2f}",
                    short_sql,
                )
            else:
                table.add_row(
                    str(idx),
                    f"{base.total_time:.2f}",
                    f"{curr.total_time:.2f}",
                    short_sql,
                )
        self.console.print(table)

    def _print_details(self, result: AnalysisResult):
        """打印每条记录的详细信息"""
        self.console.print()
        self.console.print("[bold underline]详细分析与优化建议[/bold underline]")
        self.console.print()

        for idx, rec in enumerate(result.records[:10], 1):
            level, color = QueryAnalyzer.get_severity_level(rec.severity_score)

            header = Text()
            header.append(f"#{idx} ", style=f"bold {color}")
            header.append(f"[{level}] ", style=f"bold {color}")
            header.append(f"得分: {rec.severity_score:.0f}", style="dim")

            details = [header]

            info_line = Text()
            info_line.append(f"执行次数: ", style="bold")
            info_line.append(f"{rec.exec_count}", style="cyan")
            info_line.append("  ")
            info_line.append(f"平均耗时: ", style="bold")
            info_line.append(f"{rec.avg_time:.4f}s", style="cyan")
            info_line.append("  ")
            info_line.append(f"总耗时: ", style="bold")
            info_line.append(f"{rec.total_time:.2f}s", style="cyan")
            info_line.append("  ")
            info_line.append(f"扫描: ", style="bold")
            info_line.append(f"{rec.rows_examined:,}", style="cyan")
            info_line.append("  ")
            info_line.append(f"返回: ", style="bold")
            info_line.append(f"{rec.rows_sent:,}", style="cyan")
            details.append(info_line)

            formatted_sql = QueryAnalyzer.format_sql(rec.sql)
            details.append(Text(formatted_sql, style="#d0d0d0"))

            if rec.patterns:
                patterns_line = Text()
                patterns_line.append("匹配模式: ", style="bold yellow")
                patterns_line.append(", ".join(rec.patterns), style="yellow")
                details.append(patterns_line)

            if rec.suggestions:
                for i, s in enumerate(rec.suggestions, 1):
                    sug_line = Text()
                    sug_line.append(f"  💡 建议{i}: ", style="bold green")
                    sug_line.append(s, style="green")
                    details.append(sug_line)

            self.console.print(Panel(Group(*details), border_style=color))

    def _truncate_sql(self, sql: str, max_len: Optional[int] = None) -> str:
        """截断SQL显示长度"""
        if max_len is None:
            max_len = self.MAX_SQL_DISPLAY_LEN
        sql_single_line = ' '.join(sql.split())
        if len(sql_single_line) > max_len:
            return sql_single_line[:max_len] + "..."
        return sql_single_line
