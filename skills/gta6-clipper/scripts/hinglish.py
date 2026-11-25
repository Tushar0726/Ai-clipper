"""Devanagari -> Roman Hinglish (the way people type Hindi in chats: "kya kar raha hai bhai").

Rule-based: consonants carry an inherent "a" that is dropped at the end of a word and, Hindi-style,
in the middle when a vowel+consonant comes before it and a consonant+vowel after it (karana -> karna).
Latin text (English words, numbers) passes through untouched.
"""
import re

V = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai",
     "ओ": "o", "औ": "au", "ऑ": "o", "ॲ": "e"}
M = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
     "ॉ": "o", "ॅ": "e"}
C = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
     "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
     "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
     "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "rh", "फ़": "f",
     "य़": "y"}
NUK = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "rh", "फ": "f"}
HAL, NUKTA = "्", "़"
NAS = {"ं": "n", "ँ": "n", "ः": "h"}
DIG = {chr(0x966 + i): str(i) for i in range(10)}


def _word(w):
    # tokens: (kind, text) kind C = consonant with inherent a, c = bare consonant, v = vowel
    t, i = [], 0
    while i < len(w):
        ch = w[i]
        if ch in C:
            r = C[ch]
            if i + 1 < len(w) and w[i + 1] == NUKTA:
                r = NUK.get(ch, r); i += 1
            if i + 1 < len(w) and w[i + 1] == HAL:
                t.append(["c", r]); i += 2; continue
            if i + 1 < len(w) and w[i + 1] in M:
                t.append(["c", r]); t.append(["v", M[w[i + 1]]]); i += 2; continue
            t.append(["C", r]); i += 1; continue
        if ch in V:
            t.append(["v", V[ch]])
        elif ch in NAS:
            t.append(["n", NAS[ch]])
        elif ch in DIG:
            t.append(["x", DIG[ch]])
        elif ch != NUKTA:
            t.append(["x", ch])
        i += 1
    # schwa deletion: final, and medial V C [a] C V
    kinds = lambda k: [x[0] for x in t[k:k + 1]]
    out = []
    for k, (kind, r) in enumerate(t):
        if kind != "C":
            out.append(r); continue
        nxt = t[k + 1] if k + 1 < len(t) else None
        if nxt is None or nxt[0] == "x":
            out.append(r if k == 0 else r); continue  # word-final: drop a (single-letter words keep it below)
        prev_vowel = k >= 1 and (t[k - 1][0] in "vC" or (t[k - 1][0] == "c" and k >= 2 and t[k - 2][0] == "v"))
        nxt2 = t[k + 2] if k + 2 < len(t) else None
        cv_after = nxt[0] in "Cc" and nxt2 is not None and nxt2[0] == "v" or nxt[0] == "C" and nxt2 is not None
        if k >= 2 and prev_vowel and nxt[0] in "Cc" and cv_after and t[k - 1][0] != "C":
            out.append(r)
        else:
            out.append(r + "a")
    s = "".join(out)
    if len(t) == 1 and t[0][0] == "C":
        s += "a"
    return s


def to_hinglish(text):
    return re.sub(r"[ऀ-ॿ]+", lambda m: _word(m.group(0)), text)


if __name__ == "__main__":
    for s in ["क्या कर रहा है भाई", "करना है", "चलो गाड़ी में बैठो", "मज़ा आ गया", "यार ये तो पागल है", "समझ नहीं आया"]:
        print(s, "->", to_hinglish(s))
