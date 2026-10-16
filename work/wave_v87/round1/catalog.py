"""追加入口の失敗原因を三部品へ分けて固定する。"""
from pathlib import Path
import importlib.util


def catalog():
    """
    機能: 同調・前高安の四条件と停止幅三条件の十二通りを定義する。
    引数: なし。
    返り値: list[dict]。売買成績による条件変更は行わない。
    """
    path = Path(__file__).resolve().parents[2] / 'wave_v86/phase2/catalog.py'
    spec = importlib.util.spec_from_file_location('wave87_prior_catalog', path)
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    base = next(c for c in prior.catalog() if c['id'] == 'T2_P1')
    names = ('元の利確後再参加', '同調の別周期', '前組高安の再突破', '別周期と再突破')
    result = []
    for gate in range(4):
        for stop in (.75, .5, .25):
            code = f'R{gate}_S{int(stop*100):02d}'
            result.append(dict(base, id=code, name=f'{names[gate]}・初期停止{stop:g}ATR',
                changes=dict(base['changes'], stop_atr=stop), reentry_filter=gate,
                source_id='T2_P1', stop_atr=stop))
    return result


def specification():
    """
    機能: 改修の判定時点・対象・反証可能性を明記する。
    引数: なし。
    返り値: dict。
    """
    return dict(件数=12,主仮説='R3_S50',
        入口='元E01_G_Uの二市場EMAと反発追跡新規。料金後黒字で親組全返済した場合だけ60秒後に新準備。',
        出口='T2の始動0.75ATR・追跡幅0.5ATRを固定。初期停止だけ0.75/0.5/0.25ATRを比較。通常影設定・途中半減の通常影MFEは変更しない。',
        R0='元の利確後再参加。停止0.75は旧T2_P1完全一致を検査する。',
        R1='黒字全返済後、両公開元が返済行より新しい有効EMAで元方向の非支持を一度確認し、同じ有効性と新公開元で元方向へ再支持した後に新準備。欠測は非支持に数えない。',
        R2='前の実親組の全保有観測（部分返済後・最後の返済観測を含む）の現在値高安から、買いは最高値+1呼値、売りは最安値−1呼値を発注成立線へ重ねる。通常の反発追跡線と厳しい方を使い、待機中も緩和しない。',
        R3='R1とR2の両方。',
        対象='追加入口条件は料金後黒字全返済に続く同方向の再参加だけ。初回・反対方向の新規は対象外。次の実新規で権利を消費し、TTL・欠測・米国静観では解除しない。',
        赤字終了='新たな早期再参加や条件を発動せず、通常影が自然終了してから300秒待つ元P1を維持する。黒字後に破棄した影の反実仮想の終了を推定しない。',
        有効時点='現在行で作った待機条件は次の原本観測以降で有効。実際の経過秒とは限らない。全返済行で同じ行に新規しない。',
        診断='旧T2_P1の追加入口を全既知30場で診断した後の探索。前半・後半はどちらも既知であり未知検証と呼ばない。高安突破・再同調だけで有効性が証明されたわけではない。',
        評価='各商品内で利益・損失・料金・純利益・親組利益割合・活動場・下落を比較する。二商品の円額を合算しない。',
        API取得=0,実注文=0)
