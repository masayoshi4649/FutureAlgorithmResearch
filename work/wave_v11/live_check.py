"""条件を凍結して現在夜間データを一回取得し、未読だった追加区間だけを別集計する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import urllib.parse
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import single as execution
import signals as turning_signals
import catalog
import research

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
LIVE = OUT / 'live'
FROZEN = OUT / '現在照合_凍結記録.json'
JST = ZoneInfo('Asia/Tokyo')
SYMBOLS = ['NK225', 'TOPIX']
BASE_URL = 'http://10.10.100.1:8080/api/v1/history'
TRACKED = [OUT / name for name in ['single.py', 'orders.py', 'accounting.py', 'signals.py', 'catalog.py', 'research.py',
           'live_check.py', '現在照合計画.md', '最終選択.json', '検証計画.md', '文献_予測.md']]
TRACKED += [ROOT / 'work/wave_v8/raw_features.py', ROOT / 'work/wave_v7/fetch_once.py',
            ROOT / 'work/wave_v10/live/取得記録.json', ROOT/'work/wave_v9/turning_signals.py',
            ROOT/'work/wave_v9/execution.py', ROOT/'work/wave_v10/engine.py', ROOT/'work/wave_v10/signals.py']


def load_module(name: str, path: Path):
    """機能: 保存コードを実行入口を呼ばず別名モジュールとして読み込む。

    引数: name (str)、path (Path)。返り値: 読み込んだモジュール (ModuleType)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    """機能: 対象ファイルを読み取り専用でSHA256化する。

    引数: path (Path)。返り値: ハッシュ文字列 (str)。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def now_jst() -> datetime:
    """機能: 日本時間の現在時刻を得る。

    引数: なし。返り値: タイムゾーン付き現在時刻 (datetime)。
    """
    return datetime.now(JST)


def current_night(stamp: datetime) -> tuple[str, datetime, datetime]:
    """機能: 今回固定した夜間の識別子と範囲を通信なしで検査する。

    引数: stamp (datetime)。返り値: セッション名・開始・終了 (tuple[str, datetime, datetime])。
    """
    if 6 <= stamp.hour < 17:
        raise ValueError('今回の一回照合は夜間セッション中だけ実行できます')
    midnight = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
    day = midnight if stamp.hour >= 17 else midnight - timedelta(days=1)
    session = day.strftime('%Y-%m-%d') + '_Night'
    if session != turning_signals.SESSIONS[-1]:
        raise ValueError(f'今回の計画の夜間セッションと異なります: {session}')
    return session, day + timedelta(hours=17), day + timedelta(days=1, hours=6)


def configuration_map() -> dict:
    """機能: 事前定義された全条件をIDで参照できる辞書に変える。

    引数: なし。返り値: IDと条件の辞書 (dict)。
    """
    return {item['id']: item for item in catalog.configs()}


def selection_ids(selections: dict) -> tuple[list[str], dict, list[str]]:
    """機能: 事前に保存された主選択と固定比較条件を読む。

    引数: selections (dict)。返り値: 重複除去ID・主選択・固定比較 (tuple[list, dict, list])。
    """
    ids = sorted(set(selections['現在照合ID']))
    configs = configuration_map()
    if not ids or not set(ids) <= set(configs):
        raise ValueError('現在照合条件のIDが事前定義と一致しません')
    primary = {group: row['採用']['方式'] for group, row in selections['主選択'].items() if row['採用']}
    if set(primary) != set(catalog.PHILOSOPHIES) or not set(primary.values()) <= set(ids):
        raise ValueError('三思想の主選択が不足しています')
    return ids, primary, sorted(set(ids)-set(primary.values()))


def json_value(value: object) -> object:
    """機能: 凍結条件の無限値を保存器と同じnullへ変換する。

    引数: value (object)。返り値: JSON互換の値 (object)。
    """
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [json_value(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def prepare() -> dict:
    """機能: 選択済み条件とコードを一度だけ凍結する。通信は行わない。

    引数: なし。返り値: 保存した凍結記録 (dict)。
    """
    if (LIVE / '一回取得開始.json').exists():
        raise RuntimeError('今回の取得開始記録があるため再凍結できません')
    session, start, end = current_night(now_jst())
    selections = json.loads((OUT / '最終選択.json').read_text(encoding='utf-8'))
    ids, selected, fixed_ids = selection_ids(selections)
    configs = configuration_map()
    if not set(ids) <= set(configs):
        raise ValueError('選択された条件が実行器の固定条件に存在しません')
    old_record = json.loads((ROOT / 'work/wave_v10/live/取得記録.json').read_text(encoding='utf-8'))
    known_cutoff = datetime.fromisoformat(old_record['cutoff']).astimezone(JST)
    if not start < known_cutoff < end:
        raise ValueError('既知データの締切が対象セッション内にありません')
    value = dict(fixed_at=now_jst().isoformat(), session=session, starts_at=start.isoformat(), ends_at=end.isoformat(),
                 known_cutoff=known_cutoff.isoformat(), selected_ids=ids, selected_groups=selected,
                 selected_by_symbol={symbol:{p:r['採用']['方式'] for p,r in groups.items() if r.get('採用')}
                                     for symbol,groups in selections.get('銘柄別主選択',{}).items()},
                 fixed_comparators=fixed_ids, selected_configs=json_value([configs[key] for key in ids]),
                 files_sha256={path.relative_to(ROOT).as_posix(): sha256(path) for path in TRACKED},
                 説明='未読追加分を一回取得して固定条件を照合する。取得前に起きたデータであり、実時間の前向き運用ではない。',
                 主評価='全区間を状態継続して再生し、既知上限直前から取得末尾までの全建玉清算価値差を主評価。新信号起源と旧起源を併記。',
                 取得後再選択=False, 要求数=6, 各要求回数=1, 再試行=False, リダイレクト=False)
    with FROZEN.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    print(f'通信なしで{len(ids)}条件と{len(TRACKED)}ファイルを凍結しました', flush=True)
    return value


def freeze_check() -> dict:
    """機能: 凍結後の変更を検査し、不一致なら取得・評価を止める。

    引数: なし。返り値: 照合済みの凍結記録 (dict)。
    """
    frozen = json.loads(FROZEN.read_text(encoding='utf-8'))
    if datetime.fromisoformat(frozen['fixed_at']) > now_jst():
        raise ValueError('凍結時刻が現在より未来です')
    expected_paths = {path.relative_to(ROOT).as_posix() for path in TRACKED}
    if set(frozen['files_sha256']) != expected_paths:
        raise ValueError('凍結対象の一覧が実装と一致しません')
    for relative, expected in frozen['files_sha256'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha256(path) != expected:
            raise RuntimeError(f'凍結後のファイル変更を検出しました: {relative}')
    configs = configuration_map()
    if frozen['selected_configs'] != json_value([configs[key] for key in frozen['selected_ids']]):
        raise RuntimeError('凍結された選択条件が実装と異なります')
    return frozen


def validate_book(path: Path, symbol: str, start: datetime, cutoff: datetime) -> dict:
    """機能: 生板の銘柄と時刻を検査し取得締切以降の混入を拒否する。

    引数: path (Path)、symbol (str)、start/cutoff (datetime)。返り値: 所属と時刻の監査 (dict)。
    """
    names, contracts = set(), set()
    previous = minimum = maximum = None
    rows = missing = 0
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            if not isinstance(row, dict) or 'Buy1' not in row or 'Sell1' not in row or 'CurrentPriceTime' not in row:
                raise ValueError('生板の必要項目が欠けています')
            names.add(str(row.get('SymbolName', '')))
            contracts.add(str(row.get('Symbol', '')))
            if not row['CurrentPriceTime']:
                missing += 1
                continue
            stamp = datetime.fromisoformat(row['CurrentPriceTime'])
            if stamp.tzinfo is None:
                raise ValueError('生板時刻にタイムゾーンがありません')
            stamp = stamp.astimezone(JST)
            if stamp >= cutoff:
                raise ValueError('共通締切以降の生板時刻があります')
            if previous is not None and stamp < previous:
                raise ValueError('生板の時刻が逆行しています')
            previous = stamp
            if stamp >= start:
                minimum = stamp if minimum is None else min(minimum, stamp)
                maximum = stamp if maximum is None else max(maximum, stamp)
    expected = '日経' if symbol == 'NK225' else 'TOPIX'
    if not names or any(expected not in value for value in names) or len(contracts) != 1 or '' in contracts or minimum is None:
        raise ValueError('生板の銘柄・限月または対象時刻を確認できません')
    return dict(銘柄=symbol, 行数=rows, 時刻欠損数=missing, 銘柄名=sorted(names), 限月=sorted(contracts),
                最初=minimum.isoformat(), 最後=maximum.isoformat(), SHA256=sha256(path))


def fetch() -> dict:
    """機能: 凍結照合後に６URLを各一回取得し、保存後に固定条件を評価する。

    引数: なし。返り値: 取得監査記録 (dict)。再実行は専用ロックで拒否する。
    """
    frozen = freeze_check()
    requested_at = now_jst()
    session, start, end = current_night(requested_at)
    if session != frozen['session']:
        raise ValueError('凍結時と取得時のセッションが異なります')
    cutoff = requested_at.replace(second=0, microsecond=0)
    if cutoff <= datetime.fromisoformat(frozen['known_cutoff']):
        raise ValueError('既知範囲を超える追加分がまだありません')
    LIVE.mkdir(parents=True, exist_ok=True)
    record = dict(started_at=requested_at.isoformat(), cutoff=cutoff.isoformat(), session=session,
                  known_cutoff=frozen['known_cutoff'], fixed_at=frozen['fixed_at'], selected_ids=frozen['selected_ids'],
                  manifest_sha256=sha256(FROZEN), 再試行なし=True, リダイレクトなし=True, 最大要求数=6,
                  説明=frozen['説明'], requests=[], status='取得開始')
    with (LIVE / '一回取得開始.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    execution.save(LIVE / '凍結記録の写し.json', frozen)
    helper = load_module('_wave_v11_readonly_fetch_helper', ROOT / 'work/wave_v7/fetch_once.py')
    helper.LIVE = LIVE
    query = urllib.parse.urlencode({'from': start.isoformat(), 'to': cutoff.isoformat()})
    jobs = []
    for symbol in SYMBOLS:
        jobs.append((f'{symbol}_book', f'{BASE_URL}/{symbol}/book?{query}', LIVE/'book'/symbol/f'{session}.jsonl'))
        for minutes in [1, 5]:
            jobs.append((f'{symbol}_{minutes}min', f'{BASE_URL}/{symbol}/candles/{minutes}min?{query}',
                         LIVE/'応答'/f'{symbol}_{minutes}min.json'))
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(helper.fetch_one, *job) for job in jobs]
            record['requests'] = [future.result() for future in futures]
        execution.save(LIVE / '取得記録.json', record)
        if len(record['requests']) != 6 or not all(row['ok'] for row in record['requests']):
            raise RuntimeError('６要求の一部が失敗しました。再試行せず保存済み記録を確認してください')

        # ----------------------------------------
        # 今回の足はLIVE直下へ保存し、旧研究の入れ子構造を増やさない。
        helper.LIVE = LIVE
        candles, books = [], []
        for symbol in SYMBOLS:
            for minutes in [1, 5]:
                candles.append(helper.convert_candles(LIVE/'応答'/f'{symbol}_{minutes}min.json', symbol, minutes,
                                                      session, start, end, cutoff))
            books.append(validate_book(LIVE/'book'/symbol/f'{session}.jsonl', symbol, start, cutoff))
        record.update(status='取得と検査完了', candles=candles, books=books, finished_at=now_jst().isoformat())
        execution.save(LIVE / '取得記録.json', record)
        execution.save(OUT / '現在照合_取得記録.json', record)
    except Exception as error:
        record.update(status='失敗・再試行禁止', error=f'{type(error).__name__}: {error}', finished_at=now_jst().isoformat())
        execution.save(LIVE / '取得記録.json', record)
        execution.save(OUT / '現在照合_取得記録.json', record)
        raise
    evaluate()
    return record


def liquidation_at(ready: dict, rows: list[dict], cutoff: float) -> dict:
    """機能: 指定境界の直前気配で、全脚の確定分と清算可能な含み損益を計算する。

    引数: ready (dict)、rows (list[dict])、cutoff (float)。返り値: 清算価値と内訳 (dict)。
    境界より後の返済価格・極値は使用しない。保有脚には往復費用２呼値を引当てる。
    """
    index = int(np.searchsorted(ready['time_s'], cutoff, side='left'))-1
    if index < 0:
        return dict(清算価値円=0., 費用倍清算価値円=0., 確定収支円=0., 費用倍確定収支円=0.,
                    評価損益円=0., 費用倍評価損益円=0., 未返済数=0, 返済数=0, 評価行番号=-1)
    seq, tick = int(ready['seq'][index]), ready['tick']
    realized = stress_realized = marked = stress_marked = 0.
    closed = opened = 0
    multiplier = execution.MULTIPLIERS[ready['symbol']]
    for row in rows:
        if row['entry_seq'] > seq:
            continue
        if row['closed'] and row['exit_seq'] <= seq:
            realized += row['net_points']*multiplier
            stress_realized += row['stress_points']*multiplier
            closed += 1
        else:
            quote = ready['bid'][index] if row['side'] > 0 else ready['ask'][index]
            points = row['side']*(quote-row['entry_price'])-2*tick
            marked += points*multiplier
            stress_marked += (points-2*tick)*multiplier
            opened += 1
    return dict(清算価値円=realized+marked, 費用倍清算価値円=stress_realized+stress_marked,
                確定収支円=realized, 費用倍確定収支円=stress_realized,
                評価損益円=marked, 費用倍評価損益円=stress_marked,
                未返済数=opened, 返済数=closed, 評価行番号=seq)


def origin_summary(rows: list[dict], ready: dict, config: dict) -> dict:
    """機能: 同じ起源区分の全脚を、確定利益・損失・未返済評価に分ける。

    引数: rows (list[dict])、ready/config (dict)。返り値: 日本語集計 (dict)。
    """
    closed, opened = [r for r in rows if r['closed']], [r for r in rows if not r['closed']]
    multiplier, cap = execution.MULTIPLIERS[ready['symbol']], config.get('max_positions', 1)
    net = np.array([r['net_points']*multiplier for r in closed], dtype=float)
    stress = sum(r['stress_points']*multiplier for r in closed)
    marked = sum(r['net_points']*multiplier for r in opened)
    return dict(方式=config['id'], 思想=config['philosophy'], 群=config.get('group', config['family']),
                系統=config['family'], セッション=ready['session'], 銘柄=ready['symbol'],
                取引数=len(closed), 未返済数=len(opened), 勝ち数=int((net > 0).sum()), 負け数=int((net < 0).sum()),
                利益円=float(net[net > 0].sum()), 損失円=float(-net[net < 0].sum()), 収支円=float(net.sum()),
                費用倍収支円=float(stress), 評価損益円=float(marked),
                費用倍評価損益円=float(sum(r['stress_points']*multiplier for r in opened)), 設定最大枚数=cap,
                枚数上限換算収支円=float(net.sum()/cap), 枚数上限換算評価円=float(marked/cap))


def evaluate_inputs(frozen: dict, record: dict, inputs: dict) -> dict:
    """機能: 保存入力を状態継続して再生し、追加区間の清算価値差を保存する。

    引数: frozen/record/inputs (dict)。返り値: 集計件数と内訳 (dict)。通信は行わない。
    """
    known = datetime.fromisoformat(frozen['known_cutoff']).timestamp()
    cutoff = datetime.fromisoformat(record['cutoff']).timestamp()
    configs = configuration_map()
    rows, added_rows, known_rows, all_rows, trades, event_rows, audits, curves = [], [], [], [], [], [], [], {}
    for (session, symbol), item in inputs.items():
        ready = research.prepared_inputs({(session, symbol): item})[(session, symbol)]
        audits.append(dict(銘柄=symbol, **item['event_audit']))
        selected_families = {configs[key].get('signal_family') or configs[key]['family'] for key in frozen['selected_ids']}
        event_rows.extend(dict(セッション=session, 銘柄=symbol, 評価区分='追加区間' if r['time_s'] >= known else '既知区間', **r)
                          for r in item['events'].loc[item['events'].family.isin(selected_families)].to_dict('records'))
        for key in frozen['selected_ids']:
            config = configs[key]
            whole, raw, curve = research.run_one(ready, config)
            result = research.trade_records(ready, config, raw)
            before, after = liquidation_at(ready, result, known), liquidation_at(ready, result, cutoff)
            if not np.isclose(after['清算価値円'], whole['収支円']+whole['評価損益円']):
                raise AssertionError(f'末尾の清算価値が注文器の収支と一致しません: {key} {symbol}')
            if not np.isclose(after['清算価値円'], float(curve[-1, 2])):
                raise AssertionError(f'末尾の清算価値が評価曲線と一致しません: {key} {symbol}')
            added = [r for r in result if r['signal_time_s'] >= known]
            old = [r for r in result if r['signal_time_s'] < known]
            new_before, new_after = liquidation_at(ready, added, known), liquidation_at(ready, added, cutoff)
            old_before, old_after = liquidation_at(ready, old, known), liquidation_at(ready, old, cutoff)
            change, stress_change = after['清算価値円']-before['清算価値円'], after['費用倍清算価値円']-before['費用倍清算価値円']
            new_change = new_after['清算価値円']-new_before['清算価値円']
            old_change = old_after['清算価値円']-old_before['清算価値円']
            assert np.isclose(change, new_change+old_change)
            common = dict(評価開始時刻=frozen['known_cutoff'], スナップショット上限=record['cutoff'],
                          全区間状態継続=True, 選択条件凍結時刻=frozen['fixed_at'])
            completed_here = [r for r in result if r['closed'] and r['exit_time_s'] >= known]
            net_here = np.array([r['net_points']*execution.MULTIPLIERS[symbol] for r in completed_here])
            cap = config.get('max_positions', 1)
            rows.append(dict(方式=key, 思想=config['philosophy'], 群=config.get('group', config['family']),
                             系統=config['family'], セッション=session, 銘柄=symbol,
                             評価区分='追加区間の全建玉清算価値変化', 追加清算価値円=change,
                             費用倍追加清算価値円=stress_change, 枚数上限換算追加円=change/cap,
                             枚数上限換算費用倍追加円=stress_change/cap, 新信号起源追加円=new_change, 旧起源追加円=old_change,
                             開始清算価値円=before['清算価値円'], 終了清算価値円=after['清算価値円'],
                             開始未返済数=before['未返済数'], 終了未返済数=after['未返済数'],
                             開始評価損益円=before['評価損益円'], 終了評価損益円=after['評価損益円'],
                             区間内返済数=len(completed_here), 区間内確定利益円=float(net_here[net_here > 0].sum()),
                             区間内確定損失円=float(-net_here[net_here < 0].sum()), 区間内確定収支円=float(net_here.sum()),
                             区間内新規脚数=sum(r['entry_time_s'] >= known for r in result),
                             新信号起源脚数=len(added), 設定最大枚数=cap, **common))
            added_rows.append(dict(**origin_summary(added, ready, config), 評価区分='追加区間の新信号起源', **common))
            known_rows.append(dict(**origin_summary(old, ready, config), 評価区分='既知区間の信号起源全体', **common))
            all_rows.append(dict(whole, 評価区分='セッション全体の参考再生', **common))
            curves[f'{key}|{session}|{symbol}'] = curve
            for row in result:
                assert row['source_last_seq'] <= row['signal_seq'] <= row['condition_seq'] <= row['trigger_seq'] < row['entry_seq']
                if not (config['engine'] == 'single' and config.get('entry_mode') == 1):
                    assert row['condition_seq'] < row['trigger_seq']
                if config['engine'] == 'single' or config.get('signal_family'):
                    assert row['source_last_seq'] < row['signal_seq']
                if row['closed']:
                    assert row['entry_seq'] <= row['exit_trigger_seq'] < row['exit_seq'] and row['exit_in_session']
                    if config['engine'] == 'single':
                        assert row['entry_seq'] < row['exit_trigger_seq']
                trades.append(dict(row, 評価区分='追加区間の新信号起源' if row['signal_time_s'] >= known else '既知区間の信号起源', **common))
    for name, data in [('セッション集計', rows), ('新信号起源集計', added_rows), ('既知起源集計', known_rows), ('全体参考集計', all_rows)]:
        pd.DataFrame(data).to_csv(OUT/f'現在照合_{name}.csv', index=False, encoding='utf-8-sig')
    execution.save(OUT/'現在照合_全取引.json', trades)
    execution.save(OUT/'現在照合_転換イベント.json', event_rows)
    execution.save(OUT/'現在照合_評価曲線.json', curves)
    return dict(条件数=len(frozen['selected_ids']), 集計行数=len(rows), 全取引数=len(trades),
                追加区間取引数=sum(r['評価区分'] == '追加区間の新信号起源' for r in trades),
                転換作成=audits, 固定条件=frozen['selected_ids'])


def evaluate() -> dict:
    """機能: 今回取得済みの原本だけを検査・再抽出して、追加区間を評価する。

    引数: なし。返り値: 集計件数と検証情報 (dict)。通信は一切行わない。
    """
    frozen = freeze_check()
    record = json.loads((LIVE/'取得記録.json').read_text(encoding='utf-8'))
    if record['status'] != '取得と検査完了' or record['manifest_sha256'] != sha256(FROZEN):
        raise RuntimeError('有効な凍結・取得完了記録がありません')
    for item in record['requests']+record['candles']:
        if sha256(ROOT/item['path']) != item['sha256']:
            raise RuntimeError(f'取得・変換後のデータ変更を検出しました: {item["path"]}')
    session = frozen['session']
    cutoff = datetime.fromisoformat(record['cutoff']).timestamp()
    extractor = load_module('_wave_v11_live_raw_extractor', ROOT/'work/wave_v8/raw_features.py')
    feature_audits = []
    for symbol in SYMBOLS:
        quotes = []
        frame, audit = extractor.extract_features(LIVE/'book'/symbol/f'{session}.jsonl', symbol, session, quotes=quotes)
        if frame.empty or not quotes:
            raise ValueError('今回生板の有効な特徴または約定系列がありません')
        if frame.time_s.max() >= cutoff or max(row['time_s'] for row in quotes) >= cutoff:
            raise AssertionError('共通締切以降の観測が混入しました')
        extractor.write_features(frame, audit, LIVE/'features', quotes=quotes)
        feature_audits.append(audit)

    # ----------------------------------------
    # 開始時から継続する状態を使い、00:02に建玉やグリッド中心を作り直さない。
    old_candle = dict(turning_signals.CANDLE_OVERRIDES)
    old_feature = dict(turning_signals.FEATURE_OVERRIDES)
    try:
        turning_signals.CANDLE_OVERRIDES[session] = LIVE
        turning_signals.FEATURE_OVERRIDES[session] = LIVE/'features'
        result = evaluate_inputs(frozen, record, turning_signals.load_inputs([session]))
    finally:
        turning_signals.CANDLE_OVERRIDES.clear()
        turning_signals.CANDLE_OVERRIDES.update(old_candle)
        turning_signals.FEATURE_OVERRIDES.clear()
        turning_signals.FEATURE_OVERRIDES.update(old_feature)
    audit = dict(評価時刻=now_jst().isoformat(), 保存のみ再計算=True, 評価時ネットワーク要求数=0,
                 スナップショット上限=record['cutoff'], 評価開始時刻=frozen['known_cutoff'],
                 板抽出=feature_audits, 全区間状態継続=True, 途中時刻での強制返済=False,
                 取得後再選択=False, 説明=frozen['説明'], **result)
    execution.save(OUT/'現在照合_監査.json', audit)
    print(f'固定{len(frozen["selected_ids"])}条件の全建玉増分を、保存データだけで照合しました', flush=True)
    return audit


def main() -> None:
    """機能: 通信なし凍結・一回取得・保存のみ評価を明示的に分ける。

    引数: CLIの--prepare/--fetch/--evaluate。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description='固定条件での一回現在セッション照合')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--fetch', action='store_true')
    group.add_argument('--evaluate', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.fetch:
        fetch()
    else:
        evaluate()


if __name__ == '__main__':
    main()
