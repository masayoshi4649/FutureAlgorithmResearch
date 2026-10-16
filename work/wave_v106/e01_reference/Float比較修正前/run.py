"""事前に固定・登録した三つの実行条件を、共有紙上GUから一回だけ再生する。"""

import argparse
import gc
import gzip
import pickle
import time

import numpy as np

import engine
from accounting import account, aggregate
from bridge import HERE, ROOT, digest, load_inputs, owned_cache, read, runtime, save, source_hashes
from specification import CAP, CASES, QUANTITY, specification


def freeze() -> None:
    """
    機能: 人工と入力準備の成功を結び、登録可能な比較計画を金融前に固定する。
    引数: なし。
    返り値: None。旧結果の全額再生は行わない。
    """
    assert not (HERE / '事前固定.json').exists()
    prepared = read(HERE / 'prepared/入力準備の完了.json')
    artificial = read(HERE / '人工検査.json')
    assert prepared['全合格'] and artificial['全合格']
    assert prepared['金融再生'] == 0
    with owned_cache():
        rt = runtime()
        spec = specification(); hashes = source_hashes()
        assert all(digest(ROOT / p) == h for p, h in artificial['実装SHA256'].items())
        manifests = [dict(path=str(p.relative_to(ROOT)).replace('\\', '/'), sha256=digest(p))
            for p in (HERE / 'prepared/入力準備の完了.json', HERE / '人工検査.json',
                      ROOT / 'work/wave_v85/prepared/入力準備の完了.json',
                      ROOT / 'work/wave_v83/prepared/価格入力の照合.json')]
        old = ROOT / 'work/wave_v87/round12/observed/results/L_D20.json'
        references = [dict(path=str(p.relative_to(ROOT)).replace('\\', '/'), sha256=digest(p))
                      for p in (old, ROOT / 'work/wave_v85/results/事前固定.json',
                                ROOT / 'work/wave_v87/round12/事前固定.json')]
        proposal = dict(id='106_E01同条件と指値待機のBBO全33比較',
            name='元E01の有利指値を現実的な気配約定へ修正する比較', purpose='不具合修正',
            question='良かったCurrentPrice版L_D20が、待機買ask/売bidの到達条件でも両銘柄で安定するか。',
            change='E01入口/途中/出口は固定。実約定と清算時価だけBBO化。旧30＋追加3場を既知比較。',
            repeat_reason='旧指値モデルはCurrentPrice到達を約定扱いしていたため、BBO版の保存結果を再利用できない。',
            compares_to=[], evidence=references,
            limitations=['旧85/87の個別IDは試行台帳の索引対象外。元保存結果と事前固定を正式パスで直接確認する。',
                         '全33は既知比較。旧CurrentPrice結果の再確認を新たな成功証拠に数えない。'],
            spec=dict(entry=dict(紙上id='E01_G_U', mask=1, time_mode='U', 条件変更='なし', 指値ATR=.2,
                                 比較元の正式固定=references),
                management=dict(紙上共有='1回/口座', 元途中判断='不変更', 実保有返済待ち中の次紙上親='新規拒否'),
                exit=dict(元GU='固定出口の紙上判断後、次の正常気配。初回紙上返済で未約定指値を永久取消。',
                          場内='既知limitとU休止を優先して最初の正常気配で返済。保有終端は失敗。'),
                allocation=dict(初回=QUANTITY, 上限=CAP, 複数条件='独立比較。配分組合せではない。'),
                costs=dict(片道料金={'TOPIXmini': 41.8, 'NK225micro': 11.}, 切捨て='注文ごと'),
                execution=dict(条件=list(CASES), 指値=spec['指値'], 成行=spec['成行'], 返済=spec['返済'],
                               行順=spec['同行順序'], 不正気配='待機。紙上原行を移さない。', 時価=spec['時価']),
                data=dict(sessions=spec['全33'], input_manifests=manifests, 時計=spec['時間'],
                          探索='全33既知。新金融を読んで変数を選ばない。'), implementation=hashes))
        save(HERE / '試行計画.json', proposal)
        save(HERE / '事前固定.json', dict(全合格=True, 仕様=spec, 実装SHA256=hashes, 入力証跡=manifests,
            気配SHA256=prepared['全気配SHA256'], 旧L_D20結果SHA256=digest(old),
            計画SHA256=digest(HERE / '試行計画.json'), 正式金融=0, 紙上口座=66, 実口座=198,
            JIT保存先=str(HERE / 'jit'), API=0))
    print('三条件×全33の比較計画を固定。登録と実行許可を待ちます。', flush=True)


def packet(path, value: dict) -> None:
    """
    機能: 所有領域へ注文と全行会計を新規保存する。
    引数: path(Path)、value(dict)は保存先と台帳。
    返り値: None。既存台帳を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wb', compresslevel=1) as stream:
        pickle.dump(value, stream, protocol=5)


def verify_orders(ready: dict, q: dict, feed: np.ndarray, values: tuple, case: dict) -> dict:
    """
    機能: 新規が公開後最初の到達気配、返済が元判断後最初の気配であることを確認する。
    引数: ready/q/case(dict)、feed(ndarray)、values(tuple)は出力と当時観測。
    返り値: dict。将来利益を条件へ渡さない。
    """
    orders = values[0]; proofs = values[8]
    normal = q['quote_valid'] if case['execution'] != '旧現在値参考' else np.isfinite(ready['last']) & (ready['last'] > 0)
    checks = 0
    for o in orders:
        row, source = int(o[0]), int(o[1]); side = int(o[3])
        if int(o[7]):
            posted = proofs[(proofs[:, 1] == 1) & (proofs[:, 2] == o[2])]
            assert len(posted) == 1 and posted[0, 0] == source
            line = posted[0, 8]
            if case['execution'] == '旧現在値参考':
                path = ready['last']
            else:
                path = q['ask' if side > 0 else 'bid']
            eligible = normal[source + 1:row + 1].copy()
            if case['id'] != 'E01_G_U_BBO':
                eligible &= path[source + 1:row + 1] <= line if side > 0 else path[source + 1:row + 1] >= line
            first = np.flatnonzero(eligible)
            assert len(first) and int(first[0]) + source + 1 == row
        else:
            first = np.flatnonzero(normal[source + 1:row + 1])
            assert len(first) and int(first[0]) + source + 1 == row
            if int(o[6]) == 91:
                paper = feed[(feed[:, 0] == source) & (feed[:, 2] == o[2]) & (feed[:, 7] == 0)]
                assert len(paper) and np.sum(paper[:, 4]) >= o[4]
        checks += 1
    return dict(全合格=True, 全注文検査数=checks, 入口公開後最初の正常到達=True, 返済元行後最初の正常気配=True)


def run() -> None:
    """
    機能: 固定した66紙上口座を共有し、198実口座の約定・料金後会計を一度保存する。
    引数: なし。
    返り値: None。全33既知の比較であり未来成功を主張しない。
    """
    started = time.monotonic(); fixed = read(HERE / '事前固定.json')
    assert not (HERE / '結果.json').exists() and not (HERE / '実行開始.json').exists()
    with owned_cache():
        rt = runtime()
        assert all(digest(ROOT / p) == h for p, h in fixed['実装SHA256'].items())
        for m in fixed['入力証跡']:
            assert digest(ROOT / m['path']) == m['sha256']
        assert digest(HERE / '試行計画.json') == fixed['計画SHA256']
        assert digest(HERE / 'prepared/quotes.pkl') == fixed['気配SHA256']
        inputs, signals, input_hashes = load_inputs(rt)
        quotes = read(HERE / 'prepared/quotes.pkl')
        assert set(inputs) == set(quotes)
        save(HERE / '実行開始.json', dict(全合格=True, 固定SHA256=digest(HERE / '事前固定.json'),
            登録通知後=True, 実装SHA256=source_hashes(), 時刻=time.time(), 正式再生1回=True))
        print('元GUの入口・途中・出口の因果列を全66口座へ準備', flush=True)
        features = rt['strategy'].initialize(inputs, signals)
        old_rows = { (r['session'], r['symbol']): r for r in read(ROOT / 'work/wave_v87/round12/observed/results/L_D20.json')['rows'] }
        rows = {case['id']: [] for case in CASES}; parents = {case['id']: [] for case in CASES}
        account_checks = []; lineage_checks = []; ledger_hashes = {}; paper_hashes = {}; old_matches = []
        for key in sorted(inputs):
            ready = inputs[key]; q = quotes[key]; session, symbol = key
            for name in ('seq', 'time_s'):
                np.testing.assert_array_equal(ready[name], q[name])
            core, settings = rt['strategy'].virtual({}, ready, features[key])
            feed = rt['prior'].order_feed(core)
            assert np.all(feed[feed[:, 7] == 1, 4] == QUANTITY[symbol])
            assert int(settings['audit_cap']) == CAP[symbol]
            quiet = rt['old'].time_filter.features(ready, 'U')
            path = HERE / 'paper' / (session + '_' + symbol + '.pkl.gz')
            packet(path, dict(key=key, feed=feed, orders=core['orders'], trades=core['trades'],
                settings=settings, windows=core.get('time_windows', [])))
            paper_hashes[str(path.relative_to(HERE)).replace('\\', '/')] = digest(path)
            for case in CASES:
                base = (ready['time_s'], ready['last'])
                tail = (feed, quiet['active'], quiet['force'], float(ready['limit']), CAP[symbol],
                        float(ready['tick']), case['offset_atr'], case['execution'] == '気配成行')
                if case['execution'] == '旧現在値参考':
                    values = rt['strategy'].engine.simulate(*base, *tail)
                else:
                    values = engine.simulate(*base, q['bid'], q['ask'], q['quote_valid'], *tail)
                row, ledger = account(key, ready, q, values, case)
                linkage = verify_orders(ready, q, feed, values, case)
                ledger['order_lineage'] = linkage; ledger['paper_path'] = str(path.relative_to(HERE)).replace('\\', '/')
                ledger['paper_sha256'] = digest(path)
                rows[case['id']].append(row)
                parents[case['id']].extend(dict(**p, session=session, symbol=symbol) for p in ledger['parent'])
                target = HERE / 'ledgers' / case['id'] / (session + '_' + symbol + '.pkl.gz')
                packet(target, ledger); ledger_hashes[str(target.relative_to(HERE)).replace('\\', '/')] = digest(target)
                account_checks.append(dict(case=case['id'], session=session, symbol=symbol, 全合格=True))
                lineage_checks.append(dict(case=case['id'], session=session, symbol=symbol, **linkage))
                if case['id'] == 'L_D20_PRICE' and key in old_rows:
                    r = old_rows[key]
                    assert row['収支'] == r['net'] and row['費用'] == r['fees'] and row['親数'] == r['cycles']
                    assert row['利益'] == r['cycle_profit'] and row['損失'] == r['cycle_loss']
                    old_matches.append(dict(session=session, symbol=symbol, 旧L_D20経済一致=True))
                del ledger, values
            print(session + ' ' + symbol + ' 共有GUと3実会計完了', flush=True)
            del core, feed
            gc.collect()
        results = {}
        for case in CASES:
            identifier = case['id']
            results[identifier] = dict(case=case, rows=rows[identifier],
                symbols={symbol: aggregate([r for r in rows[identifier] if r['symbol'] == symbol],
                    [p for p in parents[identifier] if p['symbol'] == symbol], fixed['仕様']['全33'])
                    for symbol in ('TOPIX', 'NK225')})
        assert len(account_checks) == len(lineage_checks) == 198 and len(old_matches) == 60
        assert all(digest(ROOT / p) == h for p, h in fixed['実装SHA256'].items())
        save(HERE / '結果.json', dict(全合格=True, scope='固定三条件×全33・両銘柄。全既知比較。',
            事前固定SHA256=digest(HERE / '事前固定.json'), 実装開始終端一致=True, 正式再生回数=1,
            紙上口座数=66, 実会計数=198, results=results, 旧30参考経済一致=old_matches,
            全会計検査=account_checks, 全注文因果検査=lineage_checks,
            台帳SHA256=ledger_hashes, 紙上SHA256=paper_hashes, API=0, 実注文=0,
            経過秒=time.monotonic() - started))
        print('全33・198口座の共有GU比較完了', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='元GU不変更の指値BBO比較')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--root-trial-registered', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        assert not args.root_trial_registered
        freeze()
    else:
        assert args.root_trial_registered, '根による重複登録と正式実行許可が必要'
        run()
