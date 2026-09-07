#!/usr/bin/env python3
"""
report_io.py -- Shared file I/O for the report-consuming CLIs.

Keeps failure modes friendly and consistent: a malformed or missing report.json produces a
one-line diagnostic naming the file, not a raw JSON traceback, and writing an output file
creates its parent directory instead of failing on a path that does not exist yet.

Imports nothing else in the repo, so it is safe for every module to depend on.
"""
import json
import os
import sys
from typing import Any, Dict


class ReportIOError(Exception):
    """A user-facing I/O or parse problem, already phrased as a readable message."""


def load_report(path: str, label: str = "report") -> Dict[str, Any]:
    """Loads a JSON report, converting the usual failures into readable messages."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ReportIOError("{0} not found: {1}".format(label, path))
    except IsADirectoryError:
        raise ReportIOError("{0} is a directory, not a file: {1}".format(label, path))
    except PermissionError:
        raise ReportIOError("{0} is not readable: {1}".format(label, path))
    except json.JSONDecodeError as exc:
        raise ReportIOError(
            "{0} is not valid JSON: {1} (line {2}, column {3}: {4})".format(
                label, path, exc.lineno, exc.colno, exc.msg
            )
        )
    except UnicodeDecodeError:
        raise ReportIOError("{0} is not UTF-8 text: {1}".format(label, path))

    if not isinstance(data, dict):
        raise ReportIOError(
            "{0} must be a JSON object matching report-schema.json, got {1}: {2}".format(
                label, type(data).__name__, path
            )
        )
    return data


def write_text(path: str, text: str) -> None:
    """Writes text to path, creating the parent directory if it does not exist yet."""
    parent = os.path.dirname(os.path.abspath(path))
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        raise ReportIOError("could not write {0}: {1}".format(path, exc))


def fail(exc: Exception) -> int:
    """Prints a readable one-line error to stderr and returns a non-zero exit code."""
    sys.stderr.write("error: {0}\n".format(exc))
    return 1
