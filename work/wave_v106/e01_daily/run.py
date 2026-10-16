"""登録後に旧E01の実注文接頭を小利益目標で停止し、全33場を保存する。"""

import argparse
import gc
import time
import traceback

import numpy as np

import catalog
import common
import core
import reference


def aggregate(rows: list[dict], parents: list[dict], sessions: list[str]) -> dict:
    """
    機能: 同一商品全33場の料金後損益・活動・大勝ち依存を集計する。
    引数: rows/parents(list[dict])、sessions(list[str])は固定した会計と場順。
    返り値: dictは親金額指標、場の中央値と最大3利益場除外を併記する。
    """
    assert len(rows) == len(sessions) and {r['session'] for r in rows} == set(sessions)
    totals = core.metric([p['収支'] for p in parents]); active = [r for r in rows if r['親数'] > 0]
    positive = [r for r in rows if r['収支'] > 0]; negative = [r for r in rows if r['収支'] < 0]
    best = max(rows, key=lambda r: (r['収支'], r['session']))
    top3 = sorted(rows, key=lambda r: (r['収支'], r['session']), reverse=True)[:3]
    return dict(**totals, 全場=len(rows), 活動場=len(active), 黒字場=len(positive), 赤字場=len(negative),
        無取引場=len(rows)-len(active), 赤字率=len(negative)/len(active) if active else None,
        最悪場=min(rows, key=lambda r: r['収支'])['session'], 最悪場収支=min(r['収支'] for r in rows),
        最大場損失=max([0.]+[-r['収支'] for r in rows]),
        中央値=float(np.median([r['収支'] for r in rows])),
        最大利益場=best['session'], 最大利益場除外収支=totals['収支']-best['収支'],
        上位3利益場除外収支=totals['収支']-sum(r['収支'] for r in top3),
        最大利益場の全利益場寄与=best['収支']/sum(r['収支'] for r in positive) if positive else None,
        平均赤字=float(-np.mean([r['収支'] for r in negative])) if negative else 0.,
        費用=sum(r['費用'] for r in rows), 新規枚数=sum(r['新規枚数'] for r in rows),
        勝ち枚数=sum(r['勝ち枚数'] for r in rows), 負け枚数=sum(r['負け枚数'] for r in rows),
        零枚数=sum(r['零枚数'] for r in rows), 注文件数=sum(r['注文件数'] for r in rows),
        全33黒字=len(positive) == len(rows))


def changes(base: dict, new: dict) -> dict:
    """
    機能: 基準と新政策の親を実新規cidで照合し、収支差の5寄与を検算する。
    引数: base/new(dict)は実注文から復元した完結会計。
    返り値: dictは収支変化・避け損失・逃し利益・共通出口・新入口の寄与。
    """
    before = {p['親']: p for p in base['parent']}; after = {p['親']: p for p in new['parent']}
    removed = before.keys()-after.keys(); common_keys = before.keys() & after.keys()
    avoid = sum(-before[key]['収支'] for key in removed if before[key]['収支'] < 0)
    missed = sum(before[key]['収支'] for key in removed if before[key]['収支'] > 0)
    exit_change = sum(after[key]['収支']-before[key]['収支'] for key in common_keys)
    added = sum(after[key]['収支'] for key in after.keys()-before.keys())
    delta = new['summary']['収支']-base['summary']['収支']
    assert np.isclose(delta, avoid-missed+exit_change+added, atol=1e-5, rtol=1e-12)
    assert not after.keys()-before.keys(), '停止政策から元にない新規親を生成しない'
    return dict(収支変化=delta, 避けた基準損失=avoid, 失った基準利益=missed,
        共通入口の出口変化=exit_change, 新たな入口の収支=added)


def freeze() -> None:
    """
    機能: 人工と既存実注文・気配の指紋から12政策の比較計画を金融前に作る。
    引数: なし。
    返り値: None。実金融台帳と全気配pickleの内容はまだ読み込まない。
    """
    artificial = common.read(common.HERE/'UID別場内停止の人工検査_第二固定.json')
    assert artificial['全合格'] and artificial['金融再生'] == 0
    assert artificial['実装SHA256'] == common.source_hashes()
    prepared = common.read(common.REFERENCE/'prepared/入力準備の完了.json')
    reference = common.read(common.REFERENCE/'結果.json')
    assert prepared['全合格'] and reference['全合格'] and len(prepared['全33']) == 33
    manifests = [dict(path=p.relative_to(common.ROOT).as_posix(), sha256=common.digest(p)) for p in
        (common.REFERENCE/'prepared/入力準備の完了.json', common.REFERENCE/'結果.json',
         common.HERE/'UID別場内停止の人工検査_第二固定.json',
         common.REFERENCE/'liquidation_path.py', common.REFERENCE/'specification.py')]
    ledger_hashes = {name: h for name, h in reference['台帳SHA256'].items()
                     if name.startswith('ledgers/L_D20_BBO/')}
    assert len(ledger_hashes) == 66
    proposal = dict(id=catalog.TRIAL_ID, name='元E01の当時小利益をUID別に確保してその場の再参加を止める',
        purpose='新仮説',
        question='初回5枚/10枚E01の正味清算時価に小目標を置くと、再参加と利益返上を避けて各場が安定するか。',
        change='基準L_D20_BBOの実注文接頭を保持。場内口座目標と損失予算だけを追加。UID別次気配で清算して以降停止。',
        repeat_reason='元E01の正味黒字経路が最終赤字へ戻る場を確認した。小利益目標の実約定とUID別料金を含む12政策は保存結果がない。',
        compares_to=['106_E01比較の金額残差許容統一と再開'], evidence=manifests,
        limitations=['全33場は既知。入口再生・原板再抽出・未知データの成功確認は行わない。',
            '目標へ到達しても次正常気配の実価格で悪化する。到達率は最終黒字率ではない。',
            '正味黒字経路がない場と無取引場は小利益停止で救えない。',
            '既知の類似場内停止はB4入口への始値0.1%予算であり、今回はE01の初回qty×呼値金額とUID残返済料。全歴代の完全重複不存在は断言しない。'],
        spec=dict(
            entry=dict(基準=catalog.BASELINE, 条件='元GU・有利0.2ATR指値の保存実新規をそのまま使用',
                初回={'TOPIX': 5, 'NK225': 10}, 将来出口='新規テンプレートへ使用しない'),
            management=dict(判定='全実fillを当行まで適用後、正常bid/ask清算時価から残UID別返済料を引く',
                条件=catalog.CONFIGS, 基準と同経路='最初の当時閾値到達まで全注文・部分返済を保持',
                到達後='未約定指値と将来返済を取消し、以後新規なし'),
            exit=dict(利益目標呼値=[1, 2, 4], 損失予算呼値=[4, 8, 16], 損失予算無制限='比較に含む',
                閾値円='呼値数×初回枚数×商品円倍率', 約定='判断行より後の最初の正常気配で残UIDごとに別返済注文',
                既全返済='当行実返済を保持して追加注文なし', 期限='元場内返済を保持。次正常気配がない保有は失敗'),
            allocation=dict(初回={'TOPIX': 5, 'NK225': 10}, 片方向上限={'TOPIX': 10, 'NK225': 20},
                条件配分='12条件独立比較。全量10/20章とは数量を区別'),
            costs=dict(片道料金={'TOPIXmini': 41.8, 'NK225micro': 11.},
                課金='実注文ごとfloor(約定qty×片道料金)。新規全額をその時点で控除',
                予約返済料='FIFO部分返済後の各実新規UID残qtyへ個別floor。UID間合算しない'),
            execution=dict(基準='保存正常気配の買ask/売bid。原seq整数と原価格時計を保持',
                同行順序='元当行実fill・部分返済後に口座清算判断。以後元fillを削除し次正常気配でUID別清算',
                不正気配='新判断と返済を行わず、時価だけ直前正常気配を保持。未来値補完しない'),
            data=dict(sessions=prepared['全33'], input_manifests=manifests,
                quotes=dict(path='work/wave_v106/e01_reference/prepared/quotes.pkl',
                    sha256=prepared['全気配SHA256']), baseline_ledgers=ledger_hashes,
                選定='12目標予算を結果前固定。基準の売買・終端損益を入口へ逆流させない'),
            implementation=common.source_hashes()))
    assert common.read(common.HERE/'条件12.json')['configs'] == catalog.CONFIGS
    common.write(common.HERE/'試行計画_第二固定.json', proposal)
    common.write(common.HERE/'事前固定_第二固定.json', dict(全合格=True, 実装SHA256=common.source_hashes(),
        計画SHA256=common.digest(common.HERE/'試行計画_第二固定.json'), 金融再生=0, API=0, 原本再読取=0,
        気配読取予定=1, 基準台帳読取予定=66, 正式口座予定=792))
    print('12政策の計画完成。根の登録通知前は金融未実行。', flush=True)


def check_baseline(old: dict, fresh: dict) -> None:
    """
    機能: 実注文のみの復元会計を、保存された基準の全行と終端へ照合する。
    引数: old/fresh(dict)は旧保存会計と新しい独立再会計。
    返り値: None。元玉の未来返済を新政策条件に使わない。
    """
    np.testing.assert_array_equal(fresh['orders'], old['orders'])
    np.testing.assert_array_equal(fresh['order_fees'], old['order_fees'])
    np.testing.assert_allclose(fresh['equity_yen'], old['equity_yen'], atol=1e-5, rtol=1e-12)
    for key in ('利益', '損失', '収支', '費用', '親数', '勝ち親', '負け親', '新規枚数', '勝ち枚数', '負け枚数'):
        assert np.isclose(fresh['summary'][key], old['summary'][key], atol=1e-5, rtol=1e-12), key
    assert {p['親'] for p in fresh['parent']} == {p['親'] for p in old['parent']}
    reference.check_reserved(old, fresh, old['key'][1])


def control_detail(base: dict, new: dict, quotes: dict) -> dict:
    """
    機能: 停止判断と実UID返済価格を診断用に簡潔に残す。
    引数: base/new/quotes(dict)は実注文復元と当時価格。
    返り値: dictは停止の時刻・基準親との差。数値を入口の選定には使わない。
    """
    detail = dict(new['control'])
    if not detail['発動']:
        return detail
    decision = detail['判断行']; fill_row = detail['返済行']
    detail['判断bidask'] = [float(quotes['bid'][decision]), float(quotes['ask'][decision])]
    detail['返済bidask'] = [float(quotes['bid'][fill_row]), float(quotes['ask'][fill_row])]
    detail['残UID返済'] = []
    for index, order in enumerate(new['orders']):
        target = int(new['exit_target_uids'][index])
        if target < 0:
            continue
        uid = next(u for u in new['uid_accounts'] if u['uid'] == target)
        old_parent = next(p for p in base['parent'] if p['親'] == uid['親'])
        old_last = old_parent['最終返済行']
        detail['残UID返済'].append(dict(uid=target, 親=uid['親'], 枚数=int(order[4]),
            返済方向=int(order[3]), 返済価格=float(order[5]), 返済料金=int(new['order_fees'][index]),
            新規価格=uid['新規価格'], 新規原seq=int(quotes['seq'][uid['新規行']]),
            新規価格時計=float(quotes['time_s'][uid['新規行']]), UID収支=uid['収支'],
            元親収支=old_parent['収支'], 元親最終価格時計=float(quotes['time_s'][old_last])))
    return detail


def run(registry) -> None:
    """
    機能: 登録後だけ全66基準を1読取し、12政策の全行会計と診断を保存する。
    引数: registry(Path)は根担当が登録した試行正本。
    返り値: None。元paper/API/生板を一切使わず正式再実行を拒否する。
    """
    started = time.monotonic(); target = common.HERE/'finance/結果.json'
    assert not target.exists() and not (common.HERE/'finance/失敗.json').exists()
    plan = common.read(common.HERE/'試行計画_第二固定.json'); fixed = common.read(common.HERE/'事前固定_第二固定.json')
    assert plan['id'] == catalog.TRIAL_ID
    assert any(item['id'] == catalog.TRIAL_ID for item in common.read(registry)['trials'])
    assert fixed['実装SHA256'] == common.source_hashes() == plan['spec']['implementation']
    assert common.digest(common.HERE/'試行計画_第二固定.json') == fixed['計画SHA256']
    for manifest in plan['spec']['data']['input_manifests']:
        assert common.digest(common.ROOT/manifest['path']) == manifest['sha256']
    quotes_spec = plan['spec']['data']['quotes']; quote_path = common.ROOT/quotes_spec['path']
    assert common.digest(quote_path) == quotes_spec['sha256']
    common.write(common.HERE/'finance/開始.json', dict(全合格=True, 登録通知後=True,
        計画SHA256=fixed['計画SHA256'], 実装SHA256=fixed['実装SHA256'], 時刻=time.time()))
    quotes = common.read(quote_path); sessions = plan['spec']['data']['sessions']
    assert set(quotes) == {(s, p) for s in sessions for p in ('TOPIX', 'NK225')}
    rows, parents, uids = {}, {}, {}; ledger_index = {}; account_checks = []
    controls, contribution = {}, {}
    all_ids = [catalog.BASELINE]+[c['id'] for c in catalog.CONFIGS]
    for ident in all_ids:
        rows[ident], parents[ident], uids[ident] = [], [], []
        controls[ident], contribution[ident] = [], []
    try:
        for session in sessions:
            for symbol in ('TOPIX', 'NK225'):
                relative = f'ledgers/{catalog.BASELINE}/{session}_{symbol}.pkl.gz'
                path = common.REFERENCE/relative
                assert common.digest(path) == plan['spec']['data']['baseline_ledgers'][relative]
                old = common.read(path); q = quotes[(session, symbol)]
                assert old['key'] == (session, symbol) and old['case']['id'] == catalog.BASELINE
                base = core.reconstruct((session, symbol), old['orders'], old['order_uids'], q)
                check_baseline(old, base)
                rows[catalog.BASELINE].append(base['summary'])
                parents[catalog.BASELINE].extend(dict(**p, session=session, symbol=symbol) for p in base['parent'])
                uids[catalog.BASELINE].extend(dict(**u, session=session, symbol=symbol) for u in base['uid_accounts'])
                del old
                for config in catalog.CONFIGS:
                    ident = config['id']; new = core.apply_policy(base, q, config)
                    new['case'] = config; new['基準注文SHA256'] = plan['spec']['data']['baseline_ledgers'][relative]
                    new['気配SHA256'] = quotes_spec['sha256']
                    rows[ident].append(new['summary'])
                    parents[ident].extend(dict(**p, session=session, symbol=symbol) for p in new['parent'])
                    uids[ident].extend(dict(**u, session=session, symbol=symbol) for u in new['uid_accounts'])
                    delta = dict(session=session, symbol=symbol, **changes(base, new)); contribution[ident].append(delta)
                    detail = dict(session=session, symbol=symbol, **control_detail(base, new, q))
                    controls[ident].append(detail)
                    destination = common.HERE/f'finance/ledgers/{ident}/{session}_{symbol}.pkl.gz'
                    common.write(destination, new)
                    ledger_index.setdefault(ident, []).append(dict(session=session, symbol=symbol,
                        path=destination.relative_to(common.ROOT).as_posix(), SHA256=common.digest(destination)))
                    account_checks.append(dict(id=ident, session=session, symbol=symbol, 全合格=True,
                        元実注文接頭不変=True, 次正常気配UID別清算=True))
                    del new
                print(f'{session} {symbol} 基準会計一致・12政策完了', flush=True)
                del base
                gc.collect()
        assert len(account_checks) == 792
        # ----------------------------------------
        results = {}
        for ident in all_ids:
            products = {}
            for symbol in ('TOPIX', 'NK225'):
                products[symbol] = aggregate([r for r in rows[ident] if r['symbol'] == symbol],
                    [p for p in parents[ident] if p['symbol'] == symbol], sessions)
                products[symbol]['実UID会計'] = core.metric([u['収支'] for u in uids[ident] if u['symbol'] == symbol])
            results[ident] = dict(rows=rows[ident], symbols=products,
                ledgers=ledger_index.get(ident, []))
        diagnosis = {ident: {symbol: {field: sum(r[field] for r in contribution[ident] if r['symbol'] == symbol)
            for field in ('収支変化', '避けた基準損失', '失った基準利益', '共通入口の出口変化', '新たな入口の収支')}
            for symbol in ('TOPIX', 'NK225')} for ident in contribution if ident != catalog.BASELINE}
        red3 = {symbol: [r['session'] for r in sorted([r for r in rows[catalog.BASELINE]
            if r['symbol'] == symbol and r['収支'] < 0], key=lambda r: r['収支'])[:3]] for symbol in ('TOPIX', 'NK225')}
        detailed = {ident: [dict(**detail, 寄与=next(r for r in contribution[ident]
            if r['session'] == detail['session'] and r['symbol'] == detail['symbol']))
            for detail in controls[ident] if detail['session'] in red3[detail['symbol']]]
            for ident in controls if ident != catalog.BASELINE}
        assert common.source_hashes() == fixed['実装SHA256']
        common.write(target, dict(全合格=True, sessions=sessions, configs=catalog.CONFIGS, baseline=catalog.BASELINE,
            results=results, diagnosis=diagnosis, 発動=controls, 会計検査=account_checks,
            仕様='初回TOPIXmini5枚/NKmicro10枚E01の保存実注文接頭。全33既知比較。',
            基準口座読取=66, 気配pickle読取=1, 新政策口座=792, 元paper再生=0, 原本再読取=0, API=0,
            旧残返済料金全行照合=66, 旧料金四定数同値=True,
            実装開始終端一致=True, 実装SHA256=fixed['実装SHA256'], 計画SHA256=fixed['計画SHA256'],
            経過秒=time.monotonic()-started))
        common.write(common.HERE/'finance/三赤字場のUID清算と寄与.json', dict(全合格=True,
            基準赤字上位3=red3, 選び方='実行後の原因説明。条件/閾値は変更しない', cases=detailed,
            全寄与=diagnosis, 結果SHA256=common.digest(target)))
        print('全33・792政策口座のUID別場内停止を完了', flush=True)
    except Exception:
        common.write(common.HERE/'finance/失敗.json', dict(全合格=False, 原因=traceback.format_exc(),
            完成口座=len(account_checks), 自動再実行=False, 既完成台帳保持=True))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='旧E01の小利益目標とUID別場内停止')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--root-trial-registered', action='store_true')
    parser.add_argument('--registry', type=lambda p: common.ROOT/p,
        default=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args = parser.parse_args()
    if args.freeze:
        assert not args.root_trial_registered
        freeze()
    else:
        assert args.root_trial_registered, '根の試行登録通知前は正式金融を実行しない'
        run(args.registry)
