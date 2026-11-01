# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import re
import string

import i18n


def _fields(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _tags(text):
    return sorted(re.findall(r"</?(?:b|i|code|a)\b", text))


def test_catalogs_have_identical_keys():
    assert set(i18n._catalog["ar"]) == set(i18n._catalog["en"])


def test_placeholders_and_tags_match_between_languages():
    for key, ar in i18n._catalog["ar"].items():
        en = i18n._catalog["en"][key]
        assert _fields(ar) == _fields(en), key
        assert _tags(ar) == _tags(en), key


def test_no_empty_translations():
    for code in i18n.SUPPORTED:
        for key, text in i18n._catalog[code].items():
            assert text.strip(), (code, key)


def test_english_catalog_has_no_arabic_letters():
    arabic = re.compile("[\u0600-\u06FF]")
    allowed = {"LANG_MENU", "BTN_LANG", "CMD_LANG"}
    for key, text in i18n._catalog["en"].items():
        if key not in allowed:
            assert not arabic.search(text), key


def test_language_switch_is_scoped():
    assert i18n.get_lang() == "ar"
    with i18n.use("en"):
        assert i18n.t("BTN_BACK") == "🔙 Back"
    assert i18n.t("BTN_BACK") == "🔙 رجوع"


def test_guess_and_normalize():
    assert i18n.guess("ar") == "ar"
    assert i18n.guess("ar-IQ") == "ar"
    assert i18n.guess("en-US") == "en"
    assert i18n.guess(None) == i18n.DEFAULT
    assert i18n.normalize("EN") == "en"
    assert i18n.normalize("xx") is None


def test_missing_key_returns_key_and_bad_format_is_safe():
    assert i18n.t("NO_SUCH_KEY") == "NO_SUCH_KEY"
    assert i18n.t("queued") == i18n._catalog["ar"]["queued"]


def test_localized_exception_follows_current_language():
    err = i18n.Localized("PE_HASH_FAILED")
    assert str(err) == i18n._catalog["ar"]["PE_HASH_FAILED"]
    with i18n.use("en"):
        assert str(err) == i18n._catalog["en"]["PE_HASH_FAILED"]
