"""米国後の指標初期化と入口時計を切り分ける4条件を事前登録する。"""

import importlib.util
import json
from pathlib import Path
import zipfile
from datetime import datetime, timezone, timedelta
from register149 import HERE, ROOT, reference, digest


def main():
    """第一巡の結果を保持し、第二巡の変更点だけを別試行に記録する。

    引数: なし。
    返り値: None。成功時だけround2/登録受領.jsonを発行する。
    """
    out=HERE/'round2';out.mkdir(exist_ok=True)
    assert not (out/'登録受領.json').exists()
    plan=json.loads((HERE/'再生計画149.json').read_text(encoding='utf-8'))
    configs=json.loads((HERE/'configs_round2.json').read_text(encoding='utf-8-sig'))
    assert len(configs)==4
    plan.update(id='149_第二巡_指標履歴と後半準備時計の分離',name='米国後の指標履歴と準備時計を分離する4対照',
                purpose='条件比較',question='米国後の悪化は全状態初期化、価格履歴の破棄、主担当と補完の準備時計変更のどれによるか',
                change='S01はR02の指標だけ継続。S02はさらに元の主担当22分/補完30分時計を維持。S03は全指標初期化と元時計を組合せ。S04は前半のD07早期化なしでS02後半を用いる。',
                repeat_reason='第一巡R02は後半+7.8万円、C05は+88.7万円。R02にはUS全状態初期化と後半の入口時計変更が混在し、完全リセット単独の原因と断定できないため要因を分離する。',
                compares_to=['149_米国前の時刻制限と米国後の全初期化'])
    plan['spec']['entry']=dict(method='現D07の価格条件を維持。後半時計だけ元の22/30分又は統一15分で比較。',configurations=[dict(c,owners=c.get('owners') or '全担当') for c in configs])
    plan['spec']['management']=dict(method='全条件でUS15分前に実玉を全返済、US後の売買・予算・源状態は初期化。S01/S02/S04は特徴履歴だけ17時から継続、S03はUS以後だけで再構築。前半実損失を全体会計から消さない。')
    engine=HERE/'engine_go_round2'
    sources=sorted(p for p in engine.rglob('*') if p.is_file() and (p.suffix in ('.go','.toml') or p.name in ('go.mod','go.sum')))
    sources += [HERE/'configs_round2.json',HERE/'engine追加仕様149.md']
    frozen=out/'再生前実装.zip'
    with zipfile.ZipFile(frozen,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sources: archive.write(path,path.relative_to(HERE).as_posix())
    refs=[reference(p) for p in sources]
    plan['spec']['implementation']={frozen.relative_to(ROOT).as_posix():digest(frozen)}
    path=out/'計画.json';path.write_text(json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    manager_path=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec=importlib.util.spec_from_file_location('研究149第二巡管理',manager_path)
    manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)
    assert manager.analyzer().analyze(plan,[])['proposal_complete']
    print('第二巡4条件を凍結。既存試行と照合・登録します。',flush=True)
    record=manager.store_trial(plan)
    (out/'照合.json').write_text(json.dumps(record['preflight'],ensure_ascii=False,indent=2),encoding='utf-8')
    receipt=dict(id=plan['id'],registered=True,returncode=0,created_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
                 plan=reference(path),implementation=reference(frozen),inputs=reference(HERE/'data/原資料一覧149.json'),sources=refs)
    (out/'登録受領.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print('第二巡の登録完了。指紋確認後のみ再生可能。',flush=True)


if __name__=='__main__':
    main()
