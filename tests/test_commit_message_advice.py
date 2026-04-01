from checks import commit_message_advice as cma


def test_extract_commit_subjects():
    commits = [
        {"commit": {"message": "Fix parser bug\n\nBody text"}},
        {"commit": {"message": ""}},
        {"commit": {"message": "Add tests"}},
    ]

    assert cma.extract_commit_subjects(commits) == ["Fix parser bug", "Add tests"]


def test_build_comment_no_suggestions():
    comment = cma.build_comment("Messages look clean.", [])
    assert "Overall assessment" in comment
    assert "No changes are required." in comment


def test_parse_response_limits_suggestions():
    raw = '{"overall_assessment":"Needs minor polishing","suggestions":["A","B","C","D"]}'
    overall, suggestions = cma.parse_response(raw)

    assert overall == "Needs minor polishing"
    assert suggestions == ["A", "B", "C"]
