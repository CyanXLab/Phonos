"""
预设句子、音素数据、发音问题解决方法
"""

# 10个预设练习句子
PRESET_SENTENCES = [
    {
        "id": 1,
        "text": "The weather is beautiful today",
        "difficulty": "easy",
        "category": "daily",
    },
    {
        "id": 2,
        "text": "I would like a cup of coffee please",
        "difficulty": "easy",
        "category": "daily",
    },
    {
        "id": 3,
        "text": "She sells seashells by the seashore",
        "difficulty": "hard",
        "category": "tongue_twister",
    },
    {
        "id": 4,
        "text": "How are you doing this morning",
        "difficulty": "easy",
        "category": "greeting",
    },
    {
        "id": 5,
        "text": "The children are playing in the garden",
        "difficulty": "medium",
        "category": "daily",
    },
    {
        "id": 6,
        "text": "Can you help me find my way",
        "difficulty": "easy",
        "category": "daily",
    },
    {
        "id": 7,
        "text": "I enjoy reading books in the evening",
        "difficulty": "medium",
        "category": "daily",
    },
    {
        "id": 8,
        "text": "The restaurant serves delicious food",
        "difficulty": "medium",
        "category": "daily",
    },
    {
        "id": 9,
        "text": "We went to the park yesterday",
        "difficulty": "easy",
        "category": "daily",
    },
    {
        "id": 10,
        "text": "Learning English takes time and practice",
        "difficulty": "medium",
        "category": "education",
    },
]

# ARPAbet 音素分类
PHONEME_CATEGORIES = {
    "vowels": {
        "short": ["AA", "AE", "AH", "EH", "IH", "UH"],
        "long": ["AY", "AW", "EY", "OW", "OY", "IY", "UW"],
        "r_colored": ["ER"],
    },
    "consonants": {
        "stops": ["B", "D", "G", "K", "P", "T"],
        "fricatives": ["F", "S", "SH", "TH", "V", "Z", "ZH", "DH"],
        "affricates": ["CH", "JH"],
        "nasals": ["M", "N", "NG"],
        "liquids": ["L", "R"],
        "glides": ["W", "Y"],
        "aspirate": ["HH"],
    },
}

# 音素相似度矩阵（同组音素替换惩罚更低）
# 构建音素组映射
PHONEME_GROUP = {}
for group_name, subgroups in PHONEME_CATEGORIES.items():
    for sub_name, phonemes in subgroups.items():
        for p in phonemes:
            PHONEME_GROUP[p] = (group_name, sub_name)

# 音素发音错误常见问题及解决方法
PHONEME_TIPS = {
    # === 元音 ===
    "AA": {
        "description": "开口后元音，如 fAther 中的 a",
        "common_error": "容易发成 /AE/ 或 /AH/，嘴巴张得不够大",
        "solution": "嘴巴张大，舌头放低靠后，像打哈欠时的口型。发 'ah' 音，保持嘴型稳定。",
        "mouth_shape": "口腔大开，舌后缩",
    },
    "AE": {
        "description": "开前元音，如 cAt 中的 a",
        "common_error": "容易发成 /AA/ 或 /EH/，嘴型偏圆或偏窄",
        "solution": "嘴巴张开但比 /AA/ 略窄，嘴角稍向两侧拉开，像微笑时的口型。发介于 'a' 和 'e' 之间的音。",
        "mouth_shape": "口腔半开，舌前部稍抬",
    },
    "AH": {
        "description": "中央元音，如 abOut 中的 u",
        "common_error": "容易发成 /AA/ 或 /UH/，口型过于极端",
        "solution": "嘴巴自然放松，舌头处于中间位置，发出最自然的 'uh' 音。这是英语中最常见的元音。",
        "mouth_shape": "口腔自然，舌位居中",
    },
    "AW": {
        "description": "双元音，如 hOW 中的 ow",
        "common_error": "滑动不够，或起始音偏错",
        "solution": "从 /AA/ 滑向 /UW/，嘴巴从大开到渐圆。注意两个音的平滑过渡。",
        "mouth_shape": "从大开到圆唇",
    },
    "AY": {
        "description": "双元音，如 bIte 中的 i",
        "common_error": "滑动不够或发成单元音 /AA/",
        "solution": "从 /AA/ 滑向 /IY/，下巴从低到高，嘴角从开到合。感受下巴明显上抬。",
        "mouth_shape": "从大开到扁唇",
    },
    "EH": {
        "description": "半开前元音，如 bEd 中的 e",
        "common_error": "容易发成 /AE/ 或 /IH/，嘴巴张得过大或过小",
        "solution": "嘴巴半开，嘴角微展，比 /AE/ 窄但比 /IH/ 宽。发短促的 'eh' 音。",
        "mouth_shape": "口腔半开，舌前部微抬",
    },
    "ER": {
        "description": "卷舌元音，如 bIRd 中的 ir",
        "common_error": "不卷舌或过度卷舌，或发成 /AH/",
        "solution": "舌尖微微上翘（不接触上颚），嘴唇微圆。这是美式英语的标志音。注意不要过度卷舌。",
        "mouth_shape": "舌微卷，唇微圆",
    },
    "EY": {
        "description": "双元音，如 dAY 中的 ay",
        "common_error": "滑动不够或发成单元音",
        "solution": "从 /EH/ 滑向 /IY/，嘴巴从半开到合拢。确保有明显的滑动感。",
        "mouth_shape": "从半开到扁唇",
    },
    "IH": {
        "description": "闭前元音，如 bIt 中的 i",
        "common_error": "容易发成 /IY/（过长）或 /EH/",
        "solution": "嘴巴微开，嘴角微展，发短促的 'ih' 音。注意不要拖长，与 /IY/ 区分开。",
        "mouth_shape": "口腔微开，舌前部较高",
    },
    "IY": {
        "description": "闭前长元音，如 sEE 中的 ee",
        "common_error": "不够长或嘴型不够扁，或发成 /IH/",
        "solution": "嘴角向两侧拉展，舌尖抵下齿，发长音 'ee'。保持口型稳定，音要持续足够长。",
        "mouth_shape": "扁唇，舌前部高抬",
    },
    "OW": {
        "description": "双元音，如 gO 中的 o",
        "common_error": "滑动不够或发成单元音",
        "solution": "从 /AH/ 滑向 /UW/，嘴唇从自然到圆。注意滑动过程要明显。",
        "mouth_shape": "从自然到圆唇",
    },
    "OY": {
        "description": "双元音，如 bOY 中的 oy",
        "common_error": "起始音偏错或滑动不够",
        "solution": "从 /OW/ 滑向 /IY/，嘴巴从圆到扁。两个音的过渡要自然流畅。",
        "mouth_shape": "从圆唇到扁唇",
    },
    "UH": {
        "description": "闭后元音，如 bOOk 中的 oo",
        "common_error": "容易发成 /UW/（太紧）或 /AH/",
        "solution": "嘴唇微圆但不过度紧张，发短促的 'uh' 音。比 /UW/ 更放松、更短。",
        "mouth_shape": "唇微圆，舌后部微抬",
    },
    "UW": {
        "description": "闭后长元音，如 fOOd 中的 oo",
        "common_error": "不够圆唇或不够长，或发成 /UH/",
        "solution": "嘴唇前伸成小圆形，舌尖远离牙齿，发长音 'oo'。保持圆唇和音长。",
        "mouth_shape": "唇前突成圆形，舌后部高抬",
    },
    # === 辅音 - 塞音 ===
    "B": {
        "description": "浊双唇塞音，如 Ba",
        "common_error": "容易与 /P/ 混淆，没有声带振动",
        "solution": "双唇紧闭后突然打开，同时声带振动。把手放在喉咙上感受振动。与 /P/ 的区别在于声带是否振动。",
        "mouth_shape": "双唇紧闭后爆破",
    },
    "D": {
        "description": "浊齿龈塞音，如 Da",
        "common_error": "容易与 /T/ 混淆，或位置偏前/偏后",
        "solution": "舌尖抵住上齿龈后突然放开，声带振动。注意舌尖位置要准确在上齿龈。",
        "mouth_shape": "舌尖抵上齿龈后爆破",
    },
    "G": {
        "description": "浊软腭塞音，如 Go",
        "common_error": "容易与 /K/ 混淆，或发成 /D/",
        "solution": "舌后部抵住软腭后突然放开，声带振动。感受舌根与软腭的接触。",
        "mouth_shape": "舌后部抵软腭后爆破",
    },
    "K": {
        "description": "清软腭塞音，如 Kit",
        "common_error": "容易与 /G/ 混淆（浊化），或发成 /T/",
        "solution": "舌后部抵住软腭后突然放开，声带不振动。送气要明显，尤其在词首时。",
        "mouth_shape": "舌后部抵软腭后爆破送气",
    },
    "P": {
        "description": "清双唇塞音，如 Pan",
        "common_error": "容易与 /B/ 混淆（浊化），送气不够",
        "solution": "双唇紧闭后突然打开，声带不振动，要有明显送气。把手放在嘴前感受气流。",
        "mouth_shape": "双唇紧闭后爆破送气",
    },
    "T": {
        "description": "清齿龈塞音，如 Tan",
        "common_error": "容易与 /D/ 混淆（浊化），或在元音间浊化",
        "solution": "舌尖抵住上齿龈后突然放开，声带不振动，送气明显。词首要强送气。",
        "mouth_shape": "舌尖抵上齿龈后爆破送气",
    },
    # === 辅音 - 擦音 ===
    "F": {
        "description": "清唇齿擦音，如 Fan",
        "common_error": "容易与 /V/ 混淆（浊化），或上齿没有接触下唇",
        "solution": "上齿轻咬下唇，气流从缝隙中摩擦而出，声带不振动。确认上齿确实接触下唇内侧。",
        "mouth_shape": "上齿咬下唇，气流摩擦",
    },
    "V": {
        "description": "浊唇齿擦音，如 Van",
        "common_error": "容易与 /F/ 混淆（没有声带振动），或发成 /W/",
        "solution": "上齿轻咬下唇，气流从缝隙中摩擦而出，声带振动。把手放在喉咙上感受振动。",
        "mouth_shape": "上齿咬下唇，声带振动",
    },
    "S": {
        "description": "清齿龈擦音，如 See",
        "common_error": "容易与 /Z/ 混淆（浊化），或与 /SH/ 混淆",
        "solution": "舌尖靠近上齿龈（不接触），气流从窄缝中嘶嘶而出。保持笑容口型，声音尖锐清脆。",
        "mouth_shape": "嘴角展开，舌尖近上齿龈",
    },
    "Z": {
        "description": "浊齿龈擦音，如 Zoo",
        "common_error": "容易与 /S/ 混淆（没有声带振动），或发成 /DH/",
        "solution": "口型与 /S/ 相同，但声带振动发出 'zzz' 蜂鸣声。像蜜蜂嗡嗡叫。",
        "mouth_shape": "嘴角展开，声带振动",
    },
    "SH": {
        "description": "清齿龈后擦音，如 She",
        "common_error": "容易与 /S/ 混淆，或与 /CH/ 混淆",
        "solution": "嘴唇前突圆起，舌尖接近硬腭前部，发出 'sh' 嘘声。像让人安静时的声音。",
        "mouth_shape": "唇前突圆起，舌近硬腭",
    },
    "ZH": {
        "description": "浊齿龈后擦音，如 viSion",
        "common_error": "容易与 /SH/ 混淆（没有声带振动），或与 /Z/ 混淆",
        "solution": "口型与 /SH/ 相同，但声带振动。像法语中的 'j' 音。声带振动产生蜂鸣感。",
        "mouth_shape": "唇前突圆起，声带振动",
    },
    "TH": {
        "description": "清齿擦音，如 Think",
        "common_error": "最常见的错误！用 /S/、/T/ 或 /F/ 代替",
        "solution": "舌尖伸出上下齿之间（咬舌音），气流从舌齿间吹出。关键：舌尖一定要伸出牙齿外！对着镜子看舌头。",
        "mouth_shape": "舌尖伸出齿间，气流通过",
    },
    "DH": {
        "description": "浊齿擦音，如 THis",
        "common_error": "最常见的错误！用 /Z/、/D/ 或 /V/ 代替",
        "solution": "舌尖伸出上下齿之间，声带振动。与 /TH/ 口型相同但声带振动。'this' 不是 'zis' 或 'dis'。",
        "mouth_shape": "舌尖伸出齿间，声带振动",
    },
    # === 辅音 - 塞擦音 ===
    "CH": {
        "description": "清齿龈后塞擦音，如 CHin",
        "common_error": "容易与 /SH/ 或 /JH/ 混淆",
        "solution": "先做成 /T/ 的口型，然后释放为 /SH/。先阻塞后摩擦，是一个组合音。",
        "mouth_shape": "舌尖抵上齿龈，然后释放为 /SH/",
    },
    "JH": {
        "description": "浊齿龈后塞擦音，如 Jump",
        "common_error": "容易与 /CH/ 混淆（没有声带振动）或 /ZH/ 混淆",
        "solution": "先做成 /D/ 的口型，然后释放为 /ZH/。与 /CH/ 口型相同但声带振动。",
        "mouth_shape": "舌尖抵上齿龈，声带振动释放",
    },
    # === 辅音 - 鼻音 ===
    "M": {
        "description": "双唇鼻音，如 Man",
        "common_error": "闭唇不够紧，或发音时间不够长",
        "solution": "双唇紧闭，气流从鼻腔出来，声带振动。闭嘴时哼 'mmm' 音。",
        "mouth_shape": "双唇紧闭，气流从鼻出",
    },
    "N": {
        "description": "齿龈鼻音，如 No",
        "common_error": "容易与 /NG/ 混淆，尤其在词尾",
        "solution": "舌尖抵住上齿龈，气流从鼻腔出来。注意 /N/ 舌尖在上齿龈，/NG/ 舌根在软腭。",
        "mouth_shape": "舌尖抵上齿龈，鼻音",
    },
    "NG": {
        "description": "软腭鼻音，如 siNG",
        "common_error": "容易与 /N/ 混淆，或在词尾加上 /G/ 音",
        "solution": "舌后部抵住软腭，气流从鼻腔出来。注意词尾的 -ing 不要多发 /G/ 音。'sing' 不是 'sing-g'。",
        "mouth_shape": "舌后部抵软腭，鼻音",
    },
    # === 辅音 - 流音和滑音 ===
    "L": {
        "description": "齿龈边音，如 Light",
        "common_error": "容易与 /R/ 混淆，或词尾的 dark L 发不好",
        "solution": "舌尖抵住上齿龈，气流从舌头两侧流出。词首的 clear L 舌尖用力抵住；词尾的 dark L 舌尖也抵住但舌后部抬起。",
        "mouth_shape": "舌尖抵上齿龈，气流从舌侧出",
    },
    "R": {
        "description": "齿龈通音/卷舌音，如 Run",
        "common_error": "容易与 /L/ 混淆，或过度卷舌",
        "solution": "舌尖向后卷但不接触上颚，嘴唇微圆。注意英语 /R/ 舌尖不颤动，与中文 r 不同。",
        "mouth_shape": "舌尖上卷不触上颚，唇微圆",
    },
    "W": {
        "description": "双唇滑音，如 We",
        "common_error": "容易与 /V/ 混淆，或圆唇不够",
        "solution": "嘴唇紧圆前突，然后迅速滑向后续元音。注意 /W/ 是双唇音，/V/ 是唇齿音。",
        "mouth_shape": "双唇紧圆后滑开",
    },
    "Y": {
        "description": "硬腭滑音，如 Yes",
        "common_error": "发音时间过长变成 /IY/，或舌面抬得不够",
        "solution": "舌面前部抬向硬腭，然后迅速滑向后续元音。是一个短暂的滑音，不要停留。",
        "mouth_shape": "舌面近硬腭后滑开",
    },
    "HH": {
        "description": "声门擦音，如 Hat",
        "common_error": "发音过重变成咳音，或与中文 h 混淆",
        "solution": "轻轻呼气，声带不振动。比中文的 h 更轻柔，只是轻微的气流声。",
        "mouth_shape": "声门轻微打开，气流呼出",
    },
    "DX": {
        "description": "齿龈弹音（美式英语 t 的闪音），如 waTer",
        "common_error": "没有弹舌效果，或发成 /D/",
        "solution": "舌尖快速弹击上齿龈一次，像西班牙语的弹音但只弹一下。美式英语中 t 在元音间常变成此音。",
        "mouth_shape": "舌尖快速弹击上齿龈",
    },
}

# 音素对之间的相似度得分 (0-1, 1=完全相同)
# 用于评分算法中区分"接近的发音错误"和"严重的发音错误"
def _build_similarity_matrix():
    """构建音素相似度矩阵"""
    # 定义音素特征组
    vowel_short = {"AA", "AE", "AH", "EH", "IH", "UH"}
    vowel_long = {"AY", "AW", "EY", "OW", "OY", "IY", "UW"}
    vowel_r = {"ER"}
    stops_voiced = {"B", "D", "G"}
    stops_voiceless = {"P", "T", "K"}
    fricatives_voiced = {"V", "Z", "ZH", "DH"}
    fricatives_voiceless = {"F", "S", "SH", "TH"}
    affricates_voiced = {"JH"}
    affricates_voiceless = {"CH"}
    nasals = {"M", "N", "NG"}
    liquids = {"L", "R"}
    glides = {"W", "Y"}
    aspirate = {"HH"}

    groups = [
        vowel_short, vowel_long, vowel_r,
        stops_voiced, stops_voiceless,
        fricatives_voiced, fricatives_voiceless,
        affricates_voiced, affricates_voiceless,
        nasals, liquids, glides, aspirate,
    ]

    # 同子组内替换（相似错误）
    def get_similarity(p1, p2):
        if p1 == p2:
            return 1.0
        # 清浊对 (如 S/Z, F/V, TH/DH, SH/ZH, CH/JH, T/D, P/B, K/G)
        voiced_pairs = [
            ({"P", "B"}, 0.6),
            ({"T", "D"}, 0.6),
            ({"K", "G"}, 0.6),
            ({"F", "V"}, 0.6),
            ({"S", "Z"}, 0.6),
            ({"SH", "ZH"}, 0.6),
            ({"TH", "DH"}, 0.6),
            ({"CH", "JH"}, 0.6),
        ]
        for pair_set, score in voiced_pairs:
            if p1 in pair_set and p2 in pair_set:
                return score

        # 同子组内
        for group in groups:
            if p1 in group and p2 in group:
                # 同大类（都是元音、都是塞音等）
                return 0.4

        # 同大类不同子组（如短元音和长元音）
        all_vowels = vowel_short | vowel_long | vowel_r
        all_stops = stops_voiced | stops_voiceless
        all_fricatives = fricatives_voiced | fricatives_voiceless
        all_affricates = affricates_voiced | affricates_voiceless
        big_groups = [all_vowels, all_stops, all_fricatives, all_affricates, nasals, liquids | glides]
        for bg in big_groups:
            if p1 in bg and p2 in bg:
                return 0.25

        # 完全不同
        return 0.0

    return get_similarity


SIMILARITY_FUNC = _build_similarity_matrix()
