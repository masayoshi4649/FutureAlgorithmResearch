"""保存系譜と時間方針を、生成元からの純配列とメモリ固定だけで点検する。"""

from __future__ import annotations

import ast
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[1]
CHECKS = 0
REJECTS = 0


def check(value: bool, detail: object) -> None:
    """
    機能: 小人工の判定を数え、不成立なら止める。
    引数: value(bool)、detail(object) 検査内容。
    返り値: None。
    """
    global CHECKS
    CHECKS += 1
    assert value, detail


def sha(path: Path) -> str:
    """
    機能: 小さな源の指紋を求める。
    引数: path(Path) 源又は監査証跡。
    返り値: str SHA256。原入力・NPZは読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, name: str):
    """
    機能: SOURCE_ONLYの私有複製を読み込む。
    引数: path(Path)、name(str) 名前。
    返り値: module 定義だけを持つ対象。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def node(path: Path, name: str) -> ast.FunctionDef:
    """
    機能: 対象関数だけをASTで選ぶ。
    引数: path(Path)、name(str) 源と関数。
    返り値: ast.FunctionDef 関数定義。
    """
    return next(x for x in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(x, ast.FunctionDef) and x.name == name)


def rejected(function, reason: str) -> None:
    """
    機能: 不整合な純入力が受理されないことを数える。
    引数: function(callable) 実行、reason(str) 理由。
    返り値: None。
    """
    global REJECTS
    refused = False
    try:
        function()
    except (AssertionError, KeyError, ValueError, IndexError, TypeError):
        refused = True
    check(refused, reason)
    REJECTS += 1


def make_source_fixture(producer) -> tuple[dict, dict, list[str], np.ndarray, float, float]:
    """
    機能: producerの実関数を人工JSONだけへ適用し、44列と31公開列を作る。
    引数: producer(module) 原行抽出の純関数。
    返り値: tuple 型定義・原配列・公開列名・公開行・観測窓。
    """
    begin = datetime(2026, 1, 5, 9, tzinfo=timezone(timedelta(hours=9)))
    start, end = begin.timestamp() - 60, begin.timestamp() + 60
    rows = []
    for i in range(6):
        stamp = (begin + timedelta(seconds=i)).isoformat()
        raw = dict(Symbol="人工", SymbolName="人工", Exchange=23, CurrentPrice=100.5, CurrentPriceTime=stamp, TradingVolume=1000 + 10 * i, TradingVolumeTime=stamp)
        for level in range(1, 11):
            raw["Buy" + str(level)] = dict(Price=100 - (level - 1) * .5, Qty=10)
            raw["Sell" + str(level)] = dict(Price=100.5 + (level - 1) * .5, Qty=20)
        rows.append((i, raw))
    initial, _ = producer.extract_rows(rows, start, end)
    index = np.array([0, 2, 5], dtype=np.int64)
    record = {target: initial[source][index].copy() for source, target in (("raw_seq", "seq"), ("price_time_s", "time_s"), ("last", "price"), ("bid", "bid"), ("ask", "ask"))}
    arrays, _ = producer.extract_rows(rows, start, end, record)
    fields = ['type','episode','start_i','pub_i','d','bid','ask','bid_q0','ask_q0',
              'bid_q_at_public','ask_q_at_public','min_bid_q','min_ask_q',
              'opposite_q0','opposite_q_at_public','opposite_min_q','quantity_ratio','minimum_quantity_ratio',
              'quantity_group','total_volume','npositive','first_positive_i','fresh_price_time',
              'volume_after_price','volume_clock_known','first_positive_fresh_price_time',
              'first_positive_volume_after_price','first_positive_volume_clock_known',
              'start_raw_seq','pub_raw_seq','pub_price_time_s']
    events = []
    for typ, pub in ((0, 1), (1, 2)):
        values = dict(type=typ, episode=0, start_i=0, pub_i=pub, d=1, bid=100., ask=100.5,
                      bid_q0=10., ask_q0=20., bid_q_at_public=10., ask_q_at_public=20., min_bid_q=10., min_ask_q=20.,
                      opposite_q0=20., opposite_q_at_public=20., opposite_min_q=20., quantity_ratio=1., minimum_quantity_ratio=1.,
                      quantity_group=1, total_volume=10. * pub, npositive=pub, first_positive_i=1, fresh_price_time=1,
                      volume_after_price=0, volume_clock_known=1, first_positive_fresh_price_time=1,
                      first_positive_volume_after_price=0, first_positive_volume_clock_known=1, start_raw_seq=0, pub_raw_seq=pub,
                      pub_price_time_s=float(arrays["price_time_s"][pub]))
        events.append([values[k] for k in fields])
    return producer.schema()["columns"], arrays, fields, np.array(events, dtype=np.float64), start, end


def contract_checks(contract, producer) -> dict:
    """
    機能: 逆写像・原値join・未知と価格時計・未来列を純人工で点検する。
    引数: contract/producer(module) 純検査対象。
    返り値: dict 検査範囲。過去の保存eventは再測定しない。
    """
    schema, base, fields, events, start, end = make_source_fixture(producer)
    check(len(schema) == len(base) == 44, "producer44列")
    frozen = {k: x.copy() for k, x in base.items()}
    contract.validate(base, schema)
    check(all(not x.flags.writeable for x in base.values()), "44列readonly")
    for name in base:
        np.testing.assert_array_equal(base[name], frozen[name])
        check(base[name].dtype == frozen[name].dtype, ("値と型を変更しない", name))
    np.testing.assert_array_equal(base['normal_execution_row'], np.array([0, -1, 1, -1, -1, 2], dtype=np.int32))
    check(base['normal_execution_row'][0] == 0, "正常index0を未知扱いしない")
    for reason, mutate in (
        ("逆写像をboolへ変更", lambda a: a.update(normal_execution_row=a['normal_execution_row'].astype(bool))),
        ("未対応−2", lambda a: a['normal_execution_row'].__setitem__(1, -2)),
        ("正常ID交換", lambda a: a['normal_execution_row'].__setitem__([0, 2], [1, 0])),
        ("逆写像余分", lambda a: a['normal_execution_row'].__setitem__(1, 3)),
        ("順写像重複", lambda a: a['execution_to_raw_index'].__setitem__(1, 0)),
        ("順写像範囲外", lambda a: a['execution_to_raw_index'].__setitem__(2, 6)),
        ("原seq重複", lambda a: a['raw_seq'].__setitem__(2, 1)),
        ("列不足", lambda a: a.pop('last')),
        ("深さshape違い", lambda a: a.update(bid_prices=a['bid_prices'][:, :9])),
    ):
        a = {k: v.copy() for k, v in frozen.items()}
        mutate(a)
        rejected(lambda: contract.validate(a, schema), reason)
    got = contract.signal(base, events.copy(), fields, start, end)
    check(set(got) == {'events', 'fields', 'price_valid_mask'}, "結果ラベルを返さない三key")
    check(got['fields'] == fields and not got['events'].flags.writeable, "保存公開列とreadonly")
    check(got['price_valid_mask'].all(), "正常index未対応でも価格資格は独立")
    check(not got['price_valid_mask'].flags.writeable, "価格mask readonly")
    for changed, row, value in (("pub_i", 0, 1.5), ("first_positive_i", 0, 0), ("start_i", 0, -1),
                                 ("pub_raw_seq", 0, 999), ("start_raw_seq", 0, 999), ("pub_price_time_s", 0, start),
                                 ("bid", 0, 99), ("ask", 0, 101), ("bid_q0", 0, 9), ("ask_q0", 0, 19),
                                 ("bid_q_at_public", 0, 9), ("ask_q_at_public", 0, 19), ("d", 0, 0), ("type", 0, 2)):
        broken = events.copy()
        broken[row, fields.index(changed)] = value
        rejected(lambda: contract.signal(base, broken, fields, start, end), changed)
    duplicate = list(fields)
    duplicate[-1] = duplicate[0]
    rejected(lambda: contract.signal(base, events.copy(), duplicate, start, end), "31列重複")
    future = list(fields)
    future[future.index('volume_after_price')] = 'future_outcome'
    rejected(lambda: contract.signal(base, events.copy(), future, start, end), "31列を保った未知の未来列")
    # ----------------------------------------
    # 価格資格は当行と直前価格時計だけで判断する。
    cases = [
        ('同clock可', 'price_time_s', 2, frozen['price_time_s'][1], [True] * 6),
        ('価格時計欠測', 'price_time_s', 2, np.nan, [True, True, False, False, True, True]),
        ('価格時計逆行', 'price_time_s', 2, frozen['price_time_s'][1] - .5, [True, True, False, True, True, True]),
        ('reset8', 'price_reset_reason', 2, 8, [True, True, False, True, True, True]),
        ('両気配同値', 'ask', 2, 100., [True, True, False, True, True, True]),
        ('場外終端', 'price_time_s', 5, end, [True, True, True, True, True, False]),
        ('数量欠測は価格と別', 'bid_qty', 3, np.nan, [True] * 6),
        ('数量flag未知は価格と別', 'best_quantity_valid', 3, False, [True] * 6),
        ('出来高未知は価格と別', 'volume_delta_known', 3, False, [True] * 6),
        ('出来高別時計を未来価格としない', 'volume_time_s', 3, end + 100, [True] * 6),
        ('Last未知は価格と別', 'last', 3, np.nan, [True] * 6),
    ]
    for reason, name, row, value, wanted in cases:
        a = {k: v.copy() for k, v in frozen.items()}
        a[name][row] = value
        np.testing.assert_array_equal(contract.price_valid(a, start, end), wanted)
        check(True, reason)
    a = {k: v.copy() for k, v in frozen.items()}
    a['raw_seq'][2:] += 1
    contract.validate(a, schema)
    np.testing.assert_array_equal(contract.price_valid(a, start, end), [True, True, False, True, True, True])
    check(True, "原seqgap当行未知、次行復帰")
    for size in range(1, 7):
        a = {k: v[:size] for k, v in frozen.items() if k != 'execution_to_raw_index'}
        np.testing.assert_array_equal(contract.price_valid(a, start, end), contract.price_valid(frozen, start, end)[:size])
        check(True, ("価格資格の接頭", size))
    return {"原値join": ['公開原seq', '初期原seq', '公開価格時計', '公開bid/ask', '初期bidQty/askQty', '公開bidQty/askQty'],
            "派生列": "minQty/累計活動/初回方向等は114の固定源とevent NPZ指紋を出典にする。31列を全再測定したとは呼ばない。",
            "価格資格": "00114同契約。Q/V/Last/depth/旧execution inverseは価格knownへ混ぜない。"}


def plan_checks(plan, catalog, fields: list[str]) -> dict:
    """
    機能: 時間変換と正式builderの八部品をメモリだけで確認する。
    引数: plan/catalog(module)、fields(list[str]) 正常公開schema。
    返り値: dict SOURCE_ONLYの制限。正式freeze・登録は行わない。
    """
    jst = timezone(timedelta(hours=9))
    times = []
    for day, kind, expected_ny in (('2026-10-13', 'Day', None), ('2026-10-13', 'Night', 22), ('2026-11-02', 'Night', 23)):
        start = datetime.fromisoformat(day).replace(hour=8 if kind == 'Day' else 17, minute=45 if kind == 'Day' else 0, tzinfo=jst)
        end = start.replace(hour=15, minute=40) if kind == 'Day' else (start + timedelta(days=1)).replace(hour=5, minute=55)
        out = plan.time_policy(day + '_' + kind, start.timestamp(), end.timestamp())
        wanted_entry = start.replace(hour=9, minute=15) if kind == 'Day' else start.replace(minute=5)
        check(out['entry_start_s'] == wanted_entry.timestamp(), "新規開始時刻")
        check(out['entry_end_s'] == end.timestamp() - 600 and out['force_start_s'] == end.timestamp() - 300, "新規締切と返済予約")
        if expected_ny is None:
            check(out['quiet_windows'] == [], "Dayには米国静観なし")
        else:
            expected = start.replace(hour=expected_ny, minute=30).timestamp()
            check(out['quiet_windows'] == [[expected - 900, expected + 900]], "DST変換後のNY前後15分")
        times.append({"場": day + '_' + kind, "方針": out})
    sources = {str((BASE / name).relative_to(ROOT).as_posix()): hashlib.sha256(('合成源:' + name).encode()).hexdigest() for name in plan.SOURCE_NAMES}
    sessions = [(datetime(2026, 1, 5) + timedelta(days=i)).date().isoformat() + '_Day' for i in range(33)]
    fixed = dict(sessions=sessions, inputs=[dict(場=s, 商品=k, fields=fields) for s in sessions for k in ('TOPIX', 'NK225')])
    generated = {}
    def fake_digest(path: Path) -> str:
        """
        機能: 合成metadata専用の指紋を返し実ファイルを開かない。
        引数: path(Path) 合成位置。
        返り値: str 合成SHA256。
        """
        return hashlib.sha256(str(path).encode()).hexdigest()
    audit = dict(全合格=True, 新金融=0, source_SHA256=sources, evidence=[dict(path='合成監査.json', SHA256=fake_digest(ROOT / '合成監査.json'))])
    def fake_read(path: Path) -> dict:
        """
        機能: 完成前の正式builderへ合成固定又は監査を渡す。
        引数: path(Path) 予定位置。
        返り値: dict 実本文を読まない合成値。
        """
        return fixed if path.name == '入力と保存公開の固定.json' else audit
    def fake_write(path: Path, value: dict) -> None:
        """
        機能: builderの出力をメモリ捕捉し、正式ファイルを作らない。
        引数: path(Path)、value(dict) 出力予定。
        返り値: None。
        """
        generated[path.name] = copy.deepcopy(value)
    namespace = dict(HERE=BASE, ROOT=ROOT, read=fake_read, write=fake_write, digest=fake_digest, sources=lambda: sources, json=json)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node(BASE / 'plan.py', 'freeze')], type_ignores=[])), str(BASE / 'plan.py'), 'exec'), namespace)
    namespace['freeze']()
    proposal = generated['試行計画.json']
    check(set(proposal['spec']) == {'entry', 'management', 'exit', 'allocation', 'costs', 'execution', 'data', 'implementation'}, "八部品")
    check(all(isinstance(v, dict) and v for v in proposal['spec'].values()), "部品を空や文字列にしない")
    check(proposal['spec']['entry']['conditions'] == catalog.configs(), "十二条件の係数保持")
    check(len(proposal['spec']['data']['sessions']) == 33 and len(proposal['spec']['data']['inputs']) == 66, "合成33場66組")
    check(proposal['spec']['implementation'] == sources, "flat source map")
    check(len(proposal['spec']['data']['input_manifests']) == 1, "目録のpathとsha")
    check(proposal['表示主候補'] == 'QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1', "主候補の結果前固定")
    check(proposal['目標']['TOPIX全場平均net'] == 100000 and proposal['目標']['NK円額床'] == '未指定', "経済床は全場平均")
    check(proposal['目標']['金額利益割合'] == .65 and proposal['目標']['赤字場割合'] == .2, "従来基準保持")
    check(proposal['spec']['costs']['fee_ratio'] == {'TOPIX': (418, 10), 'NK225': (11, 1)}, "注文別料金")
    check(json.loads(json.dumps(proposal, ensure_ascii=False))['spec']['entry']['conditions'] == catalog.configs(), "条件のJSON roundtrip")
    for reason, mutate in (
        ('金融既実行の監査を拒否', lambda: audit.update(新金融=1)),
        ('源指紋不一致拒否', lambda: audit.update(source_SHA256={})),
        ('根拠指紋不一致拒否', lambda: audit.update(evidence=[dict(path='合成監査.json', SHA256='0' * 64)])),
    ):
        audit.update(全合格=True, 新金融=0, source_SHA256=sources, evidence=[dict(path='合成監査.json', SHA256=fake_digest(ROOT / '合成監査.json'))])
        mutate()
        rejected(namespace['freeze'], reason)
    return {"時間人工": times, "builder": "合成fixed・source mapを注入し正式freeze関数だけをメモリ実行。正式freeze/登録成功ではない。", "未完成": "finance.py/artificial_root.pyおよび正式全source/登録との実接続は別監査。"}


def main() -> None:
    """
    機能: 指定二源だけへ純人工を接続し、成功又はFalseを保存する。
    引数: なし。
    返り値: None。原入力・結果・NPZ・APIは開かない。
    """
    output = HERE / '入力契約と時間八部品のSOURCE_ONLY独立接続_v2.json'
    result = dict(全合格=False, 入力本文=0, NPZ=0, 保存114事象本文=0, 金融=0, API=0)
    try:
        selected = ('input_contract.py', 'plan.py')
        hashes = {name: sha(BASE / name) for name in selected}
        private = HERE / '指定二源と生成元の私有複製'
        private.mkdir(exist_ok=True)
        for name in selected + ('catalog.py',):
            (private / name).write_bytes((BASE / name).read_bytes())
        producer_path = ROOT / 'work/wave_v103/input/core.py'
        (private / 'producer.py').write_bytes(producer_path.read_bytes())
        sys.path.insert(0, str(private))
        contract = load(private / 'input_contract.py', '独立入力契約')
        plan = load(private / 'plan.py', '独立計画定義')
        catalog = load(private / 'catalog.py', 'catalog')
        sys.modules['catalog'] = catalog
        producer = load(private / 'producer.py', '純人工生成元')
        result['入力契約'] = contract_checks(contract, producer)
        fields = make_source_fixture(producer)[2]
        result['固定計画'] = plan_checks(plan, catalog, fields)
        check(hashes == {name: sha(BASE / name) for name in selected}, "検査中の二源不変更")
        result.update(全合格=True, 確認数=CHECKS, 不整合拒否数=REJECTS, source_SHA256=hashes,
                      生成元_SHA256=sha(producer_path), 独立checker_SHA256=sha(Path(__file__)),
                      実データの有効性='未測定。保存114由来を新しい独立標本へ数えない。')
    except BaseException:
        result.update(確認数=CHECKS, 不整合拒否数=REJECTS, 失敗=traceback.format_exc())
        raise
    finally:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(json.dumps({k: result.get(k) for k in ('全合格', '確認数', '不整合拒否数', '失敗')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
