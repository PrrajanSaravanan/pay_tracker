"""Database commands.

    python -m paytracker.db setup     # migrate to latest + load seed data
    python -m paytracker.db migrate   # migrate to latest only
    python -m paytracker.db seed      # reload seed data (empties all tables first)
    python -m paytracker.db reset     # drop everything, migrate, seed

`seed` and `reset` refuse to run if non-seed invoices exist, unless --force is given.
"""

import argparse
import sys

from paytracker.db import migrate
from paytracker.db.seed import SeedRefused, count_real_invoices, seed
from paytracker.db.session import get_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m paytracker.db")
    parser.add_argument("command", choices=["setup", "migrate", "seed", "reset"])
    parser.add_argument("--force", action="store_true", help="allow deleting non-seed invoices")
    args = parser.parse_args(argv)

    try:
        if args.command == "reset":
            with get_session() as session:
                real = count_real_invoices(session)
            if real and not args.force:
                raise SeedRefused(
                    f"{real} non-seed invoice(s) exist and reset would delete them. "
                    "Pass --force to do it anyway."
                )
            migrate.downgrade()

        if args.command in ("setup", "migrate", "reset"):
            migrate.upgrade()

        if args.command in ("setup", "seed", "reset"):
            with get_session() as session:
                seed(session, force=args.force)
            print("Seed data loaded.")
    except SeedRefused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
