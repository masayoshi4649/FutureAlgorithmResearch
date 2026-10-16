"""追加102条件の前半だけを使い、粗い方向・価格出口・再準備の効果を分解する。"""
from pathlib import Path
import hashlib
import json


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
SYMBOLS = ('TOPIX', 'NK225')


def load(path):
    """
    機能: JSON資料を読む。
    引数: path (Path)。
    返り値: dict の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


# ----------------------------------------
def score(result):
    """
    機能: 元選定と同じ前半評価順を返す。後半は使用しない。
    引数: result (dict)。
    返り値: tuple の順位キー。
    """
    values = [result['periods']['前16'][symbol] for symbol in SYMBOLS]
    sufficient = all(value['trades'] >= 20 and value['active_sessions'] >= 8 for value in values)
    shares = [value['profit_share'] if value['profit_share'] is not None else -1 for value in values]
    return sufficient, min(shares), sum(shares) / 2, min(value['without_best_session'] / max(1, value['fees']) for value in values), result['config']['id']


# ----------------------------------------
def metrics(result):
    """
    機能: 両商品の前半指標を、実際の中値進行と費用に分ける。
    引数: result (dict)。
    返り値: dict の商品別要約。
    """
    output = {}
    for symbol in SYMBOLS:
        value = result['periods']['前16'][symbol]
        output[symbol] = {key: value[key] for key in ('profit', 'loss', 'net', 'trades', 'fees', 'spread_drag',
            'profit_share', 'average_net', 'average_win', 'average_loss', 'payoff', 'active_sessions', 'hold_median', 'hold_max')}
        output[symbol]['中値進行円'] = value['net'] + value['fees'] + value['spread_drag']
    return output


# ----------------------------------------
def compare(before, after):
    """
    機能: 二つの完全再生結果の差を記録する。
    引数: before/after (dict) の保存結果。
    返り値: dict の利益減少・損失減少・活動数と費用の変化。
    """
    a, b = metrics(before), metrics(after)
    changes = {}
    for symbol in SYMBOLS:
        old, new = a[symbol], b[symbol]
        changes[symbol] = dict(
            利益変化円=new['profit'] - old['profit'], 損失削減円=old['loss'] - new['loss'],
            収支改善円=new['net'] - old['net'], 取引数変化=new['trades'] - old['trades'],
            気配差削減円=old['spread_drag'] - new['spread_drag'], 手数料削減円=old['fees'] - new['fees'],
            中値進行改善円=new['中値進行円'] - old['中値進行円'],
            一組平均収支改善円=new['average_net'] - old['average_net'] if new['average_net'] is not None and old['average_net'] is not None else None)
        assert abs(changes[symbol]['利益変化円'] + changes[symbol]['損失削減円'] - changes[symbol]['収支改善円']) < .01
    return dict(前ID=before['config']['id'], 後ID=after['config']['id'], 前=a, 後=b, 差分=changes)


# ----------------------------------------
def main():
    """
    機能: 追加102条件の前半改修と、同入口の対照・再準備24対を保存する。
    引数: なし。
    返り値: None。既往診断、方向状態、選定結果は変更しない。
    """
    paths = sorted((BASE / 'improved/results').glob('*.json'))
    assert len(paths) == 102
    additions = {path.stem: load(path) for path in paths}
    first_paths = sorted((BASE / 'first/results').glob('*.json'))
    first = {path.stem: load(path) for path in first_paths}
    results = dict(first, **additions)
    selected_path = BASE / '前半選定.json'
    selected = load(selected_path)
    broad = [compare(results[old['id']], results[new['id']]) for old, new in zip(selected['初回'], selected['改修'])]
    matched_before = ('D1_K08_X2_M0', 'D2_N128_T15_X2_M1', 'D3_K04_N032_T15_X1_M0')
    matched = [compare(results[old], results[new['id']]) for old, new in zip(matched_before, selected['改修'])]
    gate = [result for result in additions.values() if result['config']['entry_gate']]
    strongest = [max([result for result in gate if result['config']['family'] == family], key=score) for family in ('D1', 'D2', 'D3')]
    gate_comparisons = []
    for candidate in strongest:
        c = candidate['config']
        candidates = [result for result in results.values() if not result['config'].get('entry_gate', 0) and
            result['config']['model'] == c['model'] and result['config']['entry_mode'] == c['entry_mode'] and not result['config']['solo']]
        same_x1 = next(result for result in candidates if result['config']['exit_mode'] == 1)
        old_best = max(candidates, key=score)
        gate_comparisons.append(dict(家族=c['family'], 前半基準で選んだ分離出口=c['id'],
            元も片側反対で降りる対照=compare(same_x1, candidate), 元出口の中で最良との対照=compare(old_best, candidate)))
    pairs = []
    for candidate in gate:
        if candidate['config']['repair'] != 1:
            continue
        before = additions[candidate['config']['id'].replace('_再準備1_', '_再準備0_')]
        pairs.append(compare(before, candidate))
    assert len(pairs) == 24
    summary = {}
    for symbol in SYMBOLS:
        delta = [item['差分'][symbol] for item in pairs]
        summary[symbol] = dict(比較対数=len(pairs),
            取引数変化なし対数=sum(value['取引数変化'] == 0 for value in delta),
            全収支一致対数=sum(abs(value['収支改善円']) < .01 for value in delta),
            収支改善対数=sum(value['収支改善円'] > .01 for value in delta),
            収支悪化対数=sum(value['収支改善円'] < -.01 for value in delta),
            最大改善円=max(value['収支改善円'] for value in delta), 最大悪化円=min(value['収支改善円'] for value in delta))
    out = dict(
        範囲='初回86・追加102の前16だけ。後14、全30の追加損益は使用しない。再選定・条件追加・新規再生なし。',
        結論=[
            '追加102にも両商品が同時に黒字となる条件はなかった。粗い方向で売買回数と損失総額は減ったが、一回の取引が一様に良くなったわけではない。',
            'D1は粗くして両商品39組へ減少したが、一組平均収支はTOPIX約−10,604円→−26,733円、NK225約−4,220円→−8,850円へ悪化。大きな反転待ちは一回の損失も大きくする。',
            '選定された粗いD3は初回代表からの収支改善の約8割が気配差と手数料の減少で説明される。方向をより長く捉えるだけで新たな予測利益が得られたとは言えない。',
            '価格出口を分離した家族内最上位でも、D3の元条件よりTOPIXは利益442,492円を失い、損失削減220,820円を上回って悪化。NK225は利益減20,880円に対して損失226,000円を減らし改善した。両市場に共通の解ではなかった。',
            '再準備24対のうち16対は両商品で取引数・収支が変わらない。変化した8対ではTOPIXは8改善、NK225は7改善・1悪化。価格方向との整合が再参加を既に制約する条件では追加効果が乏しい。',
            'D2とD3の価格出口最上位は、同じN512の圧力とDC16方向の一致を入口にして同じDC16を出口とするため、実質同じ経路である。独立した成功2件とは数えない。',
            '早く降りることには損失削減例があるが、伸びる利益を切る効果と再参加費用もある。今回の改修では「早く降りれば解決する」は確認できなかった。'],
        注意=[
            '初回代表から改修代表への比較には入口方式・出口種類・強度閾値の変更が混ざる。別に同じ通常出口・発注方式・方向強度閾値を揃えた比較を示す。',
            '価格出口分離は入口整合条件も追加するため、出口だけの純粋な因果効果ではない。完全再生の取引経路全体を比較する。',
            '補助flow・極値列は旧13モデルだけのもの。拡張N512、K32等の根拠値として解釈しない。この集計は会計結果のみを使用する。',
            '損失削減は負け取引金額合計の減少。消えた負けだけの抽出ではなく、失った利益と取引数変化も同時に示す。'],
        代表改修=broad, 通常出口と発注方式と強度閾値を揃えた比較=matched,
        価格出口分離の家族別最上位=gate_comparisons, 再準備の全24対=pairs, 再準備要約=summary,
        改修102で両商品黒字条件数=sum(all(result['periods']['前16'][symbol]['net'] > 0 for symbol in SYMBOLS) for result in additions.values()),
        出典SHA256={str(path.relative_to(BASE)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths + first_paths + [selected_path]})
    target = HERE / '追加102の前半改修効果.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(代表比較=[dict(前ID=v['前ID'], 後ID=v['後ID'], 差分=v['差分'], 後=v['後']) for v in broad],
                         価格出口代表=[dict(家族=v['家族'], ID=v['前半基準で選んだ分離出口'], 差分=v['元出口の中で最良との対照']['差分']) for v in gate_comparisons],
                         再準備=summary, 両黒字数=out['改修102で両商品黒字条件数']), ensure_ascii=False))


if __name__ == '__main__':
    main()
