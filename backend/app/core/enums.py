from enum import StrEnum


class Role(StrEnum):
    DOCTOR = "doctor"
    NURSE = "nurse"
    BILLING_EXECUTIVE = "billing_executive"
    TECHNICIAN = "technician"
    ADMIN = "admin"


ROLE_COLLECTIONS: dict[Role, list[str]] = {
    Role.DOCTOR: ["general", "clinical", "nursing"],
    Role.NURSE: ["general", "nursing"],
    Role.BILLING_EXECUTIVE: ["general", "billing"],
    Role.TECHNICIAN: ["general", "equipment"],
    Role.ADMIN: ["general", "clinical", "nursing", "billing", "equipment"],
}


COLLECTION_ROLES: dict[str, list[Role]] = {
    "general": [Role.DOCTOR, Role.NURSE, Role.BILLING_EXECUTIVE, Role.TECHNICIAN, Role.ADMIN],
    "clinical": [Role.DOCTOR, Role.ADMIN],
    "nursing": [Role.NURSE, Role.DOCTOR, Role.ADMIN],
    "billing": [Role.BILLING_EXECUTIVE, Role.ADMIN],
    "equipment": [Role.TECHNICIAN, Role.ADMIN],
}


SQL_RAG_ROLES: set[Role] = {Role.BILLING_EXECUTIVE, Role.ADMIN}


class ChunkType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    HEADING = "heading"
    CODE = "code"


class RetrievalType(StrEnum):
    HYBRID_RAG = "hybrid_rag"
    SQL_RAG = "sql_rag"


DEMO_USERS: dict[str, dict] = {
    "dr.mehta": {"password": "doctor", "role": Role.DOCTOR, "name": "Dr. Mehta"},
    "nurse.priya": {"password": "nurse", "role": Role.NURSE, "name": "Nurse Priya"},
    "billing.ravi": {"password": "billing_executive", "role": Role.BILLING_EXECUTIVE, "name": "Ravi Sharma"},
    "tech.anand": {"password": "technician", "role": Role.TECHNICIAN, "name": "Anand Kumar"},
    "admin.sys": {"password": "admin", "role": Role.ADMIN, "name": "Admin Sys"},
}
