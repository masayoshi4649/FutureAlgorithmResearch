"""追加Dayを読まず、旧30場の38条件と同一新規の管理変更を独立に検算する。"""

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
    機能: 旧30場の結果・台帳・素材と固定仕様だけを読み取る。
    引数: path(Path)。
    返り値: object。JSON又はpickleの内容。
    """
    assert 'extra' not in path.relative_to(WORK).parts if path.is_relative_to(WORK) else True
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 比較対象と固定仕様の内容指紋を計算する。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def clean(value: object) -> object:
    """
    機能: 独立診断を有限の日本語JSONへ変換する。
    引数: value(object)。
    返り値: object。標準型。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
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
    機能: 凍結済みコードを変更せず新review内だけへ保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    target = HERE / name
    assert target.resolve().is_relative_to(HERE.resolve())
    target.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                 allow_nan=False)+'\n', encoding='utf-8')


def clock(stamp: float) -> str:
    """
    機能: 当時の代理時計を日本時間へ表示する。
    引数: stamp(float、Unix秒)。
    返り値: str。時刻。
    """
    return datetime.fromtimestamp(float(stamp), JST).isoformat(timespec='seconds')


def totals(trades: np.ndarray) -> dict:
    """
    機能: 親別純損益から源間相殺なしで費用後利益・損失を独立集計する。
    引数: trades(ndarray、公開16列)。
    返り値: dict。金額・枚数・親数。
    """
    values = trades[:, 11]
    positive, negative = values > 1e-5, values < -1e-5
    g = float(values[positive].sum())
    l = float(-values[negative].sum())
    return dict(profit=g, loss=l, net=g-l, gross=float(trades[:, 10].sum()),
                fees=float((trades[:, 8]+trades[:, 9]).sum()), campaigns=len(trades),
                winning_campaigns=int(positive.sum()), losing_campaigns=int(negative.sum()),
                flat_campaigns=int((~(positive | negative)).sum()),
                winning_lots=int(trades[positive, 5].sum()),
                losing_lots=int(trades[negative, 5].sum()),
                flat_lots=int(trades[~(positive | negative), 5].sum()),
                lots=int(trades[:, 5].sum()), profit_share=g/(g+l) if g+l else None,
                payoff=(g/int(positive.sum()))/(l/int(negative.sum()))
                if positive.any() and negative.any() else None)


def check(result: dict, ledgers: dict) -> dict:
    """
    機能: 旧30場の親・注文・料金・方向上限・全源合計を独立検算する。
    引数: result/ledgers(dict)。
    返り値: dict。確認件数。全行時価は別担当の全会計監査を参照する。
    """
    assert len(result['rows']) == len(ledgers) == 60
    order_count = parent_count = 0
    for row in result['rows']:
        key = (row['session'], row['symbol'])
        entry = ledgers[key]
        orders, trades = entry['orders'], entry['trades']
        multiplier, fee, cap = (1000., 41.8, 10) if key[1] == 'TOPIX' else (10., 11., 20)
        assert len(orders) == 2*len(trades)
        assert len(np.unique(orders[:, 16])) == len(orders)
        assert np.all(orders[:, 0] > orders[:, 1])
        assert not np.any(entry['slots'][:, 0])
        assert not np.any(entry['trace_changes'][-1, 1:])
        assert entry['stats'][2] <= cap and entry['stats'][3] <= cap
        by_parent = {}
        for order in orders:
            assert order[9] == math.floor(float(order[5])*fee+1e-8)
            by_parent.setdefault((int(order[2]), int(order[3])), []).append(order)
        for parent in trades:
            pair = by_parent[(int(parent[0]), int(parent[1]))]
            assert len(pair) == 2
            first, last = pair
            assert first[7] == 1 and last[7] == 0
            assert first[0] == parent[2] and last[0] == parent[3]
            assert first[5] == last[5] == parent[5]
            assert first[4] == parent[4] and last[4] == -parent[4]
            assert first[6] == parent[6] and last[6] == parent[7]
            expected = float(parent[4])*(float(parent[7])-float(parent[6]))*float(parent[5])*multiplier
            assert abs(expected-parent[10]) < 1e-5
            assert first[9] == parent[8] and last[9] == parent[9]
            assert abs(parent[11]-(expected-first[9]-last[9])) < 1e-5
        actual = totals(trades)
        for name, value in actual.items():
            expected = row[name]
            assert value is None and expected is None or abs(float(value)-float(expected)) < 1e-4
        for source, name in enumerate(('J2', 'O06')):
            for field, value in totals(trades[trades[:, 1] == source]).items():
                expected = row['sources'][name][field]
                assert value is None and expected is None or abs(float(value)-float(expected)) < 1e-4
        assert abs(sum(row['sources'][s]['net'] for s in ('J2', 'O06'))-row['net']) < 1e-4
        order_count += len(orders)
        parent_count += len(trades)
    for period, sessions in [('旧30', FIXED['旧30']), ('前16', FIXED['前16']), ('後14', FIXED['後14'])]:
        for symbol in SYMBOLS:
            trades = np.concatenate([ledgers[(s, symbol)]['trades'] for s in sessions])
            for name, value in totals(trades).items():
                expected = result['periods'][period][symbol][name]
                assert value is None and expected is None or abs(float(value)-float(expected)) < 1e-4
            selected = [r for r in result['rows'] if r['session'] in sessions and r['symbol'] == symbol]
            metric = result['periods'][period][symbol]
            assert metric['positive_sessions'] == sum(r['net'] > 1e-5 for r in selected)
            assert metric['active_sessions'] == sum(r['campaigns'] > 0 for r in selected)
            assert metric['no_trade_sessions'] == sum(r['campaigns'] == 0 for r in selected)
            rate = metric['positive_sessions']/metric['active_sessions'] if metric['active_sessions'] else None
            assert metric['positive_session_rate'] == rate
    return dict(口座=60, 注文=order_count, 親=parent_count, 商品期間=6)


def parents(ledger: dict, source: int | None = None) -> dict:
    """
    機能: 実際の同一新規を価格・時刻・方向・枚数で対応させる。
    引数: ledger(dict)、source(int | None)。
    返り値: dict。キーはentry行/源/方向/枚数/約定価格で、一対一対応を要求する。
    """
    result = {}
    for trade in ledger['trades']:
        if source is not None and int(trade[1]) != source:
            continue
        key = (int(trade[2]), int(trade[1]), int(trade[4]), int(trade[5]), float(trade[6]))
        assert key not in result
        result[key] = trade
    return result


def sign(value: float) -> str:
    """
    機能: 費用後損益の符号を分類する。
    引数: value(float)。
    返り値: str。利益/損失/ゼロ。
    """
    return '利益' if value > 1e-5 else '損失' if value < -1e-5 else 'ゼロ'


def compare(base: str, modified: str, all_ledgers: dict, all_results: dict) -> dict:
    """
    機能: 一軸変更の同一新規と経路変更を分離して純収支差を恒等検算する。
    引数: base/modified(str)、all_ledgers/all_results(dict)。
    返り値: dict。対応した管理差、新旧固有経路、源別寄与。
    """
    result = {}
    for symbol in SYMBOLS:
        result[symbol] = {}
        for source, label in [(None, '全源'), (0, 'J2'), (1, 'O06')]:
            matched, old_only, new_only = [], [], []
            for session in FIXED['旧30']:
                old = parents(all_ledgers[base][(session, symbol)], source)
                new = parents(all_ledgers[modified][(session, symbol)], source)
                matched.extend((session, old[k], new[k]) for k in old.keys() & new.keys())
                old_only.extend((session, old[k]) for k in old.keys()-new.keys())
                new_only.extend((session, new[k]) for k in new.keys()-old.keys())
            change = sum(float(b[11]-a[11]) for _, a, b in matched)
            old_net = sum(float(a[11]) for _, a in old_only)
            new_net = sum(float(a[11]) for _, a in new_only)
            cohorts = {}
            for session, old, new in matched:
                cohort = f'{sign(float(old[11]))}→{sign(float(new[11]))}'
                item = cohorts.setdefault(cohort, dict(親=0, 元収支円=0., 新収支円=0., 差円=0.))
                item['親'] += 1
                item['元収支円'] += float(old[11])
                item['新収支円'] += float(new[11])
                item['差円'] += float(new[11]-old[11])
            old_total = sum(t[11] for s in FIXED['旧30'] for t in all_ledgers[base][(s, symbol)]['trades']
                            if source is None or int(t[1]) == source)
            new_total = sum(t[11] for s in FIXED['旧30'] for t in all_ledgers[modified][(s, symbol)]['trades']
                            if source is None or int(t[1]) == source)
            assert abs((new_total-old_total)-(change+new_net-old_net)) < 1e-4
            def examples(order: bool) -> list:
                """
                機能: 同一新規の改善又は悪化上位3件を診断例として取り出す。
                引数: order(bool、悪化ならTrue)。
                返り値: list[dict]。採否に使う未来特徴ではない。
                """
                selected = sorted(matched, key=lambda t: (float(t[2][11]-t[1][11]), t[0]), reverse=not order)[:3]
                return [dict(場=s, 源='J2' if int(a[1]) == 0 else 'O06', 新規行=int(a[2]),
                             方向='買い' if a[4] == 1 else '売り', 枚数=int(a[5]), 新規価格=float(a[6]),
                             元返済行=int(a[3]), 新返済行=int(b[3]), 元収支円=float(a[11]),
                             新収支円=float(b[11]), 差円=float(b[11]-a[11]),
                             元理由=int(a[13]), 新理由=int(b[13])) for s, a, b in selected]
            result[symbol][label] = dict(元収支円=float(old_total), 新収支円=float(new_total),
                差円=float(new_total-old_total), 同一新規親=len(matched), 同一新規管理差円=change,
                同一新規の符号変化=cohorts, 元固有親=len(old_only), 元固有利益円=sum(max(t[11], 0.) for _, t in old_only),
                元固有損失円=-sum(min(t[11], 0.) for _, t in old_only), 元固有収支円=old_net,
                新固有親=len(new_only), 新固有利益円=sum(max(t[11], 0.) for _, t in new_only),
                新固有損失円=-sum(min(t[11], 0.) for _, t in new_only), 新固有収支円=new_net,
                恒等検算=True, 改善上位3=examples(False), 悪化上位3=examples(True))
    return result


def selected(results: dict) -> dict:
    """
    機能: 正式選定と同じ旧前16制約を独立に計算する。
    引数: results(dict[str,dict])。
    返り値: dict。選定段階、参考代表、候補。
    """
    active, positive, good = [], [], []
    for ident, result in results.items():
        views = [result['periods']['前16'][s] for s in SYMBOLS]
        if all(v['campaigns'] >= 20 and v['active_sessions'] >= 8 for v in views):
            active.append(ident)
            if all(v['net'] > 0 for v in views):
                positive.append(ident)
                if all(v['payoff'] is not None and v['payoff'] > 1 for v in views):
                    good.append(ident)
    pool = good or positive or active or list(results)
    def score(ident: str) -> tuple:
        """
        機能: 金額割合・活動黒字率と固定同点順で独立採点する。
        引数: ident(str)。
        返り値: tuple。小さい値を優先。
        """
        views = [results[ident]['periods']['前16'][s] for s in SYMBOLS]
        shares = [v['profit_share'] if v['profit_share'] is not None else -1 for v in views]
        rates = [v['positive_session_rate'] if v['positive_session_rate'] is not None else -1 for v in views]
        return -min(shares), -min(rates), -sum(shares), ident
    chosen = min(pool, key=score)
    formal = WORK/'前16参考代表.json'
    if formal.exists():
        assert read(formal)['selected'] == chosen
    return dict(selected=chosen, level=0 if good else 1 if positive else 2 if active else 3,
                eligible=pool, 独立再選定ではなく正式規則照合=True, 追加Day閲覧なし=True)


def confirmation(grid: np.ndarray, condition: np.ndarray, valid: np.ndarray,
                 first: np.ndarray, second: np.ndarray, seconds: float) -> np.ndarray:
    """
    機能: 反対状態の連続と双方更新をproductionと別実装で確認する。
    引数: grid/condition/valid/first/second(ndarray)、seconds(float)。
    返り値: ndarray[bool]。当時確認済み旗。
    """
    out = np.zeros(len(grid), dtype=bool)
    began = None
    for i, stamp in enumerate(grid):
        if not valid[i] or not condition[i]:
            began = None
            continue
        if began is None or i and stamp-grid[i-1] > 5.+1e-8:
            began = i
        out[i] = seconds == 0 or stamp-grid[began] >= seconds and first[i] > first[began] and second[i] > second[began]
    return out


def old_material() -> dict:
    """
    機能: 追加Dayを含まない旧専用data.pyから60口座だけを読み取る。
    引数: なし。
    返り値: dict。原板価格と旧30の格子。
    """
    path = ROOT/'work/wave_v90/data.py'
    spec = importlib.util.spec_from_file_location('独立旧30価格入力91', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = module.load_inputs(verify=True)
    assert set(value['metadata']['sessions']) == set(FIXED['旧30'])
    assert all(k[0] != FIXED['追加1'][0] for k in value['prices'])
    return value


def diagnostic_state(session: dict, entries: dict) -> dict:
    """
    機能: 旧30だけのcommon・反対両気配・個別持続旗を独立再構築する。
    引数: session/entries(dict)。
    返り値: dict。売買後の説明用状態であり新注文には接続しない。
    """
    grid = session['grid']
    markets = [session['markets'][s] for s in SYMBOLS]
    valid = np.logical_and.reduce([m['current']['valid'] for m in markets])
    common_valid = valid.copy()
    q_valid = valid.copy()
    for m in markets:
        for window in (30, 300):
            w = m['windows'][window]
            common_valid &= w['source_valid'] & np.isfinite(w['ret_bp'])
        w = m['windows'][30]
        q_valid &= w['source_valid'] & np.isfinite(w['bid_change_ticks']) & np.isfinite(w['ask_change_ticks'])
    common = np.zeros(len(grid), dtype=np.int8)
    source = [m['current']['index'] for m in markets]
    output = dict(common=common, current_valid=valid, common_valid=common_valid, quote_valid=q_valid)
    for direction in (-1, 1):
        active = common_valid.copy()
        quotes = q_valid.copy()
        for m in markets:
            active &= (direction*m['windows'][300]['ret_bp'] >= 3.) & (direction*m['windows'][30]['ret_bp'] > 0.)
            quotes &= (direction*m['windows'][30]['bid_change_ticks'] >= 1.-1e-8) & (direction*m['windows'][30]['ask_change_ticks'] >= 1.-1e-8)
        common[active] = direction
        output[f'quotes{direction}'] = quotes
        for seconds in (0, 10, 15):
            output[f'common{direction}_{seconds}'] = confirmation(grid, active, common_valid, *source, float(seconds))
            output[f'quotes{direction}_{seconds}'] = confirmation(grid, quotes, q_valid, *source, float(seconds))
    assert np.array_equal(common, entries['common'])
    return output


def row_mapping(record: dict, grid: np.ndarray) -> np.ndarray:
    """
    機能: 当時の格子公開を次の原板へ対応させ、原板行ごとの最新公開番号にする。
    引数: record(dict)、grid(ndarray)。
    返り値: ndarray[int32]。未来格子を補間しない。
    """
    out = np.full(len(record['time_s']), -1, dtype=np.int32)
    for g, row in enumerate(np.searchsorted(record['time_s'], grid, side='left')):
        if row < len(out) and record['time_s'][row]-grid[g] <= 10.:
            out[row] = g
    return np.maximum.accumulate(out)


def point(record: dict, session: dict, state: dict, mapping: np.ndarray, row: int) -> dict:
    """
    機能: 具体的な原板行で当時見えた両市場価格・ER・反対旗を説明する。
    引数: record/session/state(dict)、mapping(ndarray)、row(int)。
    返り値: dict。原板と採用済み格子の情報。
    """
    row = int(row)
    g = int(mapping[row])
    stamp = record['time_s'][row]
    output = dict(行=row, 原本seq=int(record['seq'][row]), 時刻=clock(stamp),
                  LastPrice=float(record['price'][row]), bid=float(record['bid'][row]),
                  ask=float(record['ask'][row]), 原板気配有効=bool(record['quote_valid'][row]),
                  格子番号=g, 格子鮮度秒=float(stamp-session['grid'][g]) if g >= 0 else None)
    if g < 0:
        return output
    output.update(格子時刻=clock(session['grid'][g]), common=int(state['common'][g]),
                  current_valid=bool(state['current_valid'][g]),
                  買い反対common10=bool(state['common-1_10'][g]),
                  売り反対common10=bool(state['common1_10'][g]),
                  買い反対気配15=bool(state['quotes-1_15'][g]),
                  売り反対気配15=bool(state['quotes1_15'][g]))
    output['両市場'] = {}
    for symbol in SYMBOLS:
        m = session['markets'][symbol]
        output['両市場'][symbol] = dict(源行=int(m['current']['index'][g]),
            mid=float(m['current']['mid'][g]), 現在有効=bool(m['current']['valid'][g]),
            ER300=float(m['windows'][300]['efficiency'][g]),
            ret300bp=float(m['windows'][300]['ret_bp'][g]), ret30bp=float(m['windows'][30]['ret_bp'][g]),
            bid30呼値=float(m['windows'][30]['bid_change_ticks'][g]),
            ask30呼値=float(m['windows'][30]['ask_change_ticks'][g]))
    return output


def cases(ident: str, results: dict, ledgers: dict, material: dict, states: dict) -> dict:
    """
    機能: 商品別赤字上位3場の全親と大きな負け親3つを具体時系列で診断する。
    引数: ident(str)、results/ledgers/material/states(dict)。
    返り値: dict。未来最大値は診断専用であり当時判断へ逆流しない。
    """
    output = {}
    config = results[ident]['config']
    for symbol in SYMBOLS:
        losing = sorted([r for r in results[ident]['rows'] if r['symbol'] == symbol and r['net'] < 0],
                        key=lambda r: (r['net'], r['session']))[:3]
        output[symbol] = []
        for account in losing:
            session_name = account['session']
            key = (session_name, symbol)
            record = material['prices'][key]
            session = material['grids'][session_name]
            state = states[session_name]
            mapping = row_mapping(record, session['grid'])
            ledger = ledgers[ident][key]
            trades = ledger['trades']
            all_parents = []
            details = []
            for parent in trades:
                all_parents.append(dict(親=int(parent[0]), 源='J2' if parent[1] == 0 else 'O06',
                    方向='買い' if parent[4] == 1 else '売り', 枚数=int(parent[5]),
                    新規時刻=clock(record['time_s'][int(parent[2])]),
                    返済時刻=clock(record['time_s'][int(parent[3])]),
                    新規価格=float(parent[6]), 返済価格=float(parent[7]), 収支円=float(parent[11]),
                    返済理由=ledger['reasons'][int(parent[13])]))
            for parent in sorted(trades, key=lambda t: float(t[11]))[:3]:
                if parent[11] >= 0:
                    continue
                entry, exit_row = int(parent[2]), int(parent[3])
                side, source = int(parent[4]), int(parent[1])
                parent_id = int(parent[0])
                paired = ledger['orders'][(ledger['orders'][:, 2] == parent_id) & (ledger['orders'][:, 3] == source)]
                assert len(paired) == 2
                exit_decision = int(paired[1, 1])
                active = np.arange(entry+1, exit_decision+1)
                g = mapping[active]
                safe = g >= 0
                fresh = np.zeros(len(active), dtype=bool)
                fresh[safe] = record['time_s'][active[safe]]-session['grid'][g[safe]] <= 10.+1e-8
                flags = {}
                for field, label in [('common'+str(-side)+'_0', '初めて逆共同方向'),
                                     ('common'+str(-side)+'_10', '初めて逆共同方向10秒確認'),
                                     ('quotes'+str(-side)+'_15', '初めて逆両気配15秒確認')]:
                    values = np.zeros(len(active), dtype=bool)
                    values[fresh] = state[field][g[fresh]]
                    hits = active[values]
                    flags[label] = point(record, session, state, mapping, int(hits[0])) if len(hits) else None
                quote = record['bid'] if side == 1 else record['ask']
                valid_rows = np.arange(entry, exit_row+1)[record['quote_valid'][entry:exit_row+1]]
                moves = side*(quote[valid_rows]-parent[6])
                best = int(valid_rows[int(np.argmax(moves))])
                worst = int(valid_rows[int(np.argmin(moves))])
                value = 1000. if symbol == 'TOPIX' else 10.
                fee = parent[8]+parent[9]
                events = ledger['events']
                related = events[(events[:, 1] == parent_id) & (events[:, 2] == source)]
                lifecycle = []
                for event in related:
                    if int(event[3]) in (2, 3, 7, 12, 13, 14, 15):
                        lifecycle.append(dict(種類=ledger['event_codes'][int(event[3])],
                            原板=point(record, session, state, mapping, int(event[0])),
                            limit又は基準=float(event[7]), detail=float(event[11]), mode=int(event[8])))
                if source == 1:
                    arm = events[(events[:, 2] == 1) & (events[:, 10] == parent[14]) & (events[:, 3] == 12)
                                 & (events[:, 0] <= entry)]
                    lifecycle = [dict(種類='準備時の基準', 原板=point(record, session, state, mapping, int(e[0])),
                                      anchor=float(e[7]), 幅=float(e[11])) for e in arm[-1:]]+lifecycle
                details.append(dict(親=parent_id, 源='J2' if source == 0 else 'O06',
                    方向='買い' if side == 1 else '売り', 枚数=int(parent[5]),
                    純収支円=float(parent[11]), 新規価格=float(parent[6]), 返済価格=float(parent[7]),
                    返済理由=ledger['reasons'][int(parent[13])],
                    新規判断=point(record, session, state, mapping, int(parent[15])),
                    新規約定=point(record, session, state, mapping, entry),
                    返済判断=point(record, session, state, mapping, exit_decision),
                    返済約定=point(record, session, state, mapping, exit_row),
                    保有中の反証=flags, 注文状態の変化=lifecycle,
                    事後最大順行=dict(原板=point(record, session, state, mapping, best),
                        順行pt=float(moves.max()), 費用後清算評価円=float(moves.max()*parent[5]*value-fee)),
                    事後最大逆行=dict(原板=point(record, session, state, mapping, worst),
                        順行pt=float(moves.min()), 費用後清算評価円=float(moves.min()*parent[5]*value-fee))))
            output[symbol].append(dict(場=session_name, 親合計収支円=account['net'],
                利益円=account['profit'], 損失円=account['loss'], 源別=account['sources'],
                全親=all_parents, 大きな負け親3=details))
    return output


def main() -> None:
    """
    機能: 完成した旧38を検算し、部品と具体時系列の反証を新reviewへ保存する。
    引数: なし。
    返り値: None。追加Dayの結果・価格・台帳を一切読み取らない。
    """
    global FIXED
    FIXED = read(WORK/'事前固定.json')
    assert len(FIXED['条件']) == 38
    for relative, expected in FIXED['SHA256'].items():
        assert digest(ROOT/relative) == expected, relative
    results, ledgers, checks = {}, {}, {}
    source_hash = {}
    for condition in FIXED['条件']:
        ident = condition['id']
        path, ledger_path = WORK/'results'/f'{ident}.json', WORK/'ledgers'/f'{ident}.pkl'
        assert path.exists() and ledger_path.exists()
        results[ident], ledgers[ident] = read(path), read(ledger_path)
        assert results[ident]['config'] == condition
        assert results[ident]['ledger_SHA256'] == digest(ledger_path)
        checks[ident] = check(results[ident], ledgers[ident])
        source_hash[str(path.relative_to(ROOT))] = digest(path)
        source_hash[str(ledger_path.relative_to(ROOT))] = digest(ledger_path)
    reference = selected(results)
    comparisons = [('J8', f'J8_XC{s:02}') for s in (0, 10, 15)]
    comparisons += [('M82', f'M82_XC{s:02}') for s in (0, 10, 15)]
    comparisons += [('M82', 'M82_XQ15'), ('M82', 'M82_XOR15'),
        ('B_QA', 'A_D'), ('A_D', 'A_D_B300'), ('A_G82', 'A_G82_B300')]
    comparisons += [('O10', f'O10_F{s}') for s in ('05', '10', '15')]
    comparisons += [('M82', 'M82_F10'), ('B_QA', 'B_QA_T0'), ('B_QA', 'B_QA_TNONE'),
        ('O10', 'O10_TR'), ('M82', 'M82_TR'), ('J8', 'J8_HUNL'), ('M82', 'M82_HUNL')]
    comparisons += [(f'P_G82_OMIT{part}', 'P_G82') for part in ('X', 'TRAIL', 'F', 'ARM')]
    comparisons += [('P_G82', 'P_G82_HUNL'), ('P_G82_XR', 'P_G82'),
        ('P_G82', 'P_G82_XOR10'), ('P_G82', 'P_G82_B300')]
    differences = {f'{a}→{b}': compare(a, b, ledgers, results) for a, b in comparisons}
    views = {ident: {period: {s: {k: value[s][k] for k in ('profit', 'loss', 'net', 'profit_share',
                      'payoff', 'campaigns', 'positive_sessions', 'losing_sessions', 'active_sessions',
                      'no_trade_sessions', 'equity_drawdown', 'without_best_day', 'sources')}
                      for s in SYMBOLS} for period, value in result['periods'].items()}
             for ident, result in results.items()}
    save('旧38の独立会計と同一新規及び経路変化の部品分解.json', dict(
        全合格=True, 対象='旧30場だけ。追加Dayを含まない。', 条件数=38, 主=FIXED['主'],
        独立参考代表=reference, 口座=sum(v['口座'] for v in checks.values()),
        注文=sum(v['注文'] for v in checks.values()), 親=sum(v['親'] for v in checks.values()),
        検算=checks, 比較=views, 部品差分=differences,
        旧30両商品金額80=[i for i in results if all((results[i]['periods']['旧30'][s]['profit_share'] or 0) >= .8 for s in SYMBOLS)],
        注意=['同一新規管理差＋新固有収支−元固有収支＝全経路差。固有経路を単に逃した利益/救った損失と呼ばない。',
              '全原板時価は別担当の全会計監査で確認。ここでは親・注文・料金・源・上限・商品期間を独立検算。',
              '旧30は既知の3週。追加Day未閲覧で全31目標の判定は未実施。無取引は勝ちへ含めない。'],
        新場損益閲覧=0, 新場価格閲覧=0, API取得=0, 実注文=0,
        固定SHA256=digest(WORK/'事前固定.json'), SHA256=source_hash))
    print('旧38の独立会計・同一新規・部品経路の恒等検算を保存', flush=True)
    material = old_material()
    states = {name: diagnostic_state(value, material['entries'][name]) for name, value in material['grids'].items()}
    details = {ident: cases(ident, results, ledgers, material, states)
               for ident in dict.fromkeys((FIXED['主'], reference['selected']))}
    save('主と旧前16参考代表の赤字上位3場と具体的な価格反証.json', dict(
        全合格=True, 主=FIXED['主'], 独立参考代表=reference['selected'], 最悪場=details,
        原理='入口の高い証拠と出口の反証を分けても反転の確定はできない。commonは価格の過去300/30秒、quotesは両短期気配であり、二市場を独立確率とは扱わない。',
        事後診断のみ=True, 新場損益閲覧=0, 新場価格閲覧=0, API取得=0, 実注文=0,
        注意=['MFE/MAE、最悪場・親の選定は事後説明。これらを売買条件へ戻さない。',
              '原板価格時計は最終約定の代理。実受信時刻、mini/microの約定待ち順位は未検証。'],
        固定SHA256=digest(WORK/'事前固定.json'),
        計算コードSHA256=digest(Path(__file__))))
    print('主と参考代表の最悪場・当時反証・利益追跡の時系列を保存', flush=True)


if __name__ == '__main__':
    main()
