"""金融結果を読まず、純価格二仕様を独立した逐次選点と算術で検算する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(path: Path, name: str):
    """
    機能: 依存のない価格測定sourceだけを隔離名で読む。
    引数: path(Path)は純価格module、name(str)は私有登録名。
    返り値: moduleは測定関数のみ。金融sourceをimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    """
    機能: 小sourceと人工資料の内容指紋を求める。
    引数: path(Path)は小ファイル。
    返り値: strはSHA256。巨大入力を読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(side: int, tick: float) -> dict:
    """
    機能: 両市場・両方向に対称な人工原板価格列を作る。
    引数: side(int)は±1、tick(float)は当該市場の呼値。
    返り値: dictは401行。数量と出来高の資格は最初から全てFalse。
    """
    n = 401; bid = 10000.+side*np.arange(n)*tick/60.
    return dict(raw_seq=np.arange(n,dtype=np.int64),price_time_s=np.arange(n,dtype=float),
        bid=bid,ask=bid+tick,qualified=np.zeros(n,bool),bbo_valid=np.zeros(n,bool),
        price_reset_reason=np.full(n,96,np.uint16))


def publication_oracle(raw: dict, row_bound: int | None = None) -> list[int]:
    """
    機能: 最初の新最大時計だけを逐次採取し、自己では原行上限で先に切る。
    引数: raw(dict)、row_bound(int|None)は自己の当時行。
    返り値: list[int]は資格で公表行を選別しない独立期待値。
    """
    answer = []; high = -float('inf')
    for row in range(len(raw['raw_seq']) if row_bound is None else row_bound+1):
        time = float(raw['price_time_s'][row])
        if np.isfinite(time) and time > high:
            high = time; answer.append(row)
    return answer


def sample_oracle(raw: dict, stamp: float, tick: float, row_bound: int | None,
                  strict: bool, start: float = 0., end: float = 401.) -> dict:
    """
    機能: 六選点と価格資格・ERをowner実装から独立した逐次算式で求める。
    引数: raw(dict)、stamp/tick/start/end(float)、row_bound(int|None)、strict(bool)。
    返り値: dictは既知と期待選点・ER。区間の隣接有限clock逆行だけを宣言仕様どおり判定する。
    """
    public = publication_oracle(raw,row_bound); chosen = []; known = True
    for offset in (300.,240.,180.,120.,60.,0.):
        target = stamp-offset
        available = [row for row in public if raw['price_time_s'][row] <= target and
            (offset != 0. or not strict or raw['price_time_s'][row] < stamp)]
        if not available:
            return dict(known=False,rows=[],ER=None)
        row = available[-1]; chosen.append(row); t = float(raw['price_time_s'][row])
        bid,ask = float(raw['bid'][row]),float(raw['ask'][row])
        known &= (0 <= target-t <= 15 and start <= t < end and np.isfinite(bid) and np.isfinite(ask) and 0 < bid < ask)
    first,last = chosen[0],chosen[-1] if row_bound is None else row_bound
    for row in range(max(1,first),last+1):
        a,b = float(raw['price_time_s'][row-1]),float(raw['price_time_s'][row])
        if raw['raw_seq'][row] != raw['raw_seq'][row-1]+1 or (np.isfinite(a) and np.isfinite(b) and b < a):
            known = False
    mids = [.5*(float(raw['bid'][row])+float(raw['ask'][row])) for row in chosen]
    tv = sum(abs(b-a) for a,b in zip(mids[:-1],mids[1:])); net = mids[-1]-mids[0]
    return dict(known=bool(known),rows=chosen,ER=abs(net)/tv if known and tv else None)


def field_oracle(raw: dict) -> np.ndarray:
    """
    機能: 二端点版の価格時計欠測・過去最大から逆行・原seq断裂を逐次判定する。
    引数: raw(dict)は原行順価格列。
    返り値: ndarray[bool]はownerのprefixに依存しない期待不正列。
    """
    result = []; maximum = -float('inf')
    for row,time in enumerate(raw['price_time_s']):
        bad = not np.isfinite(time) or time < maximum
        if row and raw['raw_seq'][row] != raw['raw_seq'][row-1]+1:
            bad = True
        result.append(bad)
        if np.isfinite(time):
            maximum = max(maximum,float(time))
    return np.array(result,bool)


def main() -> None:
    """
    機能: 価格資格の量非依存・未来不変・未知保持・二仕様の差を小人工で検査する。
    引数: なし。正式入力・正式金融結果を読み込まない。
    返り値: Noneは人工証跡と留保を私有領域に保存する。
    """
    paths = [ROOT/'work/wave_v106/regime_price/features.py',ROOT/'work/wave_v106/regime_price/prepare.py',
        ROOT/'work/wave_v106/e01_pending_price/prices.py',ROOT/'work/wave_v106/e01_pending_price/prepare.py']
    before = {str(path.relative_to(ROOT)):sha(path) for path in paths}
    regime = load(paths[0],'独立純価格六点'); pending = load(paths[2],'独立純価格二端点')
    checks = {}; examples = []
    def counted(label: str) -> None:
        """
        機能: 合格した独立検査を用途別に数える。
        引数: label(str)は検査名。
        返り値: Noneは私有件数を更新する。
        """
        checks[label] = checks.get(label,0)+1
    for tick in (.5,10.):
        for side in (-1,1):
            original = fixture(side,tick)
            for strict in (False,True):
                bound = None if strict else 360
                cases = ['基準','量資格だけ反転','途中BBO不正','途中時計NaN','clockgapのみ','seq断裂','隣接逆clock',
                    '端点NaN','端点交差','端点age15','端点age16','同時計後半の未来','欠測を挟む逆clock',
                    '不正先頭の同時計後半だけ正常','途中巨大往復']
                for label in cases:
                    raw = deepcopy(original)
                    if label == '量資格だけ反転':
                        raw['qualified'][:] = True; raw['bbo_valid'][:] = True; raw['price_reset_reason'][:] = 0
                    elif label == '途中BBO不正': raw['bid'][125] = np.nan
                    elif label == '途中時計NaN': raw['price_time_s'][125] = np.nan
                    elif label == 'clockgapのみ': raw['price_time_s'][61:81] = 60.
                    elif label == 'seq断裂': raw['raw_seq'][125:] += 1
                    elif label == '隣接逆clock': raw['price_time_s'][125] = 123.
                    elif label == '端点NaN': raw['bid'][120] = np.nan
                    elif label == '端点交差': raw['ask'][120] = raw['bid'][120]
                    elif label == '端点age15': raw['price_time_s'][106:121] = 105.
                    elif label == '端点age16': raw['price_time_s'][105:121] = 104.
                    elif label == '同時計後半の未来':
                        raw['price_time_s'][361] = 360.; raw['bid'][361] = 1.; raw['ask'][361] = 2.
                    elif label == '欠測を挟む逆clock':
                        raw['price_time_s'][125] = np.nan; raw['price_time_s'][126] = 123.
                    elif label == '不正先頭の同時計後半だけ正常':
                        raw['bid'][120] = np.nan; raw['price_time_s'][121] = 120.
                    elif label == '途中巨大往復':
                        raw['bid'][125] += 1000.; raw['ask'][125] += 1000.
                    expected = sample_oracle(raw,360.,tick,bound,strict)
                    actual = regime.sample(raw,regime.context(raw,start=0.,limit=401.),360.,tick,bound,strict)
                    assert actual['known'] == expected['known'], (label,actual,expected)
                    assert actual['rows'] == expected['rows'], label
                    if actual['known']:
                        assert abs(actual['ER']-expected['ER']) <= 1e-12
                    counted('六点逐次oracle_'+label)
                    np.testing.assert_array_equal(pending.field_bad(raw),field_oracle(raw)); counted('二端点高水準時計oracle_'+label)
                    if label == '欠測を挟む逆clock' and tick == .5 and side == 1 and not strict:
                        examples.append({'反例':'124→NaN→123の時計列','六点版既知':actual['known'],
                            '二端点版123行を不正':bool(pending.field_bad(raw)[126]),
                            '意味':'六点版は隣接有限時計のみ検査し、欠測を跨ぐ高水準逆行を拒否する保証はない。二端点版は拒否する。'})
                    if label == '途中巨大往復' and tick == .5 and side == 1 and not strict:
                        mids = .5*(raw['bid'][:361]+raw['ask'][:361])
                        dense_er = abs(float(mids[-1]-mids[0]))/float(np.abs(np.diff(mids)).sum())
                        assert actual['known'] and actual['ER'] > .99 and dense_er < .01
                        examples.append({'反例':'選点の間125行で1000pt往復','六点ER':actual['ER'],'全人工行ER':dense_er,
                            '意味':'六点ERが1でも、その間の全板価格経路が一方向であったことは保証しない。'})
            pubrows = publication_oracle(original); public = dict(rows=np.array(pubrows,np.int64),times=original['price_time_s'][pubrows],raw_seq=original['raw_seq'][pubrows])
            policy = dict(baseline_extra_age_seconds=15.,spread_max_ticks=2,spread_increment_ticks=1)
            window = pending.windows(original,public,tick,policy,0.,401.)
            for width in (10,30,60):
                x = window['windows'][str(width)]
                for end in range(width,361):
                    begin = end-width
                    assert x['reference_raw_row'][end] == begin
                    expected_bid = (original['bid'][end]-original['bid'][begin])/tick
                    expected_ask = (original['ask'][end]-original['ask'][begin])/tick
                    assert abs(x['bid_change_ticks'][end]-expected_bid) <= 1e-12
                    assert abs(x['ask_change_ticks'][end]-expected_ask) <= 1e-12
                    assert x['unknown_reason'][end] == 0
                    direction = side if min(abs(expected_bid),abs(expected_ask)) >= 1 else 0
                    assert x['direction_t1'][end] == direction
                    counted('二端点価格差と原系譜')
            changed = deepcopy(original); changed['qualified'][:] = True; changed['bbo_valid'][:] = True; changed['price_reset_reason'][:] = 0
            nextvalue = pending.windows(changed,public,tick,policy,0.,401.)
            for width in ('10','30','60'):
                for field in ('unknown_reason','direction_t1','reference_raw_row','bid_change_ticks','ask_change_ticks'):
                    np.testing.assert_array_equal(window['windows'][width][field],nextvalue['windows'][width][field]); counted('二端点量資格非依存')
            observed = np.array([0.,400.,415.,415.000001]); qualified = np.ones(4,bool)
            projected = pending.project(original,window,observed,None,60,True,qualified)
            assert projected['public_index'].tolist() == [-1,399,400,400]
            assert np.isnan(projected['age_seconds'][0]) and projected['age_seconds'][1] == 1.
            assert projected['age_seconds'][2] == 15. and projected['direction'][2] == side
            assert projected['direction'][0] == projected['direction'][3] == 3
            counted('相手strictpastとage15境界と未知未救済')
    after = {str(path.relative_to(ROOT)):sha(path) for path in paths}; assert before == after
    output = dict(全合格=True,scope='純価格source独立人工のみ・正式金融結果未読',検査件数=checks,検査合計=sum(checks.values()),
        source_SHA256=before,開始終端source一致=True,人工反例と仕様差=examples,金融結果読取=0,金融再生=0,原本NPZAPI=0,
        設計判定='価格算式から数量/出来高資格を分離する理由は妥当。源C/R数量根拠を緩和する操作とは異なる。',
        留保=['六点版は間の不正BBO/時計欠測を保証しない宣言仕様。完全な時計整合保証ではない。',
            '二端点版は時計欠測と過去最大からの逆行も拒否し、六点版より区間資格が厳しい。両者を同一資格とは呼ばない。',
            'first-newmax圧縮に捨てられた板と上流非normalのNaNは回復しない。',
            'asof15は最終価格時計であり、板受信間隔や実秒での新鮮さを保証しない。',
            'この人工合格は利潤や将来勝率の証拠ではない。'])
    output['レビューsource_SHA256'] = sha(Path(__file__))
    (HERE/'純価格二仕様の独立人工と定義の限界.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print('純価格独立人工',sum(checks.values()),'合格',flush=True)


if __name__ == '__main__':
    main()
