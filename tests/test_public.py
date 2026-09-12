def test_index_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.content_type


def test_index_is_macedonian_and_declares_its_language(client):
    """lang="mk" is required for correct Macedonian Cyrillic letterforms.

    Without it the browser may pick Russian locale forms, which a native reader
    sees immediately (see .claude/skills/design-system/SKILL.md).
    """
    body = client.get("/").get_data(as_text=True)

    assert 'lang="mk"' in body
    assert "Платформа за грантови и субвенции" in body
