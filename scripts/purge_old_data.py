"""
It tidies up data that hasn't been used for a long time.

Nigeria's data protection law (NDPA) says personal data shouldn't be kept longer than needed. This script applies
three rules, all set in .env:

    A user who hasn't visited for MEMORY_RETENTION_DAYS (365 days) has everything stored about them deleted: their
        businesses, facts, chats, notes, reminders and logs.
    For users who are still active, a business nobody has worked on for BUSINESS_INACTIVE_DAYS (180 days) is set
        aside as "inactive". It's kept, but Navi only sees its name until the user brings it up again.
    A business unused for BUSINESS_DELETE_DAYS (540 days) is deleted. A business with a reminder still in the future
        is never set aside or deleted.

The API server already runs this clean-up every time it starts. Schedule this script to run once a day as well (for
example as a cron job), so the clean-up still happens on a server that runs for months without restarting.

HOW TO RUN IT
    python -m scripts.purge_old_data
"""

from agent.config import get_settings
from agent.storage import store


def main() -> None:
    """Apply the user and business rules, and say what was done."""
    s = get_settings()
    if s.memory_retention_days > 0:
        removed = store.purge_inactive_users(s.memory_retention_days)
        print(f"Deleted {removed} user(s) not seen in the last {s.memory_retention_days} days.")
    else:
        print("MEMORY_RETENTION_DAYS is 0, which means keep users forever. No users were deleted.")

    retired = store.retire_unused_businesses(s.business_inactive_days, s.business_delete_days)
    print(f"Businesses set aside as inactive: {retired['made_inactive']}; deleted: {retired['deleted']}.")


if __name__ == "__main__":
    main()
