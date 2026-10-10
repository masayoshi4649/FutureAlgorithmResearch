"""前回の到達率と対称先着の差を、新出口検証前の独立監査として記録する。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v64/最大順行と入口採点.json'


def main():
    """機能: 旧23入口の到達と先着を件数照合し、新出口評価の注意を保存する。

    引数: なし。返り値: なし(None)。新規注文、条件変更、API取得は行わない。
    """
    packet=json.loads(SOURCE.read_text(encoding='utf-8'))
    method=next(m for m in packet['methods'] if m['number']==3)
    rows=[r for r in packet['rows'] if r['method']==method['id'] and r['symbol']=='NK225']
    labels=[r['extent']['到達']['0.10'] for r in rows]
    counts=dict(入口数=len(rows),順行到達=sum(x['順行到達'] for x in labels),逆行到達=sum(x['逆行到達'] for x in labels),
        両側到達=sum(x['順行到達'] and x['逆行到達'] for x in labels),順行先着=sum(x['先着']==1 for x in labels),
        逆行先着=sum(x['先着']==-1 for x in labels),未到達=sum(x['先着']==0 for x in labels),
        順行到達したが先に逆行した数=sum(x['順行到達'] and x['先着']==-1 for x in labels))
    assert counts==dict(入口数=23,順行到達=22,逆行到達=17,両側到達=16,順行先着=14,逆行先着=9,未到達=0,順行到達したが先に逆行した数=8)
    summary=method['summary']['NK225']['到達']['0.10']
    assert summary['順行到達']==counts['順行到達'] and summary['順行先着']==counts['順行先着']
    widths=[r['decision_mid']*.0001 for r in rows]
    report=dict(対象='候補3の旧実新規判断23件・NK',元採点SHA256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        件数=counts,順行到達率=22/23,順行先着率=14/23,
        判断中値に対する0_01パーセント幅=dict(最小=min(widths),最大=max(widths),参照ラージ呼値=10),
        注意=['22/23はセッション末まで一度でも0.1%順行した割合。8件は同幅逆行が先なので同幅損切りを追加しても95.7%勝つ根拠にはならない。',
        '旧起点は判断中値。新検証は次行の実新規売買気配起点へ変わるため、旧9件の逆行先着と新実損切り件数は一致を保証しない。',
        '0.01%トレールは参照ラージ呼値未満。板価格が線を飛び越え、さらに次行で約定するため、0.1%利益線の厳密な利益保証とはならない。',
        '順行判定と最高有利値は買いなら返済可能bid、売りなら返済可能askで観測し、新規約定価格と同じ定義で比較する。',
        '実約定がセッション末の次行に不足する場合は失敗として区別し、事後に最後の行へ約定を戻さない。',
        '新規と返済それぞれに手数料を課金する。ラージ板によるmicro/mini約定の代理である限界を説明する。',
        '旧23入口は旧出口・休止で選別済み。独立出口差し替え23試行と、同時保有上限を守った実戦1口座PLは区別する。',
        '実戦再生なら元の因果的候補列から新保有状態に応じて再選別し、実取引件数の変更を許す。',
        '保護前損切り→保護発動→以後最高有利値から0.01%線、という状態を順序通り記録する。判定後の約定価格で発動前の状態を未来にさかのぼって変更しない。'])
    (HERE/'入口到達と新出口の事前監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
