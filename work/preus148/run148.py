"""事前登録後に16条件を全保存夜へ再生し、米国後の仮想D07と組み合わせる。"""

from pathlib import Path
import json
import pickle
import numpy as np

import engine
from configs import CONFIGS
from accounting import account, summary

HERE = Path(__file__).resolve().parent


def clean(value):
    """非有限診断値を空値へ正規化する。

    引数: value(object)は辞書・配列・数値。
    返り値: objectはJSONで保存可能な値。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def save(path, value):
    """UTF-8のJSONを有限数値だけで保存する。

    引数: path(Path)、value(object)。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def main():
    """登録済み条件を再生し、25夜と途中場の会計を別々に記録する。

    引数: なし。
    返り値: None。注文の実送信は行わない。
    """
    receipt = json.loads((HERE / '登録受領.json').read_text(encoding='utf-8'))
    assert receipt['returncode'] == 0
    methods = [dict(id='D07', description='従来D07。夜間全体の基準', rows=[])]
    methods += [dict(id=c['id'], description=c['description'], config=c, rows=[]) for c in CONFIGS]
    pre_rows = {method['id']: [] for method in methods}
    partial = []
    paths = sorted((HERE / 'inputs').glob('*_Night.pkl'))
    for path in paths:
        payload = pickle.loads(path.read_bytes())
        data, label = payload['data'], payload['label']
        scene, is_partial = path.stem, bool(payload.get('partial', False))
        prepared = engine.prepare(data)
        details, arrays = {}, {}
        if not is_partial:
            original = account(payload['baseline'], data, strict_next=False)
            pre = account(payload['pre'], data, strict_next=False)
            post = account(payload['post'], data, strict_next=False)
            assert abs(original['net'] - pre['net'] - post['net']) < 1e-5
            original.update(session=scene, direction=label['direction'], pre_net=pre['net'], post_net=post['net'])
            methods[0]['rows'].append(original)
            pre.update(session=scene, direction=label['direction'])
            pre_rows['D07'].append(pre)
        else:
            partial.append(dict(id='D07', session=scene, **account(payload['baseline'], data, allow_open=True, strict_next=False)))
        for config in CONFIGS:
            simulation = engine.simulate(data, config, prepared)
            orders = simulation['orders']
            result = account(orders, data, allow_open=is_partial)
            result.update(session=scene, direction=label['direction'])
            details[config['id']] = dict(pre=result, diagnostics=simulation['diagnostics'], final_state=simulation['final_state'])
            arrays[config['id']] = orders
            if is_partial:
                partial.append(dict(id=config['id'], **result))
                continue
            assert not simulation['positions'] and not simulation['final_state']['pending_orders']
            pre_rows[config['id']].append(result)
            # ----------------------------------------
            # 後半は17時から継続する独立した仮想D07の通知。前半実損益を後半予算へ混ぜない。
            tail = payload['post'].copy()
            if len(tail) and len(orders):
                assert data['ready']['time_s'][int(orders[-1, 0])] < data['ready']['time_s'][int(tail[0, 1])]
            tail[:, 2] += 1000000
            tail[:, 8] += 1000000
            combined = np.concatenate([orders, tail], axis=0)
            combined = combined[np.argsort(combined[:, 0], kind='stable')]
            whole = account(combined, data, strict_next=False)
            assert abs(whole['net'] - result['net'] - post['net']) < 1e-5
            whole.update(session=scene, direction=label['direction'], pre_net=result['net'], post_net=post['net'])
            next(m for m in methods if m['id'] == config['id'])['rows'].append(whole)
            arrays['全夜_' + config['id']] = combined
        save(HERE / 'results' / f'{scene}.json', details)
        (HERE / 'orders').mkdir(exist_ok=True)
        np.savez_compressed(HERE / 'orders' / f'{scene}.npz', **arrays)
        print(scene, '途中' if is_partial else '完了', flush=True)
    # ----------------------------------------
    # 終値方向と前後期間の分類は会計の後にだけ行う。
    for method in methods:
        rows = method['rows']
        method['summary'] = summary(rows)
        method['pre_summary'] = summary(pre_rows[method['id']])
        method['divisions'] = {name: summary([r for r in rows if r['direction'] == name]) for name in ('上昇', '下落') if any(r['direction'] == name for r in rows)}
        method['periods'] = dict(前半15夜=summary(rows[:15]), 後半10夜=summary(rows[15:]))
        method['pre_rows'] = pre_rows[method['id']]
    save(HERE / 'report.json', dict(methods=methods, partial=partial,
        scope='既知開発25夜＋説明用の10月26日途中。日経mini最大10枚、手数料0、ラージ次正常気配代理。',
        integration='前半実運転とは独立にD07を17時から仮想継続。22:15に前半を終了し、22:45以後の仮想D07通知を採用。前半実損益はD07予算へ注入しない。',
        current_cutoff='2026-10-26T21:13:52+09:00'))
    save(HERE / '集計.json', [{k: m[k] for k in ('id', 'description', 'summary', 'pre_summary', 'divisions', 'periods')} for m in methods])
    print('全比較完了', flush=True)


if __name__ == '__main__':
    main()
