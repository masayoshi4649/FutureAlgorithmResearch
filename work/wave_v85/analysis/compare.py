"""固定16条件の部品効果・時間帯9対照・原E01赤字場の統合版との差を事後診断する。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import importlib.util
import json
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
MODELS = ('specified', 'observed')
PERIODS = ('前16', '後14', '全30')
JST = timezone(timedelta(hours=9))
FIELDS = ('campaign_profit', 'campaign_loss', 'net', 'campaign_profit_share', 'campaign_payoff',
          'campaigns', 'profit', 'loss', 'profit_share', 'gross', 'fees', 'active_sessions',
          'positive_sessions', 'negative_sessions', 'no_trade_sessions', 'max_drawdown', 'best_session_removed')
REASONS = {1: '組の初期損切り', 2: 'トレーリング返済', 7: '元の部分利確', 8: '最大保有時間', 9: '場内全返済',
           30: '順行後の悪化で半減', 32: '実組損失予算', 50: '両市場逆行で早期半減', 70: '実組利益の半分保護', 71: '予定した静観時間の全返済'}


def read(path):
    """
    機能: 完了した保存結果だけを読む。
    引数: path (Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 読取資料と分析コードの内容を指紋化する。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(name, value):
    """
    機能: 選定・戦略を変更せず今回の分析領域だけへ結果を保存する。
    引数: name (str)、value (dict)。
    返り値: None。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def stamp(value):
    """
    機能: 代理時計を日本時間の表示へ変換する。
    引数: value (float) はUnix秒。
    返り値: str。実受信時計であるとは解釈しない。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def brief(value):
    """
    機能: 親組会計を主とし、脚会計・費用・活動・DDも残した比較値を取り出す。
    引数: value (dict) は保存期間集計。
    返り値: dict。
    """
    return {name: value[name] for name in FIELDS}


def difference(before, after):
    """
    機能: 部品ありからなしを引き、金額割合は率の差で保持する。
    引数: before/after (dict)。
    返り値: dict。比率未定義時はNone。
    """
    return {name: after[name] - before[name] if before[name] is not None and after[name] is not None else None
            for name in before}


def components(results, fixed):
    """
    機能: 4部品それぞれを他3部品が同じ8組で比較する。
    引数: results (dict[tuple,dict])、fixed (dict)。
    返り値: dict。全モデル・期間・商品を同じ定義で比較し、代表は変更しない。
    """
    base_ids = {'E01' + ('_' + ''.join(p for bit, p in enumerate('GPDC') if mask & (1 << bit)) if mask else '') for mask in range(16)}
    ids = {c['mask']: c['id'] for c in fixed['catalog'] if c['id'] in base_ids}
    assert set(ids) == set(range(16))
    pairs, summaries = [], []
    for bit, part in enumerate('GPDC'):
        for model in MODELS:
            for period in PERIODS:
                for symbol in SYMBOLS:
                    group = []
                    for mask in range(16):
                        if mask & (1 << bit):
                            continue
                        a, b = ids[mask], ids[mask | (1 << bit)]
                        before = brief(results[model, a]['periods'][period][symbol])
                        after = brief(results[model, b]['periods'][period][symbol])
                        delta = difference(before, after)
                        item = dict(部品=part, model=model, period=period, symbol=symbol, なし=a, あり=b,
                                    before=before, after=after, difference=delta,
                                    負組損失削減=before['campaign_loss'] - after['campaign_loss'],
                                    勝組利益増減=after['campaign_profit'] - before['campaign_profit'])
                        assert abs(delta['net'] - (delta['campaign_profit'] - delta['campaign_loss'])) < 1e-5
                        pairs.append(item); group.append(item)
                    assert len(group) == 8
                    changes = np.asarray([r['difference']['net'] for r in group])
                    summaries.append(dict(部品=part, model=model, period=period, symbol=symbol,
                        組合せ数=8, 収支改善数=int(sum(changes > 0)), 収支悪化数=int(sum(changes < 0)), 収支同値数=int(sum(changes == 0)),
                        収支差最小=float(changes.min()), 収支差中央値=float(np.median(changes)), 収支差最大=float(changes.max()),
                        損失削減数=sum(r['負組損失削減'] > 0 for r in group),
                        利益増加数=sum(r['勝組利益増減'] > 0 for r in group),
                        金額利益割合改善数=sum(r['difference']['campaign_profit_share'] is not None and r['difference']['campaign_profit_share'] > 0 for r in group)))
    assert len(pairs) == 384
    return dict(対象='他の3部品を同一にした有無8組。共有経路があり8独立試行とは呼ばない。',
                差の定義='部品あり−部品なし。負組損失削減だけは、なしの損失−ありの損失。',
                主会計='親組の料金後利益・損失。決済脚を細分化して見かけの利益割合を上げない。',
                pairs=pairs, summaries=summaries, 主3固定=fixed['primary'], 再選定=False)


def event_count(ledger):
    """
    機能: 予約・実返済・停止・解除を実際の台帳から別々に数える。
    引数: ledger (dict)。
    返り値: dict[str,int]。注文理由名だけで利益改善とみなさない。
    """
    guard = ledger.get('guard_events', np.empty((0, 10)))
    block = ledger.get('block_events', np.empty((0, 8)))
    risk = ledger.get('risk_events', np.empty((0, 10)))
    timed = ledger.get('time_events', np.empty((0, 7)))
    orders = ledger['orders']
    stopped = set()
    for event in block:
        side, code = int(event[3]), int(event[2])
        if code == 1:
            stopped.add(side)
        elif code == 3:
            stopped.discard(side)
    exits = orders[orders[:, 7] == 0]
    return dict(P保護開始組=int(np.sum(guard[:, 2] == 1)), P返済予約=int(np.sum(guard[:, 2] == 2)),
                P実返済=int(np.sum(guard[:, 2] == 3)), P部分利確後予約維持=int(np.sum(guard[:, 2] == 4)),
                P元全返済優先=int(np.sum(guard[:, 2] == 5)), P実返済枚数=int(exits[exits[:, 6] == 70, 4].sum()),
                D早期半減予約=int(np.sum((risk[:, 2] == 1) & (risk[:, 3] == 50))),
                D早期半減実注文=int(np.sum(exits[:, 6] == 50)), D早期半減実枚数=int(exits[exits[:, 6] == 50, 4].sum()),
                元の途中半減実注文=int(np.sum(exits[:, 6] == 30)), 元の途中半減実枚数=int(exits[exits[:, 6] == 30, 4].sum()),
                C方向停止=int(np.sum(block[:, 2] == 1)), C失効確認=int(np.sum(block[:, 2] == 2)),
                C再成立解除=int(np.sum(block[:, 2] == 3)), C場末まで停止方向=len(stopped),
                時間帯全返済イベント=int(np.sum(timed[:, 2] == 1)),
                時間帯又は古い準備禁止=int(np.sum(timed[:, 2] == 2)),
                時間帯実返済注文=int(np.sum(exits[:, 6] == 71)), 時間帯実返済枚数=int(exits[exits[:, 6] == 71, 4].sum()),
                時間帯事前窓=len(ledger.get('time_windows', [])),
                時間窓終了後まで有効観測なし=sum(w['窓終了後の初観測'] for w in ledger.get('time_windows', [])))


def campaigns(ledger):
    """
    機能: 組番号変更の影響を避けて、新規原本行と方向で全返済の会計をまとめる。
    引数: ledger (dict)。
    返り値: dict[tuple,dict]。入口価格が変われば別途明示する。
    """
    output = {}
    for cycle in ledger['cycles']:
        cid = int(cycle[0])
        trades = [t for t in ledger['net_trades'] if t['組'] == cid]
        assert trades
        first = trades[0]
        key = first['新規原本行'], first['方向']
        assert key not in output
        output[key] = dict(campaign=cid, direction=first['方向'], entry_row=first['新規行'],
            entry_seq=first['新規原本行'], entry_time=first['新規時刻'], entry_price=first['建値'],
            exit_row=max(t['返済行'] for t in trades), exit_time=max(t['返済時刻'] for t in trades),
            net=sum(t['収支'] for t in trades), gross=sum(t['利益損失前'] for t in trades),
            fees=sum(t['手数料'] for t in trades), lots=sum(t['枚数'] for t in trades),
            fixed_atr=float(cycle[5]), risk=float(cycle[4]), trades=trades)
    return output


def same_entries(before, after):
    """
    機能: 同じ入口の管理変更と、見送った入口・新しく出た入口を分ける。
    引数: before/after (dict) は入口別の組会計。
    返り値: dict。差は事後説明に限り、取引選択へ返さない。
    """
    common = set(before) & set(after)
    lost, added = set(before) - set(after), set(after) - set(before)
    return dict(共通入口数=len(common), 消えた入口数=len(lost), 新しい入口数=len(added),
        共通入口の価格不一致数=sum(before[k]['entry_price'] != after[k]['entry_price'] for k in common),
        共通入口の収支差=sum(after[k]['net'] - before[k]['net'] for k in common),
        見送り入口の元利益=sum(max(before[k]['net'], 0.) for k in lost),
        見送り入口の元損失=sum(max(-before[k]['net'], 0.) for k in lost),
        新規追加入口の利益=sum(max(after[k]['net'], 0.) for k in added),
        新規追加入口の損失=sum(max(-after[k]['net'], 0.) for k in added))


def case(cycle, ledger, ready):
    """
    機能: 1組の時刻・返済理由・事後最大順行を説明用にまとめる。
    引数: cycle/ledger/ready (dict)。
    返り値: dict 又は None。将来極値は診断だけに使う。
    """
    if cycle is None:
        return None
    selected = [o for o in ledger['orders'] if int(o[2]) == cycle['campaign']]
    fills = []
    for order in selected:
        i, source = int(order[0]), int(order[1])
        fills.append(dict(新規=bool(order[7]), 売買='買い' if order[3] > 0 else '売り', 枚数=int(order[4]),
            条件公開JST=stamp(ready['time_s'][source]), 約定JST=stamp(ready['time_s'][i]),
            条件元行=source, 約定行=i, 原本連番=int(ready['seq'][i]), 価格=float(order[5]),
            観測現在値=float(ready['last'][i]), 理由=REASONS.get(int(order[6]), '新規' if order[7] else str(int(order[6])))))
    entry, exit_row = cycle['entry_row'], cycle['exit_row']
    signed = cycle['direction'] * (ready['last'][entry:exit_row + 1] - cycle['entry_price'])
    events = []
    for name in ('guard_events', 'block_events', 'risk_events'):
        for event in ledger.get(name, []):
            if int(event[1]) == cycle['campaign']:
                events.append(dict(種別=name, JST=stamp(ready['time_s'][int(event[0])]), 値=event.tolist()))
    return dict(direction='ロング' if cycle['direction'] > 0 else 'ショート', entry_JST=stamp(cycle['entry_time']),
                exit_JST=stamp(cycle['exit_time']), net=cycle['net'], gross=cycle['gross'], fees=cycle['fees'],
                初回枚数=cycle['lots'], 準備時ATR=cycle['fixed_atr'],
                事後最大順行価格幅=float(signed.max(initial=0)), 事後最大逆行価格幅=float(-signed.min(initial=0)),
                売買=fills, 制御イベント=events,
                決済=[dict(JST=stamp(t['返済時刻']), 枚数=t['枚数'], 価格=t['返済値'], 収支=t['収支'],
                           理由=REASONS.get(t['理由'], str(t['理由']))) for t in cycle['trades']])


def worst_cases(results, ledgers, inputs):
    """
    機能: 原E01観測値版の各市場最悪3場を固定し、全統合の変化を診断する。
    引数: results/ledgers/inputs (dict)。
    返り値: list[dict]。統合版に有利な場を選び直さない。
    """
    output = []
    base, improved = results['observed', 'E01'], results['observed', 'E01_GPDC']
    for symbol in SYMBOLS:
        worst = sorted([r for r in base['rows'] if r['symbol'] == symbol], key=lambda r: (r['net'], r['session']))[:3]
        for row in worst:
            key = row['session'], symbol
            before_ledger = ledgers['observed', 'E01'][key]
            after_ledger = ledgers['observed', 'E01_GPDC'][key]
            before, after = campaigns(before_ledger), campaigns(after_ledger)
            totals = next(r for r in improved['rows'] if (r['session'], r['symbol']) == key)
            delta = {k: after.get(k, {}).get('net', 0.) - before.get(k, {}).get('net', 0.) for k in set(before) | set(after)}
            examples = []
            if before:
                examples.append(('元の最大負け組', min(before, key=lambda k: before[k]['net'])))
            if delta:
                examples.append(('最も改善した又は悪化が小さい入口', max(delta, key=lambda k: delta[k])))
                examples.append(('最も悪化した又は改善が小さい入口', min(delta, key=lambda k: delta[k])))
            chosen = []
            used = set()
            for label, entry in examples:
                if entry in used:
                    continue
                used.add(entry)
                chosen.append(dict(選択理由=label, 元新規原本行=entry[0], 収支差=delta[entry],
                    before=case(before.get(entry), before_ledger, inputs[key]),
                    after=case(after.get(entry), after_ledger, inputs[key])))
            combined = same_entries(before, after)
            explained = combined['共通入口の収支差'] - combined['見送り入口の元利益'] + combined['見送り入口の元損失'] + combined['新規追加入口の利益'] - combined['新規追加入口の損失']
            assert abs(explained - (totals['net'] - row['net'])) < 1e-5
            output.append(dict(session=key[0], symbol=symbol, 原収支=row['net'], 統合収支=totals['net'],
                収支差=totals['net'] - row['net'], 同入口分解=combined, 統合発動=event_count(after_ledger), 代表例=chosen))
    return output


def main():
    """
    機能: 全固定結果が揃った後だけ読み、部品・時間帯比較と実発動を保存する。
    引数: なし。
    返り値: None。新条件・再選定・再生計算を行わない。
    """
    fixed = read(WORK / 'results/事前固定.json')
    paths = {(model, config['id']): WORK / model / 'results' / (config['id'] + '.json')
             for model in MODELS for config in fixed['catalog']}
    assert len(paths) == 50 and all(p.exists() for p in paths.values()), '全50結果が揃うまで集計しません'
    results = {key: read(path) for key, path in paths.items()}
    pair_analysis = components(results, fixed)
    pair_analysis['出典SHA256'] = {str(p.relative_to(ROOT)): sha(p) for p in paths.values()}
    pair_analysis['コードSHA256'] = sha(Path(__file__))
    save('4部品の有無比較.json', pair_analysis)
    # ----------------------------------------
    all_ledgers, counts, main_ledgers = {}, [], {}
    for key, result in results.items():
        path = WORK / key[0] / 'ledgers' / (key[1] + '.pkl')
        assert sha(path) == result['ledger_SHA256']
        with path.open('rb') as stream:
            ledger = pickle.load(stream)
        all_ledgers[key] = ledger
        for period in PERIODS:
            for symbol in SYMBOLS:
                chosen = [event_count(l) for k, l in ledger.items() if k[0] in fixed[period] and k[1] == symbol]
                totals = {name: sum(r[name] for r in chosen) for name in chosen[0]}
                counts.append(dict(model=key[0], id=key[1], period=period, symbol=symbol, **totals))
        if key[1] in fixed['primary']:
            main_ledgers[key] = ledger
    spec = importlib.util.spec_from_file_location('wave85_diagnosis_inputs', WORK / 'prepare.py')
    prepare = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = prepare
    spec.loader.exec_module(prepare)
    inputs, _, _ = prepare.load_inputs(verify=True)
    examples = worst_cases(results, main_ledgers, inputs)
    primary_comparison = []
    for model in MODELS:
        for identifier in ('E01_G', 'E01_GPDC'):
            for period in PERIODS:
                for symbol in SYMBOLS:
                    entries = []
                    for key in inputs:
                        if key[0] in fixed[period] and key[1] == symbol:
                            entries.append(same_entries(campaigns(main_ledgers[model, 'E01'][key]), campaigns(main_ledgers[model, identifier][key])))
                    summed = {name: sum(r[name] for r in entries) for name in entries[0]}
                    primary_comparison.append(dict(model=model, id=identifier, period=period, symbol=symbol, **summed))
    save('主3の実発動と損失例.json', dict(説明=[
        '原版と改修は同じ保存データへ因果的に再生済み。この診断は結果説明だけであり、将来極値や原版の負けを取引条件へ戻さない。',
        '原版の最悪3場を各市場で選ぶ。統合版に有利な場へ差し替えず、同じ入口の改善・悪化と入口見送りを分ける。',
        '時刻は原板のCurrentPriceTime。新規の条件公開元は追跡準備又は更新元で、発動判断そのものの時刻と同義ではない。',
        'P保護開始・返済予約・実約定を区別する。Dは元の半減と共通回数枠を使うため、Dが元半減を前倒しして利益も減らし得る。',
        'Cは方向別に停止し、新しい両市場資料で失効と再成立を確認して解除する。停止数そのものを回避できた損失数とは呼ばない。'],
        発動数=counts, 主3同入口分解=primary_comparison, 原観測版最悪3場=examples, 主3固定=fixed['primary'], 再選定=False,
        結果SHA256=pair_analysis['出典SHA256'], コードSHA256=sha(Path(__file__))))
    timing = []
    for model in MODELS:
        for parent in fixed['primary']:
            for suffix in ('_J', '_U', '_JU'):
                identifier = parent + suffix
                for period in PERIODS:
                    for symbol in SYMBOLS:
                        before = brief(results[model, parent]['periods'][period][symbol])
                        after = brief(results[model, identifier]['periods'][period][symbol])
                        entries = [same_entries(campaigns(all_ledgers[model, parent][k]), campaigns(all_ledgers[model, identifier][k]))
                                   for k in inputs if k[0] in fixed[period] and k[1] == symbol]
                        activity = next(r for r in counts if r['model'] == model and r['id'] == identifier and r['period'] == period and r['symbol'] == symbol)
                        timing.append(dict(model=model, parent=parent, id=identifier, period=period, symbol=symbol,
                            before=before, after=after, difference=difference(before, after),
                            実発動={name: value for name, value in activity.items() if name.startswith('時間')},
                            入口分解={name: sum(r[name] for r in entries) for name in entries[0]}))
    assert len(timing) == 108
    save('時間帯見送りの比較.json', dict(説明='主3の各々を元条件と日中J・米国U・双方JUで比較。結果による選び直しは行わない。',
        比較=timing, 主3固定=fixed['primary'], 再選定=False, 結果SHA256=pair_analysis['出典SHA256'], コードSHA256=sha(Path(__file__))))
    print('4部品384対照・時間帯108対照・原版最悪6口座の事後診断を保存しました', flush=True)


if __name__ == '__main__':
    main()
