"""防止策の効果差、失った勝ち、同じ新規と新経路の分解、表示時刻を独立照合する。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json

from full_accounts import HERE, study
from account_parts import same_fields
from independent_account import save


def records(ledger: dict, times: object) -> dict:
    """機能: 新規判断行と方向で注文を対応させ、決済明細から表示値を再構成する。

    引数: ledger(dict)、times(ndarray)。返り値: 対応キー→記録(dict)。
    """
    output={};jst=timezone(timedelta(hours=9))
    for trade in ledger['trades']:
        cid=int(trade[0]);orders=ledger['orders'][ledger['orders'][:,2]==cid]
        opened=next(o for o in orders if o[7]==1);closed=next(o for o in orders if o[7]==0)
        value=dict(組=cid,判断行=int(opened[1]),方向=int(trade[3]),新規価格=float(trade[5]),返済価格=float(trade[6]),収支=float(trade[10]),返済理由=int(closed[6]))
        for name,row in (('新規判断',opened[1]),('新規約定',opened[0]),('返済判断',closed[1]),('返済約定',closed[0])):
            value[name]=datetime.fromtimestamp(float(times[int(row)]),jst).isoformat()
        output[(value['判断行'],value['方向'])]=value
    return output


def main() -> None:
    """機能: 全18案の全期間差と6口座図用時刻、因果対照の収支分解を照合する。

    引数: なし。返り値: なし(None)。
    """
    fixed=study.load(HERE.parent/'事前固定.json');material=study.material(5);ready=material[0]
    base=study.load(HERE.parent/'results/E0_X0.json');baseline=study.load(HERE.parent/'ledgers/E0_X0.pkl')
    effects=study.load(HERE.parent/'analysis/全条件の効果.json')
    matches=study.load(HERE.parent/'analysis/同じ新規の勝ち損失と新規経路.json')['条件']
    traces=study.load(HERE.parent/'analysis/赤字上位6口座の再生時刻.json')
    old={key:records(value,ready[key]['time_s']) for key,value in baseline.items()};compared=trace_count=0
    assert {v['id'] for v in effects}=={c['id'] for c in fixed['条件']} and len(traces)==6
    for effect in effects:
        ident=effect['id'];result=study.load(HERE.parent/'results'/f'{ident}.json');ledgers=study.load(HERE.parent/'ledgers'/f'{ident}.pkl')
        for period,rows in result['periods'].items():
            for symbol,actual in rows.items():
                prior=base['periods'][period][symbol]
                expected=dict(actual,収支変化=actual['net']-prior['net'],利益変化=actual['profit']-prior['profit'],損失削減=prior['loss']-actual['loss'])
                compared+=same_fields(expected,effect['期間'][period][symbol],(ident,period,symbol))
        for delay in (1,5,15):
            area=study.output_base(delay);dr=study.load(area/'results'/f'{ident}.json');db=study.load(area/'results/E0_X0.json')
            for symbol in ('TOPIX','NK225'):
                v=dr['periods']['全30'][symbol];expected=dict(v,収支変化=v['net']-db['periods']['全30'][symbol]['net'])
                compared+=same_fields(expected,effect['遅延'][str(delay)][symbol],(ident,delay,symbol))
        calc={symbol:{name:0 for name in matches[ident][symbol]} for symbol in ('TOPIX','NK225')}
        for key,ledger in ledgers.items():
            new=records(ledger,ready[key]['time_s']);prior=old[key];totals=calc[key[1]]
            for entry,value in prior.items():
                assert value['収支']!=0,'基準のゼロ損益を元負けへ紛れ込ませない'
                label='元勝ち' if value['収支']>0 else '元負け';totals[label+'数']+=1
                if entry in new:
                    totals[label+'対応数']+=1;totals[label+'対応の収支変化']+=new[entry]['収支']-value['収支']
                else:
                    totals[label+'未対応数']+=1;totals[label+'未対応の元'+('利益' if label=='元勝ち' else '損失')]+=abs(value['収支'])
            for entry,value in new.items():
                if entry not in prior:totals['新規経路取引数']+=1;totals['新規経路収支']+=value['収支']
            label='|'.join(key)
            if label in traces:
                assert traces[label]['基準']==list(prior.values())
                expected=dict(全取引=list(new.values()),元新規の対応=[dict(元組=v['組'],再生=new.get(entry)) for entry,v in prior.items()])
                assert expected==traces[label]['変更'][ident];trace_count+=1
        for symbol,actual in calc.items():
            compared+=same_fields(actual,matches[ident][symbol],(ident,symbol))
            change=actual['元勝ち対応の収支変化']+actual['元負け対応の収支変化']-actual['元勝ち未対応の元利益']+actual['元負け未対応の元損失']+actual['新規経路収支']
            assert abs(change-(result['periods']['全30'][symbol]['net']-base['periods']['全30'][symbol]['net']))<1e-6
    proof=dict(合格=True,条件数=18,比較項目数=compared,診断口座条件数=trace_count,
        同一新規分解と完全再生の収支差一致=True,旧15秒入口と追加5秒条件の区別は入口監査を併読=True,
        対象={str(path.relative_to(HERE.parent)):study.digest(path) for path in (HERE.parent/'analysis').glob('*.json')},
        新損益探索=0,API取得=0,実注文=0)
    save(HERE/'効果集計と同一新規分解と表示時刻監査.json',proof)
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
