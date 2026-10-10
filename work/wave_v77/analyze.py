"""固定した代表・同設定対照・遅延感度から、金額8対2の達否をまとめる。"""

from pathlib import Path
import json
import pickle
import numpy as np

import study
import accounting

HERE=Path(__file__).resolve().parent


def comparison(result: dict) -> dict:
    """機能: 各期間の判定と比較に必要な会計を抜き出す。

    引数: result(dict)。返り値: 要約(dict)。
    """
    fields=('profit','loss','net','profit_share','profit_loss_ratio','trades','active_sessions','win_rate','payoff','fees','adds','risk_excesses',
            'without_best_session','without_best_profit_share','max_trade_loss','drawdown','winning_lots','losing_lots','max_long','max_short')
    return {p:{s:{k:a[k] for k in fields} for s,a in values.items()} for p,values in result['periods'].items()}


def main() -> None:
    """機能: 前半選定を変えずに確認期間と追加1場の結果を集計する。

    引数: なし。返り値: なし(None)。原本・設定・選定を変更しない。
    """
    fixed=study.load(HERE/'事前固定.json');chosen=study.load(HERE/'前半選定.json')
    results={p.stem:study.load(p) for p in sorted((HERE/'results').glob('*.json'))};assert len(results)==492
    eligible=[r for r in results.values() if all(r['periods']['前16'][s]['trades']>=20 and r['periods']['前16'][s]['active_sessions']>=8 for s in study.SYMBOLS)]
    counts={}
    for period in ('前16','後13','全29'):
        counts[period]=dict(全492内両商品80達成=sum(all(r['periods'][period][s]['goal80'] for s in study.SYMBOLS) for r in results.values()),
            前半活動条件達成内両商品80達成=sum(all(r['periods'][period][s]['goal80'] for s in study.SYMBOLS) for r in eligible))
    output=[]
    for row in chosen['代表']:
        ident=row['id'];r=results[ident];old=study.load(HERE/'unseen/results'/(ident+'.json'))
        combined=r['rows']+old['rows'];periods=dict(r['periods'],**old['periods'])
        periods['全30']={s:accounting.aggregate(combined,s,fixed['全30']) for s in study.SYMBOLS}
        post=periods['後13'];active=all(post[s]['trades']>=10 and post[s]['active_sessions']>=5 for s in study.SYMBOLS)
        goal=all(post[s]['goal80'] for s in study.SYMBOLS)
        delays={str(d):comparison(study.load(study.base_path(d)/'results'/(ident+'.json')))['全29'] for d in (1,5,15)}
        controls={cid:comparison(results[cid]) for cid in row['controls']}
        # ----------------------------------------
        # 追加玉の負けや、一組では黒字でも個別玉に負けがある件数を省略しない。
        ledgers=study.load(HERE/'ledgers'/(ident+'.pkl'));ledgers.update(study.load(HERE/'unseen/ledgers'/(ident+'.pkl')))
        parts={}
        for symbol in study.SYMBOLS:
            trades=np.concatenate([v['trades'] for k,v in ledgers.items() if k[1]==symbol]);summary=[]
            for leg in range(3):
                t=trades[trades[:,11]==leg];net=t[:,10]
                summary.append(dict(建値番号=leg,決済明細数=len(t),利益=float(net[net>0].sum()),損失=float(-net[net<0].sum()),収支=float(net.sum()),枚数=int(t[:,4].sum())))
            hidden=0
            for key,v in ledgers.items():
                if key[1]!=symbol:continue
                for cid in np.unique(v['trades'][:,0]):
                    t=v['trades'][v['trades'][:,0]==cid]
                    if t[:,10].sum()>0 and (t[:,10]<0).any():hidden+=1
            parts[symbol]=dict(建値別=summary,組黒字でも負け玉を含む組数=hidden)
        output.append(dict(**row,会計=comparison(dict(periods=periods)),後半活動条件=active,後半両商品80=goal,
            認定='後半8対2達成' if row['eligible'] and active and goal else '活動不足で判定保留' if not row['eligible'] or not active else '8対2未達',
            遅延全29=delays,同設定対照=controls,追加玉内訳=parts))
    baseline=results[chosen['基準']];new=study.load(HERE/'unseen/results'/(chosen['基準']+'.json'))
    bp=dict(baseline['periods'],**new['periods']);bp['全30']={s:accounting.aggregate(baseline['rows']+new['rows'],s,fixed['全30']) for s in study.SYMBOLS}
    study.save(HERE/'analysis/改善と反証の整理.json',dict(条件数=492,前半活動条件達成数=len(eligible),金額80条件数=counts,
        基準=comparison(dict(periods=bp)),代表=output,代表は前半固定=True,追加場で再選定=False,
        結果の限界='前29は既知データの再探索。追加1場だけが今回固定後の新確認。最終約定時計とラージ気配の代用限界は残る。'))
    print(json.dumps(dict(条件数=492,前半活動条件達成数=len(eligible),金額80条件数=counts,
        代表=[dict(id=x['id'],認定=x['認定'],全30=x['会計']['全30'],追加1=x['会計']['追加1']) for x in output]),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
