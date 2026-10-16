"""同じ数量十一条件を、複数返済に対応する会計で再評価する。"""

from pathlib import Path
import importlib.util


def source():
    """
    機能: 凍結した数量条件の定義を読み取る。
    引数: なし。
    返り値: module。
    """
    path = Path(__file__).resolve().parent.parent / 'round4/catalog.py'
    spec = importlib.util.spec_from_file_location('wave87_round6_catalog_source', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def catalog():
    """
    機能: 失敗時に固定した数量条件を、そのまま一意のIDへ対応させる。
    引数: なし。
    返り値: list[dict]。取引パラメータは不変更。
    """
    return [dict(c, id='A_'+c['id'], source_condition=c['id'], source_id='E01_G_U') for c in source().catalog()]


def specification():
    """
    機能: 再評価の理由と、取引条件を変えていないことを記録する。
    引数: なし。
    返り値: dict。
    """
    value = source().specification()
    value['主仮説'] = 'A_D05_R'
    value['会計修正'] = '同時刻の複数返済注文の料金を辞書で上書きせず、数量キューから脚へ配賦する。取引再生器・条件はround4の凍結版をそのまま使う。'
    value['旧段階'] = 'round4は旧会計の料金総額検算で停止。保存済み追加なし3対照を再照合し、失敗結果は採用しない。'
    return value
