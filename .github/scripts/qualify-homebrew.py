"""Pinned Homebrew lifecycle qualification on disposable GitHub macOS runners.

This script installs packages only on the approved CI branch. Local imports have
no effects. It does not publish packages or change the production tap.
"""

import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request


REPOSITORY = "synthesiseng/homebrew-tap"
TAP = "synthesiseng/tap"
FORMULA = f"{TAP}/gitrole"
BRANCH = "refs/heads/qualification/homebrew-0.13.4"
RELEASES = {
    "0.13.3": (
        "6fbc37e699f6c7fbee82e2b50a17d863a0f01885",
        "8ba1fb0a645bf4178e1a96633f956bef04207239aaa2323184f4c255838d24bc",
    ),
    "0.13.4": (
        "1faeaf664f5d1342932476a99056b8a85142d8b1",
        "dc8acaeae9976b85cdc2818cfcba3bab5b23126a2649d9ad356e77f920d560f4",
    ),
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def runner_guard(environment, system, machine):
    require(environment.get("GITHUB_ACTIONS") == "true", "CI execution required")
    require(environment.get("GITHUB_REPOSITORY") == REPOSITORY, "Unexpected repository")
    require(environment.get("GITHUB_REF") == BRANCH, "Unexpected branch")
    require(environment.get("GITHUB_EVENT_NAME") == "push", "Push event required")
    require(system == "Darwin" and machine == "arm64", "macOS arm64 required")


def run(args, env, cwd=None, expected=0, timeout=120, input_text=None):
    args = [str(value) for value in args]
    print("+ " + shlex.join(args), flush=True)
    result = subprocess.run(args, env=env, cwd=cwd, text=True,
                            input=input_text, capture_output=True, timeout=timeout)
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", file=sys.stderr, flush=True)
    require(result.returncode == expected,
            f"Expected exit {expected}, got {result.returncode}: {shlex.join(args)}")
    return result.stdout


def preserve(paths):
    return {str(path): (path.read_bytes(), path.stat().st_mode & 0o777)
            for path in paths}


def verify_links(prefix, keg, version):
    package = keg / "libexec/lib/node_modules/gitrole"
    require(json.loads((package / "package.json").read_text())["version"] == version,
            "Installed package version differs")
    for name, entry in [("gitrole", "dist/cli/index.js"),
                        ("gitrole-prompt", "shell/gitrole-prompt")]:
        link = prefix / "bin" / name
        require(link.is_symlink(), f"Normal executable link missing: {name}")
        require(link.resolve() == (package / entry).resolve(),
                f"Wrong installed entrypoint: {name}")
        print(f"LINK {name}: {link} -> {link.resolve()}", flush=True)
    return package


def pin_tap(version, tap, env):
    revision, checksum = RELEASES[version]
    run(["git", "-C", tap, "-c", "credential.helper=", "fetch", "origin", revision], env)
    run(["git", "-C", tap, "checkout", "--detach", revision], env)
    require(run(["git", "-C", tap, "rev-parse", "HEAD"], env).strip() == revision,
            "Tap revision differs")
    formula = (tap / "Formula/gitrole.rb").read_text()
    url = f"https://registry.npmjs.org/gitrole/-/gitrole-{version}.tgz"
    require(f'  url "{url}"' in formula and f'  sha256 "{checksum}"' in formula,
            "Pinned formula artifact differs")
    with urllib.request.urlopen(url, timeout=60) as response:
        archive = response.read(20 * 1024 * 1024 + 1)
    require(len(archive) <= 20 * 1024 * 1024, "Unexpected archive size")
    require(hashlib.sha256(archive).hexdigest() == checksum, "Archive checksum differs")
    print(f"ARTIFACT {version}: tap={revision} sha256={checksum}", flush=True)


def installed(version, prefix, env):
    keg = prefix / "Cellar/gitrole" / version
    require(keg.is_dir(), "Expected installed keg missing")
    require((prefix / "opt/gitrole").resolve() == keg.resolve(), "Wrong active keg")
    package = verify_links(prefix, keg, version)
    require(run([prefix / "bin/gitrole", "--version"], env).strip() == version,
            "CLI version differs")
    require("Manage named git identities" in run([prefix / "bin/gitrole", "--help"], env),
            "CLI help missing")
    sample = "role=work scope=na override=na commit=ok remote=na auth=na policy=na overall=aligned\n"
    require("gitrole:work ✓" in run([prefix / "bin/gitrole-prompt", "--format"], env,
                                   input_text=sample), "Prompt helper differs")
    return package


def probe_environment(root, prefix):
    home = root / "home"
    config = root / "config"
    guards = root / "guards"
    for directory in [home, config, guards, root / "cache", root / "tmp"]:
        directory.mkdir()
    global_config = root / "global.gitconfig"
    global_config.write_text("[user]\n\tuseConfigOnly = true\n[commit]\n\tgpgsign = false\n")
    guard = '#!/bin/sh\nprintf "%s\\n" "$0" >> "$FORBIDDEN_LOG"\nexit 97\n'
    for name in ["ssh", "ssh-add", "security", "scp", "sftp"]:
        path = guards / name
        path.write_text(guard)
        path.chmod(0o755)
    return {
        "PATH": f"{guards}:{prefix}/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home), "XDG_CONFIG_HOME": str(config),
        "XDG_CACHE_HOME": str(root / "cache"), "TMPDIR": str(root / "tmp"),
        "GIT_CONFIG_GLOBAL": str(global_config), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": str(guards / "ssh"),
        "SSH_AUTH_SOCK": str(root / "absent-agent"), "SSH_ASKPASS_REQUIRE": "never",
        "FORBIDDEN_LOG": str(root / "forbidden.log"),
        "GIT_CEILING_DIRECTORIES": str(root),
        "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
        "NO_COLOR": "1", "FORCE_COLOR": "0", "TERM": "dumb",
    }


def setup_state(root, package, env):
    repo = root / "synthetic-repository"
    repo.mkdir()
    run(["git", "init", "-b", "main"], env, repo)
    run(["gitrole", "add", "work", "--name", "Fixture Developer",
         "--email", "fixture@example.invalid"], env, repo)
    # No key, remote or destination exists when use performs alignment.
    run(["gitrole", "use", "work", "--local"], env, repo)
    run(["gitrole", "pin", "work"], env, repo)
    hook = repo / ".git/hooks/pre-commit"
    shutil.copyfile(package / "hooks/pre-commit", hook)
    hook.chmod(0o755)
    protected = [Path(env["XDG_CONFIG_HOME"]) / "gitrole/roles.json",
                 Path(env["GIT_CONFIG_GLOBAL"]), repo / ".git/config",
                 repo / ".gitrole", hook]
    return repo, protected


def verify_state(repo, env):
    require(run(["gitrole", "check", "commit"], env, repo) == "",
            "Matching commit check must be quiet")
    run([repo / ".git/hooks/pre-commit"], env, repo)
    for field in ["GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"]:
        mismatch = {**env, field: "other@example.invalid"}
        run(["gitrole", "check", "commit"], mismatch, repo, expected=2)
        run([repo / ".git/hooks/pre-commit"], mismatch, repo, expected=2)
    status = run(["gitrole", "status", "--short", "--offline"], env, repo, expected=2)
    require(status.strip() == "role=work scope=local override=true commit=ok remote=warn auth=na policy=ok overall=warning",
            "Unexpected local offline status")
    require(not Path(env["FORBIDDEN_LOG"]).exists(), "Forbidden SSH/agent/Keychain attempt")


def main():
    require(len(sys.argv) == 2 and sys.argv[1] in ["fresh", "upgrade"], "Choose fresh or upgrade")
    runner_guard(os.environ, platform.system(), platform.machine())
    scenario = sys.argv[1]
    root = Path(tempfile.mkdtemp(prefix="gitrole-brew-", dir=os.environ["RUNNER_TEMP"]))
    # Homebrew uses the disposable runner's own HOME; only Gitrole probes use the
    # synthetic HOME. No token is passed to these package-management subprocesses.
    brew_env = {key: os.environ[key] for key in ["PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"]
                if key in os.environ}
    brew_env.update({"HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ANALYTICS": "1",
                     "HOMEBREW_NO_INSTALL_CLEANUP": "1", "HOMEBREW_NO_ENV_HINTS": "1",
                     "GIT_TERMINAL_PROMPT": "0", "CI": "true"})
    run(["sw_vers"], brew_env)
    run(["uname", "-m"], brew_env)
    run(["brew", "--version"], brew_env)
    print(json.dumps({key: os.environ.get(key) for key in
                      ["ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH", "GITHUB_SHA"]}), flush=True)
    prefix = Path(run(["brew", "--prefix"], brew_env).strip())
    require(str(prefix) == "/opt/homebrew", "Standard Apple Silicon prefix required")
    require(not (prefix / "Cellar/gitrole").exists(), "Gitrole already installed")
    for name in ["gitrole", "gitrole-prompt"]:
        require(not os.path.lexists(prefix / "bin" / name), "Executable conflict")
    taps = run(["brew", "tap"], brew_env).splitlines()
    require(TAP not in taps, "Tap unexpectedly already present")
    run(["brew", "tap", TAP, "https://github.com/synthesiseng/homebrew-tap.git"], brew_env,
        timeout=300)
    tap = Path(run(["brew", "--repository", TAP], brew_env).strip())
    first = "0.13.3" if scenario == "upgrade" else "0.13.4"
    pin_tap(first, tap, brew_env)
    run(["brew", "install", FORMULA], brew_env, timeout=900)
    env = probe_environment(root, prefix)
    run(["ssh", "fixture-guard-control.invalid"], env, expected=97)
    require(Path(env["FORBIDDEN_LOG"]).is_file(), "Transport guard control was not observed")
    Path(env["FORBIDDEN_LOG"]).unlink()
    package = installed(first, prefix, env)
    run(["brew", "test", FORMULA], brew_env, timeout=300)
    repo, protected = setup_state(root, package, env)
    before = preserve(protected)
    verify_state(repo, env)
    require(preserve(protected) == before, "Read-only probes changed synthetic state")
    if scenario == "upgrade":
        pin_tap("0.13.4", tap, brew_env)
        run(["brew", "upgrade", FORMULA], brew_env, timeout=900)
        require(preserve(protected) == before, "Upgrade changed synthetic state")
        installed("0.13.4", prefix, env)
        run(["brew", "test", FORMULA], brew_env, timeout=300)
        verify_state(repo, env)
        require(preserve(protected) == before, "Post-upgrade probes changed synthetic state")
    run(["brew", "list", "--versions", "gitrole", "node"], brew_env)
    print(json.dumps({"result": "PASS", "scenario": scenario, "version": "0.13.4",
                      "formulaTests": "PASS", "syntheticStatePreserved": True,
                      "cliAndHelperSameKeg": True, "forbiddenProbeAttempts": 0,
                      "limits": "macOS15 arm64 runner; no live authentication or personal Mac qualification"}), flush=True)


if __name__ == "__main__":
    main()
