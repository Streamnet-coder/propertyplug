from fastapi import HTTPException
from fastapi.security import HTTPBearer
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, BeforeValidator, ConfigDict
from typing import Annotated, Optional
from datetime import datetime, timezone
from bson import ObjectId
from pathlib import Path
import os, logging, html

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
EMERGENT_KEY = os.environ['EMERGENT_LLM_KEY']
STRIPE_API_KEY = os.environ['STRIPE_API_KEY']
PRO_PRICE_GBP = 19.0
APP_NAME = "my-builder-app"

bearer = HTTPBearer(auto_error=False)
E = html.escape


# ---------------- Mongo models ----------------
PyObjectId = Annotated[str, BeforeValidator(lambda v: str(v) if isinstance(v, ObjectId) else v)]


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    @classmethod
    def from_mongo(cls, doc):
        return cls.model_validate(doc) if doc else None

    def to_mongo(self):
        d = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            d["_id"] = ObjectId(self.id)
        return d

    def out(self):
        return self.model_dump(exclude={"user_id", "password_hash"})


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(404, "Not found")


def money(n, d=0):
    return f"£{n:,.{d}f}"
