CATEGORIES = [
    "Gas bill",
    "Software licenses",
    "Electricity bill",
    "Cloud services",
    "Office supplies",
    "Professional services",
    "Hotel stay",
    "Software subscription",
    "Internet & telephone",
    "Hardware purchase",
]

DEPARTMENT_ROUTING = {
    "Gas bill":              "Facilities",
    "Electricity bill":      "Facilities",
    "Software licenses":     "IT",
    "Cloud services":        "IT",
    "Software subscription": "IT",
    "Internet & telephone":  "IT",
    "Hardware purchase":     "IT",
    "Office supplies":       "Administration",
    "Professional services": "Finance",
    "Hotel stay":            "Travel & Expenses",
}

INVOICES_DIR = "Invoices"
MANIFEST_FILE = "Invoices/00_manifest.csv"
GEMINI_MODEL = "gemini-2.5-flash"
