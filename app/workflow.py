from typing import List


def evaluate_approval(amount: float, category: str) -> List[str]:
    """Mirror of processes/approval-routing.dmn decision table for UI task routing."""
    steps = ["manager"]
    if category == "Regulated" or amount > 10000:
        steps.append("finance")
    if amount > 50000:
        steps.append("procurement_director")
    return steps


def task_label(role: str) -> str:
    return {
        "manager": "Manager approval",
        "finance": "Finance approval",
        "procurement_director": "Procurement director approval",
    }[role]
