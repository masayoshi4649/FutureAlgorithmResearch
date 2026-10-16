"""正式試行照合の終端と完成ファイルの指紋だけを検査する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = HERE.parents[1]
MANAGER = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
PUBLIC = ROOT / 'アルゴリズム調査/00113_現在の注文活動と再進行から波の中間に参加'
PROOF = HERE / '正式deep検査終端と完成十七源及び公開成果物の指紋確認.json'


def digest(path: Path) -> str:
    """
    機能: ファイルを意味解析せずstreamでSHA256だけ計算する。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。金融結果JSONもparseしない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_small(path: Path) -> dict:
    """
    機能: 既存小証跡又は正式計画を上限付きで読む。
    引数: path(Path)は小JSON。
    返り値: dictは保存metadata。大金融結果やcacheは対象外。
    """
    assert path.stat().st_size < 2_000_000
    return json.loads(path.read_bytes())


def main() -> None:
    """
    機能: 正式ルートverify --deepを終端まで回収し、既存証跡へ現在指紋を結ぶ。
    引数: なし。
    返り値: None。金融再生・結果意味内容再読・文書変更は行わない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    assert not PROOF.exists() and not (HERE / '開始.json').exists()
    command = [sys.executable, '-B', '-X', 'utf8', str(MANAGER), 'verify', '--deep']
    started = dict(目的='試行台帳と根拠指紋の正式終端確認。金融監査は再実行しない。', command=command,
        workdir=str(ROOT), 元金融結果の意味解析=0, 元入力cache=0, NPZ=0, 原板=0, API=0, 金融再生=0,
        直接金融結果読取='SHA256のstream走査のみ', 文書変更=0)
    (HERE / '開始.json').write_text(json.dumps(started, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    try:
        old = load_small(BASE / 'technical_audit/diagnosis_audit/九条件と六例及び初期支持線比較の独立限定診断監査.json')
        fixed = load_small(BASE / 'root_review/金融事前固定.json')
        plan = load_small(BASE / 'root_review/試行計画.json')
        expected_sources = old['経済17source_SHA256']
        before = {name: digest(ROOT / name) for name in expected_sources}
        assert len(before) == 17 and before == expected_sources == fixed['source_SHA256'] == plan['spec']['implementation']
        assert fixed['全合格'] and fixed['正式freeze'] and plan['正式freeze']
        assert digest(BASE / 'root_review/試行計画.json') == fixed['計画SHA256']
        public_manifest = load_small(BASE / 'technical_audit/report_audit/公開一読と同bytes保全の目録.json')
        published = {}
        for name, entry in public_manifest['成果物'].items():
            actual = digest(PUBLIC / name)
            assert actual == entry['SHA256'], (name, actual, entry['SHA256'])
            published[name] = actual
        result_path = BASE / 'root_review/finance/結果.json'
        financial_digest = digest(result_path)
        assert financial_digest == old['金融結果への系譜']
        common_root = ROOT / 'アルゴリズム調査/共通'
        expected_common = {'知見台帳/' + name for name in ('README.md', '入口.md', '継続.md', '出口.md', '売買の工夫.md')}
        common_paths = [path for path in common_root.rglob('*') if path.is_file()]
        assert {path.relative_to(common_root).as_posix() for path in common_paths} == expected_common
        common_hashes = {path.relative_to(ROOT).as_posix(): digest(path) for path in common_paths}
        print(json.dumps(dict(開始=True, 金融は指紋だけ一致=True, 経済十七源一致=True, 共通五MDのみ=True), ensure_ascii=False), flush=True)
        started_clock = time.monotonic()
        process = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=3600, creationflags=subprocess.CREATE_NO_WINDOW)
        elapsed = time.monotonic() - started_clock
        (HERE / '正式verify_deep標準出力.json').write_bytes(process.stdout)
        (HERE / '正式verify_deep標準エラー.txt').write_bytes(process.stderr)
        assert process.returncode == 0, (process.returncode, process.stderr.decode('utf-8', errors='replace'))
        terminal = json.loads(process.stdout.decode('utf-8'))
        assert terminal['全合格'] and terminal['正本と閲覧データ一致'] and terminal['根拠指紋検証']
        after = {name: digest(ROOT / name) for name in expected_sources}
        assert before == after
        output = dict(全合格=True, 終了コード=process.returncode, 経過秒=elapsed, 正式実行=started,
            正式終端結果=terminal, 経済17source_SHA256=after, 正式計画SHA256=fixed['計画SHA256'],
            金融結果=dict(path=result_path.relative_to(ROOT).as_posix(), SHA256=financial_digest,
                         bytes=result_path.stat().st_size, 読取方法='streamによるSHA256のみ。JSON意味内容parse=0。'),
            公開成果物_SHA256=published, 共通領域=dict(ファイル数=5, 指定五MDのみ=True, SHA256=common_hashes),
            既存比較証跡='technical_audit/diagnosis_audit/九条件と六例及び初期支持線比較の独立限定診断監査.json',
            留保='正式verify --deep自体は台帳metadataを読み、登録根拠ファイルの指紋を照合する。新金融や親会計再計算はしない。',
            金融結果意味内容再読=0, 原板=0, NPZ=0, cache意味内容読取=0, API=0, 新金融=0, 文書変更=0,
            監査sourceSHA256=digest(Path(__file__)))
    except Exception as error:
        output = dict(全合格=False, 理由=str(error), traceback=traceback.format_exc(),
            金融結果意味内容再読=0, 原板=0, NPZ=0, cache意味内容読取=0, API=0, 新金融=0, 文書変更=0)
        PROOF.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
    PROOF.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 終了コード=process.returncode, 経過秒=elapsed, 証跡=str(PROOF), SHA256=digest(PROOF)), ensure_ascii=False))


if __name__ == '__main__':
    main()
