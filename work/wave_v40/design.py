"""固定価格帯の二試行を比較する条件を、新しい収支を見る前に定義する。"""

from __future__ import annotations


def catalog() -> list[dict]:
    """機能: 板履歴の除去・反転・価格独立対照と一軸感度を列挙する。

    引数: なし。返り値: 主条件と反証条件 (list[dict])。出口と枚数は共通。
    """
    base = dict(mode='weaken', board_anchor=True, anchor_seconds=30., trial_seconds=30.,
        departure=.5, break_ticks=2., lifetime=1800., momentum=.10,
        peer=False, invert=False, delay=0., observed=False, seed=None, role='comparison')
    definitions = [
        ('B00','板回復と押し返しの弱化',dict(role='primary')),
        ('B01','板比較可能な機会で価格弱化だけ',dict(mode='price_matched')),
        ('B02','板履歴不明も含め価格弱化だけ',dict(mode='price')),
        ('B03','二試行後の突破だけ',dict(mode='all')),
        ('B04','板回復の弱化だけ',dict(mode='quantity')),
        ('B05','最後の回復比率だけ',dict(mode='last')),
        ('B06','二回の平均回復比率だけ',dict(mode='mean')),
        ('B07','板回復の強化を採用',dict(mode='strengthen')),
        ('B08','主案の売買方向を反転',dict(invert=True)),
        ('B09','二試行を待たない価格突破',dict(mode='first_break')),
        ('B10','数量を使わない帯の二試行後突破',dict(mode='all',board_anchor=False)),
        ('B11','数量を使わない帯の最初の突破',dict(mode='first_break',board_anchor=False)),
        ('B12','相手市場の過去5分方向も確認',dict(peer=True)),
    ]
    result = []
    for identifier,name,changes in definitions:
        item=dict(base);item.update(id=identifier,name=name,**changes);result.append(item)
    # ----------------------------------------
    # 共通の比較5方式へ、帯生成・試行確定・別試行距離・突破距離を同じく揺らす。
    sensitivities = (
        ('A080','帯生成24秒',dict(anchor_seconds=24.)),('A120','帯生成36秒',dict(anchor_seconds=36.)),
        ('T080','試行確定24秒',dict(trial_seconds=24.)),('T120','試行確定36秒',dict(trial_seconds=36.)),
        ('D080','離脱0.4ATR',dict(departure=.4)),('D120','離脱0.6ATR',dict(departure=.6)),
        ('K1','突破1呼値',dict(break_ticks=1.)),('K3','突破3呼値',dict(break_ticks=3.)),
    )
    originals = {row['id']:row for row in result}
    for identifier in ('B00','B01','B05','B06','B07'):
        for suffix,name,changes in sensitivities:
            item=dict(originals[identifier]);item.update(id=identifier+'_'+suffix,
                name=item['name']+'・'+name,role='sensitivity',parent=identifier,**changes)
            result.append(item)
    for identifier in ('B00','B01','B02','B05','B06','B07','B08','B11','B12'):
        for delay in (1.,5.,15.):
            item=dict(originals[identifier]);item.update(id=identifier+f'_D{int(delay):02d}',
                name=item['name']+f'・伝達{delay:g}秒',role='execution',parent=identifier,delay=delay)
            result.append(item)
        item=dict(originals[identifier]);item.update(id=identifier+'_OBS',
            name=item['name']+'・観測価格返済',role='execution',parent=identifier,observed=True)
        result.append(item)
    assert len(result)==len({r['id'] for r in result})==89
    return result


def supplementary() -> list[dict]:
    """機能: 主・価格除去対照・相手確認の候補を保つ方向乱数192条件を返す。

    引数: なし。返り値: 固定seed0〜63の3群 (list[dict])。
    """
    specs={r['id']:r for r in catalog()};result=[]
    for identifier in ('B00','B01','B12'):
        for seed in range(64):
            item=dict(specs[identifier]);item.update(id=f'{identifier}_R{seed:02d}',
                name=item['name']+f'・方向乱数{seed}',seed=seed,role='random',parent=identifier)
            result.append(item)
    return result


def rules() -> dict:
    """機能: 売買・公平な比較・採否の意味を起動前に固定する。

    引数: なし。返り値: 仕様 (dict)。既知データを未知へ読み替えない。
    """
    return dict(主='B00',主条件数=89,方向乱数条件数=192,全条件数=281,
        既知セッション数=13,学習除外なし=True,各市場1枚=True,保存ライブ使用=False,現在API取得数=0,
        入口='公開後の固定価格帯の二試行を確定した次以降の突破、さらに次原本行で新規。',
        比率='各試行の全可視減少に対する、最初の減少後の可視増加の累積比。真の補充又は約定量ではない。',
        主判定='u2<u1 かつ b2<b1。不明と等号は不採用。',
        除去対照='B01はu1/u2可用性と価格弱化を共有して数量の大小だけ外す。B02は数量不明も価格有効なら保持。',
        最終平均逆判定='B05:u2<1、B06:(u1+u2)/2<1、B07:u2>u1。いずれもu1/u2可用性とb2<b1を共有。',
        先着対照='B09/B11は共通列挙の試行前突破も使う。帯の準備・終了はその親母集団と同じ。',
        価格独立='B10/B11は数量条件なしの帯生成で別母集団。数量品質で価格経路を落とさない。',
        相手='主候補を先に固定。相手公開に60秒加えたasof、追加遅延後の古さ<=120秒、連続価格窓5分の進行が自方向0.25公開ATR以上。',
        乱数='SHA256(v40|seed|session|symbol|rawseq)の符号を候補方向へ掛ける。実約定数と時刻は返済・休止により変わり得る。',
        出口='v39の1枚注文器を無変更で使用。判断ATR/2呼値からr、損切り1r/利確2r、30分後と場末に返済予約、次行と伝達時間待ち、返済後5分休止。',
        基礎='両銘柄で20決済/6活動場/両方向各3以上、黒字、PFと平均勝負比1.2以上、最大勝ち取引・最大勝ち場を各々除いて非赤字。非有限や未定義は不合格。',
        情報追加='両銘柄で主の合計RがB01/B05/B06/B07/B08と同候補乱数中央値を全て上回る。円収支と活動を併記。正式有意確率とはしない。',
        価格全体比較='B10/B11とのR・金額・DD・活動を別表示。対応比較の情報成分と混同しない。',
        執行='主の1/5/15秒と観測返済の4条件が両銘柄で基礎基準を満たす。',
        近傍='8近傍を全表示。両銘柄で各6/8以上が活動数基準を満たし黒字PF>=1.2、全8収支中央値>=主の50%、最悪>=主の-25%。主自体が基礎不合格なら合格しない。',
        採用='基礎・情報追加・執行・近傍を全て通過した既知上の候補だけ。未来の保証でも全体目標完了でもない。')
