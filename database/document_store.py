from datetime import datetime
from typing import Optional, List
from pymongo import MongoClient
from bson import ObjectId
from config import settings

class LoanDocument:
    def __init__(
        self,
        document_id: str = "MISSING",
        company_name: str = "MISSING",
        loan_plans: str = "MISSING",
        service_area: str = "MISSING",
        credit_score_requirements: str = "MISSING",
        loan_minimum_amount: float = 0,
        loan_maximum_amount: float = 0,
        loan_to_value_ratio: float = 0,
        application_requirements: str = "MISSING",
        guidelines: str = "MISSING",
        contact_information: Optional[dict] = None,
        property_types: str = "MISSING",
        interest_rates: str = "MISSING",
        points_charged: str = "MISSING",
        liquidity_requirements: str = "MISSING",
        loan_to_cost_ratio: Optional[float] = 0,
        debt_service_coverage_ratio: float = 0,
        loan_term: str = "MISSING",
        amortization: str = "MISSING",
        construction: str = "MISSING",
        value_add: str = "MISSING",
        personal_guarantee: str = "MISSING",
        created_at: datetime = datetime.utcnow(),
        updated_at: datetime = datetime.utcnow(),
        created_by: str = "MISSING"
    ):
        self.id = str(ObjectId())
        self.document_id = document_id
        self.company_name = company_name
        self.loan_plans = loan_plans
        self.service_area = service_area
        self.credit_score_requirements = credit_score_requirements
        self.loan_minimum_amount = loan_minimum_amount
        self.loan_maximum_amount = loan_maximum_amount
        self.loan_to_value_ratio = loan_to_value_ratio
        self.application_requirements = application_requirements
        self.guidelines = guidelines
        self.contact_information = contact_information or {"person": "MISSING", "phone": "MISSING", "email": "MISSING"}
        self.property_types = property_types
        self.interest_rates = interest_rates
        self.points_charged = points_charged
        self.liquidity_requirements = liquidity_requirements
        self.loan_to_cost_ratio = loan_to_cost_ratio
        self.debt_service_coverage_ratio = debt_service_coverage_ratio
        self.loan_term = loan_term
        self.amortization = amortization
        self.construction = construction
        self.value_add = value_add
        self.personal_guarantee = personal_guarantee
        self.created_at = created_at
        self.updated_at = updated_at
        self.created_by = created_by

    def to_dict(self):
        return {
            "_id": ObjectId(self.id),
            "document_id": self.document_id,
            "company_name": self.company_name,
            "loan_plans": self.loan_plans,
            "service_area": self.service_area,
            "credit_score_requirements": self.credit_score_requirements,
            "loan_minimum_amount": self.loan_minimum_amount,
            "loan_maximum_amount": self.loan_maximum_amount,
            "loan_to_value_ratio": self.loan_to_value_ratio,
            "application_requirements": self.application_requirements,
            "guidelines": self.guidelines,
            "contact_information": self.contact_information,
            "property_types": self.property_types,
            "interest_rates": self.interest_rates,
            "points_charged": self.points_charged,
            "liquidity_requirements": self.liquidity_requirements,
            "loan_to_cost_ratio": self.loan_to_cost_ratio,
            "debt_service_coverage_ratio": self.debt_service_coverage_ratio,
            "loan_term": self.loan_term,
            "amortization": self.amortization,
            "construction": self.construction,
            "value_add": self.value_add,
            "personal_guarantee": self.personal_guarantee,
            "created_at": self.created_at.timestamp(),
            "updated_at": self.updated_at.timestamp(),
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LoanDocument":
        return cls(
            document_id=data.get("document_id", "MISSING"),
            company_name=data.get("company_name", "MISSING"),
            loan_plans=data.get("loan_plans", "MISSING"),
            service_area=data.get("service_area", "MISSING"),
            credit_score_requirements=data.get("credit_score_requirements", "MISSING"),
            loan_minimum_amount=data.get("loan_minimum_amount", 0),
            loan_maximum_amount=data.get("loan_maximum_amount", 0),
            loan_to_value_ratio=data.get("loan_to_value_ratio", 0),
            application_requirements=data.get("application_requirements", "MISSING"),
            guidelines=data.get("guidelines", "MISSING"),
            contact_information=data.get("contact_information", {"person": "MISSING", "phone": "MISSING", "email": "MISSING"}),
            property_types=data.get("property_types", "MISSING"),
            interest_rates=data.get("interest_rates", "MISSING"),
            points_charged=data.get("points_charged", "MISSING"),
            liquidity_requirements=data.get("liquidity_requirements", "MISSING"),
            loan_to_cost_ratio=data.get("loan_to_cost_ratio", 0),
            debt_service_coverage_ratio=data.get("debt_service_coverage_ratio", 0),
            loan_term=data.get("loan_term", "MISSING"),
            amortization=data.get("amortization", "MISSING"),
            construction=data.get("construction", "MISSING"),
            value_add=data.get("value_add", "MISSING"),
            personal_guarantee=data.get("personal_guarantee", "MISSING"),
            created_at=datetime.fromtimestamp(data["created_at"]),
            updated_at=datetime.fromtimestamp(data["updated_at"]),
            created_by=data.get("created_by", "MISSING"),
        )

class LoanDocumentStore:
    def __init__(self):
        self.client = MongoClient(settings.MONGODB_URL)
        self.db = self.client[settings.MONGO_DATABASE]
        self.collection = self.db.loan_documents

    def store_document(self, document: LoanDocument) -> LoanDocument:
        loan_document = document.to_dict()
        self.collection.insert_one(loan_document)
        return document

    def get_document_by_id(self, document_id: str) -> Optional[LoanDocument]:
        data = self.collection.find_one({"document_id": document_id})
        return LoanDocument.from_dict(data) if data else None

    def update_document(self, document_id: str, updates: dict) -> bool:
        if "document_id" in updates:
            del updates["document_id"]  # Ensure document_id is not overwritten
        result = self.collection.update_one(
            {"document_id": document_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    def delete_document(self, document_id: str) -> bool:
        result = self.collection.delete_one({"document_id": document_id})
        return result.deleted_count > 0
        
    def search_documents(self, query: dict) -> list[LoanDocument]:
        documents = self.collection.find(query)
        return [doc for doc in list(documents)]

    def find_similar_documents(self, document: LoanDocument) -> List[LoanDocument]:
        query = {"company_name": document.company_name}
        documents = self.collection.find(query)
        return [doc for doc in list(documents)]
