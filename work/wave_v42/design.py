"""原本全行の数量観測を、旧帯を固定した260条件で比較する。"""

from __future__ import annotations


SENSITIVITIES = (
    ('A080', '帯生成24秒', dict(anchor_seconds=24.)),
    ('A120', '帯生成36秒', dict(anchor_seconds=36.)),
    ('T080', '試行確定24秒', dict(trial_seconds=24.)),
    ('T120', '試行確定36秒', dict(trial_seconds=36.)),
    ('D080', '離脱0.4ATR', dict(departure=.4)),
    ('D120', '離脱0.6ATR', dict(departure=.6)),
    ('K1', '突破1呼値', dict(break_ticks=1.)),
    ('K3', '突破3呼値', dict(break_ticks=3.)),
)
EXECUTION_SUFFIXES = ('D01', 'D05', 'D15', 'OBS')
COMPONENTS = {'F01': ('F03', 'F06', 'F07', 'F08', 'F09'),
              'F02': ('F04', 'F12', 'F13', 'F14', 'F15')}
LEGACY_EQUIVALENTS = {'F00': 'B00', 'F05': 'B02', 'F18': 'B01', 'F19': 'B03'}


def catalog() -> list[dict]:
    """機能: 20基本方式と、指定4方式の32近傍・16執行条件を返す。

    引数: なし。返り値: 新しい収支を見る前の68条件(list[dict])。
    """
    base = dict(mode='weaken', feature_source='strict', board_anchor=True,
        anchor_seconds=30., trial_seconds=30., departure=.5, break_ticks=2.,
        lifetime=1800., momentum=.10, peer=False, invert=False, delay=0.,
        observed=False, seed=None, role='comparison')
    definitions = (
        ('F00', '旧公開端点・数量と押し戻りの弱化', dict(feature_source='old', legacy_id='B00')),
        ('F01', '原本全行・旧品質維持・数量と押し戻りの弱化', dict(role='primary')),
        ('F02', '原本全行・P局所品質・数量と押し戻りの弱化', dict(feature_source='local', role='secondary')),
        ('F03', '原本全行の旧品質比較可能機会・押し戻り弱化だけ', dict(mode='price_matched')),
        ('F04', '原本全行の局所品質比較可能機会・押し戻り弱化だけ', dict(feature_source='local', mode='price_matched')),
        ('F05', '数量不明も含む押し戻り弱化だけ', dict(feature_source='old', mode='price', legacy_id='B02')),
        ('F06', '旧品質維持・最後の数量比率だけ', dict(mode='last')),
        ('F07', '旧品質維持・二回の平均数量比率だけ', dict(mode='mean')),
        ('F08', '旧品質維持・数量比率の強化を採用', dict(mode='strengthen')),
        ('F09', '主案の売買方向を反転', dict(invert=True)),
        ('F10', '主案に相手市場の過去価格確認', dict(peer=True)),
        ('F11', '旧品質維持・数量比率の弱化だけ', dict(mode='quantity')),
        ('F12', 'P局所品質・最後の数量比率だけ', dict(feature_source='local', mode='last')),
        ('F13', 'P局所品質・二回の平均数量比率だけ', dict(feature_source='local', mode='mean')),
        ('F14', 'P局所品質・数量比率の強化を採用', dict(feature_source='local', mode='strengthen')),
        ('F15', 'P局所品質主案の売買方向を反転', dict(feature_source='local', invert=True)),
        ('F16', 'P局所品質主案に相手市場の過去価格確認', dict(feature_source='local', peer=True)),
        ('F17', 'P局所品質・数量比率の弱化だけ', dict(feature_source='local', mode='quantity')),
        ('F18', '旧数量比較可能機会・押し戻り弱化だけ', dict(feature_source='old', mode='price_matched', legacy_id='B01')),
        ('F19', '二試行後の突破すべて', dict(feature_source='old', mode='all', legacy_id='B03')),
    )
    result = []
    for identifier, name, changes in definitions:
        item = dict(base)
        item.update(id=identifier, name=name, **changes)
        result.append(item)
    originals = {row['id']: row for row in result}
    # ----------------------------------------
    # 原本観測と数量情報除去の両品質へ同じ一軸の反証を適用する。
    for identifier in ('F01', 'F02', 'F03', 'F04'):
        for suffix, name, changes in SENSITIVITIES:
            item = dict(originals[identifier])
            item.update(id=identifier+'_'+suffix, name=item['name']+'・'+name,
                role='sensitivity', parent=identifier, **changes)
            result.append(item)
    for identifier in ('F01', 'F02', 'F03', 'F04'):
        for delay in (1., 5., 15.):
            item = dict(originals[identifier])
            item.update(id=identifier+f'_D{int(delay):02d}', name=item['name']+f'・伝達{delay:g}秒',
                role='execution', parent=identifier, delay=delay)
            result.append(item)
        item = dict(originals[identifier])
        item.update(id=identifier+'_OBS', name=item['name']+'・観測価格返済',
            role='execution', parent=identifier, observed=True)
        result.append(item)
    assert len(result) == len({row['id'] for row in result}) == 68
    return result


def supplementary() -> list[dict]:
    """機能: F01・F02・F03の同候補時刻へ64固定符号を掛ける192対照を返す。

    引数: なし。返り値: 方向乱数条件(list[dict])。実約定数を固定する対照ではない。
    """
    originals = {row['id']: row for row in catalog()}
    result = []
    for identifier in ('F01', 'F02', 'F03'):
        for seed in range(64):
            item = dict(originals[identifier])
            item.update(id=f'{identifier}_R{seed:02d}', name=item['name']+f'・方向乱数{seed}',
                seed=seed, role='random', parent=identifier)
            result.append(item)
    assert len(result) == len({row['id'] for row in result}) == 192
    return result


def rules() -> dict:
    """機能: v40の数値基準と、新旧観測を分離する比較範囲を明記する。

    引数: なし。返り値: 起動前の判定・売買・観測契約(dict)。
    """
    return dict(主='F01', 副='F02', 主条件数=68, 基本方式数=20, 近傍条件数=32,
        執行条件数=16, 方向乱数条件数=192, 全条件数=260, 既知セッション数=13,
        学習除外なし=True, 各市場1枚=True, 保存ライブ使用=False, 現在API取得数=0,
        元数値基準='wave_v40/design.py と assessment.py の固定値を継承',
        数値基準=dict(決済数=20, 活動場数=6, 買い決済数=3, 売り決済数=3,
            PF=1.2, 平均勝負比=1.2, 最大勝ち取引除外収支下限=0., 最大勝ち場除外収支下限=0.,
            近傍活動黒字PF合格数=6, 近傍全数=8, 近傍収支中央値比下限=.5, 近傍最悪収支比下限=-.25),
        母集団='旧v40の板アンカー・試行・終端時刻を固定。8近傍も旧cacheの同じ母集団を使う。',
        観測='原本全行の同側Pの差分。最初の減少以降の増加合計/減少合計。真の補充や約定量ではない。',
        不明='可視外・非掲載・不正数量・D=0・未完試行はNone。不明を0や弱化へ変換しない。',
        品質='F01は原本P可用性に旧公開数量品質を追加、F02は原本P局所品質だけ。副案で主案を救済しない。',
        比較可能='数量の順序を除くF03/F04・最後/平均/逆判定も同じu1/u2可用性を要求する。',
        主判定='u2<u1 かつ b2<b1。等号は不採用。',
        入口='二試行が公開完了した後の別公開で生じた初回突破。判断の次原本行と伝達時間を待つ。',
        相手='旧B12と同じ価格品質。相手公開+60秒のasof、追加待ち後の古さ<=120秒、連続5分の進行が自方向0.25ATR以上。',
        乱数='SHA256(v42|seed|session|symbol|候補rawseq)の符号を候補方向にだけ掛ける。候補時刻は保持し、約定や損益を参照しない。',
        出口='v39の1枚注文器を無変更で使用。判断ATR/2呼値からr、1r損切り・2r利確、30分/場末返済、5分休止。',
        観測返済='価格条件成立時の現観測価格で返済。新規と時間返済は元から次行の現価格。',
        基礎='両銘柄で20決済/6活動場/買売各3以上、黒字、PFと平均勝負比1.2以上、最大勝ち取引と場を各々除いて非赤字。不定義・非有限は不合格。',
        情報追加={key: list(value) for key, value in COMPONENTS.items()},
        情報追加判定='両銘柄で主又は副の合計Rが指定5対照と同候補64乱数中央値を全て厳密に上回る。正式有意確率ではない。',
        執行='主・副それぞれの1/5/15秒と観測返済の4条件が、両銘柄で基礎基準を全て満たす。',
        近傍='主・副それぞれの8近傍。各銘柄で6/8以上が活動基準・黒字・PF>=1.2、全8収支中央値>=元の50%、最悪>=元の-25%。元の基礎不合格を救済しない。',
        旧完全再現=LEGACY_EQUIVALENTS,
        採用='基礎・情報追加・執行・近傍を分離判定。既知13の再確認を未知検証や利益保証と呼ばない。')
