"""数量と分離した価格資格を、原行と6端点の独立期待値で検算する。"""

from copy import deepcopy
from pathlib import Path

import numpy as np

import artificial
import common
import features

HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 量連動除外、NaN不救済、seq/逆時計、厳密過去と未来不変を人工検算する。
    引数: なし。
    返り値: None。正式入力も金融も読み込まない。
    """
    target=HERE/'純価格資格と未知端点不救済の人工検査.json';assert not target.exists()
    paths=[HERE/n for n in ('features.py','prepare.py','price_artificial.py')]
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths};checks={}
    specs=[('基準',True),('量出来高fullqualifiedなし',True),('旧bbovalidなし',True),
        ('混合reset32',True),('混合reset64',True),('途中BBO不明',True),('価格clock停滞',True),
        ('途中時計不明',True),('NaN跨ぎ高水準逆行',False),('原seq断裂',False),('隣接時計逆行',False),('端点BBO不明',False),
        ('端点交差BBO',False),('端点asof超過',False),('端点場外',False)]
    for peer in (False,True):
        for side in (1,-1):
            original=artificial.raw_fixture([100+side*i for i in range(6)],peer)
            row=None if peer else 360;stamp=360.;ctx=features.context(original,start=0,limit=402)
            baseline=features.sample(original,ctx,stamp,.5,row,peer)
            assert baseline['known'] and len(baseline['midpoint'])==6
            for label,expected in specs:
                raw=deepcopy(original);start=0.
                if label=='量出来高fullqualifiedなし':raw['qualified'][:]=False
                elif label=='旧bbovalidなし':raw['bbo_valid'][:]=False
                elif label=='混合reset32':raw['price_reset_reason'][:]=32
                elif label=='混合reset64':raw['price_reset_reason'][:]=64
                elif label=='途中BBO不明':raw['bid'][125]=raw['ask'][125]=np.nan
                elif label=='価格clock停滞':raw['price_time_s'][61:81]=raw['price_time_s'][60]
                elif label=='途中時計不明':raw['price_time_s'][125]=np.nan
                elif label=='NaN跨ぎ高水準逆行':
                    raw['price_time_s'][125]=np.nan;raw['price_time_s'][126]=raw['price_time_s'][124]-1
                elif label=='原seq断裂':raw['raw_seq'][125:]+=1
                elif label=='隣接時計逆行':raw['price_time_s'][125]=raw['price_time_s'][124]-1
                elif label=='端点BBO不明':raw['bid'][120]=raw['ask'][120]=np.nan
                elif label=='端点交差BBO':raw['ask'][120]=raw['bid'][120]
                elif label=='端点asof超過':raw['price_time_s'][100:121]=raw['price_time_s'][99]
                elif label=='端点場外':start=100.
                value=features.sample(raw,features.context(raw,start=start,limit=402),stamp,.5,row,peer)
                assert value['known']==expected,(label,peer,side,value)
                if label in ('量出来高fullqualifiedなし','旧bbovalidなし','混合reset32','混合reset64','途中BBO不明','途中時計不明'):
                    assert value==baseline
                if label=='端点BBO不明':assert value['rows'][1]==120 and value['reason']&4
                checks[label]=checks.get(label,0)+1
            future=deepcopy(original);future['bid'][361:]=1.;future['ask'][361:]=2.
            future['price_time_s'][361:]=10000.;future['raw_seq'][361:]+=1000
            past=features.sample(future,features.context(future,start=0,limit=402),stamp,.5,row,peer)
            assert past==baseline;checks['未来priceclockとseqとBBOを混ぜない']=checks.get('未来priceclockとseqとBBOを混ぜない',0)+1
            assert all(t<stamp for t in baseline['times']) if peer else all(r<=row for r in baseline['rows'])
            checks['自己rawrow上限と相手strictpast']=checks.get('自己rawrow上限と相手strictpast',0)+1
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=checks,source_SHA256=before,
        開始終端source一致=True,正式input読取=0,新金融再生=0,原板読取=0,API取得=0,
        限界='途中経路は測っていない。保存raw非normal端点NaNは不明を維持する。量/出来高は元C/R入口だけに保持。'))
    print('純価格人工 '+str(sum(checks.values()))+'件',flush=True)


if __name__=='__main__':main()
