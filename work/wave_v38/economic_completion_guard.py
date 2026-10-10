"""全条件の経済検算を結び、既知の状態契約不適合を未合格のまま保持する。"""

from __future__ import annotations

from copy import deepcopy
import argparse

import adaptive_runner as runner
import adaptive_assessment as assessment
import assess_results
import economic_completion_checks as economic
from adaptive_independent_statistics import equal


def prepare() -> dict:
    """機能: 経済専用ガードと破損試験を事後の診断仕様として固定する。

    引数: なし。返り値: 診断実装固定(dict)。売買仕様の結果前固定とは呼ばない。
    """
    test = runner.read(runner.HERE/'economic_completion_guard_test.json')
    assert test['全合格'] is True and test['破損拒否数'] >= 30
    assert test['ガードSHA256'] == runner.digest(runner.HERE/'economic_completion_guard.py')
    assert test['補助SHA256'] == runner.digest(runner.HERE/'economic_completion_checks.py')
    assert test['試験SHA256'] == runner.digest(runner.HERE/'economic_completion_guard_test.py')
    names = ('completion_guard.py','economic_completion_guard.py','economic_completion_checks.py',
        'economic_completion_guard_test.py','economic_completion_guard_test.json',
        'adaptive_accounting_diagnostic_fixed.json','adaptive_assessment.py','adaptive_assessment_fixed.json',
        'adaptive_accounting_failed_run.json','phase_state_counterfactual.json','phase_control_flow_proof.json')
    value = dict(経済専用=True,状態欠陥判明後の事後検証=True,売買又は採否の条件変更=False,
        元ガード不変=True,全入力数=25324,因果入力数=3918,全波数=7792,
        全会計完成前には正式出力しない=True,状態不合格を合格化しない=True,
        参照SHA256={(runner.HERE/name).relative_to(runner.ROOT).as_posix():runner.digest(runner.HERE/name) for name in names})
    path = runner.HERE/'economic_completion_guard_fixed.json'
    if path.exists(): assert runner.read(path) == value
    else: runner.save(path,value)
    return value


def cash_revision(reference: dict) -> None:
    """機能: 初回停止・境界だけの改訂・旧158全結果一致を公表へ結ぶ。

    引数: reference (dict[str,str])。返り値: なし (None)。新旧の結果を混ぜない。
    """
    ready=runner.read(runner.HERE/'adaptive_cash_revision_ready.json')
    assert ready['再起動可能'] and ready['全売買条件不変'] and ready['損益算術不変']
    assert ready['主再生中断後の限定改訂'] and ready['同一試行の結果前固定と偽らない']
    assert ready['主条件数']==206 and ready['補助条件数']==768 and ready['元158再照合必須']
    assert ready['現在API取得数']==0
    for relative,sha in ready['参照SHA256'].items():
        assert runner.digest(runner.ROOT/relative)==sha,relative
        reference[relative]=sha
    assert ready['ガードSHA256']==runner.digest(runner.HERE/'cash_revision_ready.py')
    plan=runner.read(runner.HERE/'adaptive_cash_revision_plan.json')
    for row in plan['旧資料'].values():
        assert runner.digest(runner.ROOT/row['保存先'])==row['SHA256']
        reference[row['保存先']]=row['SHA256']
    proof=runner.read(runner.HERE/'adaptive_cash_revision_results.json')
    assert proof['全合格'] and proof['全数値一致'] and proof['注文エンジンと入力と採否不変']
    assert (proof['旧条件数'],proof['旧入力数'],proof['一致保存資料数'])==(158,4108,790)
    assert proof['旧計画SHA256']==runner.digest(runner.HERE/'adaptive_cash_revision_plan.json')
    assert proof['新固定SHA256']==runner.digest(runner.HERE/'探索条件の固定.json')
    expected={(runner.HERE/folder/(identifier+suffix)).relative_to(runner.ROOT).as_posix()
        for identifier in plan['旧保存ID'] for folder,suffix in (
            ('ledgers','.json.gz'),('sessions','.json.gz'),('waves','.json.gz'),('accounting','.json.gz'),('summaries','.json'))}
    assert len(expected)==790 and set(proof['参照SHA256'])==expected
    for relative,sha in proof['参照SHA256'].items():
        assert runner.digest(runner.ROOT/relative)==sha,relative
        reference[relative]=sha
    for name in ('adaptive_cash_revision_ready.json','cash_revision_ready.py','adaptive_cash_revision_results.json'):
        path=runner.HERE/name;reference[path.relative_to(runner.ROOT).as_posix()]=runner.digest(path)


def verify() -> tuple:
    """機能: 独立会計・因果・指定波の全集合と指紋を確認する。

    引数: なし。返り値: 経済検証済み判定と状態不適合を含む証跡 (tuple[dict,dict])。
    """
    fixed = runner.prepare()
    local_fixed = prepare()
    startup = runner.read(runner.HERE/'起動前監査.json')
    assert startup['実行可能'] and startup['探索固定SHA256'] == runner.digest(runner.HERE/'探索条件の固定.json')
    for relative,sha in startup['SHA256'].items(): assert runner.digest(runner.ROOT/relative) == sha, relative
    reference = {}
    economic.references(local_fixed['参照SHA256'], reference)
    local_path = runner.HERE/'economic_completion_guard_fixed.json'
    reference[local_path.relative_to(runner.ROOT).as_posix()] = runner.digest(local_path)
    cash_revision(reference)
    economic.diagnostic_fixed(fixed, reference)
    state_issues = []
    evidence_kinds = {economic.ORIGINAL: 0, economic.DIAGNOSTIC: 0}
    wave_fixed = runner.read(runner.HERE/'adaptive_wave_fixed.json')
    index, sessions, _ = assess_results.collect()
    total_input = total_causal = total_waves = 0
    expected_keys = {(s,k) for s in fixed['全セッション'] for k in runner.SYMBOLS}
    raw = runner.pickle.loads((runner.HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    lengths = {key:len(value['last']) for key,value in raw.items()}
    boundaries={}
    for key,value in raw.items():
        n=lengths[key]; ties=runner.np.flatnonzero(runner.np.diff(value['time_s'])==0)+1
        future=int(ties[runner.np.argmin(abs(ties-int(n*.73)))]) if len(ties) else max(2,int(n*.73))
        boundaries[key]=(max(2,int(n*.37)),future,bool(len(ties)))
    times = {key:value['time_s'] for key,value in raw.items()}
    del raw
    assert set(lengths) == expected_keys
    all_raw_rows = sum(lengths.values())
    wave_keys = {(w['id'],s) for w in fixed['指定波'] for s in runner.SYMBOLS}
    for destination, specs, causal_count in (('',fixed['conditions'],846),('supplementary',fixed['supplementary_conditions'],3072)):
        directory = runner.HERE/destination
        records = {name:runner.read(directory/(name+'.json')) for name in (
            'adaptive_accounting_diagnostic','adaptive_causality_audit','adaptive_wave_audit')}
        cash, causal, waves = (records[k] for k in ('adaptive_accounting_diagnostic','adaptive_causality_audit','adaptive_wave_audit'))
        economic.cash_header(cash, specs, all_raw_rows, reference)
        if not destination:
            assert cash['原版成功条件数'] == 205 and cash['診断版条件数'] == 1
        else:
            assert cash['原版成功条件数'] == 0 and cash['診断版条件数'] == 768
        assert causal['全合格'] and causal['全結果指紋一致'] and causal['条件数'] == len(specs)
        assert causal['入力数'] == causal['prefix数'] == causal['future数'] == causal['reflection数'] == causal_count
        assert causal['影新規再生成数'] == causal_count*4
        assert causal['監査規則'] == runner.read(runner.HERE/'adaptive_causality_fixed.json')
        assert waves['監査版']==1 and waves['全合格'] and waves['全保存項目一致'] and waves['条件数'] == len(specs)
        assert waves['波数'] == len(specs)*8 and waves['境界数'] == len(specs)*16
        assert waves['監査規則'] == wave_fixed
        expected_ids = {s['id'] for s in specs}
        mappings = {}
        for name, values in (('cash',cash['条件']),('causal',causal['結果']),('wave',waves['結果'])):
            assert len(values) == len(specs) and {v['id'] for v in values} == expected_ids
            mappings[name] = {v['id']:v for v in values}
        for record in records.values():
            assert record['探索固定SHA256'] == runner.digest(runner.HERE/'探索条件の固定.json')
            assert record['API取得数'] == 0 and record['現在保存物使用'] is False
        for spec in specs:
            identifier = spec['id']
            single = runner.read(directory/'summaries'/(identifier+'.json'))
            assert single == index[identifier], ('期間集約と個別保存の差',identifier)
            assert single['spec'] == spec
            rows = sessions[identifier]
            assert len(rows) == 26 and {(r['session'],r['symbol']) for r in rows} == expected_keys
            certificate = mappings['cash'][identifier]
            detail_path = economic.detail_path(directory, certificate, spec)
            detail = runner.read(detail_path)
            evidence_kinds[certificate['証拠種別']] += 1
            state_issues.extend(economic.detail_state(certificate, detail, times))
            assert certificate['経済監査合格'] is True and certificate['全入力数'] == 26
            assert certificate['全原本行会計数'] == all_raw_rows
            assert certificate['監査固定SHA256'] == cash['監査固定SHA256']
            assert certificate['実体SHA256'] == runner.digest(detail_path)
            assert detail['全入力数'] == 26 and detail['spec'] == spec
            assert detail['全原本行会計数'] == all_raw_rows
            assert detail['監査固定SHA256'] == cash['監査固定SHA256']
            assert detail['探索固定SHA256'] == cash['探索固定SHA256']
            assert len(detail['検査']) == 26 and {(r['session'],r['symbol']) for r in detail['検査']} == expected_keys
            for proof in detail['検査']:
                assert proof['原本行数'] == lengths[(proof['session'],proof['symbol'])]
                for field in ('全枠会計一致','全予約と新根拠一致','元終了以前','同約定両建て全行一致',
                        '全予算予約一致','全保存数値一致','全台帳配列一致','分岐集計独立一致','全組R超過独立一致',
                        '全分岐独立一致','全伝達遅延一致'):
                    assert proof[field] is True,field
                nested=proof['影の独立公開と執行']
                for field in ('影全会計一致','独立公開計画一致','独立準備一致','最新成熟計画一致','全行注文成立不成立一致'):
                    assert nested[field] is True,field
                assert nested['原本行数']==proof['原本行数']
            equal(detail['sessions'],rows,'会計明細と主明細')
            for field in ('all_symbols','symbols'): equal(detail[field],single[field],field)
            required = {str((directory/folder/(identifier+suffix)).relative_to(runner.ROOT).as_posix())
                for folder,suffix in (('sessions','.json.gz'),('ledgers','.json.gz'),('waves','.json.gz'),('accounting','.json.gz'),('summaries','.json'))}
            assert set(detail['保存資料SHA256']) == required
            for relative, sha in detail['保存資料SHA256'].items():
                assert runner.digest(runner.ROOT/relative) == sha, relative
                reference[relative] = sha
            causal_path = directory/'adaptive_causality_details'/(identifier+'.json')
            causal_detail = runner.read(causal_path)
            assert causal_detail == mappings['causal'][identifier]
            assert causal_detail['全合格']
            assert causal_detail['主保存SHA256'] == runner.digest(directory/'ledgers'/(identifier+'.json.gz'))
            assert causal_detail['監査固定SHA256'] == runner.digest(runner.HERE/'adaptive_causality_fixed.json')
            subset=expected_keys if spec['primary'] else {k for k in expected_keys if k[0] in causal['監査規則']['規則']['代表期間']}
            assert causal_detail['入力数'] == len(subset) and len(causal_detail['検査']) == len(subset)
            assert {(r['session'],r['symbol']) for r in causal_detail['検査']} == subset
            for proof in causal_detail['検査']:
                key=(proof['session'],proof['symbol']);n=lengths[key]
                assert proof['原本行数']==n and 0<proof['prefix行']<n and 0<proof['future行']<n
                assert (proof['prefix行'],proof['future行'],proof['同時刻群途中'])==boundaries[key]
                assert proof['影新規再生成数']==4
                for field in ('保存全指紋一致','prefix一致','future一致','reflection一致'): assert proof[field] is True
            wave_path = directory/'adaptive_wave_details'/(identifier+'.json.gz')
            wave_detail = runner.read(wave_path)
            wave_certificate = mappings['wave'][identifier]
            assert wave_detail == wave_certificate
            assert wave_detail['監査版']==1 and wave_detail['全合格'] and wave_detail['波数'] == 8
            assert wave_detail['境界数']==16 and wave_detail['全保存項目一致'] is True
            assert wave_detail['監査固定SHA256'] == runner.digest(runner.HERE/'adaptive_wave_fixed.json')
            assert set(wave_detail['主保存SHA256'])=={
                (directory/folder/(identifier+'.json.gz')).relative_to(runner.ROOT).as_posix()
                for folder in ('ledgers','waves')}
            for relative,sha in wave_detail['主保存SHA256'].items(): assert runner.digest(runner.ROOT/relative) == sha, relative
            saved_waves = runner.read(directory/'waves'/(identifier+'.json.gz'))
            assert len(saved_waves) == 8
            assert {(r['wave'],r['symbol']) for r in saved_waves} == wave_keys
            assert len(wave_detail['波'])==8 and {(r['wave'],r['symbol']) for r in wave_detail['波']}==wave_keys
            equal(sorted(saved_waves,key=lambda r:(r['wave'],r['symbol'])),
                sorted(wave_detail['波'],key=lambda r:(r['wave'],r['symbol'])), '保存波と独立波')
            assert single['wave_passes'] == sum(v['正方向ネット20分目安達成'] for v in saved_waves)
            for path in (detail_path,causal_path,wave_path): reference[path.relative_to(runner.ROOT).as_posix()] = runner.digest(path)
        for name in records:
            path=directory/(name+'.json'); reference[path.relative_to(runner.ROOT).as_posix()] = runner.digest(path)
        for name in ('全条件の期間集計.json.gz','主再生の完了.json'):
            path=directory/name; reference[path.relative_to(runner.ROOT).as_posix()] = runner.digest(path)
        total_input += cash['全入力数']; total_causal += causal['入力数']; total_waves += waves['波数']
    assert (total_input,total_causal,total_waves) == (25324,3918,7792)
    ledgers={identifier:runner.read(runner.HERE/'ledgers'/(identifier+'.json.gz')) for identifier in assessment.PAIRED_IDS}
    provisional = assessment.assess(index,sessions,fixed['全セッション'],ledgers,verification=False)
    assert provisional == runner.read(runner.HERE/'暫定判定.json')
    final = economic.final_flags(provisional, state_issues)
    assert evidence_kinds == {economic.ORIGINAL:205,economic.DIAGNOSTIC:769}
    for relative,sha in runner.read(runner.HERE/'adaptive_accounting_fixed.json')['原本78SHA256'].items():
        assert runner.digest(runner.ROOT/relative) == sha
        reference[relative] = sha
    for name in ('探索条件の固定.json','起動前監査.json','暫定判定.json','adaptive_assessment_fixed.json'):
        path=runner.HERE/name; reference[path.relative_to(runner.ROOT).as_posix()] = runner.digest(path)
    for relative,sha in reference.items(): assert runner.digest(runner.ROOT/relative)==sha,relative
    evidence=dict(検証完了=False,経済検証完了=True,実装状態契約合格=False,完全実装合格=False,監査完了=False,全条件数=206,補助条件数=768,全会計入力数=total_input,因果入力数=total_causal,
        全波数=total_waves,全境界数=2*total_waves,全主集約と個別集計一致=True,
        主仮説=runner.design.PRIMARY_ID,既知比較の採用候補=final['既知比較の採用候補'],
        探索固定SHA256=runner.digest(runner.HERE/'探索条件の固定.json'),
        ガードSHA256=runner.digest(runner.HERE/'economic_completion_guard.py'),参照資料SHA256=reference,
        状態不適合条件数=final['状態不適合条件数'],状態不一致行数=len(state_issues),状態不一致=state_issues,
        証拠種別件数=evidence_kinds,元ガードSHA256=runner.digest(runner.HERE/'completion_guard.py'),
        全体目標達成=False,現在API取得数=0,現在保存物使用=False)
    return final,evidence


def main() -> None:
    """機能: 未完了資料を拒否し、経済検証と状態不合格を別に保存する。

    引数: なし。返り値: なし (None)。目標全体を完了へ変更しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    args=parser.parse_args()
    if args.prepare:
        prepare();print('経済専用ガード準備。全補助証拠未完成時は正式出力しない。',flush=True);return
    final,evidence=verify()
    runner.save(runner.HERE/'独立判定.json',final)
    evidence['参照資料SHA256'][(runner.HERE/'独立判定.json').relative_to(runner.ROOT).as_posix()]=runner.digest(runner.HERE/'独立判定.json')
    runner.save(runner.HERE/'経済完備監査.json',evidence)
    print('全974条件の経済検証完了。実装状態契約は不合格・採用はfalse。',flush=True)


if __name__ == '__main__':
    main()
