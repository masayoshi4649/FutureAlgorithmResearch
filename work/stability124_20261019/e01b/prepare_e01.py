"""00119hの少額E01数値源を、新一場用の所有領域へ同一コピーする。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT/'work/stability119_20261017/v6_resume'
FIXED = ('work/wave_v38/探索条件の固定.json', 'work/wave_v44/探索条件の固定.json',
         'work/wave_v27/hierarchy_design_fixed.json')


def write_same(path: Path, data: bytes) -> None:
    """
    機能: 新所有域へ保存し、既にある場合は同bytesだけを受理する。
    引数: path(Path)は所有先、data(bytes)は内容。
    返り値: None。旧源や市場データを変更しない。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data, str(path)
    else:
        path.write_bytes(data)


def main() -> None:
    """
    機能: 同bytesの旧102数値源・経済12源と、小設定3本を準備する。
    引数: なし。
    返り値: None。原市場・保存価格配列・金融・登録を一切使用しない。
    """
    records = []
    for source in sorted((OLD/'legacy_root/work').rglob('*.py')):
        relative = source.relative_to(OLD/'legacy_root')
        data = source.read_bytes()
        assert data == (ROOT/relative).read_bytes(), str(relative)
        target = HERE/'legacy_root'/relative
        write_same(target, data)
        records.append(dict(source=source.relative_to(ROOT).as_posix(),
            target=target.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(data).hexdigest(),
            difference='同bytes'))
    for relative in FIXED:
        source = OLD/'legacy_root'/relative
        data = source.read_bytes()
        assert data == (ROOT/relative).read_bytes()
        target = HERE/'legacy_root'/relative
        write_same(target, data)
        records.append(dict(source=source.relative_to(ROOT).as_posix(), target=target.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(data).hexdigest(), difference='同bytes・許可済小設定'))
    for source in sorted((OLD/'engine').glob('*.py')):
        target = HERE/'engine'/source.name
        data = source.read_bytes()
        write_same(target, data)
        records.append(dict(source=source.relative_to(ROOT).as_posix(), target=target.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(data).hexdigest(), difference='同bytes・経済部品'))

    # ----------------------------------------
    # 旧adapterの数値式を変更せず、未加工bookの所有参照先だけを今回inputsへ移す。
    for name in ('adapter_v6.py', 'legacy_runtime.py', 'clock_adapter.py'):
        source = OLD/name
        data = source.read_bytes()
        changed = data
        if name == 'adapter_v6.py':
            old = b"ORIGINAL_STAGE = HERE.parent / 'v6/legacy_root'"
            new = b"ORIGINAL_STAGE = HERE.parent / 'inputs'"
            assert data.count(old) == 1
            changed = data.replace(old, new)
        target = HERE/name
        write_same(target, changed)
        records.append(dict(source=source.relative_to(ROOT).as_posix(), target=target.relative_to(ROOT).as_posix(),
            source_sha256=hashlib.sha256(data).hexdigest(), sha256=hashlib.sha256(changed).hexdigest(),
            difference='ORIGINAL_STAGE所有位置のみ' if name=='adapter_v6.py' else '同bytes'))
    target = HERE/'数値源の同bytesと所有参照先だけの差分.json'
    value = dict(passed=True, records=records, numerical_changes=0,
        original_market_reads=0, array_reads=0, financial_accounts=0, API=0, real_orders=0)
    write_same(target, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf8'))
    print(json.dumps(dict(passed=True, records=len(records), path=target.relative_to(ROOT).as_posix(),
        sha256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
