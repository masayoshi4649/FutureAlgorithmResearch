"""返済締切付近に存在する保存時計を、価格や損益とは無関係に調べる。"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent


def stamp(value: float | None) -> str | None:
    """機能: Unix秒を日本時間の読みやすい時計にする。

    引数: value(float|None) は保存された約定時計。
    返り値: ISO形式文字列またはNone(str|None)。
    """
    return None if value is None else datetime.fromtimestamp(value, timezone(timedelta(hours=9))).isoformat()


def main() -> None:
    """機能: 全50口座の強制判断行と次原本行が返済期限を満たすか点検する。

    引数: なし。
    返り値: なし(None)。価格値、入口候補、損益は参照しない。
    """
    inputs = pickle.loads((HERE.parent / 'inputs.pkl').read_bytes())
    rows = []
    for key, ready in sorted(inputs.items()):
        times, limit = ready['time_s'], ready['limit']
        index = int(np.searchsorted(times, limit - 60., side='left'))
        decision = float(times[index]) if index < len(times) else None
        following = float(times[index + 1]) if index + 1 < len(times) else None
        previous = float(times[index - 1]) if index > 0 else None
        rows.append({'セッション': key[0], '銘柄': key[1], '判断予定': stamp(limit - 60.),
                     '期限': stamp(limit), '直前の保存時計': stamp(previous),
                     '最初の判断時計': stamp(decision), '次有効原本時計': stamp(following),
                     '次行が期限以内': following is not None and following <= limit,
                     '判断時計の遅延秒': None if decision is None else decision - (limit - 60.),
                     '期限後の返済遅延秒': None if following is None else max(0., following - limit),
                     '原本判断seq': int(ready['seq'][index]) if index < len(times) else None})
    output = {'時間のみの監査': True, '不成立口座数': sum(not row['次行が期限以内'] for row in rows), '口座別': rows}
    (HERE / '締切付近の保存時計監査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'不成立口座数': output['不成立口座数'], '不成立口座': [row for row in rows if not row['次行が期限以内']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
