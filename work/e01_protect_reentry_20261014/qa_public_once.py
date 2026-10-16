"""根公開の指定二資料だけを同bytes照合し、既表示QAを一回実行する。"""

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
ROOT = HERE.parents[1]
REPORT_SHA = '75431d6caeaa3678d7549427c057beaef4360826da922e7ff8fb6cf5057305a8'
QA_SHA = 'ba17157ff2fa2d8e17ed5ca3e4232c9ec3ca24a441103bfa5e70dc9f41c640af'
HTML_SHA = '194216c6903d57e3cab4578b3a0dbff8f47211efa795cadba1533ee2b8ce81c0'
ACCOUNT_SHA = '042dc9572c9187db536fe4760069bba64de73efacb90a2b8e0847a757eae1876'
OWNED = HERE/'report_review_reader'


def digest(path: Path) -> str:
    """
    機能: 指定source又は小証跡の指紋を取得する。
    引数: path(Path)は小source位置。
    返り値: strはSHA256。公開本文は専用一読bytesから計算する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 根の指定公開bytesだけを一読し、既QAの広狭三画面検査へ接続する。
    引数: CLI --prepare-only/--root-reviewed。公開実行は根授権済みの時だけ。
    返り値: None。金融/板/入力/実台帳/APIは読まず、金融採否を変更しない。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--root-reviewed', action='store_true')
    args = parser.parse_args()
    assert digest(HERE/'report.py') == REPORT_SHA and digest(HERE/'report_view.py') == QA_SHA
    if args.prepare_only:
        print(json.dumps(dict(prepared=True, wrapper_SHA256=digest(Path(__file__)),
            report_SHA256=REPORT_SHA, QA_SHA256=QA_SHA, 公開会計指定SHA=ACCOUNT_SHA,
            公開HTML指定SHA=HTML_SHA, 公開例外上限=40_000_000, 切替=13, 円枚数セル=4420,
            金融=0, input=0, ledger=0, API=0, 公開読取=0, Chrome=0), ensure_ascii=False))
        return
    assert not OWNED.exists(), '表示reader実行の自動再開を禁止する。'
    OWNED.mkdir(parents=True)
    spec = importlib.util.spec_from_file_location('十二政策の指定公開表示QA', HERE/'report_view.py')
    qa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qa)
    reads = dict(公開HTML=0, 公開会計=0)

    def bound_display() -> tuple:
        """
        機能: 指定公開HTML/会計の同一読bytesを根の完成SHAへ照合する。
        引数: なし。qa.PUBLIC/TITLE/ACCOUNTING_TITLEは固定された指定位置。
        返り値: tuple[str,dict,dict]は表示本文・会計・読取境界。他pathの例外は作らない。
        """
        hp, ap = qa.PUBLIC/(qa.TITLE+'.html'), qa.PUBLIC/qa.ACCOUNTING_TITLE
        expected_public = ROOT/'アルゴリズム調査/00108_利益保護と二市場の再参加検証'
        assert qa.PUBLIC.resolve() == expected_public.resolve()
        assert hp.suffix == '.html' and hp.stat().st_size <= 20_000_000
        assert ap.name == '利益保護と再参加の全場会計.json' and ap.stat().st_size <= 40_000_000
        assert reads == dict(公開HTML=0, 公開会計=0)
        hb, ab = hp.read_bytes(), ap.read_bytes()
        reads['公開HTML'] += 1
        reads['公開会計'] += 1
        assert len(hb) <= 20_000_000 and len(ab) <= 40_000_000
        assert hashlib.sha256(hb).hexdigest() == HTML_SHA
        assert hashlib.sha256(ab).hexdigest() == ACCOUNT_SHA
        data = json.loads(ab.decode('utf-8-sig'))
        assert data['sources']['display_source'] == REPORT_SHA
        return hb.decode('utf-8'), data, dict(公開HTML_SHA256=HTML_SHA, 公開会計_SHA256=ACCOUNT_SHA,
            表示source_SHA256=REPORT_SHA, 公開reader_source_SHA256=digest(Path(__file__)),
            指定会計上限=40_000_000, その他上限=20_000_000, 同読取bytesSHA照合=True)

    qa.load_display = bound_display
    sys.argv = [str(HERE/'report_view.py'), '--root-reviewed']
    try:
        qa.main()
        proof = dict(全合格=True, wrapper_SHA256=digest(Path(__file__)),
            **reads, 原金融=0, 保全金融本文=0, input=0, ledger=0, API=0,
            QA証跡=(qa.OUTPUT/qa.PROOF_NAME).relative_to(ROOT).as_posix(), 根目視確認=False)
        (OWNED/'公開一読境界の証跡.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    except BaseException:
        (OWNED/'False.json').write_text(json.dumps(dict(全合格=False, 原因=traceback.format_exc(),
            **reads, 原金融=0, 保全金融本文=0, input=0, ledger=0, API=0, 自動再実行=False),
            ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
