"""Select CI scope without changing formal release requirements."""
import argparse
import json
import os
from pathlib import Path

TARGETS = ("all", "checks", "windows-x64", "linux-x64", "macos-arm64", "macos-x64")


def build_plan(event, ref, requested=""):
    if event == "push" and ref.startswith("refs/tags/v"):
        target = "all"
    elif event == "pull_request":
        target = "all"
    elif event == "workflow_dispatch":
        target = requested or "all"
        if target not in TARGETS:
            raise ValueError("Unsupported package target")
    elif event == "push" and ref.startswith("refs/heads/"):
        target = "checks"
    else:
        raise ValueError("Unsupported CI event or ref")
    return {"package_target": target, "full_browser": target != "checks"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = build_plan(os.environ["YSU_CI_EVENT"], os.environ["YSU_CI_REF"],
                      os.environ.get("YSU_CI_PACKAGE_TARGET", ""))
    with args.output.open("a", encoding="utf-8") as stream:
        stream.write(f"package_target={plan['package_target']}\n")
        stream.write(f"full_browser={str(plan['full_browser']).lower()}\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write("### Desktop validation scope\n\n")
            stream.write(f"Requested package target: `{plan['package_target']}`.\n\n")
            stream.write("Four-platform authentication, runtime and Chromium regressions remain required.\n\n")
            stream.write("Checks mode creates no installers and uses browser smoke; select a package target for full browser acceptance and installation checks. Tags and pull requests always select all packages.\n")
    print(json.dumps(plan, sort_keys=True))


if __name__ == "__main__":
    main()
