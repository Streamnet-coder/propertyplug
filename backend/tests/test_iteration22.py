"""Iteration 22 — Country totals (portfolio/map purchase_price) + Team Admin / Lead role.

Backend coverage:
- GET /api/portfolio/map now includes `purchase_price` per pin
- PUT /api/portal-members/{id} with {is_lead:true} -> 400 if member has no company; with company set -> is_lead true
- GET /api/portal-members includes is_lead and invited_by fields
- GET /api/portal/projects/{pid} returns is_lead + company fields for leads
- GET /api/portal/projects/{pid}/team: lists members with same owner+project+company (is_you flag);
    non-lead -> 403
- POST /api/portal/projects/{pid}/team {name,email}: creates teammate inheriting lead's role, company,
    doc_ids, digest; invited_by=lead email; duplicate email -> 400
- DELETE /api/portal/projects/{pid}/team/{mid}: removes non-lead teammate in same company;
    self or other lead -> 400; member of another company -> 404
- Owner GET /api/portal-activity shows team_invite / team_remove kinds with `detail`
"""
import os
import sys
import uuid
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ["EXPO_PUBLIC_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return cli[os.environ["DB_NAME"]]


def _sync(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


async def _mint_portal_token(email: str) -> str:
    """Mint a portal JWT directly, matching routes.portal.PORTAL_SECRET."""
    import jwt
    from datetime import datetime, timedelta, timezone
    from routes.portal import PORTAL_SECRET
    n = datetime.now(timezone.utc)
    return jwt.encode({"sub": email, "typ": "portal", "iat": n, "exp": n + timedelta(hours=1)},
                      PORTAL_SECRET, algorithm="HS256")


async def _cleanup_email(email: str):
    db = _db()
    await db.portal_accounts.delete_many({"email": email})
    await db.portal_handles.delete_many({"email": email})
    await db.portal_members.delete_many({"email": email})
    await db.portal_codes.delete_many({"email": email})


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def owner_ctx():
    """Login demo owner, discover first project id."""
    r = requests.post(f"{API}/auth/login",
                      json={"email": "demo@mybuilder.app", "password": "demo1234"}, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    projs = requests.get(f"{API}/projects", headers=headers, timeout=20).json()
    assert projs, "demo owner must have at least one project"
    pid = projs[0]["id"]
    # Make sure it's active
    requests.post(f"{API}/projects/{pid}/activate", headers=headers, timeout=20)
    return {"token": token, "headers": headers, "pid": pid}


@pytest.fixture
def invited_emails():
    emails: list[str] = []
    yield emails
    for e in emails:
        _sync(_cleanup_email(e))


def _invite(owner_ctx, email, name="Lead Dave", role="Investor", company=""):
    r = requests.post(f"{API}/portal-members", headers=owner_ctx["headers"], json={
        "name": name, "email": email, "role": role, "company": company,
        "doc_ids": [], "digest": True, "origin_url": BASE_URL,
    }, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# =============================================================================
# 1. Country totals: GET /api/portfolio/map includes purchase_price
# =============================================================================
class TestPortfolioMapPurchasePrice:
    def test_map_pins_include_purchase_price(self, owner_ctx):
        r = requests.get(f"{API}/portfolio/map", headers=owner_ctx["headers"], timeout=60)
        assert r.status_code == 200, r.text
        pins = r.json()
        assert isinstance(pins, list) and pins, "demo owner should have at least one project"
        for p in pins:
            assert "purchase_price" in p, f"pin missing purchase_price: {p}"
            # must be numeric (int/float), not string/null
            assert isinstance(p["purchase_price"], (int, float))
            # other totals needed by FilterTotals
            for k in ("estimated_valuation", "total_budget", "total_spent", "currency", "country"):
                assert k in p, f"pin missing {k}: {p}"

    def test_portfolio_has_rate_to_home_per_currency(self, owner_ctx):
        """FilterTotals converts mixed currencies via portfolio.by_currency[].rate_to_home."""
        r = requests.get(f"{API}/portfolio", headers=owner_ctx["headers"], timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "home_currency" in d
        assert isinstance(d.get("by_currency"), list)
        for g in d["by_currency"]:
            assert "currency" in g and "rate_to_home" in g
            assert isinstance(g["rate_to_home"], (int, float)) and g["rate_to_home"] > 0


# =============================================================================
# 2. Owner: PUT /portal-members/{id} is_lead gating + GET /portal-members fields
# =============================================================================
class TestLeadToggle:
    def test_cannot_promote_without_company(self, owner_ctx, invited_emails):
        em = f"test_nocompany_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, name="NoCo", company="")
        r = requests.put(f"{API}/portal-members/{m['id']}",
                         headers=owner_ctx["headers"],
                         json={"is_lead": True}, timeout=20)
        assert r.status_code == 400, r.text
        assert "company" in r.text.lower()

    def test_promote_with_company_sets_is_lead(self, owner_ctx, invited_emails):
        em = f"test_lead_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, name="Lead Co", company="Acme Build")
        r = requests.put(f"{API}/portal-members/{m['id']}",
                         headers=owner_ctx["headers"],
                         json={"is_lead": True}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["is_lead"] is True
        # And GET /portal-members confirms is_lead + exposes invited_by
        lst = requests.get(f"{API}/portal-members", headers=owner_ctx["headers"], timeout=20).json()
        row = next((x for x in lst if x["email"] == em), None)
        assert row and row["is_lead"] is True
        assert "invited_by" in row  # present (None for direct-invited leads)

    def test_promote_then_blank_company_fails(self, owner_ctx, invited_emails):
        em = f"test_blank_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, name="X", company="")
        # single call: setting is_lead true while company is empty must still 400
        r = requests.put(f"{API}/portal-members/{m['id']}",
                         headers=owner_ctx["headers"],
                         json={"is_lead": True, "company": "   "}, timeout=20)
        assert r.status_code == 400


# =============================================================================
# 3. Lead portal endpoints: project.is_lead/company, team list/add/delete, 403s
# =============================================================================
class TestPortalTeam:
    @pytest.fixture
    def lead_setup(self, owner_ctx, invited_emails):
        """Create a lead on the demo project and return (lead_token, lead_email, pid, mid)."""
        em = f"test_leadp_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, name="Pat Lead", company="Northfield Lending")
        # Promote to lead
        r = requests.put(f"{API}/portal-members/{m['id']}",
                         headers=owner_ctx["headers"],
                         json={"is_lead": True}, timeout=20)
        assert r.status_code == 200
        token = _sync(_mint_portal_token(em))
        return {"token": token, "email": em, "pid": owner_ctx["pid"], "mid": m["id"]}

    def _lh(self, token):
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def test_portal_project_returns_is_lead_and_company(self, lead_setup):
        r = requests.get(f"{API}/portal/projects/{lead_setup['pid']}",
                         headers=self._lh(lead_setup["token"]), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("is_lead") is True
        assert d.get("company") == "Northfield Lending"

    def test_non_lead_cannot_list_team(self, owner_ctx, invited_emails):
        em = f"test_nonlead_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        _invite(owner_ctx, em, name="Not Lead", company="Random Co")
        token = _sync(_mint_portal_token(em))
        r = requests.get(f"{API}/portal/projects/{owner_ctx['pid']}/team",
                         headers=self._lh(token), timeout=20)
        assert r.status_code == 403

    def test_team_list_scoped_to_company_with_is_you(self, lead_setup):
        r = requests.get(f"{API}/portal/projects/{lead_setup['pid']}/team",
                         headers=self._lh(lead_setup["token"]), timeout=20)
        assert r.status_code == 200, r.text
        team = r.json()
        me = [t for t in team if t["email"] == lead_setup["email"]]
        assert me and me[0]["is_you"] is True and me[0]["is_lead"] is True

    def test_invite_teammate_inherits_fields_and_log(self, owner_ctx, lead_setup, invited_emails):
        new = f"test_mate_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(new)
        r = requests.post(f"{API}/portal/projects/{lead_setup['pid']}/team",
                          headers=self._lh(lead_setup["token"]),
                          json={"name": "Mate Jo", "email": new}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "id" in body and body["email"] == new
        # Owner-side GET /portal-members: teammate inherits company/role; invited_by=lead email
        lst = requests.get(f"{API}/portal-members", headers=owner_ctx["headers"], timeout=20).json()
        row = next((x for x in lst if x["email"] == new), None)
        assert row, "teammate not visible to owner"
        assert row["company"] == "Northfield Lending"
        assert row["role"] == "Investor"
        assert row["invited_by"] == lead_setup["email"]
        # Portal activity shows team_invite kind with detail including the teammate
        act = requests.get(f"{API}/portal-activity",
                           headers=owner_ctx["headers"], timeout=20).json()
        hits = [a for a in act if a.get("kind") == "team_invite" and new in (a.get("detail") or "")]
        assert hits, f"team_invite activity not logged for {new}"

    def test_duplicate_teammate_email_rejected(self, lead_setup, invited_emails):
        new = f"test_dupmate_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(new)
        r1 = requests.post(f"{API}/portal/projects/{lead_setup['pid']}/team",
                           headers=self._lh(lead_setup["token"]),
                           json={"name": "Dup", "email": new}, timeout=30)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/portal/projects/{lead_setup['pid']}/team",
                           headers=self._lh(lead_setup["token"]),
                           json={"name": "Dup2", "email": new}, timeout=30)
        assert r2.status_code == 400

    def test_delete_teammate_and_activity_log(self, owner_ctx, lead_setup, invited_emails):
        new = f"test_rm_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(new)
        add = requests.post(f"{API}/portal/projects/{lead_setup['pid']}/team",
                            headers=self._lh(lead_setup["token"]),
                            json={"name": "RM Me", "email": new}, timeout=30).json()
        mid = add["id"]
        r = requests.delete(f"{API}/portal/projects/{lead_setup['pid']}/team/{mid}",
                            headers=self._lh(lead_setup["token"]), timeout=20)
        assert r.status_code == 200, r.text
        # confirm gone
        team = requests.get(f"{API}/portal/projects/{lead_setup['pid']}/team",
                            headers=self._lh(lead_setup["token"]), timeout=20).json()
        assert all(t["email"] != new for t in team)
        # Owner activity shows team_remove with detail including the teammate email
        act = requests.get(f"{API}/portal-activity",
                           headers=owner_ctx["headers"], timeout=20).json()
        hits = [a for a in act if a.get("kind") == "team_remove" and new in (a.get("detail") or "")]
        assert hits, f"team_remove activity not logged for {new}"

    def test_cannot_remove_self(self, lead_setup):
        r = requests.delete(f"{API}/portal/projects/{lead_setup['pid']}/team/{lead_setup['mid']}",
                            headers=self._lh(lead_setup["token"]), timeout=20)
        assert r.status_code == 400

    def test_cannot_remove_another_lead(self, owner_ctx, lead_setup, invited_emails):
        """Another lead in the SAME company cannot be removed by this lead."""
        em = f"test_otherlead_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        other = _invite(owner_ctx, em, name="Other Lead", company="Northfield Lending")
        # Promote them so they're a co-lead
        requests.put(f"{API}/portal-members/{other['id']}",
                     headers=owner_ctx["headers"],
                     json={"is_lead": True}, timeout=20)
        r = requests.delete(f"{API}/portal/projects/{lead_setup['pid']}/team/{other['id']}",
                            headers=self._lh(lead_setup["token"]), timeout=20)
        assert r.status_code == 400

    def test_cannot_remove_other_company_member(self, owner_ctx, lead_setup, invited_emails):
        em = f"test_otherco_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        other = _invite(owner_ctx, em, name="Diff Co", company="Totally Different Co Ltd")
        r = requests.delete(f"{API}/portal/projects/{lead_setup['pid']}/team/{other['id']}",
                            headers=self._lh(lead_setup["token"]), timeout=20)
        assert r.status_code == 404
