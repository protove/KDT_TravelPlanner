from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
USER_DATA = ROOT / "infra" / "environments" / "dev-eks" / "templates" / "bastion-user-data.sh.tftpl"


class BastionUserDataContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = USER_DATA.read_text(encoding="utf-8")

    def test_al2023_package_install_does_not_request_conflicting_curl(self) -> None:
        self.assertIn("dnf install -y aws-cli jq python3\n", self.source)
        self.assertNotIn("dnf install -y aws-cli jq python3 curl", self.source)
        self.assertIn("for command_name in aws jq python3 curl sha256sum; do", self.source)

    def test_kubectl_download_remains_pinned_and_checksum_verified(self) -> None:
        self.assertIn('https://dl.k8s.io/release/v${kubectl_version}/bin/linux/amd64/kubectl"', self.source)
        self.assertIn('https://dl.k8s.io/release/v${kubectl_version}/bin/linux/amd64/kubectl.sha256"', self.source)
        self.assertIn('sha256sum -c -', self.source)
        self.assertIn("command -v kubectl", self.source)


if __name__ == "__main__":
    unittest.main()
