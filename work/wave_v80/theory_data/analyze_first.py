"""初回の前半結果だけを使い、秒売買の損失構造を再集計する。"""

from pathlib import Path
import hashlib
import json
import pickle
import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
FAMILIES = ('単独OFI先行', '二市場OFI先行', '共同価格追随', '先行追随',
            '押し戻し後フロー反転', '失速逆張', '同価格表示回復', '無方向交互')
REASONS = {1: '固定損切り', 2: '小幅利確', 3: '保有期限', 4: '場内撤収', 5: '利益追跡'}
UNIT = {'TOPIX': 5000., 'NK225': 2000.}
POINT = {'TOPIX': 10000., 'NK225': 200.}


def sha(path):
    """
    機能: 読み取った入力ファイルのハッシュを計算する。
    引数: path (Path) は読取対象。
    返り値: str のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distribution(values):
    """
    機能: 条件間の分布を示し、同一取引の重複合算を避ける。
    引数: values (list) は条件別の数値又はNone。
    返り値: dict の件数・最小・中央値・最大。
    """
    clean = [float(x) for x in values if x is not None and np.isfinite(x)]
    if not clean:
        return {'件数': 0, '最小': None, '中央値': None, '最大': None}
    return {'件数': len(clean), '最小': min(clean), '中央値': float(np.median(clean)), '最大': max(clean)}


def ledger_diagnosis(ledger, symbol, front):
    """
    機能: 保存済み台帳の実保有時間と返済判断後の変化を集計する。
    引数: ledger (dict) は初回台帳、symbol (str) は商品、front (list) は前16場。
    返り値: dict の保有時間・約定待ち・返済理由別の実績。売買の再生は行わない。
    """
    hold, wait, entry_wait, exit_wait = [], [], [], []
    reasons = {name: [] for name in REASONS.values()}
    for (session, name), record in ledger.items():
        assert session in front, '前半以外の台帳は解析しない'
        if name != symbol:
            continue
        orders, trades, events = record['orders'], record['trades'], record['events']
        by_id = {int(t[0]): t for t in trades}
        entry = {int(o[2]): o for o in orders if o[7] == 1}
        decisions = {int(e[1]): e for e in events if e[2] == 24}
        for order in orders:
            duration = float(order[12] - order[10])
            wait.append(duration)
            (entry_wait if order[7] == 1 else exit_wait).append(duration)
            if order[7] == 1:
                continue
            cid, code = int(order[2]), int(order[6])
            trade, opening, decision = by_id[cid], entry[cid], decisions[cid]
            held = float(order[12] - opening[12]); hold.append(held)
            trigger_gross = float(trade[3] * (decision[5] - trade[5]) * POINT[symbol])
            actual_gross = float(trade[9])
            reasons[REASONS[code]].append({
                '収支': float(trade[10]), '費用前損益': actual_gross,
                '返済判断気配での費用前損益': trigger_gross,
                '返済判断後の追加悪化': trigger_gross - actual_gross,
                '保有秒': held, '返済待ち秒': duration,
            })
    summary = {}
    for reason, items in reasons.items():
        if not items:
            continue
        summary[reason] = {
            '取引数': len(items), '収支': sum(x['収支'] for x in items),
            '平均費用前損益tick': float(np.mean([x['費用前損益'] for x in items])) / UNIT[symbol],
            '平均判断時費用前損益tick': float(np.mean([x['返済判断気配での費用前損益'] for x in items])) / UNIT[symbol],
            '返済判断後の追加悪化': sum(x['返済判断後の追加悪化'] for x in items),
            '返済待ちで黒字判断から赤字決済': sum(x['返済判断気配での費用前損益'] > (836 if symbol == 'TOPIX' else 440) and x['収支'] < 0 for x in items),
            '返済待ちで有利': sum(x['返済判断後の追加悪化'] < 0 for x in items),
            '返済待ちで不利': sum(x['返済判断後の追加悪化'] > 0 for x in items),
            '保有秒': distribution([x['保有秒'] for x in items]),
        }
    return {'実保有秒': distribution(hold), '全注文待ち秒': distribution(wait),
            '新規注文待ち秒': distribution(entry_wait), '返済注文待ち秒': distribution(exit_wait),
            '返済理由': summary}


# ----------------------------------------
def condition_summary(result, ledger, front, symbol):
    """
    機能: 一条件一商品の前16会計をラージ呼値単位でも説明する。
    引数: result (dict) は初回結果、ledger (dict) は台帳、front (list)、symbol (str)。
    返り値: dict の会計と損失構造。中値換算は同一実取引経路の差額恒等式。
    """
    config = result['config']; a = result['periods']['前16'][symbol]
    rows = [r for r in result['rows'] if r['symbol'] == symbol]
    assert len(rows) == 16 and set(r['session'] for r in rows) == set(front)
    n, unit = int(a['trades']), UNIT[symbol]
    mid = float(a['gross'] + a['spread_drag'])
    assert abs(mid - a['spread_drag'] - a['fees'] - a['net']) < 1e-6
    out = dict(config)
    out.update({'商品': symbol, '系統': FAMILIES[config['signal']],
        '取引数': n, '取引場数': a['active_sessions'], '黒字場数': a['winning_sessions'],
        '利益': a['profit'], '損失': a['loss'], '収支': a['net'], '費用前損益': a['gross'],
        '手数料': a['fees'], '同約定行の中値からの約定差': a['spread_drag'],
        '同一経路の中値進行': mid, '判断時気配から約定への不利額': a['decision_to_fill_cost'],
        '平均保有秒': a['average_hold_seconds'], '勝率': a['win_rate'],
        '平均勝ち負け比': a['payoff'], '送信判断数': a['entry_requests'],
        '取消不成立数': a['cancellations'], '到達予定から更に5秒超待ち': a['delayed_gap_fills'],
        '約定率': n / a['entry_requests'] if a['entry_requests'] else None})
    for key, value in [('収支', a['net']), ('中値進行', mid), ('約定差', a['spread_drag']),
                       ('手数料', a['fees']), ('判断後不利', a['decision_to_fill_cost'])]:
        out[f'1組当たり{key}tick'] = float(value / n / unit) if n else None
    detail = ledger_diagnosis(ledger, symbol, front)
    assert sum(v['取引数'] for v in detail['返済理由'].values()) == n
    assert abs(sum(v['収支'] for v in detail['返済理由'].values()) - a['net']) < 1e-6
    out['台帳診断'] = detail
    return out


def group_summary(rows, keys):
    """
    機能: 同じ属性を持つ条件の分布を集計する。
    引数: rows (list) は一条件一商品結果、keys (tuple) はグループ属性。
    返り値: list の条件分布。条件を独立試行とする有意差推定は行わない。
    """
    groups = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        groups.setdefault(key, []).append(row)
    out = []
    fields = ('取引数', '取引場数', '収支', '平均保有秒', '勝率', '約定率',
              '1組当たり収支tick', '1組当たり中値進行tick', '1組当たり約定差tick',
              '1組当たり手数料tick', '1組当たり判断後不利tick')
    for key, items in sorted(groups.items()):
        item = dict(zip(keys, key)); item['条件数'] = len(items)
        item['取引あり条件数'] = sum(x['取引数'] > 0 for x in items)
        item['黒字条件数'] = sum(x['収支'] > 0 for x in items)
        item['中値進行が正の条件数'] = sum(x['同一経路の中値進行'] > 0 for x in items)
        item['判断後価格が合計有利な条件数'] = sum(x['判断時気配から約定への不利額'] < 0 for x in items)
        for field in fields:
            item[field] = distribution([x[field] for x in items])
        out.append(item)
    return out


def matched_modes(rows):
    """
    機能: 入口・利確損切り・休止が同じ注文方法の組を並べる。
    引数: rows (list) は一条件一商品会計。
    返り値: list のM0/M1/M2比較。約定経路の違いを純粋な遅延効果と扱わない。
    """
    groups = {}
    for row in rows:
        key = (row['signal'], row['profile'], row['cooldown'], row['商品'])
        groups.setdefault(key, {})[row['entry_mode']] = row
    out = []
    fields = ('id', '取引数', '収支', '約定率', '平均保有秒', '1組当たり収支tick',
              '1組当たり中値進行tick', '1組当たり約定差tick', '1組当たり判断後不利tick')
    for key, modes in sorted(groups.items()):
        assert set(modes) == {0, 1, 2}
        out.append({'signal': key[0], 'profile': key[1], 'cooldown': key[2], '商品': key[3],
                    '注文方法': {f'M{m}': {f: row[f] for f in fields} for m, row in sorted(modes.items())}})
    return out


# ----------------------------------------
def main():
    """
    機能: 前16の既存結果だけを読み、損失構造と原因に基づく追加案を保存する。
    引数: なし。
    返り値: なし。担当領域へJSON二件を作成し、要点を標準出力する。
    """
    front = json.loads((BASE / '初回事前固定.json').read_text(encoding='utf-8'))['前16']
    paths = sorted((BASE / 'first/results').glob('*.json'))
    assert len(paths) == 288
    rows, sources = [], []
    for path in paths:
        result = json.loads(path.read_text(encoding='utf-8'))
        assert result['config']['latency'] == 5 and result['config']['repair_mode'] == 0
        assert set(r['session'] for r in result['rows']) == set(front)
        ledger_path = BASE / 'first/ledgers' / (path.stem + '.pkl')
        ledger = pickle.loads(ledger_path.read_bytes())
        for symbol in ('TOPIX', 'NK225'):
            rows.append(condition_summary(result, ledger, front, symbol))
        sources.append({'結果': path.relative_to(BASE).as_posix(), '結果SHA256': sha(path),
                        '台帳SHA256': sha(ledger_path)})
    metadata = {
        '範囲': '初回288条件の前16場だけ。新たな売買再生なし。改修結果・後14結果は参照しない。',
        '比較単位': '同一商品の条件別分布。同じ相場を条件違いで繰り返しており、条件数を独立標本数にしない。',
        '呼値': '観測ラージTOPIX0.5pt、NK22510円。TOPIXミニ10枚で1呼値5000円、日経マイクロ20枚で1呼値2000円。',
        '会計恒等式': '同一経路の中値進行−同約定行の中値からの約定差−手数料＝収支。中値進行は売買条件と約定行を固定した説明用差額で、実行可能な中値取引の成績ではない。',
        '遅延差額': '判断時の売買側気配と実約定値の差。正は不利、負は有利。気配差と重なる別基準なので重ねて控除しない。注文待ちをゼロにした戦略の反実仮想ではない。',
        'M2': '自己最良へ指し、到達後の相手気配が指値を1呼値貫通した時だけ当初指値で全約定。実キューが不明なための保守モデル。スプレッドを必ず受け取るモデルではない。',
        '前16': front, '入力': sources,
    }
    output = dict(metadata)
    output.update({'全条件': rows, '八系統の商品別分布': group_summary(rows, ('signal', '系統', '商品')),
                   '出口設計の商品別分布': group_summary(rows, ('profile', '商品')),
                   '注文方法の商品別分布': group_summary(rows, ('entry_mode', '商品')),
                   '八系統注文方法別': group_summary(rows, ('signal', '系統', 'entry_mode', '商品')),
                   '同一条件の注文方法比較': matched_modes(rows)})
    destination = HERE / '初回288条件の損失構造.json'
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for group in output['八系統の商品別分布']:
        print(group['系統'], group['商品'], '黒字条件', group['黒字条件数'], '組数', group['取引数']['中央値'],
              '組net呼値', group['1組当たり収支tick']['中央値'], '中値呼値', group['1組当たり中値進行tick']['中央値'])
    print('保存', destination)


if __name__ == '__main__':
    main()
