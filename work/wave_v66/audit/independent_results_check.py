"""192条件の売買と全入口の将来経路を独立した分割価格演算で確認する。"""

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]


def chunk_trace(times,bid,ask,decision,side,config,cutoff):
    """機能: 既知の最高順行だけを持ち越す分割配列で返済条件を独立再生する。

    引数: times/bid/ask(ndarray)、decision/side(int)、config(dict)、cutoff(float)。
    返り値: 判断行・約定行・開始行・保護線・最高順行・理由(tuple)。
    """
    entry=decision+1;anchor=float(ask[entry] if side==1 else bid[entry])
    known_best=-math.inf;armed=-1;last_line=-anchor*config['stop']
    for start in range(entry,len(times),2048):
        end=min(start+2048,len(times))
        liquidation=bid[start:end] if side==1 else ask[start:end]
        gains=side*(liquidation-anchor)
        best=np.maximum(np.maximum.accumulate(gains),known_best)
        active=best>=anchor*config['arm']-1e-9
        lines=np.where(active,np.maximum(anchor*config['floor'],best-anchor*config['trail']),-anchor*config['stop'])
        triggers=np.flatnonzero((gains<=lines+1e-9)|(times[start:end]>=cutoff))
        last=int(triggers[0]) if len(triggers) else len(gains)-1
        possible=np.flatnonzero(active[:last+1])
        if armed<0 and len(possible):armed=start+int(possible[0])
        known_best=float(best[last]);last_line=float(lines[last])
        if len(triggers):
            decision_i=start+last
            reason=4 if times[decision_i]>=cutoff else 2 if active[last] else 1
            return decision_i,decision_i+1,armed,last_line,max(0.,known_best),reason
    return -1,-1,armed,last_line,max(0.,known_best),0


def first_touch(bid,ask,entry,side,width):
    """機能: 実新規価格から対称幅へ先に到達する原板行を別式で採点する。

    引数: bid/ask(ndarray)、entry/side(int)、width(float)。返り値: 先着方向・原板行(tuple)。
    """
    anchor=float(ask[entry] if side==1 else bid[entry])
    for start in range(entry,len(bid),2048):
        end=min(start+2048,len(bid));prices=bid[start:end] if side==1 else ask[start:end]
        path=side*(prices-anchor)
        positive=np.flatnonzero(path>=width-1e-9);negative=np.flatnonzero(path<=-width+1e-9)
        a=int(positive[0]) if len(positive) else len(path)
        b=int(negative[0]) if len(negative) else len(path)
        if a<b:return 1,start+a
        if b<a:return -1,start+b
    return 0,-1


def block(session):
    """機能: 固定した日付境界で期間を分類する。

    引数: session(str)。返り値: 期間名(str)。
    """
    return '前半10場' if session[:10]<'2026-09-28' else '中間10場' if session[:10]<'2026-10-05' else '後半5場'


def main():
    """機能: 全192台帳と9,600ゲート、48入口採点、期間選択を独立監査する。

    引数: なし。返り値: なし(None)。原板、条件、親実装、結果は変更しない。
    """
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location('independent_reference65',ROOT/'work/wave_v65/audit/independent_replay_check.py')
    ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
    ref.vector_trace=chunk_trace
    result=json.loads((WORK/'結果.json').read_text(encoding='utf-8'))
    scoring=json.loads((WORK/'入口採点.json').read_text(encoding='utf-8'))
    fixed=json.loads((WORK/'実行前固定.json').read_text(encoding='utf-8'))
    prepared=json.loads((WORK/'入力準備.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((WORK/'実行前固定.json').read_bytes()).hexdigest()==result['固定SHA']
    for path,sha in fixed['SHA'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    for name,sha in prepared['SHA'].items():assert hashlib.sha256((WORK/name).read_bytes()).hexdigest()==sha
    inputs=pickle.loads((ROOT/'work/wave_v60/inputs.pkl').read_bytes());quotes=pickle.loads((ROOT/'work/wave_v60/quotes.pkl').read_bytes())
    candidates=pickle.loads((WORK/'入口候補.pkl').read_bytes());metadata=pickle.loads((WORK/'入口詳細.pkl').read_bytes())
    trade_cache={};new_rows=total_accounts=0;same_clock=expired=0;reports=[];prefix_examples=[]
    def get_trade(key,i,side,config):
        """機能: 独立検算済みの同一取引を条件間で再利用する。

        引数: key(tuple)、i/side(int)、config(dict)。返り値: 独立取引(dict)。
        """
        identity=(*key,i,side,config['id'])
        if identity not in trade_cache:trade_cache[identity]=ref.trade(inputs[key],quotes[key],i,side,config)
        return trade_cache[identity]
    def summary(rows):
        """機能: 金額会計と固定0.1%損切り幅基準のRを独立集計する。

        引数: rows(list[dict])。返り値: 集計(dict)。
        """
        measured=ref.summary(rows)
        rs=[r['net']/(r['entry_price']*.001*r['qty']*r['value']) for r in rows]
        measured['net_R']=math.fsum(rs);measured['mean_R']=math.fsum(rs)/len(rs) if rs else None
        return measured
    for number,method in enumerate(result['methods'],1):
        actual=[];accounts=[];entry_config,exit_config=method['entry'],method['exit'];mirror=method['mirror']
        for key in sorted(inputs):
            account,q=inputs[key],quotes[key];signals=candidates[key][entry_config['id']]
            rows=[];busy=-1;cool=-math.inf
            gates=dict(candidates=len(signals),accepted=0,scheduled=0,holding=0,cooldown=0,cutoff=0,expired=0)
            for signal in signals:
                i=int(signal[0]);side=int(signal[1])*(-1 if mirror else 1)
                if i<=busy:
                    gates['holding']+=1;continue
                if account['time_s'][i]>=account['limit']-300:
                    gates['cutoff']+=1;continue
                if account['time_s'][i]<cool:
                    gates['cooldown']+=1;continue
                gates['scheduled']+=1
                if account['time_s'][i+1]>=account['limit']-300:
                    gates['expired']+=1;continue
                r=get_trade(key,i,side,exit_config);rows.append(r);gates['accepted']+=1
                assert r['qty']==(10 if key[1]=='TOPIX' else 20)
                busy=r['exit_i'];cool=r['exit_time']+600
                same_clock+=int(r['exit_time']==r['exit_decision_time'])
            assert gates['scheduled']==gates['accepted']+gates['expired']
            assert sum(gates[k] for k in ('accepted','holding','cooldown','cutoff','expired'))==len(signals)
            expired+=gates['expired'];actual.extend(rows)
            accounts.append(dict(session=key[0],symbol=key[1],block=block(key[0]),**summary(rows),gates=gates))
            if method['primary'] and rows:prefix_examples.append((key,rows[0],exit_config))
        ref.same(method['rows'],actual);ref.same(method['accounts'],accounts)
        measured_summary={s:summary([r for r in actual if r['symbol']==s]) for s in ('TOPIX','NK225')}
        ref.same(method['summary'],measured_summary)
        measured_blocks={b:{s:summary([r for r in actual if r['symbol']==s and block(r['session'])==b]) for s in ('TOPIX','NK225')} for b in ('前半10場','中間10場','後半5場')}
        ref.same(method['blocks'],measured_blocks)
        total_accounts+=len(accounts);new_rows+=len(actual)
        reports.append(dict(id=method['id'],取引数=len(actual),全口座一致=True))
        if number%48==0:print('売買監査',number,'/192',flush=True)
    # ----------------------------------------
    # 採点だけの未来値は、独立した返済可能気配の最高/最低と初回到達から照合する。
    score_cache={};score_count=0;excluded=0
    for method in scoring['methods']:
        config=method['config'];rows=[]
        for key,account in inputs.items():
            q=quotes[key]
            for meta in metadata[key][config['id']]:
                i,side=int(meta['i']),int(meta['side']);e=i+1
                if account['time_s'][i]>=account['limit']-300 or account['time_s'][e]>=account['limit']-300:
                    excluded+=1;continue
                identity=(*key,i,side)
                if identity not in score_cache:
                    anchor=float(q['ask'][e] if side==1 else q['bid'][e]);future=q['bid'][e:] if side==1 else q['ask'][e:]
                    highest,lowest=float(future.max()),float(future.min())
                    mfe=max(0.,highest-anchor) if side==1 else max(0.,anchor-lowest)
                    mae=max(0.,anchor-lowest) if side==1 else max(0.,highest-anchor)
                    labels={}
                    for fraction,label in ((.0005,'0.05'),(.001,'0.10'),(.002,'0.20')):
                        direction,first_i=first_touch(q['bid'],q['ask'],e,side,anchor*fraction)
                        labels[label]=dict(target=bool(mfe>=anchor*fraction-1e-9),first=direction,first_i=first_i)
                    score_cache[identity]=dict(session=key[0],symbol=key[1],i=i,seq=int(account['seq'][i]),side=side,time_s=float(account['time_s'][i]),
                        entry_i=e,entry_seq=int(account['seq'][e]),entry_price=anchor,bar_close=float(meta['close']),decision_mid=float(meta['mid']),mfe=mfe,mae=mae,
                        mfe_fraction=mfe/anchor,mae_fraction=mae/anchor,labels=labels)
                row=dict(score_cache[identity])
                for name in ('slope','er','previous_slope'):row[name]=float(meta[name]) if np.isfinite(meta[name]) else None
                rows.append(row)
        ref.same(method['rows'],rows)
        for symbol in ('TOPIX','NK225'):
            selected=[r for r in rows if r['symbol']==symbol];n=len(selected)
            measured=dict(n=n,mfe_median=float(np.median([r['mfe'] for r in selected])) if n else None,
                mfe_fraction_median=float(np.median([r['mfe_fraction'] for r in selected])) if n else None,labels={})
            for label in ('0.05','0.10','0.20'):
                targets=sum(r['labels'][label]['target'] for r in selected);first=sum(r['labels'][label]['first']==1 for r in selected);opposite=sum(r['labels'][label]['first']==-1 for r in selected)
                measured['labels'][label]=dict(targets=targets,target_rate=targets/n if n else None,first=first,opposite=opposite,unresolved=n-first-opposite,first_rate=first/n if n else None)
            ref.same(method['summary'][symbol],measured)
        score_count+=len(rows)
    assert len(score_cache)==scoring['重複除外キャッシュ数']
    # ----------------------------------------
    # 主入口のprefixで未決済/次行未約定を区別し、未来改変不変性を確認する。
    sys.path.insert(0,str(ROOT/'work/wave_v65'));import replay as original_exits
    prefix_checks=future_changes=0
    for key,row,config in prefix_examples:
        q=quotes[key];account=inputs[key];d=row['decision_i']
        lengths={row['entry_i']+1,row['exit_decision_i']+1,row['exit_i']+1}
        if row['armed_i']>=0:lengths.add(row['armed_i']+1)
        for length in lengths:
            expected=chunk_trace(q['time_s'][:length],q['bid'][:length],q['ask'][:length],d,row['side'],config,account['limit']-60)
            actual=original_exits.trace(q['time_s'][:length],q['bid'][:length],q['ask'][:length],d,row['side'],config['stop'],config['arm'],config['trail'],config['floor'],account['limit']-60)
            ref.same(list(actual),list(expected));prefix_checks+=1
        x=row['exit_i'];end=min(x+5,len(q['seq']));bid=q['bid'][:end].copy();ask=q['ask'][:end].copy()
        bid[x+1:]+=10000;ask[x+1:]+=10000
        actual=original_exits.trace(q['time_s'][:end],bid,ask,d,row['side'],config['stop'],config['arm'],config['trail'],config['floor'],account['limit']-60)
        expected=chunk_trace(q['time_s'],q['bid'],q['ask'],d,row['side'],config,account['limit']-60)
        ref.same(list(actual),list(expected));future_changes+=1
    choice=json.loads((WORK/'時系列選択.json').read_text(encoding='utf-8'))
    eligible=[m for m in result['methods'] if not m['mirror'] and all(m['blocks']['前半10場'][s]['trades']>=10 for s in ('TOPIX','NK225'))]
    selected=max(eligible,key=lambda m:min(m['blocks']['前半10場'][s]['mean_R'] for s in ('TOPIX','NK225'))) if eligible else None
    assert choice['選択条件']==(selected['id'] if selected else None) and choice['適格条件数']==len(eligible)
    ref.same(choice['selected'],selected)
    for path,sha in fixed['SHA'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    report=dict(結論='192条件の全原板次行売買・費用・予約ゲート、48入口の最大順行と対称先着、期間別と選択が独立計算に一致',
        条件数=len(result['methods']),口座照合数=total_accounts,決済照合数=new_rows,独立取引キャッシュ数=len(trade_cache),
        同時計の次原板返済約定数=same_clock,予約後失効数=expired,入口採点照合数=score_count,独立価格経路数=len(score_cache),
        採点の締切除外数=excluded,主入口のprefix検査数=prefix_checks,決済後の未来改変検査数=future_changes,
        時系列選択=dict(一致=True,id=choice['選択条件'],適格数=len(eligible)),条件別=reports,
        注意=['最大順行・先着の事後ラベルを、入口特徴と売買判断には使わない。',
        '同じ入口候補は保有状態と10分休止によって実取引に選別される。全検知の採点を決済勝率と混同しない。',
        '原板有効行の次行で売買気配約定する。CurrentPriceTime同値の別更新もseq順の次行であり、通信遅延を再現した試験ではない。',
        '実新規建値からの連続百分率を条件線とする。0.1%保護線で約定する保証ではない。',
        'ラージ気配をmicro/miniに代理した既知25セッション。前半選択に中間後半を使わなくても、全体が独立未知データにはならない。'],
        固定SHA256=hashlib.sha256((WORK/'実行前固定.json').read_bytes()).hexdigest(),結果SHA256=hashlib.sha256((WORK/'結果.json').read_bytes()).hexdigest(),
        監査コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'急傾斜192条件と全入口採点の独立監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','条件数','口座照合数','決済照合数','独立取引キャッシュ数','入口採点照合数','独立価格経路数','主入口のprefix検査数','決済後の未来改変検査数')},ensure_ascii=False))


if __name__=='__main__':
    main()
