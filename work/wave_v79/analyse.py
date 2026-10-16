"""全防止条件の会計差と、元の各新規に対応する実際の再生返済を整理する。"""

from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import pickle
import sys

sys.dont_write_bytecode=True
import experiment as study

HERE=Path(__file__).resolve().parent
JST=timezone(timedelta(hours=9))


def stamp(value: float) -> str:
    """機能: 原本の代理時計を日本時間で表示する。

    引数: value(float)。返り値: 日本時間文字列(str)。
    """
    return datetime.fromtimestamp(float(value),JST).isoformat()


def records(ledger: dict,ready: dict) -> dict:
    """機能: 取引を新規判断行と方向で対応させる。

    引数: ledger/ready(dict)。返り値: 新規キーと取引表示(dict)。
    後の注文経路が変わるため、元取引除外だけを新損益として扱わない。
    """
    output={};times=ready['time_s']
    for trade in ledger['trades']:
        cid=int(trade[0]);orders=ledger['orders'][ledger['orders'][:,2]==cid]
        first=orders[orders[:,7]==1][0];last=orders[orders[:,7]==0][-1]
        key=(int(first[1]),int(trade[3]))
        output[key]=dict(組=cid,判断行=key[0],方向=key[1],新規判断=stamp(times[key[0]]),新規約定=stamp(times[int(first[0])]),
            返済判断=stamp(times[int(last[1])]),返済約定=stamp(times[int(last[0])]),新規価格=float(trade[5]),返済価格=float(trade[6]),
            収支=float(trade[10]),返済理由=int(last[6]))
    return output


def main() -> None:
    """機能: 全18条件を選び直さず、利益喪失と損失減少を分けて保存する。

    引数: なし。返り値: なし(None)。
    """
    fixed=study.load(HERE/'事前固定.json');materials=study.material(5)
    base=study.load(HERE/'results/E0_X0.json');base_ledger=study.load(HERE/'ledgers/E0_X0.pkl')
    output=[];cases={};matches={}
    base_records={key:records(ledger,materials[0][key]) for key,ledger in base_ledger.items()}
    for c in fixed['条件']:
        result=study.load(HERE/'results'/f'{c["id"]}.json');ledgers=study.load(HERE/'ledgers'/f'{c["id"]}.pkl')
        item=dict(id=c['id'],期間={},遅延={});matched={s:dict(元勝ち数=0,元負け数=0,元勝ち対応数=0,元勝ち対応の収支変化=0.,元負け対応数=0,元負け対応の収支変化=0.,元勝ち未対応数=0,元勝ち未対応の元利益=0.,元負け未対応数=0,元負け未対応の元損失=0.,新規経路取引数=0,新規経路収支=0.) for s in study.SYMBOLS}
        for period,values in result['periods'].items():
            item['期間'][period]={}
            for s,a in values.items():
                b=base['periods'][period][s]
                item['期間'][period][s]=dict(a,収支変化=a['net']-b['net'],利益変化=a['profit']-b['profit'],損失削減=b['loss']-a['loss'])
        for delay in (1,5,15):
            dbase=study.output_base(delay)
            dr=study.load(dbase/'results'/f'{c["id"]}.json');db=study.load(dbase/'results/E0_X0.json')
            item['遅延'][delay]={s:dict(dr['periods']['全30'][s],収支変化=dr['periods']['全30'][s]['net']-db['periods']['全30'][s]['net']) for s in study.SYMBOLS}
        for key,ledger in ledgers.items():
            new=records(ledger,materials[0][key]);old=base_records[key];m=matched[key[1]]
            for entry,v in old.items():
                name='元勝ち' if v['収支']>0 else '元負け';m[name+'数']+=1
                if entry in new:
                    m[name+'対応数']+=1;m[name+'対応の収支変化']+=new[entry]['収支']-v['収支']
                else:
                    m[name+'未対応数']+=1;m[name+'未対応の元'+('利益' if name=='元勝ち' else '損失')]+=abs(v['収支'])
            for entry,v in new.items():
                if entry not in old:m['新規経路取引数']+=1;m['新規経路収支']+=v['収支']
            if key[0] in fixed['商品別赤字上位3'][key[1]]:
                label='|'.join(key)
                if label not in cases:cases[label]=dict(基準=list(old.values()),変更={})
                cases[label]['変更'][c['id']]=dict(全取引=list(new.values()),元新規の対応=[dict(元組=v['組'],再生=new.get(entry)) for entry,v in old.items()])
        matches[c['id']]=matched;output.append(item)
    study.save(HERE/'analysis/全条件の効果.json',output)
    study.save(HERE/'analysis/同じ新規の勝ち損失と新規経路.json',dict(注意='同一新規対応は診断用。見送りで保有状態が変わるため、効果は必ず全再生収支で評価する。未対応の利益は新方式の確定損失ではない。',条件=matches))
    study.save(HERE/'analysis/赤字上位6口座の再生時刻.json',cases)
    print('18条件・全期間・3遅延・6口座時刻を保存')


if __name__=='__main__':
    main()
