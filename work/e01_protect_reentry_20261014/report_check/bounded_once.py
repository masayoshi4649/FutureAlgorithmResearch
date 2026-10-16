"""指定完成JSON一ファイルだけの読取境界を補助し、凍結表示を再読なしで公開可能にする。"""

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
REPORT_SHA = 'c637130c921c7a46a78ca9fafe3f7ffd9d49b46140ebbda70b0c42ecf3388edb'
QA_SHA = '783c442046242cece650d45104aa9a509eb99c6da8bf78086715001834a99c13'
RESULT = (BASE/'engine/finance/結果.json').resolve()
RESULT_SHA = 'c0103c4817c39891f872f18d6491fdd8d8ad171a98b8053842558626d463f02f'
READY = HERE/'check_ready'


def digest(path: Path) -> str:
    """
    機能: 小source・私有表示又は証跡の指紋を求める。
    引数: path(Path)は明示されたsource又は表示成果。
    返り値: strはSHA256。金融結果には使用せず一読bytesから検算する。
    """
    assert path.resolve() != RESULT
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_report() -> object:
    """
    機能: 凍結reportを金融なしで読み、source/QAの不変更を確認する。
    引数: なし。REPORT_SHA/QA_SHA(str)は金融前固定署名。
    返り値: moduleは凍結report。金融・入力・台帳の関数をimportしない。
    """
    source = BASE/'report.py'
    assert digest(source) == REPORT_SHA and digest(BASE/'report_view.py') == QA_SHA
    spec = importlib.util.spec_from_file_location('十二固定報告書の境界付き検算', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_only(module: object) -> None:
    """
    機能: 根指定の一JSONだけ40MBまで一読し、既reportのcheck-onlyを呼ぶ。
    引数: module(module)は凍結表示。root金融完了後の一目的授権が必要。
    返り値: None。私有表示を保存し公開しない。他pathは旧20MBreaderへ委譲。
    """
    assert not READY.exists(), '本文一読後の再実行を禁止する。'
    READY.mkdir()
    original_read = module.HELPERS.read_small
    original_build = module.build
    counts = Counter()
    captured = {}

    def read_bound(path: Path) -> tuple:
        """
        機能: 同resolveの指定結果だけを同bytes一読/SHA照合し、それ以外は既readerを保つ。
        引数: path(Path)はreport指定の小JSON。
        返り値: tuple[dict,str]はJSONとSHA。原板/NPZ/台帳を受け付けない。
        """
        if path.resolve() != RESULT: return original_read(path)
        assert path.suffix == '.json' and path.stat().st_size <= 40_000_000 and counts['result'] == 0
        raw = path.read_bytes()
        counts['result'] += 1
        assert len(raw) <= 40_000_000
        sha = hashlib.sha256(raw).hexdigest()
        assert sha == RESULT_SHA
        return json.loads(raw.decode('utf-8-sig')), sha

    def capture(*args: object, **kwargs: object) -> dict:
        """
        機能: 元buildを一度呼び、同返却会計への参照だけを保持する。
        引数: args(tuple)/kwargs(dict)は正式buildへそのまま渡す引数。
        返り値: dictは元buildの値。選定・損益・rendererを変更しない。
        """
        value = original_build(*args, **kwargs)
        captured['data'] = value
        return value

    module.HELPERS.read_small = read_bound
    module.build = capture
    sys.argv = [str(BASE/'report.py'), '--check-only', '--result', str(RESULT),
        '--fixed', str(BASE/'engine/金融事前固定.json'), '--plan', str(BASE/'engine/試行計画.json')]
    try:
        module.main()
        data = captured['data']
        assert counts['result'] == 1 and data['sources']['result'] == RESULT_SHA
        assert data['sources']['display_source'] == REPORT_SHA
        account = READY/'会計.json'
        account.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        page = READY/'表示.html'
        page.write_text(module.render(data), encoding='utf-8')
        proof = dict(全合格=True, result_SHA256=RESULT_SHA, result_read=1, other_reader_limit=20_000_000,
            exact_result_limit=40_000_000, exact_result_path=RESULT.relative_to(ROOT).as_posix(),
            report_source_SHA256=REPORT_SHA, QA_source_SHA256=QA_SHA, wrapper_source_SHA256=digest(Path(__file__)),
            ready_account_SHA256=digest(account), ready_HTML_SHA256=digest(page),
            金融source_SHA256=data['金融source_SHA256'], selected=data['pair']['selected'], selection=data['selection'],
            selected_metrics=data['pair']['metrics'],
            cases={cid: dict(metrics=value['metrics'], capacity=value['capacity'], risk=value['risk']) for cid, value in data['cases'].items()},
            main_achieved_symbols=data['main_achieved_symbols'],
            新金融=0, 入力=0, 台帳=0, API=0, 公開=0, Chrome=0)
        (READY/'読取境界と私有表示の証跡.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        assert digest(BASE/'report.py') == REPORT_SHA and digest(BASE/'report_view.py') == QA_SHA
        print(json.dumps(dict(全合格=True, selected=proof['selected'], 主達成=proof['main_achieved_symbols'],
            result_read=1, 私有会計bytes=account.stat().st_size, 私有HTMLbytes=page.stat().st_size,
            proof_SHA256=digest(READY/'読取境界と私有表示の証跡.json'), 新金融=0, 入力=0, 台帳=0, API=0, 公開=0), ensure_ascii=False))
    except BaseException:
        (READY/'False.json').write_text(json.dumps(dict(全合格=False, 原因=traceback.format_exc(),
            result_read=counts['result'], 新金融=0, 入力=0, 台帳=0, API=0, 公開=0, 自動再実行=False), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise


def publish_ready(module: object) -> None:
    """
    機能: 根だけが検算済み私有表示を同bytes公開し、元結果を再読しない。
    引数: module(module)は同凍結report。root公開授権後だけ呼ぶ。
    返り値: None。私有JSON/HTMLと指紋を照合し、金融・選定の再計算は0。
    """
    proof = json.loads((READY/'読取境界と私有表示の証跡.json').read_text(encoding='utf-8'))
    assert proof['全合格'] and proof['wrapper_source_SHA256'] == digest(Path(__file__))
    assert proof['report_source_SHA256'] == REPORT_SHA and proof['result_SHA256'] == RESULT_SHA
    assert all(digest(ROOT/p) == sha for p, sha in proof['金融source_SHA256'].items())
    account, page = READY/'会計.json', READY/'表示.html'
    ab, pb = account.read_bytes(), page.read_bytes()
    assert hashlib.sha256(ab).hexdigest() == proof['ready_account_SHA256']
    assert hashlib.sha256(pb).hexdigest() == proof['ready_HTML_SHA256']
    module.PUBLIC.mkdir(parents=True, exist_ok=True)
    targets = [module.PUBLIC/module.ACCOUNTING_TITLE, module.PUBLIC/(module.TITLE+'.html')]
    assert not any(p.exists() for p in targets), '公開済み成果の上書きを禁止する。'
    targets[0].write_bytes(ab)
    targets[1].write_bytes(pb)
    publication = dict(全合格=True, report_source_SHA256=REPORT_SHA,
        公開会計_SHA256=hashlib.sha256(ab).hexdigest(), 公開HTML_SHA256=hashlib.sha256(pb).hexdigest(),
        金融結果再読=0, 新金融=0, 入力=0, 台帳=0, API=0, 公開=2)
    (READY/'根公開証跡.json').write_text(json.dumps(publication, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(publication, ensure_ascii=False))


def main() -> None:
    """
    機能: owned wrapperの検算又は根公開を分離して呼ぶ。
    引数: CLI --check-only/--root-publish。
    返り値: None。check-onlyは元結果初読一回、root-publishは元結果読取0。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only', action='store_true')
    mode.add_argument('--root-publish', action='store_true')
    args = parser.parse_args()
    module = frozen_report()
    if args.check_only: check_only(module)
    else: publish_ready(module)


if __name__ == '__main__':
    main()
