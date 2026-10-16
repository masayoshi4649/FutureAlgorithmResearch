"""待機入口の価格差、旧勝ち刈り、旧負け回避と後続経路を独立に恒等分解する。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R
import 元候補対応と独立会計分解 as P
import 判断価格上限の独立診断 as C


def daily_change(old: dict, new: dict, sessions: list[str]) -> dict:
    """
    機能: セッションの赤字救済と無取引化、新赤字及び新活動を分ける。
    引数: old/new(dict)は固定した二条件の集計、sessions(list[str])。
    返り値: dictは商品別の各場の実会計遷移。
    """
    result = {}
    for symbol in R.SYMBOLS:
        a = {row['session']: row for row in old['rows'] if row['symbol'] == symbol}
        b = {row['session']: row for row in new['rows'] if row['symbol'] == symbol}
        details = []
        for session in sessions:
            x, y = a[session], b[session]
            details.append(dict(場=session, 元親数=x['campaigns'], 新親数=y['campaigns'],
                元収支円=x['net'], 新収支円=y['net'], 差円=y['net'] - x['net'],
                既存赤字から黒字=x['net'] < -1e-5 and y['net'] > 1e-5,
                既存赤字から無取引=x['net'] < -1e-5 and y['campaigns'] == 0,
                既存黒字から赤字=x['net'] > 1e-5 and y['net'] < -1e-5,
                既存黒字から無取引=x['net'] > 1e-5 and y['campaigns'] == 0,
                無取引から新赤字=x['campaigns'] == 0 and y['net'] < -1e-5,
                無取引から新黒字=x['campaigns'] == 0 and y['net'] > 1e-5,
                既存赤字の損失額縮小=x['net'] < y['net'] < -1e-5,
                既存赤字の損失額増加=y['net'] < x['net'] < -1e-5))
        flags = ('既存赤字から黒字', '既存赤字から無取引', '既存黒字から赤字', '既存黒字から無取引',
            '無取引から新赤字', '無取引から新黒字', '既存赤字の損失額縮小', '既存赤字の損失額増加')
        result[symbol] = dict(各場=details,
            分類={name: [row['場'] for row in details if row[name]] for name in flags})
    return result


def references(ident: str) -> list[str]:
    """
    機能: 34設計の政策一軸・同出口即時・入口及び既存出口モデル対照を独立生成する。
    引数: ident(str)。
    返り値: list[str]。保存成績の順位から比較相手を選ばない。
    """
    if ident.startswith('A0_'):
        return ['A0_X3' if ident.endswith('X1') else 'A0_X1']
    cap, lane, policy, entry, exit_name = ident.split('_')
    result = [('P0' if cap != 'P0' else 'P1') + f'_{lane}_{policy}_{entry}_{exit_name}',
        cap + ('_L0_' if lane == 'L1' else '_L1_') + f'{policy}_{entry}_{exit_name}', f'A0_{exit_name}']
    if entry == 'A7': result.append(f'{cap}_{lane}_{policy}_A1_{exit_name}')
    result.append(f'{cap}_{lane}_{policy}_{entry}_' + ('X3' if exit_name == 'X1' else 'X1'))
    return list(dict.fromkeys(result))




def add_missing_reasons(value: dict, old_ledgers: dict, new_ledgers: dict, symbol: str) -> None:
    """
    機能: 固有親が反対側で実参加しなかった保存イベントを追記する。
    引数: value/old_ledgers/new_ledgers(dict)、symbol(str)。
    返り値: None。未知理由を将来価格から推定して補完しない。
    """
    for rows, opposite in ((value['元固有一覧'], new_ledgers), (value['新固有一覧'], old_ledgers)):
        for row in rows:
            row['相手側上限拒否の保存根拠'] = C.cap_exclusion(opposite[row['場'], symbol], row['元候補ID'])
            row['相手側不参加の保存理由'] = P.exclusion_evidence(opposite[row['場'], symbol], row['元候補行'], row['方向'])
            if not row['相手側不参加の保存理由']:
                row['原因限定'] = '保存取消・消費イベントへの対応なし。別親の保有経路等を個別に確かめる必要がある。'


def stability_delta(old: dict, new: dict) -> dict:
    """
    機能: 元候補と実新規の差に活動頻度と赤字安定性の変化を添える。
    引数: old/new(dict)は期間別安定性を含む二条件。
    返り値: dictは8期間・商品別の比較。無取引を勝ちへ含めない。
    """
    result = {}
    fields = ('active_sessions', 'no_trade_sessions', 'losing_sessions', 'positive_session_rate',
        'mean_losing_session_yen', 'worst_session_loss_yen', 'downside_rms_units',
        'worst_intraday_drawdown_units')
    for period in old['stability']:
        result[period] = {}
        for symbol in R.SYMBOLS:
            a, b = old['stability'][period][symbol], new['stability'][period][symbol]
            result[period][symbol] = {field: dict(元=a[field], 新=b[field],
                差=b[field] - a[field] if a[field] is not None and b[field] is not None else None)
                for field in fields}
    return result


def change_axis(old: str, new: str) -> str:
    """
    機能: 政策一軸と入口又は既定出口の複合モデル差を明示する。
    引数: old/new(str)。
    返り値: str。複合変更を単一の価格時計効果へ置き換えない。
    """
    a, b = old.split('_'), new.split('_')
    if a[-1] != b[-1]: return '既検証出口モデル'
    if len(a) == len(b) == 5 and a[1:] == b[1:]: return '候補から判断価格の上限一軸'
    if len(a) == len(b) == 5 and a[0] == b[0] and a[2:] == b[2:]: return '現在支持の観測源一軸'
    return '入口待機機構'


def required_pairs(configs: list[dict]) -> dict:
    """
    機能: 損益の順位に依存せず価格24・支持16・即時34の方向付き比較を列挙する。
    引数: configs(list[dict])は事前固定条件。
    返り値: dict[str,list[tuple[str,str]]]。同一即時の恒等比較も二条件で保持する。
    """
    caps, support, immediate = [], [], []
    for c in configs:
        ident = c['id']
        immediate.append(('A0_' + ident.split('_')[-1], ident))
        if ident.startswith('A0_'): continue
        cap, lane, policy, entry, exit_name = ident.split('_')
        if cap != 'P0': caps.append((f'P0_{lane}_{policy}_{entry}_{exit_name}', ident))
        if lane == 'L1': support.append((f'{cap}_L0_{policy}_{entry}_{exit_name}', ident))
    assert len(caps) == 24 and len(support) == 16 and len(immediate) == 34
    return dict(判断上限24=caps, 支持源16=support, 同出口即時34=immediate)



def main() -> None:
    """
    機能: 全34の原候補対応と待機消費を検算し、全一軸と同出口即時差を保存する。
    引数: --根許可後(bool)は全31正式完了通知後だけ指定する。
    返り値: None。新正式候補を追加せず、会計又は戦略を再実行しない。
    """
    R.permission()
    fixed, assembled = R.validate()
    proof_path = R.HERE / '全34条件全31の独立親会計と安定性及びNoCap旧620対照一致.json'
    proof = R.read(proof_path)
    assert proof['全合格'] and proof['口座'] == 2108
    assert proof['根集計SHA256'] == R.digest(R.WORK / 'analysis/比較結果.json')
    ledgers, maps, activity = {}, {}, {}
    for config in fixed['条件']:
        ident = config['id']
        loaded = R.load_ledgers(ident)
        maps[ident] = {key: P.origin_map(ledger) for key, ledger in loaded.items()}
        activity[ident] = {'|'.join(key): dict(待機=P.watch_counts(ledger), 政策=P.policy_counts(ledger), 判断上限=C.state_counts(ledger)) for key, ledger in loaded.items()}
        retained = ('trades', 'entry_wait_events', 'entry_wait_event_columns',
            'entry_wait_event_codes', 'entry_wait_reasons', 'trend_event_SHA256',
            'entry_policy_events', 'entry_policy_event_columns', 'entry_policy_event_codes',
            'entry_cap_state_columns', 'input_rows')
        ledgers[ident] = {key: {name: ledger[name] for name in retained} for key, ledger in loaded.items()}
        for key, ledger in loaded.items():
            index = ledger['entry_cap_state_columns'].index('cap_blocked') + 1
            ledgers[ident][key]['entry_cap_state_changes'] = ledger['entry_cap_state_changes'][
                ledger['entry_cap_state_changes'][:, index] == 1.].copy()
        immediate = 'A0_' + ident.split('_')[-1]
        if immediate in ledgers:
            for key, ledger in ledgers[ident].items():
                assert ledger['trend_event_SHA256'] == ledgers[immediate][key]['trend_event_SHA256']
        assert references(ident) == assembled['comparison_pairs'][ident]
        del loaded
    for ident, accounts in ledgers.items():
        immediate = 'A0_' + ident.split('_')[-1]
        for key, ledger in accounts.items():
            assert ledger['trend_event_SHA256'] == ledgers[immediate][key]['trend_event_SHA256']
    required = required_pairs(fixed['条件'])
    pairs = list(dict.fromkeys([pair for group in required.values() for pair in group]
        + [(reference, ident) for ident in maps for reference in references(ident)]))
    out = {}
    for old, new in pairs:
        values = {}
        for period, sessions in R.partitions(fixed['全31']).items():
            values[period] = {}
            for symbol in R.SYMBOLS:
                value = P.decompose(maps[old], maps[new], symbol, sessions, details=period == '全31')
                assert abs(value['元収支円'] - assembled['results'][old]['periods'][period][symbol]['net']) < 1e-4
                assert abs(value['新収支円'] - assembled['results'][new]['periods'][period][symbol]['net']) < 1e-4
                if period == '全31':
                    add_missing_reasons(value, ledgers[old], ledgers[new], symbol)
                values[period][symbol] = value
        out[old + '→' + new] = dict(期間別元候補対応=values,
            期間別安定性差=stability_delta(assembled['results'][old], assembled['results'][new]),
            全31場別遷移=daily_change(assembled['results'][old], assembled['results'][new], fixed['全31']),
            変更軸=change_axis(old, new))
        print(f'{old}→{new}: 同候補建値・返済・料金・固有親へ全経路差が一致', flush=True)
    R.save('全34判断価格上限と支持源及び即時の同候補建値差と固有経路の独立分解.json', dict(
        全合格=True, 条件数=34, 口座=2108, 一軸対照数=len(pairs), 必須比較群=required, 比較=out,
        各口座待機取消消費成立及び上限観測=activity, 主=fixed['主'], 前16固定参考=assembled['selected'],
        元候補キー=['session', 'symbol', 'source', 'old_candidate_id', 'side'],
        元候補原点照合=['candidate_row', 'candidate_seq', 'candidate_time', 'candidate_quote'],
        厳密実新規キー=['entry_row', 'side', 'quantity', 'entry_price', 'entry_fee', 'entry_decision_row'],
        恒等式='全収支差＝同候補建値差＋同候補返済差＋同候補料金差−元固有純額＋新固有純額。',
        注意=['同候補の価格差は実経路の会計恒等式。建値だけ変更し出口を固定した反実策略成績ではない。',
            '旧固有の負けを消せても、同時に逃した勝ち及び新固有の負けを全会計へ含める。',
            '待機成功親の事後MFE又は利益床で、待機中に未知だった発注成功確率を置き換えない。',
            '同じ出口でも新規価格と時刻から停止・床・保有期限が再設定され、後続連鎖も変わる。',
            '判断cap内の参加でも次正常気配の成行約定はcap外になり得る。実指値の成果とは呼ばない。',
            '政策イベントは保存診断の分類。40状態と補助10旗の全行独立再現を認定するものではない。'],
        根拠SHA256={str(proof_path.relative_to(R.ROOT)): R.digest(proof_path)},
        計算コードSHA256=R.digest(Path(__file__)), 独立分解式SHA256=R.digest(Path(P.__file__)), **R.provenance()))


if __name__ == '__main__':
    main()
