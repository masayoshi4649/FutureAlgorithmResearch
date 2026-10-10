"""直近の固定２条件を変更せず、現在六応答の一回取得と入力準備を接続する。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numba


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
OLD = ROOT / 'work/wave_v14'
LIVE = OUT / 'live'
FROZEN = OUT / '現在照合_凍結記録.json'
JST = ZoneInfo('Asia/Tokyo')
SYMBOLS = ['NK225', 'TOPIX']
EXPECTED = {'NK225': 'N03_R-1_L3_U1', 'TOPIX': 'N15_R-1_A4_U0'}
SESSION = '2026-09-24_Night'
KNOWN_CUTOFF = '2026-09-25T00:53:00+09:00'
LOCAL_FILES = ['current_check.py', 'run.py', '検証計画.md']
DEPENDENCIES = [
    'work/wave_v14/current_check.py', 'work/wave_v14/reference.py',
    'work/wave_v14/details.py', 'work/wave_v14/risk_guard.py',
    'work/wave_v14/metrics.py', 'work/wave_v14/grid_engine.py',
    'work/wave_v14/pair_engine.py', 'work/wave_v14/全条件一覧.json',
    'work/wave_v14/live/取得記録.json', 'work/wave_v14/現在入力.pkl',
    'work/wave_v13/current_check.py', 'work/wave_v13/research.py',
    'work/wave_v13/catalog.py', 'work/wave_v13/data.py',
    'work/wave_v13/exact_engine.py', 'work/wave_v13/new_signals.py',
    'work/wave_v11/signals.py', 'work/wave_v10/signals.py',
    'work/wave_v9/turning_signals.py', 'work/wave_v9/execution.py',
    'work/wave_v8/raw_features.py', 'work/wave_v7/fetch_once.py']

# 固有モジュール名の機械語キャッシュを旧作業と共有しない。
numba.config.CACHE_DIR = str(OUT / 'numba_cache')


@contextmanager
def module_aliases(mapping: dict):
    """機能: 読込み中だけ依存名を差し替え、他作業の同名モジュールを復元する。

    引数: mapping (dict[str, module])。返り値: コンテキスト管理器。
    """
    missing = object()
    prior = {name: sys.modules.get(name, missing) for name in mapping}
    sys.modules.update(mapping)
    try:
        yield
    finally:
        for name, value in prior.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def source_module(path: Path, name: str):
    """機能: 原本コードを編集せず固有のモジュール名で読み込む。

    引数: path (Path)、name (str)。返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime() -> tuple:
    """機能: 凍結済み旧再生器と取得器を独立した今回用の依存へ結び付ける。

    引数: なし。返り値: 参照名前空間と旧現在取得モジュール (tuple)。通信しない。
    """
    origin = ROOT / 'work/wave_v13'
    data = source_module(origin / 'data.py', 'v15_saved_data')
    engine = source_module(origin / 'exact_engine.py', 'v15_exact_engine')
    signals = source_module(origin / 'new_signals.py', 'v15_saved_new_signals')
    aliases = dict(data=data, exact_engine=engine, new_signals=signals)
    with module_aliases(aliases):
        catalog = source_module(origin / 'catalog.py', 'v15_saved_catalog')
        with module_aliases(dict(catalog=catalog)):
            previous = source_module(origin / 'research.py', 'v15_saved_research')
    previous.OUT = OUT
    reference = SimpleNamespace(ROOT=ROOT, OUT=OUT, OLD=origin, previous=previous,
        engine=engine, SYMBOLS=SYMBOLS, save=previous.save)
    with module_aliases(dict(aliases, catalog=catalog, research=previous, reference=reference)):
        audited = source_module(OLD / 'current_check.py', 'v15_audited_current_wrapper')
    return reference, audited


reference, AUDITED = load_runtime()
LEGACY = AUDITED.LEGACY
sha256 = AUDITED.sha256
_V14_MODULES = {}


def import_v14(name: str):
    """機能: 旧明細・会計関数を独立名で読み、同じ今回用の参照へ接続する。

    引数: name (str): details/metrics/risk_guard/grid_engine/pair_engine。
    返り値: module。旧ファイルを編集せず、保存先は今回の作業へ向ける。
    """
    if name not in {'details', 'metrics', 'risk_guard', 'grid_engine', 'pair_engine'}:
        raise ValueError('許可した旧評価補助モジュールではありません')
    if name in _V14_MODULES:
        return _V14_MODULES[name]
    aliases = dict(reference=reference)
    if name == 'details':
        aliases.update({key: import_v14(key) for key in ['metrics', 'risk_guard', 'grid_engine', 'pair_engine']})
    with module_aliases(aliases):
        module = source_module(OLD / f'{name}.py', f'v15_saved_{name}')
    if hasattr(module, 'OUT'):
        module.OUT = OUT
    if hasattr(module, 'WORK'):
        module.WORK = OUT
    _V14_MODULES[name] = module
    return module


def now_jst() -> datetime:
    """機能: 日本時間の現在時刻を返す。

    引数: なし。返り値: タイムゾーン付き時刻 (datetime)。
    """
    return datetime.now(JST)


def tracked_files() -> list[Path]:
    """機能: 今回の実行コードと元の固定依存を列挙する。

    引数: なし。返り値: 凍結対象 (list[Path])。
    """
    return [OUT / name for name in LOCAL_FILES] + [ROOT / name for name in DEPENDENCIES]


def selected_configs() -> list[dict]:
    """機能: 指定２条件を前回全条件から値を変えず抜き出す。

    引数: なし。返り値: ID順の２条件 (list[dict])。成績は読まない。
    """
    configs = json.loads((OLD / '全条件一覧.json').read_text(encoding='utf-8'))
    mapping = {config['id']: config for config in configs}
    if len(mapping) != len(configs) or not set(EXPECTED.values()) <= set(mapping):
        raise ValueError('指定条件の一意な定義が前回一覧にありません')
    selected = [mapping[identifier] for identifier in sorted(EXPECTED.values())]
    if any(config.get('engine') != 'single' for config in selected):
        raise ValueError('指定条件は単独銘柄の旧条件である必要があります')
    return selected


def configure() -> None:
    """機能: 監査済み関数を新保存先と今回の凍結照合へ接続する。

    引数: なし。返り値: なし (None)。通信しない。
    """
    reference.ROOT, reference.OUT = ROOT, OUT
    reference.previous.OUT = OUT
    AUDITED.ROOT, AUDITED.OUT, AUDITED.OLD = ROOT, OUT, OLD
    AUDITED.LIVE, AUDITED.FROZEN = LIVE, FROZEN
    AUDITED.reference = reference
    AUDITED.now_jst, AUDITED.freeze_check = now_jst, freeze_check
    AUDITED.configure_legacy()


def freeze() -> dict:
    """機能: ２条件・実装・前回00:53境界・旧原本を一回だけ固定する。

    引数: なし。返り値: 凍結記録 (dict)。現在APIを呼ばない。
    """
    if FROZEN.exists() or (LIVE / '一回取得開始.json').exists():
        raise FileExistsError('既に凍結または取得を開始したため上書きしません')
    stamp = now_jst()
    session, start, end = LEGACY.current_session(stamp)
    old = json.loads((OLD / 'live/取得記録.json').read_text(encoding='utf-8'))
    if session != SESSION or old['session'] != SESSION or old['cutoff'] != KNOWN_CUTOFF:
        raise ValueError('今回の同一ナイトと前回00:53境界が一致しません')
    if old.get('status') != '取得と検査完了':
        raise ValueError('前回の取得が成功状態ではありません')
    books = {}
    for symbol in SYMBOLS:
        path = OLD / 'live/book' / symbol / f'{session}.jsonl'
        books[symbol] = dict(path=path.relative_to(ROOT).as_posix(), sha256=sha256(path), bytes=path.stat().st_size)
    configs = selected_configs()
    record = dict(fixed_at=stamp.isoformat(), session=session, starts_at=start.isoformat(), ends_at=end.isoformat(),
        known_cutoff=old['cutoff'], known_session=True, known_books=books,
        selected_ids=[config['id'] for config in configs], selected_configs=configs,
        selected_by_symbol=dict(EXPECTED),
        files_sha256={path.relative_to(ROOT).as_posix(): sha256(path) for path in tracked_files()},
        要求数=6, 各要求回数=1, 再試行=False, リダイレクト=False, 取得後再選択=False,
        手数料=0, 気配差控除=0, 実時間前向き運用=False,
        主評価='前回00:53直前の全玉評価から今回共通締切直前までの資産変化。全セッション参考を別表示。',
        説明='指定２条件を変更せず、全セッションから状態を再生。新しい手法探索・選択は行わない。')
    with FROZEN.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(f'通信なしで２条件・{len(record["files_sha256"])}ファイルを凍結。既知境界{old["cutoff"]}', flush=True)
    return record


def freeze_check() -> dict:
    """機能: 固定した２条件・実装・前回原本の不変性を確認する。

    引数: なし。返り値: 確認済み凍結記録 (dict)。通信しない。
    """
    record = json.loads(FROZEN.read_text(encoding='utf-8'))
    fixed_at = datetime.fromisoformat(record['fixed_at'])
    if fixed_at.tzinfo is None or fixed_at > now_jst():
        raise ValueError('凍結時刻が不正です')
    expected_files = {path.relative_to(ROOT).as_posix() for path in tracked_files()}
    if set(record['files_sha256']) != expected_files:
        raise RuntimeError('凍結対象一覧が変わっています')
    for relative, digest in record['files_sha256'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha256(path) != digest:
            raise RuntimeError(f'凍結後の変更があります: {relative}')
    configs = selected_configs()
    if record['selected_configs'] != configs or record['selected_ids'] != [c['id'] for c in configs] or record['selected_by_symbol'] != EXPECTED:
        raise RuntimeError('指定した２条件から変更されています')
    old = json.loads((OLD / 'live/取得記録.json').read_text(encoding='utf-8'))
    if record['session'] != SESSION or old['session'] != SESSION or old['cutoff'] != KNOWN_CUTOFF or record['known_cutoff'] != KNOWN_CUTOFF or record['known_session'] is not True:
        raise RuntimeError('固定したセッション・前回境界が変わっています')
    if set(record['known_books']) != set(SYMBOLS):
        raise RuntimeError('２銘柄の既知原本が必要です')
    for symbol, book in record['known_books'].items():
        path = OLD / 'live/book' / symbol / f'{SESSION}.jsonl'
        if book['path'] != path.relative_to(ROOT).as_posix() or path.stat().st_size != book['bytes'] or sha256(path) != book['sha256']:
            raise RuntimeError('既知原本が凍結後に変わっています')
    return record


# ----------------------------------------
# 六要求と原本からの準備は旧監査済み実装をそのまま再使用する。
def fetch() -> dict:
    """機能: 凍結照合後に六URLを各一回だけ保存する。

    引数: なし。返り値: 取得記録 (dict)。失敗時も再試行しない。
    """
    configure()
    return AUDITED.fetch()


def receipt_check(frozen: dict) -> dict:
    """機能: 保存応答のハッシュ・取得所属・六要求一回を確認する。

    引数: frozen (dict)。返り値: 確認済み取得記録 (dict)。通信しない。
    """
    configure()
    return AUDITED.receipt_check(frozen)


def known_prefix_check(frozen: dict) -> list[dict]:
    """機能: 今回原本の先頭が前回00:53未満の原本と完全一致するか確認する。

    引数: frozen (dict)。返り値: 先頭一致監査 (list[dict])。
    """
    configure()
    return AUDITED.known_prefix_check(frozen)


def prepare() -> dict:
    """機能: 保存原本からCurrentPrice対応の再生入力だけを作る。

    引数: なし。返り値: 入力準備記録 (dict)。通信も手法選択も行わない。
    """
    configure()
    if (OUT / '現在入力.pkl').exists() or (OUT / '現在照合_入力準備記録.json').exists():
        raise FileExistsError('今回の現在入力は既に準備済みのため上書きしません')
    record = AUDITED.prepare()
    record['説明'] = '全セッション状態を再生する入力。固定済みrun.pyが00:53前後と現在建玉を評価する。'
    reference.save(OUT / '現在照合_入力準備記録.json', record)
    return record


def main() -> None:
    """機能: 明示された凍結・一回取得・保存入力準備だけを実行する。

    引数: コマンドライン。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description='直近２候補の条件固定と現在一回取得')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze', action='store_true')
    group.add_argument('--fetch', action='store_true')
    group.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.fetch:
        fetch()
    else:
        prepare()


if __name__ == '__main__':
    main()
