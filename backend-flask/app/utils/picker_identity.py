import secrets

from ..models import User


PICKER_ROLES = {"picker", "packer", "delivery"}


def ensure_picker_code(user):
    if not user or user.role not in PICKER_ROLES or user.picker_code:
        return user.picker_code if user else ""
    user.picker_code = generate_picker_code()
    return user.picker_code


def generate_picker_code():
    for _ in range(50):
        code = f"{secrets.randbelow(100000):05d}"
        if not User.query.filter_by(picker_code=code).first():
            return code
    raise RuntimeError("Could not generate a unique picker id")
