"""金融結果を開かず、保存列契約と完成後の限定損失診断計画を作る。"""

import ast
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]


def literal(path: Path, name: str) -> object:
    """
    機能: 経済源をimportせず、単純な列名定数だけをSOURCEから取得する。
    引数: path(Path)はPython源、name(str)は定数名。
    返り値: objectはASTで表されたリテラル。数値エンジンや読取関数を実行しない。
    """
    tree = ast.parse(path.read_text(encoding='utf8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def main() -> None:
    """
    機能: 四源だけを読み、結果解除前の選択規則・最大六cache・診断分母を固定する。
    引数: なし。
    返り値: None。市場・NPZ・金融結果・試行台帳への読取又は書込は0。
    """
    paths = [BASE/name for name in ('engine120.py', 'catalog120.py', 'run120.py', 'plan120.py')]
    source = {path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    modes = literal(BASE/'catalog120.py', 'MODES')
    ids = [f'{mode[0]}_S{width}_T{trail}' for mode in modes for width in (1, 2, 3) for trail in (1, 3)]
    assert len(ids) == len(set(ids)) == 48
    columns = {name:list(literal(BASE/'engine120.py', name)) for name in ('ORDER_COLUMNS', 'LOT_COLUMNS', 'CURVE_COLUMNS', 'SUMMARY_COLUMNS')}
    assert [len(columns[name]) for name in ('ORDER_COLUMNS', 'LOT_COLUMNS', 'CURVE_COLUMNS', 'SUMMARY_COLUMNS')] == [18, 19, 8, 20]
    baseline = 'HEDGE_S2_T1'
    comparisons = [tag+'_S2_T1' for tag in ('NET','FLIP','RECYCLE','HARD','ONCE','ALLSIDE')]
    output = HERE/'完成後の全四十八小会計と基準赤字六場を読む計画.json'
    assert not output.exists()
    value = {
        '全合格':True,
        '段階':'SOURCEと計画だけ。実結果未読、根の完成通知・指定SHA解除待ち。',
        '準備時source_SHA256':source,
        '正式源の扱い':'完成結果のsource_SHA256と保存列契約を受領時に再照合する。準備時署名だけで正式登録又は金融完了を主張しない。',
        '結果':{'path':'work/stability120_20261017/measurement/段階トレーリングと利益玉部分返済の全四十場.json',
            'SHA指定':'根が完成後に渡す64桁SHA256だけを採用。いま未定。',
            '原本読取':1,'解析前同bytes保全':True},
        '全小会計':{'期待条件ID':ids,'各条件の分母':'TOPIX40場とNK22540場、合計3840行。条件間の重複を独立標本にしない。',
            '再集計':['費用後net','総利益/総損失/全注文料','黒字/赤字/無取引/取引あり同値を分離','全40中央値',
                '黒字上位3場を除くnet','最悪場','黒字場平均と最大赤字の比','実最大買/売枚数','保有中最大DD','未清算'],
            '候補の表示':'両商品で合計正の条件を先に列挙し、中央値/上位3場除外/未清算/活動の項目別判定を並べる。全部を同時に満たす条件の有無も別記する。特定の最低活動率や旧65%/赤字20%/平均10万円を新しい必須条件へ加えない。',
            '両商品':'共通IDの両商品成績を意味する。二商品の円損益合算や日ごとの最適条件選択で黒字を作らない。'},
        '詳細場の選び方':{'基準':baseline,'規則':'基準の各商品でnet<0の場をnet昇順、同額はsession文字列昇順で最大3場。赤字が3未満なら存在する分だけで埋めない。',
            '比較':comparisons,'FIXEDの扱い':'全48小会計へ含めるが、今回の詳細六場比較は根指定の六運用へ限定する。',
            '詳細NPZ上限':6,'一意キー':['symbol','session'],'全7政策を同一cache一読のメモリ上で射影':True,
            '読取前の追加固定':'完成結果から選択した最大六項目のpath/SHA256/政策indexを別読取計画へ保存し、その後に各cacheを一読する。',
            'cache境界':'measurementの保存NPZだけ。原市場・元prepared・旧金融は読まない。bytesを先に同bytes保全し、BytesIOからparseする。'},
        '保存列契約':{'エンジン列':columns,'NPZ':'orders/lots/curvesの第0列はpolicyidx。実列はその後。result.specsのID順からindexを決め、固定数値indexを仮定しない。',
            'quotes':['row','time','last','bid','ask'],'curveの限界':'保存curveは約1分間隔と終端。全原行の最大DDはsummaryで計算済みだが、その正確な発生原行はcurveだけからは断定しない。'},
        '詳細診断':['基準の勝ち玉net累積、損失玉net累積、返済済み実現net、未返済全玉の反対BBO清算netを分離する。',
            'close_timeへ初到達した正常原行の既発注fill処理後を場末判断snapshotとし、残玉の含み益/含み損/予定返済料/買売枚数を記述する。過去quoteで架空清算しない。',
            '理由1の利確net、理由9の場末利益/損失、理由2/3/4/5/7の整理損益を全玉へ合算する。利確判断後に次quoteで赤字約定した玉も分ける。',
            '基準各場の最大損失UID一つと最大利益UID一つ（なければ未存在）を実原行・価格時計・売買・段・建値・返済値・料・MFE/MAE・前後のBBOで示す。最大含み益を別出口の救済利益にしない。',
            '各対照のnet差を共通入口玉の退出差＋新規に生じた玉net−消えた玉netへ算術分解する。政策間のUID連番は同一玉の証拠に使わない。',
            '入口対応キーはside/rung/entry_decision_row/entry_row/entry_price。全て一致した場合だけ共通入口とし、後の返済と枠再利用が変わる事実を残す。',
            'NETやFLIPは純粋な費用だけの対照ではない。実受理/返済/後参加の集合も変わるので、残損失が減ったか別の損失へ移ったかを全場netで判定する。'],
        '会計式':{'個別完結玉':'side*(exit-entry)*倍率−新規料−返済料。実装は一枚ごと別注文なのでTOP41円/NK11円を各注文へfloorする。',
            'snapshot清算資産':'完結玉net累積＋全未返済玉のside*(現在反対BBO−entry)*倍率−当該玉の新規料−予定返済料。cashと実現netを取り違えない。',
            '残在庫':'買い/売りの総枚数と純枚数を両方表示。相殺している間も既存損失と両側費用は消えない。'},
        '実施していないこと':['市場入力読取','保存NPZ読取','金融結果読取','試行台帳本文読取','金融実行','共有経済源変更'],
    }
    output.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'全合格':True,'状態':'結果SHA解除待ち','計画':output.relative_to(ROOT).as_posix(),
        'SHA256':hashlib.sha256(output.read_bytes()).hexdigest(),'条件':len(ids),'詳細cache上限':6},ensure_ascii=False))


if __name__ == '__main__':
    main()
