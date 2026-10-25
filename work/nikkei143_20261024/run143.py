"""日経F1の基本枠改修と、固定水準エピソードの独立運用を登録後に再生する。"""

import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np
import common143 as shared

HERE, ROOT, OLD, previous, prior = shared.HERE, shared.ROOT, shared.OLD, shared.previous, shared.prior


def register():
    """
    機能: 入口・管理・出口・配分・費用・執行・資料・実装を金融再生前に固定する。
    引数: なし。
    返り値: None。既存試行照合を通し、同一仕様の重複と参照元を記録する。
    """
    import core_overlay143 as overlay
    import episode143 as episode
    plan = shared.read(OLD / '第三巡計画142.json')
    plan.update(id='143_日経特化_自己支持破綻と固定水準エピソードの並行運用',
                name='日経の上昇下落偏りと03時以降除外の参加改善', purpose='条件比較',
                question='日経自身の反証を元担当へ適用し、固定水準の新しい利益源を加えると、利益損失比と活動を両立できるか。',
                change='二市場一致待ちの失敗を対象銘柄の支持喪失で区別。基本枠の新規拒否・全返済・一度半減を比較。新担当は固定帯・極値・新エピソードを用い、短期符号だけの出入りを止める。',
                repeat_reason='00142の自己逆行見逃し、逆流の入口閾値、巡回の気配差損失と保有不足、F1の夜上昇側の偏りを根拠に、日経特化の新基準で検証する。',
                compares_to=['142_状況判断と売買を分離した時間軸原板リスク切替',
                             '142_第三巡_短期往復の費用分解と中期支持状態の維持'])
    plan['configs'] = dict(overlay=overlay.configurations(), episode=episode.configurations(),
        portfolios={'Fxx': 'Oxx基本枠5＋保存追加5', 'Pxx': '基本枠5＋Exx最大5',
                    'Txx': '基本枠5＋追加最大3を再生＋Exx最大2を再生'})
    plan['spec']['entry'] = {
        '基本枠': '昼B5、夜Z04の元通知。O00無変更、他条件は当時の自己120秒又は二市場反証による拒否。全完結後だけ新しい元通知を利用する。',
        '追加枠': '昼G02、夜C13を維持。三枠対照では最大3へ変えて全新規・部分返済・追撃を再生する。',
        '新担当': '公開済み20/40/60分帯を準備時固定し、突破失敗後の回復、突破支持の再確認、低効率帯端からの反発。再参加は新しい境界又は新しい外側極値を要求。',
        '不足資料': '未確定足、同時計相手後続行、後日のセッション方向を新規判断に用いない。'}
    plan['spec']['management'] = {
        '基本枠': '自己MA20の反対側と120秒逆流、自己板反証を組み合わせ維持・半減・全返済。元の予約済通知優先。途中退出後の再参加は元通知に限定。',
        '新担当': '固定した無効価格を保険とし、中心回帰で部分返済。残玉を幅のある追尾で保護し、利益保護後だけ初回損失予算内の追加。',
        '時刻': '昼夜は別評価。新担当は場内全時刻を対象とし、米国寄付前後静観の一条件を別比較。03時以降は活動評価から除外するだけで損益を捨てない。'}
    plan['spec']['exit'] = {
        '優先': '既発注の新規/返済を先に成立。固定停止、追尾、場末清算。判断行の価格で約定しない。',
        '終端': '元資料limitの昼15:35、夜05:50に清算判断、次正常気配で全返済。終端未清算はエラー。',
        '後続': '保存親の将来損益・退出結果で入口を選ばない。新担当は全後続の準備・新規・返済も再生する。'}
    plan['spec']['allocation'] = {'商品': 'NK225mini', '片方向上限': 10,
        '二枠': '基本5＋追加5、又は基本5＋新担当5', '三枠': '基本5＋既存追加3＋新担当2',
        '貸借': '各枠固定・空き枠を他へ貸さない。役割別親IDとUIDを分離し反対玉も独立返済。'}
    plan['spec']['data']['評価'] = '全50場は既知開発。始値・終了前6分以内の有効Lastの方向は会計後の集計にのみ接続。全50平均保有率はDay420分/Night600分。'
    plan['spec']['data']['目安'] = '手数料後の完結親利益/損失2以上、深夜除外平均保有50%程度。赤字数・通常損失・上位3黒字除外・方向別PFと損失を別々に示す。各場新規0は完成候補にしない。'
    plan['spec']['data']['input_manifests'].extend([prior.ref(HERE / 'F1始終値方向と深夜除外保有率143.json'),
        prior.ref(OLD / '結果142.json'), prior.ref(HERE / '既存夜間候補の米国前後分解143.json')])
    for path in (HERE / 'common143.py', HERE / 'run143.py', HERE / 'core_overlay143.py', HERE / 'episode143.py'):
        item = prior.ref(path)
        plan['spec']['implementation'][item['path']] = item['sha256']
    plan['evidence'] = [prior.ref(OLD / 'F1_1013夜の損失診断.json'), prior.ref(OLD / 'P04損失診断と第三巡への反証142.md'),
                        prior.ref(HERE / '敵対的検証質問台帳143.md')]
    plan = json.loads(json.dumps(plan, ensure_ascii=False))
    shared.save(HERE / '第一巡計画143.json', plan)
    manager = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec = importlib.util.spec_from_file_location('manager143', manager)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    checked = mod.check(plan)
    shared.save(HERE / '第一巡照合143.json', dict(proposal_complete=checked['proposal_complete'],
        issues=checked['提案不完全理由'], matches=[{k: v for k, v in x.items() if k in ('id', 'kind', 'name')} for x in checked['matches']]))
    assert checked['proposal_complete']
    mod.check = lambda proposal: checked
    saved = mod.store_trial(plan)
    shared.save(HERE / '第一巡登録143.json', dict(returncode=0, id=saved['id'], plan=prior.ref(HERE / '第一巡計画143.json')))
    print('第一巡の事前登録完了', flush=True)


def addon_config(scene, maximum):
    """
    機能: 元の昼G02・夜C13の判断を維持し、数量枠だけを事前の上限へ変更する。
    引数: scene(str)、maximum(int)は場名と最大枚数。
    返り値: dictはactive_trader142の設定。整数配分を単純な損益倍率にしない。
    """
    from policies142 import active_configs
    changes = dict(entry_guard=2) if scene.endswith('_Day') else active_configs()[12]['changes']
    return dict(previous.first.original.configurations()[35], **changes, maximum=maximum)


def run():
    """
    機能: 凍結仕様を全50場へ因果順で再生し、単体・二枠・三枠の全損益を保存する。
    引数: なし。
    返り値: None。保存済み場は再計算せず、途中から再開できる。
    """
    import core_overlay143 as overlay
    import episode143 as episode
    import active_trader142 as active
    plan = shared.read(HERE / '第一巡計画143.json')
    assert shared.read(HERE / '第一巡登録143.json')['returncode'] == 0
    for path, sha in plan['spec']['implementation'].items():
        assert prior.ref(ROOT / path)['sha256'] == sha, path
    packets, cache, labels = shared.material()
    rows, files = [], []
    for item in packets:
        scene = item['session']
        target = HERE / 'round1/results' / f'{scene}.json'
        if target.exists():
            saved = shared.read(target)
            rows.extend(saved['rows'])
            files.extend(saved['cache'])
            continue
        packet = shared.packet_from(item)
        ready, _, _, hist15 = previous.prepared(packet)
        data = ready['NK225']
        base, addon, f1 = shared.sources(scene, cache)
        arrays = {'B0': base, 'F1': f1, 'A5': addon}
        traces = {}
        replay5, _, _ = active.replay(data, addon_config(scene, 5))
        check = addon.copy()
        if len(check):
            check[:, 2] -= 3_000_000
        assert np.array_equal(check, replay5), (scene, '既存追加の無変更同値')
        addon3, _, trace = active.replay(data, addon_config(scene, 3))
        arrays['A3'] = addon3
        traces['A3'] = trace
        for config in plan['configs']['overlay']:
            method = config['id']
            orders, trace = overlay.replay(data, base, hist15[scene, 'NK225'], config)
            if method == 'O00':
                assert np.array_equal(orders, base)
            arrays[method] = orders
            arrays['F' + method[1:]] = shared.merge(orders, addon)
            traces[method] = trace
        histories = {}
        for config in plan['configs']['episode']:
            window = config['window']
            if window not in histories:
                histories[window] = previous.first.original.history(data['ready']['time_s'], data['features'][:, 10], data['ready']['start'], window)
            orders, trace = episode.replay(data, histories[window], config)
            method = config['id']
            arrays[method] = orders
            arrays['P' + method[1:]] = shared.merge(base, orders)
            traces[method] = trace
            small_config = dict(config, maximum=2, initial=min(config['initial'], 2))
            small, small_trace = episode.replay(data, histories[window], small_config)
            arrays['S' + method[1:]] = small
            arrays['T' + method[1:]] = shared.merge(base, addon3, small)
            traces['S' + method[1:]] = small_trace
        # ----------------------------------------
        # 最終方向は全売買の生成が終わってから会計にのみ接続する。
        scene_rows = [shared.account(orders, packet, method, labels[scene]) for method, orders in arrays.items()]
        dest = HERE / 'round1/measurement' / f'NK225_{scene}.npz'
        dest.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(dest, **arrays)
        record = dict(session=scene, symbol='NK225', **prior.ref(dest))
        dest = HERE / 'round1/traces' / f'NK225_{scene}.npz'
        dest.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(dest, **traces)
        shared.save(target, dict(rows=scene_rows, cache=[record], old_addon_unchanged=True))
        rows.extend(scene_rows)
        files.append(record)
        print(scene, '日経専用の第一巡完了', flush=True)
    shared.save(HERE / '第一巡結果143.json', dict(rows=rows, cache=files, plan=prior.ref(HERE / '第一巡計画143.json'), API=0, real_orders=0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['register', 'run'])
    args = parser.parse_args()
    register() if args.stage == 'register' else run()
