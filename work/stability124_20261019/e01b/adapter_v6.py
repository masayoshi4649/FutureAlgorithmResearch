"""旧入力・旧紙上E01・旧00106実政策を、追加七場だけへ忠実に接続する。"""

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib
import json
import math
from pathlib import Path
import pickle
import sys

import numpy as np

import clock_adapter
import legacy_runtime
from source_v6 import HERE, ROOT, MIRROR, SESSIONS, SYMBOLS, ENGINE_NAMES, read, save, digest


ACTUAL = {'TOPIX': 'E01_ADAPT_G50_ADAPT75_P1', 'NK225': 'E01_ADAPT_G25_ADAPT100_P1'}
OLD_ACCOUNT = ROOT / 'work/stability119_20261017/design/revisit106/00106公開会計の同bytes参照.json'
METHOD = 'E01_006_FIXED'
ORIGINAL_STAGE = HERE.parent / 'inputs'


def primitive(value: object) -> object:
    """
    機能: NumPy型をJSON原始型へ変換し、非有限の診断値は未知で残す。
    引数: value(object)は会計・由来・診断。
    返り値: objectは有限JSON互換値。未保存の枚数等を零へ補完しない。
    """
    if isinstance(value, dict):
        return {str(k): primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [primitive(v) for v in value]
    if isinstance(value, np.ndarray):
        return primitive(value.tolist())
    if isinstance(value, np.generic):
        return primitive(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def bounds(scene: str) -> tuple[float, float]:
    """
    機能: 旧44列の出来高資格に使う観測窓をそのまま与える。
    引数: scene(str)は日付とDay/Night。
    返り値: tuple[float,float]は開始と終了epoch秒。金融のready.limitとは別。
    """
    day = datetime.fromisoformat(scene[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
    if scene.endswith('_Day'):
        return (day + timedelta(hours=8, minutes=45)).timestamp(), (day + timedelta(hours=15, minutes=40)).timestamp()
    assert scene.endswith('_Night')
    return (day + timedelta(hours=17)).timestamp(), (day + timedelta(days=1, hours=5, minutes=55)).timestamp()


def engine_modules() -> dict:
    """
    機能: 00106実経済の十二所有コピーだけを通常名で接続する。
    引数: なし。
    返り値: dictは実政策module。旧経済sourceや旧JITを直接importしない。
    """
    folder = HERE / 'engine'
    sys.path.insert(0, str(folder))
    result = {}
    for name in ENGINE_NAMES:
        stem = Path(name).stem
        if stem in sys.modules:
            assert Path(sys.modules[stem].__file__).resolve() == folder / name, ('module名衝突', stem)
        result[stem] = importlib.import_module(stem)
        assert Path(result[stem].__file__).resolve() == folder / name
    return result


def selected_configs(modules: dict) -> dict:
    """
    機能: 商品ごとの旧固定一設定だけを取り出す。
    引数: modules(dict)は所有00106数値module。
    返り値: dict[str,dict]はTOP G50/75/P1とNK G25/100/P1。成績選び直しなし。
    """
    all_configs = {v['id']: v for v in modules['catalog'].configs()}
    return {symbol: all_configs[case_id] for symbol, case_id in ACTUAL.items()}


def stage_raw(manifest: dict) -> list[dict]:
    """
    機能: 正式登録後に旧fの既stage42だけを使い、原seq保持の価格資格表示を作る。
    引数: manifest(dict)は原本の固定目録。
    返り値: list[dict]は所有copy読取履歴。元原本追加読取は0。
    """
    assert len(manifest['inputs']) == 42
    logs = []
    journal = HERE/'原本複写の逐次履歴.jsonl'
    assert not journal.exists()
    for item in manifest['inputs']:
        assert len(item['SHA256']) == 64
        origin = ROOT / item['staged_path']
        assert origin.resolve().is_relative_to(ORIGINAL_STAGE)
        target = MIRROR / item['path']
        assert target.resolve().is_relative_to(MIRROR) and not target.exists(), target
        before = origin.stat()
        assert before.st_size == item['bytes']
        target.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        with journal.open('a', encoding='utf-8') as history:
            history.write(json.dumps(dict(event='読取開始', path=item['path'], expected_SHA256=item['SHA256']),
                                     ensure_ascii=False, allow_nan=False)+'\n')
        qualification = None
        csv_clock = None
        if item['kind'] == 'book':
            start,end=bounds(item['session'])
            qualification=clock_adapter.write_view(origin,target,item['SHA256'],start,end)
            view_meta=HERE/'clock_masks'/item['symbol']/(item['session']+'.json')
            save(view_meta,dict(qualification,session=item['session'],symbol=item['symbol']))
            actual_sha=qualification['original_SHA256']
        else:
            with origin.open('rb') as source, target.open('xb') as destination:
                while block := source.read(8388608):
                    hasher.update(block)
                    destination.write(block)
            actual_sha=hasher.hexdigest()
            start,end=bounds(item['session'])
            csv_clock=clock_adapter.validate_csv(target,start,end)
        after = origin.stat()
        assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
        assert actual_sha == item['SHA256'], item['path']
        logs.append(dict(item, owned_path=target.relative_to(ROOT).as_posix(), original_reads=0,
                         staged_copy_reads=1,clock_qualification=qualification,csv_clock_guard=csv_clock,
                         用途='旧fの既stageを再利用。原clock/seqを保存し、不適格価格行だけconsumer時計をNone表示。CSVは同bytes。'))
        with journal.open('a', encoding='utf-8') as history:
            history.write(json.dumps(dict(event='同一性確認済', **logs[-1]),ensure_ascii=False,allow_nan=False)+'\n')
    return logs


def quote_mapping(ready: dict, tape: dict) -> dict:
    """
    機能: 旧正常seqと同じ原行・時計・現在値のBBOだけを対応させる。
    引数: ready/tape(dict)は旧抽出入力と正常気配系列。
    返り値: dictは00106と同じ正常quote資格。近傍や未来行へ置換しない。
    """
    indexes = np.searchsorted(tape['seq'], ready['seq'])
    assert np.all(indexes < len(tape['seq']))
    for field, name in (('seq', 'seq'), ('time_s', 'time_s'), ('last', 'last')):
        np.testing.assert_array_equal(ready[field], tape[name][indexes])
    bid, ask = tape['bid'][indexes], tape['ask'][indexes]
    valid = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    if 'quote_valid' in tape:
        valid &= tape['quote_valid'][indexes]
    return dict(bid=bid, ask=ask, quote_valid=valid, seq=ready['seq'].copy(), time_s=ready['time_s'].copy())


def make_account(rt: dict, scene: str, symbol: str, ready: dict, quotes: dict, feature: dict) -> tuple[dict, dict]:
    """
    機能: E01_G_Uの全紙上feedと当時W60票を追加一口座へ接続する。
    引数: rt(dict)、scene/symbol(str)、ready/quotes/feature(dict)は元数値部品と今回素材。
    返り値: tuple[dict,dict]は00106入力口座と由来診断。旧33を運転しない。
    """
    virtual, _ = rt['old'].play(dict(id='E01_G_U', mask=1, time_mode='U', changes={}), ready, feature, True)
    feed = rt['order_feed'](virtual)
    quiet = rt['old'].time_filter.features(ready, 'U')
    record = dict(time_s=ready['time_s'], price=ready['last'], seq=ready['seq'],
                  limit=float(ready['limit']), tick=float(ready['tick']))
    normal = dict(record, bid=quotes['bid'], ask=quotes['ask'])
    start, end = bounds(scene)
    raw, diagnosis = rt['raw_core'].extract_jsonl(ORIGINAL_STAGE / 'book' / symbol / (scene + '.jsonl'), start, end, normal)
    raw, correction = rt['correct_arrays'](raw)
    mapping = raw['execution_to_raw_index']
    qualification=read(HERE/'clock_masks'/symbol/(scene+'.json'))
    assert qualification['rows']==len(raw['raw_seq'])
    runs=np.asarray(qualification['reason_runs'],dtype=np.int64)
    index=np.searchsorted(runs[:,0],mapping,side='right')-1
    assert np.all(index>=0) and np.all(runs[index,1]==0), '旧normal行が不適格原seqを使用'
    np.testing.assert_array_equal(raw['raw_seq'][mapping], record['seq'])
    np.testing.assert_array_equal(raw['price_time_s'][mapping], record['time_s'])
    np.testing.assert_array_equal(raw['last'][mapping], record['price'])
    context = rt['votes'].context(raw)
    entries = feed[feed[:, 7] == 1]
    assert np.all(entries[:, 4] == {'TOPIX': 5, 'NK225': 10}[symbol])
    votes = {int(order[0]): rt['votes'].measure(raw, context, int(mapping[int(order[0])]), 60, int(order[3]))
             for order in entries}
    paper = hashlib.sha256(feed.tobytes(order='C')).hexdigest()
    account = dict(symbol=symbol, record=record, quotes=quotes, feed=feed, quiet=quiet['active'],
                   quiet_force=quiet['force'], quiet_windows=quiet['windows'],
                   paper_SHA256=paper, mapping=mapping, trade_features={'60': votes})
    diagnostics = dict(raw=diagnosis, v2_correction=correction, normal_rows=len(record['seq']),
        paper_orders=len(feed), paper_publications=len(entries), paper_SHA256=paper,
        clock_qualification=qualification,
        raw_source='未加工の旧f stage原本の元clock44列だけ。normal採用seqは高水位表示で適格な行へ完全一致。出来高は既存reset/v2 usable/unknownを維持。',
        limit=record['limit'], tick=record['tick'], quiet_windows=quiet['windows'])
    return account, diagnostics


def account_row(scene: str, symbol: str, result: dict) -> dict:
    """
    機能: 新14口座を旧66保存行と同じ会計列へ対応させる。
    引数: scene/symbol(str)、result(dict)は新完成政策。
    返り値: dictは共通methodと商品別固定設定を持つ一場の行。
    """
    s = result['summary']
    return dict(session=scene, symbol=symbol, method=METHOD, actual_config=ACTUAL[symbol],
        profit=s['利益'], loss=s['損失'], net=s['収支'], campaigns=s['親数'],
        winning_campaigns=s['勝ち親'], losing_campaigns=s['負け親'],
        winning_lots=s['勝ち枚数'], losing_lots=s['負け枚数'], fees=s['費用'],
        origin='追加七場の新金融', unclosed=0, verified_flat=True,
        verified_flat_basis='当該新会計のfinish=True・終端long_qty/short_qtyを直接検査。')


def old_rows() -> tuple[list[dict], dict]:
    """
    機能: 旧33場保存公開会計の固定二設定だけを引用する。
    引数: なし。
    返り値: tuple[list[dict],dict]は66行と引用SHA。旧金融再運転は0。
    """
    payload = OLD_ACCOUNT.read_bytes()
    public = json.loads(payload.decode('utf-8-sig'))
    assert len(public['sessions']) == 33
    rows = []
    for symbol, case_id in ACTUAL.items():
        own = [v for v in public['cases'][case_id]['rows'] if v['symbol'] == symbol]
        assert len(own) == 33
        rows += [dict(v, method=METHOD, actual_config=case_id, origin='旧33保存会計の引用',
                      unclosed=None, verified_flat=True,
                      verified_flat_basis='旧00106正式結果13f534a10b081db94944d723171214a2132829b66b70f177e0d3055b27116944のfinish/全会計合格と旧独立rows_checkへ委譲。rootが固定二設定66行全件Trueを確認。今回の元曲線検査や数量0の新測定ではない。',
                      保存範囲='完結親と場会計の保存集計を引用。旧実注文台帳を今回再読せず、未保存診断は補完しない。') for v in own]
    assert len({(v['session'], v['symbol']) for v in rows}) == 66
    return rows, dict(path=OLD_ACCOUNT.relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(payload).hexdigest())


def metrics(rows: list[dict]) -> dict:
    """
    機能: 無取引を含む場会計から現在目標の安定性を記述する。
    引数: rows(list[dict])は同商品・同期間の場行。
    返り値: dictは純収支・黒赤無・中央値・最大赤字と平均黒字。旧円床を復活させない。
    """
    ns = [v['net'] for v in rows]
    green = [v for v in ns if v > 0]
    red = [v for v in ns if v < 0]
    gain, loss = sum(v['profit'] for v in rows), sum(v['loss'] for v in rows)
    active = sum(v['campaigns'] > 0 for v in rows)
    return dict(net=sum(ns), profit=gain, loss=loss, fees=sum(v['fees'] for v in rows),
        parents=sum(v['campaigns'] for v in rows), sessions=len(rows), positive=len(green), negative=len(red),
        active=active, no_trade=len(rows)-active, median=float(np.median(ns)) if ns else None,
        mean_session_net=sum(ns)/len(rows) if rows else None,
        profit_share=gain/(gain+loss) if gain+loss else None,
        mean_positive_session_net=sum(green)/len(green) if green else None,
        worst_session_loss=max([-v for v in red], default=0),
        黒字率=len(green)/len(rows) if rows else None,
        未取引は勝ちでない=True, 旧十万円床を判定に使用しない=True)
