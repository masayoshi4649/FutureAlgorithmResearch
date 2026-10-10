"""遅延付きで他銘柄の板を参照する追加48条件を、保存原本だけで検証する。"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import time

import numpy as np
import pandas as pd

from model import OUT, SESSIONS, SYMBOLS, metrics, save, simulate

# ----------------------------------------
# 旧版モジュールが検索パスへ追加されても、今回の共通選択器だけを明示的に読む。
_research_spec = importlib.util.spec_from_file_location('_wave_v8_research_cross', OUT / 'research.py')
_research_module = importlib.util.module_from_spec(_research_spec)
_research_spec.loader.exec_module(_research_module)
choose, load = _research_module.choose, _research_module.load


GROUP = '２銘柄の板'
FAMILIES = {
    'C01': '両銘柄OFI300の一致',
    'C02': '自OFI60と他OFI300の一致',
    'C03': '両銘柄の板多数決の一致',
    'C04': '両銘柄の最良数量偏りの一致',
    'C05': '両銘柄の純数量変化の一致',
    'C06': '自価格CUSUMと他OFI',
    'C07': '自価格CUSUMと他多数決',
    'C08': '自価格CUSUMと他気配更新',
    'C09': '自多数決に対する他銘柄の逆向き除外',
    'C10': '両価格CUSUMと自OFIの一致',
    'C11': '他銘柄多数決による自銘柄売買',
    'C12': '両銘柄の板６票による多数決',
}


def configs() -> list[dict]:
    """機能: 結果に依存しない12系統×入口2×出口2の48条件を列挙する。

    引数: なし。返り値: 条件辞書一覧 (list[dict])。
    """
    result = []
    for family in FAMILIES:
        for entry in ['逆指値', '追跡1ATR']:
            for exit_name in ['利益保護', '板反転併用']:
                result.append(dict(id=f'{family}_300_{entry}_{exit_name}', family=family,
                                   window=300, entry=entry, exit=exit_name, group=GROUP))
    assert len(result) == 48
    return result


def aligned_peer(own: dict, peer: dict, lag: int = 60) -> tuple[np.ndarray, np.ndarray, dict]:
    """機能: 他銘柄が利用可能になった時刻以前だけを遡って対応付ける。

    引数: own/peer (dict): 単銘柄再生入力。lag (int): 他銘柄解放後の追加待機秒。
    返り値: 対応行番号・有効マスク・監査辞書 (tuple[ndarray, ndarray, dict])。
    """
    own_times = own['features'].time_s.to_numpy(float)
    peer_times = peer['features'].time_s.to_numpy(float)
    if len(peer_times) == 0:
        indices = np.full(len(own_times), -1, dtype=np.int64)
        valid = np.zeros(len(own_times), dtype=bool)
        audit = dict(他銘柄追加待機秒=lag, 特徴行数=len(indices), 他銘柄未到着行=len(indices),
                     他銘柄期限切れ行=0, 他銘柄元ブロック陳腐行=0,
                     自銘柄元ブロック陳腐行=int((own['features'].block_delay_seconds > 60).sum()),
                     有効方向判定行=0, 有効時の最小情報年齢秒=None, 有効時の最大情報年齢秒=None,
                     他銘柄利用可能時刻以下だけ参照=True,
                     同期の限界='他銘柄特徴が未到着のため全方向を中立とする。')
        return indices, valid, audit
    indices = np.searchsorted(peer_times + lag, own_times, side='right') - 1
    exists = indices >= 0
    safe = np.maximum(indices, 0)
    age = own_times - peer_times[safe]
    source_fresh = peer['features'].block_delay_seconds.to_numpy(float)[safe] <= 60
    own_fresh = own['features'].block_delay_seconds.to_numpy(float) <= 60
    valid = exists & (age >= lag) & (age <= lag + 120) & source_fresh & own_fresh
    audit = dict(他銘柄追加待機秒=lag, 特徴行数=len(indices), 他銘柄未到着行=int((~exists).sum()),
                 他銘柄期限切れ行=int((exists & (age > lag + 120)).sum()),
                 他銘柄元ブロック陳腐行=int((exists & ~source_fresh).sum()),
                 自銘柄元ブロック陳腐行=int((~own_fresh).sum()), 有効方向判定行=int(valid.sum()),
                 有効時の最小情報年齢秒=float(age[valid].min()) if valid.any() else None,
                 有効時の最大情報年齢秒=float(age[valid].max()) if valid.any() else None,
                 他銘柄利用可能時刻以下だけ参照=bool(np.all(peer_times[safe[valid]] + lag <= own_times[valid])),
                 同期の限界='受信時刻と銘柄共通行順がない。遅延付き過去参照であり厳密な同時受信ではない。')
    return indices, valid, audit


def cross_directions(own: dict, peer: dict, lag: int = 60) -> tuple[dict[str, np.ndarray], dict]:
    """機能: 過去の他銘柄特徴と自銘柄の解放済み特徴から12方向を作る。

    引数: own/peer (dict): 単銘柄入力。lag (int): 他銘柄追加待機秒。
    返り値: 系統別方向と対応付け監査情報 (tuple[dict[str, ndarray], dict])。
    """
    indices, valid, audit = aligned_peer(own, peer, lag)
    if len(peer['features']) == 0:
        signals = {key: np.zeros(len(indices), dtype=np.int8) for key in FAMILIES}
        audit['方向別行数'] = {key: dict(買い=0, 売り=0) for key in FAMILIES}
        return signals, dict(indices=indices, valid=valid, audit=audit)
    safe = np.maximum(indices, 0)
    own_signals, peer_signals = own['signals'], peer['signals']

    def other(family: str, window: int = 300) -> np.ndarray:
        """機能: 対応する過去の他銘柄方向を取得し無効箇所をゼロにする。

        引数: family (str): 系統。window (int): 窓秒。
        返り値: 自銘柄解放行へ対応付けた他銘柄方向 (ndarray)。
        """
        return np.where(valid, peer_signals[(family, window)][safe], 0).astype(np.int8)

    def agree(*values: np.ndarray) -> np.ndarray:
        """機能: 全方向が非ゼロで一致するときだけその方向を採用する。

        引数: values (ndarray群): 判定方向列。返り値: 一致方向 (ndarray)。
        """
        first = values[0]
        mask = first != 0
        for value in values[1:]:
            mask &= value == first
        return np.where(mask, first, 0).astype(np.int8)

    own_ofi = own_signals[('B05', 300)]
    own_votes = own_signals[('B12', 300)]
    peer_ofi, peer_votes = other('B05'), other('B12')
    own_price, peer_price = own_signals[('P00', 0)], other('P00', 0)
    six = np.stack([own_ofi, own_signals[('B06', 300)], own_signals[('B09', 300)],
                    peer_ofi, other('B06'), other('B09')])
    six_votes = np.where(((six == 1).sum(axis=0) >= 4) & ~(six == -1).any(axis=0), 1,
                         np.where(((six == -1).sum(axis=0) >= 4) & ~(six == 1).any(axis=0), -1, 0))
    signals = {
        'C01': agree(own_ofi, peer_ofi),
        'C02': agree(own_signals[('B05', 60)], peer_ofi),
        'C03': agree(own_votes, peer_votes),
        'C04': agree(own_signals[('B01', 300)], other('B01')),
        'C05': agree(own_signals[('B09', 300)], other('B09')),
        'C06': agree(own_price, peer_ofi),
        'C07': agree(own_price, peer_votes),
        'C08': agree(own_price, other('B06')),
        'C09': np.where(peer_votes != -own_votes, own_votes, 0),
        'C10': agree(own_price, peer_price, own_ofi),
        'C11': peer_votes,
        'C12': six_votes,
    }
    signals = {key: np.where(valid, value, 0).astype(np.int8) for key, value in signals.items()}
    audit['方向別行数'] = {key: dict(買い=int((value == 1).sum()), 売り=int((value == -1).sum())) for key, value in signals.items()}
    return signals, dict(indices=indices, valid=valid, audit=audit)


def enrich_trade(trade: dict, own: dict, peer: dict, alignment: dict, lag: int) -> dict:
    """機能: 注文条件作成に利用した他銘柄時刻・原本行番号を取引へ追記する。

    引数: trade (dict): 一取引。own/peer (dict): 入力。alignment (dict): 対応付け。lag (int): 待機秒。
    返り値: 他銘柄参照の追跡情報を追加した取引辞書 (dict)。
    """
    fi = np.searchsorted(own['features'].seq.to_numpy(), trade['signal_seq'], side='right') - 1
    pi = int(alignment['indices'][fi])
    assert fi >= 0 and pi >= 0 and alignment['valid'][fi]
    other = peer['features'].iloc[pi]
    own_time = float(own['features'].time_s.iloc[fi])
    assert float(other.time_s) + lag <= own_time <= trade['signal_time_s']
    return dict(**trade, 他銘柄追加待機秒=lag,
                二銘柄方向判定時刻=own_time, 他銘柄解放時刻=float(other.time_s),
                他銘柄利用可能時刻=float(other.time_s) + lag,
                他銘柄解放行=int(other.seq), 他銘柄参照最終行=int(other.source_last_seq),
                方向判定時の他銘柄情報年齢秒=own_time-float(other.time_s),
                注文条件作成時の他銘柄情報年齢秒=trade['signal_time_s']-float(other.time_s))


def run_one(own: dict, peer: dict, signal: np.ndarray, alignment: dict, config: dict,
            session: str, symbol: str, delay: str = '次行', lag: int = 60) -> list[dict]:
    """機能: 共通実行器を使って追加方向を売買し、因果関係を検査する。

    引数: own/peer (dict)、signal (ndarray)、alignment/config (dict)、session/symbol/delay (str)、lag (int)。
    返り値: 他銘柄参照証跡を加えた取引一覧 (list[dict])。
    """
    results = simulate(own['tape'], own['features'], signal, own['atr'], own['pressure'], config, session, symbol, delay)
    enriched = []
    for trade in results:
        row = enrich_trade(trade, own, peer, alignment, lag)
        assert row['source_last_seq'] < row['signal_seq'] <= row['trigger_seq'] < row['entry_seq']
        assert row['他銘柄参照最終行'] < row['他銘柄解放行']
        if row['closed']:
            assert row['entry_seq'] <= row['exit_trigger_seq'] < row['exit_seq']
            assert row['exit_in_session']
        enriched.append(row)
    if session != SESSIONS[-1]:
        assert all(row['closed'] for row in enriched), f'完全セッションの未返済: {session} {symbol}'
    return enriched


def main() -> None:
    """機能: 計画を記録して追加48条件・時間順選択・固定条件の遅延感度を保存する。

    引数: なし。返り値: None。既存108条件の結果を参照せず、原本と過去特徴のみを使う。
    """
    started = time.monotonic()
    conditions = configs()
    tracked = [OUT/'二銘柄検証計画.md', OUT/'cross_research.py', OUT/'model.py', OUT/'research.py']
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    save(OUT/'二銘柄_条件一覧.json', conditions)
    save(OUT/'二銘柄_実行前記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')),
         条件数=len(conditions), 新規API取得=False, 既存108結果を使った閾値調整=False, SHA256=hashes))
    cells, trades, audits, inputs, all_signals = [], [], [], {}, {}
    for session in SESSIONS:
        loaded = {symbol: load(session, symbol) for symbol in SYMBOLS}
        for symbol in SYMBOLS:
            other_symbol = SYMBOLS[1-SYMBOLS.index(symbol)]
            own, peer = loaded[symbol], loaded[other_symbol]
            signals, alignment = cross_directions(own, peer)
            inputs[(session, symbol)] = own
            all_signals[(session, symbol)] = (signals, alignment)
            audits.append(dict(セッション=session, 銘柄=symbol, 他銘柄=other_symbol, **alignment['audit']))
            for config in conditions:
                result = run_one(own, peer, signals[config['family']], alignment, config, session, symbol)
                cells.append(metrics(result, session, symbol, config))
                trades.extend(dict(方式=config['id'], 群=GROUP, セッション=session, 銘柄=symbol, 他銘柄=other_symbol, **row) for row in result)
            print(f'{session} {symbol}: 二銘柄48条件完了、累計{time.monotonic()-started:.1f}秒', flush=True)
    frame = pd.DataFrame(cells)
    frame.to_csv(OUT/'二銘柄_全条件セッション集計.csv', index=False, encoding='utf-8-sig')
    save(OUT/'二銘柄_全取引.json', trades)
    pd.DataFrame(trades).to_csv(OUT/'二銘柄_全取引.csv', index=False, encoding='utf-8-sig')
    save(OUT/'二銘柄_時刻対応監査.json', audits)

    # ----------------------------------------
    # 追加条件だけで過去選択し、次のセッションの成績を取り出す。
    selections, forward = [], []
    for test_idx in range(2, len(SESSIONS)):
        selected = choose(frame, GROUP, SESSIONS[:test_idx])
        selected['評価セッション'] = SESSIONS[test_idx]
        selections.append(selected)
        if selected['採用']:
            rows = frame[frame.方式.eq(selected['採用']['方式']) & frame.セッション.eq(SESSIONS[test_idx])]
            forward.extend(rows.to_dict('records'))
    save(OUT/'二銘柄_時間順選択.json', selections)
    pd.DataFrame(forward).to_csv(OUT/'二銘柄_時間順セッション集計.csv', index=False, encoding='utf-8-sig')
    finalists = {GROUP: choose(frame, GROUP, SESSIONS[:5])}
    save(OUT/'二銘柄_既知５セッション選択.json', finalists)
    targets = {selected['採用']['方式'] for selected in selections if selected['採用']}
    targets |= {selected['採用']['方式'] for selected in finalists.values() if selected['採用']}

    # ----------------------------------------
    # 基本60秒で選んだ条件を固定して、約定遅延と他銘柄利用遅延を延長する。
    delay_cells, clock_cells, clock_audits = [], [], []
    for session in SESSIONS:
        for symbol in SYMBOLS:
            other_symbol = SYMBOLS[1-SYMBOLS.index(symbol)]
            own, peer = inputs[(session, symbol)], inputs[(session, other_symbol)]
            signals, alignment = all_signals[(session, symbol)]
            alternatives = {lag: cross_directions(own, peer, lag) for lag in [120, 300]}
            for lag, (_, other_alignment) in alternatives.items():
                clock_audits.append(dict(セッション=session, 銘柄=symbol, **other_alignment['audit']))
            for config in conditions:
                if config['id'] not in targets:
                    continue
                for delay in ['２行後', '次時刻']:
                    result = run_one(own, peer, signals[config['family']], alignment, config, session, symbol, delay)
                    delay_cells.append(metrics(result, session, symbol, config, delay))
                for lag, (other_signals, other_alignment) in alternatives.items():
                    result = run_one(own, peer, other_signals[config['family']], other_alignment, config, session, symbol, lag=lag)
                    clock_cells.append(dict(**metrics(result, session, symbol, config), 他銘柄追加待機秒=lag))
    pd.DataFrame(delay_cells).to_csv(OUT/'二銘柄_約定遅延感度.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(clock_cells).to_csv(OUT/'二銘柄_時計遅延感度.csv', index=False, encoding='utf-8-sig')
    save(OUT/'二銘柄_時計遅延監査.json', clock_audits)
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}, '実行中に計画かコードが変化した'
    save(OUT/'二銘柄_完了記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')),
         経過秒=time.monotonic()-started, 条件数=len(conditions), 集計セル数=len(cells), 取引記録数=len(trades),
         新規実API取得回数=0, 感度条件数=len(targets), 感度対象条件=sorted(targets),
         確定取引数=sum(row['closed'] for row in trades), 実行前後コード不変=True))
    print('二銘柄48条件・時間順選択・遅延感度を保存しました。', flush=True)


if __name__ == '__main__':
    main()
