"""全返済価格を再集計し、途中判断13条件の同じ影元組差を独立に比較する。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from statistics import median

import mid_design as design

HERE, ROOT = design.HERE, design.ROOT
OUT = HERE/'mid_results'
specification = importlib.util.spec_from_file_location('mid_price_reconstruction',HERE.parent/'wave_v44/post_audit.py')
independent = importlib.util.module_from_spec(specification)
specification.loader.exec_module(independent)


def labels(values: dict) -> dict:
    """機能: 増益とDD変化を別々に分類し、微小交換を全否定へ変換しない。

    引数: values(dict)。返り値: 方向別の説明(dict)。新しい採用閾値は足さない。
    """
    net,dd=values['収支差円'],values['DD差円']
    if net == 0 and dd == 0:word='収支とDD同値'
    elif net >= 0 and dd <= 0:word='収支DD非劣位'
    elif net <= 0 and dd >= 0:word='収支DD非優位'
    else:word='利益とDDの交換'
    return dict(関係=word,増益=net>0,DD減少=dd<0)


def pair(left: str, right: str, books: dict, accounts: dict, summaries: dict, names: list[str], symbol: str) -> dict:
    """機能: 同じ影の全組を初回署名まで照合して価格再計算した損益差を作る。

    引数: left/right(str)、books/accounts/summaries(dict)、names(list[str])、symbol(str)。
    返り値: 全元組差と集約(dict)。独立した組番号だけを照合根拠にしない。
    """
    differences=[]
    for session in names:
        key=session,symbol;a,b=books[left][key],books[right][key]
        assert a['shadow_fingerprints'] == b['shadow_fingerprints']
        assert a['shadow_orders'] == b['shadow_orders'] and a['shadow_cycles'] == b['shadow_cycles']
        ga,gb=accounts[left][key]['groups'],accounts[right][key]['groups']
        assert set(ga) == set(gb)
        for campaign in sorted(ga):
            x,y=ga[campaign],gb[campaign]
            assert x['signature'] == y['signature'] and x['risk'] == y['risk'] > 0
            differences.append(dict(session=session,symbol=symbol,campaign=campaign,
                初回署名=x['signature'],元予算円=x['risk_yen'],収支差円=x['pnl']-y['pnl'],
                差R=(x['points']-y['points'])/x['risk']))
    period='all_symbols' if len(names)==13 else 'symbols'
    a,b=summaries[left][period][symbol],summaries[right][period][symbol]
    net=sum(r['収支差円'] for r in differences);r=sum(x['差R'] for x in differences)
    independent.equal(net,a['net_yen']-b['net_yen'],'対応差と全口座')
    independent.equal(r,a['net_r']-b['net_r'],'対応R差と全口座')
    value=dict(収支差円=net,DD差円=a['drawdown_yen']-b['drawdown_yen'],合計差R=r,
        元組数=len(differences),改善組数=sum(x['収支差円']>0 for x in differences),
        悪化組数=sum(x['収支差円']<0 for x in differences),同値組数=sum(x['収支差円']==0 for x in differences),
        平均差円=net/len(differences) if differences else None,
        差R中央値=median(x['差R'] for x in differences) if differences else None,
        最大1改善組除外差円=net-max([0.]+[x['収支差円'] for x in differences]),
        全元組=differences)
    return dict(**value,**labels(value))


def run() -> dict:
    """機能: 完備済み338口座の元価格・数量・元組尺度から13条件の比較を行う。

    引数: なし。返り値: 全条件・全場・全対応差の独立集計(dict)。売買再生なし。
    """
    read=independent.read;complete=read(HERE/'mid_complete.json');fixed=read(HERE/'mid_runtime_fixed.json')
    assert complete['全合格'] and complete['全条件数']==13 and complete['全入力数']==338
    assert complete['実行固定SHA256']==design.digest(HERE/'mid_runtime_fixed.json')
    for group in (complete['出力SHA256'],complete['参照資料SHA256']):
        for name,sha in group.items():assert design.digest(ROOT/name)==sha,name
    specs={s['id']:s for s in fixed['conditions']};summaries={};books={};accounts={};sessions=[];methods=[];waves=[]
    periods={'all_symbols':fixed['rules']['全セッション'],'symbols':fixed['rules']['後半7セッション']}
    keys={(n,s) for n in periods['all_symbols'] for s in ('TOPIX','NK225')}
    trade_count=cycle_count=0
    for identifier,spec in specs.items():
        summary=read(OUT/'summaries'/(identifier+'.json'));summaries[identifier]=summary
        assert summary['id']==identifier and summary['spec']==spec
        rows=read(OUT/'sessions'/(identifier+'.json.gz'));ledgers=read(OUT/'ledgers'/(identifier+'.json.gz'))
        assert len(rows)==len(ledgers)==26
        rows_by_key={(r['session'],r['symbol']):r for r in rows}
        books[identifier]={(r['session'],r['symbol']):r for r in ledgers}
        assert set(rows_by_key)==set(books[identifier])==keys
        accounts[identifier]={}
        for key,book in books[identifier].items():
            row=rows_by_key[key];assert row['id']==identifier
            account=independent.account(book,row);accounts[identifier][key]=account
            trade_count+=len(book['trades']);cycle_count+=len(book['cycles'])
            unit_win=independent.ratio(row['gross_profit_yen'],row['profit_units'])
            unit_loss=independent.ratio(row['gross_loss_yen'],row['loss_units'])
            sessions.append(dict(**row,元組PF=independent.ratio(row['cycle_profit_yen'],row['cycle_loss_yen']),
                一枚平均利益円=unit_win,一枚平均損失円=unit_loss,一枚平均勝敗比=independent.ratio(unit_win,unit_loss),
                上位2勝ち元組同時除外収支円=row['net_yen']-sum(row['two_largest_cycle_profits'])))
        cells=[]
        for period,names in periods.items():
            for symbol in ('TOPIX','NK225'):
                part=[accounts[identifier][(n,symbol)] for n in names]
                inspected=independent.cell(part,summary[period][symbol])
                cells.append(dict(期間=period,symbol=symbol,保存期間集計=summary[period][symbol],独立指標=inspected))
        source=fixed['origins'][identifier]
        methods.append(dict(id=identifier,spec=spec,origin=source,四セル=cells))
        current_waves=read(OUT/'waves'/(identifier+'.json.gz'))
        assert len(current_waves)==8 and all(w['method']==identifier for w in current_waves)
        waves.extend(current_waves)
    differences=[]
    comparisons=fixed['comparisons']+[dict(kind='A0',left=x,right=design.BASELINE,primary=False) for x in specs if x!=design.BASELINE]
    for comparison in comparisons:
        cells=[]
        for period,names in periods.items():
            for symbol in ('TOPIX','NK225'):
                cells.append(dict(期間=period,symbol=symbol,**pair(comparison['left'],comparison['right'],books,accounts,summaries,names,symbol)))
        differences.append(dict(**comparison,四セル=cells))
    # ----------------------------------------
    # 到達ゲート×復元の交互作用も、同じ全影元組を四条件で対応させる。
    interactions=[]
    for fraction in (25,50):
        for other in ('none','timer'):
            for period,names in periods.items():
                for symbol in ('TOPIX','NK225'):
                    a=pair(design.identifier(1.5,fraction,'signal'),design.identifier(1.5,fraction,other),books,accounts,summaries,names,symbol)
                    b=pair(design.identifier(0.,fraction,'signal'),design.identifier(0.,fraction,other),books,accounts,summaries,names,symbol)
                    assert len(a['全元組'])==len(b['全元組'])
                    rows=[]
                    for x,y in zip(a['全元組'],b['全元組']):
                        assert (x['session'],x['campaign'],x['初回署名'])==(y['session'],y['campaign'],y['初回署名'])
                        rows.append(dict(session=x['session'],symbol=symbol,campaign=x['campaign'],
                            交互作用円=x['収支差円']-y['収支差円'],交互作用R=x['差R']-y['差R']))
                    interactions.append(dict(fraction=fraction,比較='signal−'+other,期間=period,symbol=symbol,
                        合計円=sum(x['交互作用円'] for x in rows),合計R=sum(x['交互作用R'] for x in rows),全元組=rows))
    assert len(sessions)==338 and len(waves)==104 and len(differences)==30 and len(interactions)==16
    for name,sha in independent.REFERENCES.items():assert design.digest(ROOT/name)==sha,name
    return dict(全合格=True,全条件数=13,全入力数=338,全返済脚数=trade_count,全元組数=cycle_count,
        既知条件数=9,再利用条件数=7,既知互換再生条件数=2,未試行機構条件数=4,
        条件別=methods,全セッション=sessions,対応比較=differences,交互作用=interactions,指定波=waves,
        参照資料SHA256=independent.REFERENCES,実装SHA256=design.digest(Path(__file__)),
        評価='既知13の成分比較。元組PF・返済脚比率・枚数平均比を区別。DDは完備した全行独立会計に接続し差だけ別計算。',
        採用条件追加=False,p値を使用=False,新Night使用=False,新売買再生=False,現在API取得数=0)


if __name__ == '__main__':
    result=run();design.save(HERE/'mid_result.json',result)
    print(f"途中判断独立集計 {result['全条件数']}条件・{result['全入力数']}口座一致",flush=True)
