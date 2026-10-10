"""事後説明用の反例を、対応する全注文とともに抽出する。"""

from datetime import datetime
from zoneinfo import ZoneInfo
import pickle
import adaptive_runner as runner
import adaptive_assessment as assessment


def main() -> None:
    """機能: 両銘柄で後半の選択差Rが最も悪かった各一組を説明用に出す。

    引数: なし。返り値: なし (None)。方式選択や採否へ還流しない。
    """
    values=runner.read(runner.HERE/'主のみの分岐診断.json')['対応元組']
    fixed=runner.read(runner.HERE/'探索条件の固定.json')
    inputs=pickle.loads((runner.HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    records=[]
    for symbol in runner.SYMBOLS:
        selected=min((r for r in values if r['symbol']==symbol and r['session'] in fixed['後半7セッション'] and r['層']),key=lambda r:r['選択差R'])
        key=(selected['session'],symbol);ready=inputs[key];campaign=selected['campaign']
        modes={}
        for label,identifier in (('主案',assessment.PRIMARY),('回復待ち',assessment.SIGNAL),('時計待ち',assessment.CLOCK)):
            ledger=next(r for r in runner.read(runner.HERE/'ledgers'/(identifier+'.json.gz')) if (r['session'],r['symbol'])==key)
            cycle=next(c for c in ledger['cycles'] if int(c[0])==campaign)
            orders=[]
            for order in ledger['orders']:
                if int(order[2])!=campaign:continue
                orders.append(dict(時刻=datetime.fromtimestamp(ready['time_s'][int(order[0])],ZoneInfo('Asia/Tokyo')).isoformat(),
                    注文元時刻=datetime.fromtimestamp(ready['time_s'][int(order[1])],ZoneInfo('Asia/Tokyo')).isoformat(),
                    売買方向=int(order[3]),数量=int(order[4]),価格=order[5],理由=runner.engine.REASONS.get(int(order[6]),'初回新規' if int(order[6])==20 else str(int(order[6]))),
                    新規=bool(order[7])))
            modes[label]=dict(id=identifier,収支円=cycle[3]*ledger['config']['point_value'],注文=orders)
        records.append(dict(対応=selected,方式=modes))
    runner.save(runner.HERE/'分岐の反例.json',dict(説明用の事後抽出=True,条件再選択=False,採否変更=False,
        全補助と全独立監査の完了前=True,規則='後半7の銘柄ごとに選択差Rが最も悪い一組',例=records))
    for value in records:print(value)


if __name__=='__main__':main()
