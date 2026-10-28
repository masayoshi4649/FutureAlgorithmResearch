"""移植照合の保存結果だけを独立会計し、完了・途中を分けた監査報告を作る。"""
from pathlib import Path
from collections import defaultdict
import hashlib
import json
import statistics

HERE = Path(__file__).resolve().parent


def read(path: Path) -> dict:
    """機能: 保存済みJSONを読む。引数: path(Path)。返り値: dict。"""
    return json.loads(path.read_text(encoding='utf-8-sig'))


def close(a: float, b: float) -> None:
    """機能: 会計の絶対誤差を検査する。引数: a/b(float)。返り値: None。"""
    assert abs(a-b) < 1e-7, (a, b)


def account(case: dict, scene: dict) -> dict:
    """機能: 新規約定とTargetsから全玉・親会計を再構成する。引数: case/scene(dict)。返り値: dict。"""
    lots, parents = {}, defaultdict(lambda: {'quantity': 0, 'remaining': 0, 'net': 0.0})
    gross = 0.0
    for event in case['events'] or []:
        signal, fill = event['signal'], event['fill']
        key = (signal['owner'], signal['campaign'])
        assert event['fill_index'] > event['decision_index'] == signal['source_index']
        assert signal['quantity'] == fill['Quantity']
        subtotal = 0.0
        if signal['action'] == 'new':
            ident = fill['HoldID']
            assert ident not in lots
            lots[ident] = {'side': signal['side'], 'remaining': fill['Quantity'], 'price': fill['Price'], 'parent': key}
            parents[key]['quantity'] += fill['Quantity']
            parents[key]['remaining'] += fill['Quantity']
        else:
            assert signal['action'] == 'close'
            targets = signal['targets']
            assert sum(t['quantity'] for t in targets) == fill['Quantity']
            for target in targets:
                lot = lots[target['id']]
                assert lot['side'] == -signal['side'] and lot['parent'] == key
                assert lot['remaining'] >= target['quantity'] > 0
                pnl = lot['side'] * target['quantity'] * (fill['Price']-lot['price']) * 100
                lot['remaining'] -= target['quantity']
                parents[key]['remaining'] -= target['quantity']
                parents[key]['net'] += pnl
                subtotal += pnl
        close(subtotal, event['gross'])
        gross += subtotal
    close(gross, case['gross'])
    assert sum(l['remaining'] for l in lots.values()) == case['remaining']
    closed = [p['net'] for p in parents.values() if p['remaining'] == 0]
    open_realized = sum(p['net'] for p in parents.values() if p['remaining'] > 0)
    profit = sum(max(0,n) for n in closed)
    loss = -sum(min(0,n) for n in closed)
    close(profit-loss+open_realized,gross)
    return {'session':scene['session'],'kind':scene['kind'],'partial':scene['partial'],'method':case['method'],
            'signals':case['signals'],'fills':case['fills'],'profit':profit,'loss':loss,'gross':gross,
            'open_parent_realized':open_realized,'unrealized':case['unrealized'],'equity':gross+case['unrealized'],
            'remaining':case['remaining'],'pending':case['pending'],'parents':len(parents),'closed_parents':len(closed),'equal':case['equal']}


def main() -> None:
    """機能: 完了済み79照合の独立会計と前後不変を要約する。引数: なし。返り値: None。"""
    execution = read(HERE/'金融実行155.json')
    assert execution['終了コード'] == 0 and execution['前後改変数'] == 0 and execution['一致条件場数'] == 79
    files = sorted((HERE/'results').glob('*.json'))
    assert len(files) == 52
    rows = []
    for file in files:
        report = read(file)
        for case in report['cases']:
            assert case['equal'] is True
            rows.append(account(case, report['scene']))
    assert len(rows) == 79
    complete = [r for r in rows if not r['partial']]
    partial = [r for r in rows if r['partial']]
    assert len(complete) == 77 and len(partial) == 2
    summary = []
    for method, kind in [('D07','Day'),('D07','Night'),('S01','Day')]:
        part = [r for r in complete if r['method']==method and r['kind']==kind]
        summary.append({'method':method,'kind':kind,'sessions':len(part),'gross':sum(r['gross'] for r in part),
                        'profit':sum(r['profit'] for r in part),'loss':sum(r['loss'] for r in part),
                        'losing_sessions':sum(r['gross']<0 for r in part),'median_session':statistics.median(r['gross'] for r in part),
                        'signals':sum(r['signals'] for r in part),'fills':sum(r['fills'] for r in part)})
    out = {'purpose':'研究00154から実アプリへの同値照合。新たな収益性の証拠ではない。',
           'complete_sessions':51,'partial_sessions':1,'total_cases':79,'same_order_fill_cases':79,
           'independent_accounting_cases':79,'source_data_expected_changes':0,'summary':summary,
           'complete_rows':complete,'partial':partial,'execution':execution,
           'result_fingerprints':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
    (HERE/'report155.json').write_text(json.dumps(out, ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'summary':summary,'partial':partial,'fills':sum(r['fills'] for r in rows)},ensure_ascii=False))


if __name__=='__main__':
    main()
