# 状態効果・液体・トニックの分類

2026-09-28調査。wikiの[Effects一覧](https://wiki.cavesofqud.com/index.php?title=Effects&oldid=72812)の78項目、[Effectsの16下位カテゴリ](https://wiki.cavesofqud.com/wiki/Category:Effects)、[液体カテゴリ](https://wiki.cavesofqud.com/wiki/Category:Liquids)の27種類、[Tonics](https://wiki.cavesofqud.com/wiki/Tonics)の11種類を照合した。Effectsの下位カテゴリには、一覧にない追加の効果ページはなかった。

分類データは [hybrid_effects.json](../harness/hybrid_effects.json)、評価処理は [hybrid_hazards.py](../harness/hybrid_hazards.py)。名称、分類、優先度、条件タグ、短い判断材料、ページURL・版IDを保持する。ClaudeとJevには、現在成立する規則・根拠の観測・出典を `derived.hazards` として共通に渡す。全カタログを毎回プロンプトへ追加する方式にはしていない。

ここでの網羅は、取得したwiki一覧に対する網羅である。固定ゲーム版2.0.211.56の全Effectクラス、MODや翻訳の別名、生成される料理効果、未表示のガス濃度まで既知になったわけではない。Wikiの根拠版は項目ごとに古さが異なる。未知の効果や液体は明示的に残し、未確認の免疫・濃度・純度を補完しない。

固定版では一部の効果が表示名に原因を付け足す。`Stuck` は「形容詞＋前置詞＋原因」で、通常は `stuck in X`、`Grabber` では `grabbed by X` になる。`Sitting` は `sitting on X`、`Enclosed` は `enclosed in X`、家具上の `Prone` は `lying on X`。評価ではこれらをカタログの基本効果へ対応づけ、表示名は根拠としてそのまま渡す。`grabbed by X` の実体は `Stuck` なので `stuck` の項目を使い、Latched ontoの別名として登録した `grabbed` の項目は使わない。`lying on X` は伏せとして、足元の有害液体との組み合わせ規則にも含める。wiki一覧にない `engulfed by X` は未知のまま扱う（2026-10-11、run11の `grabbed by a jilted lover` を受けて追加）。

## 判断の分け方

優先度は死亡確率ではなく、上位判断の緊急度。0＝通常、1＝状況次第、2＝注意、3＝急ぎの計画、4＝緊急とする。成立した規則の最大値を使う。3以上の新規・変化した条件、または未知の効果をClaudeへ渡し、同じ条件のままなら既存の判断を利用する。2以上または未知の状態では安全移動・休息マクロを控える。

| 分類 | 主な対象 | 判断上の扱い |
|---|---|---|
| 継続ダメージ | 出血、燃焼、毒、灰・胞子の付着によるダメージ、吸命 | HP残量、重複、回復阻害、離脱手段を確認する。 |
| 行動・移動制約 | 凍結、麻痺、気絶、拘束、伏せ、睡眠、囲い込み、荷重超過 | 敵や継続ダメージと重なる場合に優先度を上げる。 |
| 認識・操作の乱れ | 混乱、盲目、恐怖、不随意テレポート | 名前や地図、操作結果を過信せず、過去の観測と次の結果を照合する。 |
| 防御・速度低下 | cleaved、cracked、hobbled、sluggish、stonyなど | 追撃・被弾・行動回数への影響を評価する。 |
| 疾病・前兆・恒久変化 | sore throat、stiff legs、itchy skin、glotrot、ironshank、mutating | 即死危険と区別しつつ、対処が遅れる損失を上位に計画させる。 |
| 属性脆弱性 | coated in plasma | 燃焼・凍結・溶岩接触との組み合わせを緊急扱いにする。 |
| 有益・回復 | healing、berserk、wakeful、war tranceなど | それだけでは未知の危険にしない。他の有害状態を相殺した扱いにもしない。 |
| 条件付き効果 | 飛行、位相、sprinting、blaze tonic、料理効果など | 利点と制約の両方を渡す。解除・姿勢・対象との相互作用も確認する。 |
| 装備の故障 | broken、rusted、pulsed、装備の燃焼 | 身体ダメージと別の根拠として扱い、修理・交換を検討する。 |
| 液体付着・染み・地形 | 血、酸、油、スライムなど | 身体、装備、開放地形、携帯容器、乾いた染みを分ける。 |

## 組み合わせと対処

| 組み合わせ | 優先度・判断 | 根拠 |
|---|---|---|
| 継続ダメージ＋HP35%以下／異なる継続ダメージの重複 | 4。回復量だけで生存を見積もらない。同名の重複表示を二重計上しない。35%は運用上の閾値。 | [Bleeding](https://wiki.cavesofqud.com/wiki/Bleeding)、[Poisoned](https://wiki.cavesofqud.com/wiki/Poisoned) |
| 拘束・伏せ・凍結・睡眠等＋敵または継続ダメージ | 4。行動可能性と次に受ける攻撃を確認する。 | [Prone](https://wiki.cavesofqud.com/wiki/Prone)、[Asleep](https://wiki.cavesofqud.com/wiki/Asleep)、[Frozen](https://wiki.cavesofqud.com/wiki/Frozen) |
| 混乱・盲目・防御／速度低下＋見えている敵 | 3。混乱では名前・地図記号も乱れる。以前の地形を利用しても、結果の確認を省かない。 | [Confused](https://wiki.cavesofqud.com/wiki/Confused)、[Hobbled](https://wiki.cavesofqud.com/wiki/Hobbled)、[Cleaved](https://wiki.cavesofqud.com/wiki/Cleaved) |
| プラズマ付着＋燃焼・凍結・足元の溶岩 | 4。属性への脆弱性と温度の自然回復阻害、消火効率低下が重なる。 | [Coated in plasma](https://wiki.cavesofqud.com/wiki/Coated_in_plasma) |
| healing＋毒・ill | 3。回復は継続しても効率が下がる。illでは自然回復も止まる。毒ガスの効果に、通常毒の回復阻害まで機械的に付け加えない。 | [Ill](https://wiki.cavesofqud.com/wiki/Ill)、[Phase spider venom](https://wiki.cavesofqud.com/wiki/Phase_spider_venom)、[Poisoned by gas](https://wiki.cavesofqud.com/wiki/Poisoned_by_gas) |
| 伏せ＋足元のblack ooze／green goo／brown sludge | 4。疾病・毒・装備腐食の追加接触を警戒する。接触しただけで感染成立とは断定しない。 | [Black ooze](https://wiki.cavesofqud.com/wiki/Black_ooze)、[Green goo](https://wiki.cavesofqud.com/wiki/Green_goo)、[Brown sludge](https://wiki.cavesofqud.com/wiki/Brown_sludge) |
| 油・タール付着＋燃焼 | 3。共存を明示するが、固定版で未確認の追加ダメージ倍率は付けない。乾いた染みは除く。 | [Oil](https://wiki.cavesofqud.com/wiki/Oil)、[Asphalt](https://wiki.cavesofqud.com/wiki/Asphalt) |
| 凍結＋足元のconvalessence | 4。回復作用だけを見て安全と判断しない。接触には冷却作用もある。 | [Convalessence](https://wiki.cavesofqud.com/wiki/Convalessence) |
| 位相変化＋不適合な攻撃対象／壁中での解除 | 注意情報として渡す。完全に埋まった位置での実体化は致命的になりうるが、隠れた地形や残り時間は推測しない。 | [Phased](https://wiki.cavesofqud.com/wiki/Phased)、[Omniphase](https://wiki.cavesofqud.com/wiki/Omniphase) |
| glotrot＋飲食／会話が必要なクエスト | 出血や発話不能が進行・生存を妨げる。治療配合はそのゲームのCorpus Choliysで確認する。舌の再生だけを完治と扱わない。 | [Glotrot](https://wiki.cavesofqud.com/wiki/Glotrot) |

witchwood barkは回復と混乱を同時に起こしうる。今回の実測では `healing: Recovering 10 hit points over 2 turns.` が公開されていた。回復は優先度0の既知効果とし、混乱は別に残す。混乱の対処候補にはyuckwheatがあるが、実際に所持し操作候補へ出ているかを確認する。[Witchwood bark](https://wiki.cavesofqud.com/wiki/Witchwood_bark)、[Confused](https://wiki.cavesofqud.com/wiki/Confused)

itchy skinに疾病一般の対処をそのまま流用しない。菌類感染の配合や胞子と感染種の対応にもプレイごとの変動がある。stonyのようにrecuperatingで解除されるものもあり、状態別に対処条件を確認する。洗浄、注射、能力使用など、現在の実行器に候補がない操作を実行できるとは扱わない。[Fungal infections](https://wiki.cavesofqud.com/wiki/Fungal_infections)、[Itchy skin](https://wiki.cavesofqud.com/wiki/Itchy_skin)、[Stony](https://wiki.cavesofqud.com/wiki/Stony)

## 液体27種類

| 分類 | 対象 | 注意点 |
|---|---|---|
| 現在の接触が有害 | acid、lava | 身体と装備の耐性を混同しない。magma-coveredも認識する。 |
| 極めて危険な開放・接触 | neutron flux | 現在の接触は4。安全に収納された容器を持っているだけで4にしない。EMPや容器の給電喪失との相互作用は計画材料。 |
| 変質・ランダム効果 | warm static | 現在の付着3、隣接地形2。純度を推測しない。乾いた染みから発動を推測しない。 |
| 追加曝露に注意 | black ooze、green goo、brown sludge | 伏せ・飲用・蒸気などの経路を区別する。 |
| 滑りやすい地形 | oil、slime、gel、ink | 敵がいれば移動上の優先度2。付着だけでは転倒としない。 |
| 動きを妨げる地形 | asphalt、honey、sap、molten wax | moltenという語だけで溶岩扱いにしない。 |
| 冷却・回復 | convalessence | 有益さと凍結リスクを分ける。 |
| 敵生成の条件付きリスク | primordial soup | 混合と量に依存。見えていない混合物や体積は補完しない。 |
| その他の文脈・飲用／使用効果 | algae、blood、brain brine、cider、cloning draught、putrescence、salt、sunslag、water、wine | 付着・染み・飲用を区別する。これらを「飲んでも安全」という分類にはしていない。 |

各液体の本文・別名・出典は機械用カタログに含めた。[Liquids](https://wiki.cavesofqud.com/wiki/Liquids)、[Neutron flux](https://wiki.cavesofqud.com/wiki/Neutron_flux)、[Warm static](https://wiki.cavesofqud.com/wiki/Warm_static)、[Primordial soup](https://wiki.cavesofqud.com/wiki/Primordial_soup)

## トニック11種類

所持している鑑定済みトニックに対応する注意点を `consumable_cautions` へ渡す。これ自体では危険度を加点しない。未鑑定の色付きチューブから種類を推測しない。重ね飲み、Juicer、Mutated Human、Tonic Allergyを確認する。確認できない発動中トニック数はゼロと扱わない。[Tonics](https://wiki.cavesofqud.com/wiki/Tonics)、[Juicer](https://wiki.cavesofqud.com/wiki/Juicer)

| トニック | 特に確認する副作用・組み合わせ |
|---|---|
| blaze | 非移動行動で過熱。耐熱の利点を、静止しても安全という許可にしない。副反応は燃焼。 |
| Eaters' nectar | 恒久的なビルド変更。過剰投与の一般則には例外がある。 |
| hulk honey | 筋力・一時HPと引き換えに鈍足・非致死の自傷・HP認識制限。副反応は混乱。 |
| love | 関係や行動への影響。副反応は燃焼。 |
| rubbergum | 防御面の利点とAV・出血抵抗の低下。副反応は伏せ。 |
| salve | 漸次回復。毒・illで回復効率が下がる。Tonic Allergyではランダムな副反応もある。 |
| shade oil | Mutated Humanでは不随意の位相変化。解除位置を確認する。副反応は敵対する影分身。 |
| skulk | 暗所・日光で利害が変わる。光属性への脆弱性。副反応は盲目。 |
| sphynx salt | 遺伝型で効果が違う。副反応で精神変異のクールダウンが延びる。 |
| ubernostrum | 回復・状態解除・肢再生には時間と対象範囲がある。Tonic Allergyも確認する。 |
| luminous hoarshroom | 食品でもトニック扱い。毒の予防と既存毒の治療は異なる。副反応の凍結は冷気耐性100でも完全には防げない。 |

Tonic Allergyの個別ページではsalve/ubernostrumにも特別な副反応が説明されている。一般のトニック表だけではこの例外を拾えないため、欠点の有無を別に渡す。数値確率を身体危険度へ直接加算してはいない。[Tonic Allergy](https://wiki.cavesofqud.com/wiki/Tonic_Allergy)、[Luminous hoarshroom](https://wiki.cavesofqud.com/wiki/Luminous_hoarshroom_(food))

## 調査・検証の範囲

取得本文とURL・版ID・ハッシュは `.runtime/jev-status-wiki-20260928/manifest.json` に保存した。検索用ブラウズはrobots制限だったため、公開HTMLを通常のHTTPで取得した。`Tonic_overdose` は取得できず、代わりにTonicsの副反応節と各トニックの個別ページを使用した。液体の古い個別ページと新しい一覧には深さ・温度の数値差があるため、未照合の数値を実装へ移植していない。

今回の30分実走が終わった後に、この分類を実装した。78項目の分類漏れ、実測healing、プラズマ、毒と回復、敵との複合、疾病前兆、液体、装備腐食、トニックの携帯／使用区別を回帰テストで検証した。実プレイでの改善効果は次回の検証対象であり、今回の録画を新分類の実地成功例には数えない。

## Effects一覧78項目の対応

以下は取得した一覧への対応表。詳細の条件・根拠はカタログと上記の組み合わせ規則を参照。基礎優先度だけで最終判断しない。

| wikiの名称 | 分類 | 基礎優先度 | 出典 |
|---|---|---:|---|
| acute blinking tic | 意図しない操作 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Acute_blinking_tic) |
| asleep | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Asleep) |
| berserk | 有益 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/Berserk_(effect)) |
| blaze tonic | 条件付き | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Blaze_tonic_(effect)) |
| bleeding | 継続ダメージ | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Bleeding) |
| blind | 認識障害 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Blind) |
| blurry vision | 認識障害 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Monochrome) |
| broken | 装備・機能障害 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Broken) |
| budding | 条件付き | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Budding) |
| burning | 継続ダメージ | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Burning) |
| choking on ash | 継続ダメージ | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Choking_on_ash) |
| cleaved | 防御低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Cleaved) |
| coated in plasma | 属性脆弱性 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Coated_in_plasma) |
| confused | 認識障害 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Confused) |
| corrected vision | 有益 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/Corrected_vision) |
| covered in liquid | 液体接触・染み | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Covered_in_liquid) |
| covered in spores | 継続ダメージ | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Covered_in_spores) |
| cracked | 防御低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Cracked) |
| dazed | 能力低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Dazed) |
| deep dreaming | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Deep_dreaming) |
| disoriented | 防御低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Disoriented) |
| emboldened | 有益 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/Emboldened) |
| enclosed | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Enclosed) |
| exhaustion | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Exhaustion) |
| flying | 条件付き | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Flying) |
| frenzied | 条件付き | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Frenzied) |
| frozen | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Frozen) |
| gleaming | 文脈依存 | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Gleaming) |
| glotrot | 疾病 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Glotrot) |
| greased | 有益 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/Greased) |
| grounded | 移動・速度低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Grounded) |
| hobbled | 移動・速度低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Hobbled) |
| hyper-responsive | 条件付き | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Hyper-responsive) |
| ill | 回復阻害 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Ill) |
| inspired | 有益 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/Inspired) |
| interdicted | 移動・速度低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Interdicted) |
| ironshank | 疾病 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Ironshank) |
| itchy skin | 疾病前兆 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Itchy_skin) |
| latched onto | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Latched_onto) |
| lost | 移動経路の制約 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/Lost) |
| lovesick | 能力低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Lovesick) |
| metabolizing | 条件付き | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Metabolizing) |
| monochrome | 認識障害 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Monochrome) |
| mutating | 恒久変化の前段階 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Mutating) |
| omniphase | 位相 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Omniphase) |
| overburdened | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Overburdened) |
| paralyzed | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Paralyzed) |
| phase spider venom | 継続ダメージ | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Phase_spider_venom) |
| phased | 位相 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Phased) |
| phosphorescent | 有益 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/Phosphorescent) |
| poisoned | 継続ダメージ | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Poisoned) |
| poisoned by gas | 継続ダメージ | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Poisoned_by_gas) |
| power skating | 条件付き | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Power_skating) |
| prone | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Prone) |
| proselytized | 文脈依存 | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Proselytized) |
| psionically cleaved | 防御低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Psionically_cleaved) |
| pulsed | 装備・機能障害 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Pulsed) |
| rusted | 装備・機能障害 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Rusted) |
| shaken | 防御低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Shaken) |
| shamed | 能力低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Shamed) |
| shimmering | 移動・速度低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Shimmering) |
| sitting | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Sitting) |
| sluggish | 移動・速度低下 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Sluggish) |
| sore throat | 疾病前兆 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Glotrot) |
| springing | 有益 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/Springing) |
| sprinting | 条件付き | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Sprinting) |
| stained by liquid | 液体接触・染み | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Stained_by_liquid) |
| stiff legs | 疾病前兆 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Ironshank) |
| stony | 移動・速度低下 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Stony) |
| stuck | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Stuck) |
| stunned | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Stunned) |
| stunned by gas | 行動制約 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Stunned_by_gas) |
| submerged | 文脈依存 | 1 | [wiki](https://wiki.cavesofqud.com/wiki/Submerged) |
| syphoned | 継続ダメージ | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Syphoned) |
| terrified | 意図しない操作 | 3 | [wiki](https://wiki.cavesofqud.com/wiki/Terrified) |
| wakeful | 有益 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/Wakeful) |
| waking dream | 文脈依存 | 2 | [wiki](https://wiki.cavesofqud.com/wiki/Waking_dream) |
| war trance | 有益 | 0 | [wiki](https://wiki.cavesofqud.com/wiki/War_trance) |
