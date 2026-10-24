import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

load_dotenv()

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB_NAME", "construction_manager")

_client: Optional[MongoClient] = None


def _get_collection() -> Collection:
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME]["projects"]


@dataclass
class MaterialItem:
    name: str
    qty_number: float
    qty_unit: str
    total_price: float
    dr_no: str = ""
    date: str = ""
    supplier: str = ""

    @property
    def total(self) -> float:
        return round(self.total_price, 2)

    def to_doc(self) -> dict:
        return {
            "name": self.name, "qty_number": self.qty_number, "qty_unit": self.qty_unit,
            "total_price": self.total_price, "dr_no": self.dr_no, "date": self.date,
            "supplier": self.supplier,
        }

    @staticmethod
    def from_doc(doc: dict) -> "MaterialItem":
        return MaterialItem(
            name=doc.get("name", ""),
            qty_number=doc.get("qty_number", 0.0),
            qty_unit=doc.get("qty_unit", ""),
            total_price=doc.get("total_price", 0.0),
            dr_no=doc.get("dr_no", ""),
            date=doc.get("date", ""),
            supplier=doc.get("supplier", ""),
        )


@dataclass
class LaborItem:
    worker: str
    rate: float
    skill: str = ""
    days_marked: list = field(default_factory=list)
    payroll_no: str = ""
    date_start: str = ""
    date_end: str = ""
    cash_advance: float = 0.0
    overtime_hours: float = 0.0

    @property
    def days(self) -> int:
        return len(self.days_marked)

    @property
    def overtime_pay(self) -> float:
        return round((self.rate / 8) * self.overtime_hours, 2)

    @property
    def total(self) -> float:
        return round(self.days * self.rate + self.overtime_pay - self.cash_advance, 2)

    def to_doc(self) -> dict:
        return {
            "worker": self.worker, "rate": self.rate, "skill": self.skill,
            "days_marked": self.days_marked, "payroll_no": self.payroll_no,
            "date_start": self.date_start, "date_end": self.date_end,
            "cash_advance": self.cash_advance, "overtime_hours": self.overtime_hours,
        }

    @staticmethod
    def from_doc(doc: dict) -> "LaborItem":
        return LaborItem(
            worker=doc.get("worker", ""), rate=doc.get("rate", 0.0), skill=doc.get("skill", ""),
            days_marked=list(doc.get("days_marked", [])), payroll_no=doc.get("payroll_no", ""),
            date_start=doc.get("date_start", ""), date_end=doc.get("date_end", ""),
            cash_advance=doc.get("cash_advance", 0.0), overtime_hours=doc.get("overtime_hours", 0.0),
        )

@dataclass
class EquipmentItem:
    equipment: str
    days: str
    rate: str

    @property
    def total(self) -> float:
        return round(self.days * self.rate, 2)
    def to_doc(self) -> dict:
        return {"equipment": self.equipment, "days": self.days, "rate": self.rate}

    @staticmethod
    def from_doc(doc: dict) -> "EquipmentItem":
        return EquipmentItem(equipment=doc["equipment"], days=doc["days"], rate=doc["rate"])


@dataclass
class ExpenseItem:
    description: str
    amount: float
    receipt_no: str = ""
    date: str = ""
    paid_to: str = ""

    @property
    def total(self) -> float:
        return round(self.amount, 2)

    def to_doc(self) -> dict:
        return {
            "description": self.description, "amount": self.amount,
            "receipt_no": self.receipt_no, "date": self.date, "paid_to": self.paid_to,
        }

    @staticmethod
    def from_doc(doc: dict) -> "ExpenseItem":
        return ExpenseItem(
            description=doc.get("description", ""), amount=doc.get("amount", 0.0),
            receipt_no=doc.get("receipt_no", ""), date=doc.get("date", ""), paid_to=doc.get("paid_to", ""),
        )


@dataclass
class AdminExpenseItem:
    description: str
    amount: float
    receipt_no: str = ""
    date: str = ""
    paid_to: str = ""

    @property
    def total(self) -> float:
        return round(self.amount, 2)

    def to_doc(self) -> dict:
        return {
            "description": self.description, "amount": self.amount,
            "receipt_no": self.receipt_no, "date": self.date, "paid_to": self.paid_to,
        }

    @staticmethod
    def from_doc(doc: dict) -> "AdminExpenseItem":
        return AdminExpenseItem(
            description=doc.get("description", ""), amount=doc.get("amount", 0.0),
            receipt_no=doc.get("receipt_no", ""), date=doc.get("date", ""), paid_to=doc.get("paid_to", ""),
        )


@dataclass
class Project:
    id: Optional[str]
    name: str
    description: str = ""
    location: str = ""
    budget: float = 0.0
    created_at: str = ""
    materials: list[MaterialItem] = field(default_factory=list)
    labor: list[LaborItem] = field(default_factory=list)
    equipment: list[EquipmentItem] = field(default_factory=list)
    expenses: list[ExpenseItem] = field(default_factory=list)
    admin_expenses: list[AdminExpenseItem] = field(default_factory=list)

    @property
    def materials_total(self) -> float:
        return round(sum(m.total for m in self.materials), 2)

    @property
    def labor_total(self) -> float:
        return round(sum(l.total for l in self.labor), 2)

    @property
    def equipment_total(self) -> float:
        return round(sum(e.total for e in self.equipment), 2)

    @property
    def expenses_total(self) -> float:
        return round(sum(x.total for x in self.expenses), 2)

    @property
    def admin_expenses_total(self) -> float:
        return round(sum(x.total for x in self.admin_expenses), 2)

    @property
    def total_cost(self) -> float:
        return round(
            self.materials_total + self.labor_total + self.equipment_total
            + self.expenses_total + self.admin_expenses_total,
            2,
        )


def _from_doc(doc: dict) -> Project:
    return Project(
        id=str(doc["_id"]),
        name=doc["name"],
        description=doc.get("description", ""),
        location=doc.get("location", ""),
        budget=doc.get("budget", 0.0),
        created_at=doc.get("created_at", ""),
        materials=[MaterialItem.from_doc(m) for m in doc.get("materials", [])],
        labor=[LaborItem.from_doc(l) for l in doc.get("labor", [])],
        equipment=[EquipmentItem.from_doc(e) for e in doc.get("equipment", [])],
        expenses=[ExpenseItem.from_doc(x) for x in doc.get("expenses", [])],
        admin_expenses=[AdminExpenseItem.from_doc(x) for x in doc.get("admin_expenses", [])],
    )


def init_db() -> None:
    
    try:
        collection = _get_collection()
        _client.admin.command("ping")
        collection.create_index("created_at")
    except PyMongoError as exc:
        raise ConnectionError(
            f"Could not reach MongoDB at {MONGO_URI!r}. Make sure MongoDB is running, "
            "or set the MONGO_URI environment variable (or a .env file) to point at "
            "your MongoDB instance."
        ) from exc


def list_projects() -> list[Project]:
    collection = _get_collection()
    return [_from_doc(doc) for doc in collection.find().sort("created_at", -1)]


def get_project(project_id: str) -> Optional[Project]:
    collection = _get_collection()
    try:
        doc = collection.find_one({"_id": ObjectId(project_id)})
    except InvalidId:
        return None
    return _from_doc(doc) if doc is not None else None


def save_project(project: Project) -> str:
    collection = _get_collection()
    doc = {
        "name": project.name,
        "description": project.description,
        "location": project.location,
        "budget": project.budget,
        "materials": [m.to_doc() for m in project.materials],
        "labor": [l.to_doc() for l in project.labor],
        "equipment": [e.to_doc() for e in project.equipment],
        "expenses": [x.to_doc() for x in project.expenses],
        "admin_expenses": [x.to_doc() for x in project.admin_expenses],
    }
    if project.id is None:
        doc["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        result = collection.insert_one(doc)
        project.id = str(result.inserted_id)
    else:
        collection.update_one({"_id": ObjectId(project.id)}, {"$set": doc})
    return project.id


def delete_project(project_id: str) -> None:
    collection = _get_collection()
    try:
        collection.delete_one({"_id": ObjectId(project_id)})
    except InvalidId:
        pass
