"""公式カレンダーで分けた21予定営業日を、保存窓だけから参考集計する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

from describe_clocks150 import paired

OUT=Path(__file__).resolve().parent
DEFINITION_SHA='972555f81ac240809e6225a1606f30e3f777832c0ff9b12a3a2ea2641519c8ae'


def main() -> None:
    """元25場を変更せず予定営業日と休場日の記述を保存する。

    引数: なし。
    返り値: None。金融再生を行わない参考JSONを作る。
    """
    specification=OUT/'現物営業日の参考集計定義150.json'
    assert hashlib.sha256(specification.read_bytes()).hexdigest()==DEFINITION_SHA
    definition=json.loads(specification.read_text('utf-8'))
    holidays=set(definition['対象期間の現物休場日'])
    source=OUT/'時刻前後の市場診断150.json';before=hashlib.sha256(source.read_bytes()).hexdigest()
    saved=json.loads(source.read_text('utf-8'))
    business=[s for s in saved['sessions'] if s['kind']=='デイ' and s['session'][:10] not in holidays]
    closed=[s for s in saved['sessions'] if s['kind']=='デイ' and s['session'][:10] in holidays]
    assert len(business)==21 and len(closed)==4
    comparisons=[('イベント対直後30分','イベント30分','直後対照30分'),
                 ('開始後15分対次15分','直後15分','対照15〜30分'),
                 ('直前15分対開始後15分','直前15分','直後15分')]
    summaries={}
    for name,rows in [('予定営業日21日',business),('現物休場4日',closed)]:
        summaries[name]={}
        for window in ['直前15分','直後15分','対照15〜30分']:
            summaries[name][window]={metric:float(np.mean([r['windows'][window][metric] for r in rows]))
                for metric in ['abs_change_mean','range_mid','spread_median','jump_50_rate','jump_100_rate','jump_200_rate']}
    result=dict(definition_sha256=DEFINITION_SHA,original_source_sha256=before,
        additional_after_primary_analysis=True,primary_25_sessions_unchanged=True,
        financial_replays=0,business_sessions=[s['session'] for s in business],
        closed_sessions=[s['session'] for s in closed],source_url=definition['公式出典'],
        comparisons={name:paired(business,a,b) for name,a,b in comparisons},window_means=summaries)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    (OUT/'現物営業日21場の参考診断150.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
    print(json.dumps({'business':21,'closed':4,'primary_unchanged':True,'financial_replays':0}))


if __name__=='__main__':
    main()
