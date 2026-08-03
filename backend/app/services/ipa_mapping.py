"""IPA → ARPAbet 映射表（用于将 wav2vec2-timit-phoneme 输出转 ARPAbet）。"""

# TIMIT IPA → ARPAbet 映射
IPA_TO_ARPABET = {
    # 元音
    "i": "IY", "iː": "IY",
    "ɪ": "IH",
    "ɛ": "EH",
    "æ": "AE",
    "ɑ": "AA", "ɑː": "AA",
    "ɔ": "AO",
    "ʊ": "UH",
    "u": "UW", "uː": "UW",
    "ʌ": "AH",
    "ə": "AH",
    "ɝ": "ER", "ɚ": "ER", "ɜ": "ER",
    # 双元音
    "aɪ": "AY",
    "aʊ": "AW",
    "ɔɪ": "OY", "ɔɪ": "OY",
    "eɪ": "EY",
    "oʊ": "OW",
    # 辅音 - 塞音
    "p": "P",
    "b": "B",
    "t": "T",
    "d": "D",
    "k": "K",
    "g": "G", "ɡ": "G",
    # 辅音 - 擦音
    "f": "F",
    "v": "V",
    "θ": "TH",
    "ð": "DH",
    "s": "S",
    "z": "Z",
    "ʃ": "SH",
    "ʒ": "ZH",
    "h": "HH",
    # 辅音 - 塞擦音
    "tʃ": "CH",
    "dʒ": "JH",
    "ʧ": "CH",
    "ʤ": "JH",
    "t͡ʃ": "CH",
    "d͡ʒ": "JH",
    # TIMIT 风格
    "tʃ": "CH", "ʤ": "JH",
    # 辅音 - 鼻音
    "m": "M",
    "n": "N",
    "ŋ": "NG",
    # 辅音 - 流音
    "l": "L",
    "ɹ": "R", "r": "R",
    # 辅音 - 滑音
    "w": "W",
    "j": "Y",
    # 弹音
    "ɾ": "DX", " flap": "DX",
    # 特殊
    " ": "|",  # 词边界
    "|": "|",
}


def ipa_to_arpabet(ipa_phonemes: list) -> list:
    """把 IPA 音素列表转换为 ARPAbet 列表。

    无法映射的音素保留原样（标记为 UNK）。
    """
    result = []
    i = 0
    while i < len(ipa_phonemes):
        ph = ipa_phonemes[i]
        # 尝试组合双字符（如 "tʃ", "dʒ", "aɪ"）
        if i + 1 < len(ipa_phonemes):
            two_char = ph + ipa_phonemes[i + 1]
            if two_char in IPA_TO_ARPABET:
                result.append(IPA_TO_ARPABET[two_char])
                i += 2
                continue
        # 单字符
        if ph in IPA_TO_ARPABET:
            arp = IPA_TO_ARPABET[ph]
            if arp != "|":  # 跳过分隔符
                result.append(arp)
        else:
            # 未知音素，跳过特殊 token
            if ph not in ("[PAD]", "[UNK]", "<pad>", "<unk>", "<s>", "</s>"):
                result.append(ph)  # 保留原样
        i += 1
    return result
