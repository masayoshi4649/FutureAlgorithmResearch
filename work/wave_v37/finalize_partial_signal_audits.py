"""全固定条件の因果・波監査を集約し、波監査の限定改訂を完結させる。"""

from __future__ import annotations

import argparse
from pathlib import Path

import partial_causality_audit as causal

HERE, ROOT = causal.HERE, causal.ROOT
read, save, digest = causal.read, causal.save, causal.digest


def verify_sources(fixed: dict) -> None:
    """機能: 内包された参照SHAと現物の全一致を確認する。

    引数: fixed (dict)。返り値: なし (None)。
    """
    for relative, sha in fixed['SHA256'].items():
        assert digest(ROOT/relative) == sha, relative


def waves() -> tuple[dict, list[dict]]:
    """機能: 波のv2全427明細を結び、原版保全・計算式不変・非混在を記録する。

    引数: なし。返り値: 改訂完了記録・主案8波 (tuple[dict,list[dict]])。
    """
    old = read(HERE/'partial_wave_fixed.json'); new = read(HERE/'partial_wave_fixed_v2.json')
    verify_sources(old); verify_sources(new)
    assert old['規則'] == new['規則'], '結果前の対象・閾値・計算法の変更'
    tests = read(HERE/'partial_wave_revision_checks.json')
    assert tests['全合格'] and tests['注文一覧は追加2キー以外AST同一']
    assert len(tests['数値関数AST同一']) == 5 and tests['人工注文数'] == 4
    for name, sha in tests['SHA256'].items(): assert digest(HERE/name) == sha
    plan = read(HERE/'partial_wave_revision_plan.json')
    for relative, sha in plan['旧監査SHA256'].items(): assert digest(ROOT/relative) == sha
    references = {}
    primary = []
    wave_count, boundary_count, condition_count = 0, 0, 0
    for sub, specs in (('', causal.design.catalog()), ('supplementary', causal.design.supplementary())):
        directory = HERE/sub
        path = directory/'partial_wave_audit.json'; header = read(path)
        assert header['全合格'] and header['監査版'] == 2 and header['監査規則'] == new
        assert header['条件数'] == len(specs) and header['波数'] == len(specs)*8
        assert header['境界数'] == len(specs)*16
        records = {r['id']:r for r in header['結果']}
        assert len(header['結果']) == len(records) == len(specs) and set(records) == {s['id'] for s in specs}
        references[path.relative_to(ROOT).as_posix()] = digest(path)
        for spec in specs:
            path = directory/'partial_wave_details'/(spec['id']+'.json.gz'); detail = read(path)
            assert detail == records[spec['id']] and detail['監査版'] == 2 and detail['全合格']
            assert detail['監査固定SHA256'] == digest(HERE/'partial_wave_fixed_v2.json')
            assert detail['波数'] == 8 and detail['境界数'] == 16 and detail['全保存項目一致']
            wanted = {(w['id'],s) for w in new['規則']['指定波'] for s in new['規則']['銘柄']}
            assert len(detail['波']) == 8 and {(r['wave'],r['symbol']) for r in detail['波']} == wanted
            expected = {(directory/kind/(spec['id']+'.json.gz')).relative_to(ROOT).as_posix() for kind in ('waves','ledgers')}
            assert set(detail['主保存SHA256']) == expected
            for relative, sha in detail['主保存SHA256'].items(): assert digest(ROOT/relative) == sha
            references[path.relative_to(ROOT).as_posix()] = digest(path)
            if spec['primary']: primary = detail['波']
        wave_count += header['波数']; boundary_count += header['境界数']; condition_count += len(specs)
    assert (condition_count, wave_count, boundary_count) == (427, 3416, 6832)
    assert len(primary) == 8
    for name in ('partial_wave_audit.py','partial_wave_fixed.json','partial_wave_selftest.json',
                 'partial_wave_audit_v2.py','partial_wave_fixed_v2.json','partial_wave_selftest_v2.json',
                 'partial_wave_failure_v1.json','partial_wave_revision_plan.json','partial_wave_revision_checks.json',
                 'partial_wave_revision_check.py','build_wave_audit_v2.py'):
        references[(HERE/name).relative_to(ROOT).as_posix()] = digest(HERE/name)
    result = dict(改訂完了=True, 監査版=2, 主条件数=363, 補助条件数=64, 全条件数=427,
        全波数=3416, 全境界数=6832, 全主補助をv2で再監査=True, 旧新版混在=False,
        旧実装と固定不変=True, 旧結果前規則継承=True, 改訂は主再生後=True,
        改訂理由='独立波監査で不足した注文一覧の管理方向2キーを元入口列のsource/fill行から再計算する保存schema補正。',
        数値5関数不変=True, 売買変更=False, 入力変更=False, 成績変更=False, 採否変更=False,
        許容値変更=False, 対象変更=False, 新売買再生=False, 現在保存物使用=False, API取得数=0,
        参照SHA256=references)
    save(HERE/'partial_wave_revision.json', result)
    return result, primary


def main() -> None:
    """機能: 波改訂だけ又は因果を含めた全監査の完了記録を出す。

    引数: --waves-only (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--waves-only', action='store_true'); args = parser.parse_args()
    revised, primary = waves()
    if args.waves_only:
        print('波v2全427条件・3416波の改訂完結、旧版不変、非混在。', flush=True)
        return
    fixed = read(HERE/'partial_causality_fixed.json'); verify_sources(fixed)
    total = 0; identifiers = []
    for sub, specs, count in (('', causal.design.catalog(),1474),('supplementary',causal.design.supplementary(),256)):
        header = read(HERE/sub/'partial_causality_audit.json')
        assert header['全合格'] and header['入力数'] == header['prefix数'] == header['future数'] == header['reflection数'] == count
        assert header['監査規則'] == fixed and header['条件数'] == len(specs)
        assert header['影新規再生成数'] == count*4 and header['全結果指紋一致']
        by_id = {r['id']:r for r in header['結果']}
        assert len(by_id) == len(header['結果']) == len(specs) and set(by_id) == {s['id'] for s in specs}
        for spec in specs:
            detail = read(HERE/sub/'partial_causality_details'/(spec['id']+'.json'))
            assert detail == by_id[spec['id']] and detail['全合格']
            assert detail['入力数'] == len(detail['検査']) == (26 if spec['primary'] else 4)
            for proof in detail['検査']:
                assert all(proof[k] for k in ('保存全指紋一致','prefix一致','future一致','reflection一致','同時刻群途中'))
        total += count; identifiers.extend(by_id)
    assert total == 1730 and len(identifiers) == len(set(identifiers)) == 427
    files = [HERE/sub/name for sub in ('','supplementary') for name in ('partial_causality_audit.json','partial_wave_audit.json')]
    files += [Path(__file__), HERE/'partial_causality_fixed.json', HERE/'partial_wave_revision.json', HERE/'探索条件の固定.json']
    result = dict(因果と指定波の全監査合格=True, 全条件数=427, 因果入力数=1730, prefix数=1730,
        future数=1730, reflection数=1730, 指定波数=3416, 波境界数=6832, 影新規再生成数=6920,
        会計全26の独立監査は別担当=True, 主案=causal.design.PRIMARY_ID,
        主案20分目安達成数=sum(r['正方向ネット20分目安達成'] for r in primary), 主案指定波=primary,
        全体目標達成の判定ではない=True, 現在保存物使用=False, API取得数=0,
        SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in files})
    save(HERE/'partial_signal_audits_complete.json', result)
    lines = ['# 因果・指定波の独立監査', '',
        '主363＋補助64の全427条件を照合した。因果は代表昼夜の両市場と主案全26、計1,730入力。各入力の切断・未来変更・上下反射が一致し、影は計6,920回、変更入力から新規生成した。', '',
        '全3,416波・6,832境界は全保存注文の現金と買売在庫から別計算し、保存全項目と一致した。注文一覧の管理方向2列の転記漏れで原版監査を停止し、原版を残したv2で全件を再監査した。数値計算5関数・対象・許容値は不変。', '',
        '20分は波と同方向のネット保有時間の説明用目安で、利益や統計的有意性の保証ではない。管理方向という旧保存欄は入口列の複写であり、減量・復元の悪化／回復根拠ではない。', '',
        '## 事前固定した主案', '', '|波|銘柄|正方向保有 分|逆方向保有 分|波の時価損益差 円|20分目安|',
        '|---|---|---:|---:|---:|---|']
    for row in primary:
        lines.append(f"|{row['wave']}|{row['symbol']}|{row['正方向ネット保有分']:.2f}|{row['逆方向ネット保有分']:.2f}|{row['時価損益差円']:+,.0f}|{'達成' if row['正方向ネット20分目安達成'] else '未達'}|")
    lines += ['', '境界の時価差には開始前からの玉を含む。CurrentPriceTimeは受信時刻ではなく、同時刻行の経過時間は0とする。原本・旧成果不変、現在APIと保存ライブは使用していない。']
    (HERE/'partial_signal_audits_complete.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('因果1730・波3416の全427条件監査が一致。', flush=True)


if __name__ == '__main__':
    main()
