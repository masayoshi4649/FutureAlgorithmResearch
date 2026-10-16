"""正式reportのcheck-onlyを一度呼び、同メモリから数字と選定根拠を保存する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
REPORT_SHA = 'f4567e986c15deed22bcea36c0e081fb7ea72f8a177d8c4d9a1111b6675fae08'


def main() -> None:
    """
    機能: report.py --check-onlyを一読実行し、その会計と選定を同メモリだけで確認する。
    引数: なし。根が正式金融完了後に授権した同一目的。
    返り値: None。新結果一読、入力・台帳・金融・API・公開は0。
    """
    source = BASE/'report.py'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == REPORT_SHA
    out = HERE/'小会計確認と選択根拠.json'
    assert not out.exists()
    spec = importlib.util.spec_from_file_location('凍結済み報告書の一読検算', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured = {}
    original = module.build

    def keep(*args: object, **kwargs: object) -> dict:
        """
        機能: 元buildを呼び、同じ返却会計への参照だけを保持する。
        引数: args(tuple)/kwargs(dict)は正式buildへそのまま渡す引数。
        返り値: dictは元buildの値。結果を変更せず、再読しない。
        """
        value = original(*args, **kwargs)
        captured['data'] = value
        return value

    module.build = keep
    sys.argv = [str(source), '--check-only', '--result', str(BASE/'engine/finance/結果.json'),
        '--fixed', str(BASE/'engine/金融事前固定.json'), '--plan', str(BASE/'engine/試行計画.json')]
    module.main()
    data = captured['data']
    public = dict(全合格=True, sources=data['sources'],
        report_source_SHA256=REPORT_SHA, result_read=1, new_count=data['new_count'],
        selected=data['pair']['selected'], selection=data['selection'],
        selected_metrics=data['pair']['metrics'], selected_capacity=data['pair']['capacity'],
        selected_risk=data['pair']['risk'], old_reference=data['old_reference'],
        main_achieved_symbols=data['main_achieved_symbols'],
        stability_achieved_symbols=data['stability_achieved_symbols'],
        robustness_qualified_symbols=data['robustness_qualified_symbols'],
        cases={cid: dict(metrics=item['metrics'], capacity=item['capacity'], risk=item['risk']) for cid, item in data['cases'].items()},
        金融source不変更=True, 表示source不変更=True, 新金融=0, 入力=0, 台帳=0, API=0, 公開=0, Chrome=0)
    out.write_text(json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == REPORT_SHA
    print(json.dumps(dict(全合格=True, 選択=data['pair']['selected'],
        数値=data['pair']['metrics'], 容量=data['pair']['capacity'], 途中逆行=data['pair']['risk'],
        保存SHA256=hashlib.sha256(out.read_bytes()).hexdigest(), 結果一読=1, 新金融=0, 入力=0, 台帳=0, API=0, 公開=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
