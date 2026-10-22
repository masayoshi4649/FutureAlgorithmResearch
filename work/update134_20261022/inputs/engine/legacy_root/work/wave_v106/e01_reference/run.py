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


def freeze(resume: bool = False, money: bool = False) -> None:
    """
    機能: 人工と入力準備の成功を結び、登録可能な比較計画を金融前に固定する。
    引数: resume/money(bool)は残口座継続と全金額検算の微小許容統一か。
    返り値: None。旧結果の全額再生は行わない。
    """
    fixed_name = '金額統一再開事前固定.json' if money else '再開事前固定.json' if resume else '事前固定.json'
    plan_name = '金額統一再開試行計画.json' if money else '再開試行計画.json' if resume else '試行計画.json'
    assert not (HERE / fixed_name).exists()
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
        reuse = {}
        if resume:
            first = read(HERE / '事前固定.json')
            assert first['仕様'] == spec and not read(HERE / '初回正式実行のFloat比較False.json')['全合格']
            assert digest(HERE / 'Float比較修正前/run.py') == first['実装SHA256']['work/wave_v106/e01_reference/run.py']
            reuse = {str(p.relative_to(HERE)).replace('\\', '/'): digest(p)
                     for folder in ('paper', 'ledgers') for p in (HERE / folder).rglob('*.pkl.gz')}
            assert len([name for name in reuse if name.startswith('ledgers/')]) == (132 if money else 60)
            assert len([name for name in reuse if name.startswith('paper/')]) == (44 if money else 20)
            proposal.update(id='106_E01比較の丸め許容修正と再開',
                name='旧floatの円残差検算を直し完成20口座を再利用して残46口座を継続',
                compares_to=['106_E01同条件と指値待機のBBO全33比較'],
                change='旧保存net比較だけ絶対許容1e-7円。fees/count exact。金融数学・入力・条件は変更しない。',
                repeat_reason='完成20紙上・60実台帳をSHA照合して再利用し、未完46紙上・138実のみ初回再生。')
            proposal['spec']['execution']['旧保存net同値'] = '絶対許容1e-7円。料金・件数は完全一致。'
            proposal['spec']['data']['再利用'] = dict(初回固定SHA256=digest(HERE / '事前固定.json'),
                初回FalseSHA256=digest(HERE / '初回正式実行のFloat比較False.json'), 台帳SHA256=reuse)
            if money:
                assert not read(HERE / '再開正式実行の親GLFloat比較False.json')['全合格']
                previous = read(HERE / '再開事前固定.json')
                assert digest(HERE / '親GL比較修正前/run.py') == previous['実装SHA256']['work/wave_v106/e01_reference/run.py']
                proposal.update(id='106_E01比較の金額残差許容統一と再開',
                    name='旧金額net/G/Lの丸め検算を統一し完成44口座を再利用して残22口座を継続',
                    compares_to=['106_E01比較の丸め許容修正と再開'],
                    change='旧保存金額net/G/L比較だけ絶対許容1e-7円。fees/count/capはexact。金融数学・入力・条件不変。',
                    repeat_reason='完成44紙上・132実台帳をSHA確認して再利用、未完22紙上・66実のみ初回再生。')
                proposal['spec']['execution']['旧保存net同値'] = '金額net/G/Lの絶対許容1e-7円、rTol0。整数保証fees/count/capはexact。'
                proposal['spec']['data']['再利用'].update(第二FalseSHA256=digest(HERE / '再開正式実行の親GLFloat比較False.json'))
        save(HERE / plan_name, proposal)
        save(HERE / fixed_name, dict(全合格=True, 仕様=spec, 実装SHA256=hashes, 入力証跡=manifests,
            気配SHA256=prepared['全気配SHA256'], 旧L_D20結果SHA256=digest(old),
            計画SHA256=digest(HERE / plan_name), 正式金融=0, 紙上口座=66, 実口座=198,
            再利用SHA256=reuse, 未完紙上=22 if money else 46 if resume else 66,
            未完実口座=66 if money else 138 if resume else 198,
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


def old_matches(summary: dict, old: dict) -> bool:
    """
    機能: 同じ円会計に残った旧JSONのFloat丸めだけを許容して同値確認する。
    引数: summary/old(dict)は新しい独立会計と旧保存会計。
    返り値: bool。料金・件数は完全一致、金額net/G/Lは絶対1e-7円で比較する。
    """
    return (np.isclose(summary['収支'], old['net'], atol=1e-7, rtol=0.)
        and summary['費用'] == old['fees'] and summary['親数'] == old['cycles']
        and np.isclose(summary['利益'], old['cycle_profit'], atol=1e-7, rtol=0.)
        and np.isclose(summary['損失'], old['cycle_loss'], atol=1e-7, rtol=0.))


def run(resume: bool = False, money: bool = False) -> None:
    """
    機能: 固定した66紙上口座を共有し、198実口座の約定・料金後会計を一度保存する。
    引数: resume/money(bool)は完成台帳再利用と全金額残差許容の段階。
    返り値: None。全33既知の比較であり未来成功を主張しない。
    """
    started = time.monotonic()
    fixed_name = '金額統一再開事前固定.json' if money else '再開事前固定.json' if resume else '事前固定.json'
    plan_name = '金額統一再開試行計画.json' if money else '再開試行計画.json' if resume else '試行計画.json'
    start_name = '金額統一再開実行開始.json' if money else '再開実行開始.json' if resume else '実行開始.json'
    fixed = read(HERE / fixed_name)
    assert not (HERE / '結果.json').exists() and not (HERE / start_name).exists()
    with owned_cache():
        rt = runtime()
        assert all(digest(ROOT / p) == h for p, h in fixed['実装SHA256'].items())
        for m in fixed['入力証跡']:
            assert digest(ROOT / m['path']) == m['sha256']
        assert digest(HERE / plan_name) == fixed['計画SHA256']
        assert digest(HERE / 'prepared/quotes.pkl') == fixed['気配SHA256']
        inputs, signals, input_hashes = load_inputs(rt)
        quotes = read(HERE / 'prepared/quotes.pkl')
        assert set(inputs) == set(quotes)
        assert all(digest(HERE / p) == h for p, h in fixed['再利用SHA256'].items())
        save(HERE / start_name, dict(全合格=True, 固定SHA256=digest(HERE / fixed_name),
            登録通知後=True, 実装SHA256=source_hashes(), 時刻=time.time(), 正式再生1回=True))
        print('元GUの入口・途中・出口の因果列を全66口座へ準備', flush=True)
        features = rt['strategy'].initialize(inputs, signals)
        old_rows = { (r['session'], r['symbol']): r for r in read(ROOT / 'work/wave_v87/round12/observed/results/L_D20.json')['rows'] }
        rows = {case['id']: [] for case in CASES}; parents = {case['id']: [] for case in CASES}
        account_checks = []; lineage_checks = []; ledger_hashes = {}; paper_hashes = {}; old_match_rows = []
        reused = 0; new_paper = 0
        for key in sorted(inputs):
            ready = inputs[key]; q = quotes[key]; session, symbol = key
            for name in ('seq', 'time_s'):
                np.testing.assert_array_equal(ready[name], q[name])
            path = HERE / 'paper' / (session + '_' + symbol + '.pkl.gz')
            if resume and str(path.relative_to(HERE)).replace('\\', '/') in fixed['再利用SHA256']:
                paper_hashes[str(path.relative_to(HERE)).replace('\\', '/')] = digest(path)
                for case in CASES:
                    target = HERE / 'ledgers' / case['id'] / (session + '_' + symbol + '.pkl.gz')
                    name = str(target.relative_to(HERE)).replace('\\', '/')
                    assert digest(target) == fixed['再利用SHA256'][name]
                    with gzip.open(target, 'rb') as stream:
                        ledger = pickle.load(stream)
                    row = ledger['summary']
                    assert ledger['key'] == key and ledger['case'] == case and row['全会計合格']
                    assert row['収支'] == sum(p['収支'] for p in ledger['parent'])
                    assert ledger['paper_sha256'] == digest(path) and ledger['order_lineage']['全合格']
                    rows[case['id']].append(row)
                    parents[case['id']].extend(dict(**p, session=session, symbol=symbol) for p in ledger['parent'])
                    ledger_hashes[name] = digest(target)
                    account_checks.append(dict(case=case['id'], session=session, symbol=symbol, 全合格=True, 保存済再利用=True))
                    lineage_checks.append(dict(case=case['id'], session=session, symbol=symbol, **ledger['order_lineage']))
                    if case['id'] == 'L_D20_PRICE':
                        assert old_matches(row, old_rows[key])
                        old_match_rows.append(dict(session=session, symbol=symbol, 旧L_D20経済一致=True, 保存済再利用=True))
                    reused += 1
                    del ledger
                print(session + ' ' + symbol + ' 保存済3実台帳を再利用・GU再生0', flush=True)
                continue
            core, settings = rt['strategy'].virtual({}, ready, features[key])
            new_paper += 1
            feed = rt['prior'].order_feed(core)
            assert np.all(feed[feed[:, 7] == 1, 4] == QUANTITY[symbol])
            assert int(settings['audit_cap']) == CAP[symbol]
            quiet = rt['old'].time_filter.features(ready, 'U')
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
                    assert old_matches(row, r)
                    old_match_rows.append(dict(session=session, symbol=symbol, 旧L_D20経済一致=True))
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
        assert len(account_checks) == len(lineage_checks) == 198 and len(old_match_rows) == 60
        assert reused == (132 if money else 60 if resume else 0) and new_paper == fixed['未完紙上']
        assert all(digest(ROOT / p) == h for p, h in fixed['実装SHA256'].items())
        save(HERE / '結果.json', dict(全合格=True, scope='固定三条件×全33・両銘柄。全既知比較。',
            事前固定SHA256=digest(HERE / fixed_name), 実装開始終端一致=True, 経済口座再生回数=1,
            形式的実行job数=3 if money else 2 if resume else 1, 初回False保持=resume, 第二False保持=money,
            当job実紙上再生数=new_paper, 当job実金融再生数=new_paper * 3, 当job再利用数=reused,
            紙上口座数=66, 実会計数=198, results=results, 旧30参考経済一致=old_match_rows,
            全会計検査=account_checks, 全注文因果検査=lineage_checks,
            台帳SHA256=ledger_hashes, 紙上SHA256=paper_hashes, API=0, 実注文=0,
            経過秒=time.monotonic() - started))
        print('全33・198口座の共有GU比較完了', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='元GU不変更の指値BBO比較')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--root-trial-registered', action='store_true')
    parser.add_argument('--resume-float-comparison', action='store_true')
    parser.add_argument('--resume-money-comparison', action='store_true')
    args = parser.parse_args()
    resume = args.resume_float_comparison or args.resume_money_comparison
    if args.freeze:
        assert not args.root_trial_registered
        freeze(resume, args.resume_money_comparison)
    else:
        assert args.root_trial_registered, '根による重複登録と正式実行許可が必要'
        run(resume, args.resume_money_comparison)
