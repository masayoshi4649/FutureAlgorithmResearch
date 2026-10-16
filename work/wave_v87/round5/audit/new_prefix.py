"""固定後の新強度二代表を、実原板の未来切断で独立検査する。"""

import hashlib
import json
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from baseline_prefix import strategy, catalog, clip, compare, WORK, ROOT


def main():
    """
    機能: 事前固定後の自己.25と双方.5について過去の売買・影・支持を切断照合する。
    引数: なし。
    返り値: None。新しい成績の順位付けは行わず、監査JSONを保存する。
    """
    fixed = json.loads((WORK/'事前固定.json').read_text(encoding='utf-8'))
    for name, expected in fixed['code_SHA256'].items():
        assert strategy.prepare.old.sha(ROOT/name) == expected
    inputs, signals, hashes = strategy.prepare.old.load_inputs(verify=True)
    assert hashes == fixed['input_SHA256']
    sessions = ('2026-09-25_Day', '2026-10-08_Night')
    inputs = {key:value for key,value in inputs.items() if key[0] in sessions}
    signals = {name:{key:value for key,value in values.items() if key in inputs}
               for name,values in signals.items()}
    features = strategy.initialize(inputs, signals)
    configs = [config for config in fixed['catalog'] if config['id'] in ('GU_F1_H025', 'P1_F3_H050')]
    assert len(configs) == 2
    rows = []
    for key, ready in sorted(inputs.items()):
        n = len(ready['last'])
        for observed in (True, False):
            for config in configs:
                full, _ = strategy.play(config, ready, features[key], observed)
                cuts = {int(n*.37), int(n*.78)}
                entries = full['orders'][full['orders'][:,7] == 1]
                for order in entries[:2]:
                    row = int(order[0])
                    cuts.update((max(2,row), min(n-1,row+1)))
                permit = full['support_events']
                positive = permit[(permit[:,1] != 0)&(permit[:,3] == 1)]
                for event in positive[:1]:
                    row = int(event[0])
                    cuts.update((max(2,row), min(n-1,row+1)))
                checked = 0
                for count in sorted(cuts):
                    part, _ = strategy.play(config, clip(ready,count,n), clip(features[key],count,n), observed)
                    checked += compare(full,part,count)
                rows.append(dict(セッション=key[0], 銘柄=key[1], ID=config['id'], 観測約定=observed,
                                 切断数=len(cuts), 過去配列一致数=checked, 新規数=len(entries), 合格=True))
                print(key, config['id'], observed, '新強度の未来切断一致', flush=True)
    for name, expected in fixed['code_SHA256'].items():
        assert strategy.prepare.old.sha(ROOT/name) == expected
    output = dict(全合格=True, 固定主GU自己025とP1双方050=True,
                  条件口座数=len(rows), 切断数=sum(r['切断数'] for r in rows),
                  過去配列一致数=sum(r['過去配列一致数'] for r in rows),
                  原板に新規が発生した条件口座数=sum(r['新規数'] > 0 for r in rows),
                  入力SHA256=hashes, 検査=rows,
                  固定記録SHA256=strategy.prepare.old.sha(WORK/'事前固定.json'),
                  監査器SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  限界='前16と後14の各一場で保有・発注の前後を切断した因果検査。全30は既知であり、未知期間の予測力を証明する検査ではない。')
    (HERE/'新強度二代表の実原本売買未来切断.json').write_text(
        json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
