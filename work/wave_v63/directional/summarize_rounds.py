"""三回の事前固定実験を、全決済組の費用後勝率で同じ基準に整理する。"""

import json
from pathlib import Path

import run as common


HERE = Path(__file__).resolve().parent


def goal_flags(summary: dict) -> dict:
    """機能: 勝率目標と損小利大、標本数の十分さを混同せず判定する。

    引数: summary(dict) は同一銘柄の全場集計。
    返り値: 各目標と未知の負け金額を分離したフラグ(dict)。
    負けなしの場合、平均負けと比率が未観測である事実をそのまま残す。
    """
    cycles = summary['cycles']
    wins = summary['group_wins']
    losses = summary['group_losses']
    rate = wins / cycles if cycles else None
    reached = rate is not None and rate >= .95 and summary['net'] > 0
    payoff = summary['group_payoff']
    return dict(勝率95かつ純益正=reached,
                勝率95かつ純益正かつ平均勝負比超1=bool(reached and payoff is not None and payoff > 1),
                負け金額未観測=bool(cycles and losses == 0),
                標本目安50組12活動場=bool(cycles >= 50 and summary['active_sessions'] >= 12),
                少数標本95パーセント=bool(reached and (cycles < 50 or summary['active_sessions'] < 12)),
                全同値除外せず組数=cycles)


def compact(round_name: str, method: dict, symbol: str) -> dict:
    """機能: 報告に必要な組会計・手数料・活動量・週別損益を取り出す。

    引数: round_name(str)、method(dict)、symbol(str)。
    返り値: 一条件一銘柄の短い集計(dict)。
    """
    summary = method['summary'][symbol]
    fields = ('gross_pnl', 'fees', 'net', 'cycles', 'group_wins', 'group_losses',
              'group_win_rate', 'group_mean_win', 'group_mean_loss', 'group_payoff',
              'group_pf', 'drawdown', 'max_losing_session', 'active_sessions',
              'positive_sessions', 'without_best', 'hold_mean_minutes',
              'hold_median_minutes', 'win_qty', 'loss_qty', 'flat_qty')
    return dict(round=round_name, id=method['id'], symbol=symbol,
                reference_only=method.get('reference_only', False),
                price_mode='passive' if method.get('passive_entry') else 'quote',
                **{name: summary[name] for name in fields}, **goal_flags(summary),
                weeks={week: values['net'] for week, values in method['weeks'][symbol].items()})


def main() -> None:
    """機能: 既に完了した三実験だけから、成功例と失敗を隠さない一覧を保存する。

    引数: なし。
    返り値: なし(None)。売買・閾値の変更、未来の成績最適化は行わない。
    """
    rows, hashes = [], {}
    for name in ('round1', 'round2', 'round3'):
        path = HERE / name / '集計結果.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        hashes[name] = common.digest(path)
        for method in payload['methods']:
            for symbol in ('TOPIX', 'NK225'):
                rows.append(compact(name, method, symbol))
    counts = {}
    for name in ('round1', 'round2', 'round3'):
        subset = [row for row in rows if row['round'] == name]
        counts[name] = {symbol: {
            '条件数': sum(row['symbol'] == symbol for row in subset),
            '黒字条件数': sum(row['symbol'] == symbol and row['net'] > 0 for row in subset),
            '95勝率純益正条件数': sum(row['symbol'] == symbol and row['勝率95かつ純益正'] for row in subset),
            '95勝率純益正平均勝負比超1条件数': sum(row['symbol'] == symbol and row['勝率95かつ純益正かつ平均勝負比超1'] for row in subset),
            '十分標本で95勝率純益正条件数': sum(row['symbol'] == symbol and row['勝率95かつ純益正'] and row['標本目安50組12活動場'] for row in subset),
        } for symbol in ('TOPIX', 'NK225')}
    # ----------------------------------------
    # 固定した価格拒否の対照系列を載せ、勝った条件だけに報告を絞らない。
    chain_ids = ('R1_P2_N_C', 'R1_P2_F_C', 'R2_P2_C_quote', 'R2_P2_C_passive',
                 'R3_P2_C_quote', 'R3_WAIT_C_quote', 'R3_FLOW_C_quote', 'R3_DEPTH_C_quote')
    result = {
        '結論の範囲': '既知25場での改善実験。未来の収益性の証明や独立な検証ではない。各実験は損益閲覧前に固定した。',
        '主判定': '初回新規から全玉返済までの組について、全ての往復費用控除後の純益>0を勝ちとする。無取引は勝ちにしない。',
        '標本目安': '50組・12活動場はユーザー条件ではなく十分さ目安。少数の95〜100%は消さず別枠へ。',
        '必要算術': '95%勝率と平均勝ち/平均負け>1が同時に成立すればPFは19を超える。負けなしは分母未観測。',
        '板の限界': 'R2/R3の共通価格表示量は完全OFIではない。R2執行proxyは最終値由来。受信時計がないP3は参考。',
        '指値の限界': '一呼値通過時に固定指値で全量約定とする追加仮定。実商品のmini/microの順番・板はない。',
        '条件数': len(rows) // 2, '対照再掲を含む': True, '結果SHA256': hashes,
        '実験別件数': counts,
        '小標本を含む95パーセント例': [row for row in rows if row['勝率95かつ純益正']],
        '価格拒否の固定対照系列': [row for row in rows if row['id'] in chain_ids],
        '全条件': rows,
    }
    common.save(HERE / '三ラウンドの要点.json', result)
    print(json.dumps({'件数': counts, '95例': result['小標本を含む95パーセント例']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
