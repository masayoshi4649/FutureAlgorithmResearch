"""状況選択・売買・昼夜の構成を結果参照前に固定する。"""


def active_configs():
    """
    機能: 一律介入との相違を分ける入口3・管理4・複合7条件を返す。
    引数: なし。
    返り値: list[dict]はID・説明・売買層への設定。
    """
    rows = [
        ('中期逆向きだけ再進行確認',dict(entry_policy=1)),
        ('二市場の時間軸合意で入口確認を選ぶ',dict(entry_policy=2)),
        ('再失敗と原板支持まで入口確認に含める',dict(entry_policy=3)),
        ('長短方向で維持半減全返済',dict(management_policy=1)),
        ('価格と原板の合意で維持半減全返済',dict(management_policy=2)),
        ('利益進捗で維持半減全返済',dict(management_policy=3)),
        ('長短原板と失敗履歴で維持半減全返済',dict(management_policy=4)),
        ('中期入口と長短管理の統合',dict(entry_policy=1,management_policy=1,add_policy=2)),
        ('合意入口と原板管理の統合',dict(entry_policy=2,management_policy=2,add_policy=2)),
        ('再失敗入口と進捗管理の統合',dict(entry_policy=3,management_policy=3,add_policy=1)),
        ('再失敗入口と複合管理の統合',dict(entry_policy=3,management_policy=4,add_policy=2)),
        ('合意入口と複合管理の統合',dict(entry_policy=2,management_policy=4,add_policy=1)),
        ('旧再進行入口と長短管理',dict(entry_guard=2,add_guard=2,management_policy=1)),
        ('旧再進行入口と複合管理',dict(entry_guard=2,add_guard=2,management_policy=4)),
    ]
    return [dict(id=f'C{i+1:02d}',name=name,changes=changes) for i,(name,changes) in enumerate(rows)]


def joint_configs():
    """
    機能: 昼夜の入口・保有・夜間方向投票を含む統合対照を固定する。
    引数: なし。
    返り値: list[dict]は昼夜別構成。日経の夜補完だけ新方向選択へ切り替える。
    """
    return [dict(id='J01',name='時間軸合意の統合',day='C08',night='C08',supplement='Z01'),
            dict(id='J02',name='価格位置と原板管理の統合',day='C09',night='C12',supplement='Z02'),
            dict(id='J03',name='再失敗と原板合意の統合',day='C11',night='C14',supplement='Z03'),
            dict(id='J04',name='強い反証時だけ方向変更と長短管理',day='C08',night='C13',supplement='Z04'),
            dict(id='J05',name='強い反証時だけ方向変更と元の追尾',day='C08',night='C13',supplement='Z05')]


def online_config():
    """
    機能: 過去完了場だけで次の昼又は夜の政策を選ぶ対照を固定する。
    引数: なし。
    返り値: dictは事前学習5場、直近10同種場、選択候補と損失重視の採点。
    """
    return dict(id='W01',name='過去完了場だけの逐次選択',warmup=5,window=10,
                candidates=['B5','C08','C09','C10','C11','C12','C13','C14','J01','J02','J03','J04','J05'],
                score='同商品・同昼夜の直近10場。無取引数、赤字数、平均赤字額、負の累計収支、候補IDの順で最小を選択。5場未満はB5。',
                note='各候補を並行仮想運転し、全返済後だけ会計を更新。今場の利益・最終方向・未来統計は参照しない。既知資料で設計したため未見検証とは呼ばない。')
