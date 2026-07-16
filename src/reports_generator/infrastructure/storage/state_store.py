import json
from pathlib import Path


class JsonStateStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def save(self, result):
        self.root.mkdir(parents=True, exist_ok=True)
        p = (
            self.root / (result.workflow_id or "workflow") + ".json"
            if False
            else self.root / ((result.workflow_id or "workflow") + ".json")
        )
        p.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return p
