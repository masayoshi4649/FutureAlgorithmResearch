"""最終結果の解釈を、合計・1組平均・費用・単独対照に分けて点検する。"""

import json

from accounts import HERE,WORK,study


def fields(row: dict) -> dict:
    """機能: 誤読しやすい勝率・金額比・費用・保有時間を並べる。

    引数: row(dict)。返り値: 主な指標(dict)。
    """
    names=['profit','loss','net','gross','fees','trades','wins','losses','profit_share','profit_loss_ratio',
        'average_net','average_win','average_loss','payoff','winning_sessions','active_sessions','worst_session',
        'drawdown','without_best_session','spread_drag','decision_to_fill_cost','hold_median','hold_p95','hold_max']
    out={n:row[n] for n in names};out['中値経路損益']=row['gross']+row['spread_drag']
    return out


def main() -> None:
    """機能: 188前半条件・最終代表・単独対照・遅延・鮮度の主張を再点検する。

    引数: なし。返り値: なし(None)。追加探索を行わず監査JSONを保存する。
    """
    selected=study.load(WORK/'前半選定.json')
    initial=study.load(WORK/'初回前半選定.json')['代表']
    trials=[study.load(p) for folder in ['first','improved'] for p in (WORK/folder/'results').glob('*.json')]
    assert len(trials)==188
    front_positive=[p['config']['id'] for p in trials if all(p['periods']['前16'][s]['net']>0 for s in ['TOPIX','NK225'])]
    records=[];comparison=[];paired=[];strict=[]
    for config in selected['改修']:
        identifier=config['id']
        prior=next(c for c in initial if c['family']==config['family'])
        for delay in [0,1,5]:
            packet=study.load(WORK/'final'/f'delay{delay}'/'results'/f'{identifier}.json')
            markets={s:fields(packet['periods']['対象'][s]) for s in ['TOPIX','NK225']}
            records.append(dict(id=identifier,遅延=delay,商品=markets,
                両黒字=all(v['net']>0 for v in markets.values()),両80達成=all(v['profit_share'] is not None and v['profit_share']>=.8 for v in markets.values())))
        new=study.load(WORK/'final/delay5/results'/f'{identifier}.json')
        old=study.load(WORK/'final/delay5/results'/f'{prior["id"]}.json')
        alone=study.load(WORK/'final/delay5/results'/f'{identifier}_自己のみ.json')
        quality=study.load(WORK/'quality3/results'/f'{identifier}.json')
        for symbol in ['TOPIX','NK225']:
            before=old['periods']['対象'][symbol];after=new['periods']['対象'][symbol];single=alone['periods']['対象'][symbol]
            comparison.append(dict(商品=symbol,初回=prior['id'],改修=identifier,
                初回指標=fields(before),改修指標=fields(after),収支改善=after['net']-before['net'],
                総損失減=before['loss']-after['loss'],総利益変化=after['profit']-before['profit'],
                組数変化=after['trades']-before['trades'],一組平均改善=after['average_net']-before['average_net']))
            paired.append(dict(id=identifier,商品=symbol,二市場=fields(after),自己のみ=fields(single),
                二市場収支優位=after['net']-single['net'],金額割合差=after['profit_share']-single['profit_share'],
                一組平均差=after['average_net']-single['average_net']))
            strict.append(dict(id=identifier,商品=symbol,相手3秒=fields(quality['periods']['対象'][symbol])))
    result=dict(前半条件数=len(trials),前半両黒字数=len(front_positive),前半両黒字ID=front_positive,
        主3と三遅延=records,主3初回比較=comparison,同じ条件で自己だけを見る比較=paired,鮮度厳格化=strict,
        解釈上の区別=[
            '前半の最も良い順位は採用に足る黒字性とは別。全188で両黒字0なら成功した候補があるとは言わない。',
            '平均勝ち/平均負けが1を超えても、負け回数が多ければ金額利益割合は半分に届かない。',
            '保有時間は結果であり、長く持てたこと自体は優位性ではない。X2は片方や中立では降りず双方反対まで待つ。',
            '中値経路・気配差・手数料の分解と、判断気配から約定までの待機差は別の比較。合計で二重控除しない。',
            '0秒結果も次原本行約定であり、現在観測の同じ行へ先取りしていない。真の受信時計上の即時約定は未実証。',
            '二市場と自己のみの差は全取引経路の差。両市場を見たことによる方向正答率の上昇と直接同一視しない。',
            '全30は既知資料。後半再確認は前半より追加適合を抑える手順だが完全未見ではない。'])
    assert len(front_positive)==0
    assert not any(r['両黒字'] or r['両80達成'] for r in records)
    assert all(v['net']<0 for r in records for v in r['商品'].values())
    (HERE/'最終数値と解釈の独立確認.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(前半条件188で両黒字=0,主3の三遅延は各商品赤字=True,
        主3の5秒=[r for r in records if r['遅延']==5]),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
