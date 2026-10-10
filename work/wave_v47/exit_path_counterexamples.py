"""固定済みの出口へ四つの人工経路を与え、保護と早期返済の弱点を確認する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

import engine_exit_campaign as engine
import exit_design as design
from check_exit_campaign import account

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def digest(path: Path) -> str:
    """機能: 実験前後の実装指紋を返す。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 人工経路だけの定義・検算・結果を有限JSONへ保存する。

    引数: path(Path)、value(object)。返り値: なし。
    """
    assert path.parent==HERE
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def paths() -> list[dict]:
    """機能: 約定を見る前に固定した四つの価格距離列を返す。

    引数: なし。返り値: 初回からの順行ATR距離・時間間隔(list[dict])。
    正距離は買いでは上昇、売りでは下落。同じ距離列を反射して使用する。
    """
    return [
        dict(id='P1',name='3ATR到達後に崩れる',step_seconds=60.,
             distance=[0.,0.,.5,1.5,2.,2.5,3.,3.,2.25,1.5,.75,0.,-1.,-2.]),
        dict(id='P2',name='3ATR到達後1.5ATRまで押し、6ATRへ再上昇',step_seconds=60.,
             distance=[0.,0.,.5,1.5,2.,2.5,3.,3.,2.25,1.5,2.,3.,4.,5.,6.,6.,5.,4.,3.,2.,1.,0.,-1.]),
        dict(id='P3',name='3ATR未到達のまま初期損切り',step_seconds=60.,
             distance=[0.,0.,.5,1.,1.25,.75,0.,-.5,-1.,-1.5]),
        dict(id='P4',name='長時間の単調順行を場末まで保有',step_seconds=600.,
             distance=[0.,0.]+[float(k)/4 for k in range(1,33)]),
    ]


def fixture(path: dict, qty: int, side: int) -> tuple:
    """機能: 同じ初回から始まる価格と完結時刻を作る。

    引数: path(dict)、qty(int)、side(int)。返り値: ready/entry(tuple[dict,dict])。
    ATR20・呼値1・初回価格1000。場末判断の次行を必ず用意する。
    """
    price=1000.+side*20.*np.asarray(path['distance'],float)
    n=len(price);times=np.arange(n,dtype=float)*path['step_seconds']
    ready=dict(time_s=times,last=price,seq=np.arange(n,dtype=np.int64),tick=1.,
        limit=float(times[-2]),session_close=float(times[-1]+600.))
    entry=dict(row=1,decision_row=0,side=side,qty=qty,price=1000.,initial_atr=20.,
        initial_risk=20.*qty,campaign=0)
    return ready,entry


def run() -> dict:
    """機能: 48人工の全会計・前行執行・反射・反例を確認して短い説明を残す。

    引数: なし。返り値: 人工数値と検算証跡(dict)。実相場ファイルは開かない。
    """
    sources=[Path(__file__),HERE/'engine_exit_campaign.py',HERE/'exit_design.py',HERE/'check_exit_campaign.py']
    original={p.relative_to(ROOT).as_posix():digest(p) for p in sources}
    specs=[s for s in design.catalog() if s['id'] in ('E00','E10','E11')]
    fixed=dict(経路=paths(),条件=specs,初回枚数=[5,10],方向=[-1,1],
        約定='指定価格・費用0・次有効行。各経路一組で再新規なし。',
        単位='円に換算しない。価格差×枚数と、初回数量×20ptを1Rとする比。',
        参照資料SHA256=original)
    fixed_path=HERE/'exit_path_counterexamples_fixed.json'
    if fixed_path.exists():assert json.loads(fixed_path.read_text(encoding='utf8'))==fixed
    else:save(fixed_path,fixed)
    rows=[];results={};prefix_count=0
    for path in paths():
        for qty in (5,10):
            for side in (-1,1):
                ready,entry=fixture(path,qty,side)
                for spec in specs:
                    actual=engine.run(ready,entry,spec);account(ready,entry,actual)
                    assert actual['closed'] and len(actual['cycles'])==1
                    assert np.all(actual['orders'][:,0]>actual['orders'][:,1])
                    assert actual['curve'][-1,6]==0
                    assert ready['time_s'][int(actual['trades'][-1,7])]<ready['session_close']
                    key=(path['id'],qty,side,spec['id']);results[key]=actual
                    net=float(actual['cycles'][0,3]);risk=entry['initial_risk']
                    rows.append(dict(path=path['id'],name=path['name'],qty=qty,side=side,id=spec['id'],
                        net_price_units=net,net_r=net/risk,
                        exit_row=int(actual['cycles'][0,2]),
                        holding_minutes=float((ready['time_s'][int(actual['cycles'][0,2])]-ready['time_s'][entry['row']])/60.),
                        orders=actual['orders'].tolist(),trades=actual['trades'].tolist(),
                        最終理由=engine.REASONS[int(actual['cycles'][0,9])]))
                    for cut in (min(7,len(ready['last'])-1),len(ready['last'])-2):
                        small={k:v[:cut].copy() if isinstance(v,np.ndarray) else v for k,v in ready.items()}
                        before=engine.run(small,entry,spec,require_complete=False)
                        for field,col in [('orders',0),('trades',7)]:
                            np.testing.assert_array_equal(before[field],actual[field][actual[field][:,col]<cut])
                        np.testing.assert_array_equal(before['curve'],actual['curve'][:cut])
                        np.testing.assert_array_equal(before['plans'],actual['plans'][:cut]);prefix_count+=1
    # ----------------------------------------
    # 優越する人工例だけを残さず、同じ固定幅が負ける反例も要求する。
    for qty in (5,10):
        for side in (-1,1):
            values={path['id']:{s['id']:results[(path['id'],qty,side,s['id'])]['cycles'][0,3] for s in specs} for path in paths()}
            assert values['P1']['E11']>values['P1']['E10']>values['P1']['E00']
            assert values['P2']['E00']>values['P2']['E11']>values['P2']['E10']
            assert len(set(values['P3'].values()))==1 and values['P3']['E00']==-20.*qty
            assert len(set(values['P4'].values()))==1
            for path in paths():
                for spec in specs:
                    a=results[(path['id'],qty,side,spec['id'])]
                    b=results[(path['id'],qty,-side,spec['id'])]
                    np.testing.assert_array_equal(a['trades'][:,[3,6,7,9,10]],b['trades'][:,[3,6,7,9,10]])
                    np.testing.assert_array_equal(a['curve'][:,0],b['curve'][:,0])
                    reflected=a['orders'].copy();reflected[:,3]*=-1;reflected[:,5]=2000-reflected[:,5]
                    np.testing.assert_array_equal(reflected,b['orders'])
    assert all(digest(ROOT/name)==sha for name,sha in original.items())
    proof=dict(全合格=True,人工入力条件数=len(rows),接頭部検査数=prefix_count,
        売買反射組数=24,四経路の予定した優劣と同値を確認=True,
        全行会計と前行発注と場内返済=True,経済コア前後不変=True,
        実相場読取数=0,新Night使用=False,API取得数=0,結果=rows,
        参照資料SHA256={**original,fixed_path.relative_to(ROOT).as_posix():digest(fixed_path)})
    save(HERE/'出口短縮の人工反例.json',proof)
    selected={(r['path'],r['qty'],r['id']):r for r in rows if r['side']==1}
    lines=['# 出口短縮が有利な経路と不利な経路','',
        'E10は全経路でE00に勝つ出口ではない。3ATR順行後に崩れる経路では利益を守るが、押しを耐えれば再び伸びる経路では早く返済して利益を逃す。以下は保存済みの同じ出口実装へ与えた人工経路で、実相場の追加検証ではない。','',
        '初回価格1000、初期ATR20、呼値1。E00は始動1.5ATR・追跡幅3ATR。E10/E11は3ATR順行後に幅1.5/0.75ATRへ短縮する。3方式とも2ATRで整数枚数の半分を利確し、初期予算・360分・場末返済を維持した。次行執行・指定価格・費用0。','',
        '| 人工経路 | 初回枚数 | E00収支 | E10収支 | E11収支 |',
        '|---|---:|---:|---:|---:|']
    for path in paths():
        for qty in (5,10):
            vals=[selected[(path['id'],qty,s['id'])]['net_r'] for s in specs]
            lines.append(f"| {path['name']} | {qty} | {vals[0]:.3f}R | {vals[1]:.3f}R | {vals[2]:.3f}R |")
    lines+=['','1R＝初回枚数×20pt。金額ではなく同一初回予算に対する比。5枚は2枚を利確して3枚残すため、10枚を5枚ずつ分ける場合と比率が異なる。全行会計、約定の前行根拠、場内全返済を48入力で確認し、買い・売りの反射で全損益が一致した。','',
        '- **崩れる経路**：3ATR到達後、E11は2.25ATR、E10は1.5ATR、E00は0ATRの順行位置で残玉を返済した。狭い幅ほど、それまでの含み利益を多く残す。',
        '- **押しから伸び直す経路**：3ATRから1.5ATRまで押した時点でE10/E11は終了する。E00は保有を続け、6ATR順行後の戻りで3ATRの位置から返済する。この一組ではE10/E11が劣る。同期運用では元A0の新しい準備まで再参加しないため、再上昇部分を都合よく取り直さない。',
        '- **未到達損切り**：最大順行1.25ATRから−1ATRへ反転。短縮が始まらず全方式−1Rで同じ。短縮規則は初期方向判断の誤りを直さない。',
        '- **長い単調下降のショート**：初回から320分間、8ATRまで一度も逆行せず下降し、場末予約の次行で返済。買いの単調上昇も同値。3方式とも同じ部分利確と場末返済になり、狭い幅だけを理由にトレンドを途中で切ることはない。','',
        'これは保護と取り逃しの交換が実装にも存在することの反証であり、四経路の出現確率や将来期待利益を測っていない。どの幅を採用するかをこの人工結果で最適化していない。旧13セッションの改善は別の観測事実として残る。','',
        '資料：[全48結果・注文](出口短縮の人工反例.json)、[人工経路の事前固定](exit_path_counterexamples_fixed.json)、[実行コード](exit_path_counterexamples.py)、[元の出口条件](exit_design.py)。']
    (HERE/'出口短縮の人工反例.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print('人工48件・接頭部96件・反射24組、保護例と早期返済の反例を確認。',flush=True)
    return proof


if __name__=='__main__':run()
