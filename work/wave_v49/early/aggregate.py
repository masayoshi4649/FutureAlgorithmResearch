"""同じ初回のまま、早期保護で失った利益と減った損失を集計する。"""

from __future__ import annotations

import run


def main() -> None:
    """機能: 全十一条件の全32口座と初回固定証跡をまとめる。

    引数: なし。返り値: なし(None)。
    """
    source=run.source
    baseline=source.read(run.HERE/'ledgers/E00.json.gz')
    base={(r['session'],r['symbol']):r for r in baseline}
    rows=[];checks=[]
    fields=('gross_profit_yen','gross_loss_yen','net_yen','average_unit_payoff','money_ratio',
            'drawdown_yen','cycles','win_sessions','active_sessions','session_count','max_long','max_short','best_removed_net')
    for variant in run.catalog():
        summary=source.read(run.HERE/'summaries'/(variant['id']+'.json'))
        sessions=source.read(run.HERE/'sessions'/(variant['id']+'.json.gz'))
        ledgers=source.read(run.HERE/'ledgers'/(variant['id']+'.json.gz'))
        proofs=source.read(run.HERE/'audits'/(variant['id']+'.json.gz'))
        assert len(sessions)==len(ledgers)==len(proofs)==32
        assert all(p['全初回一致'] and p['元通常影全指紋一致'] for p in proofs)
        assert sum('因果' in p for p in proofs)==2
        impacts=[]
        for ledger in ledgers:
            key=ledger['session'],ledger['symbol'];old=base[key]
            original={int(c[0]):c for c in old['cycles']}
            factor=ledger['config']['point_value']
            for cycle in ledger['cycles']:
                previous=original[int(cycle[0])]
                assert cycle[1]==previous[1] and cycle[8]==previous[8]
                old_gain,new_gain=previous[3]*factor,cycle[3]*factor
                impacts.append(dict(session=key[0],symbol=key[1],campaign=int(cycle[0]),
                    元収支円=old_gain,新収支円=new_gain,収支差円=new_gain-old_gain,元退出行=int(previous[2]),新退出行=int(cycle[2])))
        periods={}
        for label,syms in summary['periods'].items():
            periods[label]={}
            for symbol,stats in syms.items():
                chosen=[r for r in impacts if r['symbol']==symbol and (label=='全16' or ((r['session']==source.NEW)==(label=='問題Night')))]
                stat={f:stats[f] for f in fields}
                stat['初回固定の組数']=len(chosen)
                stat['元勝ち組の差額円']=sum(r['収支差円'] for r in chosen if r['元収支円']>0)
                stat['元負け組の差額円']=sum(r['収支差円'] for r in chosen if r['元収支円']<0)
                stat['元ゼロ組の差額円']=sum(r['収支差円'] for r in chosen if r['元収支円']==0)
                stat['収支差円']=sum(r['収支差円'] for r in chosen)
                stat['早く退出した組数']=sum(r['新退出行']<r['元退出行'] for r in chosen)
                assert abs(stats['net_yen']-sum(r['新収支円'] for r in chosen))<1e-6
                periods[label][symbol]=stat
        rows.append(dict(variant=variant,periods=periods,sessions=sessions,同一初回の比較=impacts))
        checks.extend(proofs)
    assert len(checks)==352
    run.save(run.HERE/'早期保護の比較.json',dict(全合格=True,基準='F50_NONE__E11',方式数=11,口座数=352,
        実施範囲='元候補1の入口・数量ルール・元通常影時計を固定し、出口configだけ変更。新20モード比較とは別。',
        建値保護の表現='E09は基準影の収支ゼロ水準。実減量口座の収支ゼロ保証ではない。',
        条件=rows))
    files=list(run.HERE.glob('*.py'))+[run.HERE/'条件の事前固定.json']
    outputs=[p for p in run.HERE.rglob('*.json*') if p.name!='完了.json']
    run.save(run.HERE/'完了.json',dict(全合格=True,方式数=11,独立会計口座数=352,元通常影全指紋一致口座数=352,
        基準全指紋一致口座数=sum(r.get('基準全指紋一致',False) for r in checks),因果口座数=sum('因果' in r for r in checks),API追加取得数=0,
        実装仕様SHA256={p.relative_to(source.ROOT).as_posix():source.sha(p) for p in files},
        出力SHA256={p.relative_to(source.ROOT).as_posix():source.sha(p) for p in outputs}))
    print('全十一条件・352口座の同初回比較を集計',flush=True)


if __name__=='__main__':main()
