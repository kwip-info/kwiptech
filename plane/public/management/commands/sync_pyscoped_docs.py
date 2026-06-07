"""Download and extract pyscoped documentation from PyPI.

Fetches the pyscoped source distribution, extracts docs/, CLAUDE.md, and
AGENTS.md, and writes them to a local directory. Works on any platform —
Heroku, Docker, bare metal.

Usage:
    python manage.py sync_pyscoped_docs
    python manage.py sync_pyscoped_docs --output /tmp/pyscoped-docs
    python manage.py sync_pyscoped_docs --sdk-version 1.5.0
"""

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Download pyscoped docs from PyPI and extract to a local directory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=os.environ.get("PYSCOPED_DOCS_PATH", "/tmp/pyscoped-docs"),
            help="Directory to write docs to (default: $PYSCOPED_DOCS_PATH or /tmp/pyscoped-docs)",
        )
        parser.add_argument(
            "--sdk-version",
            default=None,
            help="Specific pyscoped version to fetch (default: installed version)",
        )

    def handle(self, *args, **options):
        output_dir = Path(options["output"])
        version = options["sdk_version"] or self._get_installed_version()

        if not version:
            self.stderr.write(self.style.ERROR("Cannot determine pyscoped version"))
            return

        self.stdout.write(f"Syncing pyscoped {version} docs to {output_dir}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Download source distribution
            self.stdout.write("  Downloading sdist from PyPI...")
            result = subprocess.run(
                [
                    sys.executable, "-m", "pip", "download",
                    "--no-deps", "--no-binary", ":all:",
                    f"pyscoped=={version}",
                    "-d", str(tmppath),
                ],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                self.stderr.write(self.style.ERROR(f"pip download failed: {result.stderr}"))
                return

            # Find and extract the tarball
            tarballs = list(tmppath.glob("*.tar.gz"))
            if not tarballs:
                self.stderr.write(self.style.ERROR("No .tar.gz found in download"))
                return

            self.stdout.write("  Extracting...")
            with tarfile.open(tarballs[0], "r:gz") as tar:
                tar.extractall(path=tmppath, filter="data")

            # Find the extracted directory
            extracted = [p for p in tmppath.iterdir() if p.is_dir() and p.name.startswith("pyscoped-")]
            if not extracted:
                self.stderr.write(self.style.ERROR("No pyscoped-* directory found in archive"))
                return

            src = extracted[0]
            docs_src = src / "docs"

            if not docs_src.exists():
                self.stderr.write(self.style.ERROR(f"No docs/ directory in {src.name}"))
                return

            # Copy to output
            if output_dir.exists():
                shutil.rmtree(output_dir)
            shutil.copytree(docs_src, output_dir)

            # Copy the agent context files (downloaded alongside the docs).
            for fname in ("CLAUDE.md", "AGENTS.md"):
                src_file = src / fname
                if src_file.exists():
                    shutil.copy2(src_file, output_dir / fname)

        doc_count = len(list(output_dir.rglob("*.md")))
        self.stdout.write(self.style.SUCCESS(
            f"Synced {doc_count} docs to {output_dir}"
        ))

    def _get_installed_version(self) -> str | None:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", "pyscoped"],
                capture_output=True, text=True,
            )
            for line in result.stdout.split("\n"):
                if line.startswith("Version:"):
                    return line.split(":", 1)[1].strip()
        except (ValueError, IndexError):
            pass
        return None
