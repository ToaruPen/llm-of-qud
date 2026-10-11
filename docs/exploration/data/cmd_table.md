| Commands.xml 行 | ID | 表示名 | Category | Layer | 既定キー (Commands.xml) | 旧 DefaultKeymap.json | Auto | モーダル性 / ハンドラ |
|---|---|---|---|---|---|---|---|---|
| 107 | CmdMoveNW | Move northwest | Basic Move / Attack | AdventureNav | numpad7, shift+upArrow, y[hjkl] | P:NumPad7 S:Shift+Up |  | 非モーダル: Player.Move (XRLCore.cs:1191) |
| 112 | CmdMoveN | Move north | Basic Move / Attack | AdventureNav | numpad8, upArrow, k[hjkl] | P:NumPad8 |  | 非モーダル: Player.Move (XRLCore.cs:1175) |
| 117 | CmdMoveNE | Move northeast | Basic Move / Attack | AdventureNav | numpad9, shift+rightArrow, u[hjkl] | P:NumPad9 S:Shift+Right |  | 非モーダル: Player.Move (XRLCore.cs:1199) |
| 122 | CmdMoveW | Move west | Basic Move / Attack | AdventureNav | numpad4, leftArrow, h[hjkl] | P:NumPad4 |  | 非モーダル: Player.Move (XRLCore.cs:1162) |
| 127 | CmdMoveE | Move east | Basic Move / Attack | AdventureNav | numpad6, rightArrow, l[hjkl] | P:NumPad6 |  | 非モーダル: Player.Move (XRLCore.cs:1167) |
| 132 | CmdMoveSW | Move southwest | Basic Move / Attack | AdventureNav | numpad1, shift+leftArrow, b[hjkl] | P:NumPad1 S:Shift+Left |  | 非モーダル: Player.Move (XRLCore.cs:1207) |
| 137 | CmdMoveS | Move south | Basic Move / Attack | AdventureNav | numpad2, downArrow, j[hjkl] | P:NumPad2 |  | 非モーダル: Player.Move (XRLCore.cs:1183) |
| 142 | CmdMoveSE | Move southeast | Basic Move / Attack | AdventureNav | numpad3, shift+downArrow, n[hjkl] | P:NumPad3 S:Shift+Down |  | 非モーダル: Player.Move (XRLCore.cs:1215) |
| 147 | CmdMoveU | Move up | Basic Move / Attack | AdventureNav | numpadMinus, shift+comma, s | P:Shift+Oemcomma S:Subtract |  | 非モーダル/即時 (XRLCore.cs:1417) |
| 153 | CmdMoveD | Move down | Basic Move / Attack | AdventureNav | numpadPlus, shift+period, d | P:Shift+OemPeriod S:Add |  | 非モーダル/即時 (XRLCore.cs:1503) |
| 159 | CmdMoveTo | Move to cell | Basic Move / Attack | Adventure | ctrl+enter | P:Ctrl+Enter | Down | セルピッカー PickTarget (XRLCore.cs:1237) |
| 163 | CmdAttackNW | Force attack northwest | Basic Move / Attack | Adventure | ctrl+numpad7, ctrl,shift+upArrow, ctrl+y[hjkl] | P:Ctrl+NumPad7 S:Ctrl+Shift+Up |  | 非モーダル (XRLCore.cs:1367) |
| 168 | CmdAttackN | Force attack north | Basic Move / Attack | Adventure | ctrl+numpad8, ctrl+upArrow, ctrl+k[hjkl] | P:Ctrl+NumPad8 S:Ctrl+Up |  | 非モーダル (XRLCore.cs:1361) |
| 173 | CmdAttackNE | Force attack northeast | Basic Move / Attack | Adventure | ctrl+numpad9, ctrl,shift+rightArrow, ctrl+u[hjkl] | P:Ctrl+NumPad9 S:Ctrl+Shift+Right |  | 非モーダル (XRLCore.cs:1370) |
| 178 | CmdAttackW | Force attack west | Basic Move / Attack | Adventure | ctrl+numpad4, ctrl+leftArrow, ctrl+h[hjkl] | P:Ctrl+NumPad4 S:Ctrl+Left |  | 非モーダル (XRLCore.cs:1355) |
| 183 | CmdAttackE | Force attack east | Basic Move / Attack | Adventure | ctrl+numpad6, ctrl+rightArrow, ctrl+l[hjkl] | P:Ctrl+NumPad6 S:Ctrl+Right |  | 非モーダル (XRLCore.cs:1358) |
| 188 | CmdAttackSW | Force attack southwest | Basic Move / Attack | Adventure | ctrl+numpad1, ctrl,shift+leftArrow, ctrl+b[hjkl] | P:Ctrl+NumPad1 S:Ctrl+Shift+Left |  | 非モーダル (XRLCore.cs:1373) |
| 193 | CmdAttackS | Force attack south | Basic Move / Attack | Adventure | ctrl+numpad2, ctrl+downArrow, ctrl+j[hjkl] | P:Ctrl+NumPad2 S:Ctrl+Down |  | 非モーダル (XRLCore.cs:1364) |
| 198 | CmdAttackSE | Force attack southeast | Basic Move / Attack | Adventure | ctrl+numpad3, ctrl,shift+downArrow, ctrl+n[hjkl] | P:Ctrl+NumPad3 S:Ctrl+Shift+Down |  | 非モーダル (XRLCore.cs:1376) |
| 203 | CmdAttackU | Force attack up | Basic Move / Attack | Adventure | ctrl+numpadMinus, ctrl,shift+comma | P:Ctrl+Subtract |  | 非モーダル/即時 (XRLCore.cs:1379) |
| 207 | CmdAttackD | Force attack down | Basic Move / Attack | Adventure | ctrl+numpadPlus, ctrl,shift+period | P:Ctrl+Add |  | 非モーダル/即時 (XRLCore.cs:1385) |
| 211 | CmdAttackDirection | Force attack in a direction | Basic Move / Attack | Adventure | backslash | P:Oem102 | Down | 方向ピッカー PickDirection (XRLCore.cs:1393) |
| 214 | CmdAttackCell | Choose cell to force attack | Basic Move / Attack | Adventure | ctrl+backslash | P:Shift+Oem102 | Down | セルピッカー (XRLCore.cs:1405) |
| 219 | IndicateDirection | Indicate direction  | Basic Move / Attack | AdventureNav |  |  |  |  |
| 222 | IndicateDirection/up | Indicate north | Basic Move / Attack | AdventureNav |  |  |  |  |
| 224 | IndicateDirection/down | Indicate south | Basic Move / Attack | AdventureNav |  |  |  |  |
| 226 | IndicateDirection/left | Indicate west | Basic Move / Attack | AdventureNav |  |  |  |  |
| 228 | IndicateDirection/right | Indicate east | Basic Move / Attack | AdventureNav |  |  |  |  |
| 231 | Take A Step | Take a step after indicating direction | Basic Move / Attack | AdventureNav |  |  |  |  |
| 234 | ForceAttack | Force attack after indicating direction | Basic Move / Attack | Adventure |  |  |  |  |
| 239 | Accept | Accept | Menus | UINav | space, enter, numpadenter |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 245 | Cancel | Cancel | Menus | UINav | escape |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 250 | UI:Click | UI:Click | InternalUI | UINav | mouse:{'Button': 'leftButton'} |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 253 | UI:RightClick | UI:RightClick | InternalUI | UINav | mouse:{'Button': 'rightButton'} |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 256 | UI:ScrollWheel | UI:ScrollWheel | InternalUI | UINav | mouse:{'Button': 'scroll'} |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 260 | UI:Navigate | Navigate | Menus | UINav |  |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 263 | UI:Navigate/up | Navigate up | Menus | UINav | upArrow, numpad8, k[hjkl] |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 269 | UI:Navigate/down | Navigate down | Menus | UINav | downArrow, numpad2, j[hjkl] |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 275 | UI:Navigate/left | Navigate left | Menus | UINav | leftArrow, numpad4, h[hjkl] |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 281 | UI:Navigate/right | Navigate right | Menus | UINav | rightArrow, numpad6, l[hjkl] |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 288 | UI:DetailsNavigate | Navigate details | Menus | CategoryNav |  |  |  | モーダル内でのみ有効 (Layer=CategoryNav から推定) |
| 291 | UI:DetailsNavigate/up | Navigate details up | Menus | UINav | shift+upArrow, shift+k[hjkl] |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 296 | UI:DetailsNavigate/down | Navigate details down | Menus | UINav | shift+downArrow, shift+j[hjkl] |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 301 | UI:DetailsNavigate/left | Navigate details left | Menus | UINav | shift+leftArrow, shift+h[hjkl] |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 306 | UI:DetailsNavigate/right | Navigate details right | Menus | UINav | shift+rightArrow, shift+l[hjkl] |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 312 | Page Up | Page up | Menus | Menus | pageUp, ctrl+upArrow, ctrl+numpad9, ctrl+k[hjkl] |  |  | モーダル内でのみ有効 (Layer=Menus から推定) |
| 321 | Page Down | Page down | Menus | Menus | pageDown, ctrl+downArrow, ctrl+numpad3, ctrl+j[hjkl] |  |  | モーダル内でのみ有効 (Layer=Menus から推定) |
| 330 | Page Right | Next page | Menus | Menus | numpad9, end, u[hjkl] |  |  | モーダル内でのみ有効 (Layer=Menus から推定) |
| 336 | Page Left | Previous page | Menus | Menus | numpad7, home, y[hjkl] |  |  | モーダル内でのみ有効 (Layer=Menus から推定) |
| 343 | Category Right | Next category | Menus | CategoryNav | E, ctrl+rightArrow |  |  | モーダル内でのみ有効 (Layer=CategoryNav から推定) |
| 348 | Category Left | Previous category | Menus | CategoryNav | Q, ctrl+leftArrow |  |  | モーダル内でのみ有効 (Layer=CategoryNav から推定) |
| 354 | CmdInsert | Insert | Menus | Menus | insert, ctrl+][hjkl] |  | DownPass | モーダル内でのみ有効 (Layer=Menus から推定) |
| 359 | CmdDelete | Delete | Menus | Menus | delete, backspace, [[hjkl] |  | DownPass | モーダル内でのみ有効 (Layer=Menus から推定) |
| 365 | V Positive | Increase value | Menus | Menus | numpadPlus, equals |  | Down | モーダル内でのみ有効 (Layer=Menus から推定) |
| 370 | V Negative | Decrease value | Menus | Menus | numpadMinus, minus |  | Down | モーダル内でのみ有効 (Layer=Menus から推定) |
| 375 | CmdFilter | Filter/Search | Menus | Menus | ctrl+f |  | DownPass | モーダル内でのみ有効 (Layer=Menus から推定) |
| 378 | Submit | Submit text | Menus | UINav | enter, numpadenter |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 383 | CmdHelp | Help | Menus | UI | F1 | P:F1 | DownPass | Manual.ShowHelp (XRLCore.cs:1701) |
| 388 | CmdOptions | View options | Menus | Menus | tab |  | DownPass | モーダル内でのみ有効 (Layer=Menus から推定) |
| 393 | Toggle | Toggle | Menus | Menus | ctrl+tab |  | DownPass | モーダル内でのみ有効 (Layer=Menus から推定) |
| 399 | GamepadAlt | Gamepad Alt | Menus | Adventure |  |  |  |  |
| 403 | Take All | Take all | Menus | Menus | tab |  | DownPass | モーダル内でのみ有効 (Layer=Menus から推定) |
| 407 | Store Items | Store items | Menus | Menus | F2, numpadMultiply |  | DownPass | モーダル内でのみ有効 (Layer=Menus から推定) |
| 415 | CmdUse | Use | Adventuring | Adventure | space | P:Space |  | PerformSmartUse (XRLCore.cs:1679) — 文脈 popup と推定 |
| 419 | CmdTalk | Talk | Adventuring | Adventure | c | P:C | Down | 方向ピッカー→会話 UI (XRLCore.cs:2212-2238) |
| 422 | CmdLook | Look | Adventuring | Adventure | l[default], semicolon[hjkl] | P:L | Down | Look モード Look.ShowLooker (XRLCore.cs:1697) |
| 426 | LookDirection | Look in a direction | Adventuring | AdventureNav |  |  |  |  |
| 429 | CmdGet | Get | Adventuring | Adventure | g | P:G | Down | FireEvent CommandGet (XRLCore.cs:2144) — 複数物品時リスト popup と推定 |
| 432 | CmdMoveToPointOfInterest | Move to point of interest | Adventuring | Adventure | backspace | P:Back | Down | Popup.PickOption (XRLCore.cs:1347) |
| 436 | CmdMoveToEdge | Move to edge of zone | Adventuring | Adventure | shift+enter | P:Shift+Enter | Down | XRLCore.cs:1255 |
| 440 | CmdGetFrom | Interact nearby | Adventuring | Adventure | ctrl+space, ctrl+g | P:Ctrl+Space |  | FireEvent CommandGetFrom (XRLCore.cs:2147) — 方向/対象選択と推定 |
| 445 | CmdOpen | Open | Adventuring | Adventure | o | P:O | Down | 方向ピッカー (XRLCore.cs:2174-2176) |
| 448 | CmdFire | Fire missile weapon | Adventuring | AdventureTargeting | f | P:F | Down | ミサイル照準 UI (XRLCore.cs:1840-) — Targeting layer |
| 452 | CmdReload | Reload missile weapon | Adventuring | Adventure | r | P:R | Down | CommandReloadEvent (XRLCore.cs:2206) |
| 456 | CmdReplaceCell | Replace energy cell | Adventuring | Adventure | ctrl+r |  | Down | CommandReplaceCellEvent (XRLCore.cs:2209) — セル選択 popup と推定 |
| 460 | CmdThrow | Throw | Adventuring | AdventureTargeting | t | P:T | Down | Combat.ThrowWeapon (XRLCore.cs:1837) — ターゲット選択 UI と推定 |
| 464 | CmdTarget | Choose target | Adventuring | Adventure | ctrl+t | P:Ctrl+T | Down | PickTarget (XRLCore.cs:1826-1829) |
| 467 | CmdAttackNearest | Melee attack nearest enemy | Adventuring | Adventure |  | P:Shift+A | Repeat | 非モーダル/即時 (XRLCore.cs:1941) |
| 470 | CmdWait | Wait / Pat at flames | Adventuring | Adventure | numpad5, shift+space | P:NumPad5 | Repeat | 非モーダル/即時 (XRLCore.cs:1517) |
| 474 | CmdWait20 | Wait 20 turns | Adventuring | Adventure | numpadPeriod | P:Decimal | Down | 非モーダル/即時 (XRLCore.cs:1543) |
| 477 | CmdWait100 | Wait 100 turns | Adventuring | Adventure | ctrl+numpadPeriod | P:Ctrl+Decimal | Down | 非モーダル/即時 (XRLCore.cs:1587) |
| 480 | CmdWaitN | Wait a number of turns | Adventuring | Adventure |  | P:Shift+W | Down | Popup.AskNumber (XRLCore.cs:1559) |
| 481 | CmdWaitUntilHealed | Rest until healed | Adventuring | Adventure | backquote | P:Oemtilde | Down | 非モーダル/即時 (XRLCore.cs:1596) |
| 485 | CmdWaitUntilPartyHealed | Rest until party is healed | Adventuring | Adventure |  |  | Down | 非モーダル/即時 (XRLCore.cs:1607) |
| 487 | CmdWaitUntilMorning | Rest until morning | Adventuring | Adventure |  | P:Ctrl+Oemtilde | Down | 非モーダル/即時 (XRLCore.cs:1620) |
| 488 | CmdWaitMenu | Bring up wait menu | Adventuring | Adventure | ctrl+backquote |  | Down | Popup.PickOption (XRLCore.cs:929) |
| 492 | CmdMoveMenu | Bring up move menu | Adventuring | Adventure | shift+m |  | Down | Popup.PickOption (XRLCore.cs:967) |
| 495 | CmdAutoExplore | Autoexplore | Adventuring | Adventure | numpad0 | P:NumPad0 | Down | 非モーダル: AutoAct.Setting="?" (XRLCore.cs:1920-1926) |
| 499 | CmdWalk | Walk in a direction | Adventuring | AdventureLooker | w | P:W | Down | 方向ピッカー (XRLCore.cs:2105-2110) |
| 502 | CmdAutoAttack | Autoattack in melee | Adventuring | Adventure | ctrl+a | P:Ctrl+A | Down | 非モーダル: AutoAct.Setting="a"、target 無しは popup (XRLCore.cs:1927-1940) |
| 505 | CmdCompanions | Interact with companions | Adventuring | Adventure | ctrl+c |  | Down | Popup.PickGameObject (XRLCore.cs:2299-2321) |
| 508 | CmdStartTrade | Start trade from conversation | Adventuring | Conversation | tab, T |  | DownPass | モーダル内でのみ有効 (Layer=Conversation から推定) |
| 513 | Highlight | Bring up overlay / tooltip | Adventuring | Adventure |  |  |  |  |
| 516 | LookDirection/up | Look north | Adventuring | AdventureNav |  |  |  |  |
| 518 | LookDirection/down | Look south | Adventuring | AdventureNav |  |  |  |  |
| 520 | LookDirection/left | Look west | Adventuring | AdventureNav |  |  |  |  |
| 522 | LookDirection/right | Look east | Adventuring | AdventureNav |  |  |  |  |
| 524 | Navigate Vertical | Move north / south (navigate menus up / down in Legacy UI) | Adventuring | AdventureNav |  |  |  |  |
| 525 | Navigate Horizontal | Move west / east (navigate menus left / right in Legacy UI) | Adventuring | AdventureNav |  |  |  |  |
| 527 | CmdMoveFarNW | Move to northwestern corner | Advanced Adventuring | AdventureNav | alt+numpad7, alt,shift+upArrow |  | Down | 非モーダル: 自動移動 (XRLCore.cs:1270-1325) |
| 531 | CmdMoveFarN | Move to northern edge | Advanced Adventuring | AdventureNav | alt+numpad8, alt+upArrow |  | Down | 非モーダル: 自動移動 (XRLCore.cs:1270-1325) |
| 535 | CmdMoveFarNE | Move to northeastern corner | Advanced Adventuring | AdventureNav | alt+numpad9, alt,shift+rightArrow |  | Down | 非モーダル: 自動移動 (XRLCore.cs:1270-1325) |
| 539 | CmdMoveFarW | Move to western edge | Advanced Adventuring | AdventureNav | alt+numpad4, alt+leftArrow |  | Down | 非モーダル: 自動移動 (XRLCore.cs:1270-1325) |
| 543 | CmdMoveFarE | Move to eastern edge | Advanced Adventuring | AdventureNav | alt+numpad6, alt+rightArrow |  | Down | 非モーダル: 自動移動 (XRLCore.cs:1270-1325) |
| 547 | CmdMoveFarSW | Move to southwestern corner | Advanced Adventuring | AdventureNav | alt+numpad1, alt,shift+leftArrow |  | Down | 非モーダル: 自動移動 (XRLCore.cs:1270-1325) |
| 551 | CmdMoveFarS | Move to southern edge | Advanced Adventuring | AdventureNav | alt+numpad2, alt+downArrow |  | Down | 非モーダル: 自動移動 (XRLCore.cs:1270-1325) |
| 555 | CmdMoveFarSE | Move to southeastern corner | Advanced Adventuring | AdventureNav | alt+numpad3, alt,shift+downArrow |  | Down | 非モーダル: 自動移動 (XRLCore.cs:1270-1325) |
| 559 | CmdMoveCenter | Move to center | Advanced Adventuring | AdventureNav | alt+numpad5 |  | Down | 非モーダル: 自動移動 (XRLCore.cs:1270-1325) |
| 565 | CmdMissileWeaponMenu | Open missile weapon menu | Targeting | Targeting |  | P:Multiply | DownPass | モーダル内でのみ有効 (Layer=Targeting から推定) |
| 568 | CmdTargetSelf | Target self | Targeting | Targeting | numpad5, period |  | DownPass | モーダル内でのみ有効 (Layer=Targeting から推定) |
| 573 | CmdMarkTarget | Mark target | Targeting | Targeting | m |  | DownPass | モーダル内でのみ有効 (Layer=Targeting から推定) |
| 576 | CmdLockUnlock | Toggle target lock | Menus | Targeting | F1 |  | DownPass | モーダル内でのみ有効 (Layer=Targeting から推定) |
| 580 | CmdAltFire1 | Alternate missile fire 1 | Targeting | Targeting | 1 |  | DownPass | モーダル内でのみ有効 (Layer=Targeting から推定) |
| 583 | CmdAltFire2 | Alternate missile fire 2 | Targeting | Targeting | 2 |  | DownPass | モーダル内でのみ有効 (Layer=Targeting から推定) |
| 586 | CmdAltFire3 | Alternate missile fire 3 | Targeting | Targeting | 3 |  | DownPass | モーダル内でのみ有効 (Layer=Targeting から推定) |
| 589 | CmdAltFire4 | Alternate missile fire 4 | Targeting | Targeting | 4 |  | DownPass | モーダル内でのみ有効 (Layer=Targeting から推定) |
| 592 | CmdAltFire5 | Alternate missile fire 5 | Targeting | Targeting | 5 |  | DownPass | モーダル内でのみ有効 (Layer=Targeting から推定) |
| 599 | CmdAbility1 | Use ability 1 | Ability Bar | Adventure | 1 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 602 | CmdAbility2 | Use ability 2 | Ability Bar | Adventure | 2 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 605 | CmdAbility3 | Use ability 3 | Ability Bar | Adventure | 3 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 608 | CmdAbility4 | Use ability 4 | Ability Bar | Adventure | 4 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 611 | CmdAbility5 | Use ability 5 | Ability Bar | Adventure | 5 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 614 | CmdAbility6 | Use ability 6 | Ability Bar | Adventure | 6 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 617 | CmdAbility7 | Use ability 7 | Ability Bar | Adventure | 7 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 620 | CmdAbility8 | Use ability 8 | Ability Bar | Adventure | 8 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 623 | CmdAbility9 | Use ability 9 | Ability Bar | Adventure | 9 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 626 | CmdAbility10 | Use ability 10 | Ability Bar | Adventure | 0 |  |  | Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395) |
| 630 | CmdAbilityBar1 | Switch to ability bar 1 | Ability Bar | Adventure | ctrl+1 |  |  | Modern UI 専用: AbilityBar ページ切替, CurrentGameView==Stage (GameManager.cs:2398-2418) |
| 633 | CmdAbilityBar2 | Switch to ability bar 2 | Ability Bar | Adventure | ctrl+2 |  |  | Modern UI 専用: AbilityBar ページ切替, CurrentGameView==Stage (GameManager.cs:2398-2418) |
| 636 | CmdAbilityBar3 | Switch to ability bar 3 | Ability Bar | Adventure | ctrl+3 |  |  | Modern UI 専用: AbilityBar ページ切替, CurrentGameView==Stage (GameManager.cs:2398-2418) |
| 639 | CmdAbilityBar4 | Switch to ability bar 4 | Ability Bar | Adventure | ctrl+4 |  |  | Modern UI 専用: AbilityBar ページ切替, CurrentGameView==Stage (GameManager.cs:2398-2418) |
| 642 | CmdAbilityBar5 | Switch to ability bar 5 | Ability Bar | Adventure | ctrl+5 |  |  | Modern UI 専用: AbilityBar ページ切替, CurrentGameView==Stage (GameManager.cs:2398-2418) |
| 645 | Ability Page Up | Ability bar page up | Ability Bar | Adventure | ctrl+tab |  |  | 注意: GameManager は CmdAbilityNextPage/PrevPage を参照 (GameManager.cs:2420-2426) — ID 不一致 |
| 649 | Ability Page Down | Ability bar page down | Ability Bar | Adventure | ctrl,shift+tab |  |  | 注意: GameManager は CmdAbilityNextPage/PrevPage を参照 (GameManager.cs:2420-2426) — ID 不一致 |
| 653 | Next Ability | Next ability | Ability Bar | Adventure |  |  |  |  |
| 656 | Previous Ability | Previous ability | Ability Bar | Adventure |  |  |  |  |
| 659 | Use Ability | Use selected ability | Adventuring | Adventure |  |  |  |  |
| 665 | CmdAbilities | Open abilities | Shortcuts to Character Sheet | Adventure | a | P:A | Down | AbilityManager.Show (XRLCore.cs:1806-1818) |
| 669 | CmdInventory | Open inventory | Shortcuts to Character Sheet | Adventure | i | P:I S:Tab | Down | Screens.Show (XRLCore.cs:1906-1910) |
| 672 | CmdEquipment | Open equipment | Shortcuts to Character Sheet | Adventure | e | P:E | Down | Screens.Show (XRLCore.cs:1911-1915) |
| 675 | CmdSkillsPowers | Open skills | Shortcuts to Character Sheet | Adventure | k[default], shift+k[hjkl] | P:P | Down | Screens.Show (XRLCore.cs:1916-1919) |
| 679 | CmdCharacter | Open attributes | Shortcuts to Character Sheet | Adventure | tab, x | P:X | Down | Screens.Show (XRLCore.cs:1902-1905) |
| 684 | CmdQuests | Open quests | Shortcuts to Character Sheet | Adventure | q | P:Q | Down | Screens.Show (XRLCore.cs:1892-1895) |
| 687 | CmdFactions | Open reputation | Shortcuts to Character Sheet | Adventure | ctrl+f | P:Shift+F | Down | Screens.ShowPopup (XRLCore.cs:1889-1891) |
| 690 | CmdTinkering | Open tinkering | Shortcuts to Character Sheet | Adventure | n[default], shift+n[hjkl] | P:K | Down | Screens.Show (XRLCore.cs:1710-1713) |
| 694 | CmdJournal | Open journal | Shortcuts to Character Sheet | Adventure | j[default], shift+j[hjkl] | P:J | Down | Screens.Show (XRLCore.cs:1706-1709) |
| 698 | CmdActiveEffects | Open status effects | Shortcuts to Character Sheet | Adventure | ctrl+e |  | Down | ShowActiveEffects (XRLCore.cs:1896-1898) |
| 701 | CmdLastStatusPage | Open most recent page on character sheet | Shortcuts to Character Sheet | Adventure |  |  | Down | Screens.Show (XRLCore.cs:1899-1901) |
| 702 | CmdMessageHistory | Show message history | Shortcuts to Character Sheet | Adventure |  | P:Ctrl+M | Down | Messages.Show (XRLCore.cs:2296-2298) |
| 707 | InventoryQuickDrop | Inventory: drop item | Character Sheet | StatusScreens | ctrl+d |  | DownPass | モーダル内でのみ有効 (Layer=StatusScreens から推定) |
| 710 | InventoryQuickEat | Inventory: eat item | Character Sheet | StatusScreens | ctrl+a |  | DownPass | モーダル内でのみ有効 (Layer=StatusScreens から推定) |
| 713 | InventoryQuickDrink | Inventory: drink from container | Character Sheet | StatusScreens | ctrl+q |  | DownPass | モーダル内でのみ有効 (Layer=StatusScreens から推定) |
| 716 | InventoryQuickApply | Inventory: apply item | Character Sheet | StatusScreens | ctrl+p |  | DownPass | モーダル内でのみ有効 (Layer=StatusScreens から推定) |
| 719 | CmdStatusBuyMutation | Attributes screen: buy new mutation | Character Sheet | StatusScreens:Charsheet | m |  | DownPass | モーダル内でのみ有効 (Layer=StatusScreens:Charsheet から推定) |
| 723 | CmdStatusShowEffects | Attributes screen: show status effects | Character Sheet | StatusScreens:Charsheet | e |  | DownPass | モーダル内でのみ有効 (Layer=StatusScreens:Charsheet から推定) |
| 730 | CmdTradeAdd | Add one of an item | Trade | Trade | equals, numpadPlus, numpad9 |  | Repeat | モーダル内でのみ有効 (Layer=Trade から推定) |
| 736 | CmdTradeRemove | Remove one of an item | Trade | Trade | minus, numpadMinus, numpad7 |  | Repeat | モーダル内でのみ有効 (Layer=Trade から推定) |
| 742 | CmdTradeAllItems | Add / remove a whole stack of items | Trade | Trade | enter, numpadEnter, ctrl+space |  | DownPass | モーダル内でのみ有効 (Layer=Trade から推定) |
| 749 | CmdTradeToggleAll | Add / remove whole inventory | Trade | Trade | tab |  | DownPass | モーダル内でのみ有効 (Layer=Trade から推定) |
| 752 | CmdTradeOffer | Offer | Trade | Trade | o |  | DownPass | モーダル内でのみ有効 (Layer=Trade から推定) |
| 756 | CmdVendorActions | Interact with item | Trade | Trade | space |  | DownPass | モーダル内でのみ有効 (Layer=Trade から推定) |
| 760 | CmdVendorLook | Look at item | Trade | Trade | l |  | DownPass | モーダル内でのみ有効 (Layer=Trade から推定) |
| 763 | CmdVendorRead | Read a book | Trade | Trade | b |  | DownPass | モーダル内でのみ有効 (Layer=Trade から推定) |
| 766 | CmdVendorRepair | Ask vendor to repair | Trade | Trade | r |  | DownPass | モーダル内でのみ有効 (Layer=Trade から推定) |
| 769 | CmdVendorRecharge | Ask vendor to recharge | Trade | Trade | c |  | DownPass | モーダル内でのみ有効 (Layer=Trade から推定) |
| 772 | CmdVendorExamine | Ask vendor to identify | Trade | Trade | i |  | DownPass | モーダル内でのみ有効 (Layer=Trade から推定) |
| 778 | CmdChargenRandom | Make a random selection | Character Creation | Chargen | r | P:R |  | モーダル内でのみ有効 (Layer=Chargen から推定) |
| 782 | CmdChargenReset | Reset selections | Character Creation | Chargen | delete | P:Delete |  | モーダル内でのみ有効 (Layer=Chargen から推定) |
| 786 | CmdChargenItemOptions | Choose option for selected item | Character Creation | Chargen | o | P:O |  | モーダル内でのみ有効 (Layer=Chargen から推定) |
| 790 | CmdChargenMutationVariant | Choose a mutation variant | Character Creation | Chargen | v | P:V |  | モーダル内でのみ有効 (Layer=Chargen から推定) |
| 794 | CmdDebugQuickstart | Quickstart (requires debug option enabled) | Character Creation | Chargen |  |  |  | モーダル内でのみ有効 (Layer=Chargen から推定) |
| 798 | CmdZoomIn | Zoom in | UI | Adventure |  |  | DownPass | XRLCore では no-op 分岐 (XRLCore.cs:2337) |
| 801 | CmdZoomOut | Zoom out | UI | Adventure |  |  | DownPass | XRLCore では no-op 分岐 (XRLCore.cs:2338) |
| 804 | CmdShowSidebar | Toggle sidebar | UI | Adventure | numpadDivide | P:Divide | DownPass | 非モーダル (XRLCore.cs:2251) |
| 807 | CmdShowSidebarMessages | Cycle sidebar mode | UI | Adventure | numpadMultiply | P:Multiply | DownPass | 非モーダル (XRLCore.cs:2254) |
| 810 | CmdToggleMessageVerbosity | Toggle terse messages | UI | Adventure |  |  | DownPass | 非モーダル: Messages.Terse 切替 (XRLCore.cs:2240-2250) |
| 814 | CmdQuit | Quit | System | System | ctrl+q | P:Ctrl+Q |  | Yes/No popup (XRLCore.cs:1727-1729) |
| 817 | CmdLoad | Load game | System | System | F9 | P:F9 |  | Yes/No popup, OptionAllowSaveLoad 必須 (XRLCore.cs:1792-1795) |
| 820 | CmdSave | Save game | System | System | F5 | P:F5 |  | Yes/No popup, OptionAllowSaveLoad 必須 (XRLCore.cs:1784-1790) |
| 823 | CmdSystemMenu | System menu | System | System | escape | P:Escape |  | システムメニュー popup (XRLCore.cs:983-1136) |
| 829 | AdventureMouseContextAction | Mouse smart use | Mouse-specific | Adventure | mouse:{'Button': 'leftButton'} |  |  |  |
| 832 | AdventureMouseInteract | Mouse interact | Mouse-specific | Adventure | mouse:{'Button': 'rightButton'} |  |  |  |
| 835 | AdventureMouseInteractAll | Mouse interact All | Mouse-specific | Adventure | mouse:{'Modifier': 'ctrl', 'Button': 'rightButton'} |  |  |  |
| 838 | AdventureMouseLook | Mouse look | Mouse-specific | Adventure | mouse:{'Modifier': 'shift', 'Button': 'rightButton'} |  |  |  |
| 841 | AdventureMouseQuickLook | Mouse quick look | Mouse-specific | Adventure |  |  |  |  |
| 843 | AdventureMouseForceAttack | Mouse force attack | Mouse-specific | Adventure | mouse:{'Modifier': 'ctrl', 'Button': 'leftButton'} |  |  |  |
| 846 | AdventureMouseForceMove | Mouse force move | Mouse-specific | Adventure | mouse:{'Modifier': 'shift', 'Button': 'leftButton'} |  |  |  |
| 850 | AdventureNavMouseLeftClick | Mouse target left click | Mouse-specific | UINav | mouse:{'Button': 'leftButton'} |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 854 | AdventureNavMouseRightClick | Mouse targeting right click | Mouse-specific | UINav | mouse:{'Button': 'rightButton'} |  |  | モーダル内でのみ有効 (Layer=UINav から推定) |
| 860 | CmdShowReachability | Show reachability map | Debug | Adventure |  |  | DownPass | 非モーダル/即時 (XRLCore.cs:1632) |
| 861 | CmdShowFPS | Show FPS | Debug | Adventure |  |  | DownPass | 非モーダル/即時 (XRLCore.cs:1629) |
| 862 | CmdToggleAnimation | Toggle animation | Debug | Adventure |  |  | DownPass | 非モーダル/即時 (XRLCore.cs:1703) |
| 863 | CmdShowBrainlog | Show brainlog | Debug | Adventure |  |  | DownPass | XRLCore では no-op 分岐 (XRLCore.cs:2336) |
| 864 | CmdWish | Wish | Debug | Adventure | ctrl+w |  | DownPass | WishManager.AskWish 文字列入力 (XRLCore.cs:1883-1885) |
| 867 | CmdWishMenu | Wish Menu | Debug | Adventure | shift+w |  | DownPass | WishMenu.OpenWishMenu (XRLCore.cs:1886-1888) |
| 870 | CmdXP | Gain 250,000 XP | Debug | Adventure |  |  | DownPass | 非モーダル/即時 (XRLCore.cs:2195) |
| 871 | CmdExplore | Reveal the whole map | Debug | Adventure |  |  | DownPass | 非モーダル/即時 (XRLCore.cs:1714) |
| 872 | CmdNoclipD | Noclip down | Debug | Adventure |  |  | DownPass | 非モーダル/即時 (XRLCore.cs:2272) |
| 873 | CmdNoclipU | Noclip up | Debug | Adventure |  |  | DownPass | 非モーダル/即時 (XRLCore.cs:2261) |
| 874 | CmdDismemberLimb | Dismember limb | Debug | Adventure |  |  | DownPass | 非モーダル/即時 (XRLCore.cs:2283) |
| 875 | CmdRegenerateLimb | Regenerate limb | Debug | Adventure |  |  | DownPass | 非モーダル/即時 (XRLCore.cs:2293) |
