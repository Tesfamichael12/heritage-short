"""Command entry point:  python -m pipeline <command>

The Makefile calls these. Stages are imported only when needed, so a command
such as `validate` works even when a provider library is missing.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check storyboard.json against the schema")
    p.add_argument("path", nargs="?")

    sub.add_parser("secrets", help="scan the files git would commit for secrets")
    sub.add_parser("smoke", help="call each provider once and log its latency")
    sub.add_parser("draft", help="draft storyboard.draft.json from story/brief.md")
    sub.add_parser("radio", help="narration over placeholder music on a black screen")
    sub.add_parser("status", help="what is current, stale or missing, and today's call counts")
    sub.add_parser("costs", help="rebuild the tables in COSTS.md from runs.jsonl")

    p = sub.add_parser("film", help="run the whole pipeline")
    p.add_argument("--only", help="comma-separated stages, for example keyframes,narration")
    p.add_argument("--force", help="regenerate one output, for example keyframes:s04")

    args = parser.parse_args(argv)

    if args.command == "validate":
        from . import validate
        return validate.main([args.path] if args.path else [])
    if args.command == "secrets":
        from . import secrets_scan
        return secrets_scan.main()
    if args.command == "smoke":
        from . import smoke
        return smoke.main()
    if args.command == "draft":
        from . import script
        return script.main()
    if args.command == "radio":
        from . import radio
        return radio.main()
    if args.command == "status":
        from . import status
        return status.main()
    if args.command == "costs":
        from . import costs
        return costs.main()
    if args.command == "film":
        from . import film
        return film.main(only=args.only, force=args.force)
    return 2


if __name__ == "__main__":
    sys.exit(main())
