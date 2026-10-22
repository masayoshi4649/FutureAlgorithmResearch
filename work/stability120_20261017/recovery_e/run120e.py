"""小試行と合計停止の十八条件を、基準が保存した価格八十入力で一回だけ測る。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import catalog120e as catalog120
import engine120e as engine120
import runtime120e as runtime120b


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(path: Path) -> dict:
    """
    機能: 小さい固定計画を読む。
    引数: path(Path)はUTF-8 JSON。
    返り値: dict。原市場・過去結果を再解析しない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 固定源の指紋だけを照合する。
    引数: path(Path)は実在するファイル。
    返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clean(value):
    """
    機能: 配列と非有限値を保存可能な小会計へ変換する。
    引数: value(任意型)はNumPy値等。
    返り値: JSON互換値。未測定はNoneとし、0へ変えない。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: dict) -> None:
    """
    機能: 新規の計画・会計を上書きせず保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。
    """
    assert not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main() -> None:
    """
    機能: 事前照合・正式登録・人工監査に拘束した源で全注文を測定する。
    引数: なし。
    返り値: None。結果を見て条件を再選択せず、全1440口座行を残す。
    """
    fixed = read(HERE / '固定計画.json')
    proposal = read(HERE / '試行計画.json')
    registered = read(HERE / '正式登録の全出力.json')
    checked = read(HERE / '事前照合の全出力.json')
    assert registered['終了コード'] == checked['終了コード'] == 0
    actual = json.loads(registered['stdout'])
    assert json.loads(checked['stdout'])['提案完全'] is True
    assert actual['id'] == proposal['id'] and actual['spec'] == proposal['spec']
    assert actual['spec']['implementation'] == fixed['sources']
    assert actual['spec']['data']['input_manifests'] == [fixed['input_manifest']]
    assert fixed['artificial_audit']['passed'] is True
    for path, sha in fixed['sources'].items():
        assert digest(ROOT / path) == sha, path
    assert digest(HERE / '入力目録.json') == fixed['input_manifest']['sha256']
    meta = read(HERE / '入力目録.json')
    specs = catalog120.specifications()
    assert specs == fixed['specs']
    reference = fixed['artificial_audit']
    assert digest(ROOT/reference['path']) == reference['sha256']
    save(HERE/'実行時の通常高速全配列同値.json',runtime120b.verify())
    out = HERE / 'measurement'
    assert not out.exists(), '同一金融の再実行を止めます'
    out.mkdir()
    all_rows, references = [], []
    clock = time.monotonic()
    for number, item in enumerate(meta['inputs']):
        payload = (ROOT / item['path']).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == item['sha256']
        with np.load(BytesIO(payload), allow_pickle=False) as source:
            quotes = {key: source['quotes__' + key].copy() for key in ('row', 'time', 'last', 'bid', 'ask')}
        del payload
        assert len(quotes['row']) > 1 and np.all(np.diff(quotes['row']) > 0)
        symbol, session = item['symbol'], item['session']
        setting = catalog120.settings(symbol, session)
        orders, lots, curves, scene_rows = [], [], [], []
        for index, spec in enumerate(specs):
            values = engine120.replay(quotes['row'], quotes['time'], quotes['last'], quotes['bid'], quotes['ask'],
                **setting, fraction=spec['fraction'],
                mode=spec['mode'], trail=spec['trail'])
            o, lot, curve, numeric = values
            summary = dict(zip(engine120.SUMMARY_COLUMNS, numeric.tolist()))
            coherent = (summary['max_long'] <= setting['cap'] and summary['max_short'] <= setting['cap']
                and summary['entries'] == summary['closed_lots'] + summary['unclosed']
                and np.isclose(summary['profit']-summary['loss'],np.sum(lot[:,13])))
            if summary['unclosed'] == 0:
                coherent = coherent and np.isclose(summary['net'],summary['profit']-summary['loss'])
            if not coherent:
                save(out/'会計不一致.json',dict(symbol=symbol,session=session,method=spec['id'],summary=summary))
                np.savez_compressed(out/'会計不一致.npz',orders=o,lots=lot,curves=curve)
                raise AssertionError('全玉会計不一致を保存して停止しました')
            assert summary['max_long'] <= setting['cap'] and summary['max_short'] <= setting['cap']
            assert summary['closed_lots'] == len(lot)
            assert np.isclose(summary['profit'] - summary['loss'], np.sum(lot[:, 13]))
            if summary['unclosed'] == 0:
                assert np.isclose(summary['cash'], summary['net'])
                assert np.isclose(summary['net'], summary['profit'] - summary['loss'])
            terminal = lot[:, 14] == 9 if len(lot) else np.zeros(0, dtype=bool)
            row = dict(symbol=symbol, session=session, method=spec['id'], **summary,
                realized_net=summary['profit'] - summary['loss'],
                forced_loss=float(np.sum(np.maximum(-lot[terminal, 13], 0.))),
                forced_profit=float(np.sum(np.maximum(lot[terminal, 13], 0.))),
                trail_net=float(np.sum(lot[(lot[:, 14] == 1) | (lot[:, 14] == 10), 13])) if len(lot) else 0.,
                long_net=float(np.sum(lot[lot[:, 1] == 1, 13])) if len(lot) else 0.,
                short_net=float(np.sum(lot[lot[:, 1] == -1, 13])) if len(lot) else 0.)
            all_rows.append(row)
            scene_rows.append(row)
            for array, sink in ((o, orders), (lot, lots), (curve, curves)):
                if len(array):
                    sink.append(np.column_stack((np.full(len(array), index), array)))
        path = out / symbol / (session + '.npz')
        path.parent.mkdir(parents=True, exist_ok=True)
        memory = BytesIO()
        np.savez_compressed(memory, orders=np.concatenate(orders) if orders else np.empty((0,19)),
            lots=np.concatenate(lots) if lots else np.empty((0,20)),
            curves=np.concatenate(curves) if curves else np.empty((0,9)),
            **{'quotes__'+key:value for key,value in quotes.items()})
        payload = memory.getvalue()
        path.write_bytes(payload)
        references.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(payload).hexdigest(),
            symbol=symbol, session=session, input_path=item['path'], input_sha256=item['sha256']))
        save(out / symbol / (session + '.json'), dict(runs=scene_rows))
        with (out / '保存入力読取.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(input=item['path'], sha256=item['sha256'],
                numerical_read=1, new_financial_accounts=18, original_market_reads=0), ensure_ascii=False) + '\n')
        print(f'{number + 1}/80 {session} {symbol} / {time.monotonic()-clock:.1f}秒', flush=True)
    for path, sha in fixed['sources'].items():
        assert digest(ROOT / path) == sha
    save(out / 'カバーを維持する組全体追尾と全四十場.json', dict(
        sessions=meta['sessions'], specs=specs, runs=all_rows, cache=references,
        source_SHA256=fixed['sources'], order_columns=engine120.ORDER_COLUMNS,
        lot_columns=engine120.LOT_COLUMNS, curve_columns=engine120.CURVE_COLUMNS,
        original_market_reads=0, reused_input_reads=80, financial_accounts=len(all_rows), API=0, 実注文=0,
        留保='同じ既知40場の開発。ラージBBO代理・価格時計と原行順。実小型板や真の受信順を証明しない。'))
    print('追加十八条件・両商品・全四十場の全玉会計を保存しました。', flush=True)


if __name__ == '__main__':
    main()
