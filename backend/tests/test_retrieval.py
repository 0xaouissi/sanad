import uuid

from app.rag.retrieval import rrf_fuse


def test_item_in_both_lists_beats_single_list_items() -> None:
    shared, dense_only, keyword_only = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = rrf_fuse([[dense_only, shared], [keyword_only, shared]])
    assert fused[shared] > fused[dense_only]
    assert fused[shared] > fused[keyword_only]


def test_higher_rank_scores_higher() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    fused = rrf_fuse([[first, second]])
    assert fused[first] > fused[second]


def test_empty_rankings() -> None:
    assert rrf_fuse([]) == {}
    assert rrf_fuse([[], []]) == {}


def test_duplicate_within_one_list_counts_once_per_position() -> None:
    chunk = uuid.uuid4()
    fused = rrf_fuse([[chunk, chunk]])
    assert fused[chunk] == 1.0 / 61 + 1.0 / 62