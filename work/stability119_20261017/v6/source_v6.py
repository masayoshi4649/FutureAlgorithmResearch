"""旧数値源の所有コピーと、登録前に許された指紋だけを準備する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MIRROR = HERE / 'legacy_root'
SESSIONS = ('2026-10-13_Night', '2026-10-14_Day', '2026-10-14_Night',
            '2026-10-15_Day', '2026-10-15_Night', '2026-10-16_Day', '2026-10-16_Night')
SYMBOLS = ('TOPIX', 'NK225')
ENGINE_NAMES = ('common.py', 'catalog.py', 'interface.py', 'entry_policy.py', 'base_policy.py',
                'sizing_engine.py', 'order_kernel.py', 'context.py', 'reuse.py', 'daily.py',
                'exit_policy.py', 'exit_core.py')
SMALL_FIXED = ('work/wave_v38/探索条件の固定.json', 'work/wave_v44/探索条件の固定.json',
               'work/wave_v27/hierarchy_design_fixed.json')


def digest(path: Path) -> str:
    """
    機能: source又は事前に許された小資料の指紋を取得する。
    引数: path(Path)は対象位置。
    返り値: strはSHA256。市場本文の解釈には使用しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 明示した小目録だけを読む。
    引数: path(Path)はJSON小資料。
    返り値: dictは内容。NPZ、pickle及び金融結果は読まない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path: Path, value: dict) -> None:
    """
    機能: 所有領域へ新規の有限JSONを保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。既成果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def copy_source(relative: str) -> Path:
    """
    機能: sourceだけを元と同bytesで所有mirrorへ複写する。
    引数: relative(str)はrepo相対Python又は許可済み小固定JSON。
    返り値: Pathは新所有位置。金融又は市場cacheは複写しない。
    """
    origin = ROOT / relative
    assert origin.resolve().is_relative_to(ROOT / 'work')
    assert origin.suffix == '.py' or relative in SMALL_FIXED, relative
    target = MIRROR / relative
    payload = origin.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == payload, relative
    else:
        target.write_bytes(payload)
    return target


def fingerprints() -> None:
    """
    機能: statだけの計画を先に保存し、許可済28CSVだけhash-onlyで指紋化する。
    引数: なし。
    返り値: None。book14は既目録SHAを引用し、本文解釈及び金融は0。
    """
    existing = ROOT / 'work/stability119_20261017/入力と時系列分割.json'
    old = read(existing)
    source = {(v['session'], v['symbol']): v for v in old['inputs']}
    plan_path = HERE / '原本のstat指紋計画.json'
    if not plan_path.exists():
        items = []
        for scene in SESSIONS:
            for symbol in SYMBOLS:
                for folder, suffix in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv')):
                    path = ROOT / folder / symbol / (scene + suffix)
                    st = path.stat()
                    item = dict(session=scene, symbol=symbol, kind=folder,
                                path=path.relative_to(ROOT).as_posix(), bytes=st.st_size, mtime_ns=st.st_mtime_ns)
                    if folder == 'book':
                        prior = source[scene, symbol]
                        assert prior['path'] == item['path'] and prior['bytes'] == item['bytes']
                        item['SHA256'] = prior.get('SHA256')
                    items.append(item)
        save(plan_path, dict(全合格=True, inputs=items, sessions=list(SESSIONS),
            既存目録=dict(path=existing.relative_to(ROOT).as_posix(), SHA256=digest(existing)),
            許可='根の段階制御により28CSVの指紋だけを読む。実数値抽出は正式登録後。',
            book本文読取=0, CSV本文解釈=0, CSV指紋読取予定=28, 新金融=0, API=0))
    planned = read(plan_path)
    assert len(planned['inputs']) == 42
    target = HERE / '原本の固定目録.json'
    assert not target.exists()
    items = []
    for item in planned['inputs']:
        item = dict(item)
        path = ROOT / item['path']
        before = path.stat()
        assert (before.st_size, before.st_mtime_ns) == (item['bytes'], item['mtime_ns'])
        if item['kind'] != 'book':
            hasher = hashlib.sha256()
            with path.open('rb') as stream:
                while block := stream.read(8388608):
                    hasher.update(block)
            item['SHA256'] = hasher.hexdigest()
        after = path.stat()
        assert (after.st_size, after.st_mtime_ns) == (item['bytes'], item['mtime_ns'])
        items.append(item)
    save(target, dict(全合格=True, sessions=list(SESSIONS), inputs=items,
        指紋前計画=dict(path=plan_path.relative_to(ROOT).as_posix(), SHA256=digest(plan_path)),
        book指紋引用数=sum(v['SHA256'] is not None for v in items if v['kind']=='book'),
        book指紋未確定数=sum(v['SHA256'] is None for v in items if v['kind']=='book'),
        book本文読取=0, CSV指紋だけの読取数=28,
        CSV本文解釈=0, 数値抽出=0, 新金融=0, API=0))
    print('原本42目録固定、CSV28はhash-only、book本文/数値抽出/金融0。', flush=True)


def clone() -> None:
    """
    機能: 旧85源と追加の動的抽出源、00106実行源を新所有域へ接続する。
    引数: なし。
    返り値: None。commonのrepo位置だけ変更し、数値式は変更しない。
    """
    fixed = read(ROOT / 'work/wave_v106/e01_reference/金額統一再開事前固定.json')
    for relative, expected in fixed['実装SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
        copy_source(relative)
    extras = ('work/e01_adaptive_price_20261014/engine/artificial.py',
              'work/wave_v16/reference.py', 'work/wave_v8/raw_features.py',
              'work/wave_v23/depth_features.py', 'work/wave_v103/input/core.py',
              'work/wave_v103/input_v2/correction.py', 'work/wave_v106/trade_gate/votes.py')
    for relative in (*extras, *SMALL_FIXED):
        copy_source(relative)
    original = ROOT / 'work/e01_adaptive_price_20261014/engine'
    for name in ENGINE_NAMES:
        payload = (original / name).read_bytes()
        if name == 'common.py':
            assert payload.count(b'ROOT=HERE.parents[2]') == 1
            payload = payload.replace(b'ROOT=HERE.parents[2]', b'ROOT=HERE.parents[3]')
        target = HERE / 'engine' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == payload, name
        else:
            target.write_bytes(payload)
    print('旧数値源同bytesコピーとcommon位置差だけの12源を準備。市場/金融0。', flush=True)


if __name__ == '__main__':
    import sys
    {'fingerprints': fingerprints, 'clone': clone}[sys.argv[1]]()
