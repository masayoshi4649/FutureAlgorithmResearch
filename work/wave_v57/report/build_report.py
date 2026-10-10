"""事前主条件を維持した、補充3手法の損益レポートを生成する。"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
OUTPUT = ROOT / 'アルゴリズム調査/00054_補充監視3手法の実装とセッション損益'
FAMILIES = [
    dict(id='R1', name='吸収後反転',
         entry='売り側執行の代理が多い時に買い板の回復を確認。その後、買気配と中値が1呼値以上上がり、直近の買い側代理が売り側以上になれば買う。',
         middle='認定した壁の位置を固定し、中値の最高値を更新する。表示回復だけで反転したとは判断しない。',
         exit='壁の1呼値下と、最高中値から一定幅下の線を比べ、高い方に触れたら全返済。売りは反対。',
         counterexample='回復しても最後に買い供給が尽きれば、反転せず下へ進む。吸収した主体や動機は識別しない。'),
    dict(id='R2', name='補充切れ突破',
         entry='買い側執行の代理が多い時に売り板の回復を確認。その壁を気配が越えて2約定時計秒保ち、最後の回復から3秒以上なら買う。',
         middle='以前の売り壁を下側の保護線とし、中値の最高値を追う。壁が見えなくなっただけでは突破にしない。',
         exit='旧売り壁の1呼値下と、最高中値から一定幅下の線を比べ、高い方に触れたら全返済。売りは反対。',
         counterexample='一時的に売りが引かれただけなら、再供給されて抜けた価格から戻る。確認中に進行余地を使い切る場合もある。'),
    dict(id='R3', name='補充位置追従',
         entry='認定された買い板の回復価格が、前の認定価格より1呼値以上上へ移り、売気配も1呼値以上上がれば買う。',
         middle='新しい買い壁を保護線として固定し、中値の最高値を追う。追加玉は建てない。',
         exit='新しい買い壁の1呼値下と、最高中値から一定幅下の線を比べ、高い方に触れたら全返済。売りは反対。',
         counterexample='すでに起きた価格上昇を確認しただけで、参加後の余地がない場合がある。回復の追加価値は別の検証が必要。'),
]


def read(path: Path) -> dict:
    """機能: 日本語JSONを読み込む。

    引数: path(Path)。返り値: 内容(dict)。外部通信しない。
    """
    return json.loads(path.read_text(encoding='utf8'))


def reasons() -> dict:
    """機能: 売買器を実行せず、返済理由の定数だけ読む。

    引数: なし。返り値: 理由コードと表示名(dict)。
    """
    tree = ast.parse((WORK / 'engine.py').read_text(encoding='utf8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'REASONS' for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('返済理由の定義がありません')


def period_rows(method: dict, sessions: list[str]) -> dict:
    """機能: 保存済みの各評価価格の会計を期間・週へ合算する。

    引数: method(dict)、sessions(list[str])。返り値: 商品と評価価格別の表示行(dict)。
    注文や約定価格を再計算せず、保存されている場別損益と枚数を足す。
    """
    groups = {'前10場': sessions[:10], '次9場': sessions[10:19], '後4場': sessions[19:]}
    for session in sessions:
        day = datetime.strptime(session[:10], '%Y-%m-%d')
        week = (day - timedelta(days=day.weekday())).date().isoformat() + ' 週'
        groups.setdefault(week, []).append(session)
    output = {}
    fields = ('profit', 'loss', 'net', 'win_qty', 'loss_qty', 'flat_qty', 'cycles', 'wins', 'losses')
    for symbol in ('TOPIX', 'NK225'):
        output[symbol] = {}
        for mode in ('最後値', '中値', '売買気配'):
            rows = []
            for name, members in groups.items():
                accounts = [a for a in method['accounts'] if a['symbol'] == symbol and a['session'] in members]
                values = [a if mode == '最後値' else a['sensitivity'][mode] for a in accounts]
                rows.append(dict(name=name, **{k: sum(a[k] for a in values) for k in fields}))
            output[symbol][mode] = rows
    return output


def main() -> None:
    """機能: 全12条件を埋め込み、3章の暗色HTMLを生成する。

    引数: なし。返り値: なし(None)。主条件は事前のprimaryフラグを検証して維持する。
    """
    results = read(WORK / '売買結果.json')
    assert len(results['methods']) == 12
    assert len(results['sessions']) == 23
    sensitivity = {}
    periods = {}
    for method in results['methods']:
        method['main'] = method['primary']
        assert method['main'] == (method['count'] == 2 and method['width'] == 'W05')
        method['condition_label'] = f'回復{method["count"]}回・{100*method["fraction"]:.2f}%'
        sensitivity[method['id']] = {}
        for symbol, summary in method['summary'].items():
            sensitivity[method['id']][symbol] = [dict(name='理想・最後値', **{k: summary[k] for k in ('profit', 'loss', 'net')})]
            sensitivity[method['id']][symbol] += [dict(name=name, **value) for name, value in summary['sensitivity'].items()]
            for alternative in summary['sensitivity'].values():
                alternative['drawdown'] = None
        periods[method['id']] = period_rows(method, results['sessions'])
        for account in method['accounts']:
            assert not account['orders'] or len(account['orders'][0]) == 13
            account.pop('trades', None)
    assert {m['id'] for m in results['methods'] if m['main']} == set(results['meta']['main_ids'])
    for family in FAMILIES:
        selected = [m for m in results['methods'] if m['family'] == family['id']]
        assert len(selected) == 4 and sum(m['main'] for m in selected) == 1
    # ----------------------------------------
    # 結果評価文は別保存物から読み、表示処理で推奨条件を選ばない。
    evaluation_path = WORK / '報告評価.json'
    evaluation = read(evaluation_path) if evaluation_path.exists() else {
        'headline': '現在気配の中値で評価すると、全12条件・両銘柄とも赤字。今回の形では採用できません。',
        'findings': ['各手法の主条件は事前指定の回復2回・始値0.05%幅です。'],
        'audit': [],
    }
    payload = dict(results=results, families=FAMILIES, sensitivity=sensitivity, periods=periods,
                   evaluation=evaluation, reasons=reasons())
    content = (HERE / 'report_template.html').read_text(encoding='utf8').replace(
        '__DATA__', json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/'))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / '補充監視3手法の説明と損益.html'
    path.write_text(content, encoding='utf8')
    record = dict(主HTML=str(path), SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  バイト数=path.stat().st_size, 主条件=results['meta']['main_ids'],
                  手法数=len(results['methods']), 場数=len(results['sessions']),
                  口座数=sum(len(m['accounts']) for m in results['methods']),
                  全注文数=sum(len(a['orders']) for m in results['methods'] for a in m['accounts']),
                  現在API取得数=0)
    (OUTPUT / '生成記録.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(record, ensure_ascii=True))


if __name__ == '__main__':
    main()
