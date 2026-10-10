"""保存済み全420の波計測を、事前に決めた鮮度対照へ対応させる。"""

from __future__ import annotations

import numpy as np

import episode_audit as audit


def main() -> None:
    """機能: 全4,032波対応差と12入口等重みの集計を保存する。

    引数: なし。返り値: なし (None)。実行済み波結果だけを読み、再生・選抜・追加通信は行わない。
    """
    audit.deny_network()
    frozen = audit.freeze()
    report = audit.runner.read(audit.HERE / 'episode_audit.json')
    fixed = audit.runner.read(audit.HERE / '探索条件の固定.json')
    assert report['計測固定SHA256'] == audit.runner.digest(audit.HERE / 'episode_audit_fixed.json')
    index = {(row['method'], row['wave'], row['symbol']): row for row in report['結果']}
    fields = ('正方向信号分', '逆方向信号分', '中立信号分', '正方向管理分', '逆方向管理分', '中立管理分',
              '正方向ネット保有分', '逆方向ネット保有分', '正方向枚数分', '逆方向枚数分', '時価損益差円')
    differences = []
    for signal in fixed['signals']:
        for manager in fixed['managers']:
            for newer, baseline in audit.PAIRS:
                for wave in audit.metrics.EPISODES:
                    for symbol in ('TOPIX', 'NK225'):
                        a = index[(signal['id'] + '__' + manager['id'] + '__' + newer, wave['id'], symbol)]
                        b = index[(signal['id'] + '__' + manager['id'] + '__' + baseline, wave['id'], symbol)]
                        differences.append({'signal': signal['id'], 'manager': manager['id'], 'comparison': newer + '-' + baseline,
                                            'wave': wave['id'], 'symbol': symbol,
                                            'philosophy': 'EMA' if signal['params']['main_kind'].startswith('ema') else signal['params']['main_kind'],
                                            **{field + 'の差': a[field] - b[field] for field in fields},
                                            '比較側20分目安': a['正方向ネット20分目安達成'], '基準側20分目安': b['正方向ネット20分目安達成']})
    assert len(differences) == 4032
    groups = []
    for manager in fixed['managers']:
        for newer, baseline in audit.PAIRS:
            for wave in audit.metrics.EPISODES:
                for symbol in ('TOPIX', 'NK225'):
                    rows = [row for row in differences if row['manager'] == manager['id'] and row['comparison'] == newer + '-' + baseline and row['wave'] == wave['id'] and row['symbol'] == symbol]
                    assert len(rows) == 12
                    families = sorted({row['philosophy'] for row in rows})
                    assert len(families) == 5
                    keys = [field + 'の差' for field in fields]
                    means = {family: {key: float(np.mean([row[key] for row in rows if row['philosophy'] == family])) for key in keys} for family in families}
                    groups.append({'manager': manager['id'], 'comparison': newer + '-' + baseline, 'wave': wave['id'], 'symbol': symbol,
                                   '12入口中央値': {key: float(np.median([row[key] for row in rows])) for key in keys},
                                   '比較側20分達成数': sum(row['比較側20分目安'] for row in rows),
                                   '基準側20分達成数': sum(row['基準側20分目安'] for row in rows),
                                   '5思想の内部平均': means, '5思想等重み中央値': {key: float(np.median([means[family][key] for family in families])) for key in keys}})
    assert len(groups) == 336
    audit.runner.save(audit.HERE / 'episode_contrasts.json',
                      {'用途': '結果前固定した6対照を全波・全管理へ一律適用。遅延最良選択ではない。',
                       '対応差': differences, '全入口等重み集計': groups,
                       '元波結果SHA256': audit.runner.digest(audit.HERE / 'episode_audit.json'),
                       '計測固定SHA256': audit.runner.digest(audit.HERE / 'episode_audit_fixed.json'),
                       'API取得数': 0, '現在保存物使用': False})
    assert audit.freeze() == frozen
    print('全4,032波対応差・336等重み群を保存', flush=True)


if __name__ == '__main__':
    main()
