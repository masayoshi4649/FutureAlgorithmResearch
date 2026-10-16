"""古い支持・最新支持・極値後支持を、自己と双方で分ける十条件。"""
from pathlib import Path
import importlib.util


def catalog():
    """
    機能: 元GUとT2_P1へ同じ五つの支持条件を組み合わせる。
    引数: なし。
    返り値: list[dict]。
    """
    path=Path(__file__).resolve().parents[2]/'wave_v86/phase2/catalog.py'
    spec=importlib.util.spec_from_file_location('wave87_round3_prior_catalog',path)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    base=next(c for c in old.catalog() if c['id']=='T2_P1')
    labels=('元の120秒保持','自己の最新支持','自己の極値後支持','双方の最新支持','双方の極値後支持')
    return [dict(base,id=f'{parent}_F{f}',name=parent+'・'+labels[f],support_mode=f,
        parent_id=parent,source_id='E01_G_U' if parent=='GU' else 'T2_P1',
        changes={} if parent=='GU' else dict(base['changes'])) for parent in ('GU','P1') for f in range(5)]


def specification():
    """
    機能: 支持の時間順と注文公開順を明記する。
    引数: なし。
    返り値: dict。
    """
    return dict(件数=10,主仮説=['GU_F2','P1_F2'],
        F0='旧120秒支持保持を変更しない。元GU/T2_P1への全配列一致対照。',
        F1='自己の最新公開30秒中値変化/当時ATRが方向へ0.05を超える間だけ新規注文を公開。最新の有効非支持や欠測では次観測から注文無効。',
        F2='F1に加え、支持窓終端の原本seqが今の追跡極値seqより後であることを要求。同値では極値seqを更新しない。',
        F3='F1に相手の最新30秒支持も追加。自己現在時刻より厳密過去に公開された相手イベントだけを参照。',
        F4='F2に相手の最新支持と、その窓終端時刻が自己極値時刻より後であることを追加。双方の同時計未観測行は使用しない。',
        特徴='元の公開イベント時刻を基準とした30秒中値差と当時ATRを完全再現。30秒窓全体が極値後という条件ではなく、終端だけが後という条件。新しい時間鮮度の閾値を付加しない。',
        実行順='前の観測で有効だった注文を現在価格で評価し、その後に現在までの支持・極値・線を更新して次観測へ公開する。当行成立した旧注文を、当行の支持低下で後から取り消さない。',
        内部待機='無効中も元のTTLと極値追跡を継続。古い中期状態で準備は続けるが、短期条件が無効なら外へ新規注文を出さない。元G失効やTTL終了による準備破棄は維持。',
        再有効化='現在値が既に追跡線を越えていたら次観測の価格で約定する成行状態として公開。昔の有利な線では指定価格約定を復活させない。',
        出口='GUは元の広幅と通常影時計、P1はT2狭幅と親組黒字後60秒の再参加。数量・料金・途中半減・U見送りは旧系統を維持。',
        既知='全30場・前16/後14とも既知。round1の前回利確後EMA再成立や前組高安突破とは別に、各準備の極値と30秒支持を対応する。',
        API取得=0,実注文=0)
