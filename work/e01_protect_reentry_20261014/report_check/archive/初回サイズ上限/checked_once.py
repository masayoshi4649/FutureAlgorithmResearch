"""凍結reportのcheck-onlyを一度実行し、同メモリから未達結果を保存する。"""

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
REPORT_SHA = 'c637130c921c7a46a78ca9fafe3f7ffd9d49b46140ebbda70b0c42ecf3388edb'


def main() -> None:
    """
    機能: root授権後に正式check-onlyを一目的一読し、同会計の数値だけ保存する。
    引数: なし。正式finance/固定/planは凍結reportだけが読む。
    返り値: None。原入力・台帳・API・新金融・公開は0。
    """
    source = BASE/'report.py'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == REPORT_SHA
    output = HERE/'小会計確認と未達の選択根拠.json'
    assert not output.exists()
    spec = importlib.util.spec_from_file_location('十二固定報告書の一読検算', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = {}
    original = module.build

    def capture(*args: object, **kwargs: object) -> dict:
        """
        機能: 元buildを変更せず一度呼び、返却会計への参照だけ保持する。
        引数: args(tuple)/kwargs(dict)は正式buildへそのまま渡す引数。
        返り値: dictは元buildの値。金融結果の再読・再計算を行わない。
        """
        value = original(*args, **kwargs)
        saved['data'] = value
        return value

    module.build = capture
    sys.argv = [str(source), '--check-only', '--result', str(BASE/'engine/finance/結果.json'),
        '--fixed', str(BASE/'engine/金融事前固定.json'), '--plan', str(BASE/'engine/試行計画.json')]
    module.main()
    data = saved['data']
    assert data['sources']['result'] == 'c0103c4817c39891f872f18d6491fdd8d8ad171a98b8053842558626d463f02f'
    witness = dict(全合格=True, sources=data['sources'], selected=data['pair']['selected'], selection=data['selection'],
        selected_metrics=data['pair']['metrics'], selected_capacity=data['pair']['capacity'], selected_risk=data['pair']['risk'],
        cases={cid: dict(metrics=v['metrics'], capacity=v['capacity'], risk=v['risk']) for cid, v in data['cases'].items()},
        comparison_reference=data['old_reference'], result_read=1, report_source_SHA256=REPORT_SHA,
        main_achieved_symbols=data['main_achieved_symbols'], stability_achieved_symbols=data['stability_achieved_symbols'],
        robustness_qualified_symbols=data['robustness_qualified_symbols'], 金融source不変更=True, 表示source不変更=True,
        新金融=0, 入力=0, 台帳=0, API=0, 公開=0, Chrome=0)
    output.write_text(json.dumps(witness, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == REPORT_SHA
    print(json.dumps(dict(全合格=True, selected=data['pair']['selected'], 数値=data['pair']['metrics'],
        保存SHA256=hashlib.sha256(output.read_bytes()).hexdigest(), 結果一読=1, 新金融=0, 入力=0, 台帳=0, API=0, 公開=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
