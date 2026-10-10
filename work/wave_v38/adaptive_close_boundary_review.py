"""正の注文遅延と旧会計の場末検査の不整合を、時刻と人工価格だけで確認する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import socket
from zoneinfo import ZoneInfo

import numpy as np

import adaptive_causality_audit as common

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def stamp(value: float) -> str:
    """機能: 時刻を日本時間で表記する。

    引数: value (float)。返り値: ISO表記 (str)。
    """
    return datetime.fromtimestamp(float(value),ZoneInfo('Asia/Tokyo')).isoformat()


def calculate(times: list[float], delay: float) -> tuple:
    """機能: 場末近傍に密な観測を持つ人工A0だけを再生する。

    引数: times (list[float])、delay (float)。返り値: ready・影・実 (tuple[dict,dict,dict])。
    """
    ready,state,config,*_ = common.fixture([100.]+[102.]*(len(times)-3))
    assert len(state)==len(times)
    ready['time_s']=np.array(times,float)
    ready['session_close']=10600.
    zero=np.zeros(len(state),np.int8);source=np.full(len(state),-1,np.int64)
    policy=next(s['policy'] for s in common.design.catalog() if s['policy']['id']=='A0')
    shadow=common.engine.make_shadow(ready,state,config,min_delay_seconds=delay)
    actual=common.engine.run(ready,state,config,zero,source,zero,source,policy,
        min_delay_seconds=delay,budget_enabled=False)
    for name in common.engine.FIELDS:
        common.exact(shadow[name],actual[name],name)
    return ready,shadow,actual


def old_next_observation(ready: dict, result: dict) -> bool:
    """機能: 旧会計140行の次観測以降flatという述語だけを再現する。

    引数: ready/result (dict)。返り値: 旧述語の成否 (bool)。
    """
    at_limit=np.flatnonzero(ready['time_s']>=ready['limit'])
    if len(at_limit)<=1:
        return True
    after=int(at_limit[0])+1
    return not bool((result['curve'][after:,2]+result['curve'][after:,3]).any())


def inspect(ready: dict, result: dict, delay: float) -> dict:
    """機能: 当時公開の注文元と真の終場前の返済を、保存経済値を読まず確認する。

    引数: ready/result (dict)、delay (float)。返り値: 境界証跡 (dict)。
    """
    orders=result['orders'];times=ready['time_s'];close=ready['session_close']
    assert len(orders)>0
    assert np.all(times[orders[:,0].astype(int)]<close)
    assert result['stats'][9]==0
    for o in orders:
        row,source=int(o[0]),int(o[1])
        assert 0<=source<row
        assert times[source]+delay<=times[row]+1e-8
    exits=orders[orders[:,6]==9]
    assert len(exits)==1
    event=exits[0];row,source=int(event[0]),int(event[1])
    assert times[source]>=ready['limit'] and times[row]>=times[source]+delay-1e-8
    return dict(遅延秒=delay,判断行=source,判断時刻=float(times[source]),返済行=row,
        返済時刻=float(times[row]),終場時刻=close,最終残玉=0,
        旧次観測flat条件=old_next_observation(ready,result),
        旧limit加算300条件=bool(np.all(times[orders[:,0].astype(int)]<=ready['limit']+300)),
        真の終場未満=True,当行事後約定なし=True,元行から指定遅延を満たす=True)


def main() -> None:
    """機能: 全26入力の境界と人工例を保存し、改訂に必要な最低証跡を列挙する。

    引数: なし。返り値: なし (None)。売買コード・既存固定を変更しない。
    """
    socket.socket.connect=common.runner.reject_network
    socket.create_connection=common.runner.reject_network
    sources=(Path(__file__),HERE/'engine_shadow_plan.py',HERE/'engine_partial_restore.py',
        HERE/'adaptive_design_fixed.json',HERE/'エンジンの実装契約.md',HERE/'adaptive_cash_reconstruction.py',
        HERE/'adaptive_causality_fixed.json',HERE/'adaptive_wave_fixed.json',
        HERE.parent/'wave_v23/inputs.pkl')
    before={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    cash_source=(HERE/'adaptive_cash_reconstruction.py').read_text(encoding='utf-8')
    assert "times[row] <= ready['limit'] + 300" in cash_source
    assert "after = int(at_limit[0]) + 1" in cash_source
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    boundaries=[]
    for key,r in sorted(inputs.items()):
        limit=r['limit'];close=float(r.get('session_close',limit+600.));times=r['time_s']
        assert np.isfinite(times).all() and np.all(np.diff(times)>=0)
        assert times[-1]<limit+300<close and np.isfinite(r['last']).all()
        boundaries.append(dict(session=key[0],symbol=key[1],開始=stamp(r['start']),
            安全返済判断=stamp(limit),現契約の終場=stamp(close),最終観測=stamp(times[-1]),
            安全返済判断以後行数=int(np.sum(times>=limit)),全行終場前=True,
            全行旧監視末尾未満=True,価格全有限=True,session_close明示='session_close' in r))
    assert len(boundaries)==26

    # ----------------------------------------
    # limit以降に複数行が来ても、δが経過するまで約定させないことを確かめる。
    dense=[0.,10.,20.,9999.,10000.,10000.,10000.1,10001.,10005.,10015.,10016.,10030.]
    cases=[]
    for delay in (0.,1.,5.,15.):
        r,shadow,actual=calculate(dense,delay)
        record=inspect(r,actual,delay)
        assert record['旧次観測flat条件']==(delay==0.)
        assert record['返済時刻']=={0.:10000.,1.:10001.,5.:10005.,15.:10015.}[delay]
        # 同時刻の途中で切断し、既発生の影/実記録が変わらないか独立に確かめる。
        cut=6
        short_times=dense[:cut]
        sr,ss,sa=calculate(short_times,delay)
        common.prefix(actual,sa,cut)
        record['同時刻prefix一致']=True
        cases.append(record)
    # 300秒を越えても、現在の固定契約上は終場前の有効観測なら返済可能。
    r,shadow,actual=calculate([0.,10.,20.,9999.,10000.,10599.],15.)
    late=inspect(r,actual,15.)
    assert late['旧limit加算300条件'] is False and late['真の終場未満']
    cases.append(late)
    rejected=0
    for ending in (10600.,10601.):
        try:
            calculate([0.,10.,20.,9999.,10000.,ending],15.)
        except ValueError as exc:
            assert '終場' in str(exc)
            rejected+=1
        else:
            raise AssertionError('終場以後の架空返済を受理した')
    # 終場そのものをまだ含まない途中列は、エンジンだけで完了と呼ばない。
    r,shadow,actual=calculate([0.,10.,20.,9999.,10000.,10000.1],15.)
    assert actual['stats'][9]>0
    incomplete=dict(終了時刻=float(r['time_s'][-1]),最終残玉=int(actual['stats'][9]),
        エンジンが途中在庫を保持=True,全期間会計で最終残玉0検査が必要=True)
    for name,sha in before.items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
    result=dict(全合格=True,結論='旧会計の次観測flat条件は正遅延と不一致。limit+300も現在の終場契約と別境界。',
        入力境界数=26,入力境界=boundaries,人工適合数=len(cases),人工適合=cases,
        終場以後拒否数=rejected,途中入力の注意=incomplete,
        現エンジンの真の跨ぎ又は未来参照の具体例検出=False,
        限界='実データの全条件は未再計算。原本は旧監視末尾前で終わるため、完了した全26口座の最終残玉0と全注文時刻の独立検査が必須。',
        新実相場再生=False,新成績による条件選択=False,既存コード変更=False,既存固定変更=False,
        現在保存物使用=False,API取得数=0,SHA256=before,
        旧検査本文=["times[row] >= ready['start'] and times[row] <= ready['limit'] + 300",
            "at_limit = np.flatnonzero(times >= ready['limit']); after = int(at_limit[0]) + 1",
            "assert not (longs[after:] + shorts[after:]).any()"],
        改訂最低証跡=[
            '停止trace・旧試行ID集合・全保存ファイルSHAを退避前に固定する。',
            '旧コード・固定・起動証跡・旧成果を残し、旧参照パスから退避先への写像を保存する。',
            '独立会計の変更を境界2検査だけに限定し、AST差と売買/入力/設計/採否不変を記録する。',
            '密な場末観測・同時刻・遅延0/1/5/15・終場等号/以後拒否・途中残玉の人工検査を含める。',
            '新会計fixed・探索fixed・起動証跡を新SHAへ再固定し、旧固定の継承を別改訂manifestで結ぶ。',
            'cash非依存の因果/波fixedは不変で保持し、全974の新探索SHAと新成果集合へ監査headerを結ぶ。',
            '全974を同じ新試行で再計算し、旧保存158等の全IDの台帳fingerprintと全経済項目一致を確認する。',
            '非経済の経過秒・新探索SHA等だけを事前列挙して比較対象から除き、閾値や対象を変更しない。',
            '全974の独立会計、3918因果入力、7792波、原本78前後SHA、欠落重複を最終guardで結合する。'])
    (HERE/'adaptive_close_boundary_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (HERE/'adaptive_close_boundary_review.md').write_text('''# 場末境界の独立確認

停止した「安全返済判断の次観測以降は必ず残玉0」という検査は、遅延0の旧契約である。今回の固定契約では、15:35／05:50以後に作った返済判断からδ秒を経て、次以降の有効観測で返済する。同時刻や短い間隔の観測が続けば、その間に保有しているのが正しい。

人工データで、δ=1・5・15秒は旧検査だけが不合格となり、約定元より後・指定秒数後・終場前の返済を満たすことを確認した。旧会計63行の `limit+300` も別の旧境界であり、現在固定済みの終場 `limit+600` 未満とは一致しない。終場等号とそれ以後の架空返済はエンジンが拒否した。今回の読取と人工検査では、真の場跨ぎや未来参照を示す具体例は見つからなかった。

全26入力は安全返済判断後にも観測を持ち、最終行は旧監視末尾15:40／05:55より前である。したがって、この保存データに終場15:45／06:00以後の行はない。ただし、データが途中で止まればエンジンは途中在庫を返すため、全期間の会計で最終残玉0を要求する検査は必ず残す。全974の場内完結を、今回の時刻確認だけで証明したとはしない。

修正する場合は、旧試行の停止trace、ID集合、全保存SHA、コードと固定を退避し、旧参照先を追跡できる写像を残す。変更は境界2検査に限定してAST差を保存する。密な場末観測と同時刻、各遅延、終場等号、途中残玉の人工検査を追加し、新会計・探索・起動固定を改訂manifestで結ぶ。

因果・波の固定は会計モジュールへ依存しないため、そのまま保持できる。全974を一つの新試行で再計算し、新探索SHAへ全独立監査を接続する。旧保存済み全IDは台帳fingerprintと全経済項目の同一性を確認する。比較から外すのは、あらかじめ列挙した経過秒や新探索SHA等の非経済メタデータだけとする。新成績を用いた条件選択・閾値変更は行わない。

根拠と人工注文時刻は `adaptive_close_boundary_review.json`。新実相場の再生・損益順位の読取・既存コードの変更は行っていない。
''',encoding='utf-8')
    print('26入力の境界、人工5適合、終場以後2拒否、途中在庫を確認。既存コード/固定は不変。')


if __name__=='__main__':
    main()
