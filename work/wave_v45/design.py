"""探索で見つかった50%減量版を固定し、既知比較と新反証を分離する。"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PRIMARY='G150_F50_N1__V000'
CONTROL='G000_F25_N1__V000'
BASELINE='A0__V000'
PREVIOUS_PRIMARY='G150_F25_N1__V000'
SAME_FRACTION='G000_F50_N1__V000'
KNOWN_IDS=tuple(prefix+'__'+variant for prefix in ('A0','G000_F25_N1','G150_F25_N1')
                for variant in ('V000','E080','E120'))+(SAME_FRACTION,PRIMARY)


@lru_cache(maxsize=None)
def previous() -> dict:
    """機能: 完備済み00039の固定条件を読み、コピー元を返す。

    引数: なし。返り値: 旧固定資料(dict)。利用側は変更前に深く複写する。
    """
    return json.loads((HERE.parent/'wave_v44/探索条件の固定.json').read_text(encoding='utf-8'))


def economic(spec: dict) -> dict:
    """機能: 売買へ影響しない主案表示と資料区分だけを除く。

    引数: spec(dict)。返り値: 引継ぎ時に完全一致を要求する経済仕様(dict)。
    """
    return {k:v for k,v in spec.items() if k not in ('primary','role')}


def reused_id(spec: dict) -> str|None:
    """機能: 旧成果を使う11条件について経済仕様の完全一致を要求する。

    引数: spec(dict)。返り値: 旧ID又は該当なし(str|None)。
    """
    if spec['id'] not in KNOWN_IDS:return None
    original=next(r for r in previous()['conditions'] if r['id']==spec['id'])
    assert economic(spec)==economic(original),spec['id']
    return spec['id']


def specification(variant: str='V000', role: str='sensitivity', **changes) -> dict:
    """機能: 固定50%版の一つの軸だけを変更した条件を作る。

    引数: variant/role(str)、changes(dict)。返り値: 一条件(dict)。
    """
    result=deepcopy(next(r for r in previous()['conditions'] if r['id']==PRIMARY))
    result.update(id='G150_F50_N1__'+variant,variant_id=variant,role=role,primary=variant=='V000')
    result.update(changes)
    assert result['policy']['id']=='B00_RB00_F50_N1'
    assert result['gate_threshold_atr'] in (1.2,1.5,1.8)
    return result


def catalog() -> list[dict]:
    """機能: 既知11比較と新14反証を固定順で列挙する。

    引数: なし。返り値: 主比較25条件(list[dict])。
    """
    originals={r['id']:r for r in previous()['conditions']}
    rows=[]
    for identifier in KNOWN_IDS:
        row=deepcopy(originals[identifier])
        row.update(primary=identifier==PRIMARY,role='reference')
        rows.append(row)
    # ----------------------------------------
    # 近傍・入口時計・悪化回復窓・執行の一軸反証を旧25%版と揃える。
    for suffix,value in (('120',1.2),('180',1.8)):
        rows.append(specification('A'+suffix,gate_threshold_atr=value))
    for prefix,field in (('E','entry_scale'),('D','bad_scale'),('G','good_scale')):
        for suffix,value in (('080',.8),('120',1.2)):
            rows.append(specification(prefix+suffix,**{field:value}))
    for seconds in (1.,5.,15.):
        rows.append(specification(f'L{int(seconds):03d}',role='execution',min_delay_seconds=seconds))
    rows.append(specification('O000',role='execution',observed_fill=True))
    rows.append(specification('INV',role='mechanism',gate_mode='inverse'))
    rows.append(specification('AV_ALL',role='mechanism',gate_mode='any_valid'))
    assert len(rows)==len({r['id'] for r in rows})==25
    assert sum(r['primary'] for r in rows)==1
    assert sum(reused_id(r) is not None for r in rows)==11
    return rows


def supplementary() -> list[dict]:
    """機能: 同じ公開機会を保った悪化・回復各64符号対照を列挙する。

    引数: なし。返り値: 補助128条件(list[dict])。最良seedを選ばない。
    """
    rows=[]
    for seed in range(64):
        rows.append(specification(f'UB{seed:03d}',role='supplementary',bad_seed=seed))
        rows.append(specification(f'UG{seed:03d}',role='supplementary',good_seed=seed))
    assert len(rows)==len({r['id'] for r in rows})==128
    return rows


def rules() -> dict:
    """機能: 新しい有望配分と旧成績の再利用を事前に明示する。

    引数: なし。返り値: 固定比較規則(dict)。
    """
    return dict(主案=PRIMARY,元C01=CONTROL,元A0=BASELINE,前主25パーセント=PREVIOUS_PRIMARY,
        同50パーセント無ゲート=SAME_FRACTION,主条件数=25,既知主条件数=11,新主条件数=14,
        補助条件数=128,全条件数=153,新売買条件数=142,既知引継ぎ入力数=286,新売買入力数=3692,
        仮説='価格が1.5初期ATR順行した後、新しいB00悪化で現存枚数の50%を最大1回減量し、同じ元規則で復元する。',
        主案選択='00039の探索副案から選んだ既知成績の主案。今回の反証中は別の幅や割合へ差し替えない。',
        再利用='11条件は00039の完備成果をSHAと経済仕様で完全照合し、同じ売買を再生せず引き継ぐ。新たな独立標本や新発見とは数えない。',
        再利用変更可能欄=['primary','role'],ゲート実装='work/wave_v44/profit_gate.pyを無変更使用',
        注文器='work/wave_v41/engine_partial_restore_corrected.pyを無変更使用',
        旧規則='入口H019、部分利確、初期1R予算、トレーリング、360分、場内返済を全て維持。',
        価格距離時計='設計メモだけで今回へ混ぜない。',全13と後7は既知=True,
        現在API取得数=0,保存ライブ使用=False,費用=0,全体目標達成=False)


if __name__=='__main__':
    print(f'主{len(catalog())}（既知11、新14）、補助{len(supplementary())}。新損益なし。')
