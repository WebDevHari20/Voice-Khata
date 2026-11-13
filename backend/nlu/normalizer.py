import re

PHRASES = {
    "teen sau chaalis": "340", "dhai sau": "250", "sawa sau": "125",
    "paune sau": "75", "paune do sau": "175", "paune teen sau": "275",
    "paune char sau": "375", "paune chaar sau": "375", "derh sau": "150",
    "dedh sau": "150", "dhai hazar": "2500", "dhai hazaar": "2500",
    "derh hazar": "1500", "derh hazaar": "1500", "dedh hazar": "1500",
    "dedh hazaar": "1500", "sawa hazar": "1250", "sawa hazaar": "1250",
    "sava sau": "125", "sava hazar": "1250", "sava hazaar": "1250",
}

ONES = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "ek": 1, "ik": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4,
    "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6, "cheh": 6,
    "saat": 7, "aath": 8, "nau": 9, "das": 10, "gyarah": 11,
    "barah": 12, "terah": 13, "chaudah": 14, "pandrah": 15,
    "solah": 16, "satrah": 17, "atharah": 18, "unnis": 19,
    "unnees": 19, "ikkis": 21, "ikattis": 31, "iktis": 31,
    "bais": 22, "baais": 22, "teis": 23, "teiss": 23,
    "chaubees": 24, "chobees": 24, "pachchees": 25, "pachees": 25,
    "chhabbees": 26, "chabbis": 26, "sattais": 27, "athais": 28,
    "untis": 29, "untees": 29, "battis": 32, "taintees": 33,
    "chautis": 34, "chauntis": 34, "paintis": 35, "paintees": 35,
    "chhattis": 36, "saintis": 37, "adtees": 38, "untalis": 39,
    "untalees": 39, "iktalis": 41, "bayalis": 42, "taitalis": 43,
    "tintalis": 43, "chawalis": 44, "paintalis": 45, "paitalis": 45,
    "chhiyalis": 46, "chiyalis": 46, "saintalis": 47, "adtalis": 48,
    "unchaas": 49, "unchas": 49, "uncalis": 39, "ikyavan": 51, "ikavan": 51,
    "bavan": 52, "baavan": 52, "tirpan": 53, "chauvan": 54,
    "pachpan": 55, "chhappan": 56, "sattavan": 57, "athavan": 58,
    "unsath": 59, "iksath": 61, "baasath": 62, "basath": 62,
    "tirsath": 63, "chaunsath": 64, "painsath": 65, "chhiyasath": 66,
    "sadsath": 67, "adsath": 68, "unhattar": 69, "ikhattar": 71,
    "bahattar": 72, "tihattar": 73, "chauhattar": 74, "pachhattar": 75,
    "chihattar": 76, "satahattar": 77, "athahattar": 78, "unasi": 79,
    "ikyasi": 81, "bayasi": 82, "tirasi": 83, "chaurasi": 84,
    "pachasi": 85, "chhiyasi": 86, "satasi": 87, "athasi": 88,
    "navasi": 89, "ikyanave": 91, "banave": 92, "tiranave": 93,
    "chauranave": 94, "pachanave": 95, "chhiyanave": 96,
    "satanave": 97, "athanave": 98, "ninyanave": 99,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
        "bees": 20, "tees": 30, "tis": 30, "chaalis": 40, "chalis": 40,
        "pachaas": 50, "pachas": 50, "saath": 60, "sath": 60,
        "sattar": 70, "assi": 80, "nabbe": 90}
FRACTIONS = {"dhai": 2.5, "dedh": 1.5, "derh": 1.5, "sawa": 1.25, "sava": 1.25, "paune": 0.75, "pauna": 0.75}
SCALES = {"hundred": 100, "sau": 100, "thousand": 1000, "hazar": 1000,
          "hazaar": 1000, "lakh": 100000, "lac": 100000, "lakhs": 100000,
          "lacs": 100000, "crore": 10000000, "crores": 10000000}
NUMBER_WORDS = set(ONES) | set(TENS) | set(SCALES) | set(FRACTIONS) | {"and"}


def _parse_number_words(words):
    if len(words) > 1 and words[0] in {"sawa", "sava", "paune", "pauna"}:
        remainder = _parse_number_words(words[1:])
        scale = max((SCALES[word] for word in words[1:] if word in SCALES), default=1)
        adjustment = scale * 0.25
        value = remainder + adjustment if words[0] in {"sawa", "sava"} else remainder - adjustment
        return int(value) if value == int(value) else value
    # In casual Indian speech, "three forty" commonly means 340.
    if len(words) == 2 and words[0] in ONES and 1 <= ONES[words[0]] <= 9 and words[1] in TENS:
        return ONES[words[0]] * 100 + TENS[words[1]]
    total = current = 0
    for word in words:
        if word == "and":
            continue
        if word in FRACTIONS:
            current += FRACTIONS[word]
        elif word in ONES:
            current += ONES[word]
        elif word in TENS:
            current += TENS[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word in SCALES:
            scale = SCALES[word]
            total += max(current, 1) * scale
            current = 0
    value = total + current
    return int(value) if value == int(value) else value


def normalize_hindi_numbers(text: str) -> str:
    result = text.lower()
    result = re.sub(r"(?<=\d),(?=\d)", "", result)
    result = re.sub(r"(?<=[a-z])[-–](?=[a-z])", " ", result)
    for phrase, value in sorted(PHRASES.items(), key=lambda pair: -len(pair[0])):
        result = re.sub(rf"\b{re.escape(phrase)}\b", value, result)
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?|[^a-z\d\s]", result)
    output = []
    index = 0
    while index < len(tokens):
        if tokens[index] not in NUMBER_WORDS:
            output.append(tokens[index])
            index += 1
            continue
        end = index
        words = []
        while end < len(tokens) and tokens[end] in NUMBER_WORDS:
            words.append(tokens[end])
            end += 1
        output.append(str(_parse_number_words(words)))
        index = end
    return " ".join(output)
