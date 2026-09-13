"""Console entrypoint for the CiteSense marketplace orchestrator."""

from .api import _load_orchestrator


def main() -> None:
    """Preserve the marketplace CLI, including all existing options."""
    _load_orchestrator()
    from run_audit import main as orchestrator_main

    orchestrator_main()
