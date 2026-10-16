"""正式完了許可後だけ、反転制限と価格候補の経路変更を独立分類する。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R


def dense_events(ledger: dict) -> np.ndarray:
    """
    機能: 疎保存した追従候補イベントを全原行へ復元する。
    引数: ledger(dict)。
    返り値: ndarray[int8]は元の新規候補方向。保存SHAとの一致を確認する。
    """
    changes = ledger['trend_event_changes']
    output = np.zeros(ledger['input_rows'], dtype=np.int8)
    for index, row in enumerate(changes[:, 0].astype(int)):
        end = int(changes[index + 1, 0]) if index + 1 < len(changes) else len(output)
        output[row:end] = int(changes[index, 1])
    import hashlib
    assert hashlib.sha256(output.tobytes()).hexdigest() == ledger['trend_event_SHA256']
    return output


def status(observed: np.ndarray, anchor: np.ndarray, exit_time: float, side: int,
           own_tick: float, peer_tick: float) -> tuple[bool, bool, bool]:
    """
    機能: 四源の更新及び両気配・両LPの進行を独立式で判定する。
    引数: observed/anchor(ndarray)、exit_time/own_tick/peer_tick(float)、side(int)。
    返り値: tuple[bool,bool,bool]は新源、気配進行、LP進行。
    """
    qualified = True
    for row in (observed, anchor):
        qualified &= bool(np.isfinite(row[:18]).all() and np.all(row[18:] == 1))
        qualified &= all(row[index] >= 0 for index in (0, 5, 10, 14))
        qualified &= bool(0 < row[3] < row[4] and 0 < row[8] < row[9] and row[13] > 0 and row[17] > 0)
    fresh = qualified and all(observed[index] > anchor[index] and observed[sequence] > anchor[sequence]
        and observed[clock] > anchor[clock] and observed[clock] > exit_time
        for index, sequence, clock in ((0, 1, 2), (5, 6, 7), (10, 11, 12), (14, 15, 16)))
    quotes = fresh and all(side * (observed[field] - anchor[field]) >= tick - 1e-8
        for field, tick in ((3, own_tick), (4, own_tick), (8, peer_tick), (9, peer_tick)))
    prices = fresh and all(side * (observed[field] - anchor[field]) >= tick - 1e-8
        for field, tick in ((13, own_tick), (17, peer_tick)))
    return bool(fresh), bool(quotes), bool(prices)


def previous_groups(ledgers: dict, fixed: dict) -> dict:
    """
    機能: 前親の実完了純損益・停止理由と次の同方向/反対方向を前後区間別に分類する。
    引数: ledgers/fixed(dict)。
    返り値: dictは条件ごとの既存親分類。除外を新戦略成績と呼ばない。
    """
    answer = {}
    for symbol in R.SYMBOLS:
        answer[symbol] = {}
        for period in ('前16', '後15', '全31'):
            session_names = R.partitions(fixed['全31'])[period]
            cohorts = {}
            for session in session_names:
                trades = ledgers[session, symbol]['trades']
                for i, trade in enumerate(trades):
                    if i == 0:
                        tag = '最初の親'
                    else:
                        previous = trades[i - 1]
                        assert previous[3] < trade[2]
                        kind = '前親損失' if previous[11] < 0 else '前親利益' if previous[11] > 0 else '前親ゼロ'
                        direction = '同方向' if previous[4] == trade[4] else '反対方向'
                        reason = '停止' if int(previous[13]) in (1, 2) else 'その他'
                        tag = f'{kind}_{direction}_{reason}'
                    cohorts.setdefault(tag, []).append(trade)
            answer[symbol][period] = {tag: R.totals(np.asarray(values).reshape(-1, 16)) for tag, values in cohorts.items()}
    return answer


def gate_events(key: tuple, ledger: dict, config: dict, material: dict) -> dict:
    """
    機能: 実完了親の記憶と四源基準を独立検算し、反対見送りの原因を整理する。
    引数: key(tuple[str,str])、ledger/config/material(dict)。
    返り値: dictは記憶・基準・源更新・候補判定の全疎イベント診断。
    """
    events, trades = ledger['loss_reentry_events'], ledger['trades']
    columns = {name: i for i, name in enumerate(ledger['loss_event_columns'])}
    record = material['prices'][key]
    own_tick = record['tick']
    peer_tick = 10. if key[1] == 'TOPIX' else .5
    summary = dict(記憶更新=0, 記憶解除=0, 欠測後基準作成=0, 反対判定=0, 合格=0, 拒否=0,
        源更新不足=0, 気配進行不足=0, LP進行不足=0, 持続不足=0,
        合格だが実親なし=0, 拒否後同候補再利用=0, 料金だけの損失記憶=0)
    details = []
    for event in events:
        item = {name: float(event[index]) for name, index in columns.items()}
        code, row = int(item['code']), int(item['row'])
        previous = trades[trades[:, 3] <= row]
        assert len(previous)
        previous = previous[-1]
        assert item['previous_parent'] == previous[0]
        assert item['previous_side'] == previous[4] and item['previous_net'] == previous[11]
        assert item['previous_exit_reason'] == previous[13] and item['previous_exit_row'] == previous[3]
        assert item['previous_exit_time'] == record['time_s'][int(previous[3])]
        active = previous[11] < 0 and (config['loss_reentry_trigger'] == 'any_net_negative' or int(previous[13]) in (1, 2))
        assert bool(item['loss_active']) == active
        if code in (1, 2):
            assert (code == 1) == active
            summary['記憶更新' if active else '記憶解除'] += 1
            summary['料金だけの損失記憶'] += int(active and previous[10] >= 0 and previous[11] < 0)
            if item['anchor_kind'] == 1:
                assert item['anchor_own_bbo_index'] == previous[3]
                assert item['anchor_own_bbo_seq'] == record['seq'][int(previous[3])]
                assert item['anchor_own_lp_index'] == material['execution_lp_index'][key][int(previous[3])]
                assert item['anchor_own_lp_time'] == item['previous_exit_time']
            continue
        if code == 3:
            summary['欠測後基準作成'] += 1
            assert int(item['anchor_kind']) == 2 and item['anchor_row'] == row
            assert all(item[f'anchor_{channel}_time'] > item['previous_exit_time']
                for channel in ('own_bbo', 'peer_bbo', 'own_lp', 'peer_lp'))
            continue
        if code != 4:
            continue
        side = int(item['candidate_side'])
        assert active and side == -int(previous[4]) and item['gate_required'] == 1
        anchor = event[12:34]
        observed = event[34:56]
        fresh, quotes, prices = status(observed, anchor, item['previous_exit_time'], side, own_tick, peer_tick)
        name = config['loss_reentry_kind']
        if name != 'ban_opposite':
            assert (fresh, quotes, prices) == (bool(item['fresh_sources']), bool(item['quotes_progress']), bool(item['prices_progress']))
        accepted = (name == 'fresh_quotes' and quotes or name == 'fresh_price_quotes' and quotes and prices
            or name == 'sustained_price_quotes' and bool(item['sustained']))
        assert accepted == bool(item['gate_accepted'])
        actual = trades[(trades[:, 15] == row) & (trades[:, 4] == side)]
        assert accepted or len(actual) == 0
        summary['反対判定'] += 1
        summary['合格' if accepted else '拒否'] += 1
        summary['合格だが実親なし'] += int(accepted and len(actual) == 0)
        if not accepted:
            if name == 'ban_opposite':
                tag = '全面反対禁止'
            elif not fresh:
                tag = '四源の更新又は時計不足'
                summary['源更新不足'] += 1
            elif not quotes:
                tag = '両市場の両気配進行不足'
                summary['気配進行不足'] += 1
            elif name != 'fresh_quotes' and not prices:
                tag = '両LP進行不足'
                summary['LP進行不足'] += 1
            else:
                tag = '10秒位置維持又は開始後更新不足'
                summary['持続不足'] += 1
        else:
            tag = '合格'
        details.append(dict(判断行=row, 原seq=int(record['seq'][row]), 時刻=R.clock(record['time_s'][row]),
            直前完了親=int(previous[0]), 前方向=int(previous[4]), 前純額円=float(previous[11]),
            反対候補方向=side, 分類=tag, 基準種別=int(item['anchor_kind']),
            基準行=int(item['anchor_row']), 四源更新=fresh, 気配進行=quotes, LP進行=prices,
            持続=bool(item['sustained']), 合格=accepted, 実親=len(actual),
            実親純額円=float(actual[:, 11].sum()), 全イベント=item))
    return dict(全検算=True, 分類集計=summary, 反対判断=details)


def candidates(key: tuple, ledger: dict, material: dict, config: dict) -> dict:
    """
    機能: 15秒発火、5秒許可、原行判断、実約定の段階を別々に分類する。
    引数: key(tuple[str,str])、ledger/material/config(dict)。
    返り値: dictは活動不足と入口時刻移動の計数。
    """
    candidate = ledger['trend_candidate_state']
    pulse = candidate['pulse']
    event = dense_events(ledger)
    actual = ledger['trades']
    mapped = R.published_grid(material['prices'][key], material['grids'][key[0]]['grid'])
    clock = material['trend_prices']['I3'][key[0]]['candidate_grid']
    permission = ledger['trend_lp_allowed'] if config['trend_source'] != 'P0' else {
        side: material['entries'][key[0]]['entries']['J2']['long_allowed' if side == 1 else 'short_allowed'] for side in (-1, 1)}
    rows = []
    for value in candidate['candidates']:
        raw, side, g = int(value[1]), int(value[2]), int(value[0])
        published = int(mapped[raw])
        yes = published >= 0 and bool(permission[side][published])
        assert int(event[raw]) == side if yes else int(event[raw]) == 0
        parent = actual[(actual[:, 15] == raw) & (actual[:, 4] == side)]
        rows.append(dict(発火格子=g, 発火時刻=R.clock(clock[g]), 判断行=raw,
            判断時刻=R.clock(material['prices'][key]['time_s'][raw]),
            発火から判断秒=float(material['prices'][key]['time_s'][raw] - clock[g]),
            許可格子=published, 許可=yes, 実親=len(parent), 実親純額円=float(parent[:, 11].sum())))
    return dict(価格源=config['trend_source'], 有効候補格子=int(candidate['valid'].sum()),
        方向状態格子=int(np.sum(candidate['states'] != 0)), 発火=int(np.sum(pulse != 0)),
        写像候補=len(candidate['candidates']), 許可通過=int(np.sum(event != 0)), 実親=len(actual),
        段階別=rows)


def main() -> None:
    """
    機能: 全38の実損失・反対確認・候補段階を独立分類し原因証跡を保存する。
    引数: --根許可後(bool)は必須。全31正式完了通知後のみ実行する。
    返り値: None。候補変更や親除外による新戦略成績は計算しない。
    """
    R.permission()
    fixed, assembled = R.validate()
    material = R.material()
    output, groups = {}, {}
    count = 0
    for config in fixed['条件']:
        ident = config['id']
        ledger = R.load_ledgers(ident)
        groups[ident] = previous_groups(ledger, fixed)
        output[ident] = {}
        for key, value in ledger.items():
            output[ident]['|'.join(key)] = dict(候補段階=candidates(key, value, material, config),
                損失後反対確認=gate_events(key, value, config, material))
            count += 1
        print(f'{ident}: 直前実完了親・候補・四源再参加を独立分類', flush=True)
    assert count == 2356
    R.save('全38の直前完了親と四源再参加及び候補時刻移動の独立原因分解.json', dict(
        全合格=True, 口座=count, 条件数=38, 主=fixed['主'], 前16固定参考=assembled['selected'],
        前親損益方向停止別=groups, 全口座の候補段階及び四源反対確認=output,
        注意=['観測資格復旧は発火消費時刻も変える。候補集合を部分集合として扱わない。',
            'R3正常性と共同進行は将来期待値の証明ではない。拒否で失った勝ちも会計分解へ含める。',
            '判定合格と実約定は別。予約時に損失記憶を更新しない。'],
        計算コードSHA256=R.digest(Path(__file__)), **R.provenance()))


if __name__ == '__main__':
    main()
