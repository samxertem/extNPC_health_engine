"""
The testable half of the asset-pack installer.

Downloading 267 MB is not a unit test, and mocking a whole HTTP stack to prove
`urllib` works would test `urllib`. What IS worth testing is the segment
arithmetic, because its failure mode is silent: an HTTP Range request whose
end is past the end of the resource is not an error, the server clamps it, and
the result is a file of exactly the right size with a duplicated tail. Nothing
downstream notices until the zip fails to open, and by then the obvious
suspect is the network.
"""

from __future__ import annotations

import pytest

from mpfb.asset_pack import SEGMENTS, plan_segments, resume_offset

TOTAL = 280_737_770          # the real pack, as reported by the origin


def test_segments_cover_every_byte_exactly_once():
    spans = plan_segments(TOTAL, SEGMENTS)
    covered = sum(end - start + 1 for _, start, end in spans)
    assert covered == TOTAL


def test_segments_do_not_overlap_and_leave_no_gap():
    spans = plan_segments(TOTAL, SEGMENTS)
    expected_next = 0
    for _, start, end in spans:
        assert start == expected_next, "gap or overlap between segments"
        expected_next = end + 1
    assert expected_next == TOTAL


def test_the_last_segment_ends_one_before_the_total():
    # The off-by-one this file exists for. `end == total` would be clamped by
    # the server rather than rejected.
    _, _, end = plan_segments(TOTAL, SEGMENTS)[-1]
    assert end == TOTAL - 1


def test_indices_are_sequential_from_zero():
    spans = plan_segments(TOTAL, SEGMENTS)
    assert [i for i, _, _ in spans] == list(range(len(spans)))


@pytest.mark.parametrize("total,n", [(1, 16), (5, 16), (16, 16), (17, 16),
                                     (100, 3), (280_737_770, 1)])
def test_coverage_holds_for_awkward_sizes(total, n):
    spans = plan_segments(total, n)
    assert sum(end - start + 1 for _, start, end in spans) == total
    assert spans[-1][2] == total - 1


def test_more_segments_than_bytes_does_not_produce_empty_spans():
    # 16 workers over 5 bytes must give at most 5 spans, none of them empty.
    spans = plan_segments(5, 16)
    assert len(spans) <= 5
    for _, start, end in spans:
        assert end >= start


@pytest.mark.parametrize("total,n", [(0, 4), (-1, 4), (100, 0), (100, -2)])
def test_degenerate_arguments_are_rejected(total, n):
    with pytest.raises(ValueError):
        plan_segments(total, n)


def test_a_single_segment_is_the_whole_file():
    spans = plan_segments(TOTAL, 1)
    assert spans == [(0, 0, TOTAL - 1)]


# ----------------------------------------------------------------------
# resuming a partially fetched segment
# ----------------------------------------------------------------------

def test_a_complete_segment_reports_nothing_to_do():
    # end + 1 is the caller's "skip me" signal.
    assert resume_offset(100, 0, 99) == 100


def test_a_partial_segment_resumes_where_it_stopped():
    assert resume_offset(40, 0, 99) == 40
    assert resume_offset(40, 1000, 1099) == 1040


def test_an_untouched_segment_starts_at_the_beginning():
    assert resume_offset(0, 1000, 1099) == 1000


def test_an_oversized_partial_is_discarded_rather_than_appended_to():
    # Bigger than the plan expects means the file is not what this plan
    # thinks it is. Appending would splice foreign bytes into the archive.
    assert resume_offset(500, 1000, 1099) == 1000


def test_a_negative_size_is_rejected():
    with pytest.raises(ValueError):
        resume_offset(-1, 0, 99)


def test_the_real_interrupted_download_resumes_rather_than_restarts():
    """The 2026-08-20 case: 16 segments all partial, 0 complete.

    Under a resume that only skips exact-size parts, every one of these
    restarts from zero and the whole cache is wasted.
    """
    spans = plan_segments(TOTAL, SEGMENTS)
    partial = (spans[0][2] - spans[0][1] + 1) // 2      # each half fetched
    saved = 0
    for _, start, end in spans:
        offset = resume_offset(partial, start, end)
        assert offset == start + partial, "must resume, not restart"
        saved += offset - start
    assert saved > TOTAL // 3, "a half-done download should save real work"
