"""End-to-end smoke test — no Telegram needed.

Builds a properly HMAC-signed initData string (the same signature scheme
Telegram uses) and drives the whole API: auth, create with screenshot,
list, vote, admin triage.

Run from the project root:  python scripts/smoke_test.py
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

TMP = tempfile.mkdtemp(prefix="tracker-smoke-")
os.environ.update({
    "BOT_TOKEN": "123456:TEST-TOKEN",
    "ADMIN_IDS": "1",
    "DB_PATH": os.path.join(TMP, "test.db"),
    "UPLOAD_DIR": os.path.join(TMP, "uploads"),
})
os.environ.pop("DEV_USER_ID", None)
os.environ.pop("GROUP_CHAT_ID", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def make_init_data(user_id: int, first_name: str) -> str:
    """Sign initData exactly the way Telegram does."""
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "AAtest",
        "user": json.dumps({"id": user_id, "first_name": first_name}),
    }
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


def main() -> None:
    admin = {"Authorization": "tma " + make_init_data(1, "Admin")}
    member = {"Authorization": "tma " + make_init_data(2, "Member")}

    with TestClient(app) as c:
        # auth
        assert c.get("/api/me").status_code == 401, "unsigned request must be rejected"
        bad = {"Authorization": "tma " + make_init_data(1, "Admin").replace("hash=", "hash=00")}
        assert c.get("/api/me", headers=bad).status_code == 401, "tampered hash must be rejected"
        me = c.get("/api/me", headers=admin).json()
        assert me["is_admin"] is True
        assert c.get("/api/me", headers=member).json()["is_admin"] is False

        # member files a bug with a screenshot
        r = c.post(
            "/api/submissions",
            headers=member,
            data={"kind": "bug", "title": "Login button dead on Android", "description": "Tapped it. Nothing."},
            files=[("files", ("shot.png", PNG_1PX, "image/png"))],
        )
        assert r.status_code == 201, r.text
        sub = r.json()
        sid = sub["id"]
        assert sub["attachment_count"] == 1

        # screenshot is served
        fn = c.get(f"/api/submissions/{sid}", headers=member).json()["attachments"][0]["filename"]
        assert c.get(f"/uploads/{fn}").content == PNG_1PX

        # validation
        assert c.post("/api/submissions", headers=member, data={"kind": "bug", "title": "x"}).status_code == 422
        assert c.post(
            "/api/submissions", headers=member,
            data={"kind": "bug", "title": "Bad file type"},
            files=[("files", ("evil.txt", b"hi", "text/plain"))],
        ).status_code == 422

        # voting: toggle on, on again = off; two users
        assert c.post(f"/api/submissions/{sid}/vote", headers=member).json() == {"votes": 1, "my_vote": True}
        assert c.post(f"/api/submissions/{sid}/vote", headers=admin).json() == {"votes": 2, "my_vote": True}
        assert c.post(f"/api/submissions/{sid}/vote", headers=admin).json() == {"votes": 1, "my_vote": False}

        # triage: members can't, admins can
        assert c.patch(f"/api/submissions/{sid}", headers=member, json={"status": "completed"}).status_code == 403
        r = c.patch(f"/api/submissions/{sid}", headers=admin, json={"priority": "high", "status": "in_progress"})
        assert r.status_code == 200 and r.json()["priority"] == "high"
        r = c.patch(f"/api/submissions/{sid}", headers=admin, json={"status": "completed"})
        assert r.status_code == 200
        assert r.json()["status"] == "completed"
        assert r.json()["announced"] is False  # no bot/group configured in the test

        # list shows computed fields
        items = c.get("/api/submissions", headers=member).json()
        assert items[0]["votes"] == 1 and items[0]["my_vote"] is True

        # deletion: admin-only, removes record and screenshot files from disk
        r = c.post(
            "/api/submissions", headers=member,
            data={"kind": "idea", "title": "Temporary idea"},
            files=[("files", ("shot2.png", PNG_1PX, "image/png"))],
        )
        del_id = r.json()["id"]
        del_file = c.get(f"/api/submissions/{del_id}", headers=member).json()["attachments"][0]["filename"]
        assert (Path(os.environ["UPLOAD_DIR"]) / del_file).exists()
        assert c.delete(f"/api/submissions/{del_id}", headers=member).status_code == 403
        assert c.delete(f"/api/submissions/{del_id}", headers=admin).status_code == 200
        assert c.get(f"/api/submissions/{del_id}", headers=member).status_code == 404
        assert not (Path(os.environ["UPLOAD_DIR"]) / del_file).exists()
        assert c.delete(f"/api/submissions/{del_id}", headers=admin).status_code == 404

        # webhook endpoint enforces the secret header
        assert c.post("/tg/webhook", json={"update_id": 1}).status_code == 403
        import hashlib as _h
        secret = _h.sha256(os.environ["BOT_TOKEN"].encode()).hexdigest()[:32]
        r = c.post("/tg/webhook", json={"update_id": 1},
                   headers={"X-Telegram-Bot-Api-Secret-Token": secret})
        assert r.status_code == 200

        # group auto-capture storage round-trips
        from app import db as _db
        _db.set_kv("group_chat_id", "-100123")
        from app.bot import current_group_id
        assert current_group_id() == -100123

        # once bound, membership is enforced. Telegram is unreachable here,
        # so verification fails -> unknown users are locked out (fail closed)…
        assert c.get("/api/me", headers=member).status_code == 403
        # …while ADMIN_IDS-listed admins keep access regardless.
        assert c.get("/api/me", headers=admin).status_code == 200

        # frontend is served
        assert "telegram-web-app.js" in c.get("/").text

    print("All smoke tests passed ✔")


if __name__ == "__main__":
    main()
