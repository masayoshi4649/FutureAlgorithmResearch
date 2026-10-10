"""全主案と全対照の完備・会計・旧同値を確認してから採否を計算する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import math

import numpy as np

import runner

HERE, ROOT = runner.HERE, runner.ROOT
FOLDERS = (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('audits', '.json.gz'),
           ('waves', '.json.gz'), ('causality', '.json'), ('gate_use', '.json'), ('summaries', '.json'))


def destination(spec: dict):
    """機能: 条件の事前固定された保存先を返す。

    引数: spec(dict)。返り値: 作業内パス(Path)。
    """
    return HERE/'supplementary' if spec['role'] == 'supplementary' else HERE


def required(spec: dict) -> set[str]:
    """機能: 全条件で必須の七成果パス集合を生成する。

    引数: spec(dict)。返り値: ルート相対パス(set[str])。
    """
    identifier = spec['id']
    assert identifier and '/' not in identifier and '\\' not in identifier
    return {(destination(spec)/folder/(identifier+suffix)).relative_to(ROOT).as_posix()
            for folder, suffix in FOLDERS}


def record_check(spec: dict, record: dict, frozen_sha: str) -> None:
    """機能: 欠落・別条件・旧同値件数の付替えを拒否する。

    引数: spec/record(dict)、frozen_sha(str)。返り値: なし(None)。
    """
    assert record['id'] == spec['id'] and record['全合格'] is True
    assert record['探索固定SHA256'] == frozen_sha
    assert (record['全入力数'],record['因果入力数']) == (26,4)
    assert type(record['旧単一窓一致入力数']) is int
    assert record['旧単一窓一致入力数'] == (26 if runner.legacy_id(spec) else 0)
    assert set(record['出力SHA256']) == required(spec)
    assert all(isinstance(v,str) and len(v)==64 and set(v)<=set('0123456789abcdef')
               for v in record['出力SHA256'].values())


def keyed(rows: list[dict], expected: set[tuple]) -> dict:
    """機能: 全26場銘柄の欠落と重複を拒否する。

    引数: rows(list[dict])、expected(set[tuple])。返り値: 場銘柄辞書(dict)。
    """
    result = {(r['session'],r['symbol']):r for r in rows}
    assert len(rows) == len(result) == len(expected) == 26 and set(result) == expected
    return result


def wave_check(identifier: str, rows: list[dict], episodes: list[dict]) -> None:
    """機能: 固定四波×二銘柄を一意性と保存判定から照合する。

    引数: identifier(str)、rows/episodes(list[dict])。返り値: なし(None)。
    """
    expected = {(e['id'],e['session'],s):e for e in episodes for s in runner.old.SYMBOLS}
    actual = {(r['wave'],r['session'],r['symbol']):r for r in rows}
    assert len(episodes)==4 and len(expected)==len(actual)==len(rows)==8 and set(actual)==set(expected)
    for key,row in actual.items():
        e = expected[key]
        assert row['method']==identifier
        assert (row['波方向'],row['開始'],row['終了'],row['波名'])==(e['side'],e['start'],e['end'],e['name'])
        duration = (datetime.fromisoformat(e['end'])-datetime.fromisoformat(e['start'])).total_seconds()/60
        assert math.isfinite(row['区間分']) and abs(row['区間分']-duration)<=1e-8
        minutes = row['正方向ネット保有分']
        assert math.isfinite(minutes) and -1e-8<=minutes<=duration+1e-8
        assert type(row['正方向ネット20分目安達成']) is bool
        assert row['正方向ネット20分目安達成'] == (minutes>=20-1e-9)


def array_check(ledger: dict) -> None:
    """機能: 保存配列を型と形状ごと復元し、全指紋へ結び付ける。

    引数: ledger(dict)。返り値: なし(None)。
    """
    assert set(ledger['result_fingerprints']) == set(runner.FIELDS)
    assert set(ledger['shadow_fingerprints']) == set(runner.reference.EXPECTED_SHADOW_FIELDS)
    for source,field,entry in [(ledger,f,ledger['result_fingerprints'][f]) for f in runner.STORED]+[
        (ledger,'shadow_'+f,ledger['shadow_fingerprints'][f]) for f in ('cycles','orders')]:
        widths = dict(trades=11,cycles=10,orders=8,prepare_events=7,entry_preparations=4,
            slot_events=11,adjustment_events=11,budget_events=8,branch_events=10,
            shadow_orders=8,shadow_cycles=10)
        assert entry['dtype']=='<f8',field
        assert isinstance(entry['shape'],list) and all(type(v) is int and v>=0 for v in entry['shape'])
        if field=='stats':
            assert entry['shape']==[11]
        else:
            assert len(entry['shape'])==2 and entry['shape'][1]==widths[field],field
        value = np.asarray(source[field],dtype=np.dtype(entry['dtype']))
        if not value.size and field!='stats':
            assert source[field]==[] and entry['shape'][0]==0
            value=value.reshape(entry['shape'])
        else:
            assert list(value.shape)==entry['shape'],field
        assert hashlib.sha256(value.tobytes()).hexdigest()==entry['SHA256'],field


def money_check(ledger: dict, row: dict) -> None:
    """機能: 返済価格から金額と枚数を再計算し、保有上限を確認する。

    引数: ledger/row(dict)。返り値: なし(None)。
    """
    trades = np.asarray(ledger['trades'],float).reshape((-1,11))
    pnl = (trades[:,5]-trades[:,4])*trades[:,2]*trades[:,3]*ledger['config']['point_value']
    computed = dict(gross_profit_yen=float(pnl[pnl>0].sum()),gross_loss_yen=float(-pnl[pnl<0].sum()),
        net_yen=float(pnl.sum()),profit_units=int(trades[pnl>0,3].sum()),loss_units=int(trades[pnl<0,3].sum()),
        zero_units=int(trades[pnl==0,3].sum()),closed_units=int(trades[:,3].sum()))
    assert all(abs(row[k]-v)<=1e-6 for k,v in computed.items())
    assert row['max_long']<=ledger['config']['audit_cap'] and row['max_short']<=ledger['config']['audit_cap']


def complete() -> dict:
    """機能: 主35・補助128の全資料を結び付けて固定された採否を実行する。

    引数: なし。返り値: 完備証跡(dict)。未知相場への有効性は認定しない。
    """
    fixed = runner.read(HERE/'探索条件の固定.json')
    runner.verify(fixed['参照資料SHA256'])
    assert fixed['conditions']==runner.design.catalog() and fixed['supplementary']==runner.design.supplementary()
    specs = fixed['conditions']+fixed['supplementary']
    names = fixed['全セッション']; assert names[6:]==fixed['後半7セッション']
    expected = {(n,s) for n in names for s in runner.old.SYMBOLS}
    sha = runner.digest(HERE/'探索条件の固定.json')
    references = {}

    def bind(path, expected_sha=None):
        """機能: 全実体を前後照合対象へ競合なく追加する。

        引数: path(Path)、expected_sha(str|None)。返り値: なし(None)。
        """
        relative,actual = path.relative_to(ROOT).as_posix(),runner.digest(path)
        assert expected_sha is None or actual==expected_sha,relative
        assert relative not in references or references[relative]==actual,relative
        references[relative]=actual

    records={}; total_rows=0
    for directory,count,legacy in ((HERE,35,156),(HERE/'supplementary',128,0)):
        path=directory/'主再生の完了.json'; finished=runner.read(path); bind(path)
        assert finished['全合格'] is True and finished['探索固定SHA256']==sha
        assert (finished['全条件数'],finished['全入力数'],finished['因果入力数'],finished['旧単一窓一致入力数'])==(count,count*26,count*4,legacy)
        groups={r['id']:r for r in finished['records']}
        expected_ids={s['id'] for s in specs if destination(s)==directory}
        assert len(groups)==len(finished['records'])==count and set(groups)==expected_ids
        assert not (set(records)&set(groups)); records.update(groups)
        total_rows+=finished['全原本行会計数']
    index,session_rows,ledgers_all = {},{},{}
    accounts=causal_count=legacy_count=wave_count=raw_rows=0
    for spec in specs:
        identifier=spec['id']; directory=destination(spec)
        path=directory/'completed'/(identifier+'.json'); record=runner.read(path); bind(path)
        assert record==records[identifier]; record_check(spec,record,sha)
        for relative,digest in record['出力SHA256'].items(): bind(ROOT/relative,digest)
        payload={f:runner.read(directory/f/(identifier+s)) for f,s in FOLDERS}
        rows=keyed(payload['sessions'],expected); ledgers=keyed(payload['ledgers'],expected)
        proofs=keyed(payload['audits'],expected); gates=keyed(payload['gate_use'],expected)
        prior_id=runner.legacy_id(spec)
        prior=keyed(runner.read(HERE.parent/'wave_v38/ledgers'/(prior_id+'.json.gz')),expected) if prior_id else {}
        for key in expected:
            ledger=ledgers[key]; row=rows[key]; proof=proofs[key]; usage=gates[key]
            array_check(ledger); money_check(ledger,row)
            assert all(proof[f] is True for f in runner.PROOF_FLAGS)
            assert proof['全統計一致'] is True and proof['原本行数']>0
            assert proof['原本行数']==fixed['原本行数']['|'.join(key)]
            assert proof['旧単一窓一致'] is bool(prior_id)
            assert usage['全源行維持'] is True and usage['fingerprints']==ledger['gate_fingerprints']
            assert usage['arm_events']==ledger['arm_events']
            identity=usage['初期準備と建玉一致']
            assert all(identity[f] is True for f in ('全初回新規完全一致','全組初期ATR予算一致','全組影以前返済'))
            assert identity['影全組数']==len(ledger['shadow_cycles'])==len(ledger['cycles'])
            if prior_id:
                assert ledger['result_fingerprints']==prior[key]['result_fingerprints']
                assert ledger['shadow_fingerprints']==prior[key]['shadow_fingerprints']
                legacy_count+=1
        count_rows=sum(r['原本行数'] for r in proofs.values())
        assert count_rows==record['全原本行会計数']; raw_rows+=count_rows
        checks=payload['causality']
        assert len(checks)==4 and {(r['session'],r['symbol']) for r in checks}=={(n,s) for n in runner.REPRESENTATIVE for s in runner.old.SYMBOLS}
        assert all(r[f] is True for r in checks for f in ('先頭切断一致','未来変更一致','上下反射一致'))
        summary=payload['summaries']; assert summary['spec']==spec and summary['探索固定SHA256']==sha
        for period,subset in (('all_symbols',names),('symbols',names[6:])):
            runner.audit.statistics.equal(runner.old.period(payload['sessions'],subset),summary[period],'完備期間集計')
        waves=payload['waves']; wave_check(identifier,waves,fixed['指定波'])
        assert summary['wave_passes']==sum(w['正方向ネット20分目安達成'] for w in waves)
        index[identifier]=summary; session_rows[identifier]=payload['sessions']; ledgers_all[identifier]=payload['ledgers']
        accounts+=26; causal_count+=4; wave_count+=8
    assert (len(index),accounts,causal_count,legacy_count,wave_count)==(163,4238,652,156,1304)
    assert raw_rows==total_rows
    runner.verify(references)
    assessment=runner.module('profit_gate_assessment',HERE/'assessment.py')
    decision=assessment.assess(index,session_rows,names,ledgers_all,verification=True)
    runner.save(HERE/'assess_results.json',decision)
    bind(HERE/'探索条件の固定.json'); bind(HERE/'assess_results.json')
    runner.verify(fixed['参照資料SHA256']); runner.verify(references)
    result=dict(全合格=True,主条件数=35,補助条件数=128,全条件数=163,全入力数=accounts,
        全原本行会計数=raw_rows,因果入力数=causal_count,旧単一窓一致入力数=legacy_count,
        全指定波数=wave_count,必須出力数=1141,全原本場内返済=True,探索固定SHA256=sha,
        参照資料SHA256=fixed['参照資料SHA256'],出力SHA256=references,現在API取得数=0,
        保存ライブ使用=False,未知での有効性確認=False,全体目標達成=False)
    runner.save(HERE/'完備監査.json',result)
    return result


if __name__=='__main__':
    result=complete()
    print(f"全{result['全条件数']}条件・{result['全入力数']}入力の完備監査に合格。",flush=True)
