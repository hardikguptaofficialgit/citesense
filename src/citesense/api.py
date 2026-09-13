"""Thin package adapter around the existing marketplace orchestrator.

The marketplace scripts remain the single implementation of the audit engine.
This module only makes that entrypoint importable after installation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _engine_script_dirs() -> list[Path]:
    """Return the bundled skill-script directories, or the checkout locations."""
    try:
        from citesense._marketplace import audit_orchestrator

        root = Path(next(iter(audit_orchestrator.__path__)))
        return [
            root,
            root.parent / "crawl_render_audit",
            root.parent / "freshness_corroboration",
            root.parent / "engagement_audit",
            root.parent / "citation_simulator",
            root.parent / "trust_corroboration_graph",
        ]
    except (ImportError, StopIteration):
        repository = Path(__file__).resolve().parents[2]
        return [
            repository / "skills" / "audit-orchestrator" / "scripts",
            repository / "skills" / "crawl-render-audit" / "scripts",
            repository / "skills" / "freshness-corroboration" / "scripts",
            repository / "skills" / "engagement-audit" / "scripts",
            repository / "skills" / "citation-simulator" / "scripts",
            repository / "skills" / "trust-corroboration-graph" / "scripts",
        ]


def _load_orchestrator():
    for directory in reversed(_engine_script_dirs()):
        directory_string = str(directory)
        if directory.exists() and directory_string not in sys.path:
            sys.path.insert(0, directory_string)
    from run_audit import run_full_audit as orchestrate

    return orchestrate


def run_full_audit(
    site_url: str,
    max_pages: int = 5,
    timeout: int = 8,
    save_inventory_path: str | None = None,
    external_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the existing read-only CiteSense audit and return its report."""
    return _load_orchestrator()(
        site_url=site_url,
        max_pages=max_pages,
        timeout=timeout,
        save_inventory_path=save_inventory_path,
        external_evidence=external_evidence,
    )
