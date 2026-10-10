"""旧23場だけの事前基準を適用し、追加場を開く前の候補を固定する。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def screen(method: dict, symbol: str) -> dict:
    """機能: 損益を見る前に固定した六つの採用条件を判定する。

    引数: method(dict) は旧23場の結果、symbol(str) は対象銘柄。
    返り値: 条件別の合否(dict)。他銘柄の円収支は足さない。
    """
    value = method['summary'][symbol]
    return {
        '純益黒字': value['net'] > 0,
        '最大黒字場除外黒字': value['without_best'] > 0,
        '平均勝ちが平均負けより大きい': (value['payoff'] or 0) > 1,
        '旧3期間全て黒字': all(p['net'] > 0 for p in method['periods'][symbol].values()),
        '決済30回以上': value['cycles'] >= 30,
        '取引場8以上': value['active_sessions'] >= 8,
    }


def main() -> None:
    """機能: 主条件と採用候補を変更不能の記録へ保存する。

    引数: なし。返り値: なし(None)。追加2場の原本や結果を読まない。
    """
    result_path = HERE / 'dev/売買結果.json'
    target = HERE / '追加場適用前固定.json'
    assert not target.exists(), '既存の選定を上書きできません'
    assert not (HERE / 'holdout/inputs.pkl').exists(), '追加場の読取前に固定してください'
    data = json.loads(result_path.read_text(encoding='utf-8'))
    criteria = {m['id']: {s: screen(m, s) for s in ('TOPIX', 'NK225')} for m in data['methods']}
    selected = [key for key, symbols in criteria.items()
                if all(all(checks.values()) for checks in symbols.values())]
    result = {
        '固定時刻': datetime.now(timezone(timedelta(hours=9))).isoformat(),
        '開発結果SHA256': hashlib.sha256(result_path.read_bytes()).hexdigest(),
        '仕様SHA256': hashlib.sha256((HERE / '調査仕様.json').read_bytes()).hexdigest(),
        '主6条件': [m['id'] for m in data['methods'] if m['primary']],
        '採用候補': selected,
        '条件別判定': criteria,
        '追加場': ['2026-10-06_Night', '2026-10-07_Day'],
        '追加適用': '全72条件を一度だけ適用し、主6条件と採用候補を差し替えない',
        '解釈': '採用基準は中値評価の研究候補の基準。気配評価の黒字や将来利益は保証しない。旧場は反復利用済みで未見資料ではない',
    }
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'採用候補': selected, '旧結果SHA256': result['開発結果SHA256'],
                      '主条件': [{k: m[k] for k in ('id', 'summary')} for m in data['methods'] if m['primary']]},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
