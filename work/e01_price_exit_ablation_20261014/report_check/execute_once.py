"""根完成通知の結果を固定表示で検算し、同じ私有会計/HTMLを根が公開する。"""

import argparse
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
READY = HERE/'ready'
REPORT_SHA = '7b6a07155747e659c949caad0d52f4326c5b7f5b31a7cb431130bfe98b9e8174'
QA_SHA = '7aeb95c4ede6e4de90fd6c722507b974b65385f9d0aeccafbe3da4ad40b2c52b'
RESULT_SHA = '6bc96e20d9ea72af1df51ed73d4595be5cadc1e9ac8760c9a69a1a501cd8886d'


def digest(path: Path) -> str:
    """
    機能: 小source又は私有表示の指紋を取得する。
    引数: path(Path)は表示・証跡・source位置。原金融は受け付けない。
    返り値: strはSHA256。指定結果の本文は元reportの同bytes一読境界だけで読む。
    """
    assert path.resolve() != (BASE/'engine/finance/結果.json').resolve()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_module() -> object:
    """
    機能: 金融前固定report/QAの署名を照合して表示moduleだけを読む。
    引数: なし。金融sourceをimport又は実行しない。
    返り値: moduleは固定report。
    """
    assert digest(BASE/'report.py') == REPORT_SHA and digest(BASE/'report_view.py') == QA_SHA
    spec = importlib.util.spec_from_file_location('逆票返済OFFの固定表示検算', BASE/'report.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(module: object) -> None:
    """
    機能: 固定reportのcheck-onlyを一度呼び、同返却会計と同renderを私有保存する。
    引数: module(module)は結果前固定されたreport。根完成通知の授権済み。
    返り値: None。原結果同bytes保全は元reportがparse前に行う。公開は0。
    """
    assert not READY.exists(), '表示検算の自動再実行を禁止する。'
    READY.mkdir(parents=True)
    captured = {}
    original_build, original_render = module.build, module.render

    def capture_build(*args: object, **kwargs: object) -> dict:
        """
        機能: 固定buildの同返却会計だけを保持する。
        引数: args(tuple)/kwargs(dict)は固定buildの引数。
        返り値: dictは元buildと同じ値。会計/選定式を変更しない。
        """
        value = original_build(*args, **kwargs)
        captured['data'] = value
        return value

    def capture_render(data: dict) -> str:
        """
        機能: 固定renderの同HTMLだけを保持する。
        引数: data(dict)は検算済み表示会計。
        返り値: strは元renderと同じHTML。文言・セルを変更しない。
        """
        value = original_render(data)
        captured['page'] = value
        return value

    module.build, module.render = capture_build, capture_render
    sys.argv = [str(BASE/'report.py'), '--check-only', '--result', str(BASE/'engine/finance/結果.json'),
        '--fixed', str(BASE/'engine/金融事前固定.json'), '--plan', str(BASE/'engine/試行計画.json'),
        '--result-sha256', RESULT_SHA]
    try:
        module.main()
        data = captured['data']
        assert data['sources']['result'] == RESULT_SHA and data['sources']['display_source'] == REPORT_SHA
        account, page = READY/'会計.json', READY/'表示.html'
        account.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        page.write_text(captured['page'], encoding='utf-8')
        cache_proof = BASE/'display_cache'/RESULT_SHA/'読取境界.json'
        boundary = json.loads(cache_proof.read_text(encoding='utf-8'))
        assert boundary['全合格'] and boundary['result_SHA256'] == RESULT_SHA and boundary['parse前同bytes保全']
        proof = dict(全合格=True, result_SHA256=RESULT_SHA, source_SHA256=REPORT_SHA, QA_SHA256=QA_SHA,
            wrapper_SHA256=digest(Path(__file__)), 原結果先保全証跡_SHA256=digest(cache_proof),
            私有会計_SHA256=digest(account), 私有HTML_SHA256=digest(page),
            金融source_SHA256=data['金融source_SHA256'], selected=data['pair']['selected'], selection=data['selection'],
            metrics=data['pair']['metrics'], 主合格=data['main_achieved_symbols'],
            全条件={cid: dict(metrics=v['metrics'], risk=v['risk'], capacity=v['capacity']) for cid, v in data['cases'].items()},
            ON金融再運転=0, 旧108本文読取=0, 新金融=0, input=0, ledger=0, API=0, 公開=0, Chrome=0)
        target = READY/'小会計確認と選択根拠.json'
        target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        print(json.dumps(dict(全合格=True, selected=proof['selected'], 主合格=proof['主合格'],
            proof_SHA256=digest(target), 私有会計bytes=account.stat().st_size, 私有HTMLbytes=page.stat().st_size,
            金融=0, input=0, ledger=0, API=0, 公開=0), ensure_ascii=False))
    except BaseException:
        (READY/'False.json').write_text(json.dumps(dict(全合格=False, 原因=traceback.format_exc(),
            私有同bytes保全=(BASE/'display_cache'/RESULT_SHA/'完成金融結果の同bytes保全.json').exists(),
            新金融=0, input=0, ledger=0, API=0, 公開=0, 自動再実行=False), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise


def publish(module: object) -> None:
    """
    機能: 根が検算済み私有会計とHTMLを同bytesで公開する。
    引数: module(module)は同署名report。公開授権は根だけが行う。
    返り値: None。原/保全金融の再読・再計算は0。
    """
    proof = json.loads((READY/'小会計確認と選択根拠.json').read_text(encoding='utf-8'))
    assert proof['全合格'] and proof['source_SHA256'] == REPORT_SHA and proof['QA_SHA256'] == QA_SHA
    assert proof['wrapper_SHA256'] == digest(Path(__file__)) and proof['result_SHA256'] == RESULT_SHA
    assert all(digest(ROOT/p) == sha for p, sha in proof['金融source_SHA256'].items())
    ab, hb = (READY/'会計.json').read_bytes(), (READY/'表示.html').read_bytes()
    assert hashlib.sha256(ab).hexdigest() == proof['私有会計_SHA256'] and hashlib.sha256(hb).hexdigest() == proof['私有HTML_SHA256']
    targets = [module.PUBLIC/module.ACCOUNTING_TITLE, module.PUBLIC/(module.TITLE+'.html')]
    assert not any(p.exists() for p in targets)
    module.PUBLIC.mkdir(parents=True, exist_ok=True)
    targets[0].write_bytes(ab)
    targets[1].write_bytes(hb)
    result = dict(全合格=True, source_SHA256=REPORT_SHA, 公開会計_SHA256=hashlib.sha256(ab).hexdigest(),
        公開HTML_SHA256=hashlib.sha256(hb).hexdigest(), 原結果再読=0, 保全金融本文再読=0,
        新金融=0, input=0, ledger=0, API=0, 公開=2)
    (READY/'根公開証跡.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    """
    機能: 一回の私有検算と、根の同bytes公開をCLIで分ける。
    引数: CLI --check-only/--root-publish。
    返り値: None。正式金融は再実行しない。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only', action='store_true')
    mode.add_argument('--root-publish', action='store_true')
    args = parser.parse_args()
    module = report_module()
    if args.check_only:
        check(module)
    else:
        publish(module)


if __name__ == '__main__':
    main()
