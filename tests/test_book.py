"""深度读书的拆章逻辑：目录页识别 → 目录解析（部 / 折行标题）→ 书页码到 PDF 页的偏移定位 → 分章与分类。不联网、不调模型。"""
from app.modules import _book as bp

FILLER = "lorem ipsum dolor sit amet " * 80
TOC = """Contents

Preface ............................ 1
Part One: Foundations
Chapter 1: Alpha Things ............ 3
Chapter 2: Beta Stuff and a Very
    long wrapped title ............. 6
Part Two: Applications
Chapter 3: Gamma Rays .............. 9
Index .............................. 12
"""
BODY = {1: "Preface\n", 3: "Chapter 1\nAlpha Things\n", 6: "Chapter 2\nBeta Stuff and a Very long wrapped title\n",
        9: "Chapter 3\nGamma Rays\n", 12: "Index\n"}


def _pages():
    # PDF 第 0 页书名、第 1 页目录，书的第 1 页 = PDF 第 2 页（偏移 +1）
    return ["My Book\nBy Someone", TOC] + [BODY.get(n, "") + FILLER for n in range(1, 15)]


def test_toc_parse_parts_and_wrapped_titles():
    pages = _pages()
    assert bp.toc_pages(pages) == [1]
    ents = bp.parse_toc(pages, [1])
    assert [e["title"] for e in ents] == ["Preface", "Chapter 1: Alpha Things", "Chapter 2: Beta Stuff and a Very long wrapped title",
                                          "Chapter 3: Gamma Rays", "Index"]
    assert [e["num"] for e in ents] == [1, 3, 6, 9, 12]
    assert [e["part"] for e in ents] == ["", "Part One: Foundations", "Part One: Foundations", "Part Two: Applications", "Part Two: Applications"]


def test_locate_offset_and_build_chapters():
    pages = _pages()
    chs = bp.build_chapters(bp.locate(bp.parse_toc(pages, [1]), pages), pages)
    assert [(c["kind"], c["page_start"], c["page_end"]) for c in chs] == [
        ("front", 2, 3), ("chapter", 4, 6), ("chapter", 7, 9), ("chapter", 10, 12), ("matter", 13, 15)]


def test_long_chapter_is_split_under_token_budget():
    pages = ["Chapter 1\nHuge\n" + "word " * 30000] + ["word " * 30000 for _ in range(9)]
    chs = bp.build_chapters([{"title": "Chapter 1: Huge", "page": 0}], pages)
    assert len(chs) > 1 and all(c.get("split") for c in chs)
    for c in chs:
        assert bp.est_tokens("\n".join(pages[c["page_start"]:c["page_end"] + 1])) <= bp.PART_TOKENS


def test_no_toc_falls_back_to_fixed_ranges():
    pages = [FILLER] * 70
    chs = bp.build_chapters([], pages)
    assert chs[0]["page_start"] == 0 and chs[-1]["page_end"] == 69 and len(chs) == 3


def test_est_tokens_counts_cjk_per_char():
    assert bp.est_tokens("深度读书") == 4
    assert bp.est_tokens("abcd" * 10) == 10
