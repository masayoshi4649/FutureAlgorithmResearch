"""急傾斜の認識と、その後の順行・実売買を分離して検証する。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
from numba import njit

import steep_signals


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00063_短時間の急傾斜を入口にする検証'
sys.path.insert(0,str(HERE.parent/'wave_v65'))
import replay as exits

PRIMARY=('ACCEL_H03_V020','STRAIGHT_H05_V020','BREAK_H03_V020')
EXIT_CONFIGS=(dict(id='狭幅',stop=.001,arm=.0011,trail=.0001,floor=.001),
              dict(id='広幅',stop=.001,arm=.0015,trail=.0005,floor=.001))


def digest(path: Path) -> str:
    """機能: 入力と実装の固定に用いるSHA256を計算する。

    引数: path(Path)。返り値: ダイジェスト(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path,value: object) -> None:
    """機能: 非有限値を含めず日本語UTF-8でJSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


@njit(cache=True)
def first_touch(bid: np.ndarray,ask: np.ndarray,entry_i: int,side: int,width: float) -> tuple:
    """機能: 実建値から同幅の順行・逆行のどちらへ先に届くかを採点する。

    引数: bid/ask(ndarray)、entry_i/side(int)、width(float)。
    返り値: 先着方向と原板行(tuple[int,int])。未到達は0と-1。
    事後採点専用で売買の判断には渡さない。
    """
    anchor=ask[entry_i] if side>0 else bid[entry_i]
    for i in range(entry_i,len(bid)):
        price=bid[i] if side>0 else ask[i]
        gain=side*(price-anchor)
        if gain>=width-1.e-9:
            return 1,i
        if gain<=-width+1.e-9:
            return -1,i
    return 0,-1


def score(ready: dict,q: dict,meta: dict,suffix: dict) -> dict:
    """機能: 検知の後の最大順行と対称先着を同じ保存場末まで採点する。

    引数: ready/q/meta/suffix(dict)。返り値: 一入口の事後採点(dict)。
    検知前に既に進んだ価格幅は加点しない。
    """
    i,side=int(meta['i']),int(meta['side'])
    e=i+1
    anchor=float(q['ask'][e] if side>0 else q['bid'][e])
    mfe=max(0.,suffix['bid_max'][e]-anchor) if side>0 else max(0.,anchor-suffix['ask_min'][e])
    mae=max(0.,anchor-suffix['bid_min'][e]) if side>0 else max(0.,suffix['ask_max'][e]-anchor)
    labels={}
    for f in (.0005,.001,.002):
        direction,index=first_touch(q['bid'],q['ask'],e,side,anchor*f)
        labels[f'{f*100:.2f}']=dict(target=bool(mfe>=anchor*f-1.e-9),first=int(direction),first_i=int(index))
    return dict(session=ready['session'],symbol=ready['symbol'],i=i,seq=int(ready['seq'][i]),side=side,
        time_s=float(ready['time_s'][i]),entry_i=e,entry_seq=int(ready['seq'][e]),entry_price=anchor,
        slope=float(meta['slope']),er=float(meta['er']),previous_slope=float(meta['previous_slope']) if np.isfinite(meta['previous_slope']) else None,
        bar_close=float(meta['close']),decision_mid=float(meta['mid']),mfe=float(mfe),mae=float(mae),
        mfe_fraction=float(mfe/anchor),mae_fraction=float(mae/anchor),labels=labels)


def score_summary(rows: list[dict]) -> dict:
    """機能: 全ての約定可能な検知を分母として将来到達と先着を集計する。

    引数: rows(list[dict])。返り値: 件数、中央値、幅別確率(dict)。
    同じ入口系統内の複数検知は独立な市場標本とはみなさない。
    """
    n=len(rows)
    result=dict(n=n,mfe_median=float(np.median([r['mfe'] for r in rows])) if n else None,
        mfe_fraction_median=float(np.median([r['mfe_fraction'] for r in rows])) if n else None,labels={})
    for label in ('0.05','0.10','0.20'):
        targets=sum(r['labels'][label]['target'] for r in rows)
        first=sum(r['labels'][label]['first']==1 for r in rows)
        opposite=sum(r['labels'][label]['first']==-1 for r in rows)
        result['labels'][label]=dict(targets=targets,target_rate=targets/n if n else None,first=first,
            opposite=opposite,unresolved=n-first-opposite,first_rate=first/n if n else None)
    return result


def block_of(session: str) -> str:
    """機能: 日付で事前固定した三つの連続期間へ分類する。

    引数: session(str)。返り値: 期間区分(str)。
    """
    day=session[:10]
    return '前半10場' if day<'2026-09-28' else '中間10場' if day<'2026-10-05' else '後半5場'


def summarize(rows: list[dict]) -> dict:
    """機能: 費用後会計に初期損切り幅基準の単位Rを加える。

    引数: rows(list[dict])。返り値: 金額・枚数・保有時間・R(dict)。
    """
    result=exits.summarize(rows)
    rs=[r['net']/(r['entry_price']*.001*r['qty']*r['value']) for r in rows]
    result['net_R']=sum(rs)
    result['mean_R']=float(np.mean(rs)) if rs else None
    return result


def prepare() -> None:
    """機能: 48入口と192売買条件を損益再生前に固定して入力を準備する。

    引数: なし。返り値: なし(None)。現在APIへアクセスしない。
    """
    assert not (HERE/'実行前固定.json').exists()
    OUT.mkdir(parents=True,exist_ok=True)
    configs=steep_signals.definitions()
    fixed=dict(時刻=datetime.now(timezone.utc).isoformat(),入口=configs,主入口=PRIMARY,出口=EXIT_CONFIGS,
        方向=['順方向','逆方向は反証対照'],条件数=len(configs)*len(EXIT_CONFIGS)*2,
        検知='完全1分グリッドで直前確定足まで。次分最初の同銘柄原板行へ公開。必要全足の実観測、公開遅延/最終値経過60秒以内。',
        初発='各入口系統の全条件符号状態が0か逆方向から切り替わった時だけ。フィルタ点滅で再検知し得る。',
        基準='速度は100*log(終値/窓分前終値)/窓分、毎分百分率。ER>=.7、加速は直前同区間の方向成分が現在の1/2以下。',
        突破='加速条件に加え、現在足除外の直前窓高安を1ラージ呼値以上超えた終値。',
        幅='新規次行約定価格を基準。損切り0.1%、初期保護線0.1%、出口2種類。',
        枚数=dict(NK225micro=20,TOPIXmini=10),休止='返済後10分。全力初回のみ、追加/両建てなし。',
        締切='新規Day15:30/Night05:45未満、返済判断15:34/05:49以後の最初の行→次行。場内完結。',
        費用='次行気配約定、NKmicro片道20枚220円、TOPIXmini10枚418円。小商品実板/食い込み/通信遅延は未再現。',
        採点='検知後の実建値と返済気配から保存場末の最大順行、対称0.05/0.1/0.2%先着。未来は採点専用。',
        選択='前半10場で各商品10決済以上ある順方向条件の最小商品平均Rが最大の1条件を選び、中間10/後半5を分離。全25場は以前にも既知。',
        現在='主入口3×出口2だけを固定し、必要なら現在セッションを最後に一度検証。途中の現在データで調整しない。',
        SHA={str(p):digest(p) for p in (Path(__file__),HERE/'steep_signals.py',Path(exits.__file__),exits.INPUTS,exits.QUOTES)})
    save(HERE/'実行前固定.json',fixed)
    inputs,quotes=[pickle.loads(p.read_bytes()) for p in (exits.INPUTS,exits.QUOTES)]
    frames={};candidates={};metadata={}
    for key,ready in inputs.items():
        frame=steep_signals.build(ready,quotes[key])
        frames[key]=frame;candidates[key]={};metadata[key]={}
        for cfg in configs:
            candidates[key][cfg['id']]=steep_signals.candidates(frame,cfg)
            metadata[key][cfg['id']]=steep_signals.metadata(frame,cfg).to_dict('records')
    for name,data in (('公開特徴.pkl',frames),('入口候補.pkl',candidates),('入口詳細.pkl',metadata)):
        (HERE/name).write_bytes(pickle.dumps(data,protocol=pickle.HIGHEST_PROTOCOL))
    save(HERE/'入力準備.json',dict(口座数=len(inputs),公開足数=sum(len(f) for f in frames.values()),
        条件数=len(configs),候補数=sum(len(c) for a in candidates.values() for c in a.values()),
        SHA={name:digest(HERE/name) for name in ('公開特徴.pkl','入口候補.pkl','入口詳細.pkl')}))
    print('192条件を損益前に固定しました')


def run() -> None:
    """機能: 全入口の方向採点と192条件の原板次行売買を再生する。

    引数: なし。返り値: なし(None)。固定条件・既存入力を変更しない。
    """
    assert not (HERE/'結果.json').exists()
    fixed=json.loads((HERE/'実行前固定.json').read_text(encoding='utf-8'))
    for path,sha in fixed['SHA'].items():
        assert digest(Path(path))==sha
    prepared=json.loads((HERE/'入力準備.json').read_text(encoding='utf-8'))
    for name,sha in prepared['SHA'].items():
        assert digest(HERE/name)==sha
    inputs,quotes=[pickle.loads(p.read_bytes()) for p in (exits.INPUTS,exits.QUOTES)]
    candidates,metadata=[pickle.loads((HERE/name).read_bytes()) for name in ('入口候補.pkl','入口詳細.pkl')]
    scores={};scored_rows={};score_results=[]
    for key,ready in inputs.items():
        q=quotes[key]
        suffix={f'{name}_{kind}':op(q[name][::-1])[::-1] for name in ('bid','ask')
            for kind,op in (('max',np.maximum.accumulate),('min',np.minimum.accumulate))}
        for cfg in fixed['入口']:
            rows=[]
            for m in metadata[key][cfg['id']]:
                i,side=int(m['i']),int(m['side'])
                if ready['time_s'][i]>=ready['limit']-300. or ready['time_s'][i+1]>=ready['limit']-300.:
                    continue
                cache_key=(*key,i,side)
                if cache_key not in scores:
                    scores[cache_key]=score(ready,q,m,suffix)
                row=scores[cache_key].copy()
                for name in ('slope','er','previous_slope'):
                    row[name]=float(m[name]) if np.isfinite(m[name]) else None
                rows.append(row)
            scored_rows.setdefault(cfg['id'],[]).extend(rows)
    for cfg in fixed['入口']:
        rows=scored_rows[cfg['id']]
        score_results.append(dict(config=cfg,summary={s:score_summary([r for r in rows if r['symbol']==s]) for s in ('TOPIX','NK225')},rows=rows))
    save(HERE/'入口採点.json',dict(methods=score_results,採点='実建値起点、検知後から保存通常区間末。保有状態とは分離。',
        重複除外キャッシュ数=len(scores),未来を入口へ渡さない=True))
    # ----------------------------------------
    # 正逆方向の取引状態は互いに独立。逆方向の成績から入口を変更しない。
    methods=[];cache={}
    for cfg in fixed['入口']:
        for ecfg in fixed['出口']:
            for mirror in (False,True):
                accounts=[];all_rows=[]
                for key,ready in sorted(inputs.items()):
                    q=quotes[key];rows=[]
                    prev_exit,next_entry=-1,-np.inf
                    signals=candidates[key][cfg['id']]
                    gates=dict(candidates=len(signals),accepted=0,scheduled=0,holding=0,cooldown=0,cutoff=0,expired=0)
                    for signal in signals:
                        i,side=int(signal[0]),int(signal[1])*(-1 if mirror else 1)
                        if i<=prev_exit:
                            gates['holding']+=1
                        elif ready['time_s'][i]>=ready['limit']-300.:
                            gates['cutoff']+=1
                        elif ready['time_s'][i]<next_entry:
                            gates['cooldown']+=1
                        else:
                            gates['scheduled']+=1
                            if ready['time_s'][i+1]>=ready['limit']-300.:
                                gates['expired']+=1
                                continue
                            ck=(*key,i,side,ecfg['id'])
                            if ck not in cache:
                                cache[ck]=exits.one(ready,q,i,side,ecfg)
                            row=cache[ck].copy()
                            rows.append(row)
                            gates['accepted']+=1
                            prev_exit,next_entry=row['exit_i'],row['exit_time']+600.
                    assert gates['scheduled']==gates['accepted']+gates['expired']
                    assert sum(gates[k] for k in ('accepted','holding','cooldown','cutoff','expired'))==len(signals)
                    all_rows.extend(rows)
                    accounts.append(dict(session=key[0],symbol=key[1],block=block_of(key[0]),**summarize(rows),gates=gates))
                method_id=cfg['id']+'_'+ecfg['id']+('_逆' if mirror else '_順')
                methods.append(dict(id=method_id,entry=cfg,exit=ecfg,mirror=mirror,primary=cfg['id'] in PRIMARY and not mirror,
                    accounts=accounts,rows=all_rows,summary={s:summarize([r for r in all_rows if r['symbol']==s]) for s in ('TOPIX','NK225')},
                    blocks={b:{s:summarize([r for r in all_rows if r['symbol']==s and block_of(r['session'])==b]) for s in ('TOPIX','NK225')}
                        for b in ('前半10場','中間10場','後半5場')}))
                if not mirror:
                    print(method_id,[(s,m['net'],m['wins'],m['trades']) for s,m in methods[-1]['summary'].items()])
    eligible=[m for m in methods if not m['mirror'] and all(m['blocks']['前半10場'][s]['trades']>=10 for s in ('TOPIX','NK225'))]
    selected=max(eligible,key=lambda m:min(m['blocks']['前半10場'][s]['mean_R'] for s in ('TOPIX','NK225'))) if eligible else None
    save(HERE/'時系列選択.json',dict(選択条件=selected['id'] if selected else None,適格条件数=len(eligible),
        基準='前半10場だけで両銘柄10決済以上、両銘柄のうち低い平均Rが最大。',
        選択時に中間後半を使わない=True,未見性='全25場は以前の調査では既知、真の未見データではない。',
        selected=selected))
    save(HERE/'結果.json',dict(methods=methods,主入口=PRIMARY,セッション数=len(inputs)//2,口座数=len(inputs),
        条件数=len(methods),固定SHA=digest(HERE/'実行前固定.json')))
    print('急傾斜192条件の再生を完了しました')


if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('prepare','run')
    prepare() if sys.argv[1]=='prepare' else run()
