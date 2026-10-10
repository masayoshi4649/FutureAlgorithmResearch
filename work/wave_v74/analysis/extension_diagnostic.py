"""基準跨ぎ返済を外した事後追加の固定代表を独立会計診断する。"""

from collections import defaultdict
from pathlib import Path
import json
import socket
import sys

import numpy as np

sys.dont_write_bytecode = True
from diagnose import load, metric, pause_comparison, digest
from cost_and_exits import pack, REASONS, deny


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
EXT = WORK / 'extension'
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('前16', '後13', '全29')


def main() -> None:
    """機能: 追加240の分布と前半選定三代表の同条件対照を保存する。

    引数: なし。返り値: なし(None)。初回480の結果及び代表は変更しない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    fixed = load(EXT / '追記固定.json')
    selected = load(EXT / '選定.json')
    meta = load(WORK / 'inputs/refmetadata.json')
    assert selected['前16だけで選択'] and selected['後13で変更なし'] and selected['第一段階からの事後追加']
    paths = [EXT / '追記固定.json', EXT / '選定.json', Path(__file__), HERE / 'diagnose.py', HERE / 'cost_and_exits.py']
    additions = [load(path) for path in sorted((EXT / 'results').glob('*.json'))]
    assert len(additions) == 240
    distribution = {}
    for period in PERIODS:
        distribution[period] = {}
        for symbol in SYMBOLS:
            amounts = [a['periods'][period][symbol]['net'] for a in additions]
            distribution[period][symbol] = dict(追加条件数=len(amounts), 黒字数=sum(a > 0 for a in amounts),
                同値数=sum(a == 0 for a in amounts), 赤字数=sum(a < 0 for a in amounts),
                最大収支=max(amounts), 最小収支=min(amounts))
        distribution[period]['両銘柄黒字数'] = sum(all(a['periods'][period][s]['net'] > 0 for s in SYMBOLS) for a in additions)
    ready, features = {}, {}
    for name, target in (('ready', ready), ('features', features)):
        for path in meta['input_paths'][name]:
            target.update(load(ROOT / path))
    # ----------------------------------------
    # 同じ入口・幅・基準の休止なしと、即返済ありを別々に照合する。
    representatives = {}
    for choice in selected['代表']:
        ident = choice['id']
        result_path = EXT / 'results' / (ident + '.json')
        data = load(result_path)
        c = data['config']
        baseline_id = ident.rsplit('_P', 1)[0] + '_P0'
        baseline_path = WORK / 'results' / (baseline_id + '.json')
        baseline = load(baseline_path)
        immediate_id = 'A' + ident[1:]
        immediate_path = WORK / 'results' / (immediate_id + '.json')
        immediate = load(immediate_path)
        for name in ('reference', 'entry_type', 'band', 'width_fraction', 'inverse', 'entry_fraction', 'hold_seconds'):
            assert c[name] == baseline['config'][name] == immediate['config'][name]
        assert c['pause_mode'] == immediate['config']['pause_mode']
        assert not c['exit_on_reverse'] and not baseline['config']['exit_on_reverse'] and immediate['config']['exit_on_reverse']
        ledger_path = EXT / 'ledgers' / (ident + '.pkl')
        ledger = load(ledger_path)
        paths += [result_path, baseline_path, immediate_path, ledger_path]
        records = []
        for key, account in sorted(ledger.items()):
            r, f = ready[key], features[key]
            value = 1000. if key[1] == 'TOPIX' else 10.
            opens = {int(a[2]): a for a in account['orders'] if a[7] == 1}
            closes = {int(a[2]): a for a in account['orders'] if a[7] == 0}
            for trade in account['trades']:
                cid, i, e, side = (int(trade[k]) for k in (0, 1, 2, 3))
                qty, net = int(trade[4]), float(trade[10])
                entry_spread, exit_spread = float(f['ask'][i] - f['bid'][i]), float(f['ask'][e] - f['bid'][e])
                assert entry_spread >= 0 and exit_spread >= 0
                spread = (entry_spread + exit_spread) / 2. * qty * value
                mid_gross = side * float((f['bid'][e] + f['ask'][e] - f['bid'][i] - f['ask'][i]) / 2.) * qty * value
                assert abs(net + spread + float(trade[7] + trade[8]) - mid_gross) < 1e-5
                exit_order = closes[cid]
                code = int(exit_order[6])
                assert code != 5
                records.append(dict(セッション=key[0], 銘柄=key[1], 収支=net,
                    手数料=float(trade[7] + trade[8]), 気配差負担=spread,
                    同時点約定値置換損益=side * float(r['last'][e] - r['last'][i]) * qty * value - float(trade[7] + trade[8]),
                    新規気配差呼値=entry_spread / r['tick'], 返済気配差呼値=exit_spread / r['tick'],
                    新規判断から約定秒=float(r['time_s'][i] - r['time_s'][int(opens[cid][1])]),
                    返済判断から約定秒=float(r['time_s'][e] - r['time_s'][int(exit_order[1])]),
                    保有分=float(r['time_s'][e] - r['time_s'][i]) / 60., 出口理由=REASONS[code]))
        comparison = {}
        for period in PERIODS:
            comparison[period] = {}
            for symbol in SYMBOLS:
                part = [a for a in records if a['セッション'] in fixed[period] and a['銘柄'] == symbol]
                own = pack(part)
                summary = data['periods'][period][symbol]
                assert own['取引数'] == summary['trades'] and abs(own['収支'] - summary['net']) < 1e-5
                assert abs(own['気配差負担'] - summary['spread_drag']) < 1e-5
                comparison[period][symbol] = dict(選定代表=metric(summary),
                    同条件休止なし=dict(ID=baseline_id, **metric(baseline['periods'][period][symbol])),
                    休止なしに対する変化=pause_comparison(baseline['periods'][period][symbol], summary),
                    同条件基準跨ぎ即返済あり=dict(ID=immediate_id, **metric(immediate['periods'][period][symbol])),
                    気配差と金額の照合=own,
                    出口別={name: pack([a for a in part if a['出口理由'] == name]) for name in REASONS.values()})
        representatives[ident] = dict(前半選定=choice, 固定設定=c, 期間別=comparison)
    # ----------------------------------------
    # 初回結果を見た後の追加であり、後半が完全未知だという説明は行わない。
    output = dict(第一段階結果保持=True, 第二段階の結果閲覧前固定=True,
        事後追加=True, 代表差替えなし=True, 条件追加なし=True, API取得数=0, 実注文数=0,
        分離='基準の反転は新規方向だけを変え、保有はトレール・六十分・場内返済まで続ける。反転売買や両建ては追加しない。',
        約定感度='同じ売買行を中値へ置換した説明用の差。入口、トレール、休止の再実行ではない。',
        解釈='初回結果を閲覧した後の仕様切分け。前16選定と後13固定確認を行うが、後13を完全未知の将来検証とは呼ばない。',
        追加240の黒字分布=distribution, 前半固定代表=representatives,
        入力SHA256={str(p.relative_to(ROOT)): digest(p) for p in paths})
    path = HERE / '第二段階の保有継続と休止の分析.json'
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(全検査通過=True, 追加条件数=len(additions), 代表=list(representatives)), ensure_ascii=False))


if __name__ == '__main__':
    main()
