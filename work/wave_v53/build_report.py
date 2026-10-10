"""固定した50条件の損益と売買位置を、短い暗色レポートへまとめる。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / 'アルゴリズム調査/00050_一般的な分析と板確認と損益管理'
TITLE = '一般的な分析と損益管理の検証.html'


def read(path: Path) -> dict:
    """機能: 保存済みの日本語JSONを読む。

    引数: path(Path)。返り値: 内容(dict)。外部通信は行わない。
    """
    return json.loads(path.read_text(encoding='utf8'))


def charts() -> dict:
    """機能: 公開済み1分中値足を表示用の5分足に集約する。

    引数: なし。返り値: 銘柄・セッション別の表示足(dict)。
    表示専用で売買判断を再計算せず、欠落分を補間しない。
    """
    with (HERE / '特徴.pkl').open('rb') as stream:
        features = pickle.load(stream)
    result = {'TOPIX': {}, 'NK225': {}}
    for (session, symbol), frame in features.items():
        rows = []
        for start, group in frame.groupby((frame.bar_start // 300).astype('int64') * 300, sort=True):
            rows.append([int(start), float(group.open.iloc[0]), float(group.high.max()),
                         float(group.low.min()), float(group.close.iloc[-1]), int(len(group))])
        result[symbol][session] = rows
    return result


def main() -> None:
    """機能: 全50条件・全注文を持つ自己完結型HTMLを生成する。

    引数: なし。返り値: なし(None)。既存結果からの表示のみを行う。
    """
    results = read(HERE / '売買結果.json')
    assert len(results['methods']) == 50, '個別48条件と統合2条件を揃えてください'
    methods = results['methods']
    for method in methods:
        for account in method['accounts']:
            assert len(account['orders']) == 0 or len(account['orders'][0]) == 13
            account.pop('trades', None)
    evaluation_path = HERE / '報告評価.json'
    evaluation = read(evaluation_path) if evaluation_path.exists() else {
        'headline': '入口12種に、確認と損益管理を重ねて50条件を比較。',
        'findings': [
            '主比較は同じ状況選択を使うAUTO_AとAUTO_D。結果を見て最良手法へ差し替えていません。',
            '全50条件は下表で比較できます。収支順は今回のデータ内の探索順位で、未見の成績を保証する順位ではありません。',
        ],
        'audit': [],
    }
    data = dict(results=results, charts=charts(), evaluation=evaluation,
                rules={
                    'A': ['候補条件が成立した次の有効原本行で入る。', '初期ストップを維持し、1R進めば1R幅で追う。', 'ストップ・反対の生信号・30分経過・場内期限で返済。'],
                    'B': ['Aと同じ候補条件で入る。', '進捗・構造・板・時間で保護を強め、一度だけ半減。', '5分で0.25R未達なら撤退。状況別時間上限と損失制限で返済。'],
                    'C': ['候補に板の反応を確認し、相手銘柄が明瞭に逆なら見送る。', 'Aと同じ初期ストップと1R幅の追跡。', 'Aと同じ返済条件。確認前の反対生信号を使う。'],
                    'D': ['Cと同じ板・相手の確認を通った候補で入る。', 'Bと同じ進捗・構造・板・時間の管理と一度の半減。', 'Bと同じ状況別の早期撤退・時間上限・保護で返済。'],
                })
    # ----------------------------------------
    # 全注文は保持し、返済脚との重複だけを表示データから取り除く。
    template = (HERE / 'report_template.html').read_text(encoding='utf8')
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    content = template.replace('__DATA__', payload)
    assert content.count('__DATA__') == 0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / TITLE
    path.write_text(content, encoding='utf8')
    meta = dict(主HTML=str(path), バイト数=path.stat().st_size,
                SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                手法数=len(methods), セッション数=len(results['sessions']),
                注文数=sum(len(a['orders']) for m in methods for a in m['accounts']),
                外部描画ライブラリ=0, 現在API取得数=0)
    (OUTPUT / '生成記録.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main()
