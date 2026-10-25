"""確定利益を予算とする残玉一枚の維持を、元の再参加機会も含め比較する。"""

import argparse
import importlib.util
from pathlib import Path
import numpy as np
import common143 as shared

HERE, ROOT, prior = shared.HERE, shared.ROOT, shared.prior


def register():
    """
    機能: 利益が確定した後だけ残す一枚の条件を、新しい金融再生前に凍結する。
    引数: なし。
    返り値: None。入口の新造や赤字担当を使った保有率稼ぎとは分けて登録する。
    """
    import profit_residual143 as residual
    plan = shared.read(HERE/'第二巡計画143.json')
    plan.update(id='143_第三巡_確定利益内の残玉と後続機会の比較',
        name='確定利益で一枚を残す追尾と参加機会の検証', purpose='条件比較',
        question='全玉を一律に長く持たず、既に確定する他玉利益で一枚だけを残せば、利益の質と有効保有を両立できるか。',
        change='元の利確追尾全返済通知で最古の利益玉一枚だけを残す。残玉以外の実現純益を確認し、その50%/100%までの損失予算と2R/3R追尾を比較。残玉中の後続親は見送り、その失う利益も数える。',
        repeat_reason='全玉の追尾幅を拡大したR11は夜間保有20%へ伸びるが上位3黒字除外赤字。日中L11は単独赤字のため配分だけで保有時間を稼ぐ案は不採用。利益で賄える残玉の独立した機構を検証する。',
        compares_to=['143_第二巡_固定入口支持と旧反発入口の機構別復元'])
    plan['configs'] = dict(residual=residual.configurations(), portfolios={
        'CB': '元基本B0へ残玉化・最大5', 'CG': '昼O17/夜O02へ残玉化・最大5',
        'CA': '昼E01/夜R00へ残玉化・最大5', 'CS': '昼S01/夜L00へ残玉化・最大2',
        'PP': 'CB5＋CA5', 'PG': 'CG5＋CA5', 'TT': 'CB5＋旧追加A3最大3＋CS2',
        'TG': 'CG5＋旧追加A3最大3＋CS2', 'FF': 'CB5＋旧追加A5最大5'})
    plan['spec']['entry'] = {
        '元候補': '第一/二巡で生成済みの当時発注通知を因果的な仮想候補として使う。判断行以前に通知を見ない。元の未来返済値・完結損益を入口に使わない。',
        '保有中': '残玉がある間に来た次親は、その初回通知で見送り、後から途中参加しない。既存の保有中に未来の勝ち親を見て退出しない。',
        '理由': '源単体は昼E01、夜R00に分ける。逆の時間帯で赤字だった源を同じまま運転しない。ただし選択は既知50場での開発であり未見成績ではない。'}
    plan['spec']['management'] = {
        '残す資格': '利確追尾の全返済通知のみ。正常な当時気配で最古の利益玉1枚を除く清算見込純益が正か確認する。全玉収支が正でも他玉実現純益が負なら残さない。',
        '資金': '他玉が次正常気配で返済した後、全新規費用を含む実現純益で予算を確定。不足なら残玉もその後の次正常行で返済。含み益を確定利益と呼ばない。',
        '幅': 'Rは初回発注判断で公開済みATRと8呼値の大きい値で固定。元準備時停止幅ではない。残玉化時点から2R/3R幅を追尾し、利益予算の床は下げない。'}
    plan['spec']['exit'] = {
        '残玉': '確定純益の50%/100%予算の価格床又は2R/3R追尾で返済判断、次正常BBO約定。飛び越えによる予算超過は消さない。',
        '対象外': '強制清算、固定損切り、支持破綻、静観の全返済を残玉化しない。理由2/70/1437の利確追尾全返済だけを対象とする。',
        '時刻': '元の昼15:35・夜05:50場末清算を維持。新しい残玉は米国寄付前後15分に全返済する。元E01等の通常玉に新しい静観は加えない。03～06時は保有率集計からのみ除外。'}
    plan['spec']['allocation'] = dict(商品='NK225mini', 片方向上限=10, 独立枠=plan['configs']['portfolios'], 貸借='なし。残玉を含む実同時保有を監査する。')
    plan['spec']['data']['第三巡検査'] = '全50場の会計と、10/22Day・10/21Nightの未来prefix/上下鏡像/無変更同値/次正常BBO/全返済。元利確後の追加保有利益と見送った後続親を区別。'
    for path in (HERE/'第一巡結果143.json', HERE/'第二巡結果143.json'):
        plan['spec']['data']['input_manifests'].append(prior.ref(path))
    for path in (Path(__file__), HERE/'profit_residual143.py', HERE/'common143.py'):
        item = prior.ref(path)
        plan['spec']['implementation'][item['path']] = item['sha256']
    plan['evidence'] = [prior.ref(HERE/name) for name in ('第一巡集計143.json', '第二巡集計143.json', '結論反証143.md')]
    shared.save(HERE/'第三巡計画143.json', plan)
    manager = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec = importlib.util.spec_from_file_location('manager143r3', manager)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    checked = mod.check(plan)
    shared.save(HERE/'第三巡照合143.json', dict(proposal_complete=checked['proposal_complete'],
        issues=checked['提案不完全理由'], matches=[{k:v for k,v in x.items() if k in ('id','kind','name')} for x in checked['matches']]))
    assert checked['proposal_complete']
    mod.check = lambda proposal:checked
    saved = mod.store_trial(plan)
    shared.save(HERE/'第三巡登録143.json', dict(returncode=0, id=saved['id'], plan=prior.ref(HERE/'第三巡計画143.json')))
    print('第三巡の事前登録完了', flush=True)


def sources(scene, first, second):
    """
    機能: 二巡の同じ原入力から源別の保存注文を取り、場別規則だけで接続する。
    引数: scene(str)、first/second(dict)は場名と保存目録。
    返り値: tuple[dict,ndarray,ndarray]は四種の源、旧追加3枚・5枚。
    """
    archives = []
    for cache in (first, second):
        item = cache[scene]
        path = ROOT/item['path']
        assert prior.ref(path)['sha256'] == item['sha256']
        with np.load(path) as data:
            archives.append({key:data[key] for key in data.files})
    a, b = archives
    day = scene.endswith('_Day')
    return dict(CB=a['B0'], CG=b['O17'] if day else a['O02'],
        CA=a['E01'] if day else b['R00'], CS=a['S01'] if day else b['L00']), a['A3'], a['A5']


def run():
    """
    機能: 残玉保有・後続見送りを含め全50場を再生して各固定配分を保存する。
    引数: なし。
    返り値: None。残玉の親IDを変えず元の費用を含む一連の売買として会計する。
    """
    import profit_residual143 as residual
    plan = shared.read(HERE/'第三巡計画143.json')
    assert shared.read(HERE/'第三巡登録143.json')['returncode'] == 0
    for path, sha in plan['spec']['implementation'].items():
        assert prior.ref(ROOT/path)['sha256'] == sha, path
    packets, _, labels = shared.material()
    first = {x['session']:x for x in shared.read(HERE/'第一巡結果143.json')['cache']}
    second = {x['session']:x for x in shared.read(HERE/'第二巡結果143.json')['cache']}
    rows, files = [], []
    for item in packets:
        scene = item['session']
        target = HERE/'round3/results'/f'{scene}.json'
        if target.exists():
            saved = shared.read(target); rows.extend(saved['rows']); files.extend(saved['cache']); continue
        packet = shared.packet_from(item)
        key = (scene, 'NK225')
        data = dict(ready=packet['inputs'][key], quotes=packet['quotes'][key])
        source, addon3, addon5 = sources(scene, first, second)
        arrays, traces = {}, {}
        for config in plan['configs']['residual']:
            suffix = config['id'][1:]
            for name, baseline in source.items():
                method = name+suffix
                if config['id'] == 'H00':
                    orders, trace = baseline.copy(), np.empty((0,len(residual.TRACE_COLUMNS)))
                else:
                    orders, trace = residual.replay(data, baseline, config)
                arrays[method], traces[method] = orders, trace
            cb, cg, ca, cs = [arrays[x+suffix] for x in ('CB','CG','CA','CS')]
            arrays['PP'+suffix] = shared.merge(cb, ca)
            arrays['PG'+suffix] = shared.merge(cg, ca)
            arrays['TT'+suffix] = shared.merge(cb, addon3, cs)
            arrays['TG'+suffix] = shared.merge(cg, addon3, cs)
            arrays['FF'+suffix] = shared.merge(cb, addon5)
        accounts = [shared.account(o, packet, m, labels[scene]) for m,o in arrays.items()]
        dest = HERE/'round3/measurement'/f'NK225_{scene}.npz'
        dest.parent.mkdir(parents=True, exist_ok=True); np.savez_compressed(dest, **arrays)
        record = dict(session=scene, symbol='NK225', **prior.ref(dest))
        dest = HERE/'round3/traces'/f'NK225_{scene}.npz'
        dest.parent.mkdir(parents=True, exist_ok=True); np.savez_compressed(dest, **traces)
        shared.save(target, dict(rows=accounts, cache=[record]))
        rows.extend(accounts); files.append(record)
        print(scene, '確定利益内の残玉比較完了', flush=True)
    shared.save(HERE/'第三巡結果143.json', dict(rows=rows, cache=files, plan=prior.ref(HERE/'第三巡計画143.json'), API=0, real_orders=0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=('register','run'))
    register() if parser.parse_args().stage == 'register' else run()
