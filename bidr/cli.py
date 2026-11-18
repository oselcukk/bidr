"""`bidr` komut satırı. Sahibi: şef. Her alt paket kendi `cli.py`'sinde
`register(subparsers)` tanımlar; burada yalnız listeye eklenir."""
from __future__ import annotations

import argparse
import importlib
import sys

SUBCOMMAND_MODULES = [
    "bidr.criteria.cli",
    "bidr.ingest.cli",
    "bidr.labels.cli",
    "bidr.identify.cli",
    "bidr.candidates.cli",
    "bidr.evaluate.cli",
    "bidr.llm.cli",
    "bidr.decide.cli",
    "bidr.init.cli",
    "bidr.pipeline.cli",
    "bidr.audit.cli",
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bidr", description="BİDR kanıt hattı")
    sub = p.add_subparsers(dest="command", required=True)
    for name in SUBCOMMAND_MODULES:
        mod = importlib.import_module(name)
        register = getattr(mod, "register", None)
        if register is not None:
            register(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
