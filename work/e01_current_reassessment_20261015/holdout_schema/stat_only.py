"""旧33場との差集合をファイル名とstatだけで保存する。新原本の本文を読まない。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KNOWN_PLAN = HERE.parent/'clock_schema/先頭時計schemaの目的別読取固定.json'
KNOWN_SHA = '6751b1c59efa5bf378471a2490293641fe97cb203b7093bd0ced99c6b6d5168a'
SYMBOLS = ('TOPIX', 'NK225')


def file_stat(path: Path) -> dict:
    """
    機能: 指定marketファイルの名前とstatだけを取得する。
    引数: path(Path)はbook又は足ファイル。本文open/hashは禁止。
    返り値: dictは存在・bytes・mtime_ns・更新UTC。不存在の値はNone。
    """
    assert any(path.resolve().is_relative_to((ROOT/folder).resolve()) for folder in ('book', 'candle_1min', 'candle_5min'))
    if not path.exists():
        return dict(path=path.relative_to(ROOT).as_posix(), exists=False, bytes=None, mtime_ns=None, modified_utc=None)
    stat = path.stat()
    return dict(path=path.relative_to(ROOT).as_posix(), exists=True, bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
        modified_utc=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat())


def main() -> None:
    """
    機能: 旧33場外の両商品対応と、生成用ソース指紋を本文未読で保存する。
    引数: なし。既知場の私有小計画一読とfile名列挙/stat、限定sourceだけ。
    返り値: None。未見候補であり、場の完結/足一致/収益性を証明しない。
    """
    kb = KNOWN_PLAN.read_bytes()
    assert hashlib.sha256(kb).hexdigest() == KNOWN_SHA
    plan = json.loads(kb.decode('utf-8')); known = set(plan['sessions']); assert len(known) == 33
    names = {symbol: {p.stem: p for p in (ROOT/'book'/symbol).glob('*.jsonl')} for symbol in SYMBOLS}
    extra = {symbol: set(paths)-known for symbol, paths in names.items()}
    assert extra['TOPIX'] == extra['NK225'] and len(extra['TOPIX']) == 2
    sessions = sorted(extra['TOPIX'])
    records = []
    for session in sessions:
        for symbol in SYMBOLS:
            fields = {folder: file_stat(ROOT/folder/symbol/(session+suffix))
                for folder, suffix in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv'))}
            assert fields['book']['exists']
            records.append(dict(session=session, symbol=symbol, files=fields, 本文未読=True))
    dependencies = [
        'work/wave_v104/holdout_input/core.py',
        'work/wave_v103/input/core.py',
        'work/wave_v103/input_v2/correction.py',
        'work/wave_v106/e01_reference/bridge.py',
        'work/wave_v106/e01_reference/prepare.py',
        'work/wave_v48/update_20261001/replay_added_session.py',
        'work/wave_v106/e01_trade_gate/prepare.py',
        'work/wave_v106/trade_gate/votes.py',
        'work/wave_v106/e01_trade_exit/features.py',
        'work/wave_v106/e01_trade_exit/prepare.py',
        'work/e01_fak_evidence_20261014/engine/price_votes.py'
    ]
    source = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in dependencies}
    value = dict(全合格=True, 目的='未読追加場の名前とstatを、旧33場外の新規holdout候補として固定する。',
        既知場小計画_SHA256=KNOWN_SHA, 旧場数=33, 新場名=sessions, 新場数=2, 新book数=4, records=records,
        source_SHA256=source, このsource_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        未確認=['新原本のschema/時計値/欠測', '当場の完結と収録の完全性', '原本と足の一致', '新旧限月識別', '他の担当/旧試行による既読有無', '当時信号/紙上feed/新現在票/実金融'],
        制約='stat-only。元ファイルの全文hash、先頭行、価格数量、実cache、金融本文へアクセスしない。',
        読取=dict(既知小計画一読=1, 新book本文=0, 新足本文=0, 新価格数量=0, 新NPZ=0, 大cache=0, 金融=0, API=0),
        公開=0, 共通知見編集=0)
    target = HERE/'旧三十三場外の追加二場の未読stat固定.json'
    assert not target.exists()
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 新場名=sessions, 新book数=4,
        proof_SHA256=hashlib.sha256(target.read_bytes()).hexdigest(), records=records, 本文=0, NPZ=0, cache=0, 金融=0, API=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
