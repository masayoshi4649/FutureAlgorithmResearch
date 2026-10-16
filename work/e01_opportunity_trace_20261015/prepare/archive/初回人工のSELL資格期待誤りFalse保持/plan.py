"""元公開と継続窓の因果診断を、金融と独立した最小読取計画へ固定する。"""

import common

PLAN_NAME='元公開と紙上継続窓の非金融一読診断計画.json'
ART_NAME='厳密joinと公開符号及び当時窓接頭の純人工.json'
FIXED_NAME='二cacheの小目録固定.json'


def prepared(artifact_sha: str) -> dict:
    """
    機能: 本文未読の必要列・定数・分母・停止条件を明示する。
    引数: artifact_sha(str) は完成人工指紋。
    返り値: dict はsource固定済み/実入力指紋待ちの非金融計画。
    """
    return dict(全合格=True,状態='SOURCE_ONLY・人工成功。大型本文は根の小目録固定と実行授権待ち。',
        目的='元公開の一回資格と、同じ紙上方向が続く後normalの現在窓資格を当時条件だけで分ける。金融効果は測らない。',
        source_SHA256=common.sources(),source111不変の確認対象=common.old_sources(),人工SHA256=artifact_sha,
        元source契約SHA256=common.digest(common.HERE/'source契約と非金融機会診断の準備案.json'),
        input_manifest_paths=common.INPUT_MANIFESTS,入力指紋状態='3小目録本文未読。根が別授権する小目録固定でcache66のpath/SHAを確定する。',
        必要最小列=dict(TradeGate=dict(root=['schema_version','session','accounts'],
            account=['symbol','record','quotes','feed','quiet','quiet_force','mapping','trade_features'],
            record=['price','seq','time_s','start','end','limit','tick'],quotes=['bid','ask','quote_valid','seq','time_s'],
            feed='10列を同順保存。列0公開row/1旧判断row/2paperCID/3side/4qty/5公開Last/6理由/7new/8role/9ATR。',
            trade_features='PUBのみ10/30/60のknown/reason/count/up/down/既signedbalance/候補・基準・窓始原row。'),
            TradeExit=dict(account=['symbol','record','quotes','votes'],votes=['known','reason','up_votes','down_votes','unsigned_balance',
                'candidate_raw_row','candidate_raw_seq','candidate_price_time_s','reference_raw_row','first_vote_raw_row'],
                window='診断は60秒、元PUB同値は保存10/30/60すべてを照合。')),
        事前定数=dict(window_seconds=60,volume_min_votes=2,volume_signed_threshold={'TOPIX':.5,'NK225':.25},
            price_min_votes_each=2,price_signed_threshold_each=.25,peer_strictpast=True,peer_max_price_age_seconds=60,
            price_window_end='相手は選択したstrict過去の正常末端clockを終点に過去60秒。ageは自己現在clockとの差。',
            new_period='[record.start+300, record.limit-300)',quantity={'TOPIX':10,'NK225':20},
            public_cost='spread*q*multiplier+2floor(q*片道料) <= .5*当時ask買/bid売*q*multiplier*.00075',
            price_allowance='両価格票known/min2/sidebalance>=.75だけ1観測T、他0T。診断予定値で実FAK試行ではない。'),
        処理=['同bytes1読/SHA検算後、同session両cacheのrecord/quotes型shape/全原seq/clock/Last/BBO/資格を一致。',
            '各窓candidate原rowをmappingへ、原seq/clockをrecordへ一致。PUB scalarと全normal票のknown/reason/debug/count/符号/保存系譜を照合。',
            'paper feedを当行まで順に進め、現在方向/紙上残量/公開ATR/当時方向開始rowを作る。未来paper新規で過去方向をラベルしない。',
            '現在volume unsigned票を現在paper sideへ一度だけ向ける。PUB signed値を後へ持越ししない。価格票は当行自己＋strict過去peerで別計算。',
            '市場資格、静観、開始/期限、正常Last/BBO、ATR、公開費用、volume/priceの各flagを併記。111の実busy/場停止を外した暫定PUB順序と明記。',
            '紙上方向区間の元PUB/後観測数/価格clock数/連続資格区間、各観測より前の累積適格観測数を接頭で計算。実入口前の数は未測。'],
        出力=['全66商品のstrictjoin/PUB同値検算数','各紙上CID方向区間の開始/最終観測/代理秒長・元PUB・後資格の3profile',
            '紙上zeroも含む全normalのBUY/SELL別現在窓資格カウンタ。紙上方向区間の条件付き群とは別母集団。',
            '元PUBの重複flagと実stateを外した暫定理由・現在許容0T1T','unknown/不足票/釣合い/quiet/期間/費用の観測交差、正常同clockを別分母で表示',
            '数値不一致時Falseに不足項目/読取済計数/対象場を保存。成功として埋めない。'],
        大型本文予定=dict(TradeGatecache=33,TradeExitcache=33,合計cache=66,元111台帳=0,原NPZ=0,原book=0,元金融本文=0,金融=0,API=0),
        小目録固定予定=dict(TradeGate目録=1,TradeExit最終目録=1,TradeExit有限時計補完=1),
        本文読取guard='根が小目録固定を別実行後、--root-input-review-complete。成功/False/開始guardが存在する場合は再開始禁止。',
        不足時停止=['列/型/shape欠落','異なるsession又はseq/time/mapping/BBO','scalar/fullnormal票/符号不一致','最終TradeExit補完又はsource指紋不一致',
            'paper残量/side/原CID不整合','目録33不一致又は未知source/無効cacheSHA'],
        未測=['実busy/返済予約/場stop/実約定/FAK失効と後資格のexact交差','distinctな最後の実方向票seq','深板/活動量/受信先後','新参加の勝率又は収支効果'],
        分母=['元paper PUB','紙上CIDごとの現在方向区間','normal観測行','観測PriceTime値数','連続適格normal区間'],
        禁止='観測行/連続区間を独立機会・未来正答率にしない。未来MFEやsession勝ち方向は診断ラベルだけ。金融へ進めない。',
        指標='第一段で指標を売買資格へ足さない。当時保存水準/確定足とfresh活動・quote反応・二市場の接続は別の未測仮説。',
        ラベル='9/21D10:45long、9/22D09:20short、9/23D09:05short、9/22N00:40longは事後ラベル。第一段の採否へハードコードしない。')
