# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Notification templates: escaping, declared and personal fields, subject, languages (§B6.3 rule 3)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.channels.templates import TemplateError, load_template_set
from app.modules.notifications import rendering

EVENT = uuid.uuid4()


def _write(folder: Path, key: str, ext: str, front: str, body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{key}.{ext}").write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8")


@pytest.fixture
def templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    en = tmp_path / "templates" / "en"
    monkeypatch.setattr(rendering, "TEMPLATES_DIR", en)
    return en


def test_devanagari_text_renders_unchanged_in_both_formats(templates: Path) -> None:
    front = "fields: [name]"
    _write(templates, "hello", "txt", front, "नमस्ते {{ name }}, स्वागत है")
    _write(templates, "hello", "html", front, "<p>नमस्ते {{ name }}, स्वागत है</p>")
    message = rendering.render_message("hello", "x.y", EVENT, {"name": "रीना"})
    assert message.text.strip() == "नमस्ते रीना, स्वागत है"
    assert message.body.strip() == "<p>नमस्ते रीना, स्वागत है</p>"


def test_html_escapes_a_script_in_a_field_and_text_does_not(templates: Path) -> None:
    front = "fields: [note]"
    _write(templates, "note", "txt", front, "Note: {{ note }}")
    _write(templates, "note", "html", front, "<p>{{ note }}</p>")
    hostile = "<script>alert(1)</script> & more"
    message = rendering.render_message("note", "x.y", EVENT, {"note": hostile})
    assert "<script>" not in message.body
    assert "&lt;script&gt;" in message.body
    assert message.text.strip() == f"Note: {hostile}"  # plain text keeps what was written, no HTML entities


def test_only_declared_fields_reach_the_template(templates: Path) -> None:
    front = "fields: [shown]"
    _write(templates, "scoped", "txt", front, "{{ shown }}")
    message = rendering.render_message("scoped", "x.y", EVENT, {"shown": "yes", "hidden": "secret"})
    assert "secret" not in message.text
    assert rendering.minimized_data("scoped", {"shown": "yes", "hidden": "secret"}) == {"shown": "yes"}


def test_an_undeclared_field_in_a_template_is_an_error(templates: Path) -> None:
    _write(templates, "bad", "txt", "fields: [a]", "{{ b }}")
    with pytest.raises(
        Exception, match="b"
    ):  # StrictUndefined: a template cannot read what it did not declare
        rendering.render_message("bad", "x.y", EVENT, {"a": 1, "b": 2})


def test_personal_fields_are_left_out_unless_allowed(templates: Path) -> None:
    front = "fields: [team_role, display_name]\npersonal_fields: [display_name]"
    _write(templates, "person", "txt", front, "{{ display_name }} is {{ team_role }}")
    data = {"team_role": "lead", "display_name": "Ada Lovelace"}
    assert rendering.render_message("person", "x.y", EVENT, data, allow_personal=True).text.strip() == (
        "Ada Lovelace is lead"
    )
    assert (
        rendering.render_message("person", "x.y", EVENT, data, allow_personal=False).text.strip() == "is lead"
    )
    assert rendering.minimized_data("person", data, allow_personal=False) == {"team_role": "lead"}
    assert rendering.minimized_data("person", data, allow_personal=True) == data


def test_personal_fields_must_be_declared_fields(templates: Path) -> None:
    _write(templates, "wrong", "txt", "fields: [a]\npersonal_fields: [b]", "{{ a }}")
    with pytest.raises(TemplateError, match="personal_fields"):
        load_template_set(templates, "wrong")


def test_formats_must_agree_on_their_fields(templates: Path) -> None:
    _write(templates, "split", "txt", "fields: [a]", "{{ a }}")
    _write(templates, "split", "html", "fields: [a, b]", "{{ a }}")
    with pytest.raises(TemplateError, match="different fields"):
        load_template_set(templates, "split")


def test_a_subject_line_is_rendered_on_one_line(templates: Path) -> None:
    front = 'fields: [team_role]\nsubject: "Added as {{ team_role }}"'
    _write(templates, "subj", "txt", front, "Body {{ team_role }}")
    message = rendering.render_message("subj", "x.y", EVENT, {"team_role": "lead"})
    assert message.subject == "Added as lead"
    assert message.text.strip() == "Body lead"


def test_without_a_subject_the_plain_text_is_the_subject(templates: Path) -> None:
    _write(templates, "nosubj", "txt", "fields: [a]", "Only text {{ a }}")
    assert rendering.render_message("nosubj", "x.y", EVENT, {"a": 1}).subject.strip() == "Only text 1"


def test_a_language_without_the_template_falls_back_to_the_default(templates: Path) -> None:
    _write(templates, "greet", "txt", "fields: [a]", "Hello {{ a }}")
    _write(templates.parent / "hi", "greet", "txt", "fields: [a]", "नमस्ते {{ a }}")
    assert rendering.render_message("greet", "x.y", EVENT, {"a": 1}, language="hi").text.strip() == "नमस्ते 1"
    assert rendering.render_message("greet", "x.y", EVENT, {"a": 1}, language="fr").text.strip() == "Hello 1"
    assert rendering.render_message("greet", "x.y", EVENT, {"a": 1}).text.strip() == "Hello 1"


def test_a_missing_template_is_an_error(templates: Path) -> None:
    templates.mkdir(parents=True)
    with pytest.raises(TemplateError):
        rendering.render_message("nothing", "x.y", EVENT, {})


def test_the_shipped_templates_render_with_a_subject_in_both_formats() -> None:
    data = {"team_id": "t", "member_id": "m", "team_role": "lead"}
    message = rendering.render_message("team-member-added", "team_member.added", EVENT, data)
    assert message.subject == "You were added to a team"
    assert "lead" in message.text
    assert "<strong>lead</strong>" in message.body
    dead = rendering.render_message(
        "delivery-dead-lettered",
        "x.y",
        EVENT,
        {"channel_key": "email", "error_code": "smtp_550", "attempts": 3},
    )
    assert "email" in dead.text
    assert "smtp_550" in dead.body
