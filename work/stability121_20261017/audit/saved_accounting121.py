"""三新条件の保存注文・玉・全気配時価を、売買を再生せず独立照合する。"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PRIOR = ROOT / 'work/stability120_20261017'
sys.path.insert(0, str(PRIOR / 'audit'))
import saved_accounting120 as core
from qualifications120e import qualifications, valid_quotes_e

CORE_SHA = '3cf2c6727301b401a548b501ece268d62e996ec92528f35bb6b7897f2e78d16e'
BASELINE_SHA = '63766637c69f8572465b1ec3cc3c735e8eef234c1657b3ca0542bd3b6fa9f2ba'
READS = Counter()
JST = timezone(timedelta(hours=9))


def accounting_spec(accepted: dict) -> dict:
    """
    機能: 既監査算術の幅検査だけを固定一ptへ接続する。
    引数: accepted(dict)は正常気配の五列。
    返り値: dictは両建て許可と一pt幅の算術用仕様。売買条件を変換しない。
    """
    first_mid = float(accepted['bid'][0] + accepted['ask'][0]) / 2
    return dict(mode=14, fraction=1.0 / first_mid)


def audit_one(quotes: dict, orders: np.ndarray, lots: np.ndarray, curve: np.ndarray,
              row: dict, setting: dict, policy: dict) -> dict:
    """
    機能: 全正常行の現金・在庫・費用後清算時価と新規返済資格を独立算術で確認する。
    引数: quotes(dict)、orders/lots/curve(ndarray)は政策番号除去済み、row/setting/policy(dict)は固定契約。
    返り値: dictは確認済み口座の小会計。注文取消済み内部状態は再生成しない。
    """
    accepted, rejected = valid_quotes_e(quotes, setting)
    core.near(row['clock_rejected'], rejected, '121正常Last時計BBOの棄却数')
    core.near(row['step'], 1.0, '121幅は場初価格によらず一pt固定')
    normalized = dict(row, clock_rejected=0)
    if 'realized_net' not in normalized:
        normalized['realized_net'] = row['profit'] - row['loss']
    answer = core.audit_account(accepted, orders, lots, curve, normalized, setting, accounting_spec(accepted))
    qualifications(accepted, orders, row, setting, dict(mode=2, trail=policy['trail']))
    if policy['reset_after_profit']:
        entries = orders[orders[:, 1] == 1]
        profitable = orders[(orders[:, 1] == 2) & (orders[:, 9] == 1) & (orders[:, 16] > 0)]
        for close in profitable:
            side = -close[2]
            same_side = entries[entries[:, 2] == side]
            core.check(not np.any(same_side[:, 3] == close[4]), '121利確約定原行に同方向再発注なし')
            core.check(not np.any(same_side[:, 4] == close[4]), '121利確原行の既予約同方向新規は取消済み')
    return answer


def metrics(rows: list) -> dict:
    """
    機能: 確認済み小会計の全四十場を同じ分母で集計する。
    引数: rows(list[dict])は一条件・一商品の全場。
    返り値: dictは利益・損失・収支・場数と最大赤字。選抜は行わない。
    """
    return dict(sessions=len(rows), profit=sum(r['profit'] for r in rows), loss=sum(r['loss'] for r in rows),
                net=sum(r['net'] for r in rows), positive=sum(r['net'] > 0 for r in rows),
                negative=sum(r['net'] < 0 for r in rows), flat=sum(r['net'] == 0 for r in rows),
                fees=sum(r['fees'] for r in rows), worst=min((r['net'] for r in rows), default=0))


def pure() -> None:
    """
    機能: 市場と無関係な手書き二注文で固定一pt接続と全玉清算の算術を試す。
    引数: なし。
    返り値: None。エンジン・元入力・実結果をimport又は読取しない。
    """
    core.check(core.sha(Path(core.__file__).read_bytes()) == CORE_SHA, '121既監査算術の源不変')
    q = dict(row=np.arange(5), time=np.array([0., 1., 61., 121., 122.]),
             last=np.array([100., 100., 105., 105., 104.]),
             bid=np.array([100., 100., 105., 105., 104.]),
             ask=np.array([100.5, 100.5, 105.5, 105.5, 104.5]))
    setting = dict(cap=10, multiplier=1000., fee=41.8, observed_tick=.5,
                   session_start=0., entry_end=120., close_time=121., session_end=180.)
    o = np.array([[1, 1, 1, 0, 1, 0, 1, 100.5, 41, 0, 0, 1, 100.25, 100, 100, 100.5, 0, 100],
                  [1, 2, -1, 3, 4, 121, 122, 104, 41, 9, 0, 1, 105.25, 104, 104, 104.5, 3418, 0]], float)
    lots = np.array([[1, 1, 0, 0, 1, 1, 100.5, 3, 4, 122, 104, 3500, 82, 3418, 9, 4418, -582, 100, 104]], float)
    curve = np.array([[0, 0, 0, 0, 0, 0, 0, 0], [2, 61, 4418, -41, 0, 1, 0, 0],
                      [3, 121, 4418, -41, 0, 1, 0, 0], [4, 122, 3418, 3418, 3418, 0, 0, 1000]], float)
    row = dict(net=3418., cash=3418., profit=3418., loss=0., fees=82., closed_lots=1, wins=1, losses=0,
               unclosed=0, max_long=1, max_short=0, max_drawdown=1000., min_equity=-582., entries=1,
               clock_rejected=0, step=1., held_entry_fees=0, last_equity=3418., last_time=122.,
               realized_net=3418., forced_loss=0, forced_profit=3418., trail_net=0, long_net=3418., short_net=0)
    core.audit_account(q, o, lots, curve, row, setting, accounting_spec(q))
    core.save(HERE / '固定一ポイント幅と既独立算術の人工接続.json', dict(passed=True,
        audit_source_sha256=core.sha(Path(__file__).read_bytes()), accounting_source_sha256=CORE_SHA,
        checks=dict(core.CHECKS), original_market_reads=0, financial_replay=0, actual_result_reads=0))
    print('固定一ptの独立算術接続は純人工で一致。実結果読取0。', flush=True)


def main(result: Path, expected_sha: str, output: Path) -> None:
    """
    機能: 根の完成通知後にだけ新百二十口座と四十保存NPZを各一読保全して監査する。
    引数: result(Path)は完成JSON、expected_sha(str)は指定SHA、output(Path)は未使用所有先。
    返り値: None。元book・旧NPZ・売買エンジン・試行台帳は読取又は再実行しない。
    """
    core.check(not output.exists(), '121所有監査先未使用')
    core.check(core.sha(Path(core.__file__).read_bytes()) == CORE_SHA, '121既監査算術の源不変')
    auxiliary = {str(Path(f.__code__.co_filename)): core.sha(Path(f.__code__.co_filename).read_bytes())
                 for f in (valid_quotes_e, qualifications)}
    raw = result.read_bytes()
    READS['完成結果'] += 1
    core.check(core.sha(raw) == expected_sha, '121根指定完成結果SHA')
    owned = output / 'owned'
    owned.mkdir(parents=True)
    (owned / '完成結果.json').write_bytes(raw)
    data = json.loads(raw)
    core.check(data['passed'] and len(data['specs']) == 3 and len(data['runs']) == 120
               and len(data['cache']) == len(data['sessions']) == 40, '121三条件百二十口座四十入力')
    core.check(data['financial_accounts'] == 120 and data['reused_baseline_accounts'] == 40
               and data['original_market_reads'] == data['API'] == data['実注文'] == 0, '121由来と再利用数')
    core.check(tuple(data['order_columns']) == core.ORDER_COLUMNS and tuple(data['lot_columns']) == core.LOT_COLUMNS
               and tuple(data['curve_columns']) == core.CURVE_COLUMNS, '121保存列契約')
    sources = {name: core.sha((ROOT/name).read_bytes()) for name in data['sources']}
    core.check(sources == data['sources'], '121金融源開始不変')
    fixed = json.loads((WORK/'固定計画.json').read_text(encoding='utf-8'))
    proposal = json.loads((WORK/'試行計画.json').read_text(encoding='utf-8'))
    registered = json.loads((WORK/'正式登録の全出力.json').read_text(encoding='utf-8'))
    checked = json.loads((WORK/'事前照合の全出力.json').read_text(encoding='utf-8'))
    actual = json.loads(registered['stdout'])
    core.check(registered['終了コード'] == checked['終了コード'] == 0
               and json.loads(checked['stdout'])['提案完全'] is True
               and actual['id'] == proposal['id'] and actual['spec'] == proposal['spec'], '121登録実体と完全提案一致')
    core.check(sources == fixed['sources'] == proposal['spec']['implementation'], '121七源と正式実装の拘束')
    meta_raw = (ROOT/fixed['input_manifest']['path']).read_bytes()
    core.check(core.sha(meta_raw) == fixed['input_manifest']['sha256'], '121入力目録SHA')
    meta = json.loads(meta_raw)
    core.check(meta['baseline'] == data['baseline'] == fixed['baseline'], '121旧基準引用は登録前固定と同値')
    prior_raw = (PRIOR/'audit_result120e1/owned/完成結果.json').read_bytes()
    READS['既所有基準結果'] += 1
    core.check(core.sha(prior_raw) == BASELINE_SHA == data['baseline']['sha256'], '121既所有基準結果SHA')
    baseline_rows = [row for row in json.loads(prior_raw)['runs'] if row['symbol'] == 'TOPIX' and row['method'] == 'ROTATE_S2_T1']
    core.check(len(baseline_rows) == 40 and baseline_rows == data['baseline']['rows']
               and all(row['step'] == 1 for row in baseline_rows), '121基準四十場保存会計と一pt全一致')
    runtime = json.loads((WORK/'実行プロセスの通常高速全配列確認.json').read_text(encoding='utf-8'))
    core.check(runtime['passed'] and runtime['comparisons'] == 6 and len(runtime['cases']) == 6
               and all(case['entries'] > 0 for case in runtime['cases']), '121本番プロセスの非空六人工')
    engine_path = next(name for name in sources if name.endswith('/engine121.py'))
    core.check(runtime['engine_sha256'] == sources[engine_path], '121本番人工と同じ金融源')
    loader = importlib.util.spec_from_file_location('audit121_catalog', WORK/'catalog121.py')
    catalog = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(catalog)
    core.check(catalog.specifications() == data['specs'] == fixed['specs'], '121三固定仕様一致')
    planned = {item['session']: (item['path'], item['sha256']) for item in meta['inputs']}
    references = {item['session']: (item['source'], item['source_sha256']) for item in data['cache']}
    core.check(len(planned) == len(references) == 40 and planned == references
               and set(planned) == set(data['sessions']), '121四十保存入力参照の一致')
    rows = {(row['session'], row['method']): row for row in data['runs']}
    core.check(len(rows) == 120 and all(row['symbol'] == 'TOPIX' for row in data['runs']), '121商品と口座の一意性')
    reports, important = [], []
    for number, ref in enumerate(data['cache']):
        session = ref['session']
        path = (ROOT/ref['path']).resolve()
        core.check(path.is_relative_to((WORK/'measurement').resolve()), '121新保存cacheだけ読取')
        raw = path.read_bytes()
        READS['新小cache'] += 1
        core.check(core.sha(raw) == ref['sha256'], '121小cache同bytes')
        (owned/(session+'.npz')).write_bytes(raw)
        with np.load(BytesIO(raw), allow_pickle=False) as stored:
            arrays = {name: stored[name].copy() for name in stored.files}
        core.check(set(arrays) == {'orders','lots','curves','quotes__row','quotes__time','quotes__last','quotes__bid','quotes__ask'}, '121保存配列集合')
        for key, columns in (('orders',19), ('lots',20), ('curves',9)):
            a = arrays[key]
            core.check(a.ndim == 2 and a.shape[1] == columns and np.all(a[:,0] == a[:,0].astype(int))
                       and np.all((a[:,0] >= 0) & (a[:,0] < 3)), '121政策番号前置と列数')
        quotes = {name: arrays['quotes__'+name] for name in ('row','time','last','bid','ask')}
        setting = catalog.settings('TOPIX', session)
        for index, policy in enumerate(data['specs']):
            parts = [arrays[key][arrays[key][:,0] == index,1:] for key in ('orders','lots','curves')]
            answer = audit_one(quotes, *parts, rows[session,policy['id']], setting, policy)
            reports.append(dict(session=session, method=policy['id'], **answer))
            if session == '2026-09-24_Day':
                for lot in sorted(parts[1], key=lambda value: value[13])[:3]:
                    important.append(dict(method=policy['id'], uid=int(lot[0]), side=int(lot[1]), rank=int(lot[2]),
                        entry=datetime.fromtimestamp(lot[5],JST).isoformat(), entry_price=lot[6],
                        exit=datetime.fromtimestamp(lot[9],JST).isoformat(), exit_price=lot[10],
                        gross=lot[11], fees=lot[12], net=lot[13], reason=int(lot[14])))
        print(f'{number+1}/40 三新条件の保存会計一致', flush=True)
    core.check(sources == {name: core.sha((ROOT/name).read_bytes()) for name in sources}, '121金融源終端不変')
    core.check(all(core.sha(Path(name).read_bytes()) == value for name,value in auxiliary.items()), '121既資格算術源終端不変')
    unclosed = [row for row in reports if row['unclosed']]
    proof = dict(passed=not unclosed, result_sha256=expected_sha,
        audit_source_sha256=core.sha(Path(__file__).read_bytes()), accounting_source_sha256=CORE_SHA,
        auxiliary_sources=auxiliary, sources=sources, checks=dict(core.CHECKS), reads=dict(READS),
        saved_accounts=len(reports), reused_baseline_accounts=40, unclosed_accounts=unclosed,
        reconstructed=reports, original_market_reads=0, old_npz_reads=0, financial_replay=0, registry_changes=0,
        留保='固定1ptへ既独立算術を接続。rungは入口時rankで物理slotではない。取消済み未約定stateの全再現はせず、保存注文の資格と同原行再発注禁止を検査し人工へ委譲。同じ既知40場の開発比較。')
    target = output/'三新条件全百二十口座の独立保存会計監査.json'
    core.save(target, proof)
    projection = dict(baseline=metrics(baseline_rows), methods={policy['id']: metrics([
        row for row in data['runs'] if row['method'] == policy['id']]) for policy in data['specs']},
        september24={policy['id']: rows['2026-09-24_Day',policy['id']] for policy in data['specs']},
        important_loss_lots=important, financial_replay=0)
    core.save(output/'集計と九月二十四日重要玉の独立射影.json', projection)
    print(json.dumps(dict(passed=not unclosed, accounts=len(reports), sha256=core.sha(target.read_bytes()),
                          reads=dict(READS), projection=projection), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pure', action='store_true')
    parser.add_argument('--result', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.pure:
        pure()
    else:
        assert args.result and args.sha256 and args.output
        main(args.result, args.sha256, args.output)
