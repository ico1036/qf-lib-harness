"""Stub module that satisfies `from weasyprint import HTML, CSS` without
loading cairo/pango/glib system libs.

When real PDF rendering is needed, install brew cairo/pango/glib (without
forcing openssl@3 rebuild) and remove this stub.

Importing this module replaces sys.modules['weasyprint'] with a dummy.
Must be imported BEFORE any qf-lib import.
"""
import sys
import types


def _install() -> None:
    if "weasyprint" in sys.modules and not isinstance(sys.modules["weasyprint"], types.ModuleType):
        return

    mod = types.ModuleType("weasyprint")

    class _StubHTML:
        def __init__(self, string: str = "", **kwargs) -> None:
            self._html = string

        def write_pdf(self, target=None, *args, **kwargs):
            # Write a minimal valid empty-ish PDF so file IO doesn't break.
            blob = (
                b"%PDF-1.4\n"
                b"% Tearsheet PDF stubbed: WeasyPrint system libs not installed.\n"
                b"% Stats are still available in CSV/Excel and via portfolio_eod_series().\n"
            )
            if target is None:
                return blob
            if hasattr(target, "write"):
                target.write(blob)
                return None
            with open(target, "wb") as fh:
                fh.write(blob)
            return None

    class _StubCSS:
        def __init__(self, *args, **kwargs) -> None:
            pass

    mod.HTML = _StubHTML
    mod.CSS = _StubCSS
    mod.__version__ = "stub"
    sys.modules["weasyprint"] = mod


_install()
