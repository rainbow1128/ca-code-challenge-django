from ca_shared.roles import Role, has_role


def test_editor_can_do_what_a_reader_can():
    assert has_role(Role.EDITOR, Role.READER)
    assert has_role(Role.EDITOR, Role.EDITOR)


def test_reader_cannot_edit():
    assert has_role(Role.READER, Role.READER)
    assert not has_role(Role.READER, Role.EDITOR)


def test_accepts_plain_strings():
    assert has_role("editor", "reader")
    assert not has_role("reader", "editor")


def test_unknown_roles_get_nothing():
    assert not has_role("admin", "reader")
    assert not has_role("editor", "superuser")
    assert not has_role("", "reader")
