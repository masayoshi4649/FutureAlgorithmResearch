"""利確後だけ早く再準備する十条件を結果閲覧前に定義する。"""
from pathlib import Path
import importlib.util


def catalog():
    """
    機能: 元の出口五系統へ、黒字後60秒と0秒の再参加を組み合わせる。
    引数: なし。
    返り値: list[dict] の十条件。
    """
    path=Path(__file__).resolve().parent.parent/'catalog.py'
    spec=importlib.util.spec_from_file_location('wave86_p2_parent_catalog',path)
    parent=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parent)
    values=[]
    for item in parent.catalog():
        if item['clock_id'] not in ('A1','A0'): continue
        clock='P1' if item['clock_id']=='A1' else 'P0'
        value=dict(item,id=item['exit_id']+'_'+clock,clock_id=clock,
            name=item['name'].split('・')[0]+'・親組黒字後だけ'+('1分' if clock=='P1' else '次観測')+'で再準備',
            profit_fast_enabled=True,reentry_mode='profit_only')
        values.append(value)
    return values


def specification():
    """
    機能: 第一段階と区別した追加仮説と判定を固定する。
    引数: なし。
    返り値: dict。
    """
    return dict(主仮説='T3_P1',件数=10,
        理由='一律の早期再参加と、利用者が挙げた利確後の再参加は別仮説なので、黒字親組だけを区別する。',
        条件='部分返済を全て合算した親組全体の料金後確定損益が正なら早期再準備。最後の返済脚・理由名では判定しない。',
        誤差='内部価格単位を円換算し、1e-7円以下はゼロとして早期再参加を認めない。',
        対象='米国静観の強制返済でも、親組全体が料金後黒字なら対象。',
        黒字後='全返済の次の保存観測で両影と古い待機を破棄し、実返済時刻から60秒又は0秒後に新準備。静観窓・最初の強制確認観測は新準備禁止を優先。',
        赤字ゼロ後='実返済で通常影を切らず、元の通常影が自然終了してから300秒後の新準備を待つ。通常影の米国静観無視も元と同じ。',
        時計='last_exitは実観測時刻を保持。別の次準備可能時刻で早期再開を制御する。未来の通常影終了時刻を参照しない。',
        共通='出口五系統、入口・数量・半減・手数料・静観窓・約定モデルは第一段階と同じ。',
        評価='商品別に収支・利益割合・黒字場数・全原板最大下落を確認し、同出口S/A1/A0と比較する。円額を商品間合算しない。',
        検証='保存済み既知30場・前16後14。第1段階20条件は保存したまま変更しない。追加結果でパラメータを選び直さない。',
        API取得=0,実注文=0)
