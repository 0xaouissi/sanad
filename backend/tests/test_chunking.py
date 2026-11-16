"""Chunking: size limits, overlap, metadata."""

from app.rag.chunking import Block, chunk_blocks


def test_short_block_single_chunk():
    chunks = chunk_blocks([Block(text="hello world", page=1)], size=1200, overlap=200)
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].page == 1
    assert chunks[0].index == 0


def test_empty_blocks_skipped():
    assert chunk_blocks([Block(text="   "), Block(text="")], size=100, overlap=10) == []


def test_long_text_split_within_size_plus_overlap():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 80 for i in range(10))
    chunks = chunk_blocks([Block(text=text, page=2)], size=500, overlap=80)
    assert len(chunks) > 1
    assert all(len(c.text) <= 580 for c in chunks)
    assert all(c.page == 2 for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_overlap_carries_words():
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa " * 10
    chunks = chunk_blocks([Block(text=text)], size=120, overlap=30)
    assert len(chunks) > 1
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        tail_words = prev.text.split()[-3:]
        assert any(w in nxt.text.split() for w in tail_words)


def test_no_overlap_across_blocks():
    blocks = [
        Block(text="first page text " * 30, page=1, heading="Intro"),
        Block(text="second page text " * 30, page=2, heading="Details"),
    ]
    chunks = chunk_blocks(blocks, size=150, overlap=40)
    page1 = [c for c in chunks if c.page == 1]
    page2 = [c for c in chunks if c.page == 2]
    assert page1 and page2
    assert all(c.heading == "Intro" for c in page1)
    assert all(c.heading == "Details" for c in page2)
    assert "second" not in page1[-1].text
    assert "first" not in page2[0].text


def test_hard_split_without_separators():
    text = "x" * 1000
    chunks = chunk_blocks([Block(text=text)], size=300, overlap=0)
    assert all(len(c.text) <= 300 for c in chunks)
    assert "".join(c.text for c in chunks) == text


def test_arabic_sentence_separators():
    text = "هذه جملة أولى. هذه جملة ثانية؟ هذه جملة ثالثة! " * 20
    chunks = chunk_blocks([Block(text=text)], size=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c.text) <= 220 for c in chunks)