"""原版とＧ・ＧＵの入口、低リスク利益床、公開気配予算を分離する固定条件。"""

from copy import deepcopy
from pathlib import Path
import sys

TASK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK / 'design'))
from catalog126 import catalog as original_catalog


def policies() -> list[dict]:
    """
    機能: 数値核を変えず、既存十六条件へ開始閾値だけ異なる三条件を加える。
    引数: なし。
    返り値: list[dict]は十九個の条件。金融入力を読まない。
    """
    values = original_catalog()
    prototype = next(value for value in values if value['id'] == 'P01')
    for identifier, threshold in (('P025', .25), ('P050', .5), ('P075', .75)):
        value = deepcopy(prototype)
        value.update(id=identifier, protect_start_atr=threshold,
                     name=f'二市場逆行時の利益床を{threshold}リスクから許可',
                     mechanism='利益保全開始閾値だけ変更')
        values.append(value)
    assert len(values) == 19 and len({v['id'] for v in values}) == 19
    return values


def catalog() -> list[dict]:
    """
    機能: 全五十三表示条件を、入口源・数値方策・公開気配条件へ明示分解する。
    引数: なし。
    返り値: list[dict]はＧ十九・ＧＵ十九・原版低閾値三・気配条件十二。
    """
    mapping = {value['id']: value for value in policies()}
    values = []
    for source in ('G', 'GU'):
        for value in policies():
            item = deepcopy(value)
            item.update(id=source+'_'+value['id'], paper_source=source,
                        policy_id=value['id'], quote_gate_enabled=False)
            values.append(item)
    for identifier in ('P025', 'P050', 'P075'):
        item = deepcopy(mapping[identifier])
        item.update(id='E01_'+identifier, paper_source='E01',
                    policy_id=identifier, quote_gate_enabled=False)
        values.append(item)
    # ----------------------------------------
    # 入口気配の効果と低閾値利益床の効果を、それぞれ同じ元入口で比較する。
    for source in ('E01', 'G', 'GU'):
        for identifier in ('E01', 'P025', 'P050', 'P075'):
            item = deepcopy(mapping[identifier])
            name = source+'_Q'+('' if identifier == 'E01' else '_'+identifier)
            item.update(id=name, paper_source=source, policy_id=identifier,
                        quote_gate_enabled=True, quote_budget_atr=.5)
            values.append(item)
    assert len(values) == 53 and len({v['id'] for v in values}) == 53
    return values


def specification() -> dict:
    """
    機能: 入口公開時の可否と同値結果再利用の固定規則を返す。
    引数: なし。
    返り値: dictは未来価格を使わない手順と既知の限界。
    """
    return dict(
        気配判定='紙上新規通知の公開行で正常bid/askを要求し、spreadと不利側気配差がともに固定初回ATRの半分以下なら許可。有利な差は許可。',
        公開時点='orders列零の通知公開行。列一の古い準備行へ遡らず、同じ公開行のLastと気配を比較する。',
        不参加='入口で拒否した親の後続返済通知も、保存した採否によって除外。紙上影そのものは維持。',
        約定='受付後は凍結済み次正常原行BBO核を使用。将来fillで受付可否を変更しない。',
        低閾値='P01の利益床条件は維持し、既知最高益の開始だけ〇・二五／〇・五／〇・七五Rへ変更。反対成立行だけ最高益半分へ床を上げる。',
        数量='TOPIXミニ初回五枚・上限十枚、日経マイクロ初回十枚・上限二十枚、増玉なし、手数料零。',
        同値引用='同じ商品場・同じ準備packet・同じ凍結数値源に限定し、初回ATR込み十列通知bytesと四数値方策bytesが同じ場合だけ保存結果を引用する。',
        同値範囲='旧十六条件を先にseedし、新五十三条件内でも同じキーを一度だけ金融実行。商品場を跨いだ引用は禁止。',
        非参照='キーと気配フィルタは親の最終損益・終了時刻・未来極値を参照しない。初回固定ATRだけを既保存cycles列五から取り出す。',
        限界='気配予算は初回から不利な約定を避けるだけ。正常気配で始まった後の方向失敗と利益返しを防ぐ保証はなく、利益床は後の回復も捨て得る。')
