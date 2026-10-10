"""監査と表示の指紋を照合し、目視済みの公開確認を保存する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
OUT=ROOT/'アルゴリズム調査/00072_二市場の即時板判断と保有管理'


def read(path: Path) -> dict:
    """機能: 保存した証跡を読み取る。

    引数: path(Path)。返り値: 証跡(dict)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def sha(path: Path) -> str:
    """機能: ファイルの指紋を返す。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 目視完了の明示と独立監査の成立後に公開用確認を記録する。

    引数: --visual-reviewed(bool)。返り値: なし(None)。画像の自動目視は行わない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--visual-reviewed',action='store_true');args=parser.parse_args()
    assert args.visual_reviewed,'目視完了後に明示して実行してください'
    fixed=read(WORK/'事前固定.json')
    assert all(sha(ROOT/name)==fingerprint for name,fingerprint in fixed['SHA256'].items())
    audit_paths=sorted((WORK/'audit').glob('*.json'))
    assert len(audit_paths)>=10
    assert all(read(path)['合格'] for path in audit_paths)
    ledger=read(WORK/'audit/全996条件と固定遅延84条件の会計選定独立監査.json')
    assert ledger['口座会計数']==1080*58 and ledger['主条件数']==996 and ledger['固定感度条件数']==84
    future=read(WORK/'audit/二市場実経路の片側未来と途中管理注文の独立監査.json')
    assert future['片側未来切断改変比較数']==480 and future['配列末尾の架空返済なし']
    htmls={}
    for label,name in [('主報告','二市場の即時判断と保有管理の説明と損益.html'),('全一覧','全996条件の比較.html')]:
        path=HERE/(label+'_表示の独立検査.json');proof=read(path)
        assert proof['全合格'] and proof['HTML_SHA256']==sha(OUT/name)
        proof['目視確認']=True
        proof['目視内容']='暗色の文字・表・軸・売買印、広幅と狭幅を確認。全管理対照と基準の売買座標、全場会計を独立照合。'
        path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
        htmls[name]=proof['HTML_SHA256']
    public=read(OUT/'公開会計.json')
    assert public['公開SHA256']==htmls and public['全合格']
    assert public['解析SHA256']==sha(WORK/'analysis/板支持による途中判断の効果と限界.json')
    proof=dict(全合格=True,監査確認=True,目視確認=True,HTML_SHA256=htmls,
        監査SHA256={path.name:sha(path) for path in audit_paths},固定SHA256=sha(WORK/'事前固定.json'),
        原本書込=False,現在セッションAPI取得=0,実注文=0)
    (HERE/'公開前確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(f'監査{len(audit_paths)}件・両HTMLの表示と指紋を確認しました',flush=True)


if __name__=='__main__':
    main()
