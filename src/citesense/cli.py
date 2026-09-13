"""Agent-friendly console interface for the CiteSense audit engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from .api import run_full_audit


def _valid_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not any(
        character.isspace() for character in value
    )


def _read_external_evidence(path: str | None) -> dict | None:
    if not path:
        return None
    with open(path, encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("external evidence must be a JSON object")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _add_audit_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("url", help="Public http(s) URL to audit")
    parser.add_argument("-o", "--output", help="Write the final JSON report to this path")
    parser.add_argument("--max-pages", type=int, default=5, help="Maximum pages to sample (default: 5)")
    parser.add_argument("--timeout", type=int, default=8, help="Per-request timeout in seconds (default: 8)")
    parser.add_argument("--save-inventory", help="Optional path for the raw crawl inventory")
    parser.add_argument(
        "--external-evidence",
        help="Optional agent-supplied external evidence JSON; no external search is performed",
    )


def _run_audit(args: argparse.Namespace) -> int:
    if not _valid_url(args.url):
        print("error: URL must be an absolute http(s) URL", file=sys.stderr)
        return 2
    if args.max_pages < 1 or args.timeout < 1:
        print("error: --max-pages and --timeout must be positive", file=sys.stderr)
        return 2
    try:
        report = run_full_audit(
            args.url,
            max_pages=args.max_pages,
            timeout=args.timeout,
            save_inventory_path=args.save_inventory,
            external_evidence=_read_external_evidence(args.external_evidence),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: audit failed: {exc}", file=sys.stderr)
        return 1

    if args.output:
        _write_json(Path(args.output), report)
        print(json.dumps({
            "status": "completed",
            "output": str(Path(args.output)),
            "site": report.get("site"),
            "summary": report.get("summary", {}),
        }))
    else:
        print(json.dumps(report, indent=2))
    return 0


def _report_filename(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "site").replace(".", "_")
    if parsed.path not in {"", "/"} or parsed.query:
        suffix = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        return f"{host}-{suffix}.json"
    return f"{host}.json"


def _run_batch(args: argparse.Namespace) -> int:
    input_path = Path(args.file)
    if not input_path.is_file():
        print(f"error: batch input file not found: {input_path}", file=sys.stderr)
        return 2
    if args.max_pages < 1 or args.timeout < 1:
        print("error: --max-pages and --timeout must be positive", file=sys.stderr)
        return 2

    urls = []
    seen = set()
    try:
        lines = input_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        print(f"error: cannot read batch input: {exc}", file=sys.stderr)
        return 2
    for line in lines:
        url = line.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    if not urls:
        print("error: batch input contains no URLs", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    results = []
    try:
        evidence = _read_external_evidence(args.external_evidence)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for url in urls:
        if not _valid_url(url):
            results.append({"url": url, "status": "failed", "error": "invalid http(s) URL"})
            continue
        output_path = output_dir / _report_filename(url)
        try:
            report = run_full_audit(
                url,
                max_pages=args.max_pages,
                timeout=args.timeout,
                external_evidence=evidence,
            )
            _write_json(output_path, report)
            results.append({
                "url": url,
                "status": "completed",
                "output": str(output_path),
                "summary": report.get("summary", {}),
            })
        except Exception as exc:
            results.append({"url": url, "status": "failed", "error": str(exc)})

    completed = sum(item["status"] == "completed" for item in results)
    failed = len(results) - completed
    summary = {
        "status": "completed" if failed == 0 else "partial" if completed else "failed",
        "input": str(input_path),
        "output_dir": str(output_dir),
        "requested": len(urls),
        "completed": completed,
        "failed": failed,
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    return 0 if failed == 0 else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="citesense",
        description="CiteSense website AI-readiness auditor. Read-only and robots.txt-respecting.",
    )
    subparsers = parser.add_subparsers(dest="command")

    audit = subparsers.add_parser(
        "audit",
        help="Audit one public website and produce a structured JSON report",
        description=(
            "Audit one public http(s) URL for AI discoverability and on-site engagement. "
            "Read-only; robots.txt and access restrictions are respected."
        ),
    )
    _add_audit_arguments(audit)
    audit.set_defaults(handler=_run_audit)

    batch = subparsers.add_parser(
        "batch",
        help="Audit one URL per line and write one JSON report per website",
        description=(
            "Audit a URL list independently; blank lines and exact duplicates are ignored. "
            "Read-only; robots.txt and access restrictions are respected."
        ),
    )
    batch.add_argument("file", help="Text file containing one public http(s) URL per line")
    batch.add_argument("--output-dir", default="reports", help="Directory for reports (default: reports)")
    batch.add_argument("--max-pages", type=int, default=5, help="Maximum pages per site (default: 5)")
    batch.add_argument("--timeout", type=int, default=8, help="Per-request timeout in seconds (default: 8)")
    batch.add_argument(
        "--external-evidence",
        help="Optional agent-supplied external evidence JSON applied to each site",
    )
    batch.set_defaults(handler=_run_batch)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the agent-friendly CLI while preserving the legacy URL-first form."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] not in {"audit", "batch", "-h", "--help"}:
        arguments.insert(0, "audit")
    parser = _parser()
    args = parser.parse_args(arguments)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 0
    return args.handler(args)
