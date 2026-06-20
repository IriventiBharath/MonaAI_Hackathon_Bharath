import csv
import time
from pathlib import Path

from tabulate import tabulate

from config import INVOICES_DIR, MANIFEST_FILE
from agent import classify_invoice


def load_manifest(manifest_path: str) -> dict:
    ground_truth = {}
    with open(manifest_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ground_truth[row["file"].strip()] = row["invoice_type"].strip()
    return ground_truth


def run_evaluation():
    ground_truth = load_manifest(MANIFEST_FILE)
    invoice_files = sorted(
        f for f in Path(INVOICES_DIR).iterdir()
        if f.is_file() and f.suffix.lower() in (".pdf", ".png", ".docx")
    )

    rows = []
    correct_count = 0

    for file_path in invoice_files:
        print(f"Processing {file_path.name} ...")
        result = classify_invoice(file_path)

        actual = ground_truth.get(file_path.name, "NOT IN MANIFEST")
        is_correct = result["predicted_category"] == actual
        if is_correct:
            correct_count += 1

        rows.append([
            file_path.name,
            result["predicted_category"],
            actual,
            "Y" if is_correct else "N",
            result["department"],
        ])

        time.sleep(1)

    headers = ["Filename", "Predicted Category", "Actual Category", "Correct", "Department Routed To"]
    print("\n" + tabulate(rows, headers=headers, tablefmt="github"))

    total = len(invoice_files)
    accuracy = correct_count / total * 100 if total else 0
    print(f"\nAccuracy: {correct_count}/{total} = {accuracy:.1f}%")


if __name__ == "__main__":
    run_evaluation()
