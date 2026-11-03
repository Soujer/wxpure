# -*- coding: utf-8 -*-
"""葵花码固定表（从 wxocr.dll 提取，全部内嵌，无外部依赖）

每套版式由「模板 + 配套掩码」组成，模板里已固化版本/掩码信息，必须配套使用。
"""
import base64, zlib

_B64 = (
    "eNrNWD1v2zAQfQoQdDDgdsyHutmGtg7poJHO5hSwO4RDty715qLuH+j9Ag/e8hc0dYkCBGimAl4M"
    "1ECXAloCeMyQ/IKod6Qc+TNxG3/wIJLn4/np8Z1A0R6UiwQo7KFKuwAKoTqthgrX5TrHgX0cY4fn"
    "PSiqcruTfM45CDxwPhV4juNAxeIcooEXwL1/oX5VL9T9q4rBId/EFY8GB4HkB+r0dVigHZ4f4Q/K"
    "dbkt88nwQ2R8isj5POTjTuKccxAIf5XxAaFicOgQLzM+yPgUx/gAGR9iPkAA5vOOsvUanIG5rxrj"
    "I/qAMn1on9nk+iDTR/h4GR8IjugjOMKHcn0w0od5SFwJH3Nfq4/wKWT4FmeQ3XdKH8uH1Jg+oCoJ"
    "nzo96MPzeb3qotIcfQRf6tQQnjza+wYSt/pgh5TVn8f3sHXZ49XvUl6vj2TXy/oQ58Mjk48vqGNG"
    "H7Oioq0XNWiqXpB1+cT6MIZvcSigeq6Pwbfr1TqKptts5Llt+cy4lWzgqnVLS15aW2ZujVZRF/y4"
    "VaqJnkncLbngn0cn2qWWple3cUt0urp1wR/VLq/hpK17ftrSNOyUalp3S52hC748RfZZcqPXG7Fo"
    "aUs3YljarEp2BxBHdoNcvc3HV/3mfH67uRyGaToMby5d8I+M9Y254I+fB1zwXXvDN5tnZ82mO/11"
    "+qf9Mz7RX5PPvgt+f8yOZqw/Y+vOmbcHnEfba7Pn7e1G3Nh1cn8zv7+Wb7223+sMQ77YccCfp9rq"
    "6/Ev74tPH5LY77WS329d8KVinaH0bT+KpNc67Ei/nXia9tpJrHUrccO3dbNPzeS+uZ14s1n4cfzG"
    "nV7O0N+/2bP0olH+HDPjE3lrx5k6+xM2x0dyFn02fx56kziP5c/97E3y+Z/vP6bPuvg8OXqT+iz9"
    "vVXjLNDHxNfI5y8+lZwF"
)
_BLOB = zlib.decompress(base64.b64decode(_B64))

_N = 5
FIXED  = _BLOB[0:144 * _N]
MASK32 = _BLOB[144 * _N: 144 * _N + 4608]
BMPACK = _BLOB[144 * _N + 4608:]

# (总码字, 数据码字, 配套掩码) —— 按容量从小到大
LAYOUTS = [
    (38, 14, 25),
    (38, 20, 31),
    (38, 25, 25),
    (52, 35, 12),
    (66, 43, 6),
]

_BM_OFF = {38: 0, 52: 288, 66: 576}
_IDX = {(t, k): i for i, (t, k, _m) in enumerate(LAYOUTS)}


def mask_for(total, k):
    return LAYOUTS[_IDX[(total, k)]][2]


def fixed_bit(total, k, slot, ring):
    ti = _IDX[(total, k)]
    i = slot * 16 + ring
    return (FIXED[ti * 144 + (i >> 3)] >> (i & 7)) & 1


def mask_bit(mi, slot, ring):
    i = slot * 16 + ring
    return (MASK32[mi * 144 + (i >> 3)] >> (i & 7)) & 1


def data_words(total):
    off = _BM_OFF[total]
    return [int.from_bytes(BMPACK[off + s*4: off + s*4 + 4], "little") for s in range(72)]
