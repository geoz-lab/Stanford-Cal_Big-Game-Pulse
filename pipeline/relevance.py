"""Rule-based relevance tiers (generalized from the 2025 demo): big_game | team_football | off_topic | unrelated."""

from __future__ import annotations

import re

import pandas as pd

STANFORD = re.compile(r"\b(stanford|stanfurd|stantuu*rd|gostanford|stanfordfootball|stanfordcardinal|lsjumb|fear the tree)")
CAL = re.compile(r"\b(cal|berkeley|ucberkeley|golden ?bears|calbears|gobears|go bears|calfootball|calgorithm|calband|california)\b")
RIVALRY = (r"big ?game|thebiggame|stanford ?vs?\.? ?cal|cal ?vs?\.? ?stanford|stanfordvcal|calvstanford|"
           r"\baxe\b|stanfordaxe|theaxe|🪓|stanfordsucks|beat ?cal|beat ?stanford")
FOOTBALL = re.compile(r"\b(football|collegefootball|cfb|game ?day|gamedayoutfit|tailgate|touchdown|quarterback|qb|"
                      r"kickoff|stadium|jks|wilcox|rally|marching band|band|the play)\b")
OFF_TOPIC = re.compile(r"\b(hunt|hunting|hunter|elk|deer|safari|rifle|whitetail|antler|super ?bowl)\b")


def rivalry_pattern(score: tuple[int, int] | None) -> re.Pattern:
    """Rivalry markers plus that year's final score (e.g. '31-10', '31 to 10')."""
    extra = ""
    if score:
        hi, lo = max(score), min(score)
        extra = rf"|{hi}[ -–]{lo}|{hi} to {lo}"
    return re.compile(f"({RIVALRY}{extra})")


def video_text(row: pd.Series) -> str:
    stickers = row.get("sticker_info_list")
    sticker_txt = ""
    if isinstance(stickers, list):
        sticker_txt = " ".join(str(s.get("sticker_name") or "") for s in stickers if isinstance(s, dict))
    return " ".join([
        str(row.get("video_description") or ""),
        " ".join(row["hashtag_names"]) if isinstance(row.get("hashtag_names"), list) else "",
        str(row.get("voice_to_text") or ""),
        sticker_txt,
    ]).lower()


def classify(row: pd.Series, rivalry: re.Pattern) -> str:
    text = video_text(row)
    stanford, cal = bool(STANFORD.search(text)), bool(CAL.search(text))
    if OFF_TOPIC.search(text):
        return "off_topic"
    if (rivalry.search(text) and (stanford or cal)) or (stanford and cal and FOOTBALL.search(text)):
        return "big_game"
    if (stanford or cal) and FOOTBALL.search(text):
        return "team_football"
    return "unrelated"
