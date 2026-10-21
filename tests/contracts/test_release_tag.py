import json
from subprocess import CompletedProcess

import pytest


def test_existing_tag_on_another_commit_stops_publication():
    from scripts.ensure_release_tag import ensure_release_tag
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return CompletedProcess(command, 0, json.dumps({'sha': 'b'*40}), '')
    with pytest.raises(RuntimeError, match='different commit'):
        ensure_release_tag('owner/repo', 'v8.3.5-preview.1', 'a'*40, run=run)
    assert len(calls) == 1  # No tag mutation or release creation.


def test_missing_tag_is_created_then_resolved_to_tested_commit():
    from scripts.ensure_release_tag import ensure_release_tag
    calls = []
    replies = [(1, '', 'gh: Not Found (HTTP 404)'), (0, '{}', ''), (0, json.dumps({'sha': 'a'*40}), '')]
    def run(command, **kwargs):
        calls.append(command)
        code, out, err = replies[len(calls)-1]
        return CompletedProcess(command, code, out, err)
    ensure_release_tag('owner/repo', 'v8.3.5-preview.1', 'a'*40, run=run)
    assert '--method' in calls[1] and 'POST' in calls[1]
    assert 'ref=refs/tags/v8.3.5-preview.1' in calls[1]
    assert 'sha='+'a'*40 in calls[1]
    assert calls[2] == calls[0]


def test_existing_matching_tag_is_never_rewritten():
    from scripts.ensure_release_tag import ensure_release_tag
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return CompletedProcess(command, 0, json.dumps({'sha': 'a'*40}), '')
    ensure_release_tag('owner/repo', 'v8.3.5-preview.1', 'a'*40, run=run)
    assert len(calls) == 1


def test_tag_read_permission_error_is_not_treated_as_missing():
    from scripts.ensure_release_tag import ensure_release_tag
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return CompletedProcess(command, 1, '', 'gh: Forbidden (HTTP 403)')
    with pytest.raises(RuntimeError, match='403'):
        ensure_release_tag('owner/repo', 'v8.3.5-preview.1', 'a'*40, run=run)
    assert len(calls) == 1
