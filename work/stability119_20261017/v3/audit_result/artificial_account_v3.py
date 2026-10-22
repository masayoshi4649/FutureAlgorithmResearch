"""v3保存会計監査器へ手計算ログを与え、追加後損失と未清算を確認する。"""

import hashlib
from pathlib import Path

import numpy as np

import audit_result_v3 as owner


def main() -> None:
    """
    機能: 全返済・未清算・悪い追加gapの独立手計算を監査器へ接続する。
    引数: なし。
    返り値: None。市場・cache・金融エンジンを読まない。
    """
    O, P = owner.definitions()
    quote = dict(row=np.arange(4), time=np.arange(4, dtype=float),
                 bid=np.asarray([3999.5, 3999.5, 4002.5, 4003.]),
                 ask=np.asarray([4000., 4000., 4003., 4003.5]))
    bars = dict(pub_raw_row=np.arange(4), pub_price_time_s=np.arange(4, dtype=float),
                t_s=np.arange(4, dtype=float), valid=np.ones(4, dtype=bool), anchor=np.full(4, 4000.))
    orders = np.asarray([[1, 1, 0, 1, 0., 1., 1, 2, 2, 4000., 83., 2, 4000., 5., 3995.],
                         [1, 3, 2, 3, 2., 3., -1, 2, -2, 4003., 83., 0, 4000., 5., 3995.]])
    parents = np.asarray([[1, 1, 0, 0, 1, 3, 1., 3., 4000., 4000., 2, 2, 2, 0, 5., 10166.,
                           83., 83., 6000., 5834., 4, 0, 3995., 4003., -1166., 5834., 1]])
    answer = owner.account(orders, parents, bars, quote, 10, 1000., 41.8, dict(allocation_mode=0, trail_multiple=1.), O, P)
    owner.audit.near(answer["summary"]["net"], 5834., "手計算純額")
    owner.audit.near(answer["equity"], [0., -1166., 4834., 5834.], "手計算公開MTM")
    owner.audit.near(answer["quantity"], [0, 2, 2, 0], "手計算公開数量")
    owner.audit.near(answer["summary"]["max_drawdown"], 1166., "手計算最大下落")
    opened = owner.account(orders[:1], np.empty((0, 27)), bars, quote, 10, 1000., 41.8,
                            dict(allocation_mode=0, trail_multiple=1.), O, P)
    owner.audit.near(opened["summary"]["unclosed"], 2, "未返済をフラットへ化けさせない")
    owner.audit.near(opened["summary"]["realized"], -83., "未清算の実支払費用")
    owner.audit.near(opened["summary"]["net"], 5834., "未清算評価は予定返済費用込み")
    quote = dict(row=np.arange(5), time=np.arange(5, dtype=float),
                 bid=np.asarray([3999.5, 3999.5, 4002.5, 3989.5, 3980.]),
                 ask=np.asarray([4000., 4000., 4003., 3990., 3980.5]))
    bars = dict(pub_raw_row=np.arange(5), pub_price_time_s=np.arange(5, dtype=float),
                t_s=np.arange(5, dtype=float), valid=np.ones(5, dtype=bool), anchor=np.full(5, 4000.))
    orders = np.asarray([[1, 1, 0, 1, 0., 1., 1, 2, 2, 4000., 83., 2, 4000., 5., 3995.],
                         [1, 2, 2, 3, 2., 3., 1, 2, 2, 3990., 83., 4, 3995., 5., 3995.],
                         [1, 3, 3, 4, 3., 4., -1, 4, -4, 3980., 167., 0, 3995., 5., 3995.]])
    parents = np.asarray([[1, 1, 0, 0, 1, 4, 1., 4., 4000., 3995., 2, 4, 4, 1, 5., 10166.,
                           166., 167., -60000., -60333., 5, 0, 3995., 4002.5, -60333., 4834., 1]])
    answer = owner.account(orders, parents, bars, quote, 10, 1000., 41.8, dict(allocation_mode=2, trail_multiple=1.), O, P)
    owner.audit.near(answer["summary"]["net"], -60333., "追加後gapの手計算純額")
    owner.audit.near(answer["summary"]["fees"], 333., "追加ごとの費用と一括close")
    owner.audit.near(answer["summary"]["max_drawdown"], 65167., "追加後gapの手計算下落")
    owner.audit.check(owner.READS == dict(結果=0, v3cache=0, 既所有quote=0, 原市場=0, 原cache追加=0, 金融再実行=0), "人工だけ")
    proof = dict(全合格=True, 検査数=owner.audit.CHECKS, counts=owner.READS,
                 監査源SHA256=hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest(),
                 人工源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    owner.write(Path(__file__).resolve().parent / "保存会計監査器の手計算ログによる純人工.json", proof)
    print(proof)


if __name__ == "__main__":
    main()
