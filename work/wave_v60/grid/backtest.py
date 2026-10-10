"""固定40グリッドを3注文モデルで独立再生し、持越し含みと全注文費用を残す。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from accounting import period_account
from engine import replay, ORDER_COLUMNS, TRADE_COLUMNS, REASONS
from features import load_streams


HERE = Path(__file__).resolve().parent
FAMILIES = {'G0': '上限付き往復格子', 'G1': '損失予算付き格子', 'G2': '方向制限と逆玉整理',
            'G3': '逆行をカバーする両建て', 'G4': '順張り格子'}
PRICE_MODES = {'quote': '次行の売買気配', 'mid': '次行中値の参考', 'passive': '待機指値の通過確認'}
CODE_FILES = ('accounting.py', 'features.py', 'engine.py', 'check_engine.py', 'backtest.py')


def clean(value: object) -> object:
    """機能: 非有限値をnullにし、NumPy型を日本語JSON互換へ変換する。

    引数: value(object)。返り値: JSONへ格納できる値(object)。
    """
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: object) -> None:
    """機能: 日本語・有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def digest(path: Path) -> str:
    """機能: コード・仕様・入力を分割読込でSHA256固定する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def methods() -> list[dict]:
    """機能: 成績を見ずに固定した40条件と3注文モデルを列挙する。

    引数: なし。返り値: 120再生条件(list[dict])。主5条件は広幅・5段・週内・気配約定。
    """
    out = []
    for family, label in FAMILIES.items():
        for width_id, fraction in (('D075', .00075), ('D125', .00125)):
            for steps in (5, 10):
                for carry_id, carry in (('S', 0), ('W', 1)):
                    condition = f'{family}_{width_id}_L{steps:02d}_{carry_id}'
                    for mode, price_mode in enumerate(PRICE_MODES):
                        out.append(dict(id=f'{condition}_{price_mode}', condition_id=condition, family=family,
                            name=label, price_mode=price_mode, price_name=PRICE_MODES[price_mode],
                            primary=width_id == 'D125' and steps == 5 and carry == 1 and mode == 0,
                            config=dict(family=int(family[1]), fraction=fraction, steps=steps, carry=carry, mode=mode)))
    return out


def freeze(configs: list[dict]) -> dict:
    """機能: 損益前に全コード・共通入力・親仕様と注文モデルの物理契約を固定する。

    引数: configs(list[dict])。返り値: 固定記録(dict)。固定後の無記録変更を拒否する。
    """
    code = {name: digest(HERE / name) for name in CODE_FILES}
    inputs = {name: digest(HERE.parent / name) for name in ('inputs.pkl', 'quotes.pkl')}
    parent_spec = digest(HERE.parent / '調査仕様.json')
    path = HERE / '売買仕様固定.json'
    if path.exists():
        fixed = json.loads(path.read_text(encoding='utf8'))
        assert fixed['コードSHA256'] == code and fixed['入力SHA256'] == inputs and fixed['親仕様SHA256'] == parent_spec
        assert fixed['条件'] == configs
        return fixed
    fixed = dict(固定時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(), 条件=configs,
        コードSHA256=code, 入力SHA256=inputs, 親仕様SHA256=parent_spec,
        原則='全25場は既知資料。40条件を3注文モデルで独立再生し、成績を見て主5条件を変更しない。',
        注文='各段の通常新規/利確は別注文。強制返済とG2逆玉整理は同方向全玉を1注文へまとめる。TOPIXmini fee=floor(qty*41.8)、NKmicro=qty*11。',
        再武装='配置又は再配置より後の原本行で一度条件不成立側を観測してから到達。禁止中は待機を取消し、再許可後も不成立観測が必要。',
        締切='core新規判断と約定の双方を各場limit-300未満に限定し、別場へ跨いだ新規予約も取消す。coverと返済はcore新規締切と区別する。',
        清算='強制判断はlimit-60以後の初観測。約定は同一ザラバ内limit+300未満の次有効原本行。存在しなければ安全停止し架空価格を作らない。',
        指値='前行以前の待機と、買ask<=limit-large_tick/売bid>=limit+large_tickで指値約定。TPも返済気配がTPをlarge_tick以上通過してからそのTPで約定。',
        指値呼値='取引対象はTOPIXmini0.25/NKmicro5。参照large_tickの半分に一致するか全待機指値をassertする。通過量と幅丸めはlarge_tickを維持。',
        行内順='前行の成行予約、前行以前の待機指値約定を先に処理。その後で当行の新しい清算/risk/方向/TP/新規判断を行い、過去に遡る指値取消をしない。',
        方向unknown='準備不足は新規禁止。中立0と区別し、G2整理やG3方向によるcover解除の根拠にしない。価格保護と全体riskは継続。',
        cycle='全玉/予約なしの5分公開行の再基準時、又はDDによる全返済後30分休止の再開時にcycle最高を現在週資産へリセット。週損失予算は週初0基準のまま。',
        追跡='G4・coverの高安は返済可能気配で更新し、cover約定行の返済可能価格から開始。core実建値と返済気配を混ぜない。',
        持越し='場の末尾に残る含みは次場へ引継ぐ。次場開始時のgapも新しい場の期間損益へ計上。FriNight末は週末清算、最後の10/7Dayは調査終了清算。',
        会計='期間純収支=当場の返済粗利益-返済粗損失-当場の全発生fee+期末含み-前場末含み。返済玉のfee控除後勝敗は別記する。',
        部分再生='finish=False/final_reason=0で途中のopen玉と現金をそのまま評価可能。自然金曜末の清算は別に有効で、APIは本体から取得しない。',
        限界='ラージ気配から小型取引を近似する。待機指値は注文の順番・小型板の実約定を保証しない。証拠金・自身の板への影響は推定しない。',
        現在API取得数=0)
    save(path, fixed)
    return fixed


def account_week(stream: dict, result: tuple) -> tuple[list[dict], dict]:
    """機能: 週の全台帳を場へ分け、前場末含みからの時価変化を独立に会計照合する。

    引数: stream(dict)、result(tuple)。返り値: 各場の会計と週の補足記録(tuple)。
    """
    orders, trades, curve, mid_curve, risks, resets, pos, pending, book, cancellations = result
    assert not np.any(pos[:, 1] > 0) and not np.any(pending[:, 0])
    np.testing.assert_allclose(trades[:, 18], trades[:, 15] - trades[:, 16] - trades[:, 17], atol=1e-7)
    np.testing.assert_allclose(orders[:, 13].sum(), trades[:, 16:18].sum(), atol=1e-6)
    np.testing.assert_allclose(curve[-1], trades[:, 18].sum(), atol=1e-5)
    accounts = []
    offsets = np.r_[stream['offsets'], len(curve)]
    for sid, session in enumerate(stream['sessions']):
        first, end = int(offsets[sid]), int(offsets[sid + 1])
        os = orders[orders[:, 6] == sid]
        ts = trades[trades[:, 12] == sid]
        gross, net_legs = ts[:, 15], ts[:, 18]
        fees = float(os[:, 13].sum())
        before_unrealized = float(risks[first - 1, 2:4].sum()) if first else 0.
        after_unrealized = float(risks[end - 1, 2:4].sum())
        period = period_account(float(gross[gross > 0].sum()), float(-gross[gross < 0].sum()), fees,
                                before_unrealized, after_unrealized)
        before_curve = float(curve[first - 1]) if first else 0.
        before_mid = float(mid_curve[first - 1]) if first else 0.
        np.testing.assert_allclose(period['net'], curve[end - 1] - before_curve, atol=1e-5)
        close_pos = risks[end - 1, :2]
        risk = risks[first:end]
        local_curve = np.r_[before_curve, curve[first:end]]
        local_mid_curve = np.r_[before_mid, mid_curve[first:end]]
        cs = cancellations[(cancellations[:, 1] >= first) & (cancellations[:, 1] < end)]
        account = dict(session=session, symbol=stream['symbol'], week=stream['week'], **period,
            gross_pnl=period['realized_gross'], mtm_change=period['unrealized_change'],
            unrealized_start=before_unrealized, unrealized_end=after_unrealized,
            closed_net_profit=float(net_legs[net_legs > 0].sum()), closed_net_loss=float(-net_legs[net_legs < 0].sum()),
            closed_net=float(net_legs.sum()), cycles=len(ts), wins=int((net_legs > 0).sum()), losses=int((net_legs < 0).sum()),
            win_qty=int(ts[net_legs > 0, 4].sum()), loss_qty=int(ts[net_legs < 0, 4].sum()), flat_qty=int(ts[net_legs == 0, 4].sum()),
            gross_win_qty=int(ts[gross > 0, 4].sum()), gross_loss_qty=int(ts[gross < 0, 4].sum()),
            gross_flat_qty=int(ts[gross == 0, 4].sum()), order_count=len(os),
            drawdown=float(np.max(np.maximum.accumulate(local_curve) - local_curve)),
            mid_drawdown=float(np.max(np.maximum.accumulate(local_mid_curve) - local_mid_curve)),
            mid_net=float(mid_curve[end - 1] - before_mid),
            max_long_qty=int(risk[:, 0].max()), max_short_qty=int(risk[:, 1].max()),
            max_gross_qty=int(np.max(risk[:, 0] + risk[:, 1])), max_abs_net_qty=int(np.max(abs(risk[:, 0] - risk[:, 1]))),
            end_long_qty=int(close_pos[0]), end_short_qty=int(close_pos[1]),
            max_long_unrealized_loss=float(-min(0., risk[:, 2].min())),
            max_short_unrealized_loss=float(-min(0., risk[:, 3].min())),
            max_losing_inventory=float(-min(0., risk[:, 4].min())),
            orders=os.tolist(), trades=ts.tolist(), cancellations=cs.tolist(),
            curve=curve[first:end] - before_curve, mid_curve=mid_curve[first:end] - before_mid)
        accounts.append(account)
    np.testing.assert_allclose(sum(a['net'] for a in accounts), curve[-1], atol=1e-5)
    np.testing.assert_allclose(sum(a['mtm_change'] for a in accounts), 0., atol=1e-5)
    return accounts, dict(symbol=stream['symbol'], week=stream['week'], sessions=stream['sessions'],
                          resets=resets.tolist(), order_count=len(orders), cycles=len(trades),
                          net=float(curve[-1]), fees=float(book[1]), cancellations=len(cancellations),
                          final_reason=REASONS[stream['final_reason']], flattened=True)


def summarize(accounts: list[dict]) -> dict:
    """機能: 持越しを二重計上せず、時価純収支・返済勝敗・最大保有を銘柄内で集計する。

    引数: accounts(list[dict])。返り値: 集計(dict)。
    """
    sums = ('gross_profit', 'gross_loss', 'gross_pnl', 'fees', 'net', 'mtm_change', 'closed_net_profit',
            'closed_net_loss', 'closed_net', 'cycles', 'wins', 'losses', 'win_qty', 'loss_qty', 'flat_qty', 'order_count')
    out = {name: sum(a[name] for a in accounts) for name in sums}
    out.update(sessions=len(accounts), active_sessions=sum(a['order_count'] > 0 for a in accounts),
               positive_sessions=sum(a['net'] > 0 for a in accounts), negative_sessions=sum(a['net'] < 0 for a in accounts),
               without_best=out['net'] - max((a['net'] for a in accounts), default=0.),
               worst_session=min((a['net'] for a in accounts), default=0.),
               win_rate=out['wins'] / out['cycles'] if out['cycles'] else None,
               pf=out['closed_net_profit'] / out['closed_net_loss'] if out['closed_net_loss'] else None,
               gross_pf=out['gross_profit'] / out['gross_loss'] if out['gross_loss'] else None)
    average_win = out['closed_net_profit'] / out['win_qty'] if out['win_qty'] else None
    average_loss = out['closed_net_loss'] / out['loss_qty'] if out['loss_qty'] else None
    out.update(win_per_lot=average_win, loss_per_lot=average_loss,
               payoff=average_win / average_loss if average_win is not None and average_loss else None)
    for name in ('max_long_qty', 'max_short_qty', 'max_gross_qty', 'max_abs_net_qty',
                 'max_long_unrealized_loss', 'max_short_unrealized_loss', 'max_losing_inventory'):
        out[name] = max((a[name] for a in accounts), default=0)
    balance = peak = dd = mid_balance = mid_peak = mid_dd = 0.
    for a in sorted(accounts, key=lambda a: a['session']):
        curve = np.r_[balance, balance + a['curve']]
        peaks = np.maximum.accumulate(np.r_[peak, curve])[1:]
        dd = max(dd, float(np.max(peaks - curve)))
        peak = max(peak, float(curve.max()))
        mid_curve = np.r_[mid_balance, mid_balance + a['mid_curve']]
        mid_peaks = np.maximum.accumulate(np.r_[mid_peak, mid_curve])[1:]
        mid_dd = max(mid_dd, float(np.max(mid_peaks - mid_curve)))
        mid_peak = max(mid_peak, float(mid_curve.max()))
        balance += a['net']
        mid_balance += a['mid_net']
    out.update(drawdown=dd, mid_drawdown=mid_dd)
    return out


def main() -> None:
    """機能: 合成監査後の固定を確認し、40条件×3モデルの全成績を保存する。

    引数: CLI --freeze-only 又は --run。返り値: なし(None)。親のGO後だけ --run を実行する。
    """
    parser = argparse.ArgumentParser(description='グリッドの持越し・注文モデル・費用を固定再生する')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--freeze-only', action='store_true')
    action.add_argument('--run', action='store_true')
    args = parser.parse_args()
    configs = methods()
    fixed = freeze(configs)
    if args.freeze_only:
        print('40条件・3注文モデルの損益前固定が完了しました', flush=True)
        return
    streams = load_streams()
    output, audits = [], []
    for ordinal, config in enumerate(configs, 1):
        accounts, week_details = [], []
        for key in sorted(streams):
            stream = streams[key]
            symbol = stream['symbol']
            cap, value, fee_tenths = (10, 1000., 418) if symbol == 'TOPIX' else (20, 10., 110)
            arguments = {name: stream[name] for name in ('mid', 'bid', 'ask', 'limits', 'events', 'final_reason')}
            result = replay(times=stream['time_s'], seqs=stream['seq'], sessions=stream['session_index'],
                            **arguments, **config['config'], cap=cap, value=value, tick=stream['tick'], fee_tenths=fee_tenths)
            selected, detail = account_week(stream, result)
            accounts.extend(selected)
            week_details.append(detail)
            audits.append(dict(method=config['id'], **detail, passed=True))
        summary, weeks = {}, {}
        for symbol in ('TOPIX', 'NK225'):
            selected = [a for a in accounts if a['symbol'] == symbol]
            summary[symbol] = summarize(selected)
            weeks[symbol] = {w: summarize([a for a in selected if a['week'] == w])
                             for w in sorted({a['week'] for a in selected})}
            assert abs(summary[symbol]['net'] - (summary[symbol]['gross_profit'] - summary[symbol]['gross_loss'] - summary[symbol]['fees'])) < 1e-5
        compact = [{k: v for k, v in a.items() if k not in ('curve', 'mid_curve')} for a in accounts]
        output.append(dict(**config, accounts=compact, summary=summary, weeks=weeks, week_details=week_details))
        if config['primary'] or ordinal % 12 == 0:
            print(ordinal, config['id'], [(s, summary[s]['net'], summary[s]['fees'], summary[s]['drawdown'])
                                        for s in ('TOPIX', 'NK225')], flush=True)
    freeze(configs)
    save(HERE / '売買会計監査.json', dict(合格=True, 週口座数=len(audits),
        注文数=sum(a['order_count'] for a in audits), 返済玉数=sum(a['cycles'] for a in audits), 詳細=audits))
    save(HERE / '売買結果.json', dict(methods=output,
        sessions=sorted({a['session'] for m in output for a in m['accounts']}),
        meta=dict(conditions=40, price_models=3, replays=120, accounts=6000, known_sessions=25, unseen=False,
            main_ids=[c['id'] for c in configs if c['primary']], order_columns=ORDER_COLUMNS, trade_columns=TRADE_COLUMNS,
            reasons=REASONS, current_api_requests=0, qty='方向別上限TOPIXmini10枚/NK225micro20枚、段数に応じて一段2/1枚と4/2枚',
            session_pnl='返済粗利益−返済粗損失−当場全注文費用＋期末含み−前場末含み',
            win_quantity='入口/出口費用を配分した返済玉の勝敗枚数。期間時価収支の符号や純保有とは別。',
            price_models_independent=True, freeze_sha256=digest(HERE / '売買仕様固定.json'),
            inputs_sha256=fixed['入力SHA256'], code_sha256=fixed['コードSHA256'],
            final_liquidation='自然金曜ナイトは週末清算、最後の水曜Dayは調査終了清算。',
            limitation=fixed['限界'])))
    print('40条件×3注文モデルの保存を完了しました', flush=True)


if __name__ == '__main__':
    main()
