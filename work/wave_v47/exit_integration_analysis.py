"""固定した12条件の同じ初回組を対応させ、数量と出口を混同せず記述する。"""

from pathlib import Path

import numpy as np

import exit_integration_runner as runner

HERE=Path(__file__).resolve().parent
MULT={'TOPIX':1000.,'NK225':10.}


def campaigns(identifier: str) -> dict:
    """機能: 保存台帳から元組の初回と終了収支を抽出する。

    引数: identifier(str)。返り値: セッション・銘柄・組ID別の初回と収支(dict)。
    再生はせず、元影から異なる入口を誤対応しない。
    """
    result={}
    for row in runner.read(runner.DESTINATION/'ledgers'/(identifier+'.json.gz')):
        orders=np.asarray(row['orders'],float).reshape(-1,8)
        for cycle in row['cycles']:
            cid=int(cycle[0]);key=(row['session'],row['symbol'],cid)
            opening=orders[(orders[:,2]==cid)&(orders[:,6]==20)&(orders[:,7]==1)]
            assert len(opening)==1
            result[key]=dict(entry=opening[0].tolist(),cycle=cycle,
                net_yen=float(cycle[3])*MULT[row['symbol']])
    assert len(result)==102
    return result


def run() -> dict:
    """機能: 全件完備後に同数量の出口差と元A0/C01差を保存する。

    引数: なし。返り値: 記述的な対応比較(dict)。採否条件や新方式を追加しない。
    """
    complete=runner.read(HERE/'exit_integration_complete.json')
    assert complete['全合格'] and complete['全入力数']==312 and not complete['新Night使用']
    runner.verify(complete['出力SHA256'])
    summaries={r['id']:r for r in runner.read(HERE/'exit_integration_results.json')['conditions']}
    matched={name:campaigns(name) for name in summaries}
    comparisons=[]
    for quantity in ('A0','C01','F50','F50_NONE'):
        for exit_id in ('E10','E11'):
            name=quantity+'__'+exit_id;base=quantity+'__E00'
            for symbol in MULT:
                keys=[k for k in matched[name] if k[1]==symbol]
                diffs=[];positive=negative=zero=earlier=later=same=0
                for key in keys:
                    a,b=matched[name][key],matched[base][key]
                    assert a['entry']==b['entry']
                    assert [a['cycle'][i] for i in (0,1,4,5,8)]==[b['cycle'][i] for i in (0,1,4,5,8)]
                    delta=a['net_yen']-b['net_yen'];diffs.append(delta)
                    positive+=delta>1e-6;negative+=delta<-1e-6;zero+=abs(delta)<=1e-6
                    earlier+=a['cycle'][2]<b['cycle'][2];later+=a['cycle'][2]>b['cycle'][2];same+=a['cycle'][2]==b['cycle'][2]
                a=summaries[name]['all_symbols'][symbol];b=summaries[base]['all_symbols'][symbol]
                total=float(sum(diffs));assert abs(total-(a['net_yen']-b['net_yen']))<1e-6
                comparisons.append(dict(id=name,対照=base,symbol=symbol,同じ初回組数=len(keys),
                    収支差円=total,最大の正改善1組を除く差円=total-max(0.,max(diffs)),
                    改善組数=int(positive),悪化組数=int(negative),同額組数=int(zero),
                    早期終了組数=int(earlier),同時終了組数=int(same),遅い終了組数=int(later),
                    総利益差円=a['gross_profit_yen']-b['gross_profit_yen'],
                    総損失差円=a['gross_loss_yen']-b['gross_loss_yen'],
                    口座最大下落差円=a['drawdown_yen']-b['drawdown_yen'],
                    後7収支差円=summaries[name]['symbols'][symbol]['net_yen']-summaries[base]['symbols'][symbol]['net_yen'],
                    後7最大下落差円=summaries[name]['symbols'][symbol]['drawdown_yen']-summaries[base]['symbols'][symbol]['drawdown_yen']))
    source=HERE/'exit_integration_results.json'
    value=dict(全同初回対応一致=True,対応比較数=len(comparisons),結果=comparisons,
        注意='既知13だけの記述比較。出口が変わるとその後の減量復元も変わるため、数量方式との相互作用を含む。新Night未使用。',
        参照資料SHA256={p.relative_to(runner.ROOT).as_posix():runner.digest(p) for p in
            (source,HERE/'exit_integration_complete.json',Path(__file__))})
    runner.save(HERE/'exit_integration_analysis.json',value)
    lines=['# 同期統合12条件の旧13セッション結果','',
        '元A0の新規準備に同期し、初回の時刻・価格・枚数・初期ATR・Rを全方式で維持した単一口座の比較。全312入力の独立会計・因果検査、E00旧同値104入力、無調整の独立出口306組一致を通過した。新しい9月29日ナイトは未使用。','',
        'E10（3ATR順行後に幅1.5ATRへ短縮）は、4数量方式すべてで全13の両銘柄収支が改善し、口座の最大下落も減った。後7の両銘柄収支も改善し、最大の正改善1組を除いても改善差は残る。旧条件で選ばれた初回を固定した結果なので、未知期間や別入口での優位性を意味しない。','',
        'E11（短縮幅0.75ATR）は全13の利益がさらに多いが、最初6のNKは全4数量方式でE00より減益した。E10も復元なしの最初6のNKでは300円減益であり、全期間・全状態での優越は確認できていない。主E10、対照E11という事前の位置付けは変更しない。','',
        '| 数量・出口 | TOPIX収支 / 最大下落 | NK収支 / 最大下落 | 後7 TOPIX / NK |',
        '|---|---:|---:|---:|']
    for quantity in ('A0','C01','F50','F50_NONE'):
        for exit_id in ('E00','E10','E11'):
            r=summaries[quantity+'__'+exit_id];a=r['all_symbols'];b=r['symbols']
            lines.append(f"| {r['id']} | {a['TOPIX']['net_yen']:,.0f} / {a['TOPIX']['drawdown_yen']:,.0f} | {a['NK225']['net_yen']:,.0f} / {a['NK225']['drawdown_yen']:,.0f} | {b['TOPIX']['net_yen']:,.0f} / {b['NK225']['net_yen']:,.0f} |")
    lines+=['','金額は円。TOPIXミニ5枚・NKマイクロ10枚から開始し、同銘柄内で比較する。ここでの最大下落はセッションを接続した実現＋含みの口座曲線。先行した「元組内の独立実験」の最大下落とは定義が異なる。','',
        '| 同数量の出口変更 | 銘柄 | 収支差 | 最大の正改善1組を除く差 | 口座最大下落差 | 後7収支差 |',
        '|---|---|---:|---:|---:|---:|']
    for r in comparisons:
        lines.append(f"| {r['id']}−{r['対照']} | {r['symbol']} | {r['収支差円']:+,.0f} | {r['最大の正改善1組を除く差円']:+,.0f} | {r['口座最大下落差円']:+,.0f} | {r['後7収支差円']:+,.0f} |")
    lines+=['','最大の正改善1組を除く差は、方式の最大勝ちを除いた絶対収支とは別の、対応する改善差の集中診断。プラスでも未知期間の利益を保証しない。','',
        'E10/E11は3ATRまで順行した組だけで幅を短縮する。到達前の初期損失を改善する機構ではない。数量調整版では、早い終了が後続の減量・復元を止めるため、その相互作用を含む。独立した出口部品の改善額をそのまま現在の管理へ足すことはできない。','',
        '資料：[全12集計](exit_integration_results.json)、[同じ初回の対応差](exit_integration_analysis.json)、[全件完備](exit_integration_complete.json)、[機械仕様](出口同期統合の仕様.md)。']
    (HERE/'出口同期統合の結論.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print('同期12条件の同じ初回に対する出口差を記述しました。',flush=True)
    return value


if __name__=='__main__':run()
