"""保全済み同結果だけから表示schemaを検算し、同じ私有表示を根が公開する。"""

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
REPORT_SHA = '75431d6caeaa3678d7549427c057beaef4360826da922e7ff8fb6cf5057305a8'
OLD_REPORT_SHA = 'c637130c921c7a46a78ca9fafe3f7ffd9d49b46140ebbda70b0c42ecf3388edb'
QA_SHA = 'ba17157ff2fa2d8e17ed5ca3e4232c9ec3ca24a441103bfa5e70dc9f41c640af'
RESULT = (BASE/'engine/finance/結果.json').resolve()
RESULT_SHA = 'c0103c4817c39891f872f18d6491fdd8d8ad171a98b8053842558626d463f02f'
READY = HERE/'schema_v3'
SNAPSHOT = HERE/'schema_v2/同一金融結果の保全.json'
SNAPSHOT_PROOF = HERE/'schema_v2/parse前保全の証跡.json'
ARCHIVE = BASE/'report_archive/原board読取へ訂正する前'


def digest(path: Path) -> str:
    """
    機能: 小source・私有表示又は証跡の指紋を求める。
    引数: path(Path)は明示された小資料。原金融と保全本文には使用しない。
    返り値: strはSHA256。大型金融本文は専用の同bytes境界で照合する。
    """
    assert path.resolve() not in (RESULT, SNAPSHOT.resolve())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    """
    機能: 私有証跡を有限値JSONとして保存する。
    引数: path(Path)は自所有先、value(dict)は小証跡。
    返り値: None。金融・採否・選定値を変更せず保存する。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def corrected_report() -> object:
    """
    機能: 原boardキーと方向別親新規枚数だけを訂正した表示source/QAを照合する。
    引数: なし。固定署名および旧sourcearchiveを用いる。
    返り値: moduleは訂正report。金融source・金額・順位は変更しない。
    """
    source = BASE/'report.py'
    old_source = ARCHIVE/'report.py'
    assert digest(source) == REPORT_SHA and digest(old_source) == OLD_REPORT_SHA
    assert digest(BASE/'report_view.py') == QA_SHA
    new = source.read_text(encoding='utf-8')
    assert "finance['原板']" not in new and new.count("finance['原board']") == 1
    spec = importlib.util.spec_from_file_location('十二固定報告書のschema訂正検算', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preserved_result(counts: Counter) -> bytes:
    """
    機能: 先に保全済みの同SHA本文だけを一読し、原結果の再読を拒否する。
    引数: counts(Counter)は今回の私有copy読取回数。
    返り値: bytesは根指定SHAと一致した本文。40MB例外は指定copyだけ。
    """
    assert SNAPSHOT.exists() and SNAPSHOT_PROOF.exists(), '原結果へ自動fallbackしない。'
    manifest = json.loads(SNAPSHOT_PROOF.read_text(encoding='utf-8'))
    assert manifest['全合格'] and manifest['result_SHA256'] == RESULT_SHA
    assert manifest['original_path'] == RESULT.relative_to(ROOT).as_posix()
    assert SNAPSHOT.stat().st_size <= 40_000_000 and counts['snapshot'] == 0
    raw = SNAPSHOT.read_bytes()
    counts['snapshot'] += 1
    assert len(raw) == manifest['bytes'] and hashlib.sha256(raw).hexdigest() == RESULT_SHA
    return raw


def check_only(module: object) -> None:
    """
    機能: 同金融の保全bytesを訂正reportへ接続し、会計と表示を私有保存する。
    引数: module(module)は一キー訂正済みreport。根の訂正目的授権済み。
    返り値: None。原再読は初回だけ、その他readerの20MB上限は維持する。
    """
    READY.mkdir(parents=True, exist_ok=True)
    assert not (READY/'読取境界と私有表示の証跡.json').exists(), '成功済みの再検算を禁止する。'
    original_read, original_build = module.HELPERS.read_small, module.build
    counts, captured = Counter(), {}

    def read_bound(path: Path) -> tuple:
        """
        機能: 指定原結果を同SHA保全本文へ接続し、他pathは旧readerへ委譲する。
        引数: path(Path)はreportの正式資料位置。
        返り値: tuple[dict,str]はJSONとSHA。本文保全はparseより先に完了する。
        """
        if path.resolve() != RESULT:
            return original_read(path)
        assert counts['request'] == 0
        counts['request'] += 1
        raw = preserved_result(counts)
        return json.loads(raw.decode('utf-8-sig')), RESULT_SHA

    def capture(*args: object, **kwargs: object) -> dict:
        """
        機能: 訂正reportの元buildを呼び、同返却会計を保持する。
        引数: args(tuple)/kwargs(dict)は正式buildへそのまま渡す値。
        返り値: dictは元buildと同値。採否・金融・選定を変更しない。
        """
        value = original_build(*args, **kwargs)
        captured['data'] = value
        return value

    module.HELPERS.read_small, module.build = read_bound, capture
    sys.argv = [str(BASE/'report.py'), '--check-only', '--result', str(RESULT),
        '--fixed', str(BASE/'engine/金融事前固定.json'), '--plan', str(BASE/'engine/試行計画.json')]
    try:
        module.main()
        data = captured['data']
        assert counts['request'] == 1 and counts['result']+counts['snapshot'] == 1
        assert data['sources']['result'] == RESULT_SHA and data['sources']['display_source'] == REPORT_SHA
        account, page = READY/'会計.json', READY/'表示.html'
        write_json(account, data)
        page.write_text(module.render(data), encoding='utf-8')
        proof = dict(全合格=True, result_SHA256=RESULT_SHA, original_result_read=counts['result'],
            snapshot_read=counts['snapshot'], 旧schema失敗本文読取=1, 根授権訂正目的再読=1,
            parse前保全_SHA256=digest(SNAPSHOT_PROOF), archive_source_SHA256=OLD_REPORT_SHA,
            変更='原board読取名と完結実親からの方向別新規枚数表示だけ訂正。金融金額・採否・順位は不変。',
            other_reader_limit=20_000_000, exact_result_limit=40_000_000,
            report_source_SHA256=REPORT_SHA, QA_source_SHA256=QA_SHA,
            wrapper_source_SHA256=digest(Path(__file__)),
            ready_account_SHA256=digest(account), ready_HTML_SHA256=digest(page),
            金融source_SHA256=data['金融source_SHA256'], selected=data['pair']['selected'], selection=data['selection'],
            selected_metrics=data['pair']['metrics'],
            cases={cid: dict(metrics=value['metrics'], capacity=value['capacity'], risk=value['risk'])
                   for cid, value in data['cases'].items()},
            main_achieved_symbols=data['main_achieved_symbols'], 新金融=0, input=0, ledger=0, API=0, 公開=0, Chrome=0)
        write_json(READY/'読取境界と私有表示の証跡.json', proof)
        assert digest(BASE/'report.py') == REPORT_SHA and digest(BASE/'report_view.py') == QA_SHA
        print(json.dumps(dict(全合格=True, selected=proof['selected'], 主達成=proof['main_achieved_symbols'],
            original_result_read=counts['result'], snapshot_read=counts['snapshot'],
            私有会計bytes=account.stat().st_size, 私有HTMLbytes=page.stat().st_size,
            proof_SHA256=digest(READY/'読取境界と私有表示の証跡.json'), 新金融=0, input=0, ledger=0, API=0, 公開=0), ensure_ascii=False))
    except BaseException:
        write_json(READY/'False.json', dict(全合格=False, 原因=traceback.format_exc(),
            original_result_read=counts['result'], snapshot_read=counts['snapshot'],
            parse前保存=SNAPSHOT.exists(), 新金融=0, input=0, ledger=0, API=0, 公開=0, 自動再実行=False))
        raise


def publish_ready(module: object) -> None:
    """
    機能: 根が検算済み私有会計とHTMLを同bytesで公開する。
    引数: module(module)は訂正済み同report。根の公開授権後に限る。
    返り値: None。原金融・保全金融本文・選定の再計算はすべて0。
    """
    proof = json.loads((READY/'読取境界と私有表示の証跡.json').read_text(encoding='utf-8'))
    assert proof['全合格'] and proof['wrapper_source_SHA256'] == digest(Path(__file__))
    assert proof['report_source_SHA256'] == REPORT_SHA and proof['result_SHA256'] == RESULT_SHA
    assert all(digest(ROOT/p) == sha for p, sha in proof['金融source_SHA256'].items())
    ab, pb = (READY/'会計.json').read_bytes(), (READY/'表示.html').read_bytes()
    assert hashlib.sha256(ab).hexdigest() == proof['ready_account_SHA256']
    assert hashlib.sha256(pb).hexdigest() == proof['ready_HTML_SHA256']
    targets = [module.PUBLIC/module.ACCOUNTING_TITLE, module.PUBLIC/(module.TITLE+'.html')]
    assert not any(path.exists() for path in targets), '公開済み成果の上書きを禁止する。'
    module.PUBLIC.mkdir(parents=True, exist_ok=True)
    targets[0].write_bytes(ab)
    targets[1].write_bytes(pb)
    publication = dict(全合格=True, report_source_SHA256=REPORT_SHA,
        公開会計_SHA256=hashlib.sha256(ab).hexdigest(), 公開HTML_SHA256=hashlib.sha256(pb).hexdigest(),
        原金融再読=0, 保全金融本文読取=0, 新金融=0, input=0, ledger=0, API=0, 公開=2)
    write_json(READY/'根公開証跡.json', publication)
    print(json.dumps(publication, ensure_ascii=False))


def main() -> None:
    """
    機能: 訂正目的の会計確認と根の公開を別のCLIとして実行する。
    引数: CLI --check-only/--root-publish。原金融は必ず読取0。
    返り値: None。成功後の公開は会計JSON/HTMLのcopyだけを用いる。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only', action='store_true')
    mode.add_argument('--root-publish', action='store_true')
    args = parser.parse_args()
    module = corrected_report()
    if args.check_only:
        check_only(module)
    else:
        publish_ready(module)


if __name__ == '__main__':
    main()
