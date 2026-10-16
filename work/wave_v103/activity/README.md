最初に [活動cache仕様.json](活動cache仕様.json)、次に [人工発火の正常列直接投影と未来不変.json](人工発火の正常列直接投影と未来不変.json) を確認する。

活動は利益ではない。発火0は未活動として記録する。受付内normal対応pulseも、保有・返済優先・cooldown・次気配約定を判定する前の候補数である。

`prepare.py --prepare-plan` は小さい由来資料だけを読み、全32場・64口座の対象とsourceを固定する。正式入力は読まない。

根の別指示後だけ `python -X utf8 work/wave_v103/activity/prepare.py --root-activity-reviewed --workers 2` を一回実行する。既存正式cacheがあれば再開始を拒否する。

完了後の読取は `data.py.load_session(session:str, verify:bool=True) -> dict`。保存済み新cache一場だけを読み、配列をreadonlyにする。`accounts[symbol].pulses[id].normal_event` は同一原行のnormal列への直接投影であり、非対応pulseを次正常行へ移さない。元raw判断と受付外の消費記録も保持する。

`states_snapshot.py` は確定 `engine/states.py` の同一bytes複製。処理を改変せず、JIT書込を活動領域へ閉じるために使用する。

人工初回の成功記録は `人工初回_保存照合前/` に残す。保存summary内の配分tupleをlistへ揃え、JSONとpickleの照合も人工確認した現証跡を正式固定に使う。金融条件に変更はない。
