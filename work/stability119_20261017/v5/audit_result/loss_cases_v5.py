"""既所有結果と組cacheだけから四条件の最悪場・大損失親を抜き出す。"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
V5 = HERE.parent
JST = timezone(timedelta(hours=9))
REASONS = {1: '固定中心へ復帰', 2: '入口残差から外側2σ', 3: '組清算時価の円損失', 4: '片脚60秒期限', 5: '場末返済'}


def clock(epoch: float) -> str:
    """
    機能: 保存価格時計を日本時刻へ整形する。
    引数: epoch(float) はepoch秒。
    返り値: str は年月日と時分秒。受信時計とは呼ばない。
    """
    return datetime.fromtimestamp(float(epoch), JST).strftime('%m/%d %H:%M:%S')


def yen(value: float) -> str:
    """
    機能: 損益を符号付き円表記へ整形する。
    引数: value(float) は円額。
    返り値: str は小数一桁の円額。
    """
    return f'{float(value):+,.1f}円'


def main() -> None:
    """
    機能: 四政策の最悪セッション中の最大損失親を小JSON/Markdownへ保存する。
    引数: なし。原cacheを再読せず、私有同bytes保全物だけ使う。
    返り値: None。事後診断であり、候補の選び直しや金融再実行は0。
    """
    result = json.loads((HERE / 'owned/完成結果.json').read_text(encoding='utf-8'))
    diagnostic = {(r['session'], r['method']): r for r in result['diagnostics']}
    cases, cache = [], {}
    for spec in result['specs']:
        rows = [r for r in result['runs'] if r['method'] == spec['id']]
        worst = min(rows, key=lambda r: (r['net'], r['session']))
        scene = worst['session']
        if scene not in cache:
            payload = (HERE / 'owned/PAIR' / (scene + '.npz')).read_bytes()
            with np.load(BytesIO(payload), allow_pickle=False) as saved:
                cache[scene] = {key: saved[key].copy() for key in saved.files}
        parents = cache[scene][spec['id'] + '__parents']
        parent = min(parents, key=lambda r: (r[28], r[0]))
        pid = int(parent[0])
        own = cache[scene][spec['id'] + '__orders']
        own = own[own[:, 0] == pid]
        split = next(r for r in diagnostic[scene, spec['id']]['parents'] if r['parent'] == pid)
        cases.append(dict(method=spec['id'], session=scene, session_net=worst['net'], parent=pid,
            reason=REASONS[int(parent[5])], decision_time=clock(parent[3]), exit_decision_time=clock(parent[4]),
            quantity_nk=int(parent[12]), quantity_top=int(parent[13]), side_nk='買' if parent[2] == 1 else '売',
            side_top='売' if parent[2] == 1 else '買', entry_nk=parent[14], entry_top=parent[15],
            exit_nk=parent[16], exit_top=parent[17], entry_time_nk=clock(parent[18]), entry_time_top=clock(parent[19]),
            exit_time_nk=clock(parent[20]), exit_time_top=clock(parent[21]), gross_nk=parent[22], gross_top=parent[23],
            net=parent[28], beta=parent[6], delta=parent[9], sigma=parent[8],
            relative=split['relative_gross'], common=split['common_gross'], gross=split['gross'], fees=split['fees'],
            orders=[dict(leg='NK' if r[1] == 0 else 'TOPIX', kind='新規' if r[2] == 1 else '返済',
                side='買' if r[3] == 1 else '売', quantity=int(r[4]), time=clock(r[6]), price=r[8], fee=r[9]) for r in own]))
    target = HERE / '四政策の最悪場と最大損失親.json'
    assert not target.exists()
    target.write_text(json.dumps(dict(cases=cases, 原cache再読=0, 原市場読取=0, 金融再実行=0),
                                 ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    lines = ['# NT四条件の最悪場で何が起きたか', '',
        '各条件の収支が最も悪い場から、最大損失の親を1件ずつ示す。時計は日本の価格時計。既所有copyだけの事後会計であり、新しい金融再生ではない。', '']
    for case in cases:
        c = case
        lines += [f"## {c['method']}：{c['session']}（場収支{yen(c['session_net'])}）", '',
            f"{c['decision_time']}に予約。NK{c['side_nk']}{c['quantity_nk']}枚／TOPIX{c['side_top']}{c['quantity_top']}枚。{c['exit_decision_time']}に「{c['reason']}」で返済判断。", '',
            '| 脚 | 新規約定 | 返済約定 | gross |', '|---|---|---|---:|',
            f"| NKmicro | {c['entry_time_nk']}・{c['entry_nk']:g} | {c['exit_time_nk']}・{c['exit_nk']:g} | {yen(c['gross_nk'])} |",
            f"| TOPIXmini | {c['entry_time_top']}・{c['entry_top']:g} | {c['exit_time_top']}・{c['exit_top']:g} | {yen(c['gross_top'])} |", '',
            f"相対成分 **{yen(c['relative'])}** ＋ 共通元本差成分 **{yen(c['common'])}** − 手数料 **{c['fees']:,.0f}円** ＝ **純損益{yen(c['net'])}**。", '']
        if c['relative'] < 0 and abs(c['relative']) > abs(c['common']):
            lines += ['中心へ戻る仮説と反対に、二脚の相対変化が損失の中心となった。整数端数や手数料だけを修正しても、この親の主因は残る。', '']
        elif c['common'] < 0 and abs(c['common']) > abs(c['relative']):
            lines += ['この親では共通元本差成分の損失が相対成分より大きい。予約時の整数ヘッジだけで実建値・非同時保有を完全相殺できていない。', '']
    lines += ['相対・共通の分解は実建値と実返済値による恒等式で、真の市場因果の特定ではない。単一の最悪親から後付けの除外条件は追加していない。']
    output = V5 / 'design/四政策の最悪場で損失を生んだ二脚.md'
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists()
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(cases, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
