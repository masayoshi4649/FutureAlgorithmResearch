"""選定仕様の全50保存場を、条件を変えず移植照合用へ展開する。"""

from pathlib import Path
from extract_fixture143 import HERE, ROOT, RESEARCH, shared, extract, digest, write_json


def main():
    """
    機能: 全50場の凍結入力と保存注文だけを読み、独立同値試験の素材を作る。
    引数: なし。返り値: None。四場の標準fixtureと過去研究会計は変更しない。
    """
    packets,_,_=shared.material();output=HERE/'fixtures_all';output.mkdir(exist_ok=True)
    plan=dict(purpose='既存TG04/PG04のGo移植の独立同値検査。金融探索や新規優位性評価ではない。',
        entry='研究143で固定した昼O17/G02/20分帯回復、夜O02/C13/40分帯反発。候補通知の判断行以前への参照禁止。',
        management='元担当の独立仮想状態と実玉の分離。利益追尾で最古1枚の残玉化、実現純益確定後の予算化。',
        exit='H04：実現純益100%の床又は3R追尾。米国寄付前後15分・既存場末清算。',
        allocation='TG04は5/3/2、PG04は5/5、日経mini片方向上限10枚、空き枠の貸借なし。',
        costs='mini片道38.5円、注文ごと切捨て。利益/損失は完結親手数料後。',
        execution='発注判断の次の正常自己原行BBO。予定済発注の境界取消や場末一行差を許容しない。',
        data=dict(sessions=[p['session'] for p in packets],packets=packets,price_clock='原価格時計、実受信時計ではない',model='ラージBBOによるmini代理'),
        implementation={str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),HERE/'extract_fixture143.py',RESEARCH/'profit_residual143.py',RESEARCH/'core_overlay_v2_143.py']},
        restrictions=['期待約定・最終方向・完結損益を戦略入力へ渡さない','全50場は既知開発で未見検証とは呼ばない','再集計を過去成績へ上書きしない'],new_financial_replays=0)
    write_json(HERE/'全50場移植同値計画.json',plan)
    cases=[]
    for item in packets:
        casefile=output/(item['session']+'_extraction.json')
        if casefile.exists():
            case=shared.read(casefile)
        else:
            case=extract(item['session'],item,output)
            write_json(casefile,case)
        cases.append(case)
        print(item['session'],'保存入力・期待注文の全行抽出完了',flush=True)
    write_json(output/'manifest.json',dict(schema=1,scope=plan['purpose'],cases=cases,
        plan=dict(path=str((HERE/'全50場移植同値計画.json').relative_to(ROOT)),sha256=digest(HERE/'全50場移植同値計画.json')),
        new_financial_replays=0,live_orders=0))


if __name__=='__main__':main()
