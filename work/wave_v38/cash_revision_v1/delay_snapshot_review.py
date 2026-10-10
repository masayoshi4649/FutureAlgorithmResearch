"""最新の成熟済み注文群を使う遅延モデルの境界だけを人工価格で監査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import numpy as np

import adaptive_causality_audit as common

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
engine = common.engine


def calculate(prices: list, times: list | None = None, neutral_after: int | None = None,
              reverse_after: int | None = None, delay: float = 5.) -> tuple:
    """機能: 人工入力だけで独立影と追加予算なしの元A0実枠を生成する。

    引数: prices/times (list|None)、neutral_after/reverse_after (int|None)、delay (float)。
    返り値: ready・影・実 (tuple[dict,dict,dict])。完成した影を実へ流用しない。
    """
    args = common.fixture(prices, spacing=1.)
    ready, state, config = args[:3]
    if times is not None:
        assert len(times) == len(prices)
        ready['time_s'][:len(prices)] = times
    if neutral_after is not None:
        state[neutral_after:] = 0
    if reverse_after is not None:
        state[reverse_after:] = -1
    assert np.all(np.diff(ready['time_s']) >= 0)
    shadow = engine.make_shadow(ready, state, config, min_delay_seconds=delay)
    zero = np.zeros(len(state), np.int8)
    missing = np.full(len(state), -1, np.int64)
    policy = next(s['policy'] for s in common.design.catalog() if s['policy']['id'] == 'A0')
    actual = engine.run(ready, state, config, zero, missing, zero, missing, policy,
        min_delay_seconds=delay, budget_enabled=False)
    for name in engine.FIELDS:
        common.exact(actual[name], shadow[name], '人工A0影実/' + name)
    for result in (shadow,actual):
        for order in result['orders']:
            filled, source = int(order[0]), int(order[1])
            assert source < filled
            assert ready['time_s'][source]+delay <= ready['time_s'][filled]+1e-8
    for row, plan in enumerate(shadow['execution_plans']):
        if np.isfinite(plan[33]):
            source = int(plan[33])
            assert source < row and ready['time_s'][source]+delay <= ready['time_s'][row]+1e-8
    return ready,shadow,actual


def record(name: str, ready: dict, result: dict, detail: str) -> dict:
    """機能: 人工約定の時刻・元行・準備を短い証跡にする。

    引数: name/detail (str)、ready/result (dict)。返り値: 一検査 (dict)。
    """
    return dict(検査=name,合格=True,意味=detail,
        注文=[dict(行=int(o[0]),元行=int(o[1]),時刻=float(ready['time_s'][int(o[0])]),
            元時刻=float(ready['time_s'][int(o[1])]),方向=int(o[3]),枚数=int(o[4]),
            価格=float(o[5]),理由=int(o[6])) for o in result['orders']],
        準備=result['prepare_events'].tolist())


def main() -> None:
    """機能: 遅延・取消・旧注文再発火の具体例を検算し、モデルの仮定を記録する。

    引数: なし。返り値: なし (None)。旧固定と実装は変更せず、新実相場を再生しない。
    """
    socket.socket.connect = common.runner.reject_network
    socket.create_connection = common.runner.reject_network
    paths = (Path(engine.__file__),Path(engine.shadow_engine.__file__),HERE/'adaptive_causality_fixed.json',
             HERE/'adaptive_wave_fixed.json',HERE/'adaptive_causality_audit.py',Path(__file__))
    hashes = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    rows = []

    # ----------------------------------------
    # 取消が未到着の旧注文は成立し得る。成立後は古い世代の逆注文を受け付けない。
    ready,shadow,_=calculate([100,100,102,103,104,104,104,104,104,104],
        [0,1,5,6,7,8,9,10,11,12],reverse_after=1)
    opens=shadow['orders'][shadow['orders'][:,6]==20]
    assert len(opens)==1 and opens[0,0]==2 and opens[0,1]==0 and opens[0,3]==1
    assert len(shadow['prepare_events'])==2 and shadow['prepare_events'][1,2]==-1
    assert np.isnan(shadow['execution_plans'][3:7,33]).all()
    assert shadow['execution_plans'][7,33]==2
    rows.append(record('未成熟取消と旧世代の新規再発火防止',ready,shadow,
        '時刻5で旧買いが約定。時刻6から成熟する逆新規準備は、約定認知後の組・方向と不一致なので破棄。時刻10で初回保護計画が有効。'))

    ready,shadow,_=calculate([100,100,102,99],[0,1,6,10],neutral_after=1)
    assert not len(shadow['orders']) and shadow['execution_plans'][2,33]==1
    rows.append(record('取消到着後の旧新規不発',ready,shadow,
        '旧買い水準に達しても、時刻6では時刻1の取消が成熟しており約定しない。'))

    ready,shadow,_=calculate([100,101,103],[0,300,306])
    opens=shadow['orders'][shadow['orders'][:,6]==20]
    assert len(opens)==1 and opens[0,0]==2 and opens[0,1]==1
    assert shadow['entry_preparations'][0,2]==1
    rows.append(record('絶対期限等号と新準備',ready,shadow,
        '時刻300で準備0は期限切れ。約定は時刻300に作った準備1が成熟した時刻306だけ。'))

    # ----------------------------------------
    # 未成熟の高い追跡線を先取りせず、到着まで以前の成熟線を使う。
    prices=[100,100,100,100,100,102,110,120,120,120,120,105,105,105]
    ready,shadow,_=calculate(prices)
    assert shadow['plans'][6,13]==98 and shadow['plans'][7,13]==108
    assert shadow['execution_plans'][11,33]==6 and shadow['execution_plans'][11,13]==98
    assert shadow['execution_plans'][12,33]==7 and shadow['execution_plans'][12,13]==108
    assert not np.any((shadow['orders'][:,0]==11)&(shadow['orders'][:,6]==2))
    trail=shadow['orders'][shadow['orders'][:,6]==2]
    assert len(trail)==1 and trail[0,0]==12 and trail[0,1]==7
    rows.append(record('未成熟追跡更新と成熟旧線の維持',ready,shadow,
        '時刻11の追跡線は98。時刻7に公開した108は時刻12で有効になり、そこで初めて返済する。'))

    ready,shadow,_=calculate([100]*5+[102]+[110]*15)
    split=shadow['orders'][shadow['orders'][:,6]==7]
    assert len(split)==1 and split[0,0]==10
    assert np.isnan(shadow['execution_plans'][11:15,14]).all()
    assert (shadow['execution_plans'][11:15,11]==1).all()
    rows.append(record('既済部分利確の再執行防止',ready,shadow,
        '古い利確前計画が引き続き成熟しても、既済数量を即時反映して部分利確を一度に制限する。'))

    ready,shadow,actual=calculate([100]*5+[102,90,100,100,100,100,100,100])
    stop=shadow['orders'][shadow['orders'][:,6]==1]
    assert len(stop)==1 and stop[0,0]==11 and stop[0,1]==6 and stop[0,5]==100
    np.testing.assert_array_equal(actual['orders'],shadow['orders'])
    rows.append(record('回復後も市場返済予約を保持し二重遅延しない',ready,shadow,
        '時刻6の損失到達予約は価格回復で消えず、5秒後の時刻11で影と実の両方が一度だけ執行する。'))

    ready,shadow,_=calculate([100,102,102,102,102,102,102],[0,0,1,4,5,5,10])
    opens=shadow['orders'][shadow['orders'][:,6]==20]
    assert len(opens)==1 and opens[0,0]==4 and opens[0,1]==0
    assert np.isnan(shadow['execution_plans'][5,33])
    rows.append(record('同時刻別行は成熟時間を短絡しない',ready,shadow,
        '時刻0の別行では約定せず時刻5で一度だけ新規。直後の同時刻行で旧準備を再利用しない。'))

    # ----------------------------------------
    # 更新・取消が到着する間の未知の約定順序はこのモデルで推定しない。
    for name,sha in hashes.items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
    result=dict(全合格=True,人工検査数=len(rows),検査=rows,
        現契約との具体的不整合検出=False,実装変更=False,固定変更=False,
        新実相場再生=False,新損益読取=False,現在保存物使用=False,API取得数=0,
        SHA256=hashes,
        限界=['約定結果は同じ行で即時認知し、失効した注文世代を即座に排除する。',
            '同じ組の新規・取消・返済を原子的な注文群として扱い、独立注文の確認通信や部分受付失敗を再現しない。',
            '伝達中の未知の板交差や約定順序は補間せず、成熟後の観測価格だけで判断する。',
            '正遅延では初回約定後の保護注文が成熟するまで保護が未発効の区間がある。',
            'CurrentPriceTimeを時計にする感度試験であり、受信時刻や実ブローカーの往復遅延を測ったものではない。'])
    (HERE/'delay_snapshot_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (HERE/'delay_snapshot_review.md').write_text('''# 注文遅延の限定読取監査

現契約に反する具体的な再発火・未成熟線の先取りは、今回の読取と人工7検査では見つからなかった。新しい実相場成績は計算していない。

最新の成熟済み計画だけを使い、注文の元行は必ず約定行より前である。取消前に旧新規が約定する例と、取消到着後には成立しない例を確認した。新規約定後は古い組の準備を排除し、部分利確後は古い計画の利確欄を無効化する。未成熟の追跡更新は先取りせず、市場返済予約は途中の価格回復で消えない。実口座は影の成熟計画をその行で使用するため、影由来の注文へ二度目の遅延を掛けない。

ただし、これは**約定を即時に認知し、同じ組を原子的に管理できる注文モデル**である。約定通知を待たず、その行から旧世代の注文や返済済み数量を排除する。独立した注文の取消確認遅れ・部分受付・通知順の逆転は含まない。実運用で同じ性質を保てるかは別途確認が必要である。

また、初回約定から保護計画が成熟するまでの空白が生じる。伝達中に観測できなかった交差は補間せず、成熟後の観測でだけ約定を判定する。指定価格約定はユーザー指定の仮定を保ち、現在値での約定は別対照である。使用時計も受信時刻ではなく CurrentPriceTime なので、実通信の往復遅延や実約定の再現を保証する試験ではない。

詳細は `delay_snapshot_review.json`。売買コード・既存固定・採否基準は変更していない。
''',encoding='utf-8')
    print('遅延snapshotの人工7検査が一致。コードと固定を変更せず、仮定の限界を保存しました。')


if __name__=='__main__':
    main()
