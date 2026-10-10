"""現在の固定候補の途中会計を、既知区間と今回の追加区間に分けて表示する。"""

import csv
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
LIVE=HERE/'live'
OUT=HERE.parents[1]/'アルゴリズム調査'/'00058_場内完結の時間軸と積極度の再検証'
JST=timezone(timedelta(hours=9))


def stamp(value: float | None) -> str:
    """機能: 保存時計を日本時間で表示する。

    引数: value(float|None)、UNIX秒。返り値: 表示時刻(str)。
    """
    return datetime.fromtimestamp(value,JST).strftime('%Y/%m/%d %H:%M:%S') if value is not None else '期首'


def main() -> None:
    """機能: 確定済み現在結果から途中会計表と再読込検算付きCSVを作る。

    引数: なし。返り値: なし(None)。原本・候補・売買結果は変更しない。
    """
    rows=[]
    csv_rows=[]
    sources={}
    for name in ('現在方向性の途中損益.json','現在在庫の途中損益.json'):
        path=LIVE/name
        sources[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        result=json.loads(path.read_text(encoding='utf-8'))
        candidate=result['選定候補']['id']
        for account in sorted(result['accounts'],key=lambda a:(a['price_mode'],a['symbol']!='TOPIX')):
            before=account['既知境界']
            end=account['現在末尾']
            change=account['追加区間']
            assert abs(end['net']-before['net']-change['net'])<1e-6
            for phase in ('既知境界','現在末尾','追加区間'):
                state=account[phase]
                assert abs(state['gross_realized']-state['fees']+state['unrealized']-state['net'])<1e-6
                quantity=state if phase!='追加区間' else end
                csv_rows.append(dict(条件ID=candidate,セッション=account['session'],銘柄=account['symbol'],
                    価格仮定=account['price_mode'],区間=phase,
                    境界時計=stamp(state.get('time_s',state.get('保存時計'))) if phase!='追加区間' else '既知境界から現在末尾',
                    実現粗損益円=state['gross_realized'],発生手数料円=state['fees'],
                    含み損益または変化円=state['unrealized'],費用含み込み純収支または変化円=state['net'],
                    末尾買枚数=quantity['long_qty'],末尾売枚数=quantity['short_qty']))
            if account['price_mode']=='quote':
                rows.append([candidate,'TOPIX mini' if account['symbol']=='TOPIX' else 'NK225 micro',
                    before['net'],end['gross_realized'],f"{end['fees']:,.0f}",end['unrealized'],
                    end['net'],change['net'],f"買{end['long_qty']} / 売{end['short_qty']}"])
    assert len(rows)==4 and len(csv_rows)==24
    table=dict(headers=['固定条件','商品','既知境界の純損益円','現在までの実現粗損益円',
        '発生手数料円','現在の含み円','現在の累積純損益円','追加区間の純変化円','現在保有枚数'],rows=rows,sources=sources)
    (LIVE/'報告用途中会計.json').write_text(json.dumps(table,ensure_ascii=False,indent=2),encoding='utf-8')
    output=OUT/'現在確認の途中会計.csv'
    with output.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(csv_rows[0]));writer.writeheader();writer.writerows(csv_rows)
    with output.open(encoding='utf-8-sig',newline='') as f:
        assert list(csv.DictReader(f))==[{k:str(v) for k,v in row.items()} for row in csv_rows]
    # ----------------------------------------
    # 履歴の結論はそのまま残し、現在確認の説明だけ更新する。
    path=HERE/'報告判断.json'
    narrative=json.loads(path.read_text(encoding='utf-8'))
    narrative['現在確認']=[
        '取得前に固定した共通比較の参考候補D3_H240_W20_A0とI3_H240_D125_A0を、10/7ナイトの10/8 01:17:58取得分で確認しました。両候補とも履歴では赤字で、採用推奨ではありません。結果を見て差し替えていません。',
        '前回参照した00:14頃までの原本前半は完全一致。その区間を未知検証とは呼ばず、今回追加した約63分の資産変化を右から2列目に分けました。主評価は売買気配です。場がまだ終わっていないため、下表は最終セッション収支ではありません。',
        '累積純損益＝実現粗損益−全発生手数料＋全残玉の含み。残玉は買いをbid、売りをaskで評価し、まだ発生していない返済手数料は含めません。I3の日経の追加0円は、既知前半の22:58:55に損失予算へ達して取引停止済みのためです。無取引を成功とは扱いません。'
    ]
    path.write_text(json.dumps(narrative,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(表行数=len(rows),CSV行数=len(csv_rows),会計一致=True,現在表=rows),ensure_ascii=False))


if __name__=='__main__':
    main()
