"""先に設計した31場を固定し、後から保存されたナイトを別の追加確認へ隔離する。"""

import socket
from pathlib import Path

import research


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXTRA = '2026-10-12_Night'


def main() -> None:
    """
    機能: 元の固定検査を維持し、追加一場の存在だけを明記して既知31場を固定する。
    引数: なし。
    返り値: None。追加場の損益、選定又は条件変更は行わない。
    """
    socket.create_connection = research.deny
    socket.socket.connect = research.deny
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    plan = research.read(HERE / '結果前の設計案.json')
    catalog, data = research.catalog, research.data
    assert plan['予定条件数'] == len(catalog.catalog()) == 20
    assert plan['正式新条件売買実行'] == 0 and plan['理論主'] == catalog.PRIMARY
    manifest = research.read(HERE / '前検証目録.json')
    assert manifest['全合格'] and manifest['新正式損益未実行']
    assert set(manifest['検査']) == {'全20人工と停止余裕及び据置', '旧8対照全496と経済null',
        '実入力因果不変', '結果前独立反証', '独立監査人工CLI全8期間の終端'}
    paths = [HERE / '前検証目録.json', HERE / '結果前の設計案.json',
             HERE / '結果前の数理明確化.json', HERE / '実装前の仕様明確化.json',
             HERE / 'セッション安定性の事前評価.json', HERE / '結果前の設計根拠.json',
             Path(__file__), HERE / 'root_preflight/初回固定の追加保存場による目録不一致.json']
    for relative, expected in research.read(HERE / '結果前の設計根拠.json')['設計根拠SHA256'].items():
        assert data.digest(ROOT / relative) == expected, relative
        paths.append(ROOT / relative)
    for name, binding in {**manifest['検査'], **manifest.get('補足', {})}.items():
        path = ROOT / binding['資料']
        assert data.digest(path) == binding['SHA256'], name
        proof = research.read(path)
        status = proof.get('全合格', proof.get('合格'))
        if status is None:
            assert proof.get('純数理全合格') is True and proof.get('仕様確定合格') is True, name
        else:
            assert status is True, name
        paths.append(path)
        for relative, expected in proof.get('SHA256', {}).items():
            assert data.digest(ROOT / relative) == expected, relative
            paths.append(ROOT / relative)
    for name, binding in manifest.get('不合格履歴', {}).items():
        path = ROOT / binding['資料']
        assert data.digest(path) == binding['SHA256'], name
        proof = research.read(path)
        assert proof['全合格'] is False and proof['正式102損益'] == proof['実注文'] == 0, name
        paths.append(path)
    prior_path = HERE.parent / 'wave_v101/事前固定.json'
    prior = research.read(prior_path)
    for relative, expected in prior['SHA256'].items():
        assert data.digest(ROOT / relative) == expected, relative
    material = data.load_inputs()
    sessions = material['metadata']['sessions']
    assert len(sessions) == 31 and sessions == prior['全31']

    # ----------------------------------------
    # 追加場を隠さず、現在のデータ目録と隔離先を固定資料に記録する。
    extra_paths = []
    inventory = {}
    for symbol in catalog.SYMBOLS:
        actual = {p.stem for p in (ROOT / 'book' / symbol).glob('*.jsonl')}
        assert actual == set(sessions) | {EXTRA}, (symbol, actual ^ set(sessions))
        inventory[symbol] = sorted(actual)
        extra_paths.append(ROOT / 'book' / symbol / (EXTRA + '.jsonl'))
    extra_sha = {str(path.relative_to(ROOT)): data.digest(path) for path in extra_paths}
    extra_plan = dict(全合格=True, 固定の対象='既知31場の20条件。追加ナイトは選定に入れない。',
        新追加場=EXTRA, 追加場の売買再生=0, 追加場の損益閲覧=0,
        追加確認の予定='前16参考を固定し、既知31場の結果を確定した後、同じ条件で追加ナイトを別集計する。',
        現在保存板目録=inventory, SHA256=extra_sha, API取得=0, 実注文=0)
    extra_plan_path = HERE / '追加ナイトの隔離計画.json'
    assert not extra_plan_path.exists()
    research.save(extra_plan_path, extra_plan)
    paths += material['paths'] + [prior_path, extra_plan_path] + extra_paths
    paths += [HERE / name for name in ('catalog.py','data.py','engine.py','strategy.py',
              'accounting.py','research.py','analysis/assemble.py')]
    paths += list((HERE / 'audit').glob('*.py'))
    fingerprints = dict(prior['SHA256'])
    fingerprints.update({str(path.relative_to(ROOT)): data.digest(path) for path in sorted(set(paths))})
    research.save(HERE / '事前固定.json', dict(条件=catalog.catalog(), 主=catalog.PRIMARY, 対照=catalog.CONTROL,
        全31=sessions, 前16=sessions[:16], 後15=sessions[16:], 旧30=sessions[:-1],
        後14=sessions[16:-1], 追加1=sessions[-1:], 全31既知=True, 新未見確認場数=0,
        理論=plan, API取得=0, 実注文=0, 前検証SHA256=data.digest(HERE / '前検証目録.json'),
        正式新条件損益前固定=True, SHA256=fingerprints,
        固定担当=str(Path(__file__).relative_to(ROOT)), 現在の保存場数=32,
        固定対象外の新追加場=EXTRA, 追加場の売買再生=0, 追加場の損益閲覧=0,
        追加場SHA256=extra_sha))
    print('20条件と既知31場を固定。追加10月12日ナイトは別確認へ隔離しました。', flush=True)


if __name__ == '__main__':
    main()
