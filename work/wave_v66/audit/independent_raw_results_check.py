"""追加５秒足144条件の会計と全入口の価格経路を独立監査する。"""

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys

import numpy as np

from independent_results_check import chunk_trace, first_touch, block


HERE=Path(__file__).resolve().parent
WORK=HERE.parent/'round2'
ROOT=HERE.parents[2]


def synthetic_short_exit(original,ref):
    """機能: 短期幅の開始・保護・次行約定・同時計・締切優先を合成経路で確認する。

    引数: original/ref(module)。返り値: 検査件数(int)。
    """
    cfg=dict(id='短期幅',stop=.0003,arm=.0005,trail=.0002,floor=.0003)
    count=0
    for side in (1,-1):
        for spread in (0.,10.):
            for same_clock in (False,True):
                for cutoff in (math.inf,3.):
                    for gains in ((-10.,50.,31.,29.,28.),(-30.,0.,0.,0.,0.),(-10.,80.,61.,59.,58.),(-10.,49.,-30.,-31.,-32.)):
                        # 新規約定を10万円に固定し、返済気配だけから各条件線を計算する。
                        anchor=100000.;times=np.arange(6,dtype=float)
                        if same_clock:times[4]=times[3]
                        prices=anchor+side*np.asarray((-10.,*gains),dtype=float)
                        if side==1:
                            bid=prices.copy();ask=prices+spread;ask[1]=anchor
                        else:
                            ask=prices.copy();bid=prices-spread;bid[1]=anchor
                        observed=original.trace(times,bid,ask,0,side,cfg['stop'],cfg['arm'],cfg['trail'],cfg['floor'],cutoff)
                        expected=chunk_trace(times,bid,ask,0,side,cfg,cutoff)
                        ref.same(list(observed),list(expected));count+=1
                        if math.isinf(cutoff):
                            if gains[1]==50.:
                                assert expected[:3]==(4,5,2) and math.isclose(expected[3],30.) and expected[5]==2
                            elif gains[0]==-30.:
                                assert expected[:3]==(1,2,-1) and math.isclose(expected[3],-30.) and expected[5]==1
                            elif gains[1]==80.:
                                assert expected[:3]==(4,5,2) and math.isclose(expected[3],60.) and expected[5]==2
                            else:
                                assert expected[:3]==(3,4,-1) and math.isclose(expected[3],-30.) and expected[5]==1
                        elif expected[0]>=3:
                            assert expected[5]==4
    return count


def main():
    """機能: 全144条件の50口座ゲート・全決済・24入口採点を独立再演算する。

    引数: なし。返り値: なし(None)。親の実装と結果、元192条件は変更しない。
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
        if identity not in trade_cache:
            row=ref.trade(inputs[key],quotes[key],i,side,config)
            row['initial_stop_fraction']=config['stop'];trade_cache[identity]=row
        return trade_cache[identity]

    def summary(rows):
        """機能: 金額会計と各初期損切り幅を基準にしたRを独立集計する。

        引数: rows(list[dict])。返り値: 集計(dict)。
        """
        measured=ref.summary(rows)
        rs=[r['net']/(r['entry_price']*r['initial_stop_fraction']*r['qty']*r['value']) for r in rows]
        measured['net_R']=math.fsum(rs);measured['mean_R']=math.fsum(rs)/len(rs) if rs else None
        return measured

    assert len(result['methods'])==144 and len(inputs)==50
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
        ref.same(method['summary'],{s:summary([r for r in actual if r['symbol']==s]) for s in ('TOPIX','NK225')})
        measured_blocks={b:{s:summary([r for r in actual if r['symbol']==s and block(r['session'])==b]) for s in ('TOPIX','NK225')} for b in ('前半10場','中間10場','後半5場')}
        ref.same(method['blocks'],measured_blocks)
        total_accounts+=len(accounts);new_rows+=len(actual)
        reports.append(dict(id=method['id'],取引数=len(actual),全口座一致=True))
        if number%48==0:print('追加売買監査',number,'/144',flush=True)
    # ----------------------------------------
    # 採点用の将来ラベルは、売買から独立して実建値と返済可能気配で算出する。
    score_cache={};score_count=0;excluded=0
    assert len(scoring['methods'])==24
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
                    for fraction,label in ((.0003,'0.03'),(.0005,'0.05'),(.001,'0.10'),(.002,'0.20')):
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
            for label in ('0.03','0.05','0.10','0.20'):
                targets=sum(r['labels'][label]['target'] for r in selected);first=sum(r['labels'][label]['first']==1 for r in selected);opposite=sum(r['labels'][label]['first']==-1 for r in selected)
                measured['labels'][label]=dict(targets=targets,target_rate=targets/n if n else None,first=first,opposite=opposite,unresolved=n-first-opposite,first_rate=first/n if n else None)
            ref.same(method['summary'][symbol],measured)
        score_count+=len(rows)
    assert len(score_cache)==scoring['重複除外キャッシュ数']
    # ----------------------------------------
    # 主入口でトレール開始、未決済、次行未約定、閉鎖後の未来改変を照合する。
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
    synthetic_count=synthetic_short_exit(original_exits,ref)
    for path,sha in fixed['SHA'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    short_main=next(m for m in result['methods'] if m['id']=='RAW_ACCEL_S060_V050_短期幅_順')
    short_nk=[r for r in short_main['rows'] if r['symbol']=='NK225']
    short_diagnostic=dict(取引数=len(short_nk),手数料前黒字数=sum(r['gross']>0 for r in short_nk),
        トレール開始済数=sum(r['protected'] for r in short_nk),初期損切り数=sum(r['reason']==1 for r in short_nk),
        損切り後の場末までに0点1パーセント到達=sum(r['stopped_then_eventual_target'] for r in short_nk),
        判断と新規約定の最終約定時計同値数=sum(r['entry_time']==r['decision_time'] for r in short_nk),
        収支=math.fsum(r['net'] for r in short_nk),手数料=math.fsum(r['fees'] for r in short_nk))
    report=dict(結論='追加144条件の全原板次行売買・費用・予約ゲート、24入口の最大順行と4対称先着、全50口座・3期間が独立計算に一致',
        条件数=len(result['methods']),口座照合数=total_accounts,決済照合数=new_rows,独立取引キャッシュ数=len(trade_cache),
        同時計の次原板返済約定数=same_clock,予約後失効数=expired,入口採点照合数=score_count,独立価格経路数=len(score_cache),
        採点の締切除外数=excluded,主入口のprefix検査数=prefix_checks,決済後の未来改変検査数=future_changes,短期出口の合成検査数=synthetic_count,
        元192条件SHA一致=True,条件別=reports,主加速短期幅NKの診断=short_diagnostic,
        注意=['最大順行と先着の事後ラベルを入口特徴と売買判断には使わない。',
        '全入口の先着採点は保有と10分休止を通す前の母集団であり、決済勝率とは別である。',
        '原板有効行の次行はCurrentPriceTime同値でもseq順の別更新。通信遅延を再現するものではない。',
        '短期幅は実建値に対し損切り0.03%、開始0.05%、追跡0.02%、初期保護0.03%。条件成立後の次行価格で約定し保護額は保証されない。',
        'ラージ気配をmicro/miniに代理した既知25セッション。144条件の順位は未知場に対する予測力の証明ではない。'],
        固定SHA256=hashlib.sha256((WORK/'実行前固定.json').read_bytes()).hexdigest(),結果SHA256=hashlib.sha256((WORK/'結果.json').read_bytes()).hexdigest(),
        監査コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'追加5秒足144条件と全入口採点の独立監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','条件数','口座照合数','決済照合数','独立取引キャッシュ数','入口採点照合数','独立価格経路数','主入口のprefix検査数','決済後の未来改変検査数','短期出口の合成検査数')},ensure_ascii=False))


if __name__=='__main__':
    main()
