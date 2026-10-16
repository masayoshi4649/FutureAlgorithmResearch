"""根から許可されたS03/T01小射影一件だけを保全し、場単位統計を作る。"""

from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path

import cluster_bootstrap


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
STATUSES=('順先','逆先','窓末未決','EOF未決','基準不可')


def digest(raw: bytes) -> str:
    """
    機能: 同一読取bytesのSHA256を計算する。
    引数: raw(bytes)。
    返り値: str は指紋。
    """
    return hashlib.sha256(raw).hexdigest()


def normalize(session: str,row: dict) -> dict:
    """
    機能: 同一risk10の件数と固定方向対照を、純統計の六列へ射影する。
    引数: session(str)、row(dict) はriskの全体counts直置き。
    返り値: dict。未決を勝敗へ配賦しない。
    """
    assert row['n']==sum(row[name] for name in STATUSES)
    for direction in ('常時買い','常時売り'):
        assert row[direction]['n']==row['n']==sum(row[direction][name] for name in STATUSES)
    return dict(session=session,n=row['n'],favorable=row['順先'],adverse=row['逆先'],
        unresolved=sum(row[name] for name in STATUSES[2:]),
        always_long_favorable=row['常時買い']['順先'],always_short_favorable=row['常時売り']['順先'])


def count_summary(row: dict) -> dict:
    """
    機能: 期間表から候補と固定方向の率を別算術で再計算する。
    引数: row(dict) はmerge型riskの全体/常時買い/常時売り。
    返り値: dict はn・順先率・解決率・固定方向差。
    """
    all=row['全体'];n=all['n'];resolved=all['順先']+all['逆先']
    assert n==sum(all[name] for name in STATUSES)
    result=dict(n=n,favorable=all['順先'],adverse=all['逆先'],unresolved=n-resolved,
        favorable_rate_all=float(Fraction(all['順先'],n)) if n else None,
        resolution_rate=float(Fraction(resolved,n)) if n else None,
        always_long_favorable=row['常時買い']['順先'],always_short_favorable=row['常時売り']['順先'])
    result['difference_from_best_fixed']=float(Fraction(all['順先']-max(result['always_long_favorable'],result['always_short_favorable']),n)) if n else None
    return result


def main() -> None:
    """
    機能: 小射影を一回だけ読み、同bytesをparse前保全してbootstrapと対照を保存する。
    引数: なし。入力path/SHAは本文初読前に固定した所有planを使用する。
    返り値: None。元市場・元結果・prepared・金融・APIを読まない。
    """
    plan_path=HERE/'S03事後候補の一読と十場統計の解析固定.json'
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    assert digest((HERE/'cluster_bootstrap.py').read_bytes())==plan['source_SHA256']
    copy=HERE/'根S03小射影v2の同bytes私有コピー.json'
    assert not copy.exists()
    source=(ROOT/plan['入力']).resolve()
    assert source.is_relative_to(ROOT/'work/topix10pt_20261016/result_audit') and source.stat().st_size<=1024*1024
    raw=source.read_bytes();assert digest(raw)==plan['SHA256']
    copy.write_bytes(raw)
    value=json.loads(raw.decode('utf-8'))
    sessions=list(value['S03_到達経路集計']['各場'])
    assert len(sessions)==len(set(sessions))==10
    output={};context={}
    for case in ('S03','T01'):
        rows=value['by_session'][case]
        assert len(rows)==37 and len({row['session'] for row in rows})==37
        assert [row['session'] for row in rows[-10:]]==sessions
        own={row['session']:row for row in rows}
        clusters=[normalize(session,own[session]['risks'][2]) for session in sessions]
        computed=cluster_bootstrap.analyse(clusters)
        saved=value['periods'][case]['別枠10']['risks'][2]
        for direction in ('全体','買い','売り','常時買い','常時売り'):
            items=[own[s]['risks'][2] if direction=='全体' else own[s]['risks'][2][direction] for s in sessions]
            for name in (*STATUSES,'n','resolved'):
                assert sum(row[name] for row in items)==saved[direction][name]
        summary=count_summary(saved)
        for name in ('n','favorable','adverse','unresolved','favorable_rate_all','resolution_rate',
                     'always_long_favorable','always_short_favorable'):
            assert computed['observed'][name]==summary[name]
        output[case]=dict(clusters=clusters,analysis=computed)
        context[case]={period:[dict(risk=row['逆行幅'],**count_summary(row)) for row in period_value['risks']]
            for period,period_value in value['periods'][case].items()}
    result=dict(全合格=True,入力SHA256=digest(raw),解析固定SHA256=digest(plan_path.read_bytes()),
        reader_SHA256=digest(Path(__file__).read_bytes()),bootstrap_source_SHA256=plan['source_SHA256'],
        cases=output,記述対照=context,
        根小射影読取=1,元結果=0,原市場=0,prepared=0,新戦略測定=0,金融=0,API=0,
        留保='S03/risk10を別枠結果から事後に発見した後の解析。正式選択3の差替えなし。十場再標本は探索補正済み検定や未来60%の保証ではない。')
    target=HERE/'S03十場再標本と同時点固定方向差の小検査.json'
    assert not target.exists();target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,SHA256=digest(target.read_bytes()),cases={key:{
        'observed':row['analysis']['observed'],
        'rate_interval':row['analysis']['bootstrap']['favorable_rate_all'],
        'delta_interval':row['analysis']['bootstrap']['difference_from_original_best_fixed'],
        'reselected_delta_interval':row['analysis']['bootstrap']['difference_from_resampled_best_fixed']}
        for key,row in output.items()}),ensure_ascii=False))


if __name__=='__main__':main()
