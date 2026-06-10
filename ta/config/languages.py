from enum import IntEnum


class Language(IntEnum):
    AUTO = 0
    English = 1
    Japanese = 2
    Chinese_Simplified = 3
    Chinese_Traditional = 4
    Dutch = 5
    French = 6
    German = 7
    Greek = 8
    Italian = 9
    Portuguese = 10
    Spanish = 11
    Korean = 12
    Russian = 13
    Afrikaans = 14
    Albanian = 15
    Arabic = 16
    Belarusian = 17
    Bengali = 18
    Bosnian = 19
    Bulgarian = 20
    Catalan = 21
    Castilian = 22
    Croatian = 23
    Czech = 24
    Danish = 25
    Dari = 26
    Esperanto = 27
    Estonian = 28
    Filipino = 29
    Finnish = 30
    Galician = 31
    Haitian_Creole = 32
    Hausa = 33
    Hebrew = 34
    Hindi = 35
    Hmong_Daw = 36
    Hungarian = 37
    Icelandic = 38
    Indonesian = 39
    Irish = 40
    Klingon = 41
    Latin = 42
    Latvian = 43
    Lithuanian = 44
    Macedonian = 45
    Malay = 46
    Maltese = 47
    Norwegian = 48
    Pashto = 49
    Persian = 50
    Polish = 51
    Queretaro_Otomi = 52
    Romanian = 53
    Serbian = 54
    Slovak = 55
    Slovenian = 56
    Somali = 57
    Swahili = 58
    Swedish = 59
    Thai = 60
    Turkish = 61
    Ukrainian = 62
    Urdu = 63
    Vietnamese = 64
    Welsh = 65
    Yiddish = 66
    Yucatec_Maya = 67
    Zulu = 68
    NONE = 69


_NAME_MAP: dict[str, Language] = {lang.name.lower().replace("_", " "): lang for lang in Language}
_NAME_MAP.update({lang.name.lower(): lang for lang in Language})


def from_string(s: str) -> Language:
    key = s.strip().lower()
    if key in _NAME_MAP:
        return _NAME_MAP[key]
    return Language.AUTO


# BCP-47 codes used by Google Translate / most REST APIs
_GOOGLE_CODES: dict[Language, str] = {
    Language.AUTO: "auto",
    Language.English: "en",
    Language.Japanese: "ja",
    Language.Chinese_Simplified: "zh-CN",
    Language.Chinese_Traditional: "zh-TW",
    Language.Dutch: "nl",
    Language.French: "fr",
    Language.German: "de",
    Language.Greek: "el",
    Language.Italian: "it",
    Language.Portuguese: "pt",
    Language.Spanish: "es",
    Language.Korean: "ko",
    Language.Russian: "ru",
    Language.Afrikaans: "af",
    Language.Albanian: "sq",
    Language.Arabic: "ar",
    Language.Belarusian: "be",
    Language.Bengali: "bn",
    Language.Bosnian: "bs",
    Language.Bulgarian: "bg",
    Language.Catalan: "ca",
    Language.Castilian: "es",
    Language.Croatian: "hr",
    Language.Czech: "cs",
    Language.Danish: "da",
    Language.Estonian: "et",
    Language.Filipino: "tl",
    Language.Finnish: "fi",
    Language.Galician: "gl",
    Language.Haitian_Creole: "ht",
    Language.Hebrew: "iw",
    Language.Hindi: "hi",
    Language.Hungarian: "hu",
    Language.Icelandic: "is",
    Language.Indonesian: "id",
    Language.Irish: "ga",
    Language.Latin: "la",
    Language.Latvian: "lv",
    Language.Lithuanian: "lt",
    Language.Macedonian: "mk",
    Language.Malay: "ms",
    Language.Maltese: "mt",
    Language.Norwegian: "no",
    Language.Persian: "fa",
    Language.Polish: "pl",
    Language.Romanian: "ro",
    Language.Serbian: "sr",
    Language.Slovak: "sk",
    Language.Slovenian: "sl",
    Language.Swahili: "sw",
    Language.Swedish: "sv",
    Language.Thai: "th",
    Language.Turkish: "tr",
    Language.Ukrainian: "uk",
    Language.Urdu: "ur",
    Language.Vietnamese: "vi",
    Language.Welsh: "cy",
    Language.Yiddish: "yi",
    Language.Zulu: "zu",
}

# DeepL target language codes
_DEEPL_CODES: dict[Language, str] = {
    Language.English: "EN-US",
    Language.Japanese: "JA",
    Language.Chinese_Simplified: "ZH",
    Language.Chinese_Traditional: "ZH",
    Language.Dutch: "NL",
    Language.French: "FR",
    Language.German: "DE",
    Language.Greek: "EL",
    Language.Italian: "IT",
    Language.Portuguese: "PT-PT",
    Language.Spanish: "ES",
    Language.Korean: "KO",
    Language.Russian: "RU",
    Language.Bulgarian: "BG",
    Language.Czech: "CS",
    Language.Danish: "DA",
    Language.Estonian: "ET",
    Language.Finnish: "FI",
    Language.Hungarian: "HU",
    Language.Indonesian: "ID",
    Language.Latvian: "LV",
    Language.Lithuanian: "LT",
    Language.Norwegian: "NB",
    Language.Polish: "PL",
    Language.Romanian: "RO",
    Language.Slovak: "SK",
    Language.Slovenian: "SL",
    Language.Swedish: "SV",
    Language.Turkish: "TR",
    Language.Ukrainian: "UK",
}


def to_google_code(lang: Language) -> str:
    return _GOOGLE_CODES.get(lang, "")


def to_deepl_code(lang: Language) -> str:
    return _DEEPL_CODES.get(lang, "")


def display_names() -> list[tuple[str, Language]]:
    """Returns list of (display_name, Language) for UI combo boxes."""
    names = []
    for lang in Language:
        if lang == Language.NONE:
            continue
        name = lang.name.replace("_", " ")
        names.append((name, lang))
    return names
