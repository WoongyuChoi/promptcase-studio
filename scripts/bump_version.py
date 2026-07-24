from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "promptcase_studio" / "__init__.py"
PROMPT_MANIFEST = ROOT / "prompts" / "manifest.json"
README_FILE = ROOT / "README.md"
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
VERSION_DECLARATION = re.compile(r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"', re.M)
README_VERSION_BADGE = re.compile(
    r"(https://img\.shields\.io/badge/Version-)(\d+\.\d+\.\d+)(-[A-Za-z0-9]+)"
)


def read_product_version() -> str:
    match = VERSION_DECLARATION.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"버전 선언을 찾을 수 없습니다: {VERSION_FILE}")
    return match.group(1)


def read_readme_version() -> str:
    match = README_VERSION_BADGE.search(README_FILE.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"README 버전 배지를 찾을 수 없습니다: {README_FILE}")
    return match.group(2)


def next_version(current: str, target: str) -> str:
    major, minor, patch = (int(part) for part in current.split("."))
    if target == "major":
        return f"{major + 1}.0.0"
    if target == "minor":
        return f"{major}.{minor + 1}.0"
    if target == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if SEMVER_PATTERN.fullmatch(target):
        return target
    raise SystemExit("버전은 major, minor, patch 또는 X.Y.Z 형식이어야 합니다.")


def verify_versions() -> str:
    product_version = read_product_version()
    manifest = json.loads(PROMPT_MANIFEST.read_text(encoding="utf-8-sig"))
    prompt_version = str(manifest.get("bundleVersion", ""))
    readme_version = read_readme_version()
    if len({product_version, prompt_version, readme_version}) != 1:
        raise SystemExit(
            "버전이 일치하지 않습니다: "
            f"제품={product_version}, 프롬프트={prompt_version}, README={readme_version}"
        )
    if not SEMVER_PATTERN.fullmatch(product_version):
        raise SystemExit(f"유효한 SemVer가 아닙니다: {product_version}")
    return product_version


def update_versions(target: str) -> tuple[str, str]:
    current = verify_versions()
    updated = next_version(current, target)
    if tuple(map(int, updated.split("."))) < tuple(map(int, current.split("."))):
        raise SystemExit(f"이전 버전으로 낮출 수 없습니다: {current} -> {updated}")
    if updated == current:
        return current, updated

    source = VERSION_FILE.read_text(encoding="utf-8")
    VERSION_FILE.write_text(
        VERSION_DECLARATION.sub(f'__version__ = "{updated}"', source, count=1),
        encoding="utf-8",
    )
    manifest = json.loads(PROMPT_MANIFEST.read_text(encoding="utf-8-sig"))
    manifest["bundleVersion"] = updated
    PROMPT_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    readme = README_FILE.read_text(encoding="utf-8")
    README_FILE.write_text(
        README_VERSION_BADGE.sub(
            lambda match: f"{match.group(1)}{updated}{match.group(3)}",
            readme,
            count=1,
        ),
        encoding="utf-8",
    )
    return current, updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="제품, 프롬프트 번들과 README 배지 버전을 함께 관리합니다."
    )
    parser.add_argument("target", nargs="?", help="major, minor, patch 또는 X.Y.Z")
    parser.add_argument(
        "--check",
        action="store_true",
        help="현재 제품 버전과 프롬프트 번들 버전의 일치 여부만 검사합니다.",
    )
    args = parser.parse_args()

    if args.check:
        print(f"Promptcase Studio {verify_versions()}")
        return 0
    if not args.target:
        parser.error("target 또는 --check가 필요합니다.")

    previous, updated = update_versions(args.target)
    print(f"Promptcase Studio {previous} -> {updated}")
    print("CHANGELOG 확인 후 테스트, EXE 빌드, Git 태그 생성을 진행하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
