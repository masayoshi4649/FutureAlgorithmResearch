"""正式17源と十二比較の保存再利用境界を金融本文なしで確認する。"""

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


def module(path: Path, name: str) -> object:
    """
    機能: 表示sourceだけをimportしmain・金融・APIを実行しない。
    引数: path(Path)は私有表示source、name(str)はmodule名。
    返り値: moduleは純表示関数。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main() -> None:
    """
    機能: 形式guard・純算術・保存PRICEの未コピー親を結果前固定へ照合する。
    引数: なし。正式plan/fixedと根保存PRICE小射影だけを参照する。
    返り値: None。実金融結果は未読で、人工metadataを実効性証拠に数えない。
    """
    report = module(HERE/'report.py', '入口表示の純確認')
    qa = module(BASE/'report_review/report_view.py', '入口QAの純確認')
    pb = (BASE/'engine/試行計画.json').read_bytes()
    fb = (BASE/'engine/金融事前固定.json').read_bytes()
    ph = hashlib.sha256(pb).hexdigest()
    assert ph == '715340ae16637d03d78c61c57aa813c8188e9e90b6199d792958aa15ab89ed8c'
    plan, fixed = json.loads(pb.decode('utf-8')), json.loads(fb.decode('utf-8'))
    assert fixed['正式freeze'] and plan['正式freeze'] and fixed['計画SHA256'] == ph
    assert fixed['source_SHA256'] == plan['spec']['implementation'] and len(fixed['source_SHA256']) == 17
    assert all(report.digest(ROOT/p) == sha for p, sha in fixed['source_SHA256'].items())
    assert len(fixed['configs']) == 12 and all(report.parameters(c) for c in fixed['configs'])
    assert report.HELPERS.case_hashes(fixed['configs']) == fixed['case_SHA256']
    assert report.digest(report.SELECTION_PLAN) == report.SELECTION_SHA
    assert report.digest(report.COMPARISON_PATH) == report.COMPARISON_SHA
    assert report.TITLE == qa.TITLE and report.PUBLIC == qa.PUBLIC and report.ACCOUNTING_TITLE == qa.ACCOUNTING_TITLE
    assert report.SCHEMA_READY and qa.SCHEMA_READY
    new = [c for c in fixed['configs'] if c['actual_financial']]
    old = [c for c in fixed['configs'] if not c['actual_financial']]
    assert len(new) == 9 and len(old) == 3
    aliases = [dict(id=c['id'], symbol='NK225', source_id=c['economic_source_id_by_symbol']['NK225'], 保存会計=33, 新金融=0)
        for c in new if not c['actual_financial_by_symbol']['NK225']]
    assert len(aliases) == 3
    artificial_finance = dict(全合格=True, source開始終端一致=True, source_SHA256=fixed['source_SHA256'],
        configs=fixed['configs'], case_SHA256=fixed['case_SHA256'], sessions=fixed['sessions'],
        results={c['id']: {} for c in new}, actual_parent_diagnostics={c['id']: [] for c in new},
        reused_price_cases={c['id']: dict(config=c, paired_price_id=c['paired_price_id'],
            saved_public_case=fixed['comparison_reference']['cases'][c['paired_price_id']]) for c in old},
        comparison_reference=fixed['comparison_reference'], counts=report.EXPECTED_COUNTS,
        PRICE再金融=0, 保存PRICE条件=3, 新account金融=495, 内部同値会計再利用=99, 内部同値再金融=0,
        保存PRICE会計=198, 掲載口座=792, internal_aliases=aliases,
        旧GU再利用=0, 旧台帳本文=0, API=0, 原board=0, NPZ=0, 現在入力=0)
    report.guard(artificial_finance, fixed, plan, ph)
    pure = report.artificial()
    proof = dict(全合格=True, 正式plan_SHA256=ph, 正式fixed_SHA256=hashlib.sha256(fb).hexdigest(),
        report_SHA256=report.digest(HERE/'report.py'), QA_SHA256=qa.digest(BASE/'report_review/report_view.py'),
        選定SHA256=report.SELECTION_SHA, 保存PRICE_SHA256=report.COMPARISON_SHA,
        金融source_SHA256=fixed['source_SHA256'], 純算術=pure, 人工metadata形式確認=True,
        全比較条件=12, 新条件群=9, 保存PRICE条件=3, 新唯一金融=495, 旧保存=198, 内部同値=99, 掲載=792,
        ROOT結果通知後の表示確認='rootの一部集計通知は受領。金融本文は未読。選定基準/順位は通知前v2から不変。',
        未測='保存PRICE親時刻・経路は未コピー。値のある保存集計だけ引用。出来高代理は真攻撃量でない。',
        金融結果読取=0, 旧109原金融=0, input=0, ledger=0, API=0, 公開=0, Chrome=0)
    target = HERE/'表示preparedの形式と純算術確認.json'
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, report_SHA256=proof['report_SHA256'], QA_SHA256=proof['QA_SHA256'],
        prepared_SHA256=report.digest(target), 金融本文=0, input=0, ledger=0, API=0, 公開=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
