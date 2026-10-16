"""gapだけの修正を独立旧関数と同原行派生へ照合する。"""

from copy import deepcopy
from pathlib import Path

import numpy as np

import artificial
import common
import features
import prepare

HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 価格時計停滞の理由だけ外れることと保存6点派生の数学一致を検算する。
    引数: なし。
    返り値: None。実inputも金融も読み込まない。
    """
    target=HERE/'gap観測定義と保存6点派生の独立人工.json';assert not target.exists()
    strict=common.module('106strict6点特徴の読取専用対照',common.WAVE/'regime/features.py')
    paths=[HERE/n for n in ('features.py','prepare.py','definition_artificial.py')]
    paths+=[common.WAVE/'regime/features.py']
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths};checks={}
    for peer in (False,True):
        for side in (1,-1):
            raw=artificial.raw_fixture([100+side*i for i in range(6)],peer)
            raw['price_time_s'][61:81]=raw['price_time_s'][60]
            for variant in ('gapだけ','公表資格不正','price reset','時計逆行','seq断裂','端点age超過','非公表BBO不正'):
                changed=deepcopy(raw)
                if variant=='公表資格不正':changed['qualified'][120]=False
                elif variant=='price reset':changed['price_reset_reason'][125]=32
                elif variant=='時計逆行':changed['price_time_s'][125]=changed['price_time_s'][124]-1
                elif variant=='seq断裂':changed['raw_seq'][125:]+=1
                elif variant=='端点age超過':changed['price_time_s'][100:121]=changed['price_time_s'][99]
                elif variant=='非公表BBO不正':changed['bbo_valid'][65]=False
                stamp=360.;row=None if peer else 360
                old=strict.sample(changed,strict.context(changed),stamp,.5,row,peer)
                new=features.sample(changed,features.context(changed),stamp,.5,row,peer)
                record=dict(seq=changed['raw_seq'],time_s=changed['price_time_s'],bid=changed['bid'],ask=changed['ask'],
                    quote_valid=changed['bbo_valid'],tick=.5)
                saved=prepare.derive_measure(old,record)
                assert new==saved,(variant,old,new,saved)
                assert int(new['reason'])==int(old['reason'])&~16
                if variant in ('gapだけ','非公表BBO不正'):assert not old['known'] and new['known']
                else:assert not new['known']
                checks[variant]=checks.get(variant,0)+1
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=checks,source_SHA256=before,
        開始終端source一致=True,正式input読取=0,新金融再生=0,原板読取=0,API取得=0,
        検査範囲='旧関数との変更はgap bit16のみ。保存seqへの完全一致投影は未来正常行検索をしない。'))
    print('観測定義の独立人工 '+str(sum(checks.values()))+'件',flush=True)


if __name__=='__main__':main()
