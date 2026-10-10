"""指定した勝敗例について、制御成立時の過去最大順行を再確認する。"""

from datetime import datetime,timezone,timedelta
import gzip
import json
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent
OLD=HERE.parents[1]/'wave_v67'
JST=timezone(timedelta(hours=9))


def read(path:Path)->dict:
    """機能: 既存圧縮JSONを読む。

    引数: path(Path)。返り値: 結果(dict)。
    """
    return json.loads(gzip.decompress(path.read_bytes()))


def iso(stamp:float)->str:
    """機能: 原本秒を日本時間にする。

    引数: stamp(float)。返り値: 時刻(str)。
    """
    return datetime.fromtimestamp(stamp,JST).isoformat()


def main()->None:
    """機能: 代表例を指定して原本行で照合する。

    引数: なし。返り値: なし(None)。
    """
    requested=[
        ('E01_T05X','TOPIX','2026-10-01_Day','2026-10-01T10:12:42+09:00'),
        ('E01_T05X','TOPIX','2026-10-08_Night','2026-10-08T18:09:19+09:00'),
        ('E01_T05X','NK225','2026-10-02_Day','2026-10-02T09:52:34+09:00'),
        ('E01_T05X','NK225','2026-09-29_Day','2026-09-29T09:51:41+09:00'),
        ('R01_P2T','TOPIX','2026-09-30_Night','2026-09-30T21:52:54+09:00'),
        ('R01_P2T','TOPIX','2026-10-05_Night','2026-10-05T20:13:36+09:00'),
        ('R01_P2T','NK225','2026-09-30_Day','2026-09-30T11:26:19+09:00'),
        ('R01_P2T','NK225','2026-10-08_Night','2026-10-09T01:54:13+09:00'),
        ('E01_P2T','TOPIX','2026-10-01_Night','2026-10-01T19:26:15+09:00'),
    ]
    results={code:read(SOURCE/f'observed/{code}.json.gz') for code in {r[0] for r in requested}|{'E01','R01'}}
    inputs={}
    for folder in sorted((OLD/'prepared').iterdir()):
        if (folder/'new_inputs.pkl').exists():
            inputs.update(pickle.loads((folder/'new_inputs.pkl').read_bytes()))
    output=[]
    for code,symbol,session,stamp in requested:
        base=results[code]['variant']['base']
        original=next(l for l in results[base]['ledgers'] if l['session']==session and l['symbol']==symbol)
        modified=next(l for l in results[code]['ledgers'] if l['session']==session and l['symbol']==symbol)
        first=next(t for t in original['trades'] if iso(t['新規時刻'])==stamp)
        trades=[t for t in original['trades'] if t['組']==first['組']]
        new=[t for t in modified['trades'] if t['新規行']==first['新規行']]
        ready=inputs[session,symbol]
        row=first['新規行']
        atr=next(c[5] for c in original['cycles'] if c[0]==first['組'])
        entry=first['建値'];direction=first['方向']
        item=dict(改修=code,銘柄=symbol,セッション=session,新規時刻=stamp,方向=direction,
            基準収支=sum(t['収支'] for t in trades),改修収支=sum(t['収支'] for t in new) if new else None,
            基準最終返済時刻=iso(max(t['返済時刻'] for t in trades)),
            新規行=row,初回ATR=atr,改修の新規なし=not new)
        if new:
            event=next(t for t in new if t['理由']==51)
            order=next(o for o in modified['orders'] if o[0]==event['返済行'] and o[6]==51)
            trigger=int(order[1]);fill=int(order[0])
            gain=direction*(ready['last'][row:trigger+1]-entry)/atr
            assert trigger<fill
            item.update(成立時刻=iso(ready['time_s'][trigger]),返済時刻=iso(ready['time_s'][fill]),
                成立経過分=float((ready['time_s'][trigger]-ready['time_s'][row])/60),
                成立時順行ATR=float(gain[-1]),成立までの最大順行ATR=float(max(0,gain.max())),
                成立原本行=int(ready['seq'][trigger]),返済原本行=int(ready['seq'][fill]))
            assert item['成立経過分']>=5 and item['成立までの最大順行ATR']<.5
            assert item['成立時順行ATR']<=-.25+1e-8
        else:
            events=[e for e in modified['risk_events'] if e[2]==3 and e[3]==60 and ready['time_s'][int(e[0])]<=first['新規時刻']]
            assert events
            pause=events[-1];start=float(ready['time_s'][int(pause[0])])
            item.update(休止開始=iso(start),休止終了=iso(start+1800),
                休止開始から元入口までの分=(first['新規時刻']-start)/60)
            assert first['新規時刻']<start+1800
        output.append(item)
    (HERE/'代表例の成立時点照合.json').write_text(json.dumps(output,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')
    print('代表9例の成立時点を照合しました',flush=True)


if __name__=='__main__':
    main()
