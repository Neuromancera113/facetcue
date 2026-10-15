"""Annotation review transactions. Never undo or infer changes to model geometry."""

import json

import bpy

from . import api
from .core import MarkError, validate_note

MAX_REVIEW_HISTORY = 100


def snapshot(mark):
    return {"note": mark.note, "status": mark.status, "change_summary": mark.change_summary}


def history(scene):
    store = api.document(scene)
    try:
        entries = json.loads(store.asm_review_history) if store else []
        if not isinstance(entries, list):
            raise ValueError("Expected a review history list")
        return entries
    except (TypeError, ValueError) as exc:
        raise MarkError("CORRUPT_REVIEW_HISTORY", "Review history could not be read") from exc


def submit_changes(changes):
    """Validate the entire agent submission before setting any mark to MODIFIED.

    A retry of the same revision and summary is idempotent. Geometry changes
    happen before this call; this operation records an explicit agent completion,
    never guesses authorship from dependency-graph updates.
    """
    if not isinstance(changes, list) or not 1 <= len(changes) <= 200:
        raise MarkError("INVALID_ARGUMENTS", "Submit 1..200 annotation changes")
    pending, seen = [], set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {
            "scene_name",
            "marker_id",
            "expected_revision",
            "summary",
        }:
            raise MarkError(
                "INVALID_ARGUMENTS", "Expected scene_name, marker_id, expected_revision and summary"
            )
        scene = bpy.data.scenes.get(change["scene_name"])
        if scene is None:
            raise MarkError("SCENE_NOT_FOUND", "Requested scene does not exist")
        mark = api.get_mark(scene, change["marker_id"])
        key = scene.name, mark.marker_id
        if key in seen:
            raise MarkError("INVALID_ARGUMENTS", "Duplicate annotation in submission")
        seen.add(key)
        summary = validate_note(change["summary"])
        if not summary.strip():
            raise MarkError("INVALID_NOTE", "Describe the completed change")
        revision = change["expected_revision"]
        if type(revision) is not int or revision < 1:
            raise MarkError("REVISION_CONFLICT", "Read the annotation revision before editing")
        repeated = (
            mark.status == "MODIFIED"
            and mark.revision == revision + 1
            and mark.change_summary == summary
        )
        if not repeated:
            if mark.revision != revision:
                raise MarkError(
                    "REVISION_CONFLICT", "Annotation changed; read it again before submitting"
                )
            if mark.status not in {"OPEN", "IN_PROGRESS", "CHANGES_REQUESTED"}:
                raise MarkError(
                    "INVALID_REVIEW_STATE", "Only pending work can be submitted for review"
                )
        pending.append((scene, mark, summary, repeated))
    records = []
    for scene, mark, summary, repeated in pending:
        if not repeated:
            mark.change_summary = summary
            api.update(scene, mark.marker_id, mark.revision, status="MODIFIED")
        record = api.serialize(scene, mark)
        record["scene_name"] = scene.name
        records.append(record)
    return {"ok": True, "annotations": records, "submitted": len(records)}


def decide(scene, marker_id, expected_revision, action, note=None):
    mark = api.get_mark(scene, marker_id)
    if mark.revision != expected_revision:
        raise MarkError("REVISION_CONFLICT", "Annotation changed while reviewing")
    if mark.status != "MODIFIED" or action not in {"APPROVE", "REJECT"}:
        raise MarkError("INVALID_REVIEW_STATE", "Only modified annotations can be reviewed")
    if action == "REJECT":
        validate_note(note)
        if not note.strip():
            raise MarkError("INVALID_NOTE", "Keep a modification request when rejecting")
    entries = history(scene)
    before = snapshot(mark)
    api.update(
        scene,
        marker_id,
        expected_revision,
        note=note if action == "REJECT" else None,
        status="RESOLVED" if action == "APPROVE" else "CHANGES_REQUESTED",
    )
    entries.append(
        {
            "marker_id": marker_id,
            "action": action,
            "before": before,
            "after": snapshot(mark),
            "after_revision": mark.revision,
        }
    )
    api.document(scene).asm_review_history = json.dumps(
        entries[-MAX_REVIEW_HISTORY:], ensure_ascii=False
    )
    return api.serialize(scene, mark)


def withdraw(scene):
    entries = history(scene)
    if not entries:
        raise MarkError("NO_REVIEW_HISTORY", "No review decision to withdraw")
    entry = entries[-1]
    try:
        mark = api.get_mark(scene, entry["marker_id"])
        before = entry["before"]
        if mark.revision != entry["after_revision"] or snapshot(mark) != entry["after"]:
            raise MarkError(
                "REVISION_CONFLICT",
                "Annotation changed after that review; refusing to overwrite it",
            )
        validate_note(before["note"])
        validate_note(before["change_summary"])
        api.update(scene, mark.marker_id, mark.revision, before["note"], before["status"])
        mark.change_summary = before["change_summary"]
    except (KeyError, TypeError) as exc:
        raise MarkError("CORRUPT_REVIEW_HISTORY", "Review history is invalid") from exc
    entries.pop()
    if (
        entries
        and entries[-1]["marker_id"] == mark.marker_id
        and entries[-1]["after"] == snapshot(mark)
    ):
        entries[-1]["after_revision"] = mark.revision
    api.document(scene).asm_review_history = json.dumps(entries, ensure_ascii=False)
    return api.serialize(scene, mark)
