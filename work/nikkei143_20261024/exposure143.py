"""両建ての時間を分け、保有時間の増加が完全相殺だけでないか確認する。"""

import numpy as np
import common143 as shared


def exposure(orders, ready):
    """
    機能: 深夜を除いた総保有・買売相殺後の保有時間を別々に積分する。
    引数: orders(ndarray)、ready(dict)は保存約定と場時刻。
    返り値: dictは各保有率と平均総枚数・平均方向枚数。
    """
    start = last = float(ready['start'])
    duration = (420 if ready['session'].endswith('_Day') else 600)*60.
    gross = net = 0
    gross_seconds = net_seconds = gross_units = net_units = 0.
    for row in orders:
        now = float(ready['time_s'][int(row[0])])
        seconds = max(0., min(now,start+duration)-max(last,start))
        gross_seconds += seconds if gross else 0.
        net_seconds += seconds if net else 0.
        gross_units += seconds*gross
        net_units += seconds*abs(net)
        gross += int(row[4]) if row[7] else -int(row[4])
        net += int(row[3]*row[4])
        assert gross >= abs(net)
        last=now
    assert gross == net == 0
    return dict(gross_holding_ratio=gross_seconds/duration, net_holding_ratio=net_seconds/duration,
        fully_offset_holding_ratio=(gross_seconds-net_seconds)/duration,
        mean_gross_quantity=gross_units/duration, mean_abs_net_quantity=net_units/duration)


def main():
    """
    機能: 最終報告の各候補について保存注文だけから保有の相殺量を検算する。
    引数: なし。
    返り値: None。売買判断を再生成しない。
    """
    report=shared.read(shared.HERE/'report_data143.json')
    lookup={}
    for stage in ('第一巡','第二巡','第三巡'):
        data=shared.read(shared.HERE/f'{stage}結果143.json')
        files={r['session']:r for r in data['cache']}
        for row in data['rows']:
            lookup[row['method'],row['session']]=files[row['session']]
    packets,_,_=shared.material(); rows=[]
    for item in packets:
        scene=item['session']; packet=shared.packet_from(item)
        ready=packet['inputs'][scene,'NK225']
        for selected in (r for r in report['rows'] if r['session']==scene):
            source=selected['source_method']; file=lookup[source,scene]
            path=shared.ROOT/file['path']; assert shared.prior.ref(path)['sha256']==file['sha256']
            with np.load(path) as data:
                result=exposure(data[source],ready)
            assert abs(result['gross_holding_ratio']-selected['holding_ratio'])<1e-8
            rows.append(dict(session=scene,method=selected['method'],**result))
    summary=[]
    for method in dict.fromkeys(r['method'] for r in rows):
        subset=[r for r in rows if r['method']==method]
        summary.append(dict(method=method,**{k:float(np.mean([r[k] for r in subset])) for k in
            ('gross_holding_ratio','net_holding_ratio','fully_offset_holding_ratio','mean_gross_quantity','mean_abs_net_quantity')}))
    shared.save(shared.HERE/'報告候補の両建て相殺確認143.json',dict(新金融再生=0,summary=summary,rows=rows))
    print(summary)


if __name__=='__main__':
    main()
