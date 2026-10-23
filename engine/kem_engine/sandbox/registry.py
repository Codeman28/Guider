"""App name → sandbox spec (Phase 4: Excel, Word, PowerPoint)."""
from . import excel, powerpoint, word

SPECS = {"excel": excel.SPEC, "word": word.SPEC, "powerpoint": powerpoint.SPEC}
