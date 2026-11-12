from __future__ import annotations

from . import env  # noqa: F401

from .collect import comment_queue, load_videos, study
from .config import seasons


def print_status() -> None:
    print(f"{'season':<7}{'matched':>9}{'big_game':>10}{'w/ comments':>13}{'comments':>10}{'windows':>9}")
    for year, s in seasons().items():
        st = study(year)
        v = load_videos(year, st)
        n_rel = int((v.relevance == "big_game").sum()) if not v.empty else 0
        c = st.load("comments") if st.path("comments").exists() else []
        print(f"{year:<7}{len(v):>9}{n_rel:>10}{len(st.state.done('comment_videos')):>13}{len(c):>10}"
              f"{len(st.state.done('video_windows')):>9}")
    q = comment_queue()
    led = study(2025).research.client.ledger
    print(f"\nComment queue: {len(q)} videos left · quota remaining today: {led.remaining('default')}")
