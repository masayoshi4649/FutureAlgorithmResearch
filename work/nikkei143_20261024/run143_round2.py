"""入口を復元した一機構比較と、固定支持の出口を登録後に全場で比較する。"""

import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np
import common143 as shared

HERE, ROOT, previous, prior = shared.HERE, shared.ROOT, shared.previous, shared.prior
ORIGINAL = ROOT / 'work/aggressive140_20261024'


def register():
    """
    機能: 第一巡の具体的な失敗を根拠に第二巡の八項目仕様と実装を凍結登録する。
    引数: なし。
    返り値: None。保存済み対照は再利用し、新比較を未見検証と呼ばない。
    """
    import core_overlay_v2_143 as overlay
    plan = shared.read(HERE / '第一巡計画143.json')
    plan.update(id='143_第二巡_固定入口支持と旧反発入口の機構別復元',
        name='移動支持の早退と複合変更を反証した後の比較', purpose='条件比較',
        question='入口時支持と現在中期を区別すると勝ちの早退を減らせるか。真正A34/A36から一機構ずつ変更すれば夜間の利益源と参加を保てるか。',
        change='基本枠は入口時MA20固定と現在20分逆流を追加。独立枠は旧A34/A36の入口と全返済を復元し、相手支持・静観・追尾を個別比較。第一巡の中心部分返済と直後追撃は採用しない。',
        repeat_reason='O03は10/22昼に移動したMAを跨いだだけで374000円の勝ちを失った。E08は旧勝ち入口を除き、中心利確直後の再追加も発生した。元の母集団から変更を分離して評価し直す。',
        compares_to=['143_日経特化_自己支持破綻と固定水準エピソードの並行運用',
                     '140_先着損失の診断と独立枠と整数ペア'])
    configs = shared.read(HERE / 'episode_restore_configs143.json')
    original_configs = {c['id']:c for c in previous.first.original.configurations()}
    for config in configs:
        if config.get('reuse_method'):
            original_config = original_configs[config['reuse_method']]
            for key, value in original_config.items():
                if key not in ('id', 'name'):
                    assert config[key] == value, (config['id'], key, '旧保存の完全一致資格')
    plan['configs'] = dict(overlay=overlay.configurations(), restored=configs,
        portfolios={'R': '復元担当最大5枚', 'L': '復元担当初回1・最大2枚',
            'U': '基本B0最大5＋R最大5', 'V': '昼O01/夜O02基本5＋R最大5',
            'W': '基本B0最大5＋旧追加A3最大3＋L最大2',
            'Y': '昼O01/夜O02基本5＋旧追加A3最大3＋L最大2',
            'F12以降': 'O12以降の基本枠最大5＋保存旧追加最大5'})
    plan['spec']['entry'] = {
        '基本': '元B5/Z04の発注判断だけ。O16は旧O02、O17は旧O01の入口除外を併用。日時・最終方向・親の未来損益は不使用。',
        '復元': '真正active140_v2の公開40分帯。A34は低効率帯端から反発、A36は効率により突破後の戻りと帯反発を選択。設定JSONで一機構差を固定。',
        '再利用': '旧140第二巡の同設定同入力の注文は指紋を確認して再利用する。旧未保存条件と変更条件だけ新生成。',
        '小口': '最大2枠は初回1へ変更し、固定リスク予算も初回枚数とともに縮める。損益の単純な倍率換算ではない。'}
    plan['spec']['management'] = {
        '固定支持': '基本親の初回発注判断時MA20を固定。価格が固定水準の逆側0.1R、自己120秒と現在自己20分逆向きを持続確認。板又は相手20分確認、進捗半減を別条件とする。未知MAは独自退出しない。',
        '復元': '旧Rは準備時の公開ATR・帯半幅・八呼値の最大。追撃は初回から0.5R刻み、30秒間隔、初回枚数×40呼値の固定予算以内。初回実停止損失と同義ではない。',
        '途中利確': '復元担当には中心での部分返済なし。全返済後120秒、2連敗後900秒休止を維持。',
        '仮説範囲': '固定入口支持は含み損での破綻を扱う比較であり、利益後の保護を全て解く仮説ではない。'}
    plan['spec']['exit'] = {
        '基本': '元の発注済通知を優先し、独自判断は次正常行。独自半減後の元返済を実残玉比へ縮小し、将来追加を止める。',
        '復元': '元固定stop・利益トレーリング・US静観・場末の全返済。変更は設定JSONに記載した箇所のみ。',
        '場末': '昼15:35・夜05:50に全返済判断。03時での強制返済は追加せず、03～06時の損益も全額計上。'}
    plan['spec']['allocation'] = {'商品': 'NK225mini', '片方向上限': 10,
        '独立枠': plan['configs']['portfolios'], '貸借': '予約枠は貸し借りせず全注文を独立生成後に時系列合成。'}
    plan['spec']['data']['第二巡評価'] = '全50場は既知開発。昼夜・最終Last代理の上下・売買別を評価。平均保有率の分母は昼420/夜600分、無取引を勝ちにしない。'
    plan['spec']['data']['検査'] = '保存対照同値、未来prefix不変、上下鏡像、次正常気配、費用とUID数量、全返済。10/22Day・10/21Nightで全新条件と小口条件を機械監査し、旧A34/A36の保存との同値も確認。組合せは実保有の時間和集合で評価。'
    for path in (HERE/'第一巡結果143.json', ORIGINAL/'round2_known/結果140.json', ORIGINAL/'round2_new/結果140.json'):
        plan['spec']['data']['input_manifests'].append(prior.ref(path))
    for path in (Path(__file__), HERE/'core_overlay_v2_143.py', HERE/'episode_restore_configs143.json',
                 HERE/'common143.py', ORIGINAL/'active140_v2.py'):
        item = prior.ref(path)
        plan['spec']['implementation'][item['path']] = item['sha256']
    plan['evidence'] = [prior.ref(HERE/name) for name in ('結論反証143.md', 'E08が旧A34より悪化した理由143.md', 'O系の勝敗変化143.json')]
    shared.save(HERE/'第二巡計画143.json', plan)
    manager = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec = importlib.util.spec_from_file_location('manager143r2', manager)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    checked = mod.check(plan)
    shared.save(HERE/'第二巡照合143.json', dict(proposal_complete=checked['proposal_complete'],
        issues=checked['提案不完全理由'], matches=[{k:v for k,v in x.items() if k in ('id','kind','name')} for x in checked['matches']]))
    assert checked['proposal_complete']
    mod.check = lambda proposal: checked
    saved = mod.store_trial(plan)
    shared.save(HERE/'第二巡登録143.json', dict(returncode=0, id=saved['id'], plan=prior.ref(HERE/'第二巡計画143.json')))
    print('第二巡の事前登録完了', flush=True)


def old_orders(scene, method, cache):
    """
    機能: 指紋の一致する旧第二巡から、同一設定の注文があれば再利用する。
    引数: scene/method(str)、cache(dict)は場名・旧手法名・保存目録。
    返り値: ndarray又はNone。同名が未保存なら新生成が必要となる。
    """
    item = cache.get(scene)
    if item is None:
        return None
    path = ROOT/item['path']
    assert prior.ref(path)['sha256'] == item['sha256']
    with np.load(path) as data:
        return data[method].copy() if method in data.files else None


def run():
    """
    機能: 凍結した復元比較・固定支持と三種類の配分を全50場で再生する。
    引数: なし。
    返り値: None。保存済み場を再計算せず、全約定と会計を個別に保存する。
    """
    import core_overlay_v2_143 as overlay
    original = previous.first.original
    plan = shared.read(HERE/'第二巡計画143.json')
    assert shared.read(HERE/'第二巡登録143.json')['returncode'] == 0
    for path, sha in plan['spec']['implementation'].items():
        assert prior.ref(ROOT/path)['sha256'] == sha, path
    packets, cache, labels = shared.material()
    first = {x['session']:x for x in shared.read(HERE/'第一巡結果143.json')['cache']}
    oldcache = {}
    for folder in ('round2_known', 'round2_new'):
        oldcache.update({x['session']:x for x in shared.read(ORIGINAL/folder/'結果140.json')['cache'] if x['symbol']=='NK225'})
    rows, files = [], []
    for item in packets:
        scene = item['session']
        target = HERE/'round2/results'/f'{scene}.json'
        if target.exists():
            saved = shared.read(target)
            rows.extend(saved['rows']); files.extend(saved['cache'])
            continue
        packet = shared.packet_from(item)
        data, _, _, history = previous.prepared(packet)
        ready = data['NK225']
        base, addon, _ = shared.sources(scene, cache)
        source = ROOT/first[scene]['path']
        assert prior.ref(source)['sha256'] == first[scene]['sha256']
        with np.load(source) as saved:
            addon3 = saved['A3']
            gatebase = saved['O01' if scene.endswith('_Day') else 'O02']
        arrays, traces, contexts, provenance = {}, {}, {}, []
        for config in plan['configs']['overlay']:
            method = config['id']
            orders, trace = overlay.replay(ready, base, history[scene,'NK225'], config)
            arrays[method] = orders
            arrays['F'+method[1:]] = shared.merge(orders, addon)
            traces[method] = trace
            contexts[method] = overlay.parent_context(ready, base, history[scene,'NK225'], orders)
        # ----------------------------------------
        # 復元担当は元24列を使用し、判断後にしか最終場方向を会計へ渡さない。
        prepared, generated = {}, {}
        active_keys = set(original.configurations()[0]) - {'id', 'name'}
        for config in plan['configs']['restored']:
            method = config['id']
            window = config['window']
            if window not in prepared:
                prepared[window] = original.prepare(packet, window)['NK225']
            old_method = config.get('reuse_method')
            signature = json.dumps({k:config[k] for k in sorted(active_keys)}, sort_keys=True)
            orders = generated.get(signature)
            cached_here = orders is not None
            if orders is None:
                orders = old_orders(scene, old_method, oldcache) if old_method else None
            reused = orders is not None and not cached_here
            if orders is None:
                orders, _ = original.replay(prepared[window], config)
            generated[signature] = orders
            small = dict(config, initial=1, maximum=2)
            small_signature = json.dumps({k:small[k] for k in sorted(active_keys)}, sort_keys=True)
            small_orders = generated.get(small_signature)
            if small_orders is None:
                small_orders, _ = original.replay(prepared[window], small)
                generated[small_signature] = small_orders
            suffix = method[1:]
            arrays[method] = orders
            arrays['L'+suffix] = small_orders
            arrays['U'+suffix] = shared.merge(base, orders)
            arrays['V'+suffix] = shared.merge(gatebase, orders)
            arrays['W'+suffix] = shared.merge(base, addon3, small_orders)
            arrays['Y'+suffix] = shared.merge(gatebase, addon3, small_orders)
            provenance.append(dict(method=method, reused=reused, reused_same_scene=cached_here, original=old_method,
                source=oldcache.get(scene) if reused else None))
        scene_rows = [shared.account(orders, packet, method, labels[scene]) for method,orders in arrays.items()]
        dest = HERE/'round2/measurement'/f'NK225_{scene}.npz'
        dest.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(dest, **arrays)
        record = dict(session=scene, symbol='NK225', **prior.ref(dest))
        dest = HERE/'round2/traces'/f'NK225_{scene}.npz'
        dest.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(dest, **traces)
        shared.save(target, dict(rows=scene_rows, cache=[record], provenance=provenance, contexts=contexts))
        rows.extend(scene_rows); files.append(record)
        print(scene, '復元と固定支持の第二巡完了', flush=True)
    shared.save(HERE/'第二巡結果143.json', dict(rows=rows, cache=files, plan=prior.ref(HERE/'第二巡計画143.json'), API=0, real_orders=0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('register','run'))
    register() if parser.parse_args().stage == 'register' else run()
