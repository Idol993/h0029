"""CLI 主入口：命令行参数解析与整体流程编排"""
import argparse
import sys
from pathlib import Path

from rich.console import Console

from .mysql_parser import MySQLSlowLogParser
from .postgres_fetcher import PostgresStatsFetcher
from .analyzer import QueryAnalyzer
from .comparator import QueryComparator
from .reporter import ReportGenerator

console = Console()


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="慢查询日志分析与优化建议工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 分析MySQL慢查询日志
  %(prog)s --db mysql --log /var/log/mysql/slow.log

  # 从PostgreSQL数据库获取pg_stat_statements数据
  %(prog)s --db postgres --host localhost --port 5432 --user postgres --passwd secret --dbname mydb

  # 分析并导出Markdown报告
  %(prog)s --db mysql --log slow.log --output report.md

  # 趋势对比：对比当前日志与基线日志
  %(prog)s --db mysql --log slow.log --baseline baseline_slow.log
        """
    )

    parser.add_argument(
        "--db", choices=["mysql", "postgres"], required=True,
        help="数据库类型: mysql 或 postgres"
    )

    parser.add_argument(
        "--log", type=str,
        help="MySQL慢查询日志文件路径（仅MySQL时使用）"
    )

    parser.add_argument("--host", type=str, default="localhost", help="数据库主机地址")
    parser.add_argument("--port", type=int, default=3306, help="数据库端口")
    parser.add_argument("--user", type=str, default="root", help="数据库用户名")
    parser.add_argument("--passwd", type=str, default="", help="数据库密码")
    parser.add_argument("--dbname", type=str, default="", help="数据库名")

    parser.add_argument(
        "--limit", type=int, default=200,
        help="PostgreSQL时从pg_stat_statements获取的最大记录数"
    )

    parser.add_argument(
        "--baseline", type=str, default=None,
        help="基线日志文件路径（MySQL）或基线导出JSON文件，用于趋势对比"
    )

    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="导出Markdown报告的文件路径"
    )

    parser.add_argument(
        "--top", type=int, default=20,
        help="显示Top N条慢查询（默认20）"
    )

    parser.add_argument(
        "--no-progress", action="store_true",
        help="关闭进度条显示"
    )

    return parser


def main():
    """主入口函数"""
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        records = None
        baseline_records = None
        show_progress = not args.no_progress

        if args.db == "mysql":
            if not args.log:
                console.print("[red]错误: MySQL模式需要指定 --log 参数[/red]")
                sys.exit(1)

            mysql_parser = MySQLSlowLogParser(show_progress=show_progress)
            records = mysql_parser.parse(args.log)

            if args.baseline:
                baseline_path = Path(args.baseline)
                if baseline_path.exists():
                    baseline_records = mysql_parser.parse(args.baseline)
                else:
                    console.print(f"[yellow]警告: 基线文件不存在: {args.baseline}[/yellow]")

        elif args.db == "postgres":
            if args.port == 3306:
                args.port = 5432

            pg_fetcher = PostgresStatsFetcher(
                host=args.host,
                port=args.port,
                user=args.user,
                password=args.passwd,
                database=args.dbname,
                limit=args.limit,
                show_progress=show_progress,
            )
            records = pg_fetcher.fetch()

        if not records:
            console.print("[yellow]未找到任何慢查询记录[/yellow]")
            return

        analyzer = QueryAnalyzer()
        result = analyzer.analyze(records)

        if args.top and len(result.records) > args.top:
            result.records = result.records[:args.top]
            result.total_queries = len(result.records)
            result.total_time = sum(r.total_time for r in result.records)

        reporter = ReportGenerator()
        reporter.print_terminal_report(result)

        if baseline_records:
            baseline_result = analyzer.analyze(baseline_records)
            comparator = QueryComparator()
            comp_result = comparator.compare(baseline_result.records, result.records)

            baseline_name = Path(args.baseline).name if args.baseline else "基线"
            current_name = Path(args.log).name if args.log else "当前"
            reporter.print_comparison_report(comp_result, baseline_name, current_name)

            if args.output:
                base, ext = Path(args.output).stem, Path(args.output).suffix
                comp_path = str(Path(args.output).with_name(f"{base}_comparison{ext}"))
                exported = reporter.export_comparison_markdown(comp_result, comp_path, baseline_name, current_name)
                console.print(f"[green]对比报告已导出: {exported}[/green]")

        if args.output:
            exported = reporter.export_markdown(result, args.output)
            console.print(f"[green]报告已导出: {exported}[/green]")

    except KeyboardInterrupt:
        console.print("\n[yellow]操作已取消[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]错误: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
