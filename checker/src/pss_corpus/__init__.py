"""pss-corpus: the checker for the executable tier of the PSS corpus.

See ``COMPLIANCE-DESIGN.md`` at the repository root. Verdicts depend only on the
standard library and an SMT solver -- never on pssparser, pssc or dv-solve (G4).
"""

from .check import ERROR, FAIL, PASS, UNLOCATED, UNSUPPORTED, Verdict, check_run
from .model import SEED_BASE, Test, default_root, discover, load
from .runner import run_test
from .trace import Record, extract

__version__ = "0.1.0"

from .bundle import (MISSING, STALE, BundleError, Selection,  # noqa: E402 (needs __version__)
                     export, import_results, select)
from .report import Report, load_report, render_markdown, write_report  # noqa: E402
from .html_report import render_html  # noqa: E402

__all__ = [
    "PASS", "FAIL", "ERROR", "UNSUPPORTED", "UNLOCATED", "STALE", "MISSING",
    "Verdict", "check_run", "Selection", "select", "export", "import_results",
    "write_report", "BundleError", "Report", "load_report", "render_markdown",
    "render_html",
    "SEED_BASE", "Test", "default_root", "discover", "load",
    "run_test", "Record", "extract",
]
