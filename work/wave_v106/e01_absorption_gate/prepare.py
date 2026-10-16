"""条件を先に固定し、根の許可後だけ既知33場の公開観測を非金融測定する。"""

import argparse
from collections import Counter
import gc
import gzip
import hashlib
import io
import pickle
import time
import traceback

import numpy as np

import catalog
import common
import feature
import gate
import known_policy
import votes


def fix(independent_path) -> None:
    """
    機能: 小metadata・人工と単一部品の八部品草案を、大型入力読取前に固定する。
    引数: independent_path(Path)は独立人工の合格JSON。
    返り値: None。保存33cache・NPZ・金融会計は読まない。
    """
    meta_path = common.ROOT/'work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json'
    raw_path = common.ROOT/'work/wave_v106/e01_trade_gate/入力測定前の固定.json'
    art_path = common.HERE/'表示維持述語と元公開門の人工検査.json'
    meta, raw_meta, art = (common.read_json(p) for p in (meta_path, raw_path, art_path))
    independent_path = independent_path.resolve()
    assert independent_path.is_relative_to(common.ROOT/'work')
    independent = common.read_json(independent_path)
    assert all(v['全合格'] for v in (meta, raw_meta, art, independent))
    assert meta['sessions'] == raw_meta['sessions'] and len(meta['sessions']) == 33
    assert len(meta['cache']) == 33 and len(raw_meta['raw_inputs']) == 66
    current = common.sources()
    for p, h in art['source_SHA256'].items():
        assert current[p] == h, p
    assert independent['source_SHA256'] == current
    originals = {
        'work/wave_v106/e01_trade_gate/votes.py': 'votes.py',
        'work/wave_v106/e01_known_veto/policy.py': 'known_policy.py'}
    for original, owned in originals.items():
        assert (common.ROOT/original).read_bytes() == (common.HERE/owned).read_bytes()
    manifests = [dict(path=p.relative_to(common.ROOT).as_posix(), SHA256=common.digest(p))
                 for p in (meta_path, raw_path, art_path, independent_path)]
    spec = dict(
        entry=dict(比較元=catalog.BASELINE_ID, 候補=catalog.CANDIDATE_ID,
                   紙上='保存E01_G_U全後続feed不変。原paperの再計算0。',
                   新部品=catalog.definition(), 最小接触回数=catalog.MINIMUM_TOUCHES,
                   活動比下限=catalog.MINIMUM_ACTIVITY_RATIO),
        management=dict(変更='公開行の入口maskだけ。待機/保有/返済への流用なし。',
                        影='拒否された親も元の部分/全返済feedへ進み、後続親を維持。',
                        再参加='元エンジンの実玉busy・場停止・受付期限を維持。'),
        exit=dict(政策='P1L8：当時の費用後清算利益1初回観測呼値又は損失8呼値で次正常BBOへ全返済、その場終了。',
                  静観='元Uquiet・quiet_force・場内limitを変更しない。',
                  今回='非金融準備だけ。停止・返済・収支は測定しない。'),
        allocation=dict(初回=catalog.QUANTITY, 片方向上限=catalog.CAP,
                        政策='比較元1・単一入口部品1。配分・増玉・商品別閾値なし。'),
        costs=dict(片道料金={'TOPIXmini': 41.8, 'NK225micro': 11.},
                   価格倍率={'TOPIX': 1000., 'NK225': 10.},
                   扱い='将来金融は実注文単位floor、元UID残料・FIFOを不変更。今回料金計算0。'),
        execution=dict(新規='D0、公開当行で約定せず次正常買ask/売bid。',
                       気配='ラージ板を実商品の価格代理に使う元仮定。旧正常執行資格を変更しない。',
                       順序='追加部品を公開時だけ判定。未来同時計原行で予約を取り消さない。'),
        data=dict(sessions=meta['sessions'], input_manifests=manifests,
                  入力33=meta['cache'], 原行66=raw_meta['raw_inputs'], 必要原列=list(catalog.FIELDS),
                  読取='根の明示後、同bytes照合で各一読。原book/currentAPI/原paper再計算0。',
                  時計='自己原seq以下、元W60 first_vote_raw_rowから公開原行まで。真の受信時計は未保存。'),
        implementation=current)
    plan = dict(id=catalog.TRIAL_ID, name='同価格逆板の表示維持と反復接触の非金融準備',
                purpose='新仮説の可用性測定、金融未許可',
                question='表示初期数量以上の活動代理でも気配が進まない公開入口を、当時までに既知として識別できるか。',
                change='KNOWN_VETO公開入口に、同逆価格の数量非減少・支持非進行・接触2回・公表出来高差Q0以上だけ追加する案。',
                repeat_reason='旧Supply門が要求する表示減少のない枝。price-only/volume-only等全既存枝が未捕捉とは断定しない。',
                compares_to=['106_E01既知二票以上の逆票見送り二出口対照'],
                spec=spec, 金融未許可=True, 原金融入力読取=0, API=0,
                root敵対レビュー='件数2だけでは通常の厚い板の少量処理を判定する欠点を修正し、活動差/Q0比1をデータ未読の段階で追加。',
                financial_policy=dict(id=catalog.CANDIDATE_ID, baseline_id=catalog.BASELINE_ID,
                                      window_seconds=60, mode='KNOWN_VETO_ABSORB', execution='D0',
                                      exit='P1L8', offset_atr=0., quantity=catalog.QUANTITY, cap=catalog.CAP),
                limitations=['集約出来高差の全量が同価格・同方向の約定だったとは証明できない。',
                             '新しい成立件数・金額成績は未測定。基準保存会計の再読も有効性の新証拠ではない。'])
    common.write(common.HERE/'八部品と非金融測定の計画.json', plan)
    fixed = dict(全合格=True, source_SHA256=current, input_manifests=manifests,
                 sessions=meta['sessions'], cache=meta['cache'], raw_inputs=raw_meta['raw_inputs'],
                 original_sources={p: common.digest(common.ROOT/p) for p in originals},
                 計画SHA256=common.digest(common.HERE/'八部品と非金融測定の計画.json'),
                 非金融範囲='全paper公開候補の適用・未知・成立のみ。旧勝敗との照合と金融は別目的。',
                 接頭検査='各商品各場の先頭・中央・末尾の公開候補を接頭入力で再測定、同一由来と値を要求。',
                 大型入力読取=0, NPZ=0, 原板=0, 原paper再計算=0, 金融=0, API=0)
    common.write(common.HERE/'入力測定前の固定.json', fixed)
    print('八部品案と非金融範囲を固定、rootの入力許可待ち。金融0、大型入力0。', flush=True)


def load(item: dict, raw: bool = False) -> dict:
    """
    機能: 固定された保存cache又は派生NPZを、同一bytes照合で各一回読む。
    引数: item(dict)はpath/SHA256、raw(bool)は原行NPZか。
    返り値: dictは保存値又は必要原列。原JSON・API・金融を実行しない。
    """
    path = common.ROOT/item['path']
    assert path.resolve().is_relative_to(common.ROOT/'work')
    saved = path.read_bytes()
    assert hashlib.sha256(saved).hexdigest() == item['SHA256'], path
    if not raw:
        return pickle.loads(gzip.decompress(saved))
    with np.load(io.BytesIO(saved), allow_pickle=False) as archive:
        value = {name: archive[name] for name in catalog.FIELDS}
    assert len(value['raw_seq']) == item['raw_rows']
    assert len(value['execution_to_raw_index']) == item['normal_rows']
    for array in value.values():
        array.flags.writeable = False
    return value


def availability(entries: np.ndarray, base: dict, added: dict) -> dict:
    """
    機能: 公開候補を元資格・追加観測・見送り理由へ分け、勝敗を使わず集計する。
    引数: entries(ndarray)、base/added(dict[int,dict])は紙上公開候補と元票・新述語。
    返り値: dictは非金融の件数。実新規・実決済・勝率ではない。
    """
    rows = [int(o[0]) for o in entries]
    values = [added[r] for r in rows]
    original = [known_policy.verdict(base[r], 'KNOWN_VETO')[0] for r in rows]
    return dict(
        紙上公開候補数=len(rows), 元KNOWN_VETO許可数=sum(original),
        元票未知数=sum(not base[r]['known'] for r in rows),
        元票既知二票未満数=sum(base[r]['known'] and base[r]['direction_votes'] < 2 for r in rows),
        追加述語対象数=sum(v['eligible'] for v in values),
        追加述語既知数=sum(v['eligible'] and v['known'] for v in values),
        追加述語未知数=sum(v['eligible'] and not v['known'] for v in values),
        全公開の成立数=sum(v['eligible'] and v['known'] and v['hit'] for v in values),
        元許可から追加見送り数=sum(ok and v['eligible'] and v['known'] and v['hit'] for ok, v in zip(original, values)),
        追加後公開許可数=sum(ok and not (v['eligible'] and v['known'] and v['hit']) for ok, v in zip(original, values)),
        追加未知理由=dict(Counter(str(v['reason']) for v in values if v['eligible'] and not v['known'])))


def run() -> None:
    """
    機能: rootが明示した一回だけ、既知33cacheと66NPZから全公開候補の観測を作る。
    引数: なし。
    返り値: None。新所有cache・可用性と接頭照合を保存し、金融・勝敗照合は0に保つ。
    """
    fixed = common.read_json(common.HERE/'入力測定前の固定.json')
    assert fixed['全合格'] and fixed['source_SHA256'] == common.sources()
    for item in fixed['input_manifests']:
        assert common.digest(common.ROOT/item['path']) == item['SHA256']
    for path, sha in fixed['original_sources'].items():
        assert common.digest(common.ROOT/path) == sha
    assert common.digest(common.HERE/'八部品と非金融測定の計画.json') == fixed['計画SHA256']
    common.write(common.HERE/'入力測定開始.json', dict(全合格=True, 新金融=0,
                 事前固定SHA256=common.digest(common.HERE/'入力測定前の固定.json')))
    cache = {}
    summaries = {}
    checks = Counter()
    started = time.monotonic()
    for session in fixed['sessions']:
        old = load(fixed['cache'][session])
        checks['保存E01cache一読'] += 1
        packet = dict(schema_version=1, session=session, accounts={})
        summaries[session] = {}
        for symbol in ('TOPIX', 'NK225'):
            account = old['accounts'][symbol]
            raw = load(fixed['raw_inputs'][session+'|'+symbol], True)
            checks['原行NPZ一読'] += 1
            mapping = raw['execution_to_raw_index']
            np.testing.assert_array_equal(mapping, account['mapping'])
            for source, normal in (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price')):
                np.testing.assert_array_equal(raw[source][mapping], account['record'][normal])
                checks['原行normal一致'] += 1
            for name in ('bid', 'ask'):
                np.testing.assert_array_equal(raw[name][mapping], account['quotes'][name])
                checks['原行BBO一致'] += 1
            entries = account['feed'][account['feed'][:, 7] == 1]
            assert len(set(int(o[0]) for o in entries)) == len(entries)
            context = votes.context(raw)
            base = account['trade_features']['60']
            added = {}
            for entry in entries:
                normal_row, side = int(entry[0]), int(entry[3])
                raw_row = int(mapping[normal_row])
                measured = votes.measure(raw, context, raw_row, catalog.WINDOW, side)
                assert measured == base[normal_row], (session, symbol, normal_row)
                checks['保存元票同値'] += 1
                added[normal_row] = feature.measure(raw, context, raw_row, side, base[normal_row])
                checks['新公開観測'] += 1
            # ----------------------------------------
            # 実接頭でも未来同時計行が混ざらないことを、先頭・中央・末尾の候補で確認する。
            for j in sorted(set((0, len(entries)//2, len(entries)-1))) if len(entries) else ():
                entry = entries[j]
                normal_row, side = int(entry[0]), int(entry[3])
                raw_row = int(mapping[normal_row])
                short = {name: value[:raw_row+1] for name, value in raw.items()
                         if name != 'execution_to_raw_index'}
                short['execution_to_raw_index'] = mapping[mapping <= raw_row]
                shorter_context = votes.context(short)
                shorter_base = votes.measure(short, shorter_context, raw_row, catalog.WINDOW, side)
                assert shorter_base == base[normal_row]
                assert feature.measure(short, shorter_context, raw_row, side, shorter_base) == added[normal_row]
                checks['実公開接頭一致'] += 1
            accepted, reason = gate.mask(account['feed'], len(account['record']['price']), base, added)
            own = dict(account, absorption_features=added,
                       absorption_gate_accepted=accepted, absorption_gate_reasons=reason)
            packet['accounts'][symbol] = own
            summaries[session][symbol] = availability(entries, base, added)
            del raw, context
        path = common.HERE/f'input/{session}.pkl.gz'
        common.write(path, packet)
        cache[session] = dict(path=path.relative_to(common.ROOT).as_posix(), SHA256=common.digest(path))
        del old, packet
        gc.collect()
        print(session+' 表示維持の公開観測完了、金融0', flush=True)
    assert checks['保存E01cache一読'] == 33 and checks['原行NPZ一読'] == 66
    assert common.sources() == fixed['source_SHA256']
    aggregate = {}
    for symbol in ('TOPIX', 'NK225'):
        rows = [summaries[s][symbol] for s in fixed['sessions']]
        aggregate[symbol] = {key: sum(r[key] for r in rows)
                             for key in rows[0] if key != '追加未知理由'}
        aggregate[symbol]['追加未知理由'] = dict(sum((Counter(r['追加未知理由']) for r in rows), Counter()))
        aggregate[symbol]['元許可から追加見送りあり場数'] = sum(r['元許可から追加見送り数'] > 0 for r in rows)
    common.write(common.HERE/'全33場の表示維持公開観測の準備.json', dict(
        全合格=True, sessions=fixed['sessions'], cache=cache, activity=summaries, aggregate=aggregate,
        一致検査=dict(checks), source_SHA256=fixed['source_SHA256'], 開始終端source一致=True,
        入力固定SHA256=common.digest(common.HERE/'入力測定前の固定.json'),
        大型入力読取=33, NPZ読取=66, 原板=0, 原paper再計算=0, 旧金融読取=0,
        新金融=0, 勝敗照合=0, API=0, 経過秒=time.monotonic()-started))
    print('全33場の非金融観測準備完了。金融・勝敗照合0。', flush=True)


def main() -> None:
    """
    機能: 静的固定又はrootが明示した非金融入力測定を一回だけ呼ぶ。
    引数: CLI --fix-only/--root-input-reviewed(bool)、--independent-proof(Path)は独立人工位置。
    返り値: None。未許可金融・自動再開始・現在APIの経路はない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--fix-only', action='store_true')
    parser.add_argument('--root-input-reviewed', action='store_true')
    parser.add_argument('--independent-proof', type=common.Path)
    args = parser.parse_args()
    assert args.fix_only != args.root_input_reviewed
    if args.fix_only:
        assert args.independent_proof is not None
        fix(args.independent_proof)
        return
    assert args.independent_proof is None
    assert not (common.HERE/'入力測定開始.json').exists()
    assert not (common.HERE/'入力測定False.json').exists()
    assert not (common.HERE/'全33場の表示維持公開観測の準備.json').exists()
    try:
        run()
    except Exception:
        common.write(common.HERE/'入力測定False.json', dict(全合格=False, 原因=traceback.format_exc(),
                     新金融=0, 自動再開始=False, API=0))
        raise


if __name__ == '__main__':
    main()
