"""未取得の現ナイトを、旧入力数学と途中終端のまま答え合わせする計画。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 再利用する小sourceだけを事前指紋化する。
    引数: path(Path)は既存source又は小人工証跡。
    返り値: strはSHA256。原本/API/巨大cacheは読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> None:
    """
    機能: 同パイプライン接続と未完了場の会計境界を、API取得前に保存する。
    引数: なし。
    返り値: None。まだ新原行の抽出・正式活動・金融は開始しない。
    """
    source_names=[
        'work/wave_v104/holdout_input/core.py','work/wave_v104/holdout_input/artificial.py',
        'work/wave_v103/input/core.py','work/wave_v103/input_v2/correction.py',
        'work/wave_v74/inputs/prepare_refs.py','work/wave_v77/inputs/core.py',
        'work/wave_v91/inputs/prepare.py','work/wave_v94/inputs_r1/last_price.py',
        'work/wave_v102/strategy.py','work/wave_v103/activity/core.py',
        'work/wave_v103/activity/states_snapshot.py','work/wave_v103/catalog.py',
        'work/wave_v104/peer/api.py','work/wave_v104/peer/core.py','work/wave_v104/peer/prices.py',
        'work/wave_v106/range_price/features.py','work/wave_v106/range_price/selection.py',
        'work/wave_v106/range_price/prepare.py','work/wave_v106/range_price/catalog.py',
        'work/wave_v106/range_price/interface.py','work/wave_v106/range_price/engine/core.py',
        'work/wave_v106/time_guard/time_windows.py']
    value=dict(全合格=True,段階='未取得APIへ適応する読取設計のみ',session='2026-10-13_Night',
        事前固定対照=['AUTO_ER40_M2_LIMIT','R_ONLY_ER40_M2_LIMIT'],
        商品枚数=dict(TOPIX='TOPIXmini5、上限10',NK225='NK225micro10、上限20'),
        API='根がbook二銘柄を各1回取得しwork/wave_v106/current_session/apiに保存。book/candle領域へ書かない。子はAPI0。',
        入力='保存取得bytesを各1read/hash。JSONLなら元行順seq、JSON配列なら明示された配列順を保存。辞書wrapper等未知形式は推測せずFalse。有限clockをソートして保存順を改変しない。',
        pipeline=[
            dict(stage='原行3系列',source='work/wave_v104/holdout_input/core.py',function='extract_rows(rows,session,symbol)',
                 details='session引数一般化済み。一回fanoutから44原行v2・旧77/91normal・独立LP。原本パス固定extract_jsonlは使わず新work入力wrapperのみ。'),
            dict(stage='旧入力準備',source='work/wave_v104/holdout_input/core.py',function='build_material(extracted)',
                 details='4価格lane/独立LP/格子/旧候補→不変102.prepareの完全同入力。開場参照known_from_i=0を要求し、後からOpeningPriceを遡及補完しない。前場参照不要。'),
            dict(stage='板C候補',source='work/wave_v103/activity/core.py',function='build_session(session,raw,items,values)',
                 details='不変103state数学を新所有同一bytes snapshotへ接続、同canonical alias/JITをcurrent_session内へ限定。旧19routeと新10419entryを混同しない。'),
            dict(stage='旧C_OWN正常投影',source='work/wave_v104/peer/api.py',function='prepared_session(activity,execution_records)',
                 details='同normal.recordのquote_valid/seq/価格から同原行に投影。候補不対応を未来行へ移動しない。C量/reset/支持rootsはそのまま。'),
            dict(stage='純価格6点と範囲内反発',source='work/wave_v106/range_price/features.py',function='build(raws,records,symbol)',
                 details='不変六点測定を現在packetへ直接接続。first公表、相手strictpast、asof15秒、各同clock尾部seq/highwater再確認。量を価格差へ代用しない。'),
            dict(stage='二固定条件',source='work/wave_v106/range_price/selection.py',function='build(packet,symbol,config)',
                 details='ER0.4/margin2/LIMIT、料金後RR1.25、範囲内quarter、5/10枚、RANGE先AUTOは元C_OWN同方向2bp。未取得場から閾値調整/再選定しない。'),
            dict(stage='途中終端の答え合わせ',source='work/wave_v106/range_price/interface.py',function='play(prepared,normal,config,quantity,finish=False)',
                 details='根の正式登録/金融指示後のみ。途中端点を架空返済せず、最後のquoteで保有/予約・実現収支・料込清算時価を分離。')],
        時間境界=dict(予定='Night16:30開始、06:00終了、旧normal limit=05:55、entrycut=05:50、force=05:54。元値を新4:30終端へ移動しない。',
            取得予定='根が04:30頃。実際の取得開始/終了時計と各商品の最後の価格代理時計を別記。',
            途中='04:30はforce前の接頭入力。06:00まで計算しても取得後の価格は追加されない。全ナイト損益/通常全返済とは呼ばない。',
            clocks='CurrentPriceTimeは最終価格代理、受信時計ではない。二商品の取得時間が別である事実と各原行の到着順不明を記録。'),
        必要人工対照=[
            '小Night JSON行の旧extract_rowsと新wrapperの44列/normal/LP完全同値。欠測、同clock、時計逆行は元採否のまま。',
            'Night接頭180行と延長241行で、同原seqのprepared record/reference_open/trend_widthとC_OWN当時pulse/支持roots一致。',
            '純価格six新current接続と確定scalar観測一致。同期/相手同clockをstrictpastとして未来救済しない。',
            '二固定normalケースはrange_price.selection直接出力と全列/decisions同値。初回5/10と上限10/20を混同しない。',
            '途中finish=Falseは保有/予約を保持。後の正常quote/forceを追加した人工だけ通常返済し、接頭までの注文は不変。',
            '新所有cache locatorとcanonical aliasを確認し、旧source/cache書込0。'],
        観測限界=['取得時に履歴が開場から存在しなければC板episodeの状態は再現不能。見えていない先頭を補完しない。',
            'API応答の配列保存順は原seq代理。個別受信時刻が無ければ真のクロスマーケット到着因果を証明しない。',
            '未完了場の実現損益だけでは残玉評価リスクを隠すため、全残玉fee込み清算時価を併記。',
            '既知33場とは別表。未取得場はまだ評価0であり成功とは言えない。'],
        source_SHA256={n:digest(ROOT/n) for n in source_names},API取得=0,原本読取=0,新金融再生=0,現Night内容読取=0)
    path=HERE/'現ナイトの同パイプライン接続と途中終端の計画.json';assert not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    print('未取得Nightの適応計画を保存。API・新金融0',flush=True)


if __name__=='__main__':run()
