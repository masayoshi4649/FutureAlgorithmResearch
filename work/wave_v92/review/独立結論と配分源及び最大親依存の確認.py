"""全場会計を維持して主の反証・部品の追加価値・配分と依存を簡潔に固定する。"""

import importlib.util
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: 独立会計の読取関数を固有名で接続する。
    引数: name(str)、path(Path)。
    返り値: object。読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


REVIEW = module('配分源と依存の独立会計92', HERE/'全場親会計と入口再参加の経路分解.py')


def load_ledgers(ident: str) -> dict:
    """
    機能: 前16と後15の保存台帳を排他的に接続する。
    引数: ident(str)。
    返り値: dict。全62口座の台帳。
    """
    result = {}
    for stage in ('front', 'back'):
        value = REVIEW.read(WORK/stage/'ledgers'/f'{ident}.pkl')
        assert not set(value) & set(result)
        result.update(value)
    assert len(result) == 62
    return result


def main() -> None:
    """
    機能: 配分の非干渉・対照重複・最大利益親除外を全場で検算し結論を保存する。
    引数: なし。
    返り値: None。固定後の条件・源を変更しない。
    """
    fixed = REVIEW.read(WORK/'事前固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert REVIEW.digest(ROOT/relative) == expected, relative
    full = REVIEW.read(WORK/'analysis/比較結果.json')
    proof = REVIEW.read(HERE/'全条件全31の独立親会計と同一新規及び再参加経路分解.json')
    cases = REVIEW.read(HERE/'主と事前参考の赤字上位3場及び回復中心の具体原板.json')
    distance = REVIEW.read(HERE/'主全親の極値停止距離と判断までの回復消費.json')
    assert proof['全合格'] and cases['全合格'] and distance['全合格']
    ledger_sets = {i: load_ledgers(i) for i in ('R0', 'R0_C', 'J8', 'M_RB25_C')}
    duplicate = 0
    for key in ledger_sets['R0']:
        a, b = ledger_sets['R0'][key], ledger_sets['R0_C'][key]
        assert np.array_equal(a['orders'], b['orders']) and np.array_equal(a['trades'], b['trades'])
        assert all(a[c] == b[c] for c in ('curve_SHA256', 'source_curve_SHA256', 'target_trace_SHA256'))
        duplicate += 1
    # ----------------------------------------
    # 固定8対2はJ8源の価格・判断・時価を変えず、反発2を足したものか確認する。
    mix = {}
    for symbol in ('TOPIX', 'NK225'):
        count = 0
        for key in ledger_sets['J8']:
            if key[1] != symbol:
                continue
            a, b = ledger_sets['J8'][key], ledger_sets['M_RB25_C'][key]
            left, right = a['orders'][a['orders'][:, 3] == 0], b['orders'][b['orders'][:, 3] == 0]
            columns = [0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
            assert np.array_equal(left[:, columns], right[:, columns])
            assert a['source_curve_column_SHA256'][0] == b['source_curve_column_SHA256'][0]
            count += 1
        view = full['results']['M_RB25_C']['periods']['全31'][symbol]
        reference = full['results']['J8']['periods']['全31'][symbol]
        sources = view['sources']
        g, loss = sum(v['profit'] for v in sources.values()), sum(v['loss'] for v in sources.values())
        ratio = g/(g+loss)
        assert abs(ratio-view['profit_share']) < 1e-12
        upper = max(v['profit_share'] for v in sources.values() if v['profit_share'] is not None)
        assert ratio <= upper+1e-12
        assert abs(view['net']-reference['net']-sources['O06']['net']) < 1e-4
        mix[symbol] = dict(J8価格判断及び全行清算一致口座=count,
            親ID及びUIDは源混在により変わるため照合から除外=True,
            同J8に反発を足した収支差円=view['net']-reference['net'],
            最大下落差円=view['equity_drawdown']-reference['equity_drawdown'],
            実配分源の金額割合={name: value['profit_share'] for name, value in sources.items()},
            配分金額割合=ratio, 実配分源の最高割合=upper, 加重平均上限一致=True)
    # ----------------------------------------
    # 最大の一勝に依存するか、事後診断として全36の親を一つだけ除く。
    dependence = {}
    for config in fixed['条件']:
        ident = config['id']
        ledgers = ledger_sets.get(ident) or load_ledgers(ident)
        dependence[ident] = {}
        for symbol in ('TOPIX', 'NK225'):
            parents = np.concatenate([ledgers[(session, symbol)]['trades'] for session in fixed['全31']])
            if len(parents):
                index = int(np.argmax(parents[:, 11]))
                removed = float(parents[index, 11])
                remaining = np.delete(parents, index, axis=0)
            else:
                removed, remaining = None, parents
            view = full['results'][ident]['periods']['全31'][symbol]
            values = REVIEW.totals(remaining)
            assert removed is None or abs(values['net']-(view['net']-removed)) < 1e-4
            dependence[ident][symbol] = dict(除外した最大親収支円=removed, 最大利益親除外=values,
                最大利益日=view['best_day'], 最大利益日除外=view['without_best_day'])
    primary = fixed['主']
    selected = REVIEW.read(WORK/'前16参考代表.json')['selected']
    conclusion = [
        '全36条件・全31場で両商品金額利益80%を達成した条件はない。主の極値停止は両商品赤字。前16参考は後成績で差替えていない。',
        '回復確認の追加価値は日経で確認できたが、TOPIXへ共通の優位は確認できなかった。同成行確認なしから双方確認Cへ変えた全経路差はTOPIX−14,148円・日経＋729,680円。',
        '極値停止はTOPIXの同一新規では管理差＋105,000円だった。しかし早期終了で増えた14親が−221,704円となり合計を悪化させた。日経では元勝ち10親を負けへ変え、同一新規−200,000円と新8親−77,520円で悪化した。',
        '観測極値外は一定の小損失幅ではない。双方確認までに自己の回復が進み、実取得価格から過去極値まで遠くなる。固定1幅より広い予定失敗線はTOPIX3/94親・日経19/115親にあった。',
        '利益追跡はTOPIXの同一新規21負けを利益へ救い改善した一方、日経では元34勝ちの利益を918,000円削った。損失抑制の追加価値は銘柄共通とは確認できない。',
        '中心帯へ帰還する再参加は、初回・出口を変えずに実装できた。しかし統合自己帰還は同TRからTOPIX−21,720円・日経−74,520円。双方帰還はTOPIX＋179,148円・日経−89,040円で、共通改善ではない。',
        '参考0.15%幅はTOPIXで最大利益日を除いても＋855,724円だが、日経は後15が−65,400円、最大利益日除外−97,920円。全31の小さな日経黒字を安定の証明にしない。',
        '固定追従8対反発2の回復版は、J8へ反発を足すとTOPIX−255,280円・日経＋44,184円。最大下落は両商品で増えた。配分だけで各源の最高金額割合を超えない。'
    ]
    REVIEW.save('全36と主の反証及び部品追加価値の敵対的結論.json', dict(
        全合格=True, 主=primary, 前16固定参考=selected, 条件数=36, 場数=31,
        口座=proof['口座'], 注文=proof['注文'], 親=proof['親'], 両商品金額80=proof['両商品金額80'],
        主固定は損益前の論理=True, 結論=conclusion, 配分源の独立一致と数学上限=mix,
        重複対照=dict(条件=['R0', 'R0_C'], 一致口座=duplicate,
            注文親全行時価保有予約一致=True, 別の有効手法として数えない=True),
        全36の最大親及び最大日除外=dependence,
        原本同seq板=sum(p['同seq板'] for p in cases['原本板の同seq照合'].values()),
        固定SHA256=REVIEW.digest(WORK/'事前固定.json'),
        選定SHA256=REVIEW.digest(WORK/'前16参考代表.json'),
        根集計SHA256=REVIEW.digest(WORK/'analysis/比較結果.json'),
        根拠SHA256={str(p.relative_to(ROOT)): REVIEW.digest(p) for p in (
            HERE/'全条件全31の独立親会計と同一新規及び再参加経路分解.json',
            HERE/'主と事前参考の赤字上位3場及び回復中心の具体原板.json',
            HERE/'主全親の極値停止距離と判断までの回復消費.json')},
        計算コードSHA256=REVIEW.digest(Path(__file__)), API取得=0, 実注文=0,
        注意=[
            '最大利益親・日除外は事後診断。新しい売買条件でそこだけ除いた成績ではない。',
            '低い勝ち親率と高い平均勝負比は同時に起こる。金額割合80と勝ち親率を混同しない。',
            '全31は既知探索。前後区分も未見証明ではなく、実験段階を固定するための分割。',
            '全行清算・状態の独立復元は別担当監査の全2,232口座証拠を参照する。']))
    print('全36の敵対的結論・源非干渉・対照重複・最大親依存を保存しました', flush=True)


if __name__ == '__main__':
    main()
