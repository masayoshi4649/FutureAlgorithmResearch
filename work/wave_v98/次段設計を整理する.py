"""三担当の実装前案を根の未確定課題へまとめ、売買結果と混同しない。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 日本語の計画資料と前段終端を読む。
    引数: path(Path)はJSON資料。
    返り値: dict。提案又は完了した前段証跡。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 次段へ引き継ぐ設計案と前段成果を同一ファイルへ結びつける。
    引数: path(Path)はファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 98の未実装案と未解決境界を保存する。
    引数: なし。
    返り値: None。候補数、主、出口及び採用を損益前の次段へ残す。
    """
    prior_path = HERE.parent / 'wave_v97/97正式終端と98入力時計の未実行引継ぎ.json'
    prior = read(prior_path)
    assert prior['全合格'] and not prior['安定性の改善を採用']
    for relative, expected in prior['根拠SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    papers = []
    for name in ('design_engine', 'design_adversary', 'design_audit'):
        files = sorted((HERE / name).glob('*.json'))
        assert files, name+'の計画保存が未完了'
        for path in files:
            paper = read(path)
            for label, fingerprints in paper.items():
                if not label.endswith('SHA256') or not isinstance(fingerprints, dict):
                    continue
                for relative, expected in fingerprints.items():
                    if not isinstance(expected, str) or len(expected) != 64:
                        continue
                    assert digest(ROOT / relative) == expected, relative
        papers.extend(files)
    assert not (HERE / '事前固定.json').exists()
    assert not (HERE / 'front').exists() and not (HERE / 'back').exists()
    result = dict(
        段階='98の実装前の提案整理。正式な条件固定又は損益結果ではない。',
        優先='最大収益より毎セッションの赤字額、赤字頻度、両商品の悪い側を改善する。利益80%目標も残す。',
        前段='97の36条件全31を独立検算して00093へ公開。安定改善は採用せず。',
        原因='価格時計の飛びを受信断裂とみなして待機を取消していた。139件は原保存行が連続し、同じ価格時計の間にも板が変化していた。原seqは真受信時計や欠測検出番号ではない。',
        有限比較の共通点=[
            '旧J8候補と入口幅W、初期停止、料金、数量、場内返済を保持し、変更する機構を明示する。',
            'C0は厳密97。C1はgap取消だけ除去し、gap行の発注禁止を暗黙に追加しない。',
            'C2の各自anchor基準のseq更新及びclock非逆行は、両市場の共通phase後という旧証拠を変える別意味の案。単に観測救済と呼ばない。',
            'C3の別epoch再準備はC1と分け、幾何、基準、再準備行発注禁止、必要源を正式損益前に確定する。',
            '自己qok不正、reset、TTL、場末、硬い反対と未知又は未来peerをgap保持で救済しない。',
        ],
        根の追加反証='peer_clock>phaseかつpeer_clock<=own_nowならown_now>phaseは必然。自己phase時計要件だけをseqへ置換しても、この制約は消えない。各源のclock要件とpeer選択の冗長性を人工例で確かめ、同値の枝を独立した改善候補と数えない。',
        未確定=[
            '最終条件数、入口代表、出口の組合せ、理論主。設計担当の16案等は参考であり採用済みではない。',
            'C3のgap後に要求する証拠、再準備対象、未知基準の順序。保存点と枠を含め独立状態表で決める。',
            'C2のfallback及び共通phase時計を外す際の源資格。二市場の実受信順は保存データから証明できない。',
            '時計政策を変えても既存入力が保持する代理時刻・旧quality/reset等は変わらない。新たに真受信時計を発明しない。',
            '保持系列の原seq欠番は元の除外行を反映し得る。seq欠番だけを新たな通信中断と扱わない。新しい故障判定をC0へ足さず、C1もgap取消だけの差を維持する。',
            '深板や出来高の不正を価格経路の故障と分離するC4は敵対担当の追加参考。未知OFIを支持へ変えず、源資格を緩める場合は別条件として明記する。',
        ],
        次の順序=[
            '提案を統合して有限条件を損益前に固定する。旧対照と新機構の差を一軸で明示する。',
            '同clock板変化、gapとresetの共存、未知peer、TTL、候補競合、次BBO、再準備を少数の独立人工で検査する。',
            '旧対照の経済一致、実接頭及び未来変形、共通CLIと全期間集計の終端を検査してから凍結する。',
            '既知全31を前後に分けて再生し、各場損益、同候補の建値・返済・費用差、旧勝ちの消失と新損失を分離する。',
            '安定性が改善した場合にだけ現在セッションで一度答え合わせを検討する。実注文は行わない。',
        ],
        新98売買実装=0, 新98売買実行=0, 新98損益計算=0,
        現在API取得=0, 実注文=0, 探索目標='未達で継続',
        根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in papers+[prior_path, Path(__file__)]},
    )
    (HERE / '98実装前の独立設計整理と未確定事項.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(設計資料数=len(papers), 新98損益計算=0, 探索目標='未達で継続'), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
