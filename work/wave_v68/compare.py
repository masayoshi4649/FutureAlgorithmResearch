"""損失削減と利益維持を分け、事前の前半採否規則を適用する。"""

from collections import defaultdict
import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')


def read(path: Path) -> dict:
    """機能: 通常又は圧縮JSONを読み取る。

    引数: path(Path)。返り値: 内容(dict)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def compare(candidate: dict, baseline: dict) -> dict:
    """機能: 同銘柄の損失削減、利益維持、活動維持を計算する。

    引数: candidate/baseline(dict)。返り値: 比較指標(dict)。
    """
    loss_cut = 1 - candidate['campaign_loss'] / baseline['campaign_loss']
    gains = candidate['campaign_profit'] / baseline['campaign_profit']
    net = candidate['net'] / baseline['net']
    activity = candidate['active_sessions'] / baseline['active_sessions']
    count = candidate['campaigns'] / baseline['campaigns']
    dd = candidate['max_session_drawdown'] / baseline['max_session_drawdown']
    tests = dict(負け組損失10パーセント削減=loss_cut >= .1,
        勝ち組利益80パーセント維持=gains >= .8,
        収支80パーセント維持=net >= .8,
        活動場80パーセント維持=activity >= .8,
        組数70パーセント維持=count >= .7,
        黒字=candidate['net'] > 0,
        一枚平均勝負比一超=candidate['lot_payoff'] is not None and candidate['lot_payoff'] > 1,
        場内最大下落110パーセント以下=dd <= 1.1)
    return dict(campaign_loss_cut=loss_cut, campaign_profit_retention=gains, net_retention=net,
        activity_retention=activity, campaign_retention=count, drawdown_ratio=dd,
        partial_loss_cut=1-candidate['loss']/baseline['loss'],
        partial_profit_retention=candidate['profit']/baseline['profit'],
        net_change=candidate['net']-baseline['net'],
        max_campaign_loss_change=candidate['max_campaign_loss']-baseline['max_campaign_loss'],
        tests=tests, eligible=all(tests.values()))


def stability(rows: list[dict], names: list[str], symbol: str) -> dict:
    """機能: 大勝ち集中と場末累積収支の下落を計測する。

    引数: rows(list[dict])、names(list[str])、symbol(str)。返り値: 診断(dict)。
    """
    subset = [r for r in rows if r['session'] in names and r['symbol'] == symbol]
    days = defaultdict(float)
    for row in subset:
        days[row['session'][:10]] += row['net']
    largest = max(days, key=days.get)
    balance, peak, drawdown, streak, longest = 0., 0., 0., 0, 0
    for row in sorted(subset, key=lambda r: r['session']):
        balance += row['net']
        peak = max(peak, balance)
        drawdown = max(drawdown, peak-balance)
        streak = streak+1 if row['net'] < 0 else 0
        longest = max(longest, streak)
    return dict(best_day=largest, best_day_net=days[largest], without_best_day=balance-days[largest],
        settlement_drawdown=drawdown, losing_streak=longest)


def campaigns(packet: dict, symbol: str) -> dict:
    """機能: 新規位置が完全一致する実建玉群を対応づける。

    引数: packet(dict)、symbol(str)。返り値: 新規識別子と組情報(dict)。
    """
    result = {}
    for ledger in packet['ledgers']:
        if ledger['symbol'] != symbol:
            continue
        for order in ledger['orders']:
            if int(order[7]) != 1:
                continue
            cid = int(order[2])
            key = (ledger['session'], int(order[0]), int(order[3]), order[4], order[5])
            parts = [t for t in ledger['trades'] if t['組'] == cid]
            assert key not in result
            result[key] = dict(net=sum(t['収支'] for t in parts), parts=parts)
    return result


def entry_effect(base: dict, changed: dict, symbol: str) -> dict:
    """機能: 入口維持下で救った損失と削った利益を独立に集計する。

    引数: base/changed(dict)、symbol(str)。返り値: 効果内訳(dict)。
    """
    original, new = campaigns(base, symbol), campaigns(changed, symbol)
    common, removed, added = set(original)&set(new), set(original)-set(new), set(new)-set(original)
    delta = sum(new[k]['net']-original[k]['net'] for k in common)
    removed_net = sum(original[k]['net'] for k in removed)
    added_net = sum(new[k]['net'] for k in added)
    assert abs(delta-removed_net+added_net - (sum(v['net'] for v in new.values())-sum(v['net'] for v in original.values()))) < 1e-5
    return dict(common=len(common), removed=len(removed), added=len(added), same_entry_delta=delta,
        removed_net=removed_net, added_net=added_net,
        improved_losers=sum(original[k]['net']<0 and new[k]['net']>original[k]['net'] for k in common),
        saved_loss=sum(new[k]['net']-original[k]['net'] for k in common if original[k]['net']<0),
        winner_delta=sum(new[k]['net']-original[k]['net'] for k in common if original[k]['net']>0),
        winning_turned_loss=sum(original[k]['net']>0 and new[k]['net']<0 for k in common))


def main() -> None:
    """機能: 全38条件を採否判定し、後半・全期間・出口差を保存する。

    引数: なし。返り値: なし(None)。
    """
    fixed = read(HERE/'事前固定.json')
    data = {v['id']: read(HERE/'observed'/(v['id']+'.json.gz')) for v in fixed['条件']}
    assert len(data) == 38 and all(len(v['rows']) == 56 for v in data.values())
    result, eligible = {}, []
    for identifier, packet in data.items():
        base = data[packet['variant']['base']]
        comparison = {period: {s: compare(packet['periods'][period][s], base['periods'][period][s])
            for s in SYMBOLS} for period in ('前16', '後12', '全28')}
        result[identifier] = dict(variant=packet['variant'], comparison=comparison,
            stability={p: {s: stability(packet['rows'], fixed[n], s) for s in SYMBOLS}
                for p,n in [('前16','前16'),('後12','後12'),('全28','全セッション')]},
            entry_effect={s: entry_effect(base, packet, s) for s in SYMBOLS})
        if identifier not in ('E01','R01') and all(v['eligible'] for v in comparison['前16'].values()):
            eligible.append(dict(id=identifier,
                minimum_loss_cut=min(v['campaign_loss_cut'] for v in comparison['前16'].values()),
                minimum_net_retention=min(v['net_retention'] for v in comparison['前16'].values())))
    eligible.sort(key=lambda r: (-r['minimum_loss_cut'], -r['minimum_net_retention'], r['id']))
    output = dict(selected=eligible[0]['id'] if eligible else None, front_rank=eligible, methods=result,
        used_later_for_selection=False, 完全未見データ=False, 比較基準='各改修のvariant.base',
        実予算補足='A50は既に支払った料金だけを評価損益から控除して判定。将来の返済料金は含めず、次観測への飛越もあり、最終損失0.5R以内は保証しない。')
    (HERE/'損失削減の比較と選定.json').write_text(json.dumps(output,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')
    print('前16による選定:',output['selected'])
    for r in eligible:
        print(r['id'],f"弱い側の負け組損失削減 {r['minimum_loss_cut']:.1%} / 収支維持 {r['minimum_net_retention']:.1%}")


if __name__ == '__main__':
    main()
