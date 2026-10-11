| Options.xml 行 | ID | 表示名 | Category | Type | Default | 追加属性 |
|---|---|---|---|---|---|---|
| 3 | OptionMasterVolume | Main volume | Sound | Slider | 100 | Min: 0, Max: 100, Increment: 5 |
| 4 | OptionSound | Sound effects | Sound | Checkbox | Yes |  |
| 5 | OptionSoundVolume | Sound effects volume | Sound | Slider | 100 | Requires: OptionSound==Yes, Min: 0, Max: 100, Increment: 5 |
| 6 | OptionMusic | Music | Sound | Checkbox | Yes |  |
| 7 | OptionMusicVolume | Music volume | Sound | Slider | 100 | Requires: OptionMusic==Yes, Min: 0, Max: 100, Increment: 5 |
| 8 | OptionAmbient | Ambient sounds | Sound | Checkbox | Yes |  |
| 9 | OptionAmbientVolume | Ambient volume | Sound | Slider | 50 | Requires: OptionAmbient==Yes, Min: 0, Max: 100, Increment: 5 |
| 10 | OptionUseInterfaceSounds | Interface sounds | Sound | Checkbox | Yes | Requires: OptionSound==Yes,OptionShowAdvancedOptions==Yes |
| 11 | OptionInterfaceVolume | Interface volume | Sound | Slider | 100 | Requires: OptionUseInterfaceSounds==Yes,OptionShowAdvancedOptions==Yes, Min: 0, Max: 100, Increment: 5 |
| 12 | OptionUseCombatSounds | Combat sounds | Sound | Checkbox | Yes | Requires: OptionSound==Yes,OptionShowAdvancedOptions==Yes |
| 13 | OptionCombatVolume | Combat volume | Sound | Slider | 100 | Requires: OptionUseCombatSounds==Yes,OptionShowAdvancedOptions==Yes, Min: 0, Max: 100, Increment: 5 |
| 14 | OptionPlayFireSounds | Fire crackling sounds | Sound | Checkbox | Yes | Requires: OptionSound==Yes,OptionShowAdvancedOptions==Yes |
| 17 | OptionDisplayBrightness | Brightness | Display | Slider | 0 | Min: -100, Max: 100, Increment: 5 |
| 18 | OptionDisplayContrast | Contrast | Display | Slider | 0 | Min: -100, Max: 100, Increment: 5 |
| 19 | OptionDisplayFullscreen | Fullscreen | Display | Checkbox | Yes | RequiresCapability: CanModifyWindowSettings |
| 20 | OptionDisplayResolution | Fullscreen resolution | Display | BigCombo | Unset | RequiresCapability: CanModifyWindowSettings, Values: *Resolution |
| 21 | OptionDisplayFramerate | Frame rate | Display | Combo | VSync | RequiresCapability: CanModifyWindowSettings, Values: 10,20,30,40,50,60,120,Unlimited,VSync |
| 22 | OptionUseTiles | Enable tile graphics | Display | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 23 | OptionDisplayVignette | Display vignette effect | Display | Checkbox | Yes |  |
| 24 | OptionDisplayScanlines | Display scanlines | Display | Checkbox | Yes |  |
| 25 | OptionUseOverlayCombatEffects | Display combat animations | Display | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 26 | OptionUseOverlayDamageText | Display floating damage numbers | Display | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 27 | OptionUseParticleVFX | Display modern visual effects | Display | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 28 | OptionUseTextParticleVFX | Display ASCII visual effects | Display | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 29 | OptionDisableFloorTextures | Disable floor textures | Display | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 30 | OptionDisableBloodsplatter | Disable blood splatters | Display | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 31 | OptionDisableSmoke | Disable smoke effects | Display | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 32 | OptionDisableImposters | Disable modern, tile-based graphical effects | Display | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 33 | OptionMainMenuBackground | Main menu background art | Display | Combo | Modern | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes, Values: Modern,Classic |
| 36 | OptionsKeybindings | Control Mapping | Controls | Button | None | OnClick: Qud.UI.KeybindsScreen.ShowKeybindsClick, SearchKeywords: Control bindings |
| 37 | OptionKeyRepeatDelay | Key repeat delay | Controls | Slider | 10 | ConsoleDisplayText: Button repeat delay, Min: 5, Max: 100, Increment: 5 |
| 38 | OptionKeyRepeatRate | Key repeat rate | Controls | Slider | 90 | ConsoleDisplayText: Button repeat rate, Min: 0, Max: 100, Increment: 5 |
| 39 | OptionMouseInput | Allow mouse input | Controls | Checkbox | Yes | RequiresCapability: Mouse, Requires: OptionShowAdvancedOptions==Yes |
| 40 | OptionMouseMovement | Allow mouse movement | Controls | Checkbox | Yes | RequiresCapability: Mouse, Requires: OptionMouseInput==Yes,OptionShowAdvancedOptions==Yes |
| 41 | OptionMouseScrollWheel | Allow scroll wheel to zoom | Controls | Checkbox | Yes | RequiresCapability: Mouse, Requires: OptionMouseInput==Yes,OptionShowAdvancedOptions==Yes |
| 42 | OptionCapInputBuffer | Limit the input buffer to two commands | Controls | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 45 | OptionDisableFullscreenColorEffects | Disable fullscreen color effects (for color blindness) | Accessibility | Checkbox | No |  |
| 46 | OptionAlphanumericBits | Display bits with alphanumerics instead of dots (for color blindness) | Accessibility | Checkbox | Yes |  |
| 47 | OptionDisableTextAnimationEffects | Disable most tile-based flashing effects | Accessibility | Checkbox | No |  |
| 48 | OptionDisableAllIdleTileAnimations | Disable all idle tile-based animations | Accessibility | Checkbox | No |  |
| 49 | OptionDisableTextWarpEffects | Disable tile-based screen-warping effects | Accessibility | Checkbox | No |  |
| 50 | OptionDisableFullscreenWarpEffects | Disable fullscreen screen-warping effects | Accessibility | Checkbox | No |  |
| 53 | OptionModernUI | Enable modern UI | UI | Checkbox | Yes | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 54 | OptionPrereleaseStageScale | UI scale | UI | Combo | auto | Requires: OptionModernUI==Yes, Values: auto,auto x1.25,auto x1.5,.5,.75,1.0,1.25,1.5,2 |
| 55 | OptionModernCharacterSheet | Enable modern UI character sheet | UI | Checkbox | Yes | Requires: OptionModernUI==Yes,OptionShowAdvancedOptions==Yes |
| 56 | OptionCharacterSheetAdditionalScale | Character sheet scale percentage | UI | Slider | 0 | Requires: OptionModernUI==Yes,OptionModernCharacterSheet==Yes,OptionShowAdvancedOptions==Yes, Min: -50, Max: 50, Increment: 1 |
| 57 | OptionPlayScale | Play area scale | UI | Combo | Cover | Requires: OptionModernUI==Yes, Values: Fit,Cover,Pixel Perfect, SearchKeywords: Fit Cover Pixel Perfect |
| 66 | OptionTileScale | Pixel perfect tile graphic scale | UI | Combo | 1 | Requires: OptionModernUI==Yes,OptionPlayScale==Pixel Perfect, Values: 1,2,3,4,5,6,7,8 |
| 67 | OptionAbilityBarMode | Ability bar mode | UI | Combo | Full | Values: Full,Compact |
| 68 | OptionOverlayMinimap | Show minimap | UI | Checkbox | No | Requires: OptionModernUI==Yes |
| 69 | OptionOverlayNearbyObjects | Show nearby objects list | UI | Checkbox | No | Requires: OptionModernUI==Yes |
| 70 | OptionOverlayNearbyObjectsLocal | Nearby objects list: show only current cell's contents | UI | Checkbox | No | Requires: OptionModernUI==Yes,OptionOverlayNearbyObjects==Yes,OptionShowAdvancedOptions==Yes |
| 71 | OptionOverlayNearbyObjectsPools | Nearby objects list: show liquid pools | UI | Checkbox | No | Requires: OptionModernUI==Yes,OptionOverlayNearbyObjects==Yes,OptionShowAdvancedOptions==Yes |
| 72 | OptionOverlayNearbyObjectsPlants | Nearby objects list: show plants | UI | Checkbox | No | Requires: OptionModernUI==Yes,OptionOverlayNearbyObjects==Yes,OptionShowAdvancedOptions==Yes |
| 73 | OptionOverlayNearbyObjectsTakeable | Nearby objects list: show only show takeable objects | UI | Checkbox | No | Requires: OptionModernUI==Yes,OptionOverlayNearbyObjects==Yes,OptionShowAdvancedOptions==Yes |
| 74 | OptionMessageLineLogScale | Message log font size (pt) | UI | Slider | 0 | Requires: OptionModernUI==Yes, Min: -12, Max: 24, Increment: 1 |
| 75 | OptionDockMovable | Dock message log &amp;&amp; minimap | UI | Combo | Right | Requires: OptionModernUI==Yes,OptionShowAdvancedOptions==Yes, Values: Unset,Right,Left,Flip |
| 76 | OptionDockOpacity | Dock background opacity | UI | Slider | 100 | Requires: OptionModernUI==Yes,OptionDockMovable!=Unset, Min: 0, Max: 100, Increment: 10 |
| 77 | OptionMouseCursor | Mouse cursor appearance | UI | Combo | Default | RequiresCapability: Mouse, Requires: OptionModernUI==Yes, Values: System,Default,Alternate |
| 78 | OptionMouseAutoHideCursorEnabled | Automatically hide mouse cursor when inactive | UI | Checkbox | Yes | RequiresCapability: Mouse, Requires: OptionModernUI==Yes,OptionShowAdvancedOptions==Yes |
| 79 | OptionControllerFont | Gamepad button appearance | UI | Combo | Auto | RequiresCapability: IsDesktop, Requires: OptionModernUI==Yes, Values: Auto,KBM,XBox,PS,XBox Filled,PS Filled,Switch |
| 80 | OptionFloatingKeyboard | Display overlay keyboard for input on supported devices | UI | Checkbox | Yes | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 81 | OptionZoomSensitivity | Zoom sensitivity | UI | Slider | 1 | Requires: OptionModernUI==Yes,OptionShowAdvancedOptions==Yes, Min: 1, Max: 25, Increment: 1 |
| 82 | OptionTooltipDelay | Tooltip delay (ms) | UI | Slider | 1000 | Min: 0, Max: 3000, Increment: 100 |
| 83 | Option@HPColor | Color your character's glyph based on health status | UI | Checkbox | Yes |  |
| 84 | Option@AlwaysHPColor | Ignore all effects that recolor your character's glyph other than health status | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 85 | Option@MutationColor | Allow mutations to recolor your character's glyph | UI | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 86 | OptionDisplayMousableZoneTransitionBorder | Display mouse-clickable zone transition arrows | UI | Checkbox | Yes | Requires: OptionModernUI==Yes,OptionShowAdvancedOptions==Yes |
| 87 | OptionShiftHidesSidebar | Pressing shift hides the sidebar | UI | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 88 | OptionAllowFramelessZoomOut | When zoomed out to max zoom, remove the UI frame from the main gameplay screen | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 89 | OptionHighlightStairs | Always highlight stairs | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 90 | OptionLogTurnSeparator | Add a line separator at the end of each round during combat | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 91 | OptionIndentBodyParts | Indent body parts by attachment on the Equipment screen | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 92 | OptionShowDetailedWeaponStats | Display detailed weapon penetration and damage in weapon names | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 93 | OptionTakeallCorpses | Take corpses when using the 'take all' command | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 94 | OptionDropAll | Enable a 'drop all' interaction on items in your inventory | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 95 | OptionNavigateInventoryAndEquipmentWithPagination | Navigate inventory and equipment panes with left/right pagination instead of movement binds | UI | Checkbox | No | Requires: OptionModernUI==Yes,OptionShowAdvancedOptions==Yes |
| 96 | OptionPressingRightInInventoryEquips | Equip/unequip highlighted item when pressing right or left, respectively, on the Equipment screen | UI | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes,OptionNavigateInventoryAndEquipmentWithPagination==Yes |
| 97 | OptionExpandHighlightedInventoryAndEquipmentPane | Expand the equipment or inventory pane when focused | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 98 | OptionStatusScreenSize | Character sheet size | UI | Combo | Standard | Values: Standard,Full Height,Full |
| 99 | OptionTutorialComplete | Move tutorial to the end of the game mode list | UI | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 100 | OptionShowCollectionBadges | Show collector's seals on the main menu | UI | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 102 | OptionShowSidebarAbilities | Display ability icons on the sidebar | Legacy UI | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes,OptionModernUI==No |
| 103 | OptionShowCurrentCellPopup | Display contents of current cell in a popup | Legacy UI | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes,OptionModernUI==No |
| 104 | OptionShowMonsterHPHearts | Color hit hearts per the target's remaining HP | Legacy UI | Checkbox | No | Requires: OptionModernUI!=Yes,OptionShowAdvancedOptions==Yes |
| 105 | OptionShowNumberOfItems | Show number of items in each inventory category | Legacy UI | Checkbox | No | Requires: OptionModernUI!=Yes,OptionShowAdvancedOptions==Yes |
| 106 | OptionLocationIntseadOfName | Display location instead of name on the sidebar | Legacy UI | Checkbox | No | Requires: OptionModernUI!=Yes,OptionShowAdvancedOptions==Yes |
| 107 | OptionMapDirectionsToKeypad | Always map directions to numpad | Legacy UI | Checkbox | Yes | RequiresCapability: HardwareKeyboard, Requires: OptionShowAdvancedOptions==Yes |
| 108 | OptionMapShiftDirectionToPage | Map Shift+directions to menu pagination binds (doesn't work for numpad bindings) | Legacy UI | Checkbox | No | RequiresCapability: HardwareKeyboard, Requires: OptionShowAdvancedOptions==Yes |
| 109 | OptionPushAZHotkeys | Always pass A-Z hotkeys through to the legacy UI | Legacy UI | Checkbox | No | RequiresCapability: HardwareKeyboard, Requires: OptionShowAdvancedOptions==Yes,OptionModernUI==No |
| 112 | OptionAutoexploreMode | Autoexplore Mode | Automation | Combo | Standard | Requires: OptionShowAdvancedOptions==Yes, Values: Standard,Performance |
| 113 | OptionAutoSip | Automatically drink fresh water when thirsty | Automation | Checkbox | Yes |  |
| 114 | OptionAutoSipLevel | Thirst threshold for automatic drinking | Automation | Combo | Thirsty | Requires: OptionAutoSip==Yes, Values: Dehydrated,Parched,Thirsty,Quenched,Tumescent |
| 115 | OptionAutoTorch | Automatically douse and light torches | Automation | Checkbox | Yes |  |
| 116 | OptionAutoDisassembleScrap | Automatically disassemble scrap | Automation | Checkbox | No |  |
| 117 | OptionAutoexploreIgnoreEasyEnemies | Difficulty threshold for ignoring hostile creatures | Automation | Combo | None | Values: None,Easy,Average,Tough,Very Tough,Impossible |
| 118 | OptionAutoexploreIgnoreDistantEnemies | Range threshold for ignoring hostile creatures | Automation | Combo | None | Requires: OptionShowAdvancedOptions==Yes, Values: None,1,2,3,5,7,10,15,20,30,40 |
| 119 | OptionAutoexploreAttackIgnoredAdjacentEnemies | Attack ignored hostiles that you move adjacent to during autoexplore | Automation | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 120 | OptionInterruptHeldMovement | Interrupt held movement when hostiles are nearby | Automation | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 121 | OptionInterruptHeldMovementOnZoneTransition | Interrupt held movement when entering an unexplored zone | Automation | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 122 | OptionUseTextAutowalkThreatIndicator | Use text autoact interrupt indicator instead of flashing red box | Automation | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 123 | OptionAutoexploreChests | Search containers while autoexploring | Automation | Checkbox | Yes |  |
| 124 | OptionDigOnMove | Automatically dig through walls by moving into them when wielding a digging implement | Automation | Checkbox | Yes |  |
| 125 | OptionAutosaveInterval | Automatically save when moving to a different zone | Automation | Combo | 5 | Requires: OptionShowAdvancedOptions==Yes, Values: 0\|None,1,2,3,5,7,10,15,20,30,40 |
| 126 | OptionAutoexploreRate | Maximum automove cells/sec and autoattack actions/sec | Automation | Combo | 20 | Requires: OptionShowAdvancedOptions==Yes, SearchKeywords: autoact autoexplore framerate, Values: 1,2,3,5,7,10,15,20,30,60,0\|&#236; |
| 129 | OptionAutogetAmmo | Autoget ammo | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 130 | OptionAutogetPrimitiveAmmo | Autoget primitive ammo | Autoget | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 131 | OptionAutogetNuggets | Autoget copper, silver, and gold nuggets | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 132 | OptionAutogetTradeGoods | Autoget trade goods | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 133 | OptionAutogetFood | Autoget food | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 134 | OptionAutogetFreshWater | Autoget fresh water | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 135 | OptionAutogetDroppedLiquid | Autoget liquids from containers you've dropped | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 136 | OptionAutogetSpecialItems | Autoget special items | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 137 | OptionAutogetArtifacts | Autoget artifacts | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 138 | OptionAutogetScrap | Autoget scrap | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 139 | OptionAutogetBooks | Autoget books | Autoget | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 140 | OptionAutogetZeroWeight | Autoget weightless items | Autoget | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 141 | OptionAutogetIfHostiles | Autoget if hostiles are nearby | Autoget | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 142 | OptionAutogetFromNearby | Autoget from adjacent cells | Autoget | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 145 | OptionAskForWorldmap | Prompt before moving to the world map | Prompts | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 146 | OptionAskAutostair | Prompt before autowalking to stairs | Prompts | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 147 | OptionConfirmSwimming | Prompt before swimming | Prompts | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 148 | OptionConfirmDangerousLiquid | Prompt before drinking and moving into certain dangerous liquids | Prompts | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 149 | OptionAskForOneItem | Prompt list of items when getting from the ground, even if there's only one | Prompts | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 150 | OptionDisplayHPWarning | Threshold for low hitpoint warning | Prompts | Combo | 40% | Requires: OptionShowAdvancedOptions==Yes, Values: 20%,40%,60%,80%,100%,No Warning |
| 151 | OptionDismemberAsPopup | Show popups when you dismember or decapitate someone | Prompts | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 152 | OptionAbilityCooldownWarningAsMessage | Show ability-on-cooldown prompts as message log entries instead of popups | Prompts | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 153 | OptionShowScavengeItemAsMessage | Show scavenged items as message log entries instead of popups | Prompts | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 154 | OptionPopupJournalNote | Display popups when noting information in your journal | Prompts | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 155 | OptionDisplayLedLevelUp | Display verbose level up messages for companions | Prompts | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 156 | OptionDefaultDeathToViewFinalMessages | Default the selection on death prompts in Roleplay mode to 'View final messages' instead of 'Reload checkpoint' | Prompts | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 159 | OptionEnableMods | Enable mods | Mods | Checkbox | Yes | RequiresCapability: Mods, Restart: true |
| 160 | OptionAllowCSMods | Allow scripting mods (scripting mods may contain malicious code!) | Mods | Checkbox | No | RequiresCapability: Mods, Requires: OptionEnableMods==Yes |
| 161 | OptionOutputModAssembly | Write compiled mod assemblies to disk | Mods | Checkbox | Yes | Requires: OptionEnableMods==Yes,OptionAllowCSMods==Yes,OptionShowAdvancedOptions==Yes |
| 162 | OptionHarmonyDebug | Enable Harmony debug output | Mods | Checkbox | No | Requires: OptionEnableMods==Yes,OptionAllowCSMods==Yes,OptionShowAdvancedOptions==Yes |
| 163 | OptionTextBuilderDebug | Enable Text Builder leak analyzation | Mods | Checkbox | No | Requires: OptionEnableMods==Yes,OptionAllowCSMods==Yes,OptionShowAdvancedOptions==Yes |
| 171 | OptionCheckMemory | Check memory usage and show a warning when it's high | Performance | Checkbox | Yes | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 172 | OptionCacheEarly | Flush zones to cache early (for low memory environments) | Performance | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 173 | OptionCollectEarly | Garbage collect after each zone flush (for low memory environments) | Performance | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 174 | OptionDisableFloorTextureObjects | Do not generate floor texture objects | Performance | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 175 | OptionThrottleAnimation | Throttle animations (for low CPU environments) | Performance | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 176 | OptionDrawStepImmediately | Render a frame immediately after moving (for low CPU environments) | Performance | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 179 | OptionShowAdvancedOptions | Show advanced options | App Settings | Checkbox | No |  |
| 180 | OptionMusicBackground | Keep Caves of Qud active in background | App Settings | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 181 | OptionSessionBackups | Number of rolling backup saves | App Settings | Combo | 3 | RequiresCapability: UnlimitedStorage, Requires: OptionShowAdvancedOptions==Yes, Values: None,1,2,3,5,7,10,15,20,30,40 |
| 186 | OptionAnalytics | Send anonymous gameplay statistics | App Settings | Checkbox | Yes | RequiresCapability: Analytics |
| 187 | OptionDisableSteamInputWarning | Disable input warning | App Settings | Checkbox | No | RequiresCapability: SteamInput, Requires: OptionModernUI==Yes,OptionShowAdvancedOptions==Yes |
| 190 | OptionDisablePermadeath | Don't delete Classic mode saved games on death | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 191 | OptionAllowSaveLoad | Enable save and load | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 192 | OptionAllowReallydie | Get prompted to confirm deaths | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 193 | OptionEnableSeed | Enable world seeds (experimental) | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 194 | OptionEnablePrereleaseContent | Enable unfinished and unsupported content | Debug | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes, Restart: true |
| 195 | OptionDisableDefectLimit | Allow creatures to have multiple defects  | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 196 | OptionStripUIColorText | Strip color formatting from UI text | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 197 | OptionEnableColorTextInput | Enable color menu for text input | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 198 | OptionDisableAchievements | Disable achievements | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 199 | OptionShowQuickstart | Show quickstart option during character creation | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 200 | OptionDisablePlayerbrain | Disable brain hijacking on player-controlled characters | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 201 | OptionDisableZoneCaching2 | Disable zone caching | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 202 | OptionDisableZoneThawRestrict | Disable zone thaw restrictions | Debug | Checkbox | Yes | Requires: OptionShowAdvancedOptions==Yes |
| 208 | OptionDisableTryLimit | Disable limit on zone build tries | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 209 | OptionEnableWishRegionNames | Pregenerate zone names for wish support | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 210 | OptionGivesRepShowsCurrentRep | Show reputation with a creature's factions when looking at them | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 211 | OptionDebugShowConversationNode | Show XML conversation and node names during conversation | Debug | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 212 | OptionDebugShowFullZoneDuringBuild | Show the full zone ID during zone creation | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 213 | OptionDebugDamagePenetrations | Show damage penetration debug text | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 214 | OptionDebugSavingThrows | Show saving throw debug text | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 215 | OptionDebugGetLostChance | Show lost chance debug text | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 216 | OptionDebugStatShift | Show debug text for stat shifts | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 217 | OptionDebugEncounterChance | Show encounter chance debug chance | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 218 | OptionDebugTravelSpeed | Show travel speed debug text | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 219 | OptionDebugInternals | Show debug info on objects | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 220 | OptionDebugAttitude | Show attitude info on objects | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 221 | OptionShowOverlandEncounters | Indicate special encounters on the worldmap | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 222 | OptionShowOverlandRegions | Indicate biomes on the worldmap | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 223 | OptionDrawPopulationHintMaps | Draw population placement hint maps when building zones | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 224 | OptionDrawInfluenceMaps | Draw population placement regions when building zones | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 225 | OptionDrawPathfinder | Draw creature pathfinding  | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 226 | OptionDrawPathfinderHalt | Wait for keypress when drawing pathfinding | Debug | Checkbox | No | RequiresCapability: Mouse, Requires: OptionShowAdvancedOptions==Yes |
| 227 | OptionDrawNavigationWeightMaps | Draw navigation weight maps on each step | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 228 | OptionDrawCASystems | Draw cellular automata when used in map generation | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 229 | OptionShowReachable | Draw reachability maps on zone generation | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 230 | OptionDrawZoneSemantics | Draw semantic tag info when building zones | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 231 | OptionDrawFloodVis | Draw visibility flood fill | Debug | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 232 | OptionDrawFloodAud | Draw audibility flood fill | Debug | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 233 | OptionDrawFloodOlf | Draw olfaction flood fill | Debug | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 234 | OptionDrawFloodExplore | Draw autoexplore flood fill | Debug | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 235 | OptionDrawArcs | Draw electrical arc history for last few rounds | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 236 | OptionWriteSoundsToLog | Write played sound file names to message log | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 237 | OptionDisableSoundPreload | Disable preloading of sounds | Debug | Checkbox | Yes | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 238 | OptionInventoryConsistencyCheck | Perform inventory consistency checks | Debug | Checkbox | No | Requires: OptionShowAdvancedOptions==Yes |
| 239 | OptionShowErrorPopups | Show error popups | Debug | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 240 | OptionDisableBindConflictChecking | Disable conflict checking when rebinding controls | Debug | Checkbox | No | RequiresCapability: IsDesktop, Requires: OptionShowAdvancedOptions==Yes |
| 241 | OptionBugDeckKeyboardShift | Enable workaround for Steam Deck shift key bug | Debug | Checkbox | No | RequiresCapability: IsDesktop |
