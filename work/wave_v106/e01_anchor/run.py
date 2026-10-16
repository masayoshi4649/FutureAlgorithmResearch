"""参照値三対照を金融前に固定し、登録後だけ全33へ適用する。"""

import argparse
import gc
import gzip
import pickle
import time

import numpy as np

import common
import catalog
import engine
from prepare import packet


def freeze() -> None:
    """
    機能: 三参照と単独変更の限界を入力/人工へ結んで固定する。
    引数: なし。
    返り値: None。登録前金融は行わない。
    """
    inp = common.read(common.HERE / '保存紙上66の入力接続.json')
    proof = common.read(common.HERE / '参照値三対照と不正公開の人工検査.json')
    assert inp['全合格'] and proof['全合格']
    for p, sha in proof['sourceSHA256'].items():
        assert common.digest(common.ROOT / p) == sha
    src = common.sources(); cases = catalog.catalog()
    refs = [dict(path=str(p.relative_to(common.ROOT)).replace('\\', '/'), sha256=common.digest(p))
        for p in (common.HERE / '保存紙上66の入力接続.json', common.HERE / '参照値三対照と不正公開の人工検査.json',
                  common.REFERENCE / '結果.json', common.REFERENCE / '金額統一再開事前固定.json')]
    plan = dict(id='106_E01の指値参照値を当時気配へ揃える三対照',
        name='同じ0.2ATRの待機幅を即時側・中値・受動側から測る', purpose='条件比較',
        compares_to=['106_E01比較の金額残差許容統一と再開'],
        question='Lastの取引位置に依存する指値を実気配へ揃えると、未約定の利益機会と追加損失はどう変わるか。',
        change='新規指値の参照値だけを変更、元GUの方向/固定ATR/途中/出口と5/10枚は不変。',
        repeat_reason='前回はLast基準のBBO実行。今回は公開時点の三参照へ単独変更、紙上66は再生せず保存feedを共有。',
        limitations=['ミニ/マイクロの実商品板・表示量・受動指値の列順と部分約定は再現しない。',
            '新建値が変わっても元の紙上GU返済条件を張り直さないため、実損切りリスクとの乖離はあり得る。',
            '紙上の密な影停止線は今回保存packetにない。新旧建値差と返済判断の固定を示し、真の当時S幅を創作しない。',
            '全33既知の対照。最高値/将来勝敗から参照値や幅を決めない。'], evidence=refs,
        spec=dict(entry=dict(紙上='元E01_G_U保存66feed', 変更=cases, 有利幅ATR=.2,
            参照=['即時側:買ask/売bid', '中値:(bid+ask)/2', '受動側:買bid/売ask'],
            資格='紙上新規公開行の正常BBOのみ。不正公開親は即取消、未来正常行へ移さない。'),
            management=dict(元GU='保存済み注文順を共有、新紙上0', 途中条件='不変更', 欠測中別親='旧busy取消不変'),
            exit=dict(元返済='元virtual返済判断後の次正常気配、元予定timer優先。',
                未成立='最初のvirtual返済で永久取消、当行到達は先に約定して次気配返済。', 場内='全返済'),
            allocation=dict(初回=common.QUANTITY, 片方向上限=common.CAP, 追加='なし'),
            costs=dict(片道={'TOPIXmini':41.8,'NK225micro':11.}, 切捨て='部分返済含む各実注文別floor'),
            execution=dict(線='参照−side×0.2ATR、買floor/売ceil native呼値',
                新規='公開当行禁止、以後最初ask<=買線/bid>=売線で当該気配約定。',
                返済='元判断後の次qok、通常気配は買ask/売bid', 評価='買玉bid/売玉ask−実料',
                残差='旧経済金額net/G/Lのatol1e-7 rTol0、fees/count/cap exact。'),
            data=dict(sessions=inp['sessions'], input_manifests=refs, 全既知=True, 紙上新再生=0), implementation=src))
    common.save(common.HERE / '試行計画.json', plan)
    common.save(common.HERE / '事前固定.json', dict(全合格=True, cases=cases, sessions=inp['sessions'],
        sourceSHA256=src, 入力SHA256=inp['出力SHA256'], 計画SHA256=common.digest(common.HERE / '試行計画.json'),
        入力証跡=refs, 新実金融=198, 紙上新再生=0, 基準再生=0, 基準66会計再利用=True))
    print('気配参照三対照を固定、登録と根の金融開始許可を待ちます。', flush=True)


def contribution(base: dict, candidate: dict) -> dict:
    """
    機能: 同じ紙上親で、見送り・追加・共通入口/返済/費用の変化を分ける。
    引数: base/candidate(dict)は元BBOと候補の保存会計。
    返り値: dict。未約定と無取引を勝ちとして集計しない。
    """
    b = {p['親']: p for p in base['parent']}; c = {p['親']: p for p in candidate['parent']}
    common_ids = set(b) & set(c); omitted = set(b) - set(c); added = set(c) - set(b)
    diff = dict(避けた基準損失=0., 失った基準利益=0., 得た追加利益=0., 生じた追加損失=0.,
        共通入口変化=0., 共通返済変化=0., 共通費用変化=0.)
    mult = 1000. if candidate['key'][1] == 'TOPIX' else 10.
    for cid in omitted:
        diff['失った基準利益' if b[cid]['収支'] > 0 else '避けた基準損失'] -= b[cid]['収支']
    for cid in added:
        diff['得た追加利益' if c[cid]['収支'] > 0 else '生じた追加損失'] += c[cid]['収支']
    entry_risk = []
    for cid in common_ids:
        bo = base['orders'][(base['orders'][:,2] == cid) & (base['orders'][:,7] == 1)][0]
        co = candidate['orders'][(candidate['orders'][:,2] == cid) & (candidate['orders'][:,7] == 1)][0]
        assert bo[3] == co[3] and bo[4] == co[4]
        entry = -co[3] * co[4] * (co[5] - bo[5]) * mult
        exits = (c[cid]['粗損益'] - b[cid]['粗損益']) - entry
        cost = b[cid]['費用'] - c[cid]['費用']
        diff['共通入口変化'] += entry; diff['共通返済変化'] += exits; diff['共通費用変化'] += cost
        entry_risk.append(dict(親=cid, 方向=int(co[3]), 基準実建値=float(bo[5]), 候補実建値=float(co[5]),
            有利方向建値差=float(co[3] * (co[5] - bo[5])), 基準新規行=int(bo[0]), 候補新規行=int(co[0]),
            注意='元紙上返済判断は不変更。これは建値差であり、真の当時停止線までのリスク幅ではない。'))
    delta = candidate['summary']['収支'] - base['summary']['収支']
    assert np.isclose(delta, sum(diff.values()), atol=1e-7, rtol=0.)
    return dict(収支変化=delta, 分解=diff, 共通親数=len(common_ids), 見送り親数=len(omitted),
        追加親数=len(added), 建値乖離=entry_risk, 全一致=True)


def run() -> None:
    """
    機能: 登録済み三参照を198実口座だけ再生し、基準との差を親で対応付ける。
    引数: なし。
    返り値: None。元紙上GU・元BBO基準の再生はしない。
    """
    start = time.monotonic(); fixed = common.read(common.HERE / '事前固定.json')
    assert fixed['sourceSHA256'] == common.sources() and not (common.HERE / '結果.json').exists()
    assert common.digest(common.HERE / 'prepared.pkl') == fixed['入力SHA256']
    for ref in fixed['入力証跡']:
        assert common.digest(common.ROOT / ref['path']) == ref['sha256']
    common.save(common.HERE / '実行開始.json', dict(全合格=True, 固定SHA256=common.digest(common.HERE / '事前固定.json'),
        正式1回=True, 紙上再生=0, 基準再生=0))
    material = common.read(common.HERE / 'prepared.pkl')
    baseline = common.read(common.REFERENCE / '結果.json')
    rows = {c['id']: [] for c in fixed['cases']}; parents = {c['id']: [] for c in fixed['cases']}
    changes = {c['id']: [] for c in fixed['cases']}; hashes = {}
    with common.cache():
        for key, values in sorted(material.items()):
            r, q, paper, quiet = [values[name] for name in ('ready','quote','paper','quiet')]
            base_path = common.REFERENCE / 'ledgers/L_D20_BBO' / (key[0] + '_' + key[1] + '.pkl.gz')
            name = str(base_path.relative_to(common.REFERENCE)).replace('\\', '/')
            assert common.digest(base_path) == baseline['台帳SHA256'][name]
            original = packet(base_path); assert original['summary'] == values['baseline']
            for case in fixed['cases']:
                a = catalog.anchors(r, q, paper['feed'], case['mode'])
                output = engine.simulate(r['time_s'], r['last'], q['bid'], q['ask'], q['quote_valid'], a,
                    paper['feed'], quiet['active'], quiet['force'], r['limit'], common.CAP[key[1]], r['tick'], .2, False)
                row, ledger = common.ACCOUNT.account(key, r, q, output, case)
                for order in ledger['orders']:
                    if int(order[7]) != 1:
                        continue
                    source, fill, side = int(order[1]), int(order[0]), int(order[3])
                    assert q['quote_valid'][source] and np.isfinite(a[source]) and source < fill
                    posted = ledger['limit_events'][(ledger['limit_events'][:,1] == 1) & (ledger['limit_events'][:,2] == order[2])][0]
                    line = posted[8]; path = q['ask' if side > 0 else 'bid'][source+1:fill+1]
                    reached = q['quote_valid'][source+1:fill+1] & ((path<=line) if side>0 else (path>=line))
                    assert np.flatnonzero(reached)[0] + source + 1 == fill
                ledger['reference_at_posts'] = a[paper['feed'][paper['feed'][:,7] == 1,0].astype(int)]
                ledger['paper_feed_rows'] = paper['feed'][paper['feed'][:,7] == 1,0].astype(int)
                diff = contribution(original, ledger)
                changes[case['id']].append(dict(session=key[0], symbol=key[1], **diff))
                rows[case['id']].append(row)
                parents[case['id']].extend(dict(**p, session=key[0], symbol=key[1]) for p in ledger['parent'])
                target = common.HERE / 'ledgers' / case['id'] / (key[0] + '_' + key[1] + '.pkl.gz')
                assert not target.exists(); target.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(target, 'wb', compresslevel=1) as stream:
                    pickle.dump(ledger, stream, protocol=5)
                hashes[str(target.relative_to(common.HERE)).replace('\\','/')] = common.digest(target)
                del ledger, output, a
            print(key[0] + ' ' + key[1] + ' 3参照・同親寄与完了', flush=True)
            del original
            gc.collect()
    results = {}
    for case in fixed['cases']:
        name = case['id']
        results[name] = dict(case=case, rows=rows[name],
            symbols={symbol: common.ACCOUNT.aggregate([r for r in rows[name] if r['symbol']==symbol],
                [p for p in parents[name] if p['symbol']==symbol], fixed['sessions']) for symbol in ('TOPIX','NK225')})
    assert sum(len(v) for v in rows.values()) == 198 and fixed['sourceSHA256'] == common.sources()
    common.save(common.HERE / '結果.json', dict(全合格=True, results=results, 同紙上親の寄与=changes,
        基準66=baseline['results']['L_D20_BBO'], 基準SHA256=common.digest(common.REFERENCE / '結果.json'),
        台帳SHA256=hashes, source開始終端一致=True, 正式口座数=198, 紙上新再生=0, 基準再生=0,
        事前固定SHA256=common.digest(common.HERE / '事前固定.json'), 経過秒=time.monotonic()-start,
        scope='全33既知。新規参照値のみ変更。相手信号/元GU返済不変更。', API=0, 原本再読=0))
    print('参照値三条件×全33・198会計完了', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='E01有利指値の参照値だけを単独比較')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--root-trial-registered', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        assert not args.root_trial_registered
        freeze()
    else:
        assert args.root_trial_registered, '登録と根の金融開始許可が必要'
        run()
