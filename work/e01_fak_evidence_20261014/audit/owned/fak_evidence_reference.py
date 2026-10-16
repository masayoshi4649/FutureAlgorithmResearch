"""価格票二回の証拠をFAK一呼値許容だけへ追加し、出来高入口を別に保つ。"""

from math import isfinite
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[4]
sys.path.append(str(ROOT / 'work/e01_entry_information_20261014/audit/owned'))
from entry_information_reference import Price


def allowance(own: Price,peer: Price,side: int) -> int:
    """
    機能: 候補方向の強支持に両市場各二価格更新票を要求して一呼値許容を判定する。
    引数: own/peer(Price)、side(int:±1) は現在票と注文方向。
    返り値: int は両既知・各二票・両方向釣合い0.75以上なら1、他0。
    """
    assert side in (-1,1)
    return int(all(p.known and p.count>=2 and isfinite(p.balance) and side*p.balance>=.75 for p in (own,peer)))


def first_try(side: int,public_quote: float,tick: float,tolerance: int,quotes: list[tuple[bool,float]]) -> dict:
    """
    機能: 公開価格へ許容を一度だけ固定し、最初正常気配一回のfill又は失効を判定する。
    引数: side(int:±1)、public_quote/tick(float)、tolerance(int:0/1)、quotes(list[tuple[bool,float]])。
    返り値: dict は固定capと最初試行/成否。後気配へ失効注文を復活させない。
    """
    assert side in (-1,1) and tolerance in (0,1) and public_quote>0 and tick>0
    cap=public_quote+side*tolerance*tick
    for row,(normal,quote) in enumerate(quotes):
        if normal:
            assert isfinite(quote) and quote>0
            return dict(cap=cap,試行行=row,約定=quote<=cap if side>0 else quote>=cap,約定価格=quote if (quote<=cap if side>0 else quote>=cap) else None)
    return dict(cap=cap,試行行=None,約定=None,約定価格=None)
