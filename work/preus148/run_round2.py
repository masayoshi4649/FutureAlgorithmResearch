"""第二巡の登録を確認し、第一巡を残したまま8条件を再生する。"""

from pathlib import Path
import json
import engine_round2
import run148

HERE = Path(__file__).resolve().parent


def main():
    """登録済み第二巡だけを別フォルダで再生する。

    引数: なし。
    返り値: None。第一巡の会計を保持して比較表へ追加する。
    """
    from verify_round2 import verify
    verify()
    run148.HERE = HERE / 'round2'
    run148.engine = engine_round2
    run148.CONFIGS = json.loads((HERE / 'configs_round2.json').read_text(encoding='utf-8'))
    run148.main()
    first_path = HERE / 'report_first.json'
    if not first_path.exists():
        first_path.write_bytes((HERE / 'report.json').read_bytes())
    first = json.loads(first_path.read_text(encoding='utf-8'))
    second = json.loads((HERE / 'round2/report.json').read_text(encoding='utf-8'))
    first['methods'] += second['methods'][1:]
    first['partial'] += [r for r in second['partial'] if r['id'] != 'D07']
    run148.save(HERE / 'report.json', first)


if __name__ == '__main__':
    main()
