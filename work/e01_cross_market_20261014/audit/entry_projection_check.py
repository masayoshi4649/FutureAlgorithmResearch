"""十五活動親と一赤字親の小射影を、台帳再読せず価格差と公開票から検算する。"""

from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import math


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'work/e01_cross_market_20261014/entry_diagnosis'
EXPECTED = 'bc44cdd7dbf0f69f737a559c9af0bd912fb3dca7d4722e8b5a884a3d028ded60'
COUNTS = Counter()


def read(path: Path) -> tuple[dict, str]:
    """
    機能: 目的を指定した小射影・読取計画・自分の会計監査だけを一読する。
    引数: path(Path) は事後診断小 JSON 又は自所有の保存監査。
    返り値: tuple[dict,str] は保存内容と同 bytes の SHA256。
    """
    assert path.parent in (SOURCE, HERE)
    saved = path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')), hashlib.sha256(saved).hexdigest()


def same(left: float, right: float) -> None:
    """
    機能: 有限の小算術値を厳密な金額許容内で比較する。
    引数: left/right(float) は保存値と独立に得た数値。
    返り値: None。不一致を例外とし比較数だけ増やす。
    """
    assert math.isfinite(left) and math.isfinite(right)
    assert math.isclose(left,right,abs_tol=1e-5,rel_tol=1e-12), (left,right)
    COUNTS['小算術照合'] += 1


def fee(q: int, symbol: str) -> int:
    """
    機能: 整数の分数単価で片道料の floor を独立に求める。
    引数: q(int) は注文数量、symbol(str) は商品。
    返り値: int は実注文料金。未丸め単価をそのまま徴収しない。
    """
    return q*209//5 if symbol == 'TOPIX' else q*11


def main() -> None:
    """
    機能: 保存した実親の全返済価格・数量・料金・票釣合い・選定分母を独立検算する。
    引数: なし。新入力・新金融・台帳本文・API を読み取らない。
    返り値: None。自所有の計画と合格証跡を新規保存する。
    """
    scope = HERE / '公開票と事後逆行小射影の独立読取計画.json'
    target = HERE / '実公開票と全返済小価格からの独立算術監査.json'
    assert not scope.exists() and not target.exists()
    paths = [SOURCE/'実公開票と事後逆行の追加射影.json', SOURCE/'読取計画.json',
        HERE/'十六対照1056小会計と128期間及び受理円尺度の独立監査_v2.json']
    scope.write_text(json.dumps(dict(小JSON各一読=[p.relative_to(ROOT).as_posix() for p in paths],
        目的='全16診断台帳の小射影の数値だけを再集計する。実台帳を再読しない。',
        台帳=0,packet=0,金融=0,原板=0,NPZ=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    reads = [read(p) for p in paths]
    diagnosis, plan, finance = [v for v,h in reads]
    assert reads[0][1] == EXPECTED
    assert all(v['全合格'] for v,h in reads)
    assert diagnosis['保存結果SHA256'] == plan['result_SHA256'] == finance['正式結果SHA256']
    assert diagnosis['計画SHA256'] == reads[1][1]
    assert diagnosis['開始終端source一致']
    assert len(plan['targets']) == diagnosis['台帳数'] == 16
    assert len(diagnosis['台帳一読']) == 16 and all(n==1 for n in diagnosis['台帳一読'].values())
    for key in ('金融再生','入力読取','原板','NPZ','API'):
        assert diagnosis[key] == 0
    for path, sha in diagnosis['source_SHA256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == sha
    groups = {}
    parent_keys = set()
    target_keys = {(t['case_id'],t['session'],t['symbol']):t for t in plan['targets']}
    for p in diagnosis['parent_projections']:
        key = (p['case_id'],p['session'],p['symbol'])
        assert key in target_keys
        uid = key + (p['paper_parent'],)
        assert uid not in parent_keys
        parent_keys.add(uid)
        pub = p['publication']
        fill = p['actual_fill']
        close = p['close']
        risk = p['risk']
        first = p['session_first_accept']
        symbol = p['symbol']
        value = 1000 if symbol == 'TOPIX' else 10
        side = p['side']
        q = fill['quantity']
        assert pub['known'] and pub['unknown_reason'] == 0 and side in (1,-1)
        same(pub['up_votes'] + pub['down_votes'], pub['direction_votes'])
        assert pub['direction_votes'] >= 2
        same(side*(pub['up_votes']-pub['down_votes'])/pub['direction_votes'], pub['balance'])
        assert pub['balance'] >= pub['threshold']
        same(pub['threshold'], .75 if p['case_id']=='E01_CROSS_B03' else .5)
        assert pub['normal_row'] < fill['normal_row'] <= close['normal_row']
        assert first['normal_row'] <= pub['normal_row']
        assert first['raw_seq'] <= pub['raw_seq'] and first['price_time_s'] <= pub['price_time_s']
        assert fill['quote_side'] == ('ask' if side > 0 else 'bid')
        assert 0 < q <= (5 if symbol == 'TOPIX' else 10)
        same(q, pub['selected_quantity'])
        assert pub['published_ATR'] > 0 and pub['published_spread'] > 0
        assert pub['価格代理時計JST'] == datetime.fromtimestamp(pub['price_time_s'],timezone(timedelta(hours=9))).isoformat()
        # 全返済小価格の価格差と注文別 floor 料を独立計算する。
        same(sum(o['quantity'] for o in close['orders']), q)
        gross = math.fsum(side*(o['price']-fill['price'])*o['quantity']*value for o in close['orders'])
        paid = fee(q,symbol) + sum(fee(o['quantity'],symbol) for o in close['orders'])
        same(gross, p['gross_yen'])
        same(paid, p['actual_fees_yen'])
        same(gross-paid, p['actual_net_yen'])
        for order in close['orders']:
            assert fill['normal_row'] <= order['normal_row'] <= close['normal_row']
            assert order['decision_row'] < order['normal_row']
            assert 0 < order['quantity'] <= q
        assert max(o['normal_row'] for o in close['orders']) == close['normal_row']
        # 保存極値の小算術だけ。全normal曲線の最小点を再走査したとは呼ばない。
        same(max(0., -risk['worst_fee_liquidation_yen']),risk['fee_liquidation_MAE_yen'])
        assert risk['gross_mark_MAE_yen'] >= 0
        assert risk['maximum_fee_liquidation_yen'] >= p['actual_net_yen']
        assert risk['worst_fee_liquidation_yen'] <= p['actual_net_yen']
        assert fill['normal_row'] <= risk['worst_fee_liquidation_row'] <= close['normal_row']
        assert fill['normal_row'] <= risk['gross_mark_MAE_row'] <= close['normal_row']
        same(risk['observed_normal_rows'],close['normal_row']-fill['normal_row']+1)
        assert 0 <= risk['negative_fee_liquidation_rows'] <= risk['observed_normal_rows']
        assert 0 <= risk['held_rows'] <= risk['observed_normal_rows']
        # 未保存列を補完せず未知として保持する。
        for missing in ('raw_seq','price_time_s','bid','ask'):
            assert fill[missing] is None
        assert pub['bid'] is None and pub['ask'] is None
        groups.setdefault(p['case_id']+'|'+symbol,[]).append(p)
        COUNTS['親の全返済価格算術'] += 1
    independent = {}
    for name, parents in groups.items():
        calculated = dict(実親数=len(parents),黒字親=sum(p['actual_net_yen']>0 for p in parents),
            赤字親=sum(p['actual_net_yen']<0 for p in parents),
            direction_vote_counts=dict(Counter(str(p['publication']['direction_votes']) for p in parents)),
            balances=dict(Counter(str(p['publication']['balance']) for p in parents)),
            初受理qと実fillq差数=sum(p['session_first_accept']['quantity']!=p['actual_fill']['quantity'] for p in parents),
            総net=math.fsum(p['actual_net_yen'] for p in parents))
        for field,val in calculated.items():
            if isinstance(val,dict):
                assert diagnosis['summary'][name][field] == val
            else:
                same(diagnosis['summary'][name][field],val)
        owncase,symbol = name.split('|')
        for key in target_keys:
            if key[0] == owncase and key[2] == symbol:
                own = [p for p in parents if p['session']==key[1]]
                small = target_keys[key]['small_row']
                same(math.fsum(p['actual_net_yen'] for p in own), small['収支'])
                same(math.fsum(max(0,p['actual_net_yen']) for p in own), small['利益'])
                same(math.fsum(max(0,-p['actual_net_yen']) for p in own), small['損失'])
                same(sum(p['actual_fees_yen'] for p in own),small['費用'])
                same(sum(p['actual_fill']['quantity'] for p in own),small['新規枚数'])
                same(len(own),small['親数'])
        if owncase == 'E01_CROSS_B03':
            assert calculated['黒字親'] == calculated['実親数'] and calculated['赤字親'] == 0
            same(calculated['総net'],finance['商品と期間'][owncase][symbol]['期間']['全33']['金額']['収支'])
        calculated.update(費用後最大逆行円=max(p['risk']['fee_liquidation_MAE_yen'] for p in parents),
            粗時価最大逆行円=max(p['risk']['gross_mark_MAE_yen'] for p in parents),
            ナイト親数=sum(p['session'].endswith('_Night') for p in parents),
            デイ親数=sum(p['session'].endswith('_Day') for p in parents),
            方向=dict(Counter('long' if p['side']>0 else 'short' for p in parents)))
        independent[name] = calculated
    b03 = [p for p in diagnosis['parent_projections'] if p['case_id']=='E01_CROSS_B03']
    assert len(b03) == 15 and sum(p['publication']['direction_votes']==2 for p in b03) == 7
    assert sum(p['publication']['balance']==1 for p in b03) == 13
    assert sum(p['session'].endswith('_Night') for p in b03) == 13
    assert independent['E01_CROSS_B03|TOPIX']['費用後最大逆行円'] == 3166
    assert independent['E01_CROSS_B03|NK225']['費用後最大逆行円'] == 1566
    false_parent = [p for p in diagnosis['parent_projections'] if p['case_id']=='E01_CROSS_B01' and p['actual_net_yen']<0]
    assert len(false_parent) == 1
    assert false_parent[0]['publication']['direction_votes']==20
    same(false_parent[0]['publication']['balance'],.7)
    output = dict(全合格=True,小射影SHA256=reads[0][1],
        小JSON一読SHA256={p.relative_to(ROOT).as_posix():h for p,(v,h) in zip(paths,reads)},
        検査=dict(COUNTS),商品別小射影再集計=independent,
        B03全15親=dict(票2の親=7,balance1の親=13,ナイト親=13,デイ親=2),
        B01反証=dict(case_id=false_parent[0]['case_id'],session=false_parent[0]['session'],
            symbol=false_parent[0]['symbol'],実収支=false_parent[0]['actual_net_yen'],
            票数=20,balance=.7),
        留保=['公開票はLast対直前BBOと公表出来高正増からの1更新1票の攻撃側代理。真の成行量や独立の攻撃注文数ではない。',
            '15親の13親が夜間。無敗を全33場又は広範なデイ/ナイト状態での95%方向精度と呼ばない。',
            '費用後最大逆行は全勝親でもTOP3166円/NK1566円。小利確と大きな途中損失を両立しうる。未来の平均損失をこの全勝から推定しない。',
            'B01の敗け親は20票でbalance .7。多数票だけでは敗けないという仮説への反証。 .75境界の未知性能を証明した事例ではない。',
            '事後MAEとピークは保存小射影の数値/範囲と reader の局所分離を確認した。全曲線の最小点を独立再走査していない。',
            '原seq/価格時計/両BBOの無い実fill列は未保存のまま。物理fill保証や板の補充方向の証明を追加しない。'],
        独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        台帳=0,packet=0,原板=0,NPZ=0,金融再生=0,API=0,共有又は経済源変更=0)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,検査=dict(COUNTS),B03=output['B03全15親'],
        SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__ == '__main__':
    main()
