"""CLI 主入口：命令行参数解析与整体流程编排"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console

from .mysql_parser import MySQLSlowLogParser
from .mysql_fetcher import MySQLDirectFetcher
from .postgres_fetcher import PostgresStatsFetcher
from .analyzer import QueryAnalyzer
from .comparator import QueryComparator
from .reporter import ReportGenerator
from .snapshot import save_snapshot, load_snapshot, is_snapshot_file

console = Console()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="慢查询日志分析与优化建议工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 分析MySQL慢查询日志
  %(prog)s --db mysql --log /var/log/mysql/slow.log

  # MySQL直连分析（从performance_schema读取统计）
  %(prog)s --db mysql --host 10.0.1.100 --port 3306 --user root --passwd secret

  # PostgreSQL直连分析
  %(prog)s --db postgres --host localhost --port 5432 --user postgres --passwd secret --dbname mydb

  # 保存快照供下次对比
  %(prog)s --db mysql --log slow.log --save-snapshot baseline.json

  # 趋势对比（MySQL日志 vs 日志 / 快照 vs 快照）
  %(prog)s --db mysql --log slow.log --baseline baseline.json
  %(prog)s --db postgres --host db --user pg --passwd s --dbname mydb --baseline baseline.json
        """
    )

    parser.add_argument(
        "--db", choices=["mysql", "postgres"], required=True,
        help="数据库类型: mysql 或 postgres"
    )

    parser.add_argument(
        "--log", type=str, default=None,
        help="MySQL慢查询日志文件路径（与直连模式二选一）"
    )

    parser.add_argument("--host", type=str, default="localhost", help="数据库主机地址")
    parser.add_argument("--port", type=int, default=None, help="数据库端口（MySQL默认3306，PG默认5432）")
    parser.add_argument("--user", type=str, default="root", help="数据库用户名")
    parser.add_argument("--passwd", type=str, default="", help="数据库密码")
    parser.add_argument("--dbname", type=str, default="", help="数据库名")

    parser.add_argument(
        "--limit", type=int, default=200,
        help="从数据库获取的最大记录数（默认200）"
    )

    parser.add_argument(
        "--baseline", type=str, default=None,
        help="基线文件路径：支持MySQL慢日志(.log)或JSON快照(.json)"
    )

    parser.add_argument(
        "--save-snapshot", type=str, default=None, metavar="PATH",
        help="将当前结果保存为JSON快照文件，供后续 --baseline 对比"
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


def _get_default_port(db_type: str) -> int:
    return 3306 if db_type == "mysql" else 5432


def _resolve_port(args) -> int:
    if args.port is not None:
        return args.port
    return _get_default_port(args.db)


def _fetch_current_records(args, show_progress: bool):
    """根据参数获取当前慢查询记录"""
    port = _resolve_port(args)

    if args.db == "mysql":
        if args.log:
            parser = MySQLSlowLogParser(show_progress=show_progress)
            return parser.parse(args.log), "log"
        else:
            fetcher = MySQLDirectFetcher(
                host=args.host, port=port, user=args.user,
                password=args.passwd, database=args.dbname, limit=args.limit,
            )
            return fetcher.fetch(), "direct"

    elif args.db == "postgres":
        fetcher = PostgresStatsFetcher(
            host=args.host, port=port, user=args.user,
            password=args.passwd, database=args.dbname or "postgres",
            limit=args.limit, show_progress=show_progress,
        )
        return fetcher.fetch(), "direct"


def _load_baseline_records(args, show_progress: bool):
    """加载基线记录，支持日志文件和JSON快照"""
    if not args.baseline:
        return None

    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        console.print(f"[yellow]警告: 基线文件不存在: {args.baseline}[/yellow]")
        return None

    if is_snapshot_file(args.baseline):
        try:
            return load_snapshot(args.baseline)
        except (ValueError, json_error()) as e:
            console.print(f"[red]快照文件加载失败: {e}[/red]")
            return None
    else:
        if args.db == "mysql":
            parser = MySQLSlowLogParser(show_progress=show_progress)
            return parser.parse(args.baseline)
        else:
            console.print(
                "[yellow]PostgreSQL模式不支持直接解析慢日志文件作为基线，"
                "请使用 --save-snapshot 保存的JSON快照[/yellow]"
            )
            return None


def json_error():
    import json
    return json.JSONDecodeError


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        show_progress = not args.no_progress

        if args.db == "mysql" and not args.log and not args.host:
            console.print("[red]MySQL模式需要指定 --log（日志文件）或提供 --host（直连模式）[/red]")
            sys.exit(1)

        records, source_type = _fetch_current_records(args, show_progress)

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

        source_label = f"{args.db} ({'日志' if source_type == 'log' else '直连'})"

        if args.save_snapshot:
            snap_path = save_snapshot(
                result.records, args.save_snapshot,
                source=source_label
            )
            console.print(f"[green]快照已保存: {snap_path}[/green]")

        baseline_records = _load_baseline_records(args, show_progress)

        if baseline_records:
            baseline_result = analyzer.analyze(baseline_records)
            comparator = QueryComparator()
            comp_result = comparator.compare(baseline_result.records, result.records)

            if is_snapshot_file(args.baseline):
                import json
                snap_data = json.loads(Path(args.baseline).read_text(encoding='utf-8'))
                baseline_name = f"快照({snap_data.get('created_at', 'unknown')[:19]})"
            else:
                baseline_name = Path(args.baseline).name

            current_name = Path(args.log).name if args.log else f"{args.db}直连"
            reporter.print_comparison_report(comp_result, baseline_name, current_name)

            if args.output:
                base_stem, ext = Path(args.output).stem, Path(args.output).suffix
                comp_path = str(Path(args.output).with_name(f"{base_stem}_comparison{ext}"))
                exported = reporter.export_comparison_markdown(
                    comp_result, comp_path, baseline_name, current_name
                )
                console.print(f"[green]对比报告已导出: {exported}[/green]")

        if args.output:
            exported = reporter.export_markdown(result, args.output)
            console.print(f"[green]报告已导出: {exported}[/green]")

    except KeyboardInterrupt:
        console.print("\n[yellow]操作已取消[/yellow]")
        sys.exit(130)
    except (ConnectionError, PermissionError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    except ImportError as e:
        console.print(f"[red]缺少依赖: {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]错误: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
