"""将来評価区間内の価格観測空白を追加監査する。入口条件や既存集計は変更しない。"""
import hashlib
import json
import numpy as np
import pandas as pd
import analysis as a


def main() -> None:
    """機能: 未来経路の内部と両端の最大観測間隔を測り、結果の品質感度を記録する。

    引数: なし。返り値: なし(None)。
    """
    protected=['現在状態.csv','観測点と将来経路.csv','状態別集計.json','状態遷移集計.json','事前固定.json']
    fingerprints={name:hashlib.sha256((a.HERE/name).read_bytes()).hexdigest() for name in protected}
    data=pd.read_csv(a.HERE/'観測点と将来経路.csv');inputs=a.load();cache={}
    for row in data[['session','symbol','time_s','horizon']].drop_duplicates().itertuples(index=False):
        key=(row.session,row.symbol);ready=inputs[key];now=float(row.time_s);end=now+int(row.horizon)*60
        left=np.searchsorted(ready['time_s'],now,side='left');right=np.searchsorted(ready['time_s'],end,side='left')
        times=ready['time_s'][left:right];prices=ready['last'][left:right]
        valid=np.isfinite(prices)&(prices>0);times=times[valid]
        assert len(times)>0
        gaps=np.diff(np.r_[now,times,end])
        assert np.all(gaps>=0)
        cache[(row.session,row.symbol,now,int(row.horizon))]=dict(max_gap_seconds=float(gaps.max()),
            left_gap_seconds=float(times[0]-now),right_gap_seconds=float(end-times[-1]),
            internal_gap_seconds=float(np.diff(times).max()) if len(times)>1 else 0.,price_observations=len(times))
    for name in ['max_gap_seconds','left_gap_seconds','right_gap_seconds','internal_gap_seconds','price_observations']:
        data[name]=[cache[(v.session,v.symbol,float(v.time_s),int(v.horizon))][name]
                    for v in data[['session','symbol','time_s','horizon']].itertuples(index=False)]
    data.to_csv(a.HERE/'将来区間の価格品質付きラベル.csv',index=False,encoding='utf-8-sig')
    paths=data.drop_duplicates(['session','symbol','time_s','horizon']);distribution=[]
    for (symbol,state,horizon),frame in paths.groupby(['symbol','state','horizon']):
        distribution.append(dict(symbol=symbol,state=state,horizon=int(horizon),unique_paths=len(frame),
            over60=int((frame.max_gap_seconds>60).sum()),over120=int((frame.max_gap_seconds>120).sum()),
            median=float(frame.max_gap_seconds.median()),q95=float(frame.max_gap_seconds.quantile(.95)),maximum=float(frame.max_gap_seconds.max())))
    sensitivity=[]
    for symbol in ('TOPIX','NK225'):
        chosen=data.loc[(data.symbol==symbol)&(data.state=='同方向高効率')&(data.horizon==30)&(data.hypothesis=='過去30分方向')]
        for sampling in ('5分全観測','60分非重複'):
            group=chosen if sampling=='5分全観測' else chosen.loc[chosen.nonoverlap_60==1]
            for threshold in (None,60,120):
                qualified=group if threshold is None else group.loc[group.max_gap_seconds<=threshold]
                sensitivity.append(dict(symbol=symbol,sampling=sampling,quality='元の評価対象' if threshold is None else f'将来区間最大gap{threshold}秒以内',
                    **a.describe(qualified)))
    a.save('将来区間品質監査.json',dict(全合格=True,既存結果変更=False,入口条件への品質フィルタ適用=False,
        定義='未来区間[t,t+h)の有効価格観測間隔。左端から最初、内部、最後から右端を含む最大秒。',
        評価ラベル数=len(data),独立性を意味しない異なる区間数=len(paths),
        over60_labels=int((data.max_gap_seconds>60).sum()),over120_labels=int((data.max_gap_seconds>120).sum()),
        over60_paths=int((paths.max_gap_seconds>60).sum()),over120_paths=int((paths.max_gap_seconds>120).sum()),
        最大空白秒=float(paths.max_gap_seconds.max()),分布=distribution,同方向高効率30分の感度=sensitivity,
        注意='未来の観測品質を確認した結果ラベルの感度分析で、入口時点に利用できるフィルタではない。観測のない間の価格経路は復元できない。',
        時計の限界='gapはCurrentPriceTime代理時計による。無約定による時刻停滞と受信・収集断をこの値だけでは区別できない。',
        既存成果SHA256=fingerprints,検証実装SHA256=hashlib.sha256((a.HERE/'quality.py').read_bytes()).hexdigest()))
    for name,digest in fingerprints.items():assert hashlib.sha256((a.HERE/name).read_bytes()).hexdigest()==digest
    # ----------------------------------------
    # 再現用主報告を変えず、追加監査の読み口を末尾へ一度だけ追記する。
    report=a.HERE/'README.md';text=report.read_text(encoding='utf8');heading='## 追加: 将来評価中の価格空白'
    if heading in text:text=text.split(heading)[0].rstrip()+'\n'
    lines=[heading,'',f'既存ラベル{len(data):,}件（同じ将来区間を二方向から測ったものを除くと{len(paths):,}区間）を追加点検した。',
           f'両端を含む将来区間最大gapが60秒超は{int((paths.max_gap_seconds>60).sum()):,}区間、120秒超は{int((paths.max_gap_seconds>120).sum()):,}区間。最大{float(paths.max_gap_seconds.max()):.0f}秒。',
           '元の集計では開始・終了付近の鮮度は確認していたが、評価途中の全gapを除外していたわけではない。空白中のMFE/MAE・先着順は復元できないため、記録された観測列での結果として読む。','',
           '|高効率30分・最大gap60秒以内|残数／元数|継続率|終値平均ATR|順行先着／逆行先着／未到達|',
           '|---|---:|---:|---:|---|']
    for symbol in ('TOPIX','NK225'):
        for sampling in ('5分全観測','60分非重複'):
            original=next(x for x in sensitivity if x['symbol']==symbol and x['sampling']==sampling and x['quality']=='元の評価対象')
            v=next(x for x in sensitivity if x['symbol']==symbol and x['sampling']==sampling and x['quality']=='将来区間最大gap60秒以内')
            lines.append(f"|{symbol}・{sampling}|{v['n']}／{original['n']}|{v.get('continue_direction',0):.1%}|{v.get('terminal_atr',0):+.3f}|{v.get('hit_win',0):.1%}／{v.get('hit_loss',0):.1%}／{v.get('untouched',0):.1%}|")
    lines+=['','gapは受信時刻ではなく `CurrentPriceTime` の代理時計で測っている。長いgapが無約定によるものか、収集・受信の空白によるものかは、この値だけでは区別できない。',
            'これは未来の記録品質を用いた評価感度であり、売買時点に使う入口フィルタにはできない。固定状態・閾値・元の結果ファイルは変更していない。`将来区間品質監査.json` と `将来区間の価格品質付きラベル.csv` に全件保存。再実行は `python work/wave_v51/properties_price/quality.py`。']
    report.write_text(text+'\n'+'\n'.join(lines)+'\n',encoding='utf8')
    print('将来区間品質確認完了: '+str(len(paths))+'区間',flush=True)


if __name__=='__main__':main()
