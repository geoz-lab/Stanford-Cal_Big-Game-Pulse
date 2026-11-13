"""biggame CLI: games | football | collect | status | label | build | serve | export"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="biggame")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("games", help="refresh kickoff/score/scoring plays from ESPN")
    sub.add_parser("football", help="coaches, rosters and box-score stats from ESPN")
    sub.add_parser("collect", help="collect videos + comments for all seasons (resumable)")
    sub.add_parser("status", help="per-season collection status and quota")
    lab = sub.add_parser("label", help="multi-model LLM sentiment labeling")
    lab.add_argument("--models", default="haiku,sonnet,opus")
    lab.add_argument("--limit", type=int, default=None)
    lab.add_argument("--sync", action="store_true", help="use synchronous calls instead of the Batch API")
    sub.add_parser("build", help="build the dashboard dataset")
    ex = sub.add_parser("export", help="standalone HTML dashboard + zip in dist/")
    ex.add_argument("--public", action="store_true", help="results only: no comment text, creators or video links")
    srv = sub.add_parser("serve", help="run the dashboard")
    srv.add_argument("--port", type=int, default=8050)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.cmd == "games":
        from .espn import refresh_games
        refresh_games()
    elif a.cmd == "football":
        from .football import refresh_football
        refresh_football()
    elif a.cmd == "collect":
        from .collect import collect_all
        return collect_all()
    elif a.cmd == "status":
        from .status import print_status
        print_status()
    elif a.cmd == "label":
        from .label import run
        run(a.models.split(","), limit=a.limit, sync=a.sync)
    elif a.cmd == "build":
        from .build import build
        build()
    elif a.cmd == "export":
        from .export import export
        print(export(public=a.public))
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("backend.app:app", host="127.0.0.1", port=a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
