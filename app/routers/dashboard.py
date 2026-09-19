"""Server-rendered dashboard views (Phase 6): Jinja2 + HTMX, no separate
frontend build pipeline, per DESIGN.md's Phase 1 decided-implementation-
detail.

WHAT: `GET /` renders the login page or the connected-account status page
depending on session state; `GET /dashboard/races` renders the logged-in
user's race list with predicted-vs-actual and a live HTMX unmark toggle
(`POST /dashboard/races/{id}/unmark` swaps the row out via
`_race_row.html`'s `hx-swap="outerHTML"`); `GET /scoreboard` renders the
latest `eval_run`'s `eval_metrics` — the one view here that requires no
login, since DESIGN.md's data-isolation rule allows *aggregate-only* tables
to be read by a shared, cross-user view.

WHY this is additive to, not a replacement for, the bare-JSON endpoints in
app/routers/auth.py and app/routers/races.py: those remain the correct
integration surface for tests and any future API client. This router is
purely a presentation layer on the exact same repository functions, with
zero duplicated business logic — account_status.html's backfill/disconnect/
delete buttons call those JSON endpoints directly via a tiny inline
`fetch()` (see that template) rather than this router growing parallel
HTML-only versions of them.

WHY the race list only shows effectively-classified races
(`is_race_effective = true`), with the toggle only ever "unmark," never
"mark": showing every ingested activity (so a user could mark one the
heuristic missed) would need a much larger activity browser/search UI —
real, unscoped work for an MVP dashboard. This is a deliberate, documented
gap: correcting a false positive is supported; catching a false negative is
not, yet.

WHY `Jinja2Templates` is instantiated here rather than in app/main.py
(which DESIGN.md's own file-header comment once described as owning
"Jinja2Templates setup"): keeping it colocated with the only router that
uses it avoids a circular import (app.main imports this router; this router
would otherwise need to import back from app.main for the shared instance).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_current_user_optional
from app.models.activity import Activity
from app.models.user import User
from app.repositories import backfill_job_repo, evaluation_repo, prediction_repo, race_repo

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _build_race_rows(db: Session, user: User) -> list[dict]:
    races = race_repo.list_races_for_user(db, user.id)
    activity_ids = [activity.id for activity, _classification in races]
    details_by_activity = race_repo.get_details_for_activities(db, activity_ids)
    predictions_by_activity = prediction_repo.list_predictions_by_activity(db, activity_ids)

    rows = []
    for activity, classification in races:
        detail = details_by_activity.get(activity.id)
        predictions = predictions_by_activity.get(activity.id, {})
        rows.append(
            {
                "activity": activity,
                "classification": classification,
                "actual_display": _format_duration(detail.finish_time_s if detail else None),
                "riegel_display": _format_duration(predictions.get("riegel")),
                "trained_model_display": _format_duration(predictions.get("trained_model")),
            }
        )
    return rows


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if user is None:
        return templates.TemplateResponse(request, "login.html", {})
    backfill_job = backfill_job_repo.get_latest_for_user(db, user.id)
    return templates.TemplateResponse(
        request, "account_status.html", {"user": user, "backfill_job": backfill_job}
    )


@router.get("/dashboard/races", response_class=HTMLResponse)
def races_page(
    request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "races_list.html", {"races": _build_race_rows(db, user)}
    )


@router.post("/dashboard/races/{activity_id}/unmark")
def unmark_race(
    activity_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> HTMLResponse:
    activity = db.get(Activity, activity_id)
    if activity is None or activity.user_id != user.id:
        raise HTTPException(404, "No such activity for this account")

    classification = race_repo.get_classification(db, activity_id)
    if classification is None:
        raise HTTPException(404, "This activity has not been classified yet")

    race_repo.set_manual_override(db, classification, False)
    return HTMLResponse("")  # hx-swap="outerHTML" removes the row from the list


@router.get("/scoreboard", response_class=HTMLResponse)
def scoreboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    eval_run = evaluation_repo.get_latest_eval_run(db)
    metrics = evaluation_repo.list_metrics_for_run(db, eval_run.id) if eval_run else []
    return templates.TemplateResponse(
        request, "scoreboard.html", {"eval_run": eval_run, "metrics": metrics}
    )
