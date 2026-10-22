"""二つの独立した少額E01会計の場末収支を合算する。"""

import hashlib
import json
from pathlib import Path
import statistics


def main() -> None:
    """
    機能: 保存済み二口座の利益・損失・収支を40場へまとめる。
    引数: なし。根が一読保全したh結果だけを使用する。
    返り値: None。新しい金融再生、共通停止、枚数変更、共同時価推定を行わない。
    """
    base = Path(__file__).resolve().parent
    source = base / 'v6_resume/root_owned/少額E01固定二設定の追加七場と全四十場.json'
    payload = source.read_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    assert sha == 'd0f1f86cb955a2da7016f0a33f6ff097eb64edb14068e8d0a0b4278aebca963b'
    data = json.loads(payload)
    rows = []
    for scene in data['sessions']:
        own = [row for row in data['rows'] if row['session'] == scene]
        assert len(own) == 2 and {row['symbol'] for row in own} == {'TOPIX', 'NK225'}
        values = {key: sum(row[key] for row in own) for key in ('profit', 'loss', 'net', 'fees', 'campaigns')}
        assert abs(values['profit'] - values['loss'] - values['net']) < 1e-6
        rows.append(dict(session=scene, **values, active=values['campaigns'] > 0,
            origin='旧33保存会計の合算' if scene in data['old_sessions'] else '新7会計の合算'))
    metrics = {}
    for name, selected in (('全40', data['sessions']), ('旧33', data['old_sessions']), ('追加7', data['new_sessions'])):
        own = [row for row in rows if row['session'] in selected]
        values = [row['net'] for row in own]
        green = [value for value in values if value > 0]
        metrics[name] = dict(sessions=len(own), black=sum(value > 0 for value in values),
            red=sum(value < 0 for value in values), inactive=sum(not row['active'] for row in own),
            net=sum(values), profit=sum(row['profit'] for row in own), loss=sum(row['loss'] for row in own),
            fees=sum(row['fees'] for row in own), median=statistics.median(values), mean=statistics.mean(values),
            worst=min(values), mean_positive=statistics.mean(green) if green else None,
            top3_removed=sum(values)-sum(sorted(green, reverse=True)[:3]))
    proof = dict(全合格=True, method='E01_006_DUAL_FIXED', source_SHA256=sha,
        source_path=source.relative_to(base.parents[1]).as_posix(), rows=rows, metrics=metrics,
        new_financial_replay=0, new_independent_evidence=False, raw_reads=0,
        flat_basis='各口座の新14終端直接検査と旧66の既存finish保証へ委譲。旧終端枚数nullを0へ補完しない。',
        limitation='独立二口座を同時に動かした場合の場末収支の算術合算。共通の資金上限・共同場内停止・保有中の合成MTM/DDは検証していない。別銘柄だから分散されたとも主張しない。')
    output = base / 'v6_resume/root_owned/少額E01二口座の場末収支合算.json'
    assert not output.exists()
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(SHA256=hashlib.sha256(output.read_bytes()).hexdigest(), metrics=metrics), ensure_ascii=False))


if __name__ == '__main__':
    main()
