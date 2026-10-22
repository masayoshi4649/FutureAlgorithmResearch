"""公開・目視・七試行同期を確認し、復元用の進捗を実際の終了状態へ整える。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 完了済みの小証跡だけを読む。
    引数: path(Path)はUTF-8 JSON。
    返り値: dictは検査結果。市場や巨大台帳は再解析しない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    """
    機能: 全完了証跡が揃った場合だけ、最終状態と限界を復元用記録へ保存する。
    引数: なし。
    返り値: None。研究終了を安定黒字目標の達成へ置き換えない。
    """
    published=ROOT/'アルゴリズム調査/00120_段階トレーリング新規と利益玉の部分回転'
    meta=read(published/'公開目録.json')
    final=read(HERE/'七試行の終了とビュー同期.json')
    qa=read(HERE/'public_finish120/公開四段階114条件と主表全40場及び全導線の最終確認.json')
    assert final['passed'] and final['deep'] and final['unrelated_unchanged']
    assert final['目標達成の宣言'] is False and len(final['statuses'])==7
    assert qa['passed'] is True
    main_html=published/'段階トレーリングの結論と全セッション損益.html'
    actual=hashlib.sha256(main_html.read_bytes()).hexdigest()
    assert actual==meta['main_sha256']
    visual=[]
    for directory in ('desktop','mobile'):
        candidates=[read(p) for p in (HERE/'visual'/directory).glob('*.json')]
        proof=next(p for p in candidates if 'viewed_by_root' in p)
        assert proof['viewed_by_root'] and proof['dark'] and not proof['horizontalOverflow']
        assert proof['rows']==40 and proof['source_SHA256']==actual
        visual.append(proof)
    common=ROOT/'アルゴリズム調査/共通/知見台帳'
    names={'README.md','入口.md','継続.md','出口.md','売買の工夫.md'}
    assert {p.name for p in common.iterdir() if p.is_file()}==names
    anchors={p.stem:p.read_text(encoding='utf-8').count('<a id="00120_') for p in common.glob('*.md')}
    assert sum(anchors.values())==8
    value=dict(状態='四段階114条件の研究・公開・知見8法則・7試行台帳終了まで完了。安定黒字目標は未達。',
        正本ルート=ROOT.as_posix(),公開=main_html.relative_to(ROOT).as_posix(),
        completed_policies=114,sessions=40,completed_financial_accounts=9120,
        both_net_positive=meta['both_net_positive'],qualification_count=meta['qualification_count'],
        未返済=0,独立会計='b3840/c1920/d1920/e1 1440の全9120一致',
        実行履歴=final['statuses'],
        停止の扱い='120の保存48も未採用、追加未保存数は未確定。120aとeは実データ実行0、e1だけが最新18条件。',
        主な知見='入口例と鏡像は4/4純人工一致。逆側枚数超過は起きるが回収完了とは違う。個別利確でカバーを失う。保持で二場を救っても他場と上限ロックの損失は残る。',
        knowledge_anchors=anchors,root_visual_checked=True,public_QA=True,registry_parse=1,
        financial_replay_for_closure=0,API=0,実注文=0,
        限界='全114は同じ既知40場の開発。ラージBBO代理、真受信順/待ち順位/実小型板未観測。全手法の不可能性は証明していない。',
        次='追加金融は行わず、今回の結論と公開リンクを利用者へ返す。新たな依頼・入力の時は共通知見と登録済み仕様を先に確認する。')
    (HERE/'進捗メモ.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (HERE/'最終の公開と知見及び台帳の閉鎖確認.json').write_text(json.dumps(dict(passed=True,
        main_sha256=actual,knowledge_anchors=anchors,public_QA=True,root_viewed=True,
        statuses=final['statuses'],目標達成=False,financial_replay=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('114条件・40場の公開、8法則、7試行の終了を確認。安定黒字は未達。')


if __name__=='__main__':
    main()
