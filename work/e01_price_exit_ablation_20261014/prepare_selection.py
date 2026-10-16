"""00109の新OFF十二条件だけを対象に、結果前の表示選定とコピー出典を固定する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT/'work/e01_protect_reentry_20261014'


def digest(path: Path) -> str:
    """
    機能: 選定・表示source・根保存小射影だけの指紋を求める。
    引数: path(Path)は明示した小資料。
    返り値: strはSHA256。金融結果・input・台帳は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 108と同じ評価順を、新OFF十二条件の一回設定へコピーする。
    引数: なし。コピー元の既固定小選定・sourceだけを参照する。
    返り値: None。新金融本文は読まず、旧ONを新候補へ算入しない。
    """
    source = SOURCE/'報告書選定の事前固定_v1.json'
    assert digest(source) == '75fae8c12c1755ddbb720a2790214e652bf68d3b416440e354d2686ad4b6e83b'
    target = HERE/'報告書選定の事前固定_v1.json'
    assert not target.exists(), '選定を結果前に一度だけ固定する。'
    value = json.loads(source.read_text(encoding='utf-8'))
    value['段階'] = '00109新OFF十二条件の金融本文閲覧前'
    value['旧評価訂正'] = dict(旧00108全十二主条件合格数=0,
        解釈='旧ON十二条件は全商品net赤字。保存集計だけを一対一比較し、新候補へ算入しない。')
    value['改訂理由'] = '反対価格更新票による単独返済reason152だけOFF。同じ十二再参加・保護条件の対照。主平均・目標・順位は00108と同じ。'
    value['旧選定SHA256'] = digest(source)
    value['コピー元選定SHA256'] = digest(source)
    value['選定対象'] = '新OFF十二条件のみ。対応する旧ON十二条件は全場・上位三除外・買売集計だけの候補外比較。親別・場別ON差は未測。'
    value['標本'] = '同じ保存三十三場の既知内探索。新十二OFF条件を独立未知標本と呼ばない。'
    value['禁止'].append('旧ON親別又は場別比較が未保存のとき、空値を0に補完して改善額を作らない。')
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    report_sha = '75431d6caeaa3678d7549427c057beaef4360826da922e7ff8fb6cf5057305a8'
    qa_sha = 'ba17157ff2fa2d8e17ed5ca3e4232c9ec3ca24a441103bfa5e70dc9f41c640af'
    assert digest(SOURCE/'report.py') == report_sha and digest(SOURCE/'report_view.py') == qa_sha
    comparison = HERE/'comparisons/108_ON十二条件の候補外保存集計.json'
    assert digest(comparison) == '14c6bc436ad917ff85837e94ff038d36e23a417787dd3cbe723766fabaaca4c5'
    proof = dict(全合格=True, 選定SHA256=digest(target), コピー元表示SHA256=report_sha,
        コピー元QASHA256=qa_sha, 旧ON集計SHA256=digest(comparison), 新候補=12,
        旧ON候補算入=0, 金融結果=0, 旧108金融本文=0, input=0, ledger=0, API=0, 公開=0)
    (HERE/'表示sourceのコピー出典.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
