"""前半固定の注文12家族を、方向経路・費用・残玉・出口理由から説明する。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pickle
import sys

import numpy as np

sys.dont_write_bytecode = True
import data
import research


HERE = Path(__file__).resolve().parent
OUT = HERE / 'diagnosis'
JST = timezone(timedelta(hours=9))
REASONS = {1: '損切り条件', 2: '固定利確条件', 3: 'トレーリング返済',
           5: '全玉の損失枠', 6: 'セッション終端清算', 9: '主玉返済に伴う残カバー清算'}


def jst(value):
    """
    機能: 保存代理時計を日本時間へ変換する。
    引数: value (float)。
    返り値: str の時刻。実受信時計であるとはみなさない。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def read(path):
    """
    機能: 保存会計又は固定仕様を読む。
    引数: path (Path)。
    返り値: dict 又は list。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def leg_detail(key, record, trade):
    """
    機能: 一つの決済脚を観測済み価格経路に戻し、残玉の経過と最大損益を説明する。
    引数: key (tuple[str,str])、record (dict)、trade (np.ndarray[14])。
    返り値: dict。事後説明であり取引条件には戻さない。
    """
    e, x, side, qty = int(trade[1]), int(trade[2]), int(trade[3]), int(trade[4])
    r = record; times = r['time_s']; value = research.CONTRACTS[key[1]]['pointvalue']
    end_quote = r['bid'][e:x + 1] if side > 0 else r['ask'][e:x + 1]
    path = side * qty * (end_quote - trade[5]) * value - trade[7] - trade[8]
    mid_entry = (r['bid'][e] + r['ask'][e]) / 2.
    mid_exit = (r['bid'][x] + r['ask'][x]) / 2.
    middle = float(side * qty * (mid_exit - mid_entry) * value)
    return dict(session=key[0], symbol=key[1], ticket_id=int(trade[0]), cycle_id=int(trade[13]),
                direction='買い' if side > 0 else '売り', quantity=qty,
                entry_i=e, exit_i=x, entry_seq=int(r['seq'][e]), exit_seq=int(r['seq'][x]),
                entry_time=jst(times[e]), exit_time=jst(times[x]), proxy_hold_seconds=float(times[x] - times[e]),
                entry=float(trade[5]), exit=float(trade[6]), entry_CurrentPrice=float(r['price'][e]), exit_CurrentPrice=float(r['price'][x]),
                entry_bid=float(r['bid'][e]), entry_ask=float(r['ask'][e]), exit_bid=float(r['bid'][x]), exit_ask=float(r['ask'][x]),
                entry_spread_ticks=float((r['ask'][e] - r['bid'][e]) / r['tick']),
                exit_spread_ticks=float((r['ask'][x] - r['bid'][x]) / r['tick']),
                net=float(trade[10]), gross=float(trade[9]), fees=float(trade[7] + trade[8]), midpoint_gross=middle,
                execution_cost=middle - float(trade[9]),
                best_observed_liquidation_net=float(path.max()), worst_observed_liquidation_net=float(path.min()),
                profitable_observations=int(np.sum(path > 0)), losing_observations=int(np.sum(path < 0)),
                max_observed_clock_gap=float(np.diff(times[e:x + 1]).max(initial=0)),
                exit_reason=REASONS.get(int(trade[12]), str(int(trade[12]))),
                clock_note='保有秒数・観測間隔はCurrentPriceTimeの差。受信時計での真の経過や観測間の極値は不明。')


def reasons(trades):
    """
    機能: 赤字場の返済理由ごとの全脚損益を分ける。
    引数: trades (np.ndarray[n,14])。
    返り値: list[dict]。損失額の多い理由から示すが候補の再選抜には使わない。
    """
    rows = []
    for reason in np.unique(trades[:, 12].astype(int)):
        x = trades[trades[:, 12] == reason, 10]
        rows.append(dict(reason=REASONS.get(reason, str(reason)), trades=len(x),
                         profit=float(x[x > 0].sum()), loss=float(-x[x < 0].sum()), net=float(x.sum())))
    return sorted(rows, key=lambda r: r['loss'], reverse=True)


def masked_cycle_diagnosis(keys, ledgers, inputs):
    """
    機能: 黒字脚を利確していても全玉では赤字となった親組と、その後に残した時間を調べる。
    引数: keys (list[tuple])、ledgers/inputs (dict)。
    返り値: dict の件数・金額・最大の残存例。
    """
    count = 0; win_cash = loss_cash = cycle_net = 0.; max_residual = None
    for key in keys:
        trades, cycles = ledgers[key]['trades'], ledgers[key]['cycles']
        candidates = cycles[(cycles[:, 6] < 0) & (cycles[:, 3] > 1), 0].astype(int)
        for cycle_id in candidates:
            ts = trades[trades[:, 13] == cycle_id]
            wins = ts[ts[:, 10] > 0]
            if not len(wins):
                continue
            count += 1
            win_cash += float(wins[:, 10].sum())
            loss_cash -= float(ts[ts[:, 10] < 0, 10].sum())
            cycle_net += float(ts[:, 10].sum())
            first_profit = int(wins[:, 2].min()); last_exit = int(ts[:, 2].max())
            times = inputs[key]['time_s']
            elapsed = float(times[last_exit] - times[first_profit])
            if max_residual is None or elapsed > max_residual['proxy_seconds']:
                max_residual = dict(session=key[0], symbol=key[1], cycle_id=int(cycle_id),
                                    first_profitable_exit=jst(times[first_profit]), final_exit=jst(times[last_exit]),
                                    proxy_seconds=elapsed, cycle_net=float(ts[:, 10].sum()),
                                    winning_legs=float(wins[:, 10].sum()), losing_legs=float(-ts[ts[:, 10] < 0, 10].sum()))
    return dict(利益脚を含む赤字親組数=count, その利益脚円=win_cash, その損失脚円=loss_cash,
                その親組収支円=cycle_net, 利益脚返済後の最終清算まで最長例=max_residual,
                解釈='利益を返済した脚があっても、残った脚を含む親組が赤字だった例。経過秒数は代理時計であり、全期間が含み損だったことを示す値ではない。')


def explain(account, mixed):
    """
    機能: 保存会計に沿い、損失が価格経路か費用かを短く区別する。
    引数: account/mixed (dict)。
    返り値: list[str]。ルール改変・新たな候補選択はしない。
    """
    out = []
    if not account['trades']:
        return ['無取引なので収益性の根拠はない。勝ちとして数えない。']
    if account['net'] < 0 and account['midpoint_gross'] <= 0:
        out.append('約定時刻をそろえた中値経路でも利益になっておらず、気配差と手数料がさらに損失を増やした。')
    elif account['net'] < 0:
        out.append('中値経路では利益が残ったが、気配差と手数料を引くと赤字になった。手数料だけを原因とは呼ばない。')
    elif account['net'] > 0:
        out.append('この集計範囲では価格経路の利益が気配差と手数料を上回った。未知の将来でも続くことは未確認。')
    else:
        out.append('取引はあるが合計収支はゼロ。黒字として数えない。')
    if mixed['利益脚を含む赤字親組数']:
        out.append('黒字の脚を返した後も、元玉・反対玉を含む親組では赤字となる例がある。脚の利益割合だけで成功と判定できない。')
    out.append('固定の追加発注遅延は0。有効気配がなければ次の有効観測を待ち、場末の予定返済時刻と実際の観測時刻にも差があり得る。')
    return out


# ----------------------------------------
def main():
    """
    機能: 完成した固定12代表の全30場だけを説明用に診断する。
    引数: なし。
    返り値: None。前半代表を変えず、未完成時は保存せず停止する。
    """
    selection = read(HERE / '前半選定.json')
    family_ids = {r['id'] for r in selection['families']}
    primary_extra = list({r['id']: r for r in selection['primary'] if r['id'] not in family_ids}.values())
    representatives = selection['families'] + primary_extra
    paths = [HERE / 'final/delay0/results' / (r['id'] + '.json') for r in representatives]
    assert all(p.exists() for p in paths), '固定12代表の全30場が揃ってから診断します'
    inputs = data.load_data()
    output = []; sources = {str(p.relative_to(HERE)): data.digest(p) for p in paths}
    for representative, path in zip(representatives, paths):
        result = read(path); identifier = representative['id']
        with (HERE / 'final/delay0/ledgers' / (identifier + '.pkl')).open('rb') as stream:
            ledgers = pickle.load(stream)
        family = dict(config=result['config'], selection_status=representative['status'], symbols={})
        for symbol in research.SYMBOLS:
            rows = [r for r in result['rows'] if r['symbol'] == symbol]
            keys = sorted(k for k in ledgers if k[1] == symbol)
            mixed = masked_cycle_diagnosis(keys, ledgers, inputs)
            worst = []
            for r in sorted(rows, key=lambda x: x['net'])[:3]:
                key = (r['session'], symbol); trades = ledgers[key]['trades']
                largest = leg_detail(key, inputs[key], trades[np.argmin(trades[:, 10])]) if len(trades) else None
                worst.append(dict(session=r['session'], net=r['net'], midpoint_gross=r['midpoint_gross'],
                                  spread_drag=r['spread_drag'], fees=r['fees'], cycles=r['cycles'],
                                  cycle_profit=r['cycle_profit'], cycle_loss=r['cycle_loss'],
                                  leg_profit=r['profit'], leg_loss=r['loss'], exit_reasons=reasons(trades),
                                  worst_leg=largest))
            maximum = None
            for key in keys:
                trades = ledgers[key]['trades']
                if not len(trades):
                    continue
                t = trades[np.argmin(trades[:, 10])]
                if maximum is None or float(t[10]) < maximum['net']:
                    maximum = leg_detail(key, inputs[key], t)
            periods = {p: result['periods'][p][symbol] for p in ('前16', '後14', '対象')}
            family['symbols'][symbol] = dict(periods=periods, explanation=explain(periods['対象'], mixed),
                                            profitable_legs_in_losing_cycles=mixed, worst_leg=maximum, worst3_sessions=worst)
        output.append(family)
    proof = dict(対象='前16だけで固定した12家族代表の全30場・判断当該行の即時約定。結果による代表再選択はしていない。',
                 時計='保有時間はCurrentPriceTimeの差。同時計後続の真の受信間隔は不明。',
                 原理='約定中値での純価格損益−全注文の気配差−手数料＝全脚収支＝全親組収支。中値で約定できた成績とはみなさない。',
                 正負='未返済を残して利益だけを集計しない。全場で全玉ゼロを会計runnerが照合済み。',
                 families=output[:12], primary_extra=output[12:], source_SHA256=sources,
                 selection_SHA256=data.digest(HERE / '前半選定.json'), code_SHA256=data.digest(Path(__file__)),
                 未来値の用途='各脚の最大順行・逆行は事後原因説明だけ。売買・候補選択には使わない。',
                 保存気配の限界='拡大した売買気配の中値は、その価格で約定できる値ではない。同じCurrentPriceTimeの各行にある売買気配をそのまま評価するが、実受信時計がなく各価格の更新同期は確証しない。')
    research.save_json(OUT / '12家族代表の損失構造.json', proof)
    print('固定12家族の損失構造と各商品最悪3場を診断しました。候補の再選択なし。')


if __name__ == '__main__':
    main()
