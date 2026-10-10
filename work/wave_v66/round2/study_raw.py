"""確定５秒足で１〜２分の急傾斜を早く認識する追加検証。"""

from datetime import datetime, timezone
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import study
import raw_signals

PRIMARY=('RAW_ACCEL_S060_V050','RAW_STRAIGHT_S060_V050')
EXIT_CONFIGS=(*study.EXIT_CONFIGS,dict(id='短期幅',stop=.0003,arm=.0005,trail=.0002,floor=.0003))


def summarize(rows: list[dict]) -> dict:
    """機能: 初期損切り幅が違う条件も同じ単位Rで会計する。

    引数: rows(list[dict])。返り値: 全建玉決済の会計(dict)。
    """
    result=study.exits.summarize(rows)
    rs=[r['net']/(r['entry_price']*r['initial_stop_fraction']*r['qty']*r['value']) for r in rows]
    result['net_R']=sum(rs)
    result['mean_R']=float(np.mean(rs)) if rs else None
    return result


def prepare() -> None:
    """機能: 生板の５秒確定足の144条件を追加損益計算前に固定する。

    引数: なし。返り値: なし(None)。第１段階の実装・結果を変更しない。
    """
    assert not (HERE/'実行前固定.json').exists()
    configs=raw_signals.definitions()
    fixed=dict(時刻=datetime.now(timezone.utc).isoformat(),理由='1分確定足での入口が遅い仮説を検査。生板価格を5秒グリッドで確定後に公開。',
        入口=configs,主入口=PRIMARY,出口=EXIT_CONFIGS,条件数=len(configs)*len(EXIT_CONFIGS)*2,
        実観測='受信時計ではなく最終約定時計。全必要5秒足の観測を要求し欠測で発火しない。',
        短期出口='損切り0.03%、順行0.05%で開始、追跡幅0.02%、初期保護線0.03%。通常2出口は前段と同じ。',
        共通仕様='次の有効原板行で売買気配約定、NKmicro20枚/TOPIXmini10枚、両側手数料、10分休止、当場返済。',
        採点='検知後の実建値から場内最大順行と0.03/0.05/0.1/0.2%対称先着。未来価格は採点専用。',
        選択='今回追加は主入口2を固定。全体順位は既知全場の探索結果と表示し、将来検証済みとは扱わない。',
        SHA={str(p):study.digest(p) for p in (Path(__file__),HERE/'raw_signals.py',HERE.parent/'study.py',
                Path(study.exits.__file__),study.exits.INPUTS,study.exits.QUOTES,HERE.parent/'結果.json')})
    study.save(HERE/'実行前固定.json',fixed)
    inputs,quotes=[pickle.loads(p.read_bytes()) for p in (study.exits.INPUTS,study.exits.QUOTES)]
    frames={};candidates={};metadata={}
    for key,ready in inputs.items():
        frame=raw_signals.build(ready,quotes[key])
        frames[key]=frame;candidates[key]={};metadata[key]={}
        for cfg in configs:
            candidates[key][cfg['id']]=raw_signals.candidates(frame,cfg)
            metadata[key][cfg['id']]=raw_signals.metadata(frame,cfg).to_dict('records')
    for name,data in (('公開特徴.pkl',frames),('入口候補.pkl',candidates),('入口詳細.pkl',metadata)):
        (HERE/name).write_bytes(pickle.dumps(data,protocol=pickle.HIGHEST_PROTOCOL))
    study.save(HERE/'入力準備.json',dict(口座数=len(inputs),候補数=sum(len(c) for a in candidates.values() for c in a.values()),
        SHA={name:study.digest(HERE/name) for name in ('公開特徴.pkl','入口候補.pkl','入口詳細.pkl')}))
    print('追加144条件を固定しました')


def run() -> None:
    """機能: ５秒確定足の方向採点と144条件の実行可能売買を計算する。

    引数: なし。返り値: なし(None)。現在セッションでの再調整はしない。
    """
    assert not (HERE/'結果.json').exists()
    fixed=json.loads((HERE/'実行前固定.json').read_text(encoding='utf-8'))
    for path,sha in fixed['SHA'].items():
        assert study.digest(Path(path))==sha
    inputs,quotes=[pickle.loads(p.read_bytes()) for p in (study.exits.INPUTS,study.exits.QUOTES)]
    candidates,metadata=[pickle.loads((HERE/name).read_bytes()) for name in ('入口候補.pkl','入口詳細.pkl')]
    prepared=json.loads((HERE/'入力準備.json').read_text(encoding='utf-8'))
    for name,sha in prepared['SHA'].items():
        assert study.digest(HERE/name)==sha
    scores={};scored_rows={}
    for key,ready in inputs.items():
        q=quotes[key]
        suffix={f'{name}_{kind}':op(q[name][::-1])[::-1] for name in ('bid','ask') for kind,op in (('max',np.maximum.accumulate),('min',np.minimum.accumulate))}
        for cfg in fixed['入口']:
            rows=[]
            for m in metadata[key][cfg['id']]:
                i,side=int(m['i']),int(m['side'])
                if ready['time_s'][i]>=ready['limit']-300. or ready['time_s'][i+1]>=ready['limit']-300.:
                    continue
                ck=(*key,i,side)
                if ck not in scores:
                    row=study.score(ready,q,m,suffix)
                    first,at=study.first_touch(q['bid'],q['ask'],i+1,side,row['entry_price']*.0003)
                    row['labels']['0.03']=dict(target=row['mfe']>=row['entry_price']*.0003-1.e-9,first=int(first),first_i=int(at))
                    scores[ck]=row
                row=scores[ck].copy()
                for name in ('slope','er','previous_slope'):
                    row[name]=float(m[name]) if np.isfinite(m[name]) else None
                rows.append(row)
            scored_rows.setdefault(cfg['id'],[]).extend(rows)
    score_methods=[]
    for cfg in fixed['入口']:
        rows=scored_rows[cfg['id']]
        summaries={}
        for symbol in ('TOPIX','NK225'):
            chosen=[r for r in rows if r['symbol']==symbol]
            a=study.score_summary(chosen);n=len(chosen)
            a['labels']['0.03']=dict(targets=sum(r['labels']['0.03']['target'] for r in chosen),
                target_rate=sum(r['labels']['0.03']['target'] for r in chosen)/n if n else None,
                first=sum(r['labels']['0.03']['first']==1 for r in chosen),opposite=sum(r['labels']['0.03']['first']==-1 for r in chosen),
                unresolved=sum(r['labels']['0.03']['first']==0 for r in chosen),
                first_rate=sum(r['labels']['0.03']['first']==1 for r in chosen)/n if n else None)
            summaries[symbol]=a
        score_methods.append(dict(config=cfg,summary=summaries,rows=rows))
    study.save(HERE/'入口採点.json',dict(methods=score_methods,重複除外キャッシュ数=len(scores)))
    # ----------------------------------------
    # 細かい入口も、保有と休止を通した実口座だけを主成績にする。
    methods=[];cache={}
    for cfg in fixed['入口']:
        for ecfg in fixed['出口']:
            for mirror in (False,True):
                accounts=[];all_rows=[]
                for key,ready in sorted(inputs.items()):
                    q=quotes[key];rows=[];prev_exit=-1;next_entry=-np.inf
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
                                row=study.exits.one(ready,q,i,side,ecfg)
                                row['initial_stop_fraction']=ecfg['stop']
                                cache[ck]=row
                            row=cache[ck].copy();rows.append(row)
                            gates['accepted']+=1
                            prev_exit,next_entry=row['exit_i'],row['exit_time']+600.
                    assert gates['scheduled']==gates['accepted']+gates['expired']
                    assert sum(gates[k] for k in ('accepted','holding','cooldown','cutoff','expired'))==len(signals)
                    all_rows.extend(rows)
                    accounts.append(dict(session=key[0],symbol=key[1],block=study.block_of(key[0]),**summarize(rows),gates=gates))
                method=dict(id=cfg['id']+'_'+ecfg['id']+('_逆' if mirror else '_順'),entry=cfg,exit=ecfg,
                    mirror=mirror,primary=cfg['id'] in PRIMARY and not mirror,accounts=accounts,rows=all_rows,
                    summary={s:summarize([r for r in all_rows if r['symbol']==s]) for s in ('TOPIX','NK225')},
                    blocks={b:{s:summarize([r for r in all_rows if r['symbol']==s and study.block_of(r['session'])==b]) for s in ('TOPIX','NK225')}
                        for b in ('前半10場','中間10場','後半5場')})
                methods.append(method)
                if method['primary']:
                    print(method['id'],[(s,a['net'],a['wins'],a['trades']) for s,a in method['summary'].items()])
    study.save(HERE/'結果.json',dict(methods=methods,主入口=PRIMARY,セッション数=25,口座数=50,条件数=len(methods),固定SHA=study.digest(HERE/'実行前固定.json')))
    print('生板５秒確定足の追加144条件を完了しました')


if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('prepare','run')
    prepare() if sys.argv[1]=='prepare' else run()
