"""指定33場二商品の先頭一JSON行だけから、キー型と時計候補を射影する。"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
META = ROOT/'work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json'
PLAN = HERE/'先頭時計schemaの目的別読取固定.json'
RESULT = HERE/'三十三場六十六先頭のキーと時計候補.json'
MAX_LINE = 8192
SYMBOLS = ('TOPIX', 'NK225')


def digest_bytes(value: bytes) -> str:
    """
    機能: 同じ読取bytesのSHA256を求める。
    引数: value(bytes)は小source・metadata又は先頭一行。
    返り値: strは指紋。原book全文のhashは計算しない。
    """
    return hashlib.sha256(value).hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 所有域に未存在の計画・時計射影・終端を保存する。
    引数: path(Path)、value(dict)は保存位置と価格数量を含まない資料。
    返り値: None。共有資料・元book・完成資料を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def project(value: object, prefix: str = '') -> tuple[list, list]:
    """
    機能: JSONの全キー名・型と、時計又はseq候補の値だけを取り出す。
    引数: value(object)は先頭JSON、prefix(str)は入れ子のキー経路。
    返り値: tuple[list,list]はキー型一覧と時計seq候補。価格・数量の値を含めない。
    """
    keys, candidates = [], []
    if isinstance(value, dict):
        for name, content in value.items():
            path = name if not prefix else prefix+'.'+name
            kind = 'null' if content is None else type(content).__name__
            keys.append(dict(path=path, type=kind))
            lower = re.sub(r'[^a-z0-9]', '', name.lower())
            clock = any(token in lower for token in ('time', 'clock', 'received', 'collected', 'captured', 'asof'))
            sequence = lower in ('seq', 'sequencenumber', 'commonseq', 'globalseq', 'sourceseq') or 'sequence' in lower
            if clock or sequence:
                assert not any(token in lower for token in ('price', 'qty', 'quantity', 'volume', 'value')) or clock
                if isinstance(content, (str, int, float, bool)) or content is None:
                    assert not isinstance(content, str) or len(content) <= 160
                    candidates.append(dict(path=path, type=kind, value=content, clock_candidate=clock, sequence_candidate=sequence))
            if isinstance(content, dict):
                child_keys, child_candidates = project(content, path)
                keys.extend(child_keys); candidates.extend(child_candidates)
            elif isinstance(content, list):
                for index, child in enumerate(content):
                    if isinstance(child, (dict, list)):
                        child_keys, child_candidates = project(child, path+'['+str(index)+']')
                        keys.extend(child_keys); candidates.extend(child_candidates)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                a, b = project(child, prefix+'['+str(index)+']')
                keys.extend(a); candidates.extend(b)
    return keys, candidates


def prepare() -> None:
    """
    機能: 完成33場metadataの場名だけとsource署名を、原行読取前に固定する。
    引数: なし。120KBの既非金融metadataを場一覧の別目的で一読する。
    返り値: None。原book・NPZ・cache・金融・APIはまだ読まない。
    """
    assert META.stat().st_size <= 2_000_000
    raw = META.read_bytes(); meta = json.loads(raw.decode('utf-8'))
    sessions = meta['sessions']
    assert meta['全合格'] and len(sessions) == len(set(sessions)) == 33
    records = []
    for session in sessions:
        assert re.fullmatch(r'2026-\d{2}-\d{2}_(Day|Night)', session)
        for symbol in SYMBOLS:
            path = ROOT/'book'/symbol/(session+'.jsonl')
            assert path.resolve().is_relative_to((ROOT/'book'/symbol).resolve())
            stat = path.stat()
            records.append(dict(session=session, symbol=symbol, path=path.relative_to(ROOT).as_posix(), bytes=stat.st_size, mtime_ns=stat.st_mtime_ns))
    save(PLAN, dict(全合格=True, 目的='元JSONL先頭一有効JSON行のキー型と時計seq候補だけ。NPZ未保存と元データ不存在を区別する。',
        source_SHA256=digest_bytes(Path(__file__).read_bytes()), 場一覧metadata=dict(path=META.relative_to(ROOT).as_posix(), SHA256=digest_bytes(raw), 読取=1),
        sessions=sessions, targets=records, 予定ファイル数=66, 一ファイル最大byte=MAX_LINE,
        制約='最初の一行が空又は不正又は上限超過なら停止し、次行を探す自動再読はしない。元価格数量は値の保存/出力/統計0。',
        元book読取=0, NPZ=0, cache=0, 金融=0, API=0, 公開=0, 共通編集=0))
    print(json.dumps(dict(準備完了=True, plan_SHA256=digest_bytes(PLAN.read_bytes()), targets=66, 元book=0, NPZ=0, cache=0, 金融=0, API=0), ensure_ascii=False))


def run() -> None:
    """
    機能: root授権の先頭一行だけを読取り、キー型と時計seq候補を保存する。
    引数: なし。固定66pathを一ファイル一回開く。先頭bytesを生保存しない。
    返り値: None。この限られた先頭の有無を全原行の不存在へ一般化しない。
    """
    assert not RESULT.exists() and not (HERE/'先頭schemaFalse.json').exists()
    pb = PLAN.read_bytes(); plan = json.loads(pb.decode('utf-8'))
    assert plan['全合格'] and plan['source_SHA256'] == digest_bytes(Path(__file__).read_bytes())
    records = []; opens = 0; read_bytes = 0
    for item in plan['targets']:
        path = ROOT/item['path']
        assert path.resolve() == (ROOT/'book'/item['symbol']/(item['session']+'.jsonl')).resolve()
        stat = path.stat()
        assert stat.st_size == item['bytes'] and stat.st_mtime_ns == item['mtime_ns']
        with path.open('rb', buffering=0) as stream:
            line = stream.readline(MAX_LINE+1); opens += 1
            assert stream.tell() == len(line)
        read_bytes += len(line)
        assert line.strip() and len(line) <= MAX_LINE and line.endswith(b'\n'), item['path']
        original = json.loads(line.decode('utf-8-sig'))
        assert isinstance(original, dict), item['path']
        keys, clocks = project(original)
        after = path.stat(); assert (after.st_size, after.st_mtime_ns) == (stat.st_size, stat.st_mtime_ns)
        records.append(dict(session=item['session'], symbol=item['symbol'], path=item['path'],
            JSON原行番号=0, 頭部byte数=len(line), 頭部SHA256=digest_bytes(line), schema=keys, clock_sequence_candidates=clocks))
        del original, line
    assert opens == len(records) == 66
    clock_keys = Counter(c['path'] for record in records for c in record['clock_sequence_candidates'])
    save(RESULT, dict(全合格=True, 目的=plan['目的'], source_SHA256=plan['source_SHA256'], 計画SHA256=digest_bytes(pb),
        sessions=plan['sessions'], records=records, 時計候補キーの頭部出現数=dict(clock_keys),
        読取=dict(元bookファイルopen=opens, 原先頭JSON行=66, 原行bytes=read_bytes, 原全文hash=0, 原行生保存=0, 価格数量保存=0, 価格数量出力=0, 価格数量統計=0,
            NPZ=0, 大cache=0, 金融本文=0, 金融再生=0, API=0),
        限界='66ファイルの最初の一JSON行のみ。キーがない頭部から後の行にもないとは断定しない。別市場のファイル行番号は共通seqではない。候補時計を意味確認なしで真受信clockへ合成しない。'))
    print(json.dumps(dict(全合格=True, proof_SHA256=digest_bytes(RESULT.read_bytes()), 元bookopen=opens, 原先頭JSON行=66,
        原行bytes=read_bytes, 時計候補キー=dict(clock_keys), 価格数量保存=0, 価格数量出力=0, 価格数量統計=0, NPZ=0, cache=0, 金融=0, API=0), ensure_ascii=False))


def main() -> None:
    """
    機能: 先頭schemaの事前固定と、root許可済み一回読取を分けて開始する。
    引数: CLI --prepare-only/--root-head-reviewed(bool)は排他的モード。
    返り値: None。失敗を保存し自動再開始しない。
    """
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--prepare-only', action='store_true')
    choice.add_argument('--root-head-reviewed', action='store_true')
    args = parser.parse_args()
    if args.prepare_only:
        prepare(); return
    try:
        run()
    except Exception as error:
        save(HERE/'先頭schemaFalse.json', dict(全合格=False, 原因=type(error).__name__+': '+str(error), 金融=0, API=0, 自動再開始=False))
        raise


if __name__ == '__main__':
    main()
