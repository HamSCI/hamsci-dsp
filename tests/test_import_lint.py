"""Import lint: hamsci-dsp must never import hf_timestd (split §5.2).

The library is the base of the dependency graph; a single upward import
re-creates the circular coupling the split exists to remove.  Scans
source text (not sys.modules) so even lazy/function-level imports are
caught.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "hamsci_dsp"

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+hf_timestd", re.M)


def test_no_module_imports_hf_timestd():
    offenders = []
    for py in sorted(SRC.rglob("*.py")):
        text = py.read_text()
        for m in _IMPORT_RE.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            offenders.append(f"{py.relative_to(SRC)}:{line_no}")
    assert not offenders, (
        "hamsci_dsp must never import hf_timestd; found: " + ", ".join(offenders))


def test_the_scanner_actually_scans():
    # Guard the guard: the tree is non-trivial and the regex matches the
    # forbidden pattern when present.
    assert len(list(SRC.rglob("*.py"))) > 20
    assert _IMPORT_RE.search("from hf_timestd.core import x")
    assert _IMPORT_RE.search("    import hf_timestd")
    assert not _IMPORT_RE.search("# from hf_timestd import nothing")
