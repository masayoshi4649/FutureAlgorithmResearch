"""売買収支を読む前に、監査済み入口の候補頻度を固定して記録する。"""

from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import design

HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 20基本条件の機会数を集計し、主案の活動上限を収支前に明示する。

    引数: なし。返り値: なし (None)。口座再生・将来損益参照は行わない。
    """
    path = HERE / 'check_entry_signals_details.json.gz'
    rows = json.loads(gzip.decompress(path.read_bytes()))
    assert len(rows) == 6760
    methods = [s for s in design.catalog() if s['id'] in {f'F{i:02}' for i in range(20)}]
    assert len(methods) == 20
    result = {}
    lines = ['# 売買前に確認した候補頻度', '',
             '主F01・副F02とも、両市場で全13セッションの候補が20回に届かない。',
             '同じ候補から繰り返し新規を作らない注文器なので、従来からの決済20回という基礎目安は、この時点で通過できない。',
             '活動基準は変更せず、数量情報・価格対照・品質変更による損益差を調べるため、予定した260条件の再生は実施する。',
             '候補数は実約定数・勝ち数・利益ではない。少数機会の好成績だけで採用へ進めない。', '',
             '|方式|TOPIX候補／候補がある場|NK候補／候補がある場|', '|---|---:|---:|']
    for spec in methods:
        result[spec['id']] = {}
        display = []
        for symbol in ('TOPIX','NK225'):
            group = [r for r in rows if r['id'] == spec['id'] and r['symbol'] == symbol]
            assert len(group) == len({r['session'] for r in group}) == 13
            stages = Counter()
            for row in group:
                assert row['全入口列独立一致']
                stages.update(row['段階件数'])
            candidates = sum(r['候補数'] for r in group)
            active = sum(r['候補数'] > 0 for r in group)
            assert candidates == stages['全候補']
            result[spec['id']][symbol] = dict(候補数=candidates,候補がある場数=active,
                段階件数=dict(stages),基礎活動20未満=candidates < 20)
            display.append(f'{candidates}／{active}')
        lines.append(f'|{spec["id"]} {spec["name"]}|{display[0]}|{display[1]}|')
    assert all(result[name][symbol]['基礎活動20未満'] for name in ('F01','F02') for symbol in ('TOPIX','NK225'))
    record = dict(全20基本頻度確認=True,収支前の頻度確認=True,基礎活動基準変更=False,
                  条件別=result,新売買再生=False,現在API取得数=0,
                  入口監査明細SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  記録実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target = HERE / '候補頻度の事前確認.json'
    if target.exists():
        assert json.loads(target.read_text(encoding='utf-8')) == record
    else:
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    (HERE / '候補頻度の事前確認.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('F01/F02は両市場とも候補20未満。活動基準を変えず260条件を比較。',flush=True)


if __name__ == '__main__':
    main()
