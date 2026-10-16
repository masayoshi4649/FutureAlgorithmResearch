"""固定後の全場親会計と入口・返済・再参加の経路差を独立検算する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
JST = timezone(timedelta(hours=9))


def read(path: Path) -> object:
    """
    機能: 固定した条件と完成済み保存結果を読む。
    引数: path(Path)。
    返り値: object。JSON又はpickleの内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 読み取り資料の内容指紋を求める。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def clean(value: object) -> object:
    """
    機能: 独立診断を有限日本語JSON用標準型へ変換する。
    引数: value(object)。
    返り値: object。配列・数値の標準型。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def save(name: str, value: dict) -> None:
    """
    機能: 自担当review内だけに独立証拠を保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    target = HERE / name
    target.parent.mkdir(parents=True, exist_ok=True)
    assert target.resolve().is_relative_to(HERE.resolve())
    target.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                 allow_nan=False)+'\n', encoding='utf-8')


def module(name: str, path: Path) -> object:
    """
    機能: 入力と旧独立診断の読取関数を固有名で接続する。
    引数: name(str)、path(Path)。
    返り値: object。読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def totals(trades: np.ndarray) -> dict:
    """
    機能: 全親の純損益を源間相殺なしで独立集計する。
    引数: trades(ndarray、公開16列)。
    返り値: dict。利益・損失・枚数・平均勝負額。
    """
    values = trades[:, 11]
    wins, losses = values > 1e-5, values < -1e-5
    g, loss = float(values[wins].sum()), float(-values[losses].sum())
    nw, nl = int(wins.sum()), int(losses.sum())
    average_win, average_loss = g/nw if nw else None, loss/nl if nl else None
    return dict(profit=g, loss=loss, net=g-loss, gross=float(trades[:, 10].sum()),
        fees=float((trades[:, 8]+trades[:, 9]).sum()), campaigns=len(trades),
        winning_campaigns=nw, losing_campaigns=nl, flat_campaigns=len(trades)-nw-nl,
        winning_lots=int(trades[wins, 5].sum()), losing_lots=int(trades[losses, 5].sum()),
        flat_lots=int(trades[~(wins | losses), 5].sum()), lots=int(trades[:, 5].sum()),
        profit_share=g/(g+loss) if g+loss else None,
        average_win=average_win, average_loss=average_loss,
        payoff=average_win/average_loss if nw and nl else None)


def equal(actual: dict, expected: dict) -> None:
    """
    機能: 独立算出した会計の全項目を保存表へ照合する。
    引数: actual/expected(dict)。
    返り値: None。不一致は項目付き例外。
    """
    for name, value in actual.items():
        wanted = expected[name]
        assert value is None and wanted is None or value is not None and wanted is not None \
            and abs(float(value)-float(wanted)) < 1e-4, (name, value, wanted)


def check(result: dict, ledgers: dict, fixed: dict) -> dict:
    """
    機能: 全62口座の親・注文・料金・源・枚数上限と全期間会計を独立照合する。
    引数: result/ledgers/fixed(dict)。
    返り値: dict。確認件数。全行時価は別独立監査の範囲。
    """
    sessions = fixed['全31']
    assert len(result['rows']) == len(ledgers) == 62
    assert set(ledgers) == {(s, symbol) for s in sessions for symbol in SYMBOLS}
    orders_count = parent_count = 0
    for row in result['rows']:
        key = row['session'], row['symbol']
        account = ledgers[key]
        orders, trades = account['orders'], account['trades']
        multiplier, unit, cap = (1000., 41.8, 10) if key[1] == 'TOPIX' else (10., 11., 20)
        assert len(orders) == 2*len(trades)
        assert len(np.unique(orders[:, 16])) == len(orders)
        assert np.all(orders[:, 0] > orders[:, 1])
        assert not np.any(account['slots'][:, 0])
        assert not np.any(account['trace_changes'][-1, 1:])
        assert account['stats'][2] <= cap and account['stats'][3] <= cap
        pairs = {}
        for order in orders:
            assert order[9] == math.floor(float(order[5])*unit+1e-8)
            pairs.setdefault((int(order[2]), int(order[3])), []).append(order)
        for trade in trades:
            pair = pairs[int(trade[0]), int(trade[1])]
            assert len(pair) == 2
            entry, exit_order = pair
            assert entry[7] == 1 and exit_order[7] == 0
            assert entry[0] == trade[2] and exit_order[0] == trade[3]
            assert entry[1] == trade[15]
            assert entry[5] == exit_order[5] == trade[5]
            assert entry[4] == trade[4] and exit_order[4] == -trade[4]
            assert entry[6] == trade[6] and exit_order[6] == trade[7]
            gross = float(trade[4])*(float(trade[7])-float(trade[6]))*trade[5]*multiplier
            assert abs(gross-trade[10]) < 1e-4
            assert entry[9] == trade[8] and exit_order[9] == trade[9]
            assert abs(trade[11]-(gross-entry[9]-exit_order[9])) < 1e-4
        equal(totals(trades), row)
        for source, name in enumerate(('J2', 'O06')):
            equal(totals(trades[trades[:, 1] == source]), row['sources'][name])
        for side, name in [(1, '買い'), (-1, '売り')]:
            equal(totals(trades[trades[:, 4] == side]), row['directions'][name])
        orders_count += len(orders)
        parent_count += len(trades)
    partitions = {'全31': sessions, '旧30': sessions[:-1], '前16': sessions[:16], '後15': sessions[16:],
                  '後14': sessions[16:-1], '追加1': sessions[-1:],
                  'デイ': [s for s in sessions if s.endswith('_Day')],
                  'ナイト': [s for s in sessions if s.endswith('_Night')]}
    for label, subset in partitions.items():
        for symbol in SYMBOLS:
            trades = np.concatenate([ledgers[(s, symbol)]['trades'] for s in subset])
            metric = result['periods'][label][symbol]
            equal(totals(trades), metric)
            rows = [r for r in result['rows'] if r['session'] in subset and r['symbol'] == symbol]
            assert metric['positive_sessions'] == sum(r['net'] > 1e-5 for r in rows)
            assert metric['active_sessions'] == sum(r['campaigns'] > 0 for r in rows)
            assert metric['no_trade_sessions'] == sum(r['campaigns'] == 0 for r in rows)
            assert metric['losing_sessions'] == sum(r['net'] < -1e-5 for r in rows)
            expected_rate = metric['positive_sessions']/metric['active_sessions'] if metric['active_sessions'] else None
            assert metric['positive_session_rate'] == expected_rate
            days = {s[:10] for s in subset}
            best = max(sorted(days), key=lambda day: sum(r['net'] for r in rows if r['session'][:10] == day))
            assert metric['best_day'] == best
            without = np.concatenate([ledgers[(s, symbol)]['trades'] for s in subset if s[:10] != best]) \
                if any(s[:10] != best for s in subset) else np.empty((0, 16))
            equal(totals(without), metric['without_best_day'])
    return dict(口座=62, 注文=orders_count, 親=parent_count, 商品期間=16)


def parents(ledger: dict, source: int | None = None) -> dict:
    """
    機能: 判断・実約定・源・方向・枚数・価格が全て同じ新規を一対一対応する。
    引数: ledger(dict)、source(int | None)。
    返り値: dict。完全な新規キーと親。
    """
    output = {}
    for trade in ledger['trades']:
        if source is not None and int(trade[1]) != source:
            continue
        key = int(trade[15]), int(trade[2]), int(trade[1]), int(trade[4]), int(trade[5]), float(trade[6])
        assert key not in output
        output[key] = trade
    return output


def compare(base: str, modified: str, ledgers: dict, fixed: dict) -> dict:
    """
    機能: 同一新規の管理差と消失・新追加の親別G/Lを恒等分解する。
    引数: base/modified(str)、ledgers/fixed(dict)。
    返り値: dict。商品・源ごとの全経路差。
    """
    output = {}
    for symbol in SYMBOLS:
        output[symbol] = {}
        for source, label in [(None, '全源'), (0, 'J2'), (1, 'O06')]:
            matched, old_only, new_only = [], [], []
            for session in fixed['全31']:
                old = parents(ledgers[base][session, symbol], source)
                new = parents(ledgers[modified][session, symbol], source)
                matched.extend((session, old[k], new[k]) for k in old.keys() & new.keys())
                old_only.extend((session, old[k]) for k in old.keys()-new.keys())
                new_only.extend((session, new[k]) for k in new.keys()-old.keys())
            change = sum(float(b[11]-a[11]) for _, a, b in matched)
            old_net, new_net = sum(float(t[11]) for _, t in old_only), sum(float(t[11]) for _, t in new_only)
            full_old = sum(float(t[11]) for s in fixed['全31'] for t in ledgers[base][s, symbol]['trades']
                           if source is None or int(t[1]) == source)
            full_new = sum(float(t[11]) for s in fixed['全31'] for t in ledgers[modified][s, symbol]['trades']
                           if source is None or int(t[1]) == source)
            assert abs((full_new-full_old)-(change+new_net-old_net)) < 1e-4
            cohorts = {}
            for _, a, b in matched:
                tag = ('利益' if a[11] > 0 else '損失' if a[11] < 0 else 'ゼロ')+'→'+ \
                    ('利益' if b[11] > 0 else '損失' if b[11] < 0 else 'ゼロ')
                item = cohorts.setdefault(tag, dict(親=0, 元収支円=0., 新収支円=0., 差円=0.))
                item['親'] += 1
                item['元収支円'] += float(a[11])
                item['新収支円'] += float(b[11])
                item['差円'] += float(b[11]-a[11])
            output[symbol][label] = dict(元収支円=full_old, 新収支円=full_new, 差円=full_new-full_old,
                同一新規親=len(matched), 同一新規管理差円=change, 同一新規符号変化=cohorts,
                元固有親=len(old_only), 逃した元固有利益円=sum(max(float(t[11]), 0.) for _, t in old_only),
                避けた元固有損失円=-sum(min(float(t[11]), 0.) for _, t in old_only), 元固有収支円=old_net,
                新固有親=len(new_only), 新固有利益円=sum(max(float(t[11]), 0.) for _, t in new_only),
                新固有損失円=-sum(min(float(t[11]), 0.) for _, t in new_only), 新固有収支円=new_net,
                恒等検算=True)
    return output


def first_profit_prefix(base: str, modified: str, ledgers: dict, fixed: dict) -> dict:
    """
    機能: N2だけの列で最初の黒字全返済までの注文が元と一致するか照合する。
    引数: base/modified(str)、ledgers/fixed(dict)。
    返り値: dict。62口座の接頭部一致件数。
    """
    complete = 0
    no_profit = 0
    for session in fixed['全31']:
        for symbol in SYMBOLS:
            old, new = ledgers[base][session, symbol], ledgers[modified][session, symbol]
            profitable = old['trades'][(old['trades'][:, 1] == 1) & (old['trades'][:, 11] > 1e-5)]
            end = int(profitable[0, 3]) if len(profitable) else math.inf
            left = old['orders'][old['orders'][:, 0] <= end]
            right = new['orders'][new['orders'][:, 0] <= end]
            assert np.array_equal(left, right), (base, modified, session, symbol, end)
            complete += 1
            no_profit += not len(profitable)
    return dict(一致口座=complete, 初黒字の無い口座=no_profit, 比較=f'{base}→{modified}')


def selection_check(results: dict, fixed: dict) -> dict:
    """
    機能: 前16だけの活動足切りと固定採点を独立復元する。
    引数: results/fixed(dict)。
    返り値: dict。正式参考の照合。後成績で新たに代表を選ばない。
    """
    formal = read(WORK/'前16参考代表.json')
    assert formal['固定SHA256'] == digest(WORK/'事前固定.json')
    assert formal['後15正式損益前選定'] and formal['全31既知']
    for relative, expected in formal['結果SHA256'].items():
        assert digest(ROOT/relative) == expected, relative
    active, positive, good = [], [], []
    for ident, result in results.items():
        values = [result['periods']['前16'][symbol] for symbol in SYMBOLS]
        if all(v['campaigns'] >= 20 and v['active_sessions'] >= 8 for v in values):
            active.append(ident)
            if all(v['net'] > 0 for v in values):
                positive.append(ident)
                if all(v['payoff'] is not None and v['payoff'] > 1 for v in values):
                    good.append(ident)
    pool = good or positive or active or list(results)
    scores = {}
    for ident in pool:
        values = [results[ident]['periods']['前16'][symbol] for symbol in SYMBOLS]
        shares = [v['profit_share'] if v['profit_share'] is not None else -1 for v in values]
        rates = [v['positive_session_rate'] if v['positive_session_rate'] is not None else -1 for v in values]
        scores[ident] = (-min(shares), -min(rates), -sum(shares), ident)
    chosen = min(pool, key=lambda ident: scores[ident])
    assert formal['selected'] == chosen
    assert formal['level'] == (0 if good else 1 if positive else 2 if active else 3)
    assert set(formal['eligible']) == set(pool)
    for ident, score in scores.items():
        assert list(score) == formal['scores'][ident]
    assert formal['primary'] == fixed['主']
    return dict(一致=True, selected=chosen, primary=fixed['主'], 足切り段階=formal['level'],
                参考候補=pool, 全31既知=True, 選び直し=False,
                選定SHA256=digest(WORK/'前16参考代表.json'))


def main() -> None:
    """
    機能: 根担当の損益閲覧許可後、全条件全31の独立会計と部品経路を保存する。
    引数: なし。
    返り値: None。注文条件の変更やAPI取得はしない。
    """
    fixed = read(WORK/'事前固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT/relative) == expected, relative
    assembled = read(WORK/'analysis/比較結果.json')
    assert assembled['primary'] == fixed['主']
    results, ledgers, checks, hashes = {}, {}, {}, {}
    for config in fixed['条件']:
        ident = config['id']
        results[ident] = assembled['results'][ident]
        ledgers[ident] = {}
        saved_rows = []
        for stage in ('front', 'back'):
            result_path, ledger_path = WORK/stage/'results'/f'{ident}.json', WORK/stage/'ledgers'/f'{ident}.pkl'
            result, account_ledgers = read(result_path), read(ledger_path)
            assert result['config'] == config
            assert result['ledger_SHA256'] == digest(ledger_path)
            assert not set(ledgers[ident]) & set(account_ledgers)
            ledgers[ident].update(account_ledgers)
            saved_rows.extend(result['rows'])
            hashes[str(result_path.relative_to(ROOT))] = digest(result_path)
            hashes[str(ledger_path.relative_to(ROOT))] = digest(ledger_path)
        assert saved_rows == results[ident]['rows']
        assert results[ident]['config'] == config
        checks[ident] = check(results[ident], ledgers[ident], fixed)
    pairs = [('O10', 'O10_TR'), ('A_O', 'R0'), ('O10_F10_TR', 'K0')]
    for confirmation in ('S', 'B'):
        for fraction in ('25', '50'):
            plain = f'R_{confirmation}{fraction}'
            altered = plain+'_C'
            pairs.extend([('R0', plain), ('R0_C', altered), (plain, altered)])
        pairs.append((f'R_{confirmation}25_C', f'R_{confirmation}25_C_ESTOP'))
    pairs.extend([(f'R_S{fraction}', f'R_B{fraction}') for fraction in ('25', '50')])
    pairs.extend([(f'R_S{fraction}_C', f'R_B{fraction}_C') for fraction in ('25', '50')])
    for prefix in ('S', 'B'):
        for fraction in ('25', '50'):
            pairs.append(('K0', f'K{prefix}{fraction}'))
            pairs.append(('O10_F10_TR', f'K{prefix}{fraction}'))
        pairs.append((f'K{prefix}25', f'K{prefix}25_REL'))
    pairs.extend([('KS25', 'KB25'), ('KS50', 'KB50'), ('KS25', 'KS25_ALL'),
                  ('O10_F10_TR', 'O10_F15_TR'), ('R_B25_C', 'R_B25_C_W15'),
                  ('KS25', 'KS25_W15'), ('R_B25_C', 'R_B25_C_TR'),
                  ('R_B25_C_TR', 'I_B25_C_KS25'), ('R_B25_C_TR', 'I_B25_C_KB25'),
                  ('I_B25_C_KS25', 'I_B25_C_KB25')])
    pairs = [(a, b) for a, b in pairs if a in results and b in results]
    differences = {f'{a}→{b}': compare(a, b, ledgers, fixed) for a, b in pairs}
    prefix_checks = {ident: first_profit_prefix('O10_F10_TR', ident, ledgers, fixed)
                     for ident in ('K0', 'KS25', 'KS50', 'KB25', 'KB50', 'KS25_REL', 'KB25_REL')
                     if ident in results}
    if 'R_B25_C_TR' in results:
        prefix_checks.update({ident: first_profit_prefix('R_B25_C_TR', ident, ledgers, fixed)
                              for ident in ('I_B25_C_KS25', 'I_B25_C_KB25')})
    views = {ident: result['periods'] for ident, result in results.items()}
    reference_check = selection_check(results, fixed)
    all80 = [ident for ident in results if all(
        (results[ident]['periods']['全31'][symbol]['profit_share'] or 0.) >= .8 for symbol in SYMBOLS)]
    save('全条件全31の独立親会計と同一新規及び再参加経路分解.json', dict(
        全合格=True, 条件数=len(results), 場数=31, 全31は全て既知探索=True, 主=fixed['主'],
        口座=sum(c['口座'] for c in checks.values()), 注文=sum(c['注文'] for c in checks.values()),
        親=sum(c['親'] for c in checks.values()), 検算=checks, 比較=views,
        部品差分=differences, 初回及び初黒字終了までの対照一致=prefix_checks,
        前16正式参考の独立照合=reference_check,
        両商品金額80=all80, 注意=[
            '親別費用後G/Lを維持。無取引は勝ちでない。2商品の円額を加算採用しない。',
            '同一新規キーには判断行と実約定行・源・方向・枚数・価格を全て含む。',
            '固有経路は単純な管理改善でない。避けた損失、逃した利益、新利益、新損失を別に示す。',
            '全行時価及び独立状態復元は別監査担当の全会計監査を参照。'],
        API取得=0, 実注文=0, 固定SHA256=digest(WORK/'事前固定.json'), SHA256=hashes,
        根集計SHA256=digest(WORK/'analysis/比較結果.json'),
        計算コードSHA256=digest(Path(__file__))))
    print(f'{len(results)}条件×31場×2商品の独立親会計と部品経路を保存しました', flush=True)


if __name__ == '__main__':
    main()
