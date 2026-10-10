"""全条件の保存資料と独立検査を結び、経済合否と監査完了を分離する。"""

from __future__ import annotations

from copy import deepcopy
import argparse

import adaptive_runner as runner
import adaptive_assessment as assessment
import assess_results
from adaptive_independent_statistics import equal


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

    引数: なし。返り値: 正式判定と完備証跡 (tuple[dict,dict])。
    """
    fixed = runner.prepare()
    startup = runner.read(runner.HERE/'起動前監査.json')
    assert startup['実行可能'] and startup['探索固定SHA256'] == runner.digest(runner.HERE/'探索条件の固定.json')
    for relative,sha in startup['SHA256'].items(): assert runner.digest(runner.ROOT/relative) == sha, relative
    reference = {}
    cash_revision(reference)
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
    del raw
    assert set(lengths) == expected_keys
    all_raw_rows = sum(lengths.values())
    wave_keys = {(w['id'],s) for w in fixed['指定波'] for s in runner.SYMBOLS}
    for destination, specs, causal_count in (('',fixed['conditions'],846),('supplementary',fixed['supplementary_conditions'],3072)):
        directory = runner.HERE/destination
        records = {name:runner.read(directory/(name+'.json')) for name in (
            'adaptive_accounting_audit','adaptive_causality_audit','adaptive_wave_audit')}
        cash, causal, waves = (records[k] for k in ('adaptive_accounting_audit','adaptive_causality_audit','adaptive_wave_audit'))
        assert cash['全監査合格'] and cash['対象条件数'] == len(specs) and cash['全入力数'] == 26*len(specs)
        assert cash['全原本行会計数'] == len(specs)*all_raw_rows
        for key in ('全枠会計一致','全予約と新根拠一致','同約定両建て全行一致','全予算予約一致','全保存統計一致','全台帳配列一致','元終了以前','全分岐独立一致','全成熟注文独立一致','全組R超過独立一致'):
            assert cash[key] is True, key
        assert cash['監査固定SHA256'] == runner.digest(runner.HERE/'adaptive_accounting_fixed.json')
        for relative, sha in cash['参照SHA256'].items():
            assert runner.digest(runner.ROOT/relative) == sha, relative
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
            detail_path = directory/'adaptive_accounting_details'/(identifier+'.json.gz')
            detail = runner.read(detail_path)
            certificate = mappings['cash'][identifier]
            assert certificate['全監査合格'] and certificate['全入力数'] == 26
            assert certificate['全原本行会計数'] == all_raw_rows
            assert certificate['監査固定SHA256'] == cash['監査固定SHA256']
            assert certificate['実体SHA256'] == runner.digest(detail_path)
            assert detail['全監査合格'] and detail['全入力数'] == 26 and detail['spec'] == spec
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
    final = assessment.assess(index,sessions,fixed['全セッション'],ledgers,verification=True)
    expected=deepcopy(provisional)
    expected['監査完了']=True; expected['既知比較の採用候補']=bool(expected['経済目安合格'])
    assert final == expected
    for relative,sha in runner.read(runner.HERE/'adaptive_accounting_fixed.json')['原本78SHA256'].items():
        assert runner.digest(runner.ROOT/relative) == sha
    for name in ('探索条件の固定.json','起動前監査.json','暫定判定.json','adaptive_assessment_fixed.json'):
        path=runner.HERE/name; reference[path.relative_to(runner.ROOT).as_posix()] = runner.digest(path)
    for relative,sha in reference.items(): assert runner.digest(runner.ROOT/relative)==sha,relative
    evidence=dict(検証完了=True,全条件数=206,補助条件数=768,全会計入力数=total_input,因果入力数=total_causal,
        全波数=total_waves,全境界数=2*total_waves,全主集約と個別集計一致=True,
        主仮説=runner.design.PRIMARY_ID,既知比較の採用候補=final['既知比較の採用候補'],
        探索固定SHA256=runner.digest(runner.HERE/'探索条件の固定.json'),
        ガードSHA256=runner.digest(runner.HERE/'completion_guard.py'),参照資料SHA256=reference,
        全体目標達成=False,現在API取得数=0,現在保存物使用=False)
    return final,evidence


def main() -> None:
    """機能: 未完了資料を拒否し、完全なときだけ正式判定を保存する。

    引数: なし。返り値: なし (None)。目標全体を完了へ変更しない。
    """
    final,evidence=verify()
    runner.save(runner.HERE/'独立判定.json',final)
    evidence['参照資料SHA256'][(runner.HERE/'独立判定.json').relative_to(runner.ROOT).as_posix()]=runner.digest(runner.HERE/'独立判定.json')
    runner.save(runner.HERE/'完備監査.json',evidence)
    print('全974条件の独立検算完了。採用候補='+str(final['既知比較の採用候補']),flush=True)


if __name__ == '__main__':
    main()
