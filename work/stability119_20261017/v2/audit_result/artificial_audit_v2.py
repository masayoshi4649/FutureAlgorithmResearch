"""新規保護と親Last分解の追加監査を、手計算の人工台帳で確認する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import audit_v2 as owner


def main() -> None:
    """
    機能: 新監査ラッパーの売買保護とLast恒等式を、市場とengineなしで確認する。
    引数: なし。
    返り値: None。結果JSON・cache・金融エンジンを読まない。
    """
    ledger = np.asarray([[1., 1., 2., 1., 2., 1., 3., 1000., 1010., 30000., 125., 125., 29750., 4., 0., 1.]])
    quotes = dict(row=np.arange(3), time=np.arange(3, dtype=float),
                  bid=np.asarray([999., 999., 1010.]), ask=np.asarray([1000., 1000., 1011.]),
                  last=np.asarray([999.5, 999.5, 1010.5]))
    bars = dict(pub_raw_row=np.asarray([0]), pub_price_time_s=np.asarray([0.]), anchor=np.asarray([1000.]), close=np.asarray([1000.]))
    owner.entry_protection(ledger, bars, quotes, "TOPIX", 3)
    flipped = ledger.copy()
    flipped[:, 5] *= -1
    flipped[:, 7:9] = 2000. - flipped[:, 7:9]
    reflected = dict(quotes, bid=2000. - quotes["ask"], ask=2000. - quotes["bid"], last=2000. - quotes["last"])
    owner.entry_protection(flipped, bars, reflected, "TOPIX", 1)
    saved = [dict(parent=1, direction=1, quantity=3., entry_raw=1, entry_time=1., entry=1000.,
                  entry_last=999.5, entry_bid=999., entry_ask=1000., signal_bar=0, prior20_change=None,
                  final_time=2., MFE_observed=10., MAE_observed=-1., gross_last_same_times=33000.,
                  entry_adverse=1500., exit_adverse=1500., fees=250., net=29750.,
                  legs=[dict(exit_raw=2, exit_time=2., quantity=3., exit=1010., bid=1010., ask=1011.,
                             last=1010.5, reason=4, net=29750., decision_to_fill=1.)])]
    owner.episodes(ledger, quotes, bars, 1000., saved)
    owner.audit.check(owner.READS == dict(結果=0, v2cache=0, 既所有v1cache=0, 原市場=0, 原cache追加=0, 金融再実行=0), "純人工のみ")
    here = Path(__file__).resolve().parent
    proof = dict(全合格=True, 検査数=owner.audit.CHECKS, counts=owner.READS,
                 監査源SHA256=hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest(),
                 算術源SHA256=hashlib.sha256(Path(owner.audit.__file__).read_bytes()).hexdigest(),
                 人工源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    owner.write(here / "新規価格保護とLast分解の保存会計監査器の純人工.json", proof)
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
