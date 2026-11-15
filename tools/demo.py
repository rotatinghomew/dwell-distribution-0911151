from pathlib import Path
import json
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dwell_distribution.client import ProductClient
from dwell_distribution.data import load_bundle
from dwell_distribution.service import running_service
from dwell_distribution.store import ArtifactStore
from dwell_distribution.workflow import publish_latent_analysis, publish_overview


def main():
    root = Path(__file__).resolve().parents[1]
    bundle = load_bundle(root / "fixtures/bundle.json")
    with tempfile.TemporaryDirectory() as directory:
        store = ArtifactStore(str(Path(directory) / "state.sqlite3"), bundle.get("policy"))
        try:
            with running_service(bundle, store) as base:
                client = ProductClient(base)
                published = publish_overview(client, "2026-01-01", "overview-demo")
                restored = client.artifact(published["artifact_id"])
                assert restored == published["artifact"]
                latent = publish_latent_analysis(client, "2026-01-01", "latent-demo")
                restored_latent = client.artifact(latent["artifact_id"])
                assert restored_latent == latent["artifact"]
                print(json.dumps({"产品": bundle["product"], "发布编号": published["artifact_id"], "原始资料概览": restored["result"]}, ensure_ascii=False, indent=2))
                print(json.dumps({"发布编号": latent["artifact_id"], "潜在时长分析": restored_latent["result"]}, ensure_ascii=False, indent=2))
        finally:
            store.close()


if __name__ == "__main__":
    main()
