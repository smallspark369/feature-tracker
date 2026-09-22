"""REST API consumed by the Mini App frontend."""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import db
from .auth import current_user
from .bot import announce_completed
from .config import settings

router = APIRouter()

ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_FILES = 4


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return user


@router.get("/submissions")
async def list_submissions(user: dict = Depends(current_user)):
    return db.list_submissions(user["id"])


@router.get("/submissions/{sid}")
async def get_submission(sid: int, user: dict = Depends(current_user)):
    sub = db.get_submission(sid, user["id"])
    if sub is None:
        raise HTTPException(404, "Not found.")
    return sub


@router.post("/submissions", status_code=201)
async def create_submission(
    kind: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    user: dict = Depends(current_user),
):
    kind = kind.strip().lower()
    title = title.strip()
    description = description.strip()

    if kind not in db.KINDS:
        raise HTTPException(422, "Kind must be 'idea' or 'bug'.")
    if not 3 <= len(title) <= 120:
        raise HTTPException(422, "Title must be 3–120 characters.")
    if len(description) > 4000:
        raise HTTPException(422, "Description is limited to 4000 characters.")
    if len(files) > MAX_FILES:
        raise HTTPException(422, f"At most {MAX_FILES} screenshots per submission.")

    # Validate all files before writing anything.
    saved: list[tuple[bytes, str, str]] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024
    for f in files:
        ext = ALLOWED_IMAGE_TYPES.get(f.content_type or "")
        if ext is None:
            raise HTTPException(422, "Screenshots must be PNG, JPEG, WebP, or GIF.")
        data = await f.read()
        if len(data) > max_bytes:
            raise HTTPException(422, f"Each screenshot must be under {settings.max_upload_mb} MB.")
        if not data:
            continue
        saved.append((data, uuid.uuid4().hex + ext, f.filename or ""))

    sid = db.create_submission(kind, title, description, user["id"], user["name"])
    for data, name, original in saved:
        (settings.upload_dir / name).write_bytes(data)
        db.add_attachment(sid, name, original)

    return db.get_submission(sid, user["id"])


@router.post("/submissions/{sid}/vote")
async def vote(sid: int, user: dict = Depends(current_user)):
    if db.get_submission(sid, user["id"]) is None:
        raise HTTPException(404, "Not found.")
    votes, my_vote = db.toggle_vote(sid, user["id"])
    return {"votes": votes, "my_vote": my_vote}


class TriagePatch(BaseModel):
    status: str | None = None
    priority: str | None = None


@router.patch("/submissions/{sid}")
async def triage(sid: int, patch: TriagePatch, user: dict = Depends(current_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "Only admins can triage submissions.")
    if patch.status is not None and patch.status not in db.STATUSES:
        raise HTTPException(422, "Invalid status.")
    if patch.priority is not None and patch.priority not in db.PRIORITIES:
        raise HTTPException(422, "Invalid priority.")

    before = db.get_submission(sid, user["id"])
    if before is None:
        raise HTTPException(404, "Not found.")

    db.update_submission(sid, patch.status, patch.priority)
    after = db.get_submission(sid, user["id"])

    announced = False
    if patch.status == "completed" and before["status"] != "completed":
        announced = await announce_completed(after, after["votes"])

    after["announced"] = announced
    return after
