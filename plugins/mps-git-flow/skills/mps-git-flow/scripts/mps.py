#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MPS git flow helper CLI (skill mps-git-flow).

Commit & push code to the MPS self-hosted GitLab with Jira ticket discipline.
Usage: mps.py <group> <command> [args]. Every command prints exactly ONE JSON object
to stdout: {"ok": true, ...} or {"ok": false, "error": "<code>", "message": "<vi>"}.

Python >= 3.8, standard library only.

COMPATIBILITY NOTE: this file must stay *parseable* by Python 2.7 so that the version
guard below can print a friendly message instead of a SyntaxError. Do not use
f-strings, annotations, keyword-only arguments, numeric underscores, the walrus
operator, nonlocal, "yield from", "raise ... from" or star-unpacking.
"""

import sys

if sys.version_info < (3, 8):
    sys.stdout.write(
        '{"ok": false, "error": "python_too_old", '
        '"message": "Can Python 3.8 tro len. Hay chay lai bang py -3 (Windows) hoac python3."}\n'
    )
    sys.exit(3)

import argparse  # noqa: E402
import base64  # noqa: E402
import copy  # noqa: E402
import datetime  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import posixpath  # noqa: E402
import re  # noqa: E402
import socket  # noqa: E402
import ssl  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import unicodedata  # noqa: E402
import uuid  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402

VERSION = "0.2.4"
USER_AGENT = "mps-git-flow/" + VERSION

EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 4

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

ENV_FILENAME = ".env"
ENV_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "env.example")
SECRET_KEY_SUFFIX = "_PAT"

KEY_JIRA_URL = "MPS_JIRA_URL"
KEY_JIRA_PAT = "MPS_JIRA_PAT"
KEY_JIRA_PROJECT = "MPS_JIRA_PROJECT_KEY"
KEY_GITLAB_URL = "MPS_GITLAB_URL"
KEY_GITLAB_PAT = "MPS_GITLAB_PAT"
KEY_GITLAB_PROJECT = "MPS_GITLAB_PROJECT"
KEY_BRANCH_DEV = "MPS_BRANCH_DEV"
KEY_BRANCH_BETA_PREFIX = "MPS_BRANCH_BETA_PREFIX"
KEY_BRANCH_PROD = "MPS_BRANCH_PROD"
KEY_CA_BUNDLE = "MPS_CA_BUNDLE"
KEY_GENERATED_PATTERNS = "MPS_GENERATED_PATTERNS"

KNOWN_KEYS = (
    KEY_JIRA_URL, KEY_JIRA_PAT, KEY_JIRA_PROJECT,
    KEY_GITLAB_URL, KEY_GITLAB_PAT, KEY_GITLAB_PROJECT,
    KEY_BRANCH_DEV, KEY_BRANCH_BETA_PREFIX, KEY_BRANCH_PROD,
    KEY_CA_BUNDLE, KEY_GENERATED_PATTERNS,
)
# The only keys a team member fills in .env; every other key keeps its template default.
MEMBER_KEYS = (KEY_JIRA_PAT, KEY_JIRA_PROJECT, KEY_GITLAB_PAT)
SERVICE_PAT_KEYS = {"jira": KEY_JIRA_PAT, "gitlab": KEY_GITLAB_PAT}
JIRA_PAT_PAGE = "/secure/ViewProfile.jspa?selectedTab=com.atlassian.pats.pats-plugin:jira-user-personal-access-tokens"
# GitLab 16+ pre-fills the token name and scopes from these query parameters.
GITLAB_PAT_PAGE = "/-/user_settings/personal_access_tokens?name=mps-git-flow&scopes=api,write_repository"

# Plugin integration into a project (lead) and the plugin version check.
MARKETPLACE_NAME = "mps-cdci-agents"
MARKETPLACE_REPO = "madpoly-studio/mps-cicd-agent-flow"
# GitHub repos the marketplace used to live in. A project still pointing to one is moved to MARKETPLACE_REPO.
LEGACY_MARKETPLACE_REPOS = ("hung-bui-121/mps-cdci-agents",)
# Where Claude Code keeps the marketplaces registered on this machine (one file per user).
PLUGINS_DIR_ENV = "CLAUDE_CODE_PLUGIN_CACHE_DIR"
CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
KNOWN_MARKETPLACES_FILE = "known_marketplaces.json"
# Commands that still run while this machine installs the plugin from a legacy repo: `project setup` is how a
# lead moves the project to the shared repo, so it must never be locked out.
LEGACY_SOURCE_EXEMPT_COMMANDS = (("project", "setup"),)
PLUGIN_KEY = "mps-git-flow@mps-cdci-agents"
PROJECT_SETTINGS_PATH = ".claude/settings.json"
# Claude Code's `attribution` setting with every part hidden, in the form older Claude Code versions also accept
# (`"attribution": false` needs v2.1.281+; earlier versions would skip the whole settings file).
HIDDEN_ATTRIBUTION = {"commit": "", "pr": "", "sessionUrl": False}
# GitLab label per ticket type (hotfix tickets are bugs).
MR_LABELS = {"story": "Enhancement", "bug": "Bug"}
PLUGIN_MANIFEST_URL = ("https://raw.githubusercontent.com/" + MARKETPLACE_REPO + "/main/"
                       "plugins/mps-git-flow/.claude-plugin/plugin.json")
VERSION_CHECK_TIMEOUT_SECONDS = 3
MANIFEST_MAX_BYTES = 64 * 1024
DEFAULT_SETTINGS_INDENT = 2
UPDATE_BLOCKER_ENV = ("DISABLE_UPDATES", "DISABLE_AUTOUPDATER", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
NONESSENTIAL_TRAFFIC_ENV = "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
FORCE_AUTOUPDATE_ENV = "FORCE_AUTOUPDATE_PLUGINS"
PLUGIN_UPDATE_COMMANDS = ("claude plugin marketplace update " + MARKETPLACE_NAME,
                          "claude plugin update " + PLUGIN_KEY)
# After removing every legacy marketplace: register the shared repo and install the plugin from it.
LEGACY_SOURCE_INSTALL_COMMANDS = ("claude plugin marketplace add " + MARKETPLACE_REPO,
                                  "claude plugin install " + PLUGIN_KEY)

# Files Unity (or the IDE) rewrites on its own. They never make the current branch "hold work" for phase
# pinning; they are still classified by the scope review and never auto-committed.
DEFAULT_GENERATED_PATTERNS = (
    "ProjectSettings/**", "Packages/packages-lock.json", "UserSettings/**", "*.csproj", "*.sln", "Library/**",
)
UNITY_VERSION_FILE = "ProjectSettings/ProjectVersion.txt"
# Keys the user must edit by hand in .env (env set refuses them): tokens, and patterns that relax phase pinning.
MANUAL_ONLY_KEYS = (KEY_GENERATED_PATTERNS,)
REQUIRED_CONNECTION_KEYS = (KEY_JIRA_URL, KEY_JIRA_PAT, KEY_GITLAB_URL, KEY_GITLAB_PAT)
DEFAULTS = {
    KEY_JIRA_URL: "https://jira-mps.mto.zing.vn",
    KEY_GITLAB_URL: "https://git-gst.mto.zing.vn",
    KEY_BRANCH_DEV: "develop",
    KEY_BRANCH_BETA_PREFIX: "release/",
    KEY_BRANCH_PROD: "master",
}

HTTP_TIMEOUT_SECONDS = 20
GITLAB_PER_PAGE = 100
JIRA_PAGE_SIZE = 50
MAX_PAGES = 50

MAX_FILE_BYTES = 5 * 1024 * 1024
SLUG_MAX_LEN = 50
JIRA_SUMMARY_MAX_LEN = 255
REVIEW_CAP_CHARS = 200 * 1000
UNTRACKED_FILE_CAP_CHARS = 20 * 1000
MAX_UTF8_BYTES_PER_CHAR = 4
BINARY_SNIFF_BYTES = 8192
RELEASE_BRANCHES_REPORTED = 5
FOREIGN_COMMITS_REPORTED = 10
TMP_DIRNAME = "mps-tmp"
BASE_CONFIG_NAME = "mps-base"
SCOPE_FILENAME = "scope.json"
BUNDLE_META_FILENAME = "bundle.json"
PUSHED_CONFIG_NAME = "mps-pushed"
STASH_MESSAGE = "mps-auto"
REVIEW_BUNDLE_FILENAME = "mps-review.md"
MIN_REDACT_LEN = 4

# Rule-based code review (runs next to the scope review on the same Bundle-ID snapshot).
CODE_REVIEW_BUNDLE_FILENAME = "mps-code-review.md"
CODE_REVIEW_FILENAME = "code_review.json"            # pending: written by review findings, consumed by git commit
COMMITTED_REVIEW_FILENAME = "committed_review.json"  # the review of the last commit, read by mr ensure
CODE_REVIEW_VERSION = 1
PROJECT_RULES_PATH = ".mps/review.md"
REVIEW_RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "review")
REVIEW_RULES_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates",
                                          "review.example.md")
SHIPPED_PROFILES = ("python", "unity-csharp", "web")
SEVERITIES = ("blocker", "major", "minor")
RULES_CAP_CHARS = 40 * 1000
DIFF_LINE_CAP_CHARS = 1000
PROJECT_RULES_MAX_CHARS = 100 * 1000
RULE_ID_MAX_LEN = 64
MR_REVIEW_MAX_ITEMS = 30
MR_PROBLEMS_SHOWN = 5
MR_PATHS_SHOWN = 10
WARNING_ITEMS_SHOWN = 10

ACCESS_LEVEL_MAINTAINER = 40
ACCESS_LEVEL_NAMES = {
    0: "No access", 5: "Minimal access", 10: "Guest", 15: "Planner", 20: "Reporter",
    30: "Developer", 40: "Maintainer", 50: "Owner",
}

SERVICE_NAMES = {"jira": "Jira", "gitlab": "GitLab"}

# ---------------------------------------------------------------------------
# Errors and output
# ---------------------------------------------------------------------------


class MpsError(Exception):
    """A handled failure: becomes {"ok": false, "error": code, "message": message, ...extra}."""

    def __init__(self, code, message, **extra):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.extra = extra


_SECRET_VALUES = []


def register_secret(value):
    """Remember a secret so it is masked in every output."""
    if value and len(value) >= MIN_REDACT_LEN and value not in _SECRET_VALUES:
        _SECRET_VALUES.append(value)


def redact(text):
    for value in _SECRET_VALUES:
        text = text.replace(value, "****")
    return text


def emit(payload):
    text = redact(json.dumps(payload, ensure_ascii=False, indent=2)) + "\n"
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(text)
    else:
        stream.write(text.encode("utf-8"))
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Pure helpers: .env
# ---------------------------------------------------------------------------

_ENV_LINE_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_INLINE_COMMENT_RE = re.compile(r"\s#")


def _parse_env_value(value):
    if len(value) >= 2 and value[0] in ("'", '"'):
        end = value.find(value[0], 1)
        if end > 0:
            return value[1:end]
    if value.startswith("#"):
        return ""
    match = _INLINE_COMMENT_RE.search(value)
    if match:
        value = value[:match.start()]
    return value.strip()


def parse_env(text):
    """Parse KEY=VALUE lines. Supports comments, `export`, optional quotes. Last duplicate wins."""
    result = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE_RE.match(line)
        if match:
            result[match.group(1)] = _parse_env_value(match.group(2))
    return result


def format_env_value(value):
    if '"' in value:
        raise MpsError("invalid_value", "Giá trị không được chứa dấu nháy kép (\").")
    if re.search(r"[\s#']", value):
        return '"' + value + '"'
    return value


def update_env_text(text, key, value):
    """Set KEY=value in .env text: replace the first occurrence, drop later duplicates, or append."""
    newline = "\r\n" if "\r\n" in text else "\n"
    pattern = re.compile(r"^\s*(?:export\s+)?" + re.escape(key) + r"\s*=")
    new_line = key + "=" + format_env_value(value)
    output = []
    replaced = False
    for line in text.splitlines():
        if pattern.match(line):
            if not replaced:
                output.append(new_line)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        output.append(new_line)
    return newline.join(output) + newline


_SAVE_TOKEN_STEP = ("Copy token vừa hiện ra, dán ngay sau dấu bằng ở dòng %s trong file .env rồi lưu file. KHÔNG dán "
                    "token vào khung chat.")


def _member_key_guide(key, jira_url, gitlab_url):
    """(label, steps, link) for one of MEMBER_KEYS. The click path in `steps` is authoritative; links are a shortcut."""
    if key == KEY_JIRA_PAT:
        return ("Token Jira (%s)" % key, [
            "Mở link bên dưới (hoặc trên Jira: bấm ảnh đại diện góc phải > Profile > Personal Access Tokens).",
            "Bấm Create token, đặt tên (ví dụ mps-git-flow), chọn ngày hết hạn theo quy định của team, bấm Create.",
            _SAVE_TOKEN_STEP % key,
        ], jira_url.rstrip("/") + JIRA_PAT_PAGE)
    if key == KEY_GITLAB_PAT:
        return ("Token GitLab (%s)" % key, [
            "Mở link bên dưới: GitLab bản mới tự điền sẵn tên token (mps-git-flow) và hai quyền api, write_repository.",
            "Nếu trang không điền sẵn: trên GitLab bấm ảnh đại diện > Edit profile > Access Tokens, bấm Add new token, "
            "đặt tên mps-git-flow, tích hai quyền (scope) api và write_repository.",
            "Chọn ngày hết hạn theo quy định của team rồi bấm Create.",
            _SAVE_TOKEN_STEP % key,
        ], gitlab_url.rstrip("/") + GITLAB_PAT_PAGE)
    return ("Mã board Jira của team (%s)" % key, [
        "Đây là mã board Jira của team, ví dụ MPS. Hỏi lead nếu chưa biết.",
        "Điền mã ngay sau dấu bằng ở dòng %s trong file .env rồi lưu file." % key,
        "Chưa biết mã thì cứ để trống: trợ lý sẽ gợi ý danh sách board để bạn chọn.",
    ], None)


def env_fill_guide(cfg_values, jira_url, gitlab_url, keys=None, token_rejected=False):
    """Ordered [{key, label, steps, link}] telling a member how to fill .env by hand.

    keys None = the MEMBER_KEYS still blank in `cfg_values`. Other keys (deleted lines) get one step that restores
    the template default. `token_rejected` adds a first step saying the current token is wrong or expired.
    Token values are only tested for blankness, never copied into the output.
    """
    if keys is None:
        keys = [k for k in MEMBER_KEYS if not (cfg_values.get(k) or "").strip()]
    order = list(MEMBER_KEYS) + [k for k in KNOWN_KEYS if k not in MEMBER_KEYS]
    ordered = [k for k in order if k in keys] + [k for k in keys if k not in order]
    guide = []
    for key in ordered:
        if key in MEMBER_KEYS:
            label, steps, link = _member_key_guide(key, jira_url, gitlab_url)
        elif key in DEFAULTS:
            label, steps, link = key, ["Khôi phục dòng mặc định trong file .env: %s=%s" % (key, DEFAULTS[key])], None
        else:
            label, steps, link = key, ["Điền %s trong file .env theo hướng dẫn của lead." % key], None
        if token_rejected and key.endswith(SECRET_KEY_SUFFIX):
            steps = ["Token hiện tại sai hoặc đã hết hạn - tạo token mới theo các bước dưới và thay vào dòng %s trong "
                     "file .env." % key] + steps
        guide.append({"key": key, "label": label, "steps": steps, "link": link})
    return guide


# ---------------------------------------------------------------------------
# Pure helpers: naming
# ---------------------------------------------------------------------------

NAMING_RULES = {
    "story": ("feature/", "feat: "),
    "bug": ("bugfix/", "fix: "),
    "hotfix": ("hotfix/", "fix: "),
}
_ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-[0-9]+$")


def normalize_issue_key(key):
    normalized = (key or "").strip().upper()
    if not _ISSUE_KEY_RE.match(normalized):
        raise MpsError("invalid_ticket_key", "Mã ticket Jira không hợp lệ: '%s'. Ví dụ đúng: MPS-123, ART-12." % key)
    return normalized


def slugify(text, max_len=SLUG_MAX_LEN):
    """Vietnamese-aware ASCII slug: 'Sửa lỗi Đặc biệt!' -> 'sua-loi-dac-biet'."""
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = stripped.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if len(slug) > max_len:
        cut = slug[:max_len]
        if slug[max_len] != "-":
            # The cut landed inside a word: back off to the previous dash if there is one.
            dash = cut.rfind("-")
            if dash > 0:
                cut = cut[:dash]
        slug = cut.strip("-")
    return slug


def build_names(key, kind, title):
    """Branch / commit / MR names for kind story|bug|hotfix."""
    if kind not in NAMING_RULES:
        raise MpsError("invalid_type", "Loại không hợp lệ: '%s' (chỉ story, bug, hotfix)." % kind)
    issue_key = normalize_issue_key(key)
    clean_title = " ".join((title or "").split())
    if not clean_title:
        raise MpsError("empty_title", "Tiêu đề ticket đang trống.")
    branch_prefix, commit_prefix = NAMING_RULES[kind]
    slug = slugify(clean_title)
    branch = branch_prefix + issue_key + ("-" + slug if slug else "")
    commit_message = commit_prefix + issue_key + " " + clean_title
    return {
        "key": issue_key,
        "type": kind,
        "branch": branch,
        "commit_message": commit_message,
        "mr_title": commit_message[len(commit_prefix):],
        "mr_description": "Close " + issue_key,
    }


# ---------------------------------------------------------------------------
# Pure helpers: AI attribution
# ---------------------------------------------------------------------------

# The exact forms an AI assistant appends to commits / MR descriptions, and nothing else: a human co-author named
# Claude ("Claude Martin <claude.martin@...>"), a subject such as "claude-api: bump SDK" or a sentence mentioning
# claude are never matched.
_AI_ATTRIBUTION_RES = (
    # Any co-author trailer with an anthropic.com address.
    re.compile(r"^\s*co-authored-by\s*:.*<[^>]*@anthropic\.com>\s*$", re.IGNORECASE),
    # "Co-Authored-By: Claude", "Claude Code", "Claude Opus 5.5", ... with an optional address.
    re.compile(r"^\s*co-authored-by\s*:\s*claude(\s+(code|opus|sonnet|haiku|fable|\d[\w.]*))*\s*(<[^>]*>)?\s*$",
               re.IGNORECASE),
    # "Generated with [Claude Code](https://...)" / "Generated by Claude Code", optionally after an emoji.
    re.compile(r"^\s*(?:[^\w\s]+\s*)?generated\s+(with|by)\s+\[?claude(\s+code)?\]?(\(https?://[^)]*\))?\.?\s*$",
               re.IGNORECASE | re.UNICODE),
    re.compile(r"^\s*claude-session\s*:", re.IGNORECASE),
    re.compile(r"^\s*https?://claude\.ai/code/session[\w/-]*\s*$", re.IGNORECASE),
)


def strip_ai_attribution(text):
    """Remove Claude / AI attribution lines. Returns (text, removed).

    Only matching lines are dropped; trailing blank lines are then trimmed. Text without such lines is returned
    unchanged (removed False).
    """
    lines = (text or "").splitlines()
    kept = [line for line in lines if not any(regex.search(line) for regex in _AI_ATTRIBUTION_RES)]
    if len(kept) == len(lines):
        return text or "", False
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept), True


# ---------------------------------------------------------------------------
# Pure helpers: project integration
# ---------------------------------------------------------------------------

_BOM = chr(0xFEFF)


def parse_settings_text(text):
    """.claude/settings.json text -> dict. A leading BOM is accepted; empty or whitespace-only text is {}."""
    if text.startswith(_BOM):
        text = text[len(_BOM):]
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        line = getattr(exc, "lineno", None)
        column = getattr(exc, "colno", None)
        raise MpsError("settings_invalid_json",
                       "File %s không phải JSON hợp lệ (dòng %s, cột %s). Chưa sửa gì. Hãy nhờ developer sửa file rồi "
                       "chạy lại." % (PROJECT_SETTINGS_PATH, line, column), line=line, column=column)
    if not isinstance(data, dict):
        raise MpsError("settings_not_object", "File %s phải là một object JSON ({...}). Chưa sửa gì. Hãy nhờ developer "
                                              "kiểm tra." % PROJECT_SETTINGS_PATH)
    return data


def _settings_conflict(key):
    return MpsError("settings_conflict",
                    "Mục %s trong %s có dạng không mong đợi nên không thể tự thêm plugin. Chưa sửa gì. Hãy nhờ "
                    "developer kiểm tra." % (key, PROJECT_SETTINGS_PATH), key=key)


def _expected_marketplace_source():
    return {"source": "github", "repo": MARKETPLACE_REPO}


def _describe_source(source):
    if isinstance(source, dict):
        for field in ("repo", "url", "path"):
            if source.get(field):
                return str(source[field])
    return json.dumps(source, ensure_ascii=False, sort_keys=True)


def merge_project_settings(settings):
    """Add the marketplace (auto-update on) and enable the plugin. Returns (new_settings, changes, warnings).

    The input is never mutated; existing keys keep their order and new keys are appended. A marketplace entry that
    still points to a legacy repo (LEGACY_MARKETPLACE_REPOS) is moved to MARKETPLACE_REPO, keeping its `ref`; an
    entry with another source (a fork, a local directory) is kept as it is and reported.
    """
    merged = copy.deepcopy(settings)
    changes = []
    warnings = []
    marketplaces = merged.setdefault("extraKnownMarketplaces", {})
    if not isinstance(marketplaces, dict):
        raise _settings_conflict("extraKnownMarketplaces")
    entry = marketplaces.get(MARKETPLACE_NAME)
    if entry is None and MARKETPLACE_NAME not in marketplaces:
        marketplaces[MARKETPLACE_NAME] = {"source": _expected_marketplace_source(), "autoUpdate": True}
        changes.append("marketplace_added")
    else:
        if not isinstance(entry, dict):
            raise _settings_conflict("extraKnownMarketplaces." + MARKETPLACE_NAME)
        source = entry.get("source")
        unpinned = dict((k, v) for k, v in source.items() if k != "ref") if isinstance(source, dict) else source
        if points_to_legacy_repo(unpinned):
            # Every form the legacy check recognises is moved, so `legacy_project_source` always has a fix.
            ref = source.get("ref")
            entry["source"] = dict(_expected_marketplace_source(), **({"ref": ref} if ref is not None else {}))
            changes.append("marketplace_source_migrated")
        elif unpinned != _expected_marketplace_source():
            warnings.append({"code": "marketplace_source_differs", "source": source,
                             "message": "Marketplace %s trong %s đang trỏ tới nguồn khác (%s); giữ nguyên nguồn đó."
                                        % (MARKETPLACE_NAME, PROJECT_SETTINGS_PATH, _describe_source(source))})
        if entry.get("autoUpdate") is not True:
            entry["autoUpdate"] = True
            changes.append("auto_update_enabled")
    enabled = merged.setdefault("enabledPlugins", {})
    if not isinstance(enabled, dict):
        raise _settings_conflict("enabledPlugins")
    if enabled.get(PLUGIN_KEY) is not True:
        enabled[PLUGIN_KEY] = True
        changes.append("plugin_enabled")
    _merge_attribution(merged, changes, warnings)
    return merged, changes, warnings


def _merge_attribution(merged, changes, warnings):
    """Hide Claude Code's commit / PR attribution for the project. Only missing sub-keys are added; values the
    project already set are kept (and reported when they still add attribution). `false` already hides it all."""
    if "attribution" not in merged:
        merged["attribution"] = dict(HIDDEN_ATTRIBUTION)
        changes.append("attribution_disabled")
        return
    attribution = merged["attribution"]
    if attribution is False:
        return
    if not isinstance(attribution, dict):
        raise _settings_conflict("attribution")
    missing = [key for key in HIDDEN_ATTRIBUTION if key not in attribution]
    for key in missing:
        attribution[key] = HIDDEN_ATTRIBUTION[key]
    if missing:
        changes.append("attribution_disabled")
    kept = [key for key in ("commit", "pr") if attribution.get(key)]
    if attribution.get("sessionUrl") is True:
        kept.append("sessionUrl")
    if kept:
        warnings.append({"code": "attribution_kept", "keys": kept,
                         "message": "Mục attribution trong %s đang đặt sẵn nội dung ghi công (%s); giữ nguyên. Script "
                                    "vẫn tự gỡ các dòng ghi công AI khỏi commit và merge request."
                                    % (PROJECT_SETTINGS_PATH, ", ".join(kept))})


_INDENTED_LINE_RE = re.compile(r"\n([ \t]+)\S")


def detect_json_indent(text):
    """Indent unit of existing JSON text (a number of spaces, or a tab); DEFAULT_SETTINGS_INDENT when nothing is
    indented. The first indented line of pretty-printed JSON is one level deep."""
    match = _INDENTED_LINE_RE.search(text or "")
    if not match:
        return DEFAULT_SETTINGS_INDENT
    unit = match.group(1)
    return "\t" if "\t" in unit else len(unit)


def render_settings_json(settings, newline, indent=DEFAULT_SETTINGS_INDENT):
    """Indented JSON (spaces or a tab), non-ASCII kept as is, `newline` line endings, ending with a newline."""
    return json.dumps(settings, indent=indent, ensure_ascii=False).replace("\n", newline) + newline


def project_integration_status(settings):
    """"integrated" when the settings enable the plugin, else "missing"."""
    enabled = settings.get("enabledPlugins") if isinstance(settings, dict) else None
    if isinstance(enabled, dict) and enabled.get(PLUGIN_KEY) is True:
        return "integrated"
    return "missing"


def pinned_marketplace_ref(settings):
    """The `ref` the project pins the mps-cdci-agents marketplace source to (e.g. "v0.1.1"), or None."""
    marketplaces = settings.get("extraKnownMarketplaces") if isinstance(settings, dict) else None
    entry = marketplaces.get(MARKETPLACE_NAME) if isinstance(marketplaces, dict) else None
    source = entry.get("source") if isinstance(entry, dict) else None
    ref = source.get("ref") if isinstance(source, dict) else None
    return ref.strip() if isinstance(ref, str) and ref.strip() else None


def points_to_legacy_repo(source):
    """True when a marketplace source fetches one of LEGACY_MARKETPLACE_REPOS: a `github` source with that repo or a
    git URL ending in it (https or ssh, with or without `.git`). GitHub names ignore case."""
    if not isinstance(source, dict):
        return False
    target = source.get("repo") if source.get("source") == "github" else source.get("url")
    if not isinstance(target, str):
        return False
    text = target.strip().lower()
    if text.endswith(".git"):
        text = text[:-len(".git")]
    return any(text == repo or text.endswith("/" + repo) or text.endswith(":" + repo)
               for repo in LEGACY_MARKETPLACE_REPOS)


def known_marketplaces_path(environ):
    plugins_dir = environ.get(PLUGINS_DIR_ENV)
    if not plugins_dir:
        config_dir = environ.get(CLAUDE_CONFIG_DIR_ENV) or os.path.join(os.path.expanduser("~"), ".claude")
        plugins_dir = os.path.join(config_dir, "plugins")
    return os.path.join(plugins_dir, KNOWN_MARKETPLACES_FILE)


def load_known_marketplaces(environ):
    """{name: entry} of the marketplaces Claude Code registered on this machine; {} when the file is missing or
    unreadable (an unknown state never blocks the user)."""
    try:
        data = json.loads(read_text_file(known_marketplaces_path(environ)))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def legacy_plugin_source_status(known, settings):
    """(status, names) for the marketplaces of this machine that still fetch from a legacy repo.

    status is None (none left), "project" (the project's .claude/settings.json itself still declares the legacy
    repo: removing it on this machine would only bring it back, so the lead has to run `project setup` first) or
    "machine" (this user has to remove it). names lists the legacy marketplaces, sorted.
    """
    names = sorted(name for name, entry in known.items()
                   if isinstance(entry, dict) and points_to_legacy_repo(entry.get("source")))
    if not names:
        return None, []
    return ("project" if project_declares_legacy_source(settings) else "machine"), names


def project_declares_legacy_source(settings):
    """True when the project's .claude/settings.json declares the marketplace with a legacy repo."""
    marketplaces = settings.get("extraKnownMarketplaces") if isinstance(settings, dict) else None
    declared = marketplaces.get(MARKETPLACE_NAME) if isinstance(marketplaces, dict) else None
    return isinstance(declared, dict) and points_to_legacy_repo(declared.get("source"))


def legacy_plugin_source_error(names):
    commands = ["claude plugin marketplace remove " + name for name in names] + list(LEGACY_SOURCE_INSTALL_COMMANDS)
    steps = ", ".join("`/plugin marketplace remove %s`" % name for name in names)
    return MpsError(
        "plugin_source_legacy",
        "Team đã thống nhất đưa plugin mps-git-flow về repo dùng chung của tổ chức (%s), nên bạn cần gỡ bản cài từ "
        "repo cá nhân của hungbt (%s) thì mới dùng tiếp được nhé. Chỉ mất khoảng một phút: trong Claude Code gõ lần "
        "lượt %s, `/plugin marketplace add %s`, `/plugin install %s`, rồi `/reload-plugins`. Cảm ơn bạn!"
        % (MARKETPLACE_REPO, ", ".join(LEGACY_MARKETPLACE_REPOS), steps, MARKETPLACE_REPO, PLUGIN_KEY),
        marketplaces=names, commands=commands)


def legacy_project_source_warning():
    return {"code": "legacy_project_source",
            "message": "Project này vẫn khai báo plugin mps-git-flow từ repo cá nhân cũ của hungbt (%s). Team đã "
                       "chuyển plugin về repo dùng chung %s: nhờ lead nói \"tích hợp plugin vào project\" (lệnh "
                       "project setup) rồi commit .claude/settings.json để cả team tự chuyển sang."
                       % (", ".join(LEGACY_MARKETPLACE_REPOS), MARKETPLACE_REPO)}


def _settings_of_current_project():
    """.claude/settings.json of the project the command runs in, or None (not in a git project, missing file)."""
    try:
        return load_project_settings(find_project_root())
    except MpsError:
        return None


def ensure_plugin_source_current(group, command, environ):
    """Stop every command (except LEGACY_SOURCE_EXEMPT_COMMANDS) while this machine still installs the plugin from
    a legacy repo the user can remove themselves."""
    if (group, command) in LEGACY_SOURCE_EXEMPT_COMMANDS:
        return
    known = load_known_marketplaces(environ)
    if not any(isinstance(entry, dict) and points_to_legacy_repo(entry.get("source")) for entry in known.values()):
        return  # the usual case: no need to look for the project
    status, names = legacy_plugin_source_status(known, _settings_of_current_project())
    if status == "machine":
        raise legacy_plugin_source_error(names)


# ---------------------------------------------------------------------------
# Pure helpers: phase rules and release branches
# ---------------------------------------------------------------------------

PHASES = ("dev", "beta", "production")
TICKET_TYPES = ("story", "bug")
KIND_TO_NAMING_TYPE = {"feature": "story", "bugfix": "bug", "hotfix": "hotfix"}


def access_level_name(level):
    if level is None:
        return None
    return ACCESS_LEVEL_NAMES.get(level, str(level))


def production_warning(access_level):
    text = ("CẢNH BÁO: hotfix đưa code thẳng vào nhánh production (master) rất rủi ro — nếu có lỗi, "
            "người dùng thật sẽ bị ảnh hưởng ngay. Việc này nên để developer làm; thành viên không nên tự làm.")
    if access_level is None:
        return text + " (Không xác định được quyền của bạn trên GitLab.)"
    if access_level < ACCESS_LEVEL_MAINTAINER:
        return text + (" Quyền GitLab của bạn trên project là %s (%d), thấp hơn Maintainer (40): bạn nhiều khả năng "
                       "không merge được vào master. Rất nên nhờ developer/maintainer làm thay."
                       % (access_level_name(access_level), access_level))
    return text


def plan_phase(phase, ticket_type, branches, access_level=None):
    """Phase rules. branches = {"dev", "beta_prefix", "prod"}. Beta base/target are resolved later (latest release)."""
    if phase not in PHASES:
        raise MpsError("invalid_phase", "Giai đoạn không hợp lệ: '%s' (chỉ dev, beta, production)." % phase)
    if ticket_type not in TICKET_TYPES:
        raise MpsError("invalid_type", "Loại ticket không hợp lệ: '%s' (chỉ story, bug)." % ticket_type)
    plan = {"phase": phase, "ticket_type": ticket_type, "needs_release_lookup": False}
    if phase == "dev":
        plan["kind"] = "feature" if ticket_type == "story" else "bugfix"
        plan["base_branch"] = branches["dev"]
        plan["target_branch"] = branches["dev"]
    elif phase == "beta":
        if ticket_type == "story":
            raise MpsError(
                "phase_rule_violation",
                "Giai đoạn beta chỉ nhận sửa lỗi (bug). Tính năng mới (story) phải đưa vào giai đoạn dev "
                "(nhánh %s)." % branches["dev"],
                phase=phase, ticket_type=ticket_type)
        plan["kind"] = "bugfix"
        plan["base_branch"] = None
        plan["target_branch"] = None
        plan["needs_release_lookup"] = True
        plan["note"] = ("Không tạo MR back-merge về %s: team sẽ back-merge khi kết thúc giai đoạn beta."
                        % branches["dev"])
    else:
        if ticket_type == "story":
            raise MpsError(
                "phase_rule_violation",
                "Production chỉ nhận hotfix cho lỗi (bug). Tính năng mới (story) phải đi qua giai đoạn dev.",
                phase=phase, ticket_type=ticket_type)
        plan["kind"] = "hotfix"
        plan["base_branch"] = branches["prod"]
        plan["target_branch"] = branches["prod"]
        plan["warning"] = production_warning(access_level)
        plan["requires_explicit_confirmation"] = True
        plan["access_level"] = access_level
        plan["access_level_name"] = access_level_name(access_level)
    plan["naming_type"] = KIND_TO_NAMING_TYPE[plan["kind"]]
    return plan


TICKET_BRANCH_PREFIXES = ("feature/", "bugfix/", "hotfix/")


def phase_of_branch(name, branches):
    """develop -> dev, release/* -> beta, master -> production, anything else -> None."""
    if not name:
        return None
    if name == branches["dev"]:
        return "dev"
    if name == branches["prod"]:
        return "production"
    if name.startswith(branches["beta_prefix"]):
        return "beta"
    return None


_TICKET_BRANCH_KEY_RE = re.compile(r"^(?:feature|bugfix|hotfix)/([A-Za-z][A-Za-z0-9_]*-[0-9]+)")


def ticket_key_of_branch(branch):
    """'bugfix/MPS-2-sua-loi' -> 'MPS-2' (None for non-ticket branches)."""
    match = _TICKET_BRANCH_KEY_RE.match(branch or "")
    return match.group(1).upper() if match else None


def unique_protected_branch(remote_branches, branches):
    """Of the origin branches pointing exactly at a detached HEAD, the single develop/master/release one, else None."""
    protected = sorted(set(b for b in remote_branches if phase_of_branch(b, branches)))
    return protected[0] if len(protected) == 1 else None


def detect_branch_context(branch, branches, recorded_base, key=None, recorded_base_exists=True, detached_at=None):
    """Where is the user working? The MR must go back into the branch the work started from.

    branch None = detached HEAD; `detached_at` is then the unique protected origin branch pointing at HEAD.
    A ticket branch pins its recorded base only when it belongs to the current ticket (`key`) and that base
    still exists on origin.
    """
    context = {"current_branch": branch, "recorded_base": recorded_base,
               "branch_ticket_key": ticket_key_of_branch(branch), "recorded_base_gone": False,
               "detached": branch is None}
    phase = None
    base = None
    if branch is None:
        phase = phase_of_branch(detached_at, branches)
        base = detached_at if phase else None
        role = phase or "detached"
    elif phase_of_branch(branch, branches):
        role = phase = phase_of_branch(branch, branches)
        base = branch
    elif (branch.startswith(TICKET_BRANCH_PREFIXES) and phase_of_branch(recorded_base, branches)
          and (key is None or context["branch_ticket_key"] == key)):
        if recorded_base_exists:
            role, phase, base = "ticket", phase_of_branch(recorded_base, branches), recorded_base
        else:
            role = "other"
            context["recorded_base_gone"] = True
    else:
        role = "other"
    context.update({"current_branch_role": role, "detected_phase": phase, "detected_base": base})
    return context


def reconcile_phase(context, requested, dirty):
    """Return (phase, phase_source, pinned). Never silently moves changes made on one phase's branch elsewhere.

    The current branch pins the phase only when work exists on it (changes or unpushed commits) or when it is the
    current ticket's own branch. On a clean tree the user's requested phase wins.
    """
    detected = context["detected_phase"]
    role = context["current_branch_role"]
    if role == "detached" and dirty:
        raise MpsError("detached_head", "Bạn đang có thay đổi nhưng không đứng trên nhánh nào (detached HEAD), nên không "
                                        "biết thay đổi thuộc nhánh nào. Hãy nhờ developer giúp đưa thay đổi về đúng nhánh.")
    if context.get("recorded_base_gone") and dirty:
        raise MpsError("recorded_base_gone",
                       "Nhánh %s được tạo từ %s nhưng nhánh %s không còn trên GitLab. Thay đổi đang dở trên nhánh này "
                       "cần developer giúp chuyển sang đúng nhánh." % (
                           context["current_branch"], context["recorded_base"], context["recorded_base"]),
                       recorded_base=context["recorded_base"], current_branch=context["current_branch"])
    pinned = bool(detected) and (role == "ticket" or dirty)
    if pinned:
        if requested and requested != detected:
            raise MpsError("phase_conflict",
                           "Bạn đang làm việc trên nhánh %s (giai đoạn %s) nhưng lại chọn giai đoạn %s. Thay đổi làm "
                           "trên nhánh nào phải gộp về đúng nhánh đó; chuyển thay đổi sang giai đoạn khác cần developer "
                           "giúp." % (context["current_branch"] or context["detected_base"], detected, requested),
                           detected_phase=detected, requested_phase=requested, current_branch=context["current_branch"])
        return detected, "detected", True
    if requested:
        return requested, ("requested_clean_tree" if detected else "requested"), False
    raise MpsError("phase_required", "Chưa xác định được giai đoạn (nhánh hiện tại: %s, chưa có thay đổi nào gắn với "
                                     "nhánh này). Hãy hỏi người dùng: dev, beta hay production."
                   % (context["current_branch"] or "detached HEAD"),
                   current_branch=context["current_branch"], current_branch_role=role, detected_phase=detected)


def check_release_branch(current, ordered_names):
    """The release branch the work is pinned to must still exist on GitLab; warn if it is not the newest one."""
    if current not in ordered_names:
        raise MpsError("release_branch_gone", "Nhánh beta %s không còn trên GitLab (có thể đã kết thúc và bị xoá). Không "
                                              "thể tạo merge request vào nhánh này — hãy nhờ developer." % current,
                       branch=current, release_branches=ordered_names[:RELEASE_BRANCHES_REPORTED])
    if current == ordered_names[0]:
        return None
    return {"code": "not_latest_release", "latest": ordered_names[0], "branch": current,
            "message": "Bạn đang làm trên %s, nhánh beta này vẫn còn trên GitLab nhưng không phải nhánh mới nhất (%s). MR "
                       "sẽ vào đúng %s. Hãy xác nhận với người dùng đây là chủ ý." % (current, ordered_names[0], current)}


def is_protected_branch(name, branches):
    return bool(name) and (name == branches["dev"] or name == branches["prod"]
                           or name.startswith(branches["beta_prefix"]))


def parse_release_version(name, prefix):
    suffix = name[len(prefix):] if name.startswith(prefix) else name
    numbers = re.findall(r"[0-9]+", suffix)
    if not numbers:
        return None
    return tuple(int(n) for n in numbers)


_ISO_FRACTION_RE = re.compile(r"^(.*T[0-9]{2}:[0-9]{2}:[0-9]{2})\.([0-9]+)(.*)$")
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


def parse_iso_datetime(value):
    """Parse GitLab ISO 8601 timestamps on Python 3.8 (no 'Z', fractions must be 6 digits)."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    match = _ISO_FRACTION_RE.match(text)
    if match:
        text = match.group(1) + "." + (match.group(2) + "000000")[:6] + match.group(3)
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _branch_date(branch):
    return parse_iso_datetime(branch.get("committed_date")) or _EPOCH


def release_sort_method(branches, prefix):
    candidates = [b for b in branches if b.get("name", "").startswith(prefix)]
    if candidates and all(parse_release_version(b["name"], prefix) is not None for b in candidates):
        return "version"
    return "committed_date"


def sort_release_branches(branches, prefix):
    """Newest first. branches: [{"name", "committed_date"}]. Version order if every suffix has digits, else by date."""
    candidates = [b for b in branches if b.get("name", "").startswith(prefix)]
    if release_sort_method(candidates, prefix) == "version":
        return sorted(candidates, key=lambda b: (parse_release_version(b["name"], prefix), _branch_date(b)),
                      reverse=True)
    return sorted(candidates, key=_branch_date, reverse=True)


_PLUGIN_VERSION_RE = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)$")


def parse_plugin_version(text):
    """'0.1.10' / 'v0.2.0' -> (0, 1, 10); anything else (None, '', '1.x', '1.2') -> None."""
    if not isinstance(text, str):
        return None
    match = _PLUGIN_VERSION_RE.match(text.strip())
    return tuple(int(n) for n in match.groups()) if match else None


def is_newer_version(latest, running):
    """True if version string `latest` is newer than `running`; False if either does not parse."""
    latest_tuple = parse_plugin_version(latest)
    running_tuple = parse_plugin_version(running)
    if latest_tuple is None or running_tuple is None:
        return False
    return latest_tuple > running_tuple


def update_blockers(environ):
    """Environment variables (set, non-empty) that stop Claude Code from updating plugins by itself."""
    if environ.get(FORCE_AUTOUPDATE_ENV) == "1":
        return []
    return [name for name in UPDATE_BLOCKER_ENV if environ.get(name)]


def plugin_outdated_warning(latest, running, blockers):
    return {"code": "plugin_outdated", "latest": latest, "running": running, "update_blockers": blockers,
            "commands": list(PLUGIN_UPDATE_COMMANDS),
            "message": "Đã có phiên bản mới của plugin mps-git-flow (%s; máy bạn đang dùng %s). Trợ lý sẽ cập nhật "
                       "giúp; bản mới có hiệu lực sau khi gõ /reload-plugins hoặc mở lại Claude Code."
                       % (latest, running)}


def project_not_integrated_warning():
    return {"code": "project_not_integrated",
            "message": "Project này chưa khai báo plugin mps-git-flow trong %s nên đồng đội không tự có plugin và bản "
                       "cập nhật. Lead của dự án có thể nhờ Claude \"tích hợp plugin vào project\"."
                       % PROJECT_SETTINGS_PATH}


# ---------------------------------------------------------------------------
# Pure helpers: secrets, git output parsing
# ---------------------------------------------------------------------------

# (rule, regex, confirmable). Confirmable findings may be false positives (e.g. `token = getToken()`):
# the agent must stop and show them, and may continue only if the user confirms they are not real secrets.
SECRET_RULES = (
    ("gitlab_token", re.compile(r"glpat-[0-9A-Za-z_\-]{8,}"), False),
    ("private_key", re.compile(r"-----BEGIN .*PRIVATE KEY"), False),
    ("mps_pat", re.compile(r"MPS_[A-Z0-9_]*_PAT\s*=\s*['\"]?[^\s'\"#]+"), False),
    ("generic_secret", re.compile(r"(?i)(password|secret|token)\s*[:=]\s*\S{6,}"), True),
)
_HUNK_RE = re.compile(r"^@@ -[0-9]+(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@")


def scan_line(path, line_no, content):
    findings = []
    for rule, regex, confirmable in SECRET_RULES:
        if regex.search(content):
            findings.append({"file": path, "line": line_no, "rule": rule, "confirmable": confirmable})
    return findings


def scan_text(path, text):
    findings = []
    for index, line in enumerate(text.splitlines()):
        findings.extend(scan_line(path, index + 1, line))
    return findings


def _diff_header_path(raw):
    path = raw.strip()
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        path = path[1:-1]
    if path == "/dev/null":
        return None
    return path[2:] if path.startswith("b/") else path


def scan_secrets(diff_text):
    """Scan ADDED lines of a unified diff. Returns [{file, line, rule, confirmable}] (never the secret itself)."""
    findings = []
    current_file = None
    old_left = 0
    new_left = 0
    new_line_no = 0
    for line in diff_text.splitlines():
        if old_left > 0 or new_left > 0:
            if line.startswith("+"):
                findings.extend(scan_line(current_file, new_line_no, line[1:]))
                new_line_no += 1
                new_left -= 1
            elif line.startswith("-"):
                old_left -= 1
            elif line.startswith("\\"):
                pass
            else:
                new_line_no += 1
                new_left -= 1
                old_left -= 1
            continue
        if line.startswith("+++ "):
            current_file = _diff_header_path(line[4:])
            continue
        match = _HUNK_RE.match(line)
        if match:
            old_left = int(match.group(1)) if match.group(1) is not None else 1
            new_line_no = int(match.group(2))
            new_left = int(match.group(3)) if match.group(3) is not None else 1
    return findings


_WILDCARD_CHARS = ("*", "?", "[")


def is_valid_generated_pattern(pattern):
    """A user pattern must start with a literal folder or file name ('Assets/Gen/**', 'yarn.lock').

    Wildcard-only or wildcard-first patterns ('*', '**/*', '*/Gen/**', '*.cs') would hide real work from phase
    pinning, so they are rejected.
    """
    segments = [s for s in pattern.strip("/").split("/") if s]
    return bool(segments) and not any(ch in segments[0] for ch in _WILDCARD_CHARS)


def parse_generated_patterns(extra):
    """MPS_GENERATED_PATTERNS (comma-separated) -> (valid normalized patterns, rejected patterns as written)."""
    valid = []
    rejected = []
    for raw in (p.strip() for p in (extra or "").split(",")):
        if not raw:
            continue
        normalized = raw.replace("\\", "/").strip("/")
        if is_valid_generated_pattern(normalized):
            valid.append(normalized)
        else:
            rejected.append(raw)
    return valid, rejected


def generated_rules(unity_roots, extra_patterns):
    """[(pattern, roots)]: Unity defaults apply inside Unity project roots only (none -> not applied at all);
    the user's extra patterns apply from the repo root ("") and from every Unity project root."""
    roots = tuple(sorted(set(unity_roots)))
    rules = [(p, roots) for p in DEFAULT_GENERATED_PATTERNS] if roots else []
    extra_roots = tuple(sorted(set(("",) + roots)))
    rules.extend((p, extra_roots) for p in extra_patterns)
    return rules


def _glob_regex(pattern):
    """'**' = any characters (also '/'), '*' = any characters except '/', '?' = one character except '/'."""
    parts = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("^" + "".join(parts) + "$")


def _relative_to(path, root):
    if not root:
        return path
    prefix = root + "/"
    return path[len(prefix):] if path.startswith(prefix) else None


def is_generated_path(path, rules):
    """True if `path` matches a rule from `generated_rules`.

    Patterns are anchored to their roots: 'ProjectSettings/**' matches '<unity root>/ProjectSettings/...' but not
    'Assets/Plugins/ProjectSettings/x.cs'. A pattern without '/' ('*.csproj') matches only files directly inside
    one of its roots (where Unity writes them).
    """
    normalized = (path or "").replace("\\", "/").strip("/")
    for pattern, roots in rules:
        regex = _glob_regex(pattern.replace("\\", "/").strip("/"))
        for root in roots:
            relative = _relative_to(normalized, root.replace("\\", "/").strip("/"))
            if relative is None or ("/" not in pattern and "/" in relative):
                continue
            if regex.match(relative):
                return True
    return False


def is_env_file(path):
    name = os.path.basename((path or "").replace("\\", "/").rstrip("/"))
    if name == ".env.example":
        return False
    return name == ".env" or name.startswith(".env.")


UNMERGED_CODES = frozenset(["DD", "AU", "UD", "UA", "DU", "AA", "UU"])


def parse_porcelain_z(output):
    """Parse `git status --porcelain=v1 -z`. Rename sources are listed in `staged` too; `renames` maps new -> old."""
    entries = output.split("\0")
    result = {"staged": [], "unstaged": [], "untracked": [], "unmerged": [], "renames": {}}
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        x_code, y_code, path = entry[0], entry[1], entry[3:]
        code = x_code + y_code
        if x_code in "RC" or y_code in "RC":
            original = entries[index] if index < len(entries) else ""
            index += 1
            if x_code == "R" and original:
                result["staged"].append(original)
                result["renames"][path] = original
        if code == "??":
            result["untracked"].append(path)
        elif code == "!!":
            continue
        elif code in UNMERGED_CODES:
            result["unmerged"].append(path)
        else:
            if x_code != " ":
                result["staged"].append(path)
            if y_code != " ":
                result["unstaged"].append(path)
    return result


def parse_check_attr_z(output):
    """Parse `git check-attr -z <attr> --stdin` output (path NUL attr NUL value NUL ...) into {path: value}."""
    parts = output.split("\0")
    result = {}
    for index in range(0, len(parts) - 2, 3):
        result[parts[index]] = parts[index + 2]
    return result


def normalize_target_path(path):
    """CLI file argument -> root-relative POSIX path ('./a\\b/' -> 'a/b', '' -> '.')."""
    return posixpath.normpath((path or ".").replace("\\", "/"))


def path_in_targets(path, targets):
    """True if `path` equals one of the normalized targets or lies inside one of them (a folder, or '.')."""
    for target in targets:
        if target == "." or path == target or path.startswith(target + "/"):
            return True
    return False


def expand_rename_sources(targets, renames):
    """Keep both halves of every staged rename that touches a target (new path -> also the old path's deletion,
    and vice versa), so a rename is never committed as only an add or only a delete."""
    expanded = list(targets)
    for new_path, old_path in renames.items():
        if path_in_targets(new_path, targets) or path_in_targets(old_path, targets):
            for path in (new_path, old_path):
                if not path_in_targets(path, expanded):
                    expanded.append(path)
    return expanded


def mentions_key(subject, key):
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?![0-9])", subject or "", re.IGNORECASE) is not None


def find_foreign_commits(log_output, key):
    """`git log --format=%H%x09%s` lines -> [{sha, subject}] of commits whose subject does not mention KEY."""
    foreign = []
    for line in log_output.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\t")
        if not mentions_key(subject, key):
            foreign.append({"sha": sha[:12], "subject": subject})
    return foreign


def _host_of(url):
    try:
        host = urllib.parse.urlsplit(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


_SCP_REMOTE_RE = re.compile(r"^(?:[^@/]+@)?([^:/]+):(.+)$")


def parse_remote(remote_url):
    """Return (scheme, host, path) for https/ssh/scp-style remotes, or (None, None, None)."""
    url = (remote_url or "").strip()
    if not url:
        return None, None, None
    if "://" in url:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname.lower() if parts.hostname else None
        return parts.scheme.lower(), host, parts.path
    match = _SCP_REMOTE_RE.match(url)
    if match:
        return "ssh", match.group(1).lower(), match.group(2)
    return None, None, None


def parse_remote_project_path(remote_url, gitlab_url):
    """'https://host/group/sub/proj.git' -> 'group/sub/proj' when the host matches the GitLab host."""
    _, host, path = parse_remote(remote_url)
    if not host or host != _host_of(gitlab_url):
        return None
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-len(".git")]
    return path or None


def sanitize_remote_url(remote_url):
    """Drop user:password@ from URL remotes so credentials are never printed."""
    if not remote_url:
        return remote_url
    return re.sub(r"^([A-Za-z][A-Za-z0-9+.\-]*://)[^/@]*@", r"\1", remote_url)


_AUTH_ERROR_MARKERS = (
    "authentication failed", "could not read username", "could not read password",
    "http basic: access denied", "terminal prompts disabled", "returned error: 401",
    "invalid username or password", "returned error: 403",
)


def is_git_auth_error(stderr):
    text = (stderr or "").lower()
    return any(marker in text for marker in _AUTH_ERROR_MARKERS)


def classify_git_network_error(stderr, operation):
    """Map git fetch/push stderr to (code, Vietnamese message)."""
    text = (stderr or "").lower()
    if "[rejected]" in text and ("non-fast-forward" in text or "fetch first" in text):
        return "push_rejected", ("GitLab từ chối vì trên nhánh này đã có thay đổi mới mà máy bạn chưa có. Cần kéo "
                                 "(pull) code mới về trước rồi đẩy lại. Tuyệt đối không dùng force push — nếu không "
                                 "chắc, hãy nhờ developer.")
    if "protected branch" in text or "not allowed to push" in text or "pre-receive hook declined" in text:
        return "push_denied", ("GitLab không cho đẩy lên nhánh này (nhánh được bảo vệ hoặc bạn thiếu quyền). "
                               "Hãy nhờ developer/maintainer kiểm tra quyền.")
    if "ssl certificate" in text or "certificate verify failed" in text or "unable to get local issuer" in text:
        return "ssl_error", ("Lỗi chứng chỉ bảo mật (SSL) khi kết nối GitLab. Nếu công ty dùng chứng chỉ nội bộ, "
                             "hãy điền đường dẫn file CA vào MPS_CA_BUNDLE trong .env.")
    if is_git_auth_error(text):
        return "auth_failed", ("GitLab không chấp nhận thông tin đăng nhập khi %s. Hãy kiểm tra MPS_GITLAB_PAT "
                               "trong .env (còn hạn, có scope write_repository)." % operation)
    if ("could not resolve host" in text or "failed to connect" in text or "timed out" in text
            or "connection refused" in text or "unable to access" in text):
        return "network_unreachable", ("Không kết nối được tới GitLab khi %s. Hãy kiểm tra đã bật VPN công ty và "
                                       "mạng đang hoạt động." % operation)
    return "git_%s_failed" % operation, "Lệnh git %s thất bại. Xem chi tiết lỗi bên dưới." % operation


def apply_budget(texts, cap):
    """Truncate a list of texts so their total length is <= cap. Returns [(text, truncated)]."""
    remaining = cap
    output = []
    for text in texts:
        if len(text) <= remaining:
            output.append((text, False))
            remaining -= len(text)
        else:
            output.append((text[:max(remaining, 0)], True))
            remaining = 0
    return output


# ---------------------------------------------------------------------------
# Pure helpers: scope review result
# ---------------------------------------------------------------------------

REVIEW_CATEGORIES = ("in_scope", "out_of_scope", "mixed", "concern")
COMMITTABLE_CATEGORIES = ("in_scope", "concern")
_REVIEW_FILES_HEADER_RE = re.compile(r"^\s*FILES:\s*$")
_REVIEW_FILE_LINE_RE = re.compile(r"^\s*[-*]?\s*(in_scope|out_of_scope|mixed|concern)\s*:\s*(.+?)\s*$")
_REVIEW_VERDICT_RE = re.compile(r"^\s*VERDICT:\s*(PASS|FAIL)\s*$", re.MULTILINE)
_REVIEW_BUNDLE_RE = re.compile(r"^\s*BUNDLE:\s*`?([0-9a-fA-F]+)`?\s*$", re.MULTILINE)
_TRAILING_NOTE_RE = re.compile(r"\s+\(.*\)$")


def parse_review_files(text):
    """Reviewer reply -> ([(category, raw_path)], verdict or None, bundle id or None).

    Reads the lines after the `FILES:` header; the `BUNDLE:` line ties the reply to the bundle that was reviewed.
    """
    entries = []
    in_block = False
    for line in (text or "").splitlines():
        if _REVIEW_FILES_HEADER_RE.match(line):
            in_block = True
            continue
        if not in_block:
            continue
        match = _REVIEW_FILE_LINE_RE.match(line)
        if match:
            entries.append((match.group(1), match.group(2).strip("`")))
    verdicts = _REVIEW_VERDICT_RE.findall(text or "")
    bundles = _REVIEW_BUNDLE_RE.findall(text or "")
    return entries, (verdicts[-1] if verdicts else None), (bundles[-1].lower() if bundles else None)


def stale_bundle_reason(bundle, reply_bundle_id, base, branch, head, current_blobs):
    """Why a review reply cannot be trusted for the current work tree (None = it can).

    The reply must name the bundle it reviewed, and nothing may have moved since that bundle was made: same base,
    branch and HEAD, the same set of changed files with the same content.
    """
    if bundle is None:
        return "no_bundle"
    if not reply_bundle_id:
        return "reply_without_bundle_id"
    if reply_bundle_id != bundle.get("bundle_id"):
        return "reply_for_other_bundle"
    if bundle.get("base") != base:
        return "base_changed"
    if bundle.get("branch") != branch or bundle.get("head") != head:
        return "branch_or_commit_changed"
    if (bundle.get("blobs") or {}) != current_blobs:
        return "files_changed"
    return None


def _match_candidate(raw, candidates):
    if raw in candidates:
        return raw
    stripped = _TRAILING_NOTE_RE.sub("", raw).strip("`")
    return stripped if stripped in candidates else None


def classify_review(entries, uncommitted, committed, verdict):
    """Turn the reviewer's per-file list into commit decisions. Unclassified files are NEVER committed by default.

    On a PASS verdict concern files are committed by default; otherwise only in_scope files are, and concern files
    need the user's decision (`needs_decision`). A missing verdict makes the classification incomplete.
    """
    candidates = list(uncommitted) + [p for p in committed if p not in uncommitted]
    by_path = {}
    unknown = []
    duplicates = []
    for category, raw in entries:
        path = _match_candidate(raw, candidates)
        if path is None:
            unknown.append(raw)
        elif path in by_path:
            duplicates.append(path)
        else:
            by_path[path] = category
    committable = COMMITTABLE_CATEGORIES if verdict == "PASS" else ("in_scope",)
    concern = [p for p in uncommitted if by_path.get(p) == "concern"]
    return {
        "verdict": verdict,
        "commit_files": [p for p in uncommitted if by_path.get(p) in committable],
        "concern_files": concern,
        "needs_decision": [] if verdict == "PASS" else concern,
        "excluded_files": [p for p in uncommitted if by_path.get(p) == "out_of_scope"],
        "mixed_files": [p for p in uncommitted if by_path.get(p) == "mixed"],
        "unclassified_files": [p for p in uncommitted if p not in by_path],
        "committed_out_of_scope": [p for p in committed if by_path.get(p) in ("out_of_scope", "mixed")],
        "unknown_paths": unknown,
        "duplicate_paths": duplicates,
        "complete": (verdict is not None and not unknown and not duplicates
                     and all(p in by_path for p in candidates)),
    }


# ---------------------------------------------------------------------------
# Pure helpers: code review rules, diff, findings
# ---------------------------------------------------------------------------
#
# Three rule layers: L1 `references/review/base.md` (team baseline), L2 `references/review/profiles/<name>.md`
# (per detected stack, anchored to the stack's root folder) and L3 `.mps/review.md` read from origin/<base>. Only
# L3 may declare `blocker`; shipped layers are lowered to `major`. Rule paths use their own glob dialect
# (`rule_glob_regex`): a slash-less glob such as `*.cs` matches the file name at any depth, unlike
# MPS_GENERATED_PATTERNS (`_glob_regex`), where a slash-less pattern only matches directly inside its roots.

SEVERITY_RANK = {"blocker": 0, "major": 1, "minor": 2}
_FM_FENCE_RE = re.compile(r"^---[ \t]*$")
_FM_PAIR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:[ \t]*(.*?)[ \t]*$")
_FM_COMMENT_RE = re.compile(r"^\s*#")
_MD_H2_RE = re.compile(r"^##(?!#)[ \t]+(.*?)[ \t]*$")
_RULE_HEADING_RE = re.compile(r"^(\S+)[ \t]+\[([^\]]*)\][ \t]+(\S.*?)$")
_PATHS_LINE_RE = re.compile(r"^paths[ \t]*:[ \t]*(.*?)[ \t]*$", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# Every '-' is followed by a letter, so no part of an id can look like a Jira key (ABC-12) in MR text.
_RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*$")
_PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_LIST_QUOTES = "'\"`"
_RULE_GLOB_CACHE = {}


def _rule_problem(parsed, line, message):
    parsed["problems"].append({"line": line, "message": message})


def _rule_list_items(value):
    """'[a, "b"]' or 'a, b' -> ['a', 'b']; quotes (' " `) around an item are dropped, empty items skipped."""
    text = value.strip()
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        text = text[1:-1]
    items = []
    for raw in text.split(","):
        item = raw.strip()
        if len(item) >= 2 and item[0] == item[-1] and item[0] in _LIST_QUOTES:
            item = item[1:-1].strip()
        if item:
            items.append(item)
    return items


def normalize_rule_glob(glob):
    """Rule glob -> normalized form ('\\' -> '/', no leading './' or '/', 'dir/' -> 'dir/**'). ValueError if invalid."""
    text = (glob or "").replace("\\", "/").strip().strip("`").strip()
    if text.startswith("./"):
        text = text[2:]
    text = text.lstrip("/")
    if text.endswith("/"):
        text += "**"
    if not text or "\0" in text or any(seg in ("", ".", "..") for seg in text.split("/")):
        raise ValueError("invalid rule glob: %r" % glob)
    return text


def _rule_segment_regex(segment):
    parts = []
    index = 0
    while index < len(segment):
        if segment.startswith("**", index):
            parts.append("[^/]*")
            index += 2
        elif segment[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif segment[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(segment[index]))
            index += 1
    return "".join(parts)


def rule_glob_regex(glob):
    """Compiled regex for a rule glob, matched against a path relative to the rule's root.

    A glob without '/' matches the file name at any depth ('*.cs' == '**/*.cs'). A '**' segment matches zero or
    more folders when it is not last, and one or more path segments when it is last ('Assets/**' matches
    everything under Assets/, not a file named Assets). Case-sensitive, like git paths.
    """
    normalized = normalize_rule_glob(glob)
    cached = _RULE_GLOB_CACHE.get(normalized)
    if cached is None:
        segments = normalized.split("/")
        if len(segments) == 1:
            segments = ["**"] + segments
        parts = []
        for index, segment in enumerate(segments):
            last = index == len(segments) - 1
            if segment == "**":
                parts.append(".+" if last else "(?:[^/]+/)*")
            else:
                parts.append(_rule_segment_regex(segment) + ("" if last else "/"))
        cached = re.compile("^" + "".join(parts) + "$")
        _RULE_GLOB_CACHE[normalized] = cached
    return cached


def path_matches(path, globs, roots):
    """True if `path`, taken relative to one of `roots` ("" = repo root), matches one of `globs`."""
    normalized = (path or "").replace("\\", "/").strip("/")
    for root in roots:
        relative = _relative_to(normalized, (root or "").replace("\\", "/").strip("/"))
        if relative is None:
            continue
        for glob in globs:
            if rule_glob_regex(glob).match(relative):
                return True
    return False


def rule_applies(rule, path):
    return path_matches(path, rule["paths"], rule["roots"])


def parse_rule_file(text, layer):
    """Parse a rule file. layer: "base" | "profile:<name>" | "project". Returns
    {version, extends, ignore, unknown_keys, rules, problems: [{line, message}], downgraded}.

    In shipped layers a `blocker` rule is stored as `major` (and listed in `downgraded`). Problems never raise here:
    the caller decides (a shipped file with problems is a plugin bug; a project file with problems is skipped).
    """
    parsed = {"version": 1, "extends": [], "ignore": [], "unknown_keys": [], "rules": [], "problems": [],
              "downgraded": []}
    text = text or ""
    if text.startswith(_BOM):
        text = text[len(_BOM):]
    if layer == "project" and len(text) > PROJECT_RULES_MAX_CHARS:
        _rule_problem(parsed, 1, "File dài quá %d ký tự nên không được đọc. Hãy rút gọn file."
                      % PROJECT_RULES_MAX_CHARS)
        return parsed
    # Split on "\n" only: str.splitlines() also splits on other characters and would shift line numbers.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = 0
    if _FM_FENCE_RE.match(lines[0]):
        close = None
        for index in range(1, len(lines)):
            if _FM_FENCE_RE.match(lines[index]):
                close = index
                break
        if close is None:
            _rule_problem(parsed, 1, "Thiếu dòng --- đóng phần đầu file (mở ở dòng 1).")
            return parsed
        _parse_rule_frontmatter(lines, close, parsed, layer)
        start = close + 1
    _parse_rule_body(lines, start, parsed, layer)
    return parsed


def _parse_rule_frontmatter(lines, close, parsed, layer):
    seen = set()
    for index in range(1, close):
        line = lines[index]
        number = index + 1
        if not line.strip() or _FM_COMMENT_RE.match(line):
            continue
        match = _FM_PAIR_RE.match(line.strip())
        if not match:
            _rule_problem(parsed, number, "Dòng này trong phần đầu file không đúng dạng 'khoá: giá trị'.")
            continue
        key = match.group(1).lower()
        value = _INLINE_COMMENT_RE.split(match.group(2), 1)[0].strip()
        if key in seen:
            _rule_problem(parsed, number, "Khoá '%s' bị lặp trong phần đầu file." % key)
            continue
        seen.add(key)
        if key == "version":
            items = _rule_list_items(value)
            if items != ["1"]:
                _rule_problem(parsed, number, "Phiên bản '%s' không được hỗ trợ (chỉ có version: 1)." % value)
        elif key == "extends":
            if layer != "project":
                _rule_problem(parsed, number, "Khoá extends chỉ dùng được trong .mps/review.md.")
            for item in _rule_list_items(value):
                if not _PROFILE_NAME_RE.match(item):
                    _rule_problem(parsed, number, "Tên bộ quy tắc '%s' trong extends không hợp lệ (chỉ chữ thường, "
                                                  "số và dấu '-', ví dụ unity-csharp)." % item)
                elif item not in parsed["extends"]:
                    parsed["extends"].append(item)
        elif key == "ignore":
            for item in _rule_list_items(value):
                try:
                    parsed["ignore"].append(normalize_rule_glob(item))
                except ValueError:
                    _rule_problem(parsed, number, "Mẫu đường dẫn '%s' không hợp lệ." % item)
        elif key not in parsed["unknown_keys"]:
            parsed["unknown_keys"].append(key)


def _parse_rule_body(lines, start, parsed, layer):
    fence = None  # (character, length, line number) of the open code fence
    current = None
    seen = {}
    for index in range(start, len(lines)):
        line = lines[index]
        number = index + 1
        if fence is not None:
            closing = _CODE_FENCE_RE.match(line)
            if (closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= fence[1]
                    and not line[closing.end():].strip()):
                fence = None
            _rule_body_line(current, line, number, False, parsed)
            continue
        opening = _CODE_FENCE_RE.match(line)
        if opening:
            fence = (opening.group(1)[0], len(opening.group(1)), number)
            _rule_body_line(current, line, number, False, parsed)
            continue
        heading = _MD_H2_RE.match(line)
        if heading:
            _finish_rule(current, parsed, layer)
            current = _start_rule(heading.group(1), number, parsed, seen)
            continue
        _rule_body_line(current, line, number, True, parsed)
    _finish_rule(current, parsed, layer)
    if fence is not None:
        _rule_problem(parsed, fence[2], "Khối code (```) mở ở đây nhưng chưa được đóng.")


def _start_rule(text, number, parsed, seen):
    """A level-2 heading always starts a new section (so its body is never glued to the previous rule); a heading
    with problems produces no rule."""
    section = {"valid": False, "line": number, "paths": None, "body": [], "started": False}
    match = _RULE_HEADING_RE.match(text)
    if not match:
        _rule_problem(parsed, number, "Tiêu đề quy tắc sai dạng. Đúng: `## MÃ-QUY-TẮC [blocker|major|minor] Tiêu đề`.")
        return section
    rule_id, severity, title = match.group(1), match.group(2).strip(), match.group(3).strip()
    valid = True
    if not _RULE_ID_RE.match(rule_id) or len(rule_id) > RULE_ID_MAX_LEN:
        _rule_problem(parsed, number, "Mã quy tắc '%s' không hợp lệ: chỉ dùng chữ IN HOA, số và dấu '-', mỗi phần sau "
                                      "dấu '-' phải bắt đầu bằng chữ cái (để không giống mã ticket Jira như ABC-12)."
                      % rule_id)
        valid = False
    elif rule_id in seen:
        _rule_problem(parsed, number, "Mã quy tắc '%s' bị trùng (đã có ở dòng %d)." % (rule_id, seen[rule_id]))
        valid = False
    else:
        seen[rule_id] = number
    if severity.lower() not in SEVERITIES:
        _rule_problem(parsed, number, "Mức độ '%s' không hợp lệ (chỉ blocker, major, minor)." % severity)
        valid = False
    section.update({"valid": valid, "id": rule_id, "severity": severity.lower(), "title": title})
    return section


def _rule_body_line(current, line, number, plain, parsed):
    if current is None:
        return  # preamble before the first rule heading
    if plain and not current["started"] and line.strip():
        current["started"] = True
        match = _PATHS_LINE_RE.match(line.strip())
        if match:
            current["paths"] = []
            items = _rule_list_items(match.group(1))
            if not items:
                _rule_problem(parsed, number, "Dòng paths: chưa có mẫu đường dẫn nào.")
            for item in items:
                try:
                    current["paths"].append(normalize_rule_glob(item))
                except ValueError:
                    _rule_problem(parsed, number, "Mẫu đường dẫn '%s' không hợp lệ." % item)
            return
    if line.strip():
        current["started"] = True
    current["body"].append(line)


def _finish_rule(current, parsed, layer):
    if current is None or not current["valid"]:
        return
    body = list(current["body"])
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    severity = current["severity"]
    downgraded = layer != "project" and severity == "blocker"
    if downgraded:
        severity = "major"
        parsed["downgraded"].append(current["id"])
    parsed["rules"].append({"id": current["id"], "severity": severity, "title": current["title"],
                            "paths": current["paths"] or ["**"], "explicit_paths": current["paths"] is not None,
                            "roots": [""], "layer": layer, "body": "\n".join(body), "line": current["line"],
                            "downgraded": downgraded})


def _raise_shipped_problems(file_name, parsed):
    if parsed["problems"]:
        problem = parsed["problems"][0]
        raise MpsError("internal_error", "File quy tắc đi kèm plugin bị lỗi (%s, dòng %s): %s. Hãy báo người bảo trì "
                                         "plugin." % (file_name, problem["line"], problem["message"]),
                       file=file_name, problems=parsed["problems"])


def build_effective_rules(base_text, profile_texts, project_text, detected_profiles):
    """Merge L1 + L2 + L3. profile_texts: {name: text} of every shipped profile; project_text: None = no file;
    detected_profiles: {name: [roots]}. Returns {rules, ignore, profiles, project_rules, unknown_profiles,
    downgraded}; project_rules.status is absent | applied | invalid.

    An L3 rule with the id of an earlier rule replaces it in place. An invalid L3 file is skipped entirely: no
    rules, no extends, no ignore. Rules are ordered by severity, then merge order.
    """
    base = parse_rule_file(base_text, "base")
    _raise_shipped_problems("base.md", base)
    project = None
    status = "absent"
    if project_text is not None:
        project = parse_rule_file(project_text, "project")
        status = "invalid" if project["problems"] else "applied"
    applied = status == "applied"
    extends = project["extends"] if applied else []
    unknown_profiles = [name for name in extends if name not in profile_texts]
    detected = dict((name, roots) for name, roots in (detected_profiles or {}).items() if name in profile_texts)
    merged = []
    positions = {}

    def add(rule):
        if rule["id"] in positions:
            merged[positions[rule["id"]]] = rule
        else:
            positions[rule["id"]] = len(merged)
            merged.append(rule)

    for rule in base["rules"]:
        add(dict(rule, roots=[""]))
    downgraded = list(base["downgraded"])
    ignore = []
    profiles = []
    for name in sorted(set(detected) | set(n for n in extends if n in profile_texts)):
        in_detected, in_extends = name in detected, name in extends
        source = "both" if in_detected and in_extends else ("detected" if in_detected else "extends")
        roots = sorted(set(detected.get(name) or []) | (set([""]) if in_extends else set()))
        profiles.append({"name": name, "roots": roots, "source": source})
        parsed = parse_rule_file(profile_texts[name], "profile:" + name)
        _raise_shipped_problems("profiles/%s.md" % name, parsed)
        downgraded.extend(parsed["downgraded"])
        for rule in parsed["rules"]:
            add(dict(rule, roots=list(roots)))
        ignore.extend({"glob": glob, "roots": list(roots), "source": "profile:" + name} for glob in parsed["ignore"])
    if applied:
        for rule in project["rules"]:
            add(dict(rule, roots=[""]))
        ignore.extend({"glob": glob, "roots": [""], "source": "project"} for glob in project["ignore"])
    ordered = [rule for _, rule in sorted(enumerate(merged), key=lambda p: (SEVERITY_RANK[p[1]["severity"]], p[0]))]
    return {"rules": ordered, "ignore": ignore, "profiles": profiles,
            "project_rules": {"status": status, "problems": project["problems"] if project else [],
                              "unknown_keys": project["unknown_keys"] if applied else []},
            "unknown_profiles": unknown_profiles, "downgraded": downgraded}


def split_ignored(paths, ignore_entries, rules=()):
    """(reviewed, ignored), order preserved. ignore_entries: [{glob, roots, source}].

    The project's own `ignore` (source "project") always wins. A shipped profile's `ignore` (e.g. Unity's
    **/*.prefab) does not apply to a path that a project rule (layer "project" in `rules`) names in an explicit
    `paths:` line: the tech lead asked for that file to be checked. A rule without `paths:` (default `**`) does not
    count, or every serialized Unity asset would flood the bundle.
    """
    project_rules = [rule for rule in rules if rule.get("layer") == "project" and rule.get("explicit_paths")]
    reviewed = []
    ignored = []
    for path in paths:
        matching = [entry for entry in ignore_entries if path_matches(path, [entry["glob"]], entry["roots"])]
        if any(entry.get("source") == "project" for entry in matching):
            ignored.append(path)
        elif matching and not any(rule_applies(rule, path) for rule in project_rules):
            ignored.append(path)
        else:
            reviewed.append(path)
    return reviewed, ignored


def project_rules_matching_nothing(rules, paths, ignore_entries=()):
    """Project (L3) rules whose paths match none of `paths` (the files of a branch, plus the changed ones): such a
    rule can never apply, usually because its paths do not start at the repo root ('Assets/...' for a Unity project
    in 'Client/Game'). A file the project's own `ignore` hides is never reviewed, so it does not count as a match."""
    project_ignore = [entry for entry in ignore_entries if entry.get("source") == "project"]
    remaining = [rule for rule in rules if rule.get("layer") == "project"]
    for path in paths:
        if not remaining:
            break
        if any(path_matches(path, [entry["glob"]], entry["roots"]) for entry in project_ignore):
            continue
        remaining = [rule for rule in remaining if not rule_applies(rule, path)]
    return remaining


def rule_matches_nothing_warning(rule, where):
    """Warning project_rule_matches_nothing; `where` names the files that were searched (Vietnamese)."""
    return {"code": "project_rule_matches_nothing", "rule": rule["id"], "paths": rule["paths"],
            "message": "Quy tắc %s trong %s không khớp file nào %s (paths: %s), nên sẽ không bao giờ được áp dụng. "
                       "Đường dẫn tính từ gốc repo, ví dụ **/Assets/Scripts/**/*.cs; tech lead cần kiểm tra lại "
                       "dòng paths:." % (rule["id"], PROJECT_RULES_PATH, where, ", ".join(rule["paths"]))}


def _render_rule_block(rule):
    roots = [r for r in rule["roots"] if r]
    where = ""
    if roots and len(roots) == len(rule["roots"]):
        where = " (relative to %s)" % ", ".join("`%s`" % r for r in roots)
    lines = ["### %s [%s] %s" % (rule["id"], rule["severity"], rule["title"]),
             "Applies to: %s%s. Source: %s." % (", ".join("`%s`" % g for g in rule["paths"]), where, rule["layer"])]
    if rule.get("body"):
        lines.extend(["", rule["body"]])
    return "\n".join(lines) + "\n"


def render_rules_section(rules):
    """Section A of the code bundle: one block per rule (also the unit used to size rules for RULES_CAP_CHARS)."""
    return "\n".join(_render_rule_block(rule) for rule in rules) if rules else "(none)\n"


def filter_rules(rules, paths, cap):
    """Rules that apply to at least one of `paths`, within `cap` characters. Returns (kept, dropped_ids).

    Blocker rules are always kept. Once a major/minor rule does not fit, it and every later non-blocker rule are
    dropped (rules are ordered by severity, so minor rules go first).
    """
    kept = []
    dropped = []
    used = 0
    overflow = False
    for rule in rules:
        if not any(rule_applies(rule, path) for path in paths):
            continue
        size = len(_render_rule_block(rule)) + 1
        if rule["severity"] == "blocker":
            kept.append(rule)
            used += size
        elif not overflow and used + size <= cap:
            kept.append(rule)
            used += size
        else:
            overflow = True
            dropped.append(rule["id"])
    return kept, dropped


# -- net diff: merge-base -> working tree, rendered with new-file line numbers ---------------------------------

_GIT_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _unquote_git_path(raw):
    """C-quoted git path ('"a/\\303\\251.cs"') -> text ('a/é.cs'); an unquoted path is returned unchanged."""
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return raw
    body = raw[1:-1]
    out = bytearray()
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            following = body[index + 1]
            octal = body[index + 1:index + 4]
            if len(octal) == 3 and all(c in "01234567" for c in octal):
                out.append(int(octal, 8) & 0xFF)
                index += 4
                continue
            if following in _GIT_C_ESCAPES:
                out.append(_GIT_C_ESCAPES[following])
                index += 2
                continue
        out.extend(char.encode("utf-8"))
        index += 1
    return out.decode("utf-8", "replace")


def _git_quoted_token(text):
    """('"..."' token at the start of `text`, rest) for a C-quoted token, else (None, text)."""
    if not text.startswith('"'):
        return None, text
    index = 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == '"':
            return text[:index + 1], text[index + 1:]
        index += 1
    return None, text


def _diff_git_line_path(line):
    """New path from 'diff --git a/X b/X' (only used when no rename / +++ header names it)."""
    rest = line[len("diff --git "):]
    first, after = _git_quoted_token(rest)
    if first is not None:
        second = after.strip()
        path = _unquote_git_path(second) if second.startswith('"') else second
        return path[2:] if path.startswith("b/") else path
    half = (len(rest) - 5) // 2
    if rest[:2] == "a/" and rest[2 + half:5 + half] == " b/" and rest[2:2 + half] == rest[5 + half:]:
        return rest[2:2 + half]
    marker = rest.rfind(" b/")
    return rest[marker + 3:] if marker >= 0 else rest


def _diff_side_path(raw, prefix):
    """Path from a '--- a/..' / '+++ b/..' header (git appends a TAB when the path has a space); None for /dev/null."""
    path = _unquote_git_path(raw.rstrip("\t"))
    if path == "/dev/null":
        return None
    return path[len(prefix):] if path.startswith(prefix) else path


def _new_file_diff(path, status):
    return {"path": path, "old_path": None, "status": status, "binary": False, "too_large": False,
            "mode_only": False, "source_cut": False, "lines": []}


def _finish_file_diff(entry):
    meta = entry.pop("_meta")
    path = meta.get("rename_to") or meta.get("plus") or (meta.get("minus") if meta.get("plus_null") else None)
    entry["path"] = path or meta["git_line_path"]
    if meta.get("rename_from") and meta.get("rename_to"):
        entry["status"] = "renamed"
        entry["old_path"] = meta["rename_from"]
    # A modified file without hunks only changed its mode (a pure rename or an empty new file keeps its status).
    if not any(item[0] == "@" for item in entry["lines"]) and not entry["binary"] and entry["status"] == "modified":
        entry["mode_only"] = True


def parse_diff_files(diff_text):
    """Parse `git diff` output into [FileDiff]: {path, old_path, status (added|modified|deleted|renamed), binary,
    too_large, mode_only, source_cut, lines: [[marker, new_line_number_or_None, content]]}.

    Hunk bodies are consumed by their line counts (as in scan_secrets), so content lines such as '--- x' are never
    taken for headers. Markers: '@' hunk header (content = the whole line), '+', '-', ' ', '\\'.
    """
    files = []
    current = None
    old_left = new_left = new_no = 0
    lines = (diff_text or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        if current is not None and (old_left > 0 or new_left > 0):
            if line.startswith("+"):
                current["lines"].append(["+", new_no, line[1:]])
                new_no += 1
                new_left -= 1
            elif line.startswith("-"):
                current["lines"].append(["-", None, line[1:]])
                old_left -= 1
            elif line.startswith("\\"):
                current["lines"].append(["\\", None, line])
            else:
                current["lines"].append([" ", new_no, line[1:]])
                new_no += 1
                new_left -= 1
                old_left -= 1
            continue
        if line.startswith("diff --git "):
            if current is not None:
                _finish_file_diff(current)
            current = _new_file_diff(None, "modified")
            current["_meta"] = {"git_line_path": _diff_git_line_path(line)}
            files.append(current)
            continue
        if current is None:
            continue
        meta = current["_meta"]
        if line.startswith("\\"):
            current["lines"].append(["\\", None, line])  # '\ No newline' right after a hunk's last counted line
            continue
        match = _HUNK_RE.match(line)
        if match:
            old_left = int(match.group(1)) if match.group(1) is not None else 1
            new_no = int(match.group(2))
            new_left = int(match.group(3)) if match.group(3) is not None else 1
            current["lines"].append(["@", None, line])
            continue
        if line.startswith("new file mode "):
            current["status"] = "added"
        elif line.startswith("deleted file mode "):
            current["status"] = "deleted"
        elif line.startswith("rename from "):
            meta["rename_from"] = _unquote_git_path(line[len("rename from "):])
        elif line.startswith("rename to "):
            meta["rename_to"] = _unquote_git_path(line[len("rename to "):])
        elif line.startswith("--- "):
            meta["minus"] = _diff_side_path(line[4:], "a/")
        elif line.startswith("+++ "):
            plus = _diff_side_path(line[4:], "b/")
            meta["plus"] = plus
            meta["plus_null"] = plus is None
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            current["binary"] = True
    if current is not None:
        _finish_file_diff(current)
    return files


def untracked_file_diff(path, text, kind, cut):
    """FileDiff for an untracked file: every line added (numbers 1..n). kind: text | binary | too_large."""
    entry = _new_file_diff(path, "untracked")
    entry["binary"] = kind == "binary"
    entry["too_large"] = kind == "too_large"
    entry["source_cut"] = bool(cut)
    if kind == "text":
        body = (text or "").split("\n")
        if body and body[-1] == "":
            body.pop()
        entry["lines"] = [["+", index + 1, content] for index, content in enumerate(body)]
    return entry


def _file_kind(entry):
    if entry["status"] == "deleted":
        return "deleted"
    if entry["too_large"]:
        return "too_large"
    if entry["binary"]:
        return "binary"
    return "text"


_KIND_TAGS = {"deleted": "deleted - only file-level findings, use line -",
              "binary": "binary - only file-level findings, use line -",
              "too_large": "too large - only file-level findings, use line -"}


def _file_tag(entry, kind):
    if kind in _KIND_TAGS:
        return _KIND_TAGS[kind]
    if entry["status"] == "renamed":
        return "renamed from %s" % entry["old_path"]
    if entry["status"] == "untracked":
        return "untracked (new file)"
    if entry["mode_only"]:
        return "mode change only"
    return entry["status"]


def _numbered_line(marker, number, content, line_cap):
    if marker == "@":
        return content
    if marker == "\\":
        return "%6s %s" % ("", content)
    if content.endswith("\r"):
        content = content[:-1]
    if len(content) > line_cap:
        content = content[:line_cap] + " [... dòng bị cắt bớt ...]"
    return "%6s %s %s" % ("" if number is None else number, marker, content)


def _merge_ranges(numbers):
    ranges = []
    for number in sorted(set(numbers)):
        if ranges and number == ranges[-1][1] + 1:
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
    return ranges


def render_numbered_diff(files, cap, line_cap=DIFF_LINE_CAP_CHARS):
    """Section C of the code bundle, cut at line boundaries so that `cap` characters are never exceeded (None =
    unlimited). The ranges come from the same pass, so they describe exactly what the reviewer saw.

    Returns {text, ranges: {path: [[start, end]]} (text files), file_kinds: {path: text|binary|deleted|too_large|
    not_shown}, truncated_paths, shown_last_line: {path: n}}.
    """
    out = []
    state = {"used": 0, "stop": False}
    ranges = {}
    kinds = {}
    truncated = []
    last_line = {}

    def fits(text):
        return cap is None or state["used"] + len(text) + 1 <= cap

    def emit(text):
        out.append(text)
        state["used"] += len(text) + 1

    for entry in files:
        path = entry["path"]
        header = "### %s  [%s]" % (path, _file_tag(entry, _file_kind(entry)))
        if state["stop"] or not fits(header):
            state["stop"] = True
            kinds[path] = "not_shown"
            truncated.append(path)
            continue
        kind = _file_kind(entry)
        kinds[path] = kind
        header_index = len(out)
        emit(header)
        if kind != "text":
            continue
        numbers = []
        hunk = {"start": None, "numbered": False, "removed": False}

        def close_hunk():
            if hunk["start"] is not None and not hunk["numbered"] and hunk["removed"]:
                numbers.append(max(hunk["start"], 1))  # deletion-only hunk (file emptied): cite line 1

        cut = False
        for marker, number, content in entry["lines"]:
            rendered = _numbered_line(marker, number, content, line_cap)
            if not fits(rendered):
                state["stop"] = True
                cut = True
                break
            emit(rendered)
            if marker == "@":
                close_hunk()
                match = _HUNK_RE.match(content)
                hunk.update({"start": int(match.group(2)) if match else None, "numbered": False, "removed": False})
            elif marker == "-":
                hunk["removed"] = True
            elif number is not None:
                hunk["numbered"] = True
                numbers.append(number)
        close_hunk()
        ranges[path] = _merge_ranges(numbers)
        if numbers:
            last_line[path] = max(numbers)
        if cut or entry["source_cut"]:
            truncated.append(path)
            shown = last_line.get(path)
            out[header_index] += (" - TRUNCATED: shown up to line %d" % shown) if shown else " - TRUNCATED: no lines shown"
    return {"text": "\n".join(out) + ("\n" if out else ""), "ranges": ranges, "file_kinds": kinds,
            "truncated_paths": truncated, "shown_last_line": last_line}


def parse_changed_ranges(diff_text):
    """{path: [[start, end]]} on the new side of a unified diff, context lines included."""
    return render_numbered_diff(parse_diff_files(diff_text), None)["ranges"]


# -- findings: the code reviewer's FINDINGS: block -------------------------------------------------------------

_EN_DASH = chr(0x2013)
_FINDINGS_HEADER_RE = re.compile(r"^\s*(?:[-*]\s+)?FINDINGS:[ \t]*(?:`?((?i:none))`?)?[ \t]*$")
_FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")
# A list marker before a finding: "- ", "* ", "1. " or "1) ".
_BULLET_RE = re.compile(r"^\s*(?:[-*]\s+|[0-9]+[.)]\s*)?")
# Markdown emphasis / code marks a reviewer may put around the rule id (`ID`, **ID**, _ID_).
_RULE_ID_MARKS = "`*_ \t"
_LINE_SPEC_RE = re.compile(r"^([1-9][0-9]*)(?:[ \t]*[-" + _EN_DASH + r"][ \t]*([1-9][0-9]*))?$")


def _bad_finding(raw, error):
    return {"ok": False, "raw": raw, "error": error}


def _parse_finding_line(raw):
    """`<RULE-ID> | <severity> | <path>:<line|N-M|-> | <problem> | <suggestion>` -> entry ({"ok": False} if bad)."""
    text = raw.strip()
    parts = _BULLET_RE.sub("", raw, count=1).split("|", 4)
    if len(parts) < 5:
        return _bad_finding(text, "needs 5 fields separated by |")
    rule, severity, location, problem, suggestion = [part.strip() for part in parts]
    rule = rule.strip(_RULE_ID_MARKS)
    severity = severity.strip("`").strip().lower()
    location = location.strip("`").strip()
    if not rule:
        return _bad_finding(text, "empty rule id")
    if severity not in SEVERITIES:
        return _bad_finding(text, "unknown severity")
    if ":" not in location:
        return _bad_finding(text, "location needs path:line")
    path, spec = location.rsplit(":", 1)
    path = path.strip().strip("`").replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    spec = spec.strip()
    if spec == "-":
        start = end = None
        line = "-"
    else:
        match = _LINE_SPEC_RE.match(spec)
        if not match:
            return _bad_finding(text, "bad line number")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if end < start:
            return _bad_finding(text, "line range ends before it starts")
        line = str(start) if end == start else "%d-%d" % (start, end)
    if not path or not problem or not suggestion:
        return _bad_finding(text, "empty path, problem or suggestion")
    return {"ok": True, "raw": text, "rule": rule, "severity": severity, "path": path, "line": line,
            "line_start": start, "line_end": end, "problem": problem, "suggestion": suggestion}


_AMBIGUOUS_FINDINGS = "more than one FINDINGS block, or a FINDINGS block without BUNDLE before the next one"
_TEXT_AFTER_BLOCK = "text between the end of the FINDINGS block and BUNDLE"


def _findings_blocks(lines):
    """Every block: a `FINDINGS:` header, then its body up to its own `BUNDLE:` line (complete) or, without one, up
    to the next header or the end of the text."""
    headers = [index for index, line in enumerate(lines) if _FINDINGS_HEADER_RE.match(line)]
    blocks = []
    for number, header in enumerate(headers):
        stop = headers[number + 1] if number + 1 < len(headers) else len(lines)
        end = None
        for index in range(header + 1, stop):
            if _REVIEW_BUNDLE_RE.match(lines[index]):
                end = index
                break
        blocks.append({"header": lines[header].strip(),
                       "is_none": bool(_FINDINGS_HEADER_RE.match(lines[header]).group(1)),
                       "body": lines[header + 1:stop if end is None else end],
                       "bundle_id": _REVIEW_BUNDLE_RE.match(lines[end]).group(1).lower() if end is not None else None})
    return blocks


def _parse_findings_body(block):
    """Finding entries of one block. Its lines may sit inside one code block that opens right after the header;
    otherwise a code fence ends them. Anything after that end (before BUNDLE) is a bad line, never ignored."""
    entries = []
    state = "start"  # start -> open (plain lines) | fenced -> ended
    for line in block["body"]:
        if not line.strip():
            continue
        fence = _FENCE_LINE_RE.match(line)
        if state == "ended":
            if not fence:
                entries.append(_bad_finding(line.strip(), _TEXT_AFTER_BLOCK))
        elif fence:
            state = "fenced" if state == "start" else "ended"
        else:
            state = "fenced" if state == "fenced" else "open"
            entries.append(_bad_finding(line.strip(), "text after FINDINGS: none") if block["is_none"]
                           else _parse_finding_line(line))
    if not block["is_none"] and not entries:
        entries.append(_bad_finding(block["header"], "FINDINGS: without findings (write FINDINGS: none)"))
    return entries


def parse_findings(text):
    """Reviewer reply -> (entries or None, bundle id or None). None = no `FINDINGS:` block at all.

    Fails closed: the reply must hold exactly one block (`FINDINGS:` ... `BUNDLE:`); identical repeats are
    tolerated. Several different blocks, or two headers without a BUNDLE line between them, give one bad line, so
    the review is incomplete and the reviewer must answer again. Blocks are never told apart by their bundle id: a
    quoted block with a mistyped id could hold the real blocker. `FINDINGS: none` followed by any line, and a plain
    `FINDINGS:` without finding lines, are bad lines too.
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    blocks = _findings_blocks(lines)
    if not blocks:
        return None, None
    last_bundle = None
    for block in blocks:
        last_bundle = block["bundle_id"] or last_bundle
    signatures = set((block["is_none"], tuple(line.strip() for line in block["body"] if line.strip()),
                      block["bundle_id"]) for block in blocks)
    if len(signatures) > 1 or any(b["bundle_id"] is None for b in blocks[:-1]):
        return [_bad_finding(blocks[-1]["header"], _AMBIGUOUS_FINDINGS)], last_bundle
    return _parse_findings_body(blocks[-1]), blocks[-1]["bundle_id"]


def _location_ok(entry, kind, path_ranges):
    if kind in ("binary", "deleted", "too_large"):
        return entry["line_start"] is None
    if kind != "text" or entry["line_start"] is None:
        return False
    return any(entry["line_start"] <= end and entry["line_end"] >= start for start, end in path_ranges)


def verify_findings(entries, code_review, candidates):
    """Check each finding against what the code reviewer was really shown (rules, files, numbered lines).

    Returns {complete, findings, blockers, rule_warnings, blockers_in_candidates, blocked_paths, dropped_findings,
    dropped_count, duplicate_count}. Severity always comes from the rule. The review is incomplete when a line is
    malformed, or a finding that cites a blocker rule or that the reviewer marked `blocker` could not be matched:
    blockers never fail silently.
    """
    rules = dict((rule["id"], rule) for rule in code_review.get("rules") or [])
    reviewed = set(code_review.get("reviewed_paths") or [])
    ignored = set(code_review.get("ignored_paths") or [])
    kinds = code_review.get("file_kinds") or {}
    ranges = code_review.get("ranges") or {}
    findings = []
    dropped = []
    seen = set()
    for entry in entries:
        rule = rules.get(entry.get("rule")) if entry["ok"] else None
        if not entry["ok"]:
            reason = "bad_format"
        elif rule is None:
            reason = "unknown_rule"
        elif entry["path"] in ignored:
            reason = "path_ignored"
        elif entry["path"] not in reviewed:
            reason = "path_not_reviewed"
        elif not rule_applies(rule, entry["path"]):
            reason = "rule_not_applicable"
        elif not _location_ok(entry, kinds.get(entry["path"]), ranges.get(entry["path"]) or []):
            reason = "line_outside_changes"
        elif (rule["id"], entry["path"], entry["line_start"], entry["line_end"]) in seen:
            reason = "duplicate"
        else:
            reason = None
        if reason:
            # A blocker never fails silently: neither a blocker rule nor a finding the reviewer called a blocker
            # (e.g. a mistyped rule id) may be dropped without the reviewer fixing its reply.
            dropped.append({"raw": entry["raw"], "reason": reason, "rule": entry.get("rule"),
                            "blocker_rule": bool(rule and rule["severity"] == "blocker"),
                            "blocker_claimed": entry.get("severity") == "blocker"})
            continue
        seen.add((rule["id"], entry["path"], entry["line_start"], entry["line_end"]))
        findings.append({"rule": rule["id"], "severity": rule["severity"], "title": rule["title"],
                         "layer": rule["layer"], "path": entry["path"], "line": entry["line"],
                         "line_start": entry["line_start"], "line_end": entry["line_end"],
                         "problem": entry["problem"], "suggestion": entry["suggestion"],
                         "severity_corrected": entry["severity"] != rule["severity"]})
    blockers = [f for f in findings if f["severity"] == "blocker"]
    in_candidates = [f for f in blockers if f["path"] in candidates]
    duplicates = len([d for d in dropped if d["reason"] == "duplicate"])
    complete = not any(d["reason"] == "bad_format"
                       or ((d["blocker_rule"] or d["blocker_claimed"]) and d["reason"] != "duplicate")
                       for d in dropped)
    return {"complete": complete, "findings": findings, "blockers": blockers,
            "rule_warnings": ([f for f in findings if f["severity"] == "major"]
                              + [f for f in findings if f["severity"] == "minor"]),
            "blockers_in_candidates": in_candidates,
            "blocked_paths": sorted(set(f["path"] for f in in_candidates)),
            "dropped_findings": dropped, "dropped_count": len(dropped) - duplicates, "duplicate_count": duplicates}


def blockers_for_commit(review, committing_paths):
    """Blockers whose file is being committed now or was already committed on the branch (A3)."""
    paths = set(committing_paths) | set(review.get("already_committed") or [])
    return [f for f in review.get("blockers") or [] if f["path"] in paths]


def code_review_warning_items(review):
    """Accepted major / minor findings on committed files, majors first (what the MR report lists)."""
    committed = set(review.get("committed_paths") or [])
    findings = [f for f in review.get("findings") or [] if f["path"] in committed]
    return [f for f in findings if f["severity"] == "major"] + [f for f in findings if f["severity"] == "minor"]


# -- merge request report ----------------------------------------------------------------------------------------

# GitLab cross-links or notifies on Jira keys (also "UTF-8"), and on references built with @ # ! ~ $ (users,
# issues, MRs - also "group/proj#12" or "proj!12" -, labels, snippets) unless they sit inside a code span.
_MD_JIRA_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]*-[0-9]+)(?![A-Za-z0-9_])")
_MD_REFERENCE_CHARS = "@#!~$"


def _md_inline_token(token):
    if any(char in token for char in _MD_REFERENCE_CHARS):
        return "`%s`" % token  # the whole token, so a project prefix such as group/proj#12 stays inside
    return _MD_JIRA_KEY_RE.sub(lambda m: "`%s`" % m.group(1), token.replace("|", "\\|"))


def _md_inline(text):
    """One-line markdown-safe text: whitespace collapsed, '`' -> "'" (so a code span can never be broken), '|'
    escaped, and every token that GitLab could turn into a reference or mention put in a code span."""
    return " ".join(_md_inline_token(token) for token in (text or "").replace("`", "'").split())


def _md_code(text):
    return "`%s`" % " ".join((text or "").split()).replace("`", "'")


def _short_list(items, limit, rendered=None):
    shown = [rendered(i) if rendered else i for i in items[:limit]]
    text = ", ".join(shown)
    if len(items) > limit:
        text += " và %d mục khác" % (len(items) - limit)
    return text


def render_mr_review_section(review):
    """Markdown report of a committed code review for the merge request (Vietnamese). Free text goes through
    _md_inline and paths / rule ids are code spans, so nothing in it links a Jira ticket or pings a user."""
    project_rules = review.get("project_rules") or {}
    status = project_rules.get("status")
    base = review.get("base") or ""
    parts = ["### Kết quả review code tự động", ""]
    if status == "invalid":
        problems = project_rules.get("problems") or []
        parts.append("> **Quy tắc riêng của dự án KHÔNG được áp dụng:** file `%s` trên nhánh %s bị lỗi định dạng, nên "
                     "lần review này chỉ dùng quy tắc chung của team và quy tắc theo công nghệ. Developer cần sửa "
                     "file này." % (PROJECT_RULES_PATH, _md_code(base)))
        for problem in problems[:MR_PROBLEMS_SHOWN]:
            parts.append("> - dòng %s: %s" % (problem.get("line"), _md_inline(problem.get("message"))))
        if len(problems) > MR_PROBLEMS_SHOWN:
            parts.append("> - … và %d lỗi khác" % (len(problems) - MR_PROBLEMS_SHOWN))
        parts.append("")
    truncated_paths = review.get("truncated_paths") or []
    if review.get("truncated"):
        parts.extend(["> **Review chưa đầy đủ:** thay đổi quá lớn nên một số file không được xem hết: %s."
                      % _short_list(truncated_paths, MR_PATHS_SHOWN, _md_code), ""])
    if project_rules.get("pending_change"):
        parts.extend(["> Thay đổi quy tắc trong `%s` của MR này chỉ có hiệu lực sau khi được merge."
                      % PROJECT_RULES_PATH, ""])
    profiles = review.get("profiles") or []
    stack = "; ".join("%s (%s)" % (_md_code(p["name"]), ", ".join(_md_code(r) if r else "gốc repo"
                                                                  for r in p.get("roots") or [""]))
                      for p in profiles) or "không có"
    if status == "applied":
        project = _md_code("origin/%s:%s" % (base, PROJECT_RULES_PATH))
    elif status == "invalid":
        project = "không áp dụng (file lỗi)"
    else:
        project = "chưa có file `%s`" % PROJECT_RULES_PATH
    parts.extend(["Quy tắc đã dùng: chung của team; công nghệ: %s; dự án: %s." % (stack, project), ""])
    items = code_review_warning_items(review)
    if review.get("auto") == "nothing_to_review":
        parts.append("Không có file nào cần review code theo quy tắc (chỉ có file được bỏ qua, hoặc không quy tắc "
                     "nào áp dụng cho các file đã đổi).")
    elif not items:
        parts.append("Không có cảnh báo.")
    else:
        shown = items[:MR_REVIEW_MAX_ITEMS]
        for severity in ("major", "minor"):
            group = [f for f in shown if f["severity"] == severity]
            if group:
                parts.append("**Cảnh báo mức %s:**" % severity)
                for finding in group:
                    location = finding["path"] if finding["line"] == "-" else "%s:%s" % (finding["path"],
                                                                                         finding["line"])
                    parts.append("- %s · %s · %s · Gợi ý: %s" % (_md_code(finding["rule"]), _md_code(location),
                                                                _md_inline(finding["problem"]),
                                                                _md_inline(finding["suggestion"])))
        if len(items) > MR_REVIEW_MAX_ITEMS:
            parts.append("… và %d mục khác" % (len(items) - MR_REVIEW_MAX_ITEMS))
    return "\n".join(parts).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# Pure helpers: Jira
# ---------------------------------------------------------------------------

JIRA_TYPE_MAP = {"story": "story", "bug": "bug"}
CREATE_SKIP_FIELDS = frozenset(["project", "issuetype", "summary", "description", "reporter", "assignee"])
TRANSITION_NAMES = {
    "done": ("done", "close", "closed", "close issue", "hoàn thành"),
    "resolved": ("resolve", "resolved", "resolve issue", "fixed"),
}
TARGET_STATUS_NAMES = {"done": ("done", "closed"), "resolved": ("resolved",)}
NAME_REF_TYPES = frozenset(["priority", "version", "component", "resolution", "securitylevel"])


_PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def choose_create_project(override, configured):
    """Project for a NEW ticket: a one-off --project (e.g. the artist board) wins over MPS_JIRA_PROJECT_KEY.

    Existing tickets are never checked against either: any project on the Jira instance is accepted.
    """
    key = (override or configured or "").strip().upper()
    if not _PROJECT_KEY_RE.match(key):
        raise MpsError("invalid_project_key", "Mã project Jira không hợp lệ: '%s' (ví dụ đúng: MPS, ART)."
                       % (override or configured))
    return key


def normalize_issue_type(name):
    return JIRA_TYPE_MAP.get((name or "").strip().casefold())


SPRINT_ACTIVE = "active"
SPRINT_BACKLOG = "backlog"


def parse_sprint_choice(value):
    """argparse type for --sprint: 'active', 'backlog' or a sprint id (a positive number)."""
    text = (value or "").strip().casefold()
    if text in (SPRINT_ACTIVE, SPRINT_BACKLOG):
        return text
    if text.isdigit() and int(text) > 0:
        return int(text)
    raise argparse.ArgumentTypeError("must be 'active', 'backlog' or a sprint id (number), not %r" % value)


def summarize_sprint(sprint):
    def day(value):
        return (value or "")[:10] or None
    return {"id": sprint.get("id"), "name": sprint.get("name"), "start_date": day(sprint.get("startDate")),
            "end_date": day(sprint.get("endDate")), "goal": sprint.get("goal") or None,
            "board_id": sprint.get("originBoardId")}


def sprint_label(sprint):
    end = sprint.get("end_date")
    return "%s (kết thúc %s)" % (sprint.get("name"), end) if end else str(sprint.get("name"))


def choose_sprint(ticket_type, choice, sprints, project_key):
    """Decide where a NEW ticket goes, before anything is created. Returns (sprint or None, note or None).

    ticket_type: 'story' / 'bug'. choice: None (not given), 'active', 'backlog' or a sprint id.
    sprints: active sprints of the project's Scrum boards, or None when Jira cannot tell (no Jira Software).
    A bug goes into the active sprint unless the user said otherwise. A story changes the sprint's scope, so it
    needs an explicit choice whenever there is an active sprint to put it in.
    """
    if choice == SPRINT_BACKLOG:
        return None, None
    if sprints is None:
        return None, ("Jira không cho biết sprint đang chạy (không có Jira Software / không xem được board) nên "
                      "ticket nằm ở backlog; nếu cần, hãy tự kéo vào sprint trên Jira.")
    if not sprints:
        return None, ("Project %s không có sprint nào đang chạy nên ticket nằm ở backlog." % project_key)
    labels = ", ".join(sprint_label(s) for s in sprints)
    if choice is None and ticket_type != "bug":
        raise MpsError("sprint_choice_required",
                       "Story mới làm thay đổi phạm vi sprint: hãy hỏi người dùng muốn đưa vào sprint đang chạy (%s) "
                       "hay để ở backlog, rồi chạy lại với --sprint=active hoặc --sprint=backlog. Chưa tạo ticket nào."
                       % labels, active_sprints=sprints)
    if choice is None or choice == SPRINT_ACTIVE:
        if len(sprints) == 1:
            return sprints[0], None
        raise MpsError("sprint_ambiguous",
                       "Project %s có %d sprint đang chạy cùng lúc (%s). Hãy hỏi người dùng chọn sprint nào rồi chạy "
                       "lại với --sprint=<id>. Chưa tạo ticket nào." % (project_key, len(sprints), labels),
                       active_sprints=sprints)
    for sprint in sprints:
        if sprint.get("id") == choice:
            return sprint, None
    raise MpsError("sprint_not_active",
                   "Sprint %s không phải sprint đang chạy của project %s. Sprint đang chạy: %s. Chưa tạo ticket nào."
                   % (choice, project_key, labels), active_sprints=sprints)


def is_in_target_state(status_name, category_key, target):
    name = (status_name or "").strip().casefold()
    category = (category_key or "").strip().casefold()
    if target == "done":
        return category == "done"
    return name in ("resolved", "closed", "done") or category == "done"


def _pick_transition_for(transitions, target):
    by_name = {}
    for transition in transitions:
        by_name.setdefault((transition.get("name") or "").strip().casefold(), transition)
    for candidate in TRANSITION_NAMES[target]:
        if candidate in by_name:
            return by_name[candidate]
    for transition in transitions:
        to_name = ((transition.get("to") or {}).get("name") or "").strip().casefold()
        if to_name in TARGET_STATUS_NAMES[target]:
            return transition
    return None


def pick_transition(transitions, target):
    """Pick a transition by name (preferred order), then by destination status name.

    Workflows without a Resolve step fall back to the done transitions for target "resolved".
    """
    chosen = _pick_transition_for(transitions, target)
    if chosen is None and target == "resolved":
        chosen = _pick_transition_for(transitions, "done")
    return chosen


def _normalize_allowed_value(value):
    return dict((k, str(value[k])) for k in ("id", "name", "value") if value.get(k) is not None)


def normalize_field_meta(field_id, raw):
    return {
        "id": field_id,
        "name": raw.get("name") or field_id,
        "required": bool(raw.get("required")),
        "has_default": bool(raw.get("hasDefaultValue")),
        "schema": raw.get("schema") or {},
        "allowed_values": [_normalize_allowed_value(v) for v in (raw.get("allowedValues") or [])
                           if isinstance(v, dict)],
    }


def normalize_field_meta_map(fields):
    """Legacy createmeta / transitions shape: {fieldId: {...}}."""
    return dict((fid, normalize_field_meta(fid, raw)) for fid, raw in (fields or {}).items())


def normalize_field_meta_list(values):
    """Jira 9+ createmeta shape: [{"fieldId": ..., ...}]."""
    result = {}
    for raw in values or []:
        field_id = raw.get("fieldId") or raw.get("key")
        if field_id:
            result[field_id] = normalize_field_meta(field_id, raw)
    return result


def describe_field(meta):
    return {
        "id": meta["id"],
        "name": meta["name"],
        "type": meta["schema"].get("type"),
        "allowed_values": meta["allowed_values"],
    }


def find_missing_required_fields(fields_meta, provided):
    missing = [meta for fid, meta in fields_meta.items()
               if meta["required"] and not meta["has_default"]
               and fid not in CREATE_SKIP_FIELDS and fid not in provided]
    return [describe_field(m) for m in sorted(missing, key=lambda m: m["name"].casefold())]


def match_allowed_value(allowed, raw):
    wanted = raw.strip().casefold()
    for value in allowed:
        for attr in ("name", "value", "id"):
            if value.get(attr) is not None and value[attr].strip().casefold() == wanted:
                return value
    return None


def resolve_field_id(fields_meta, name):
    if name in fields_meta:
        return name
    wanted = name.strip().casefold()
    for fid, meta in fields_meta.items():
        if meta["name"].strip().casefold() == wanted or fid.casefold() == wanted:
            return fid
    return None


def build_field_value(meta, raw):
    """Turn a CLI string into the JSON Jira expects for this field."""
    text = raw.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except ValueError:
            raise MpsError("invalid_field_value", "Giá trị JSON không hợp lệ cho trường '%s'." % meta["name"])
    schema_type = meta["schema"].get("type")
    items_type = meta["schema"].get("items")
    if meta["allowed_values"]:
        choice = match_allowed_value(meta["allowed_values"], text)
        if choice is None:
            raise MpsError("invalid_field_value", "Giá trị '%s' không có trong danh sách cho phép của trường '%s'."
                           % (text, meta["name"]), field=describe_field(meta))
        ref = {"id": choice["id"]} if "id" in choice else {"name": choice.get("name") or choice.get("value")}
        return [ref] if schema_type == "array" else ref
    if schema_type == "number":
        try:
            number = float(text)
        except ValueError:
            raise MpsError("invalid_field_value", "Trường '%s' cần một con số." % meta["name"])
        return int(number) if number.is_integer() else number
    if schema_type == "array":
        values = [v.strip() for v in text.split(",") if v.strip()]
        if items_type == "user":
            return [{"name": v} for v in values]
        if items_type in NAME_REF_TYPES:
            return [{"name": v} for v in values]
        return values
    if schema_type == "user":
        return {"name": text}
    if schema_type == "option":
        return {"value": text}
    if schema_type in NAME_REF_TYPES:
        return {"name": text}
    return text


def parse_field_args(field_args, fields_meta):
    provided = {}
    for item in field_args or []:
        if "=" not in item:
            raise MpsError("invalid_field_arg", "Tham số --field phải có dạng tên=giá_trị (nhận được: '%s')." % item)
        name, raw = item.split("=", 1)
        field_id = resolve_field_id(fields_meta, name)
        if field_id is None:
            raise MpsError("unknown_field", "Không tìm thấy trường '%s' trên màn hình tạo ticket." % name.strip(),
                           available_fields=sorted("%s (%s)" % (m["name"], fid) for fid, m in fields_meta.items()))
        provided[field_id] = build_field_value(fields_meta[field_id], raw)
    return provided


PREFERRED_RESOLUTIONS = ("fixed", "done")


def choose_resolution(allowed):
    """'Fixed', else 'Done', else None (never an arbitrary value such as "Won't Fix")."""
    for wanted in PREFERRED_RESOLUTIONS:
        for value in allowed:
            if (value.get("name") or "").strip().casefold() == wanted:
                return value
    return None


def summarize_issue(data, jira_url):
    fields = data.get("fields") or {}
    status = fields.get("status") or {}
    category = status.get("statusCategory") or {}

    def person(raw):
        if not raw:
            return None
        return {"name": raw.get("name"), "displayName": raw.get("displayName"), "email": raw.get("emailAddress")}

    return {
        "key": data.get("key"),
        "summary": fields.get("summary"),
        "description": fields.get("description"),
        "issue_type_name": (fields.get("issuetype") or {}).get("name"),
        "status": status.get("name"),
        "status_category": category.get("key"),
        "assignee": person(fields.get("assignee")),
        "reporter": person(fields.get("reporter")),
        "project_key": (fields.get("project") or {}).get("key"),
        "url": jira_url.rstrip("/") + "/browse/" + (data.get("key") or ""),
    }


def extract_server_message(payload):
    if not isinstance(payload, dict):
        return None
    parts = []
    for message in payload.get("errorMessages") or []:
        parts.append(str(message))
    errors = payload.get("errors")
    if isinstance(errors, dict):
        for field, message in errors.items():
            parts.append("%s: %s" % (field, message))
    for key in ("message", "error"):
        value = payload.get(key)
        if value:
            parts.append(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    if payload.get("raw"):
        parts.append(payload["raw"])
    return "; ".join(parts) if parts else None


def describe_http_error(service, status, payload, path):
    """Map an HTTP status to (code, Vietnamese message)."""
    name = SERVICE_NAMES.get(service, service)
    pat_key = KEY_JIRA_PAT if service == "jira" else KEY_GITLAB_PAT
    if status == 401:
        return "auth_failed", ("%s từ chối token (401): token sai, đã hết hạn hoặc đã bị thu hồi. Hãy tạo token mới "
                               "và tự cập nhật %s trong file .env (không dán token vào chat)." % (name, pat_key))
    if status == 403:
        return "forbidden", ("%s không cho phép thao tác này (403): token thiếu quyền (GitLab cần scope api và "
                             "write_repository) hoặc tài khoản của bạn không có quyền trên project." % name)
    if status == 404:
        return "not_found", "Không tìm thấy trên %s (404): %s. Có thể sai mã/đường dẫn hoặc bạn không có quyền xem." % (
            name, path)
    if status >= 500:
        return "server_error", "%s đang gặp lỗi (%d). Hãy thử lại sau ít phút." % (name, status)
    if 300 <= status < 400:
        return "unexpected_redirect", ("%s chuyển hướng yêu cầu (%d) thay vì trả dữ liệu: có thể sai địa chỉ trong .env "
                                       "(cần https://, đúng tên miền) hoặc token không hợp lệ." % (name, status))
    return "http_error", "%s trả về lỗi %d." % (name, status)


# ---------------------------------------------------------------------------
# IO: HTTP
# ---------------------------------------------------------------------------


class HttpResponse(object):
    def __init__(self, status, data, headers):
        self.status = status
        self.data = data
        self.headers = headers


def _decode_body(raw, strict):
    if not raw:
        return None
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except ValueError:
        if strict:
            return _NOT_JSON
        return {"raw": text[:500]}


_NOT_JSON = object()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib would forward the auth header to any redirect target; refuse redirects (they surface as HTTP 3xx)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ServiceClient(object):
    """Small JSON-over-HTTPS client for one service (jira | gitlab)."""

    def __init__(self, service, base_url, auth_headers, ssl_context):
        self.service = service
        self.base_url = base_url.rstrip("/")
        self.auth_headers = auth_headers
        self.opener = urllib.request.build_opener(_NoRedirectHandler(), urllib.request.HTTPSHandler(context=ssl_context))

    def request(self, method, path, params=None, body=None, allow_statuses=()):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        headers.update(self.auth_headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        name = SERVICE_NAMES[self.service]
        try:
            with self.opener.open(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                payload = _decode_body(resp.read(), strict=True)
                if payload is _NOT_JSON:
                    raise MpsError("invalid_response", "%s trả về dữ liệu không phải JSON (có thể bị chuyển tới "
                                                       "trang đăng nhập: kiểm tra URL và token)." % name,
                                   service=self.service, path=path)
                return HttpResponse(resp.status, payload, resp.headers)
        except urllib.error.HTTPError as exc:
            payload = _decode_body(exc.read(), strict=False)
            if exc.code in allow_statuses:
                return HttpResponse(exc.code, payload, exc.headers)
            code, message = describe_http_error(self.service, exc.code, payload, path)
            raise MpsError(code, message, service=self.service, status=exc.code, path=path,
                           details=extract_server_message(payload))
        except urllib.error.URLError as exc:
            raise network_error(self.service, exc.reason)
        except (socket.timeout, ssl.SSLError, OSError) as exc:
            raise network_error(self.service, exc)

    def get(self, path, params=None):
        return self.request("GET", path, params=params).data


def network_error(service, reason):
    name = SERVICE_NAMES[service]
    details = str(reason)
    if isinstance(reason, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in details:
        return MpsError("ssl_error", "Lỗi chứng chỉ bảo mật (SSL) khi kết nối %s. Nếu công ty dùng chứng chỉ nội bộ, "
                                     "hãy điền đường dẫn file CA vào MPS_CA_BUNDLE trong .env." % name,
                        service=service, details=details)
    if isinstance(reason, socket.timeout) or "timed out" in details.lower():
        return MpsError("timeout", "Kết nối tới %s quá thời gian chờ. Hãy kiểm tra VPN/mạng rồi thử lại." % name,
                        service=service, details=details)
    if isinstance(reason, socket.gaierror):
        return MpsError("network_unreachable", "Không tìm thấy máy chủ %s. Hãy kiểm tra đã bật VPN công ty và mạng "
                                               "đang hoạt động." % name, service=service, details=details)
    return MpsError("network_unreachable", "Không kết nối được tới %s. Hãy kiểm tra VPN công ty và mạng." % name,
                    service=service, details=details)


def build_ssl_context(cfg):
    ca_bundle = cfg.get(KEY_CA_BUNDLE)
    if not ca_bundle:
        return ssl.create_default_context()
    path = ca_bundle if os.path.isabs(ca_bundle) else os.path.join(cfg.root, ca_bundle)
    if not os.path.isfile(path):
        raise MpsError("ca_bundle_missing", "Không tìm thấy file CA khai báo trong MPS_CA_BUNDLE: %s" % path)
    return ssl.create_default_context(cafile=path)


def fetch_latest_plugin_version(cfg, environ=None):
    """Version in the plugin.json on GitHub main, or None. Best effort: never raises, at most one short request.

    Runs in a daemon thread that is given VERSION_CHECK_TIMEOUT_SECONDS in total, because the socket timeout does
    not cover a slow DNS lookup. Skipped when the user turned non-essential traffic off.
    """
    environ = os.environ if environ is None else environ
    if environ.get(NONESSENTIAL_TRAFFIC_ENV):
        return None
    found = []
    worker = threading.Thread(target=lambda: found.append(_fetch_manifest_version(cfg)))
    worker.daemon = True
    worker.start()
    worker.join(VERSION_CHECK_TIMEOUT_SECONDS)
    return found[0] if found else None


def _fetch_manifest_version(cfg):
    """Trusts the public CAs plus MPS_CA_BUNDLE (TLS-inspecting company proxies), unlike build_ssl_context, which
    trusts only the bundle. Any failure gives None."""
    try:
        context = ssl.create_default_context()
        ca_bundle = cfg.get(KEY_CA_BUNDLE)
        if ca_bundle:
            path = ca_bundle if os.path.isabs(ca_bundle) else os.path.join(cfg.root, ca_bundle)
            if os.path.isfile(path):
                context.load_verify_locations(path)
        opener = urllib.request.build_opener(_NoRedirectHandler(), urllib.request.HTTPSHandler(context=context))
        request = urllib.request.Request(PLUGIN_MANIFEST_URL, headers={"User-Agent": USER_AGENT})
        with opener.open(request, timeout=VERSION_CHECK_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read(MANIFEST_MAX_BYTES).decode("utf-8"))
    except Exception:  # noqa: BLE001 - offline, proxy, TLS, HTTP or JSON errors all mean "unknown"
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return version.strip() if parse_plugin_version(version) is not None else None


def _require_https(cfg, key):
    url = cfg.get(key)
    if not url.lower().startswith("https://"):
        raise MpsError("insecure_url", "%s phải bắt đầu bằng https:// (token không được gửi qua kết nối không mã hoá)."
                       % key)
    return url


def jira_client(cfg):
    cfg.require(KEY_JIRA_URL, KEY_JIRA_PAT)
    url = _require_https(cfg, KEY_JIRA_URL)
    return ServiceClient("jira", url, {"Authorization": "Bearer " + cfg.get(KEY_JIRA_PAT)}, build_ssl_context(cfg))


def gitlab_client(cfg):
    cfg.require(KEY_GITLAB_URL, KEY_GITLAB_PAT)
    url = _require_https(cfg, KEY_GITLAB_URL)
    return ServiceClient("gitlab", url.rstrip("/") + "/api/v4", {"PRIVATE-TOKEN": cfg.get(KEY_GITLAB_PAT)},
                         build_ssl_context(cfg))


def gitlab_get_all(gitlab, path, params):
    items = []
    page = 1
    for _ in range(MAX_PAGES):
        query = dict(params)
        query.update({"per_page": GITLAB_PER_PAGE, "page": page})
        resp = gitlab.request("GET", path, params=query)
        batch = resp.data or []
        items.extend(batch)
        next_page = (resp.headers.get("X-Next-Page") or "").strip() if resp.headers else ""
        if next_page:
            page = int(next_page)
        elif len(batch) < GITLAB_PER_PAGE:
            break
        else:
            page += 1
    return items


def jira_paged_values(jira, path, params=None, allow_statuses=()):
    """All `values` of a paged Jira endpoint. With allow_statuses, a refused FIRST page returns None."""
    values = []
    start = 0
    for _ in range(MAX_PAGES):
        query = dict(params or {}, startAt=start, maxResults=JIRA_PAGE_SIZE)
        resp = jira.request("GET", path, params=query, allow_statuses=allow_statuses)
        if resp.status in allow_statuses:
            if start == 0:
                return None
            break
        data = resp.data or {}
        batch = data.get("values") or []
        values.extend(batch)
        start += len(batch)
        total = data.get("total")
        if data.get("isLast") or not batch or (total is not None and start >= total):
            break
    return values


# ---------------------------------------------------------------------------
# IO: configuration
# ---------------------------------------------------------------------------


class Config(object):
    """Values from <project root>/.env. Process environment variables are intentionally ignored."""

    def __init__(self, root, values, env_exists):
        self.root = root
        self.values = values
        self.env_exists = env_exists
        self.env_path = os.path.join(root, ENV_FILENAME)

    def get(self, key):
        value = (self.values.get(key) or "").strip()
        return value or DEFAULTS.get(key, "")

    def require(self, *keys):
        missing = [k for k in keys if not self.get(k)]
        if missing:
            raise self.missing_config_error(missing)

    def fill_guide(self, keys=None, token_rejected=False):
        return env_fill_guide(self.values, self.get(KEY_JIRA_URL), self.get(KEY_GITLAB_URL), keys=keys,
                              token_rejected=token_rejected)

    def missing_config_error(self, missing, **extra):
        return MpsError("missing_config", "File .env còn thiếu: %s. Hãy tự mở file .env bằng trình soạn thảo "
                                          "để điền (không dán token vào chat)." % ", ".join(missing),
                        missing_keys=missing, env_path=self.env_path, fill_guide=self.fill_guide(keys=missing), **extra)

    def branches(self):
        return {"dev": self.get(KEY_BRANCH_DEV), "beta_prefix": self.get(KEY_BRANCH_BETA_PREFIX),
                "prod": self.get(KEY_BRANCH_PROD)}


def read_text_file(path):
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8-sig", "replace")


def load_config(root):
    path = os.path.join(root, ENV_FILENAME)
    exists = os.path.isfile(path)
    values = parse_env(read_text_file(path)) if exists else {}
    for key in (KEY_JIRA_PAT, KEY_GITLAB_PAT):
        register_secret((values.get(key) or "").strip())
    return Config(root, values, exists)


# ---------------------------------------------------------------------------
# IO: git
# ---------------------------------------------------------------------------


class GitResult(object):
    def __init__(self, code, stdout, stderr):
        self.code = code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self):
        return self.code == 0


def git_base_env():
    """Environment for every git call: English messages, because git's stderr text is parsed."""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANGUAGE"] = "C"
    return env


def run_git(args, cwd, env=None, check=True, literal_pathspecs=False, input_bytes=None):
    cmd = ["git", "-c", "core.quotepath=false"]
    if literal_pathspecs:
        cmd.append("--literal-pathspecs")
    cmd.extend(args)
    stdin_kwargs = {"stdin": subprocess.DEVNULL} if input_bytes is None else {"input": input_bytes}
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env if env is not None else git_base_env(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, **stdin_kwargs)
    except OSError as exc:
        raise MpsError("git_not_found", "Không chạy được lệnh git. Hãy cài Git và thử lại.", details=str(exc))
    result = GitResult(proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))
    if check and not result.ok:
        raise MpsError("git_failed", "Lệnh git thất bại: git %s" % " ".join(args[:2]),
                       stderr=result.stderr.strip(), command="git " + " ".join(args))
    return result


def find_project_root():
    result = run_git(["rev-parse", "--show-toplevel"], cwd=os.getcwd(), check=False)
    if not result.ok or not result.stdout.strip():
        raise MpsError("not_git_repo", "Thư mục hiện tại không nằm trong một project git. Hãy mở đúng thư mục project.",
                       cwd=os.getcwd())
    return os.path.normpath(result.stdout.strip())


def current_branch(root):
    result = run_git(["symbolic-ref", "--short", "-q", "HEAD"], root, check=False)
    return result.stdout.strip() if result.ok else None


def head_exists(root):
    return run_git(["rev-parse", "--verify", "-q", "HEAD"], root, check=False).ok


def ref_exists(root, ref):
    return run_git(["show-ref", "--verify", "--quiet", ref], root, check=False).ok


def git_dir(root):
    return os.path.normpath(run_git(["rev-parse", "--absolute-git-dir"], root).stdout.strip())


def operations_in_progress(root):
    directory = git_dir(root)
    markers = (("MERGE_HEAD", "merge"), ("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
               ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"))
    found = []
    for marker, name in markers:
        if os.path.exists(os.path.join(directory, marker)) and name not in found:
            found.append(name)
    return found


def ensure_no_operation_in_progress(root):
    ops = operations_in_progress(root)
    if ops:
        raise MpsError("operation_in_progress", "Git đang dở một thao tác (%s). Cần xử lý xong trước — hãy nhờ "
                                                "developer giúp." % ", ".join(ops), operations=ops)


def git_status(root):
    output = run_git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], root).stdout
    return parse_porcelain_z(output)


def raise_unmerged(files):
    raise MpsError("unmerged_files", "Có file đang bị xung đột (conflict) chưa được giải quyết: %s. Không được commit "
                                     "trong tình trạng này — hãy nhờ developer giúp." % ", ".join(files[:10]),
                   files=files)


def ensure_no_unmerged(root):
    """A failed `stash pop` leaves conflict entries without MERGE_HEAD; they must never be committed."""
    unmerged = git_status(root)["unmerged"]
    if unmerged:
        raise_unmerged(unmerged)


def staged_paths(root):
    output = run_git(["diff", "--cached", "--name-only", "-z", "--no-renames"], root).stdout
    return [p for p in output.split("\0") if p]


def unstage(root, paths):
    """Remove paths from the index only; the working tree is never touched."""
    if not paths:
        return
    if head_exists(root):
        run_git(["reset", "-q", "--"] + list(paths), root, literal_pathspecs=True)
    else:
        run_git(["rm", "--cached", "-q", "--"] + list(paths), root, literal_pathspecs=True)


def unpushed_commit_count(root):
    """Commits reachable from HEAD that are on no origin branch, minus pushed work that already landed.

    After a (squash-)merge GitLab deletes the ticket branch and `fetch --prune` drops origin/<branch>; its commits
    are then on no remote ref. The commits up to the last push (`branch.<name>.mps-pushed`) are exempt, but only
    when their changes are really in origin/<recorded base>: an MR closed without merging must still count, or
    the work would be left behind silently. 0 before the first commit.
    """
    if not head_exists(root):
        return 0
    branch = current_branch(root)
    pushed = last_pushed_commit(root, branch)
    exempt = [pushed] if pushed and pushed_work_landed(root, pushed, recorded_base(root, branch)) else []
    args = ["rev-list", "--count", "HEAD", "--not", "--remotes=origin"] + exempt
    return int(run_git(args, root).stdout.strip() or 0)


def pushed_work_landed(root, pushed, base):
    """True if the changes up to `pushed` are already in origin/<base> (normal merge, rebase or squash-merge)."""
    if not base or not ref_exists(root, "refs/remotes/origin/" + base):
        return False
    base_ref = "refs/remotes/origin/" + base
    cherry = run_git(["cherry", base_ref, pushed], root).stdout
    if not any(line.startswith("+") for line in cherry.splitlines()):
        return True  # every commit has an equivalent patch upstream
    merge_base = run_git(["merge-base", base_ref, pushed], root, check=False).stdout.strip()
    if not merge_base:
        return False
    paths = [p for p in run_git(["diff", "--name-only", "-z", "--no-renames", merge_base, pushed], root).stdout
             .split("\0") if p]
    if not paths:
        return True
    # Squash-merge: one combined commit upstream, so compare the resulting content of every path the branch touched.
    same = run_git(["diff", "--quiet", pushed, base_ref, "--"] + paths, root, check=False, literal_pathspecs=True)
    return same.code == 0


def git_identity(root):
    name = run_git(["config", "user.name"], root, check=False).stdout.strip()
    email = run_git(["config", "user.email"], root, check=False).stdout.strip()
    return name, email


def lfs_tracked(root, paths):
    """Subset of paths whose `filter` attribute is lfs (one batched check-attr call)."""
    if not paths:
        return set()
    stdin = ("\0".join(paths) + "\0").encode("utf-8")
    output = run_git(["check-attr", "-z", "--stdin", "filter"], root, input_bytes=stdin).stdout
    return set(path for path, value in parse_check_attr_z(output).items() if value == "lfs")


def foreign_commits(root, base_ref, branch_ref, key):
    """Commits in base_ref..branch_ref whose subject does not mention the ticket key."""
    log = run_git(["log", "--no-merges", "--format=%H%x09%s", "%s..%s" % (base_ref, branch_ref)], root).stdout
    return find_foreign_commits(log, key)


def ensure_branch_matches_base(root, base, branch_ref, branch_name, key):
    foreign = foreign_commits(root, "origin/" + base, branch_ref, key)
    if foreign:
        raise MpsError("branch_base_mismatch",
                       "Nhánh %s đã có %d commit không thuộc ticket %s so với %s (thường do nhánh này được tạo từ một "
                       "nhánh gốc khác, ví dụ từ develop thay vì release). Dùng nhánh này sẽ kéo theo code chưa được "
                       "phát hành. Hãy nhờ developer kiểm tra, hoặc dùng một nhánh tên khác cho giai đoạn này."
                       % (branch_name, len(foreign), key, "origin/" + base),
                       branch=branch_name, base=base, foreign_commits=foreign[:FOREIGN_COMMITS_REPORTED],
                       foreign_commit_count=len(foreign))


def _base_config_key(branch):
    return "branch.%s.%s" % (branch, BASE_CONFIG_NAME)


def recorded_base(root, branch):
    """Base branch recorded by prepare-branch for this ticket branch (repo-local git config), or None."""
    if not branch:
        return None
    result = run_git(["config", "--local", "--get", _base_config_key(branch)], root, check=False)
    return result.stdout.strip() or None


def record_base(root, branch, base):
    run_git(["config", "--local", _base_config_key(branch), base], root)


def ensure_recorded_base_matches(root, branch, base):
    recorded = recorded_base(root, branch)
    if recorded and recorded != base:
        raise MpsError("base_mismatch",
                       "Nhánh %s được tạo từ %s nên phải gộp (merge) về đúng %s, không phải %s. Nếu thật sự cần đưa thay "
                       "đổi này sang %s, hãy nhờ developer." % (branch, recorded, recorded, base, base),
                       branch=branch, recorded_base=recorded, requested_base=base)
    return recorded


def ensure_valid_base(name, branches):
    """Ticket branches are only ever based on / merged into develop, master or a release/* branch."""
    if not is_protected_branch(name, branches):
        raise MpsError("invalid_base", "Nhánh gốc/đích '%s' không hợp lệ: chỉ dùng %s, %s hoặc %s*." % (
            name, branches["dev"], branches["prod"], branches["beta_prefix"]),
            base=name, allowed=[branches["dev"], branches["prod"], branches["beta_prefix"] + "*"])


def closest_bases(counts):
    """{base: commits in origin/base..source} -> the base(s) the source branch was most likely made from."""
    if not counts:
        return []
    fewest = min(counts.values())
    return sorted(name for name, count in counts.items() if count == fewest)


def inferred_target_verdict(target, inferred, dev_branch):
    """"ok", "mismatch" (target is not a closest base) or "ambiguous" (a tie, and the target is not the dev branch).

    A tie happens when e.g. master and a release branch point at the same commit; only develop - the safe, normal
    target - is accepted then.
    """
    if target not in inferred:
        return "mismatch"
    if len(inferred) > 1 and target != dev_branch:
        return "ambiguous"
    return "ok"


def origin_base_candidates(root, branches):
    names = [branches["dev"], branches["prod"]]
    output = run_git(["for-each-ref", "--format=%(refname:strip=3)", "refs/remotes/origin/" + branches["beta_prefix"]],
                     root).stdout
    names.extend(line.strip() for line in output.splitlines() if line.strip())
    return [n for n in names if ref_exists(root, "refs/remotes/origin/" + n)]


def _source_ref(root, source):
    """What an MR from `source` contains: origin/<source> (the pushed branch) when it exists, else the local branch."""
    if ref_exists(root, "refs/remotes/origin/" + source):
        return "refs/remotes/origin/" + source
    if ref_exists(root, "refs/heads/" + source):
        return "refs/heads/" + source
    raise MpsError("branch_not_found", "Không có nhánh %s trên máy lẫn trên GitLab (đã push chưa?)." % source,
                   branch=source)


def ensure_mr_target(root, source, target, key, branches):
    """Offline guard before creating/reusing an MR.

    The target must be the recorded base of the source branch; without a record, the protected branch the source
    is closest to (fewest commits in origin/X..source). Every non-merge commit in the range must mention the key.
    The pushed branch (origin/<source>) is what the MR contains, so it is preferred over the local branch.
    """
    ensure_valid_base(target, branches)
    recorded = recorded_base(root, source)
    if recorded and recorded != target:
        raise MpsError("target_mismatch_recorded_base",
                       "Nhánh %s được tạo từ %s nên merge request phải vào %s, không phải %s." % (
                           source, recorded, recorded, target),
                       source=source, recorded_base=recorded, target=target)
    if not ref_exists(root, "refs/remotes/origin/" + target):
        raise MpsError("base_not_found", "Chưa có origin/%s trên máy (nhánh đích không tồn tại hoặc chưa tải về)."
                       % target, base=target)
    source_ref = _source_ref(root, source)
    if not recorded:
        counts = {}
        for name in origin_base_candidates(root, branches):
            log_range = "refs/remotes/origin/%s..%s" % (name, source_ref)
            counts[name] = int(run_git(["rev-list", "--count", log_range], root).stdout.strip() or 0)
        inferred = closest_bases(counts)
        verdict = inferred_target_verdict(target, inferred, branches["dev"])
        if verdict == "mismatch":
            raise MpsError("target_mismatch_inferred_base",
                           "Nhánh %s có vẻ được tạo từ %s, không phải %s. Merge request phải vào đúng nhánh gốc — hãy "
                           "nhờ developer kiểm tra." % (source, " / ".join(inferred), target),
                           source=source, target=target, inferred_bases=inferred, commit_counts=counts)
        if verdict == "ambiguous":
            raise MpsError("target_ambiguous",
                           "Không xác định chắc nhánh %s được tạo từ đâu (%s đều có thể). Chỉ cho phép tự động khi "
                           "đích là %s; với %s hãy nhờ developer kiểm tra." % (
                               source, " / ".join(inferred), branches["dev"], target),
                           source=source, target=target, inferred_bases=inferred, commit_counts=counts)
    ensure_branch_matches_base(root, target, source_ref, source, key)
    return recorded


def head_sha(root):
    result = run_git(["rev-parse", "-q", "--verify", "HEAD"], root, check=False)
    return result.stdout.strip() if result.ok else None


def file_blobs(root, paths):
    """{path: git blob hash of the working-tree file, or "deleted"} - one batched hash-object call."""
    existing = [p for p in paths if os.path.isfile(os.path.join(root, p))]
    blobs = dict((p, "deleted") for p in paths)
    if existing:
        stdin = ("\n".join(existing) + "\n").encode("utf-8")
        hashes = run_git(["hash-object", "--stdin-paths"], root, input_bytes=stdin).stdout.split()
        blobs.update(zip(existing, hashes))
    return blobs


def scope_path(root):
    return os.path.join(mps_tmp_dir(root), SCOPE_FILENAME)


def bundle_meta_path(root):
    return os.path.join(mps_tmp_dir(root), BUNDLE_META_FILENAME)


def _read_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def load_scope(root, branch):
    """The decisions of the last `review classify`: valid only if complete and for the same branch and HEAD."""
    scope = _read_json(scope_path(root))
    if scope is None:
        raise MpsError("scope_review_required", "Chưa có kết quả review phạm vi cho các thay đổi hiện tại. Hãy chạy "
                                                "review phạm vi (bước 6) trước khi commit.")
    if scope.get("branch") != branch or scope.get("head") != head_sha(root):
        raise MpsError("scope_review_required", "Kết quả review phạm vi đã cũ (nhánh hoặc commit đã thay đổi từ lúc "
                                                "review). Hãy review lại.",
                       reviewed_branch=scope.get("branch"), current_branch=branch)
    if not scope.get("complete"):
        raise MpsError("scope_incomplete", "Kết quả review phạm vi chưa đầy đủ (thiếu file, thiếu VERDICT hoặc có đường "
                                           "dẫn lạ). Hãy yêu cầu reviewer trả lời lại cho đủ rồi chạy review classify.",
                       unclassified_files=scope.get("unclassified_files"))
    return scope


def pushed_config_key(branch):
    return "branch.%s.%s" % (branch, PUSHED_CONFIG_NAME)


def last_pushed_commit(root, branch):
    """Commit this skill last pushed for `branch` (kept after GitLab deletes the merged branch), or None."""
    if not branch:
        return None
    sha = run_git(["config", "--local", "--get", pushed_config_key(branch)], root, check=False).stdout.strip()
    if sha and run_git(["rev-parse", "-q", "--verify", sha + "^{commit}"], root, check=False).ok:
        return sha
    return None


def check_against_scope(scope, requested, current_blobs, include_out_of_scope):
    """Every requested file must be approved by the review (or explicitly named by the user) and unchanged since."""
    allowed = set(scope.get("commit_files") or []) | set(include_out_of_scope)
    not_in_scope = [p for p in requested if p not in allowed]
    if not_in_scope:
        raise MpsError("not_in_scope", "Các file sau không nằm trong danh sách được review cho phép commit: %s. Chỉ "
                                       "thêm khi người dùng chỉ đích danh từng file (--include-out-of-scope)."
                       % ", ".join(not_in_scope), files=not_in_scope)
    reviewed = scope.get("blobs") or {}
    changed = [p for p in requested if reviewed.get(p) != current_blobs.get(p)]
    if changed:
        raise MpsError("changed_since_review", "Các file sau đã thay đổi (hoặc chưa được review) sau lần review phạm vi: "
                                               "%s. Hãy chạy lại review." % ", ".join(changed), files=changed)


def review_candidates(root, base_ref):
    """Files the reviewer must classify: uncommitted changes (the commit decision) and commits already on the branch.

    .env files are never candidates (they can never be committed); rename sources follow their new path.
    """
    status = git_status(root)
    sources = set(status["renames"].values())
    uncommitted = [p for p in _changed_paths(status) if not is_env_file(p) and p not in sources]
    committed = []
    if head_exists(root) and ref_exists(root, "refs/remotes/" + base_ref):
        committed = [p for p in _name_only_z(root, [base_ref + "...HEAD"])
                     if not is_env_file(p) and p not in uncommitted]
    return uncommitted, committed


def mps_tmp_dir(root):
    """Scratch folder for temp files (descriptions, comments) inside the git dir: never committed."""
    path = os.path.join(git_dir(root), TMP_DIRNAME)
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def origin_url(root, push=False):
    result = run_git(["remote", "get-url"] + (["--push"] if push else []) + ["origin"], root, check=False)
    return result.stdout.strip() if result.ok else None


def validate_branch_name(root, name):
    if not name or not run_git(["check-ref-format", "--branch", name], root, check=False).ok:
        raise MpsError("invalid_branch_name", "Tên nhánh không hợp lệ: '%s'." % name)


def ensure_env_gitignored(root):
    """Append `.env` to <root>/.gitignore unless git already ignores it. Returns True if the file was changed."""
    if run_git(["check-ignore", "-q", "--no-index", ENV_FILENAME], root, check=False).code == 0:
        return False
    path = os.path.join(root, ".gitignore")
    existing = b""
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            existing = handle.read()
    newline = b"\r\n" if b"\r\n" in existing else b"\n"
    prefix = newline if existing and not existing.endswith(b"\n") else b""
    with open(path, "ab") as handle:
        handle.write(prefix + ENV_FILENAME.encode("ascii") + newline)
    return True


def env_is_tracked(root):
    return bool(run_git(["ls-files", "--", ENV_FILENAME], root, check=False).stdout.strip())


def project_settings_path(root):
    return os.path.join(root, *PROJECT_SETTINGS_PATH.split("/"))


def load_project_settings(root):
    """<root>/.claude/settings.json as a dict, or None when it is missing, unreadable or not a JSON object."""
    path = project_settings_path(root)
    if not os.path.isfile(path):
        return None
    try:
        return parse_settings_text(read_text_file(path))
    except (MpsError, OSError):
        return None


def project_settings_status(root):
    """project_integration_status of <root>/.claude/settings.json; a missing or unreadable file counts as "missing"."""
    return project_integration_status(load_project_settings(root))


def write_file_atomically(path, data):
    """Write bytes through a temp file in the same folder, so a crash never leaves a half-written file."""
    temp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)
    except OSError:
        if os.path.exists(temp):
            os.remove(temp)
        raise


def git_network_env(cfg, with_token):
    env = git_base_env()
    env["GIT_TERMINAL_PROMPT"] = "0"
    entries = []
    ca_bundle = cfg.get(KEY_CA_BUNDLE)
    if ca_bundle:
        entries.append(("http.sslCAInfo", ca_bundle if os.path.isabs(ca_bundle) else os.path.join(cfg.root, ca_bundle)))
    if with_token:
        credentials = base64.b64encode(("oauth2:" + cfg.get(KEY_GITLAB_PAT)).encode("utf-8")).decode("ascii")
        register_secret(credentials)
        # URL-scoped key: the header is only sent to the MPS GitLab, never to other hosts (submodules, mirrors).
        scoped_key = "http.%s/.extraHeader" % cfg.get(KEY_GITLAB_URL).rstrip("/")
        entries.append((scoped_key, "Authorization: Basic " + credentials))
    try:
        index = int(env.get("GIT_CONFIG_COUNT") or 0)
    except ValueError:
        index = 0
    for key, value in entries:
        env["GIT_CONFIG_KEY_%d" % index] = key
        env["GIT_CONFIG_VALUE_%d" % index] = value
        index += 1
    if entries:
        env["GIT_CONFIG_COUNT"] = str(index)
    return env


def token_fallback_allowed(cfg, root):
    """Only inject the GitLab PAT when both origin fetch and push URLs are https on the configured GitLab host."""
    if not cfg.get(KEY_GITLAB_PAT):
        return False
    gitlab_host = _host_of(cfg.get(KEY_GITLAB_URL))
    for url in (origin_url(root), origin_url(root, push=True)):
        scheme, host, _ = parse_remote(url)
        if scheme != "https" or host is None or host != gitlab_host:
            return False
    return True


def run_git_network(root, args, cfg):
    """Run fetch/push; on an auth error over https retry once with the PAT passed via environment (never argv)."""
    result = run_git(args, root, env=git_network_env(cfg, False), check=False)
    if result.ok or not is_git_auth_error(result.stderr) or not token_fallback_allowed(cfg, root):
        return result, False
    return run_git(args, root, env=git_network_env(cfg, True), check=False), True


def raise_git_network_error(result, operation):
    code, message = classify_git_network_error(result.stderr, operation)
    raise MpsError(code, message, stderr=result.stderr.strip())


# ---------------------------------------------------------------------------
# IO: GitLab / Jira lookups
# ---------------------------------------------------------------------------


def resolve_gitlab_project(cfg, gitlab):
    path = cfg.get(KEY_GITLAB_PROJECT).strip("/")
    source = "env"
    if not path:
        remote = origin_url(cfg.root)
        path = parse_remote_project_path(remote, cfg.get(KEY_GITLAB_URL)) if remote else None
        source = "git_remote"
        if not path:
            raise MpsError("gitlab_project_unknown",
                           "Không tự xác định được project GitLab từ remote origin. Hãy hỏi người dùng đường dẫn "
                           "project (dạng group/project) rồi lưu bằng: env set MPS_GITLAB_PROJECT <group/project>.",
                           remote_url=sanitize_remote_url(remote))
    if path.endswith(".git"):
        path = path[:-len(".git")]
    try:
        data = gitlab.get("/projects/" + urllib.parse.quote(path, safe=""))
    except MpsError as exc:
        if exc.code == "not_found":
            raise MpsError("gitlab_project_not_found", "Không tìm thấy project GitLab '%s' (hoặc bạn không có quyền "
                                                       "xem)." % path, project_path=path, source=source)
        raise
    return {"id": data.get("id"), "path": data.get("path_with_namespace"), "web_url": data.get("web_url"),
            "default_branch": data.get("default_branch"), "source": source}


def gitlab_access_level(gitlab, project_id, user_id):
    """Effective access level (inherited included). 0 = not a member, None = GitLab refused to tell (403)."""
    resp = gitlab.request("GET", "/projects/%s/members/all/%s" % (project_id, user_id), allow_statuses=(403, 404))
    if resp.status == 403:
        return None
    if resp.status == 404 or not resp.data:
        return 0
    return int(resp.data.get("access_level") or 0)


def list_jira_projects(jira):
    projects = jira.get("/rest/api/2/project") or []
    return sorted(({"key": p.get("key"), "name": p.get("name")} for p in projects), key=lambda p: p["key"] or "")


def fetch_issue(jira, key):
    try:
        return jira.get("/rest/api/2/issue/" + urllib.parse.quote(key),
                        params={"fields": "summary,description,issuetype,status,assignee,reporter,project"})
    except MpsError as exc:
        if exc.code == "not_found":
            raise MpsError("ticket_not_found", "Không tìm thấy ticket %s trên Jira (hoặc bạn không có quyền xem)." % key,
                           key=key)
        raise


def match_issue_type(types, wanted):
    for issue_type in types or []:
        if (issue_type.get("name") or "").strip().casefold() == wanted.casefold():
            return issue_type
    raise MpsError("issue_type_not_found", "Project Jira không có loại ticket '%s'." % wanted,
                   available_types=[t.get("name") for t in types or []])


def load_create_meta(jira, project_key, type_name):
    """Return (issuetype, fields_meta, source). Jira 9+ endpoints first, legacy createmeta as fallback."""
    base = "/rest/api/2/issue/createmeta/%s/issuetypes" % urllib.parse.quote(project_key)
    probe = jira.request("GET", base, params={"startAt": 0, "maxResults": JIRA_PAGE_SIZE}, allow_statuses=(404,))
    if probe.status != 404:
        issue_type = match_issue_type(jira_paged_values(jira, base), type_name)
        fields = jira_paged_values(jira, base + "/" + urllib.parse.quote(str(issue_type.get("id"))))
        return issue_type, normalize_field_meta_list(fields), "createmeta_v9"
    # A 404 above means either Jira < 9 (endpoint missing) or a wrong project key on Jira 9+ (where the legacy
    # endpoint is gone too). Both "404 here" and "no project here" therefore mean the key is wrong.
    legacy = jira.request("GET", "/rest/api/2/issue/createmeta", allow_statuses=(404,),
                          params={"projectKeys": project_key, "expand": "projects.issuetypes.fields"})
    projects = (legacy.data or {}).get("projects") or [] if legacy.status != 404 else []
    if not projects:
        raise MpsError("jira_project_not_found", "Không tìm thấy project Jira '%s' hoặc bạn không có quyền tạo ticket "
                                                 "trong đó. Hãy kiểm tra lại MPS_JIRA_PROJECT_KEY (chạy env check để "
                                                 "xem danh sách project)." % project_key, project_key=project_key)
    issue_type = match_issue_type(projects[0].get("issuetypes"), type_name)
    return issue_type, normalize_field_meta_map(issue_type.get("fields")), "createmeta_legacy"


_AGILE_REFUSED = (400, 401, 403, 404)


def find_active_sprints(jira, project_key):
    """Active sprints on the Scrum boards of a project, deduplicated and sorted by id.

    None = Jira cannot tell (Jira Software agile API missing, or every board's sprint list refused). Kanban boards
    have no sprints. A board also lists another board's sprint when one of its issues sits there; such a sprint
    (originBoardId not one of the project's own Scrum boards) belongs to another team and is left out.
    """
    boards = jira_paged_values(jira, "/rest/agile/1.0/board", params={"projectKeyOrId": project_key, "type": "scrum"},
                               allow_statuses=_AGILE_REFUSED)
    if boards is None:
        return None
    board_ids = set(board.get("id") for board in boards if board.get("id") is not None)
    found = {}
    refused = 0
    for board_id in sorted(board_ids):
        sprints = jira_paged_values(jira, "/rest/agile/1.0/board/%s/sprint" % board_id,
                                    params={"state": "active"}, allow_statuses=_AGILE_REFUSED)
        if sprints is None:
            refused += 1
            continue
        for sprint in sprints:
            origin = sprint.get("originBoardId")
            if (sprint.get("state") or "active").casefold() == "active" and sprint.get("id") is not None \
                    and (origin is None or origin in board_ids):
                found.setdefault(sprint.get("id"), summarize_sprint(sprint))
    if board_ids and refused == len(board_ids):
        return None
    return [found[key] for key in sorted(found)]


def move_issue_to_sprint(jira, key, sprint):
    """True when Jira accepted the move. Never raises: the ticket already exists, an error must not hide its key."""
    try:
        resp = jira.request("POST", "/rest/agile/1.0/sprint/%s/issue" % sprint.get("id"), body={"issues": [key]},
                            allow_statuses=_AGILE_REFUSED)
    except MpsError:
        return False
    return resp.status in (200, 201, 204)


def read_text_arg(value, file_path, label):
    if file_path:
        try:
            return read_text_file(file_path)
        except OSError as exc:
            raise MpsError("file_not_readable", "Không đọc được file %s: %s" % (label, file_path), details=str(exc))
    return value or ""


# ---------------------------------------------------------------------------
# Commands: env
# ---------------------------------------------------------------------------


def open_in_editor(path):
    try:
        if sys.platform.startswith("win"):
            try:
                os.startfile(path)  # noqa: S606 - opens the user's own file with its associated app
            except OSError:
                subprocess.Popen(["notepad.exe", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-t", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except OSError:
        return False


def cmd_env_init(args):
    root = find_project_root()
    env_path = os.path.join(root, ENV_FILENAME)
    created = False
    if not os.path.exists(env_path):
        if not os.path.isfile(ENV_TEMPLATE_PATH):
            raise MpsError("template_missing", "Không tìm thấy file mẫu env.example của skill.",
                           template=ENV_TEMPLATE_PATH)
        with open(ENV_TEMPLATE_PATH, "rb") as src:
            content = src.read()
        with open(env_path, "xb") as dst:
            dst.write(content)
        created = True
    gitignore_updated = ensure_env_gitignored(root)
    # Only the member keys still blank in the resulting .env (an existing, filled .env gives an empty guide).
    guide = load_config(root).fill_guide()
    result = {"env_path": env_path, "created": created, "gitignore_updated": gitignore_updated,
              "fill_guide": guide, "keys_to_fill": [entry["key"] for entry in guide]}
    if args.open:
        result["opened_in_editor"] = open_in_editor(env_path)
    return result


def _plugin_version_status(cfg, pinned_ref):
    """({running, latest, checked[, pinned]}, warnings). An unreachable GitHub only gives checked: false.

    A project that pins the marketplace to a `ref` chose that version on purpose: no lookup, no plugin_outdated.
    """
    if pinned_ref:
        return {"running": VERSION, "latest": None, "checked": False, "pinned": pinned_ref}, []
    latest = fetch_latest_plugin_version(cfg)
    info = {"running": VERSION, "latest": latest, "checked": latest is not None}
    warnings = []
    if is_newer_version(latest, VERSION):
        warnings.append(plugin_outdated_warning(latest, VERSION, update_blockers(os.environ)))
    return info, warnings


def cmd_env_check(args):
    root = find_project_root()
    cfg = load_config(root)
    settings = load_project_settings(root)
    version_info, warnings = _plugin_version_status(cfg, pinned_marketplace_ref(settings))
    if project_integration_status(settings) != "integrated":
        warnings.append(project_not_integrated_warning())
    if project_declares_legacy_source(settings):
        warnings.append(legacy_project_source_warning())
    try:
        result = _check_env(root, cfg, warnings)
    except MpsError as exc:
        pat_key = SERVICE_PAT_KEYS.get(exc.extra.get("service"))
        if exc.code == "auth_failed" and pat_key:
            exc.extra.setdefault("fill_guide", cfg.fill_guide(keys=[pat_key], token_rejected=True))
        # The agent handles plugin_outdated before fixing the error, so errors carry the warnings too.
        exc.extra.setdefault("warnings", warnings)
        exc.extra.setdefault("plugin_version", version_info)
        raise
    result["plugin_version"] = version_info
    return result


def _check_env(root, cfg, warnings):
    if not cfg.env_exists:
        raise MpsError("env_missing", "Chưa có file .env ở thư mục gốc project. Hãy chạy: env init --open",
                       env_path=cfg.env_path, next="env init --open")
    gitignore_updated = ensure_env_gitignored(root)
    if env_is_tracked(root):
        warnings.append({"code": "env_tracked", "message": "File .env đang bị git theo dõi (đã từng được commit). "
                                                           "Cần developer gỡ nó khỏi git (git rm --cached .env) "
                                                           "và đổi token mới."})
    rejected_patterns = parse_generated_patterns(cfg.get(KEY_GENERATED_PATTERNS))[1]
    if rejected_patterns:
        warnings.append(invalid_generated_warning(rejected_patterns))
    missing = [k for k in REQUIRED_CONNECTION_KEYS if not cfg.get(k)]
    if missing:
        raise cfg.missing_config_error(missing, gitignore_updated=gitignore_updated)
    jira = jira_client(cfg)
    me = jira.get("/rest/api/2/myself") or {}
    gitlab = gitlab_client(cfg)
    gl_user = gitlab.get("/user") or {}
    project = resolve_gitlab_project(cfg, gitlab)
    level = gitlab_access_level(gitlab, project["id"], gl_user.get("id"))
    git_name, git_email = git_identity(root)
    result = {
        "env_path": cfg.env_path,
        "tmp_dir": mps_tmp_dir(root),
        "gitignore_updated": gitignore_updated,
        "jira_user": {"name": me.get("name"), "displayName": me.get("displayName"), "email": me.get("emailAddress")},
        "gitlab_user": {"username": gl_user.get("username"), "id": gl_user.get("id"), "name": gl_user.get("name"),
                        "email": gl_user.get("commit_email") or gl_user.get("email") or gl_user.get("public_email")},
        "git_identity": {"name": git_name or None, "email": git_email or None},
        "gitlab_project": project,
        "gitlab_access_level": level,
        "gitlab_access_level_name": access_level_name(level),
        "branches": cfg.branches(),
        "warnings": warnings,
        "action_required": [],
    }
    project_key = cfg.get(KEY_JIRA_PROJECT)
    if project_key:
        resp = jira.request("GET", "/rest/api/2/project/" + urllib.parse.quote(project_key), allow_statuses=(404,))
        if resp.status == 404:
            raise MpsError("jira_project_not_found", "Không tìm thấy project Jira '%s'. Hãy chọn lại mã project."
                           % project_key, available_projects=list_jira_projects(jira))
        result["jira_project"] = {"key": resp.data.get("key"), "name": resp.data.get("name")}
    else:
        result["jira_project"] = None
        result["jira_projects"] = list_jira_projects(jira)
        result["action_required"].append("ask_jira_project_key")
    return result


def cmd_env_set(args):
    key = args.key.strip()
    if key.endswith(SECRET_KEY_SUFFIX):
        raise MpsError("secret_key_refused", "Không ghi token qua lệnh này. Hãy tự mở file .env bằng trình soạn thảo "
                                             "để điền %s (không dán token vào chat)." % key)
    if key in MANUAL_ONLY_KEYS:
        raise MpsError("manual_edit_required", "%s chỉ do người dùng tự sửa trong file .env (nó ảnh hưởng việc chọn "
                                               "giai đoạn), không ghi qua lệnh này." % key, key=key)
    if key not in KNOWN_KEYS:
        raise MpsError("unknown_key", "Khoá cấu hình không hợp lệ: %s." % key,
                       allowed_keys=[k for k in KNOWN_KEYS
                                     if not k.endswith(SECRET_KEY_SUFFIX) and k not in MANUAL_ONLY_KEYS])
    value = args.value.strip()
    if "\n" in value or "\r" in value:
        raise MpsError("invalid_value", "Giá trị không được xuống dòng.")
    root = find_project_root()
    cfg = load_config(root)
    if not cfg.env_exists:
        raise MpsError("env_missing", "Chưa có file .env. Hãy chạy: env init", env_path=cfg.env_path)
    new_text = update_env_text(read_text_file(cfg.env_path), key, value)
    with open(cfg.env_path, "wb") as handle:
        handle.write(new_text.encode("utf-8"))
    return {"env_path": cfg.env_path, "key": key, "value": value}


# ---------------------------------------------------------------------------
# Commands: project (lead)
# ---------------------------------------------------------------------------

PROJECT_SETUP_FILES = (PROJECT_SETTINGS_PATH, ".gitignore", PROJECT_RULES_PATH)


def _read_project_settings_text(path):
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise MpsError("settings_invalid_json",
                       "File %s không phải JSON hợp lệ (không đọc được dạng UTF-8). Chưa sửa gì. Hãy nhờ developer sửa "
                       "file rồi chạy lại." % PROJECT_SETTINGS_PATH, line=None, column=None)


def cmd_project_setup(args):
    """Integrate the plugin into the project for every member: settings.json entries (auto-update on), .env ignored.

    Only the marketplace / enabledPlugins entries are added; every other key and its order are kept, and so are the
    file's line endings and indent. Nothing is written when the file is not valid JSON or already integrated.
    """
    root = find_project_root()
    path = project_settings_path(root)
    created = not os.path.isfile(path)
    text = "" if created else _read_project_settings_text(path)
    newline = "\r\n" if "\r\n" in text else "\n"
    merged, changes, warnings = merge_project_settings(parse_settings_text(text))
    if changes:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        rendered = render_settings_json(merged, newline, detect_json_indent(text))
        write_file_atomically(path, rendered.encode("utf-8"))
    gitignore_updated = ensure_env_gitignored(root)
    # A file git already tracks is committed whatever .gitignore says.
    tracked = run_git(["ls-files", "--error-unmatch", "--", PROJECT_SETTINGS_PATH], root, check=False).ok
    if not tracked and run_git(["check-ignore", "-q", "--no-index", PROJECT_SETTINGS_PATH], root,
                               check=False).code == 0:
        warnings.append({"code": "settings_ignored_by_git",
                         "message": "File %s đang bị .gitignore bỏ qua nên thành viên sẽ không nhận được. Cần bỏ dòng "
                                    "ignore tương ứng rồi commit file." % PROJECT_SETTINGS_PATH})
    review_rules, review_written, review_problems = _project_review_rules(root, args.review_rules, warnings)
    written = {PROJECT_SETTINGS_PATH: bool(changes), ".gitignore": gitignore_updated, PROJECT_RULES_PATH: review_written}
    pending = set(_changed_paths(git_status(root)))
    files_to_commit = [p for p in PROJECT_SETUP_FILES if written[p] or p in pending]
    result = {"settings_path": path, "created": created, "changed": bool(changes), "changes": changes,
              "gitignore_updated": gitignore_updated, "files_to_commit": files_to_commit, "warnings": warnings,
              "review_rules": review_rules, "review_rules_path": os.path.join(root, *PROJECT_RULES_PATH.split("/")),
              "review_rules_problems": review_problems,
              "next": "commit_with_mps_git_flow" if files_to_commit else None}
    # The settings now name the shared repo, so every other command is blocked on a machine that still installs
    # from the legacy repo: the lead has to switch before committing these files with mps-git-flow.
    status, names = legacy_plugin_source_status(load_known_marketplaces(os.environ), merged)
    if status == "machine":
        error = legacy_plugin_source_error(names)
        result["machine_source_legacy"] = {"marketplaces": names, "commands": error.extra["commands"],
                                           "message": error.message}
    return result


def _project_review_rules(root, scaffold, warnings):
    """State of the project's code review rules in the working tree: (status, written, problems).

    status: "present" (the file exists; `problems` lists format problems of the local copy, and a rule whose paths
    match no tracked file adds a project_rule_matches_nothing warning), "absent", or "created" (scaffold=True and
    there was no file: written from the template, which holds no active rule). An existing file is never
    overwritten.
    """
    path = os.path.join(root, *PROJECT_RULES_PATH.split("/"))
    if os.path.isfile(path):
        parsed = parse_rule_file(read_text_file(path), "project")
        if parsed["rules"]:
            tracked = [p for p in run_git(["ls-files", "-z"], root).stdout.split("\0") if p]
            own_ignore = [{"glob": glob, "roots": [""], "source": "project"} for glob in parsed["ignore"]]
            warnings.extend(rule_matches_nothing_warning(rule, "trong repo")
                            for rule in project_rules_matching_nothing(parsed["rules"], tracked, own_ignore))
        return "present", False, parsed["problems"]
    if not scaffold:
        return "absent", False, []
    try:
        template = _read_bytes_file(REVIEW_RULES_TEMPLATE_PATH)
    except (IOError, OSError):
        raise MpsError("template_missing", "Không tìm thấy file mẫu review.example.md của skill.",
                       template=REVIEW_RULES_TEMPLATE_PATH)
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "xb") as handle:
        handle.write(template)
    return "created", True, []


def _read_bytes_file(path):
    with open(path, "rb") as handle:
        return handle.read()


# ---------------------------------------------------------------------------
# Commands: jira
# ---------------------------------------------------------------------------


def cmd_jira_get(args):
    cfg = load_config(find_project_root())
    jira = jira_client(cfg)
    key = normalize_issue_key(args.key)
    issue = summarize_issue(fetch_issue(jira, key), cfg.get(KEY_JIRA_URL))
    issue_type = normalize_issue_type(issue["issue_type_name"])
    if issue_type is None:
        raise MpsError("unsupported_type", "Ticket %s là loại '%s'. Team chỉ dùng Story và Bug — hãy dùng ticket khác "
                                           "hoặc hỏi người quản lý dự án." % (key, issue["issue_type_name"]),
                       key=key, issue_type_name=issue["issue_type_name"], url=issue["url"])
    issue["issue_type"] = issue_type
    return issue


def cmd_jira_projects(args):
    cfg = load_config(find_project_root())
    return {"default_project": cfg.get(KEY_JIRA_PROJECT) or None, "projects": list_jira_projects(jira_client(cfg))}


def ensure_jira_project_exists(jira, project_key):
    resp = jira.request("GET", "/rest/api/2/project/" + urllib.parse.quote(project_key), allow_statuses=(404,))
    if resp.status == 404:
        raise MpsError("jira_project_not_found", "Không tìm thấy project Jira '%s' (hoặc bạn không có quyền xem). Hãy "
                                                 "chọn một project trong danh sách." % project_key,
                       project_key=project_key, available_projects=list_jira_projects(jira))
    return {"key": resp.data.get("key"), "name": resp.data.get("name")}


def resolve_create_project(cfg, override):
    """(project key, Jira client) for a NEW ticket; a one-off --project is checked to exist."""
    cfg.require(KEY_JIRA_PROJECT)
    project_key = choose_create_project(override, cfg.get(KEY_JIRA_PROJECT))
    jira = jira_client(cfg)
    if project_key != cfg.get(KEY_JIRA_PROJECT).upper():
        ensure_jira_project_exists(jira, project_key)
    return project_key, jira


def cmd_jira_create(args):
    cfg = load_config(find_project_root())
    summary = " ".join((args.summary or "").split())
    if not summary:
        raise MpsError("empty_summary", "Tiêu đề (summary) ticket đang trống.")
    if len(summary) > JIRA_SUMMARY_MAX_LEN:
        raise MpsError("summary_too_long", "Tiêu đề ticket dài quá %d ký tự." % JIRA_SUMMARY_MAX_LEN)
    description = read_text_arg(args.description, args.description_file, "mô tả")
    project_key, jira = resolve_create_project(cfg, args.project)
    me = jira.get("/rest/api/2/myself") or {}
    type_name = "Story" if args.type == "story" else "Bug"
    issue_type, fields_meta, meta_source = load_create_meta(jira, project_key, type_name)
    provided = parse_field_args(args.field, fields_meta)
    missing = find_missing_required_fields(fields_meta, provided)
    if missing:
        raise MpsError("missing_required_fields", "Jira yêu cầu thêm thông tin trước khi tạo ticket. Hãy hỏi người dùng "
                                                  "từng trường rồi chạy lại với --field \"<tên>=<giá trị>\".",
                       fields=missing)
    # Decided before the ticket exists, so a question for the user never leaves a half-made ticket behind.
    sprints = None if args.sprint == SPRINT_BACKLOG else find_active_sprints(jira, project_key)
    sprint, sprint_note = choose_sprint(args.type, args.sprint, sprints, project_key)
    notes = [sprint_note] if sprint_note else []
    fields = {"project": {"key": project_key}, "issuetype": {"id": str(issue_type.get("id"))},
              "summary": summary, "description": description}
    fields.update(provided)
    assignee_on_screen = "assignee" in fields_meta
    if assignee_on_screen:
        fields["assignee"] = {"name": me.get("name")}
    if "reporter" in fields_meta:
        fields["reporter"] = {"name": me.get("name")}
    resp = jira.request("POST", "/rest/api/2/issue", body={"fields": fields}, allow_statuses=(400,))
    errors = (resp.data or {}).get("errors") if isinstance(resp.data, dict) else None
    if resp.status == 400 and "reporter" in fields and isinstance(errors, dict) and "reporter" in errors:
        del fields["reporter"]
        notes.append("Không đặt được người báo cáo (reporter) do thiếu quyền; Jira mặc định là người tạo (chính bạn).")
        resp = jira.request("POST", "/rest/api/2/issue", body={"fields": fields}, allow_statuses=(400,))
    if resp.status == 400:
        raise MpsError("jira_create_failed", "Jira từ chối tạo ticket. Xem chi tiết lỗi để biết trường nào sai.",
                       details=extract_server_message(resp.data), field_errors=(resp.data or {}).get("errors"))
    key = resp.data.get("key")
    # From here on the ticket exists: nothing may raise, or the key is lost and a retry makes a duplicate.
    if not assignee_on_screen:
        try:
            assigned = jira.request("PUT", "/rest/api/2/issue/%s/assignee" % urllib.parse.quote(key),
                                    body={"name": me.get("name")},
                                    allow_statuses=(400, 401, 403, 404)).status in (200, 204)
        except MpsError:
            assigned = False
        if assigned:
            notes.append("Đã giao ticket cho bạn sau khi tạo.")
        else:
            notes.append("Ticket đã tạo nhưng chưa giao (assign) được cho bạn; hãy tự giao trên Jira.")
    sprint_failed = False
    if sprint is not None and not move_issue_to_sprint(jira, key, sprint):
        notes.append("Ticket %s đã tạo nhưng chưa đưa được vào sprint %s (Jira từ chối hoặc lỗi kết nối), nên đang "
                     "nằm ở backlog; hãy tự kéo vào sprint trên Jira, KHÔNG tạo lại ticket." % (key, sprint_label(sprint)))
        sprint, sprint_failed = None, True
    return {"key": key, "url": cfg.get(KEY_JIRA_URL).rstrip("/") + "/browse/" + key, "issue_type": args.type,
            "project": project_key, "summary": summary, "assignee": me.get("name"), "createmeta_source": meta_source,
            "sprint": sprint, "placement": "sprint" if sprint is not None else SPRINT_BACKLOG,
            "sprint_failed": sprint_failed, "notes": notes}


def cmd_jira_sprints(args):
    """Active sprints of the board a new ticket would go to, so the user can be asked before `jira create`."""
    project_key, jira = resolve_create_project(load_config(find_project_root()), args.project)
    sprints = find_active_sprints(jira, project_key)
    return {"project": project_key, "sprint_info_available": sprints is not None, "active_sprints": sprints or []}


def cmd_jira_transition(args):
    cfg = load_config(find_project_root())
    jira = jira_client(cfg)
    key = normalize_issue_key(args.key)
    issue = summarize_issue(fetch_issue(jira, key), cfg.get(KEY_JIRA_URL))
    if is_in_target_state(issue["status"], issue["status_category"], args.to):
        return {"key": key, "skipped": True, "status": issue["status"], "url": issue["url"]}
    path = "/rest/api/2/issue/%s/transitions" % urllib.parse.quote(key)
    transitions = (jira.get(path, params={"expand": "transitions.fields"}) or {}).get("transitions") or []
    chosen = pick_transition(transitions, args.to)
    if chosen is None:
        raise MpsError("no_transition", "Không tìm thấy bước chuyển trạng thái phù hợp (%s) cho %s. Hãy tự chuyển trạng "
                                        "thái trên Jira hoặc nhờ người quản lý." % (args.to, key),
                       key=key, current_status=issue["status"], url=issue["url"],
                       available_transitions=[t.get("name") for t in transitions])
    body = {"transition": {"id": str(chosen.get("id"))}}
    fields_meta = normalize_field_meta_map(chosen.get("fields"))
    if "resolution" in fields_meta:
        resolution = choose_resolution(fields_meta["resolution"]["allowed_values"])
        if resolution is not None:
            body["fields"] = {"resolution": {"name": resolution.get("name")} if resolution.get("name")
                              else {"id": resolution.get("id")}}
    resp = jira.request("POST", path, body=body, allow_statuses=(400,))
    if resp.status == 400:
        raise MpsError("transition_failed", "Jira không cho chuyển trạng thái %s (màn hình chuyển có thể cần thêm thông "
                                            "tin). Hãy tự chuyển trên Jira." % key,
                       key=key, url=issue["url"], details=extract_server_message(resp.data))
    after = summarize_issue(fetch_issue(jira, key), cfg.get(KEY_JIRA_URL))
    return {"key": key, "skipped": False, "transition": chosen.get("name"), "from_status": issue["status"],
            "status": after["status"], "resolution": (body.get("fields") or {}).get("resolution"), "url": issue["url"]}


def cmd_jira_comment(args):
    cfg = load_config(find_project_root())
    jira = jira_client(cfg)
    key = normalize_issue_key(args.key)
    body = read_text_arg(args.body, args.body_file, "nội dung comment").strip()
    if not body:
        raise MpsError("empty_comment", "Nội dung comment đang trống.")
    data = jira.request("POST", "/rest/api/2/issue/%s/comment" % urllib.parse.quote(key), body={"body": body}).data
    return {"key": key, "comment_id": (data or {}).get("id")}


# ---------------------------------------------------------------------------
# Commands: naming / flow
# ---------------------------------------------------------------------------


def cmd_naming_build(args):
    return build_names(args.key, args.type, args.title)


def branch_context(root, branches, key=None):
    branch = current_branch(root)
    recorded = recorded_base(root, branch)
    detached_at = None
    if branch is None and head_exists(root):
        output = run_git(["for-each-ref", "--points-at", "HEAD", "--format=%(refname:strip=3)", "refs/remotes/origin/"],
                         root).stdout
        detached_at = unique_protected_branch([line.strip() for line in output.splitlines()], branches)
    return detect_branch_context(branch, branches, recorded, key=key,
                                 recorded_base_exists=not recorded or ref_exists(root, "refs/remotes/origin/" + recorded),
                                 detached_at=detached_at)


def unity_project_roots(root, paths):
    """Folders ("" = repo root) holding a Unity project, i.e. containing ProjectSettings/ProjectVersion.txt.

    Tracked version files are found through git; untracked ones are checked on disk for the folders of `paths`.
    """
    roots = set()
    tracked = run_git(["ls-files", "-z", "--", ":(glob)**/" + UNITY_VERSION_FILE], root).stdout
    for path in tracked.split("\0"):
        if path.endswith(UNITY_VERSION_FILE):
            roots.add(path[:-len(UNITY_VERSION_FILE)].strip("/"))
    candidates = set([""])
    for path in paths:
        folders = path.split("/")[:-1]
        candidates.update("/".join(folders[:depth]) for depth in range(len(folders) + 1))
    for folder in candidates:
        if os.path.isfile(os.path.join(root, folder, *UNITY_VERSION_FILE.split("/"))):
            roots.add(folder)
    return sorted(roots)


PYTHON_PROJECT_MARKERS = ("pyproject.toml", "setup.py")
WEB_PROJECT_MARKERS = ("package.json",)


def _ancestor_folders(paths):
    """"" plus every folder above each path (the candidate stack roots)."""
    folders = set([""])
    for path in paths:
        parts = path.split("/")[:-1]
        folders.update("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))
    return folders


def _repo_folder(root, folder):
    return os.path.join(root, *folder.split("/")) if folder else root


def _folder_has_python_project(root, folder):
    directory = _repo_folder(root, folder)
    if any(os.path.isfile(os.path.join(directory, name)) for name in PYTHON_PROJECT_MARKERS):
        return True
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    return any(n.startswith("requirements") and n.endswith(".txt") and os.path.isfile(os.path.join(directory, n))
               for n in names)


def detect_profiles(root, paths):
    """Shipped rule profiles that apply to the changed `paths`: {name: [roots]} (only non-empty entries).

    unity-csharp: Unity project roots; python: folders with pyproject.toml, setup.py or requirements*.txt; web:
    folders with package.json - each looked up on disk in the repo root and every folder above a changed path.

    Reading the working tree (not origin/<base>) is deliberate and safe: profiles only add shipped major / minor
    rules and shipped ignore globs, and a project rule overrides those ignores (split_ignored). Project blockers
    always come from origin/<base>, so nothing on the user's disk can switch one off.
    """
    detected = {}
    unity = unity_project_roots(root, paths)
    if unity:
        detected["unity-csharp"] = unity
    folders = sorted(_ancestor_folders(paths))
    python = [f for f in folders if _folder_has_python_project(root, f)]
    if python:
        detected["python"] = python
    web = [f for f in folders if any(os.path.isfile(os.path.join(_repo_folder(root, f), name))
                                     for name in WEB_PROJECT_MARKERS)]
    if web:
        detected["web"] = web
    return detected


def work_in_progress(root, extra_patterns):
    """(dirty, generated_changes) for phase pinning only.

    Dirty = real uncommitted changes or commits on no origin branch. `.env` files and tool-generated files (the
    Unity defaults inside Unity project roots, plus the user's valid MPS_GENERATED_PATTERNS) do not count; the
    generated ones are returned so the agent can mention them. Committing is not affected: those files still go
    through the scope review.
    """
    changed = [p for p in _changed_paths(git_status(root)) if not is_env_file(p)]
    rules = generated_rules(unity_project_roots(root, changed), extra_patterns)
    generated = [p for p in changed if is_generated_path(p, rules)]
    real = [p for p in changed if p not in generated]
    return bool(real) or unpushed_commit_count(root) > 0, generated


def invalid_generated_warning(rejected):
    return {"code": "invalid_generated_pattern", "patterns": rejected,
            "message": "Bỏ qua mẫu MPS_GENERATED_PATTERNS không hợp lệ (phải bắt đầu bằng tên thư mục hoặc tên file cụ "
                       "thể, không được chỉ là ký tự đại diện): %s. Người dùng tự sửa trong file .env."
                       % ", ".join(rejected)}


def cmd_flow_plan(args):
    root = find_project_root()
    cfg = load_config(root)
    branches = cfg.branches()
    key = normalize_issue_key(args.key)
    # Pruned fetch first, so a release branch deleted on GitLab no longer counts as an existing base.
    fetched, _ = run_git_network(root, ["fetch", "--prune", "--no-recurse-submodules", "origin"], cfg)
    if not fetched.ok:
        raise_git_network_error(fetched, "fetch")
    context = branch_context(root, branches, key)
    extra_patterns, rejected_patterns = parse_generated_patterns(cfg.get(KEY_GENERATED_PATTERNS))
    dirty, generated = work_in_progress(root, extra_patterns)
    warnings = [invalid_generated_warning(rejected_patterns)] if rejected_patterns else []
    try:
        phase, phase_source, pinned = reconcile_phase(context, args.phase, dirty)
    except MpsError as exc:
        exc.extra.setdefault("generated_changes", generated)  # so the agent can still mention them
        exc.extra.setdefault("warnings", warnings)
        raise
    plan = plan_phase(phase, args.type, branches)
    if context["recorded_base_gone"]:
        warnings.append({"code": "recorded_base_gone", "recorded_base": context["recorded_base"],
                         "message": "Nhánh %s được tạo từ %s nhưng %s không còn trên GitLab; nhánh này sẽ không được "
                                    "dùng tiếp." % (context["current_branch"], context["recorded_base"],
                                                    context["recorded_base"])})
    if context["branch_ticket_key"] and context["branch_ticket_key"] != key:
        warnings.append({"code": "other_ticket_branch", "branch_ticket_key": context["branch_ticket_key"],
                         "message": "Bạn đang đứng trên nhánh của ticket khác (%s); công việc cho %s sẽ ở nhánh riêng."
                                    % (context["branch_ticket_key"], key)})
    if phase == "production":
        gitlab = gitlab_client(cfg)
        user = gitlab.get("/user") or {}
        project = resolve_gitlab_project(cfg, gitlab)
        plan = plan_phase(phase, args.type, branches,
                          access_level=gitlab_access_level(gitlab, project["id"], user.get("id")))
    elif phase == "beta":
        gitlab = gitlab_client(cfg)
        project = resolve_gitlab_project(cfg, gitlab)
        prefix = branches["beta_prefix"]
        raw = gitlab_get_all(gitlab, "/projects/%s/repository/branches" % project["id"], {"search": "^" + prefix})
        candidates = [{"name": b.get("name"), "committed_date": (b.get("commit") or {}).get("committed_date")}
                      for b in raw]
        names = [b["name"] for b in sort_release_branches(candidates, prefix)]
        if pinned:
            # Work started on a specific release branch: it goes back into THAT branch, even if not the newest.
            release = context["detected_base"]
            warning = check_release_branch(release, names)
            if warning:
                warnings.append(warning)
        elif names:
            release = names[0]
        else:
            raise MpsError("no_release_branch", "Không tìm thấy nhánh beta nào (%s*) trên GitLab. Có thể giai đoạn beta "
                                                "chưa bắt đầu — hãy hỏi developer." % prefix)
        plan["base_branch"] = release
        plan["target_branch"] = release
        plan["release_sort"] = release_sort_method(candidates, prefix)
        plan["release_branches"] = names[:RELEASE_BRANCHES_REPORTED]
    if pinned and phase != "beta":
        plan["base_branch"] = context["detected_base"]
        plan["target_branch"] = context["detected_base"]
    plan.pop("needs_release_lookup", None)
    plan.update(context)
    plan.update({"phase_source": phase_source, "pinned_by_current_branch": pinned, "work_in_progress": dirty,
                 "generated_changes": generated, "warnings": warnings})
    return plan


# ---------------------------------------------------------------------------
# Commands: git
# ---------------------------------------------------------------------------


def _changed_paths(status):
    seen = []
    for group in ("staged", "unstaged", "untracked", "unmerged"):
        for path in status[group]:
            if path not in seen:
                seen.append(path)
    return seen


def _diff_vs_head(root, options, pathspec=()):
    """Staged + unstaged changes of tracked files (works before the first commit too)."""
    base = ["diff", "--no-color", "--no-ext-diff"] + list(options)
    if head_exists(root):
        return run_git(base + ["HEAD"] + list(pathspec), root).stdout
    staged = run_git(base + ["--cached"] + list(pathspec), root).stdout
    return staged + run_git(base + list(pathspec), root).stdout


def _read_worktree_file(root, path, limit):
    """Return (text or None, size, kind) where kind is text|binary|too_large|missing."""
    full = os.path.join(root, path)
    if not os.path.isfile(full):
        return None, 0, "missing"
    size = os.path.getsize(full)
    if size > MAX_FILE_BYTES:
        return None, size, "too_large"
    with open(full, "rb") as handle:
        raw = handle.read(limit if limit else -1)
    if b"\0" in raw[:BINARY_SNIFF_BYTES]:
        return None, size, "binary"
    return raw.decode("utf-8", "replace"), size, "text"


def cmd_git_preflight(args):
    root = find_project_root()
    cfg = load_config(root)
    branches = cfg.branches()
    branch = current_branch(root)
    status = git_status(root)
    changed = _changed_paths(status)
    blockers = []
    warnings = []

    ops = operations_in_progress(root)
    if ops:
        blockers.append({"code": "operation_in_progress", "operations": ops,
                         "message": "Git đang dở một thao tác (%s). Cần developer giúp xử lý trước." % ", ".join(ops)})
    if status["unmerged"]:
        blockers.append({"code": "unmerged_files", "files": status["unmerged"],
                         "message": "Có file đang bị xung đột (conflict) chưa giải quyết. Cần developer giúp."})
    env_files = [p for p in changed if is_env_file(p)]
    if env_files:
        blockers.append({"code": "env_file", "files": env_files,
                         "message": "Có file .env (chứa token/bí mật) nằm trong thay đổi. Không được commit file này."})

    findings = scan_secrets(_diff_vs_head(root, ["-U0"]))
    if args.base and head_exists(root) and ref_exists(root, "refs/remotes/origin/" + args.base):
        committed_range = "origin/%s..HEAD" % args.base
        findings.extend(scan_secrets(_commit_patches(root, committed_range)))
        committed_env = [p for p in _commit_touched_files(root, committed_range) if is_env_file(p)]
        if committed_env:
            blockers.append({"code": "env_file_in_commits", "files": sorted(set(committed_env)),
                             "message": "Các commit chưa đẩy lên có chứa file .env (token/bí mật). Không được đẩy lên "
                                        "— cần developer gỡ file khỏi các commit đó."})
    large = []
    lfs_paths = lfs_tracked(root, changed)
    for path in changed:
        full = os.path.join(root, path)
        if path not in lfs_paths and os.path.isfile(full) and os.path.getsize(full) > MAX_FILE_BYTES:
            large.append({"file": path, "bytes": os.path.getsize(full)})
        if path in status["untracked"] and not is_env_file(path) and path not in lfs_paths:
            text, _, kind = _read_worktree_file(root, path, 0)
            if kind == "text":
                findings.extend(scan_text(path, text))
    hard = [f for f in findings if not f["confirmable"]]
    soft = [f for f in findings if f["confirmable"]]
    if hard:
        blockers.append({"code": "secret_detected", "findings": hard, "confirmable": False,
                         "message": "Phát hiện token/khoá bí mật trong code sắp đẩy lên. Phải gỡ ra trước khi commit."})
    if soft:
        blockers.append({"code": "possible_secret", "findings": soft, "confirmable": True,
                         "message": "Có dòng trông giống mật khẩu/token. Hãy kiểm tra từng chỗ; chỉ tiếp tục nếu người "
                                    "dùng xác nhận đó không phải bí mật thật."})
    if large:
        blockers.append({"code": "large_file", "files": large,
                         "message": "Có file lớn hơn 5MB. Không nên đưa file lớn lên git — hãy hỏi developer."})

    git_name, git_email = git_identity(root)
    if not git_name or not git_email:
        blockers.append({"code": "missing_git_identity", "name": git_name or None, "email": git_email or None,
                         "message": "Git chưa biết tên/email của bạn nên không thể tạo commit. Có thể đặt cho riêng "
                                    "project này (cần bạn đồng ý)."})

    unpushed = unpushed_commit_count(root)
    if unpushed and branch and is_protected_branch(branch, branches):
        blockers.append({"code": "commits_on_protected_branch", "count": unpushed,
                         "message": "Có %d commit tạo thẳng trên nhánh %s và không có trên GitLab. Không được đẩy "
                                    "thẳng vào nhánh này — cần developer giúp chuyển chúng sang nhánh riêng." % (
                                        unpushed, branch)})
    elif unpushed and branch != args.branch:
        warnings.append({"code": "local_commits_not_carried", "count": unpushed, "branch": branch,
                         "message": "Nhánh hiện tại (%s) có %d commit không nằm trên nhánh nào của GitLab (thường là "
                                    "commit chưa được đẩy lên). Nhánh mới của ticket sẽ được tạo từ code mới nhất trên "
                                    "GitLab nên KHÔNG mang theo các commit này. Hãy hỏi developer, hoặc xác nhận là bỏ "
                                    "chúng lại." % (branch or "HEAD", unpushed)})

    upstream = None
    ahead = behind = None
    upstream_res = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root, check=False)
    if upstream_res.ok:
        upstream = upstream_res.stdout.strip()
        counts = run_git(["rev-list", "--left-right", "--count", "@{u}...HEAD"], root).stdout.split()
        behind, ahead = int(counts[0]), int(counts[1])
        if behind:
            warnings.append({"code": "behind_upstream", "message": "Nhánh trên GitLab có %d commit mới mà máy bạn "
                                                                   "chưa có." % behind})
    if branch is None:
        warnings.append({"code": "detached_head", "message": "Đang không đứng trên nhánh nào (detached HEAD)."})
    if not changed:
        warnings.append({"code": "nothing_to_commit", "message": "Không có thay đổi nào chưa commit."})
    if args.base and not ref_exists(root, "refs/remotes/origin/" + args.base):
        warnings.append({"code": "base_not_fetched", "message": "Chưa có origin/%s trên máy; bước prepare-branch sẽ tải "
                                                                "về." % args.base})
    context = detect_branch_context(branch, branches, recorded_base(root, branch))
    return {"branch": branch, "current_branch_role": context["current_branch_role"],
            "recorded_base": context["recorded_base"], "detected_phase": context["detected_phase"],
            "upstream": upstream, "ahead": ahead, "behind": behind, "staged": status["staged"],
            "unstaged": status["unstaged"], "untracked": status["untracked"], "unmerged": status["unmerged"],
            "has_changes": bool(changed), "can_proceed": not blockers, "blockers": blockers, "warnings": warnings}


def _stash_top(root):
    result = run_git(["rev-parse", "-q", "--verify", "refs/stash"], root, check=False)
    return result.stdout.strip() if result.ok else None


def _switch_with_stash(root, switch_args):
    """stash -u, switch, stash pop. Never resolves conflicts, never resets. Returns True if a stash was used."""
    before = _stash_top(root)
    pushed = run_git(["stash", "push", "-u", "-m", STASH_MESSAGE], root, check=False)
    after = _stash_top(root)
    created = after is not None and after != before
    if not pushed.ok:
        if created:
            raise MpsError("stash_failed", "Cất tạm (stash) thay đổi không hoàn tất. Một phần thay đổi đang được giữ "
                                           "trong git stash (%s). Không tự sửa — hãy nhờ developer giúp." % STASH_MESSAGE,
                           stash_commit=after, stderr=pushed.stderr.strip())
        raise MpsError("stash_failed", "Không cất tạm (stash) được thay đổi; chưa có gì bị thay đổi. Hãy nhờ developer "
                                       "xem lỗi.", stderr=pushed.stderr.strip())
    switched = run_git(switch_args, root, check=False)
    if not switched.ok:
        if created:
            restored = run_git(["stash", "pop", "--index"], root, check=False)
            if not restored.ok:
                raise _stash_conflict(root, after, restored,
                                      "Không chuyển được sang nhánh mới, và việc lấy lại thay đổi từ stash cũng gặp lỗi.")
        raise MpsError("switch_failed", "Không chuyển được sang nhánh mới. Thay đổi của bạn vẫn còn nguyên.",
                       stderr=switched.stderr.strip())
    if created:
        popped = run_git(["stash", "pop"], root, check=False)
        if not popped.ok:
            raise _stash_conflict(root, after, popped, "Đã chuyển sang nhánh mới nhưng thay đổi của bạn bị xung đột với "
                                                       "code mới nhất nên chưa áp lại được hết.")
    return created


def _stash_conflict(root, stash_commit, result, reason):
    return MpsError("stash_conflict",
                    reason + " Thay đổi vẫn được giữ an toàn trong git stash (%s). Không tự sửa — hãy nhờ developer "
                             "giúp." % STASH_MESSAGE,
                    stash_commit=stash_commit, stderr=result.stderr.strip(),
                    conflicted_files=git_status(root)["unmerged"])


def _switch_carrying_changes(root, switch_args):
    result = run_git(switch_args, root, check=False)
    if result.ok:
        return False
    text = result.stderr.lower()
    if "would be overwritten" in text or "commit your changes or stash them" in text:
        return _switch_with_stash(root, switch_args)
    raise MpsError("switch_failed", "Không chuyển được nhánh.", stderr=result.stderr.strip())


def cmd_git_prepare_branch(args):
    root = find_project_root()
    cfg = load_config(root)
    key = normalize_issue_key(args.key)
    validate_branch_name(root, args.branch)
    validate_branch_name(root, args.base)
    ensure_valid_base(args.base, cfg.branches())
    ensure_no_operation_in_progress(root)
    ensure_no_unmerged(root)
    # --prune only removes remote-tracking refs of branches deleted on GitLab (e.g. a finished release/*).
    fetched, used_token = run_git_network(root, ["fetch", "--prune", "--no-recurse-submodules", "origin"], cfg)
    if not fetched.ok:
        raise_git_network_error(fetched, "fetch")
    if not ref_exists(root, "refs/remotes/origin/" + args.base):
        raise MpsError("base_not_found", "Không tìm thấy nhánh gốc origin/%s trên GitLab." % args.base, base=args.base)
    result = {"branch": args.branch, "base": args.base, "used_token_fallback": used_token, "stash_used": False}
    # A ticket branch remembers the branch it was made from and must go back into exactly that branch.
    recorded = ensure_recorded_base_matches(root, args.branch, args.base)
    result["base_recorded"] = False
    # Existing branches are verified against the base BEFORE switching: a dev-based bugfix branch must never be
    # reused for a release (beta) MR, or unreleased develop commits would ride along.
    if current_branch(root) == args.branch:
        ensure_branch_matches_base(root, args.base, "HEAD", args.branch, key)
        result["action"] = "already_on_branch"
    elif ref_exists(root, "refs/heads/" + args.branch):
        ensure_branch_matches_base(root, args.base, "refs/heads/" + args.branch, args.branch, key)
        result["stash_used"] = _switch_carrying_changes(root, ["switch", args.branch])
        result["action"] = "switched_existing"
    elif ref_exists(root, "refs/remotes/origin/" + args.branch):
        ensure_branch_matches_base(root, args.base, "refs/remotes/origin/" + args.branch, args.branch, key)
        result["stash_used"] = _switch_carrying_changes(
            root, ["switch", "-c", args.branch, "--track", "origin/" + args.branch])
        result["action"] = "created_tracking"
    else:
        recorded = None
        result.update(_create_from_base(root, args))
    if not recorded:
        record_base(root, args.branch, args.base)
        result["base_recorded"] = True
    return result


def _create_from_base(root, args):
    left_behind = unpushed_commit_count(root)
    if left_behind and not args.leave_commits:
        raise MpsError("local_commits_not_carried",
                       "Nhánh hiện tại có %d commit không nằm trên nhánh nào của GitLab (thường là commit chưa được "
                       "đẩy lên). Nhánh mới sẽ được tạo từ origin/%s nên "
                       "KHÔNG mang theo các commit này (chúng vẫn nằm nguyên ở nhánh cũ). Hãy hỏi developer; chỉ "
                       "chạy lại với --leave-commits khi người dùng xác nhận bỏ chúng lại." % (left_behind, args.base),
                       count=left_behind, current_branch=current_branch(root))
    switch_args = ["switch", "--no-track", "-c", args.branch, "origin/" + args.base]
    stash_used = False
    if _changed_paths(git_status(root)):
        try:
            stash_used = _switch_with_stash(root, switch_args)
        except MpsError as exc:
            if exc.code == "stash_conflict" and current_branch(root) == args.branch:
                record_base(root, args.branch, args.base)  # the branch exists; remember where it came from
            raise
    else:
        run_git(switch_args, root)
    return {"action": "created_from_base", "stash_used": stash_used, "commits_left_behind": left_behind}


_REVIEW_EXCLUDES = ["--", ".", ":(exclude,glob)**/.env", ":(exclude,glob)**/.env.*"]


def code_review_path(root):
    return os.path.join(mps_tmp_dir(root), CODE_REVIEW_FILENAME)


def committed_review_path(root):
    return os.path.join(mps_tmp_dir(root), COMMITTED_REVIEW_FILENAME)


def _write_json(path, data):
    write_file_atomically(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def _remove_if_exists(path):
    if os.path.isfile(path):
        os.remove(path)


def _read_shipped_rule_file(relative):
    path = os.path.join(REVIEW_RULES_DIR, *relative.split("/"))
    try:
        return read_text_file(path)
    except (IOError, OSError):
        raise MpsError("internal_error", "Thiếu file quy tắc đi kèm plugin (%s). Hãy báo người bảo trì plugin."
                       % relative, file=relative)


def _load_shipped_rules():
    """(base.md text, {profile name: text}) shipped with the plugin."""
    profiles = dict((name, _read_shipped_rule_file("profiles/%s.md" % name)) for name in SHIPPED_PROFILES)
    return _read_shipped_rule_file("base.md"), profiles


def _read_project_rules(root, base):
    """Text of .mps/review.md on origin/<base> (never the working-tree copy), or None when the file is absent."""
    spec = "origin/%s:%s" % (base, PROJECT_RULES_PATH)
    kind = run_git(["cat-file", "-t", spec], root, check=False)
    if not kind.ok or kind.stdout.strip() != "blob":
        return None
    return run_git(["cat-file", "blob", spec], root).stdout


def _net_diff(root, base_ref):
    """(merge base or None, diff text): merge-base(origin/<base>, HEAD) -> working tree (staged and unstaged) for every
    tracked path, i.e. the net change of the merge request. Without a HEAD the empty tree is the left side."""
    merge_base = None
    if head_exists(root):
        merge_base = run_git(["merge-base", base_ref, "HEAD"], root).stdout.strip() or None
    left = merge_base or run_git(["hash-object", "-t", "tree", "--stdin"], root, input_bytes=b"").stdout.strip()
    # Explicit options so user config (diff.noprefix, diff.renames, textconv, color) cannot change the format.
    diff = run_git(["diff", "--no-color", "--no-ext-diff", "--no-textconv", "--find-renames", "--src-prefix=a/",
                    "--dst-prefix=b/", "-U3", left] + _REVIEW_EXCLUDES, root).stdout
    return merge_base, diff


def _untracked_file_diffs(root, untracked_paths):
    """FileDiffs for untracked files (sorted by path); .env files and vanished files are skipped."""
    files = []
    for path in sorted(untracked_paths):
        if is_env_file(path):
            continue
        text, size, kind = _read_worktree_file(root, path, UNTRACKED_FILE_CAP_CHARS * MAX_UTF8_BYTES_PER_CHAR)
        if kind == "missing":
            continue
        cut = False
        if kind == "text" and (len(text) > UNTRACKED_FILE_CAP_CHARS
                               or size > UNTRACKED_FILE_CAP_CHARS * MAX_UTF8_BYTES_PER_CHAR):
            cut = True
            text = text[:UNTRACKED_FILE_CAP_CHARS]
            text = text[:text.rfind("\n") + 1]  # whole lines only
        files.append(untracked_file_diff(path, text, kind, cut))
    return files


def _code_review_warnings(base, effective, project_rules, dropped_ids, truncated_paths, unmatched_rules):
    warnings = []
    if project_rules["status"] == "invalid":
        warnings.append({"code": "project_rules_invalid", "problems": project_rules["problems"],
                         "message": "File quy tắc review của dự án (%s trên nhánh %s) bị lỗi định dạng nên KHÔNG được áp "
                                    "dụng; chỉ dùng quy tắc chung của team. Hãy báo developer sửa file."
                                    % (PROJECT_RULES_PATH, base)})
    if project_rules["pending_change"]:
        warnings.append({"code": "project_rules_pending",
                         "message": "Thay đổi này có sửa file quy tắc review %s. Quy tắc mới chỉ có hiệu lực sau khi được "
                                    "merge vào %s; lần review này vẫn dùng bản trên %s." % (PROJECT_RULES_PATH, base, base)})
    if project_rules["unknown_keys"]:
        warnings.append({"code": "project_rules_unknown_key", "keys": project_rules["unknown_keys"],
                         "message": "Phần đầu file %s có khoá không được hỗ trợ: %s. Các khoá này bị bỏ qua (phiên bản này "
                                    "chưa hỗ trợ disable)." % (PROJECT_RULES_PATH, ", ".join(project_rules["unknown_keys"]))})
    if effective["unknown_profiles"]:
        warnings.append({"code": "unknown_profile", "profiles": effective["unknown_profiles"],
                         "available": list(SHIPPED_PROFILES),
                         "message": "File %s khai báo bộ quy tắc không có sẵn trong extends: %s. Bỏ qua; các bộ có sẵn: %s."
                                    % (PROJECT_RULES_PATH, ", ".join(effective["unknown_profiles"]),
                                       ", ".join(SHIPPED_PROFILES))})
    warnings.extend(rule_matches_nothing_warning(rule, "trên nhánh %s" % base) for rule in unmatched_rules)
    if effective["downgraded"]:
        warnings.append({"code": "shipped_blocker_downgraded", "rules": effective["downgraded"],
                         "message": "Quy tắc đi kèm plugin không được phép chặn commit; đã hạ %s xuống mức major."
                                    % _short_list(effective["downgraded"], WARNING_ITEMS_SHOWN)})
    if dropped_ids:
        warnings.append({"code": "rules_truncated", "rules": dropped_ids,
                         "message": "Có quá nhiều quy tắc nên %d quy tắc mức thấp không được gửi cho reviewer lần này: %s."
                                    % (len(dropped_ids), _short_list(dropped_ids, WARNING_ITEMS_SHOWN))})
    if truncated_paths:
        warnings.append({"code": "code_bundle_truncated", "files": truncated_paths,
                         "message": "Thay đổi quá lớn nên reviewer code chỉ xem được một phần; các file chưa được xem hết: "
                                    "%s. Kết quả review code sẽ ghi rõ là chưa đầy đủ."
                                    % _short_list(truncated_paths, WARNING_ITEMS_SHOWN)})
    return warnings


def _build_code_review(root, base, to_classify, already_committed, untracked_paths):
    """(code bundle text without its header, meta = bundle.json "code_review") for `diff-for-review --to-file`."""
    merge_base, diff_text = _net_diff(root, "origin/" + base)
    files = parse_diff_files(diff_text) + _untracked_file_diffs(root, untracked_paths)
    changed = [entry["path"] for entry in files]
    base_text, profile_texts = _load_shipped_rules()
    effective = build_effective_rules(base_text, profile_texts, _read_project_rules(root, base),
                                      detect_profiles(root, changed))
    reviewed, ignored = split_ignored(changed, effective["ignore"], effective["rules"])
    kept, dropped_ids = filter_rules(effective["rules"], reviewed, RULES_CAP_CHARS)
    reviewed_set = set(reviewed)
    rendered = render_numbered_diff([entry for entry in files if entry["path"] in reviewed_set], REVIEW_CAP_CHARS)
    project_rules = dict(effective["project_rules"])
    project_rules.update({"pending_change": PROJECT_RULES_PATH in list(to_classify) + list(already_committed),
                          "source": "origin/%s:%s" % (base, PROJECT_RULES_PATH)})
    unmatched = []
    if any(rule["layer"] == "project" for rule in effective["rules"]):
        base_files = [p for p in run_git(["ls-tree", "-r", "-z", "--name-only", "origin/" + base], root).stdout
                      .split("\0") if p]
        # Plus the changed paths: a rule for a folder that this change creates is not a mistake.
        unmatched = project_rules_matching_nothing(effective["rules"], changed + base_files, effective["ignore"])
    meta = {
        "version": CODE_REVIEW_VERSION,
        "merge_base": merge_base,
        "reviewed_paths": reviewed,
        "ignored_paths": ignored,
        "ranges": rendered["ranges"],
        "file_kinds": rendered["file_kinds"],
        "truncated_paths": rendered["truncated_paths"],
        "truncated": bool(rendered["truncated_paths"]),
        "rules": [dict((key, rule[key]) for key in ("id", "severity", "layer", "title", "paths", "roots"))
                  for rule in kept],
        "rules_dropped": dropped_ids,
        "profiles": effective["profiles"],
        "project_rules": project_rules,
        "auto": "nothing_to_review" if not reviewed or not kept else None,
        "warnings": _code_review_warnings(base, effective, project_rules, dropped_ids, rendered["truncated_paths"],
                                          unmatched),
    }
    return (render_rules_section(kept), rendered["text"]), meta


def _render_code_review_bundle(base, bundle_id, sections, meta):
    rules_text, diff_text = sections
    truncated = meta["truncated"]
    parts = ["# Code bundle for rule-based code review", "",
             "Bundle-ID: %s" % bundle_id, "(copy it into your reply as the line `BUNDLE: %s`)" % bundle_id, "",
             "Base: origin/%s, changes since the merge base %s. Truncated: %s." % (
                 base, (meta["merge_base"] or "(no commit yet)")[:12],
                 "YES (review what is shown and say so in your notes)" if truncated else "no")]
    if truncated:
        parts.append("Not fully shown: %s." % ", ".join(meta["truncated_paths"]))
    parts.extend(["", "## A. Rules (review ONLY against these rules)", "", rules_text.rstrip("\n"), "",
                  "## B. Files to review", ""])
    kinds = meta["file_kinds"]
    parts.extend(["- %s%s" % (path, "  [not shown - bundle size limit]" if kinds.get(path) == "not_shown" else "")
                  for path in meta["reviewed_paths"]] or ["(none)"])
    parts.extend(["", "Ignored files (never review or mention them):", ""])
    parts.extend(["- " + path for path in meta["ignored_paths"]] or ["(none)"])
    parts.extend(["", "## C. Changes with line numbers",
                  "(the number is the line in the NEW file; `+` added, `-` removed (no number), ` ` unchanged context)",
                  "", diff_text.rstrip("\n") or "(none)"])
    return "\n".join(parts) + "\n"


def _pending_review_record(bundle, already_committed, verification):
    """code_review.json: the verified code review, bound to the bundle's snapshot (base, branch, HEAD, blobs)."""
    code_review = bundle["code_review"]
    return {
        "version": CODE_REVIEW_VERSION, "base": bundle["base"], "branch": bundle["branch"], "head": bundle["head"],
        "bundle_id": bundle["bundle_id"], "blobs": bundle["blobs"],
        "complete": verification["complete"], "auto": code_review.get("auto"),
        "findings": verification["findings"], "blockers": verification["blockers"],
        "dropped_count": verification["dropped_count"], "already_committed": list(already_committed),
        "rules_applied": [rule["id"] for rule in code_review["rules"]], "profiles": code_review["profiles"],
        "project_rules": code_review["project_rules"], "truncated": code_review["truncated"],
        "truncated_paths": code_review["truncated_paths"], "warnings": code_review["warnings"],
    }


_EMPTY_VERIFICATION = {"complete": True, "findings": [], "blockers": [], "dropped_count": 0}


def _write_code_review_bundle(root, base, snapshot, sections, already_committed):
    """Write <git_dir>/mps-code-review.md, drop any pending code review (it belonged to an older bundle) and, when
    there is nothing to review against the rules, record the empty review here (no reviewer needed). Returns the
    output fields of diff-for-review."""
    meta = snapshot["code_review"]
    path = os.path.join(git_dir(root), CODE_REVIEW_BUNDLE_FILENAME)
    with open(path, "wb") as handle:
        handle.write(_render_code_review_bundle(base, snapshot["bundle_id"], sections, meta).encode("utf-8"))
    pending = code_review_path(root)
    _remove_if_exists(pending)
    if meta["auto"]:
        _write_json(pending, _pending_review_record(snapshot, already_committed, _EMPTY_VERIFICATION))
    applied = [rule["id"] for rule in meta["rules"]]
    return {
        "code_bundle_path": path,
        "code_bundle_truncated": meta["truncated"],
        "code_review_needed": not meta["auto"],
        "reviewed_files": meta["reviewed_paths"],
        "ignored_files": meta["ignored_paths"],
        "rules": {"applied": applied,
                  "blocker_rule_count": len([r for r in meta["rules"] if r["severity"] == "blocker"]),
                  "dropped": meta["rules_dropped"], "profiles": meta["profiles"],
                  "project_rules": meta["project_rules"]},
        "warnings": meta["warnings"],
    }


def cmd_git_diff_for_review(args):
    root = find_project_root()
    # The project's blocker rules are read from origin/<base>: a wrong base could read them from a branch without them.
    ensure_recorded_base_matches(root, current_branch(root), args.base)
    base_ref = "origin/" + args.base
    if not ref_exists(root, "refs/remotes/" + base_ref):
        raise MpsError("base_not_found", "Chưa có %s trên máy. Hãy chạy git prepare-branch trước." % base_ref)
    committed = ""
    if head_exists(root):
        committed = run_git(["diff", "--no-color", "--no-ext-diff", base_ref + "...HEAD"] + _REVIEW_EXCLUDES,
                            root).stdout
    working = _diff_vs_head(root, [], _REVIEW_EXCLUDES)
    untracked_paths = [p for p in run_git(["ls-files", "--others", "--exclude-standard", "-z"], root).stdout.split("\0")
                       if p]
    untracked_texts = []
    for path in untracked_paths:
        if is_env_file(path):
            untracked_texts.append("[nội dung bị ẩn: file .env chứa bí mật]")
            continue
        text, size, kind = _read_worktree_file(root, path, UNTRACKED_FILE_CAP_CHARS * MAX_UTF8_BYTES_PER_CHAR)
        if kind == "text":
            untracked_texts.append(text[:UNTRACKED_FILE_CAP_CHARS] +
                                   ("\n[... cắt bớt ...]" if len(text) > UNTRACKED_FILE_CAP_CHARS else ""))
        else:
            untracked_texts.append("[%s file, %d bytes]" % (kind, size))
    budgeted = apply_budget([committed, working] + untracked_texts, REVIEW_CAP_CHARS)
    truncated = any(flag for _, flag in budgeted)
    untracked = [{"path": path, "content": budgeted[2 + i][0], "truncated": budgeted[2 + i][1]}
                 for i, path in enumerate(untracked_paths)]
    hidden = _hidden_env_paths(root, base_ref, untracked_paths)
    to_classify, already_committed = review_candidates(root, base_ref)
    # Snapshot of exactly what the reviewer is shown; `review classify` refuses replies for any other state.
    snapshot = {"bundle_id": uuid.uuid4().hex, "base": args.base, "branch": current_branch(root),
                "head": head_sha(root), "blobs": file_blobs(root, to_classify)}
    code_sections = None
    if args.to_file:
        # The code reviewer gets the same snapshot: rules, numbered net diff and ranges are stored in bundle.json.
        code_sections, snapshot["code_review"] = _build_code_review(root, args.base, to_classify, already_committed,
                                                                    untracked_paths)
    with open(bundle_meta_path(root), "wb") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8"))
    result = {
        "base": args.base,
        "bundle_id": snapshot["bundle_id"],
        "files_to_classify": to_classify,
        "already_committed_files": already_committed,
        "committed_files": _name_status(root, [base_ref + "...HEAD"]) if head_exists(root) else [],
        "working_files": _name_status(root, ["HEAD"]) if head_exists(root) else [],
        "untracked_files_list": untracked_paths,
        "hidden_files": hidden,
        "truncated": truncated,
        "cap_chars": REVIEW_CAP_CHARS,
    }
    if args.to_file:
        path = os.path.join(git_dir(root), REVIEW_BUNDLE_FILENAME)
        bundle = _render_review_bundle(args.base, budgeted[0][0], budgeted[1][0], untracked, hidden, truncated,
                                       to_classify + already_committed, snapshot["bundle_id"])
        with open(path, "wb") as handle:
            handle.write(bundle.encode("utf-8"))
        result["bundle_path"] = path
        result.update(_write_code_review_bundle(root, args.base, snapshot, code_sections, already_committed))
    else:
        result["committed_diff"] = budgeted[0][0]
        result["working_diff"] = budgeted[1][0]
        result["untracked_files"] = untracked
    return result


def _name_status(root, revs):
    output = run_git(["diff", "--name-status"] + revs + _REVIEW_EXCLUDES, root).stdout
    return [line for line in output.splitlines() if line.strip()]


def _commit_touched_files(root, log_range):
    """Files added or modified by any non-merge commit in the range (deletions excluded)."""
    output = run_git(["log", "--no-merges", "--no-renames", "--format=", "--name-only", "-z", "--diff-filter=d",
                      log_range], root).stdout
    return [p.strip("\n") for p in output.split("\0") if p.strip("\n")]


def _commit_patches(root, log_range):
    """Concatenated per-commit patches of the range (scan_secrets reads them like one long diff)."""
    return run_git(["log", "--no-merges", "--no-renames", "--format=", "-p", "-U0", "--no-color", "--no-ext-diff",
                    log_range], root).stdout


def _name_only_z(root, args):
    return [p for p in run_git(["diff", "--name-only", "-z", "--no-renames"] + args, root).stdout.split("\0") if p]


def _hidden_env_paths(root, base_ref, untracked_paths):
    """.env* paths that changed but whose content is withheld from the reviewer."""
    paths = list(untracked_paths)
    if head_exists(root):
        paths += _name_only_z(root, [base_ref + "...HEAD"]) + _name_only_z(root, ["HEAD"])
    else:
        paths += _name_only_z(root, ["--cached"]) + _name_only_z(root, [])
    return sorted(set(p for p in paths if is_env_file(p)))


def _render_review_bundle(base, committed, working, untracked, hidden, truncated, files_to_classify, bundle_id):
    parts = ["# Change bundle for scope review", "",
             "Bundle-ID: %s" % bundle_id, "(copy it into your reply as the line `BUNDLE: %s`)" % bundle_id, "",
             "Base: origin/%s. Truncated: %s." % (base, "YES (review what is shown, say so in the verdict)"
                                                   if truncated else "no"), "",
             "## 0. Files to classify (each must appear exactly once in your FILES: block)", ""]
    parts.extend(["- " + path for path in files_to_classify] or ["(none)"])
    parts.extend(["",
                  "## 1. Commits on this branch not yet in origin/%s" % base, "", "```diff", committed or "(none)",
                  "```", "",
                  "## 2. Uncommitted changes (staged + unstaged)", "", "```diff", working or "(none)", "```", "",
                  "## 3. New untracked files", ""])
    shown =[item for item in untracked if not is_env_file(item["path"])]
    if not shown:
        parts.append("(none)")
    for item in shown:
        parts.extend(["### " + item["path"] + (" (truncated)" if item["truncated"] else ""), "", "```",
                      item["content"], "```", ""])
    parts.extend(["", "## 4. Secret files (changed, content hidden)", ""])
    parts.extend(["- %s: [content hidden]" % path for path in hidden] or ["(none)"])
    return "\n".join(parts) + "\n"


def _ensure_no_hard_secrets(diff_text, where):
    findings = [f for f in scan_secrets(diff_text) if not f["confirmable"]]
    if findings:
        raise MpsError("secret_detected", "Phát hiện token/khoá bí mật trong %s. Phải gỡ ra trước khi tiếp tục." % where,
                       findings=findings)


def cmd_git_commit(args):
    root = find_project_root()
    cfg = load_config(root)
    branch = current_branch(root)
    if branch is None:
        raise MpsError("detached_head", "Đang không đứng trên nhánh nào; hãy chạy git prepare-branch trước.")
    if is_protected_branch(branch, cfg.branches()):
        raise MpsError("protected_branch", "Không commit thẳng lên nhánh %s. Hãy chạy git prepare-branch để sang "
                                           "nhánh riêng của ticket." % branch, branch=branch)
    ensure_no_operation_in_progress(root)
    status = git_status(root)
    if status["unmerged"]:
        raise_unmerged(status["unmerged"])
    # Enforced here, whatever the agent was told: no AI attribution / co-author trailers in team commits.
    message, attribution_removed = strip_ai_attribution(args.message)
    if not message.strip():
        raise MpsError("empty_message", "Nội dung commit đang trống.")
    requested = [normalize_target_path(f) for f in args.files]
    included = [normalize_target_path(f) for f in args.include_out_of_scope or []]
    stray = [p for p in included if p not in requested]
    if stray:
        raise MpsError("invalid_include", "--include-out-of-scope chỉ dùng cho file cũng có trong --files: %s."
                       % ", ".join(stray), files=stray)
    named_env = [p for p in requested if is_env_file(p)]
    if named_env:
        raise MpsError("env_file", "Không được commit file .env (chứa token/bí mật).", files=named_env)
    changed = _changed_paths(status)
    if not changed:
        raise MpsError("nothing_to_commit", "Không có thay đổi nào để commit.")
    sources = set(status["renames"].values())
    exact = set(changed) | set(status["renames"]) | sources
    # Resuming after a successful commit (other, excluded files still changed): files already committed on this
    # ticket branch and untouched since are "nothing to commit", not a wrong path.
    already = _already_committed(root, branch, [p for p in requested if p not in exact])
    if already and len(already) == len(requested):
        raise MpsError("nothing_to_commit", "Các file này đã được commit trên nhánh %s rồi, không có thay đổi mới."
                       % branch, already_committed=already)
    # Only exact changed paths are accepted: a folder (even a deleted one), '.' or a typo would sweep in or miss
    # changes (Unity-regenerated .meta/ProjectSettings, lock files, someone else's edits).
    inexact = [p for p in requested if p not in exact]
    if inexact:
        raise MpsError("explicit_files_required", "Chỉ commit đúng từng file đang thay đổi (như danh sách của git "
                                                  "preflight), không dùng thư mục hay đường dẫn khác: %s."
                       % ", ".join(inexact),
                       files=inexact, changed_files_inside=[p for p in changed if path_in_targets(p, inexact)])
    # Rename sources no longer exist in the work tree or index, so `git add` would reject them; their deletion is
    # already staged and only needs to survive the scope filter below.
    targets = expand_rename_sources(requested, status["renames"])
    # The commit may only contain what the scope review approved (or what the user named explicitly), unchanged.
    reviewed = [p for p in targets if p not in sources]
    scope = load_scope(root, branch)
    # Both reviews must have been made against the branch's recorded base (where the project rules are read from).
    ensure_recorded_base_matches(root, branch, scope.get("base"))
    check_against_scope(scope, reviewed, file_blobs(root, reviewed), included)
    # ... and needs a complete code review of the same bundle, without a project blocker in any committed file.
    # Checked before `git add`, so a refusal never touches the index.
    code_review = load_code_review(root, branch, scope)
    blocked = blockers_for_commit(code_review, targets)
    if blocked:
        raise MpsError("code_review_blocked", "Thay đổi vi phạm quy tắc bắt buộc của dự án. Chưa commit gì. Hãy sửa theo "
                                              "quy tắc hoặc nhờ developer review.",
                       blockers=[dict((key, f[key]) for key in ("rule", "title", "path", "line", "problem",
                                                                "suggestion")) for f in blocked])
    to_add = [p for p in requested if p not in sources]
    staged_before = set(staged_paths(root))
    if to_add:
        added = run_git(["add", "-A", "--"] + to_add, root, check=False, literal_pathspecs=True)
        if not added.ok:
            raise MpsError("add_failed", "Không đưa được file vào commit (đường dẫn sai hoặc file bị git bỏ qua). "
                                         "Đường dẫn phải tính từ thư mục gốc project.", stderr=added.stderr.strip())
    # Inspect what is REALLY staged: files the user (or an IDE) staged earlier may lie outside the agreed list or
    # be .env files. Only the index is changed here, never the working tree.
    staged = staged_paths(root)
    newly_staged = [p for p in staged if p not in staged_before]
    staged_env = [p for p in staged if is_env_file(p)]
    if staged_env:
        unstage(root, sorted(set(staged_env + newly_staged)))
        raise MpsError("env_file", "Không được commit file .env (chứa token/bí mật). Chưa commit gì; file trên máy vẫn "
                                   "giữ nguyên.", files=staged_env)
    outside = [p for p in staged if not path_in_targets(p, targets)]
    unstage(root, outside)
    try:
        _ensure_no_hard_secrets(run_git(["diff", "--cached", "--no-color", "--no-ext-diff", "-U0"], root).stdout,
                                "các file sắp commit")
    except MpsError:
        unstage(root, [p for p in newly_staged if p not in outside])
        raise
    if not staged_paths(root):
        raise MpsError("nothing_to_commit", "Không có thay đổi nào để commit.")
    commit = run_git(["commit", "-m", message], root, check=False)
    if not commit.ok:
        text = (commit.stdout + commit.stderr).lower()
        if "nothing to commit" in text or "no changes added" in text:
            raise MpsError("nothing_to_commit", "Không có thay đổi nào để commit.")
        raise MpsError("commit_failed", "Commit thất bại.", stderr=commit.stderr.strip() or commit.stdout.strip())
    sha = run_git(["rev-parse", "HEAD"], root).stdout.strip()
    os.remove(scope_path(root))  # one review approves one commit
    committed_review, recorded = _record_committed_review(root, code_review, sha, targets)
    files = [line for line in run_git(["show", "--name-status", "--format=", "HEAD"], root).stdout.splitlines()
             if line.strip()]
    return {"branch": branch, "commit": sha, "message": message, "attribution_removed": attribution_removed,
            "files": files, "unstaged_other_files": outside, "left_uncommitted": _changed_paths(git_status(root)),
            "code_review_warning_count": len(code_review_warning_items(committed_review)),
            "code_review_recorded": recorded}


def load_code_review(root, branch, scope):
    """The pending code review: it must exist, belong to the same branch, HEAD and bundle as the scope review, and be
    complete. A truncated bundle or invalid project rules never block here (they only change what it found)."""
    review = _read_json(code_review_path(root))
    message = ("Chưa có kết quả review code (theo quy tắc của team và dự án) cho đúng lần review hiện tại. Hãy chạy lại "
               "bước 6 (cả review phạm vi và review code) trước khi commit.")
    if review is None:
        raise MpsError("code_review_required", message, reason="missing")
    if review.get("branch") != branch or review.get("head") != head_sha(root):
        raise MpsError("code_review_required", message, reason="branch_or_commit_changed")
    if review.get("bundle_id") != scope.get("bundle_id"):
        raise MpsError("code_review_required", message, reason="other_bundle")
    if not review.get("complete"):
        raise MpsError("code_review_incomplete", "Kết quả review code chưa đầy đủ (có dòng sai định dạng, hoặc một vi phạm "
                                                 "quy tắc bắt buộc không khớp với thay đổi). Hãy yêu cầu reviewer sửa "
                                                 "câu trả lời cho cùng bundle rồi chạy lại review findings.",
                       dropped_count=review.get("dropped_count"))
    return review


def _record_committed_review(root, review, sha, targets):
    """Move the pending review to committed_review.json (kept for mr ensure, even when step 6 runs again before the
    merge request). Returns (committed review, written). A failed write never undoes the commit."""
    committed = dict(review)
    committed.update({"committed_as": sha,
                      "committed_paths": sorted(set(targets) | set(review.get("already_committed") or []))})
    try:
        _write_json(committed_review_path(root), committed)
        _remove_if_exists(code_review_path(root))
    except OSError:
        return committed, False
    return committed, True


def _already_committed(root, branch, paths):
    """Of `paths` (unchanged in the work tree), those committed on this ticket branch since its recorded base."""
    base = recorded_base(root, branch)
    if not paths or not base or not ref_exists(root, "refs/remotes/origin/" + base) or not head_exists(root):
        return []
    on_branch = set(_name_only_z(root, ["origin/%s...HEAD" % base]))
    return [p for p in paths if p in on_branch]


def cmd_review_classify(args):
    """Check the reviewer's FILES: block against the real changes and derive the default commit / exclude lists."""
    root = find_project_root()
    if os.path.isfile(scope_path(root)):
        os.remove(scope_path(root))  # a new review always replaces the previous decisions
    uncommitted, committed = review_candidates(root, "origin/" + args.base)
    entries, verdict, reply_bundle_id = parse_review_files(read_text_arg(None, args.result_file, "kết quả review"))
    if not entries:
        raise MpsError("review_unparsable", "Không đọc được khối FILES: trong kết quả review. Hãy yêu cầu reviewer trả "
                                            "lời đúng định dạng rồi chạy lại.", result_file=args.result_file)
    # The reply must be for the bundle the reviewer actually read, and nothing may have changed since that bundle.
    bundle = _read_json(bundle_meta_path(root))
    reason = stale_bundle_reason(bundle, reply_bundle_id, args.base, current_branch(root), head_sha(root),
                                 file_blobs(root, uncommitted))
    if reason:
        raise MpsError("review_stale", "Kết quả review này không khớp với các thay đổi hiện tại (%s). Hãy chạy lại git "
                                       "diff-for-review và nhờ reviewer review lại bundle mới." % reason, reason=reason)
    result = classify_review(entries, uncommitted, committed, verdict)
    result.update({"bundle_id": bundle["bundle_id"], "files_to_classify": uncommitted,
                   "already_committed_files": committed})
    # Persist the decisions with the fingerprints of what the reviewer saw: `git commit` only accepts approved
    # files whose content is still exactly that, and only from a complete review.
    scope = {"base": args.base, "branch": bundle["branch"], "head": bundle["head"], "bundle_id": bundle["bundle_id"],
             "blobs": bundle["blobs"]}
    for name in ("commit_files", "excluded_files", "mixed_files", "unclassified_files", "needs_decision", "verdict",
                 "complete"):
        scope[name] = result[name]
    path = scope_path(root)
    with open(path, "wb") as handle:
        handle.write(json.dumps(scope, ensure_ascii=False, indent=2).encode("utf-8"))
    result["scope_file"] = path
    return result


def cmd_review_findings(args):
    """Check the code reviewer's FINDINGS: block against the code bundle (rules, files, numbered lines) and save it."""
    root = find_project_root()
    pending = code_review_path(root)
    _remove_if_exists(pending)  # a new code review always replaces the previous one (fail-closed)
    entries, reply_bundle_id = parse_findings(read_text_arg(None, args.result_file, "kết quả review code"))
    if entries is None:
        raise MpsError("code_review_unparsable", "Không đọc được khối FINDINGS: trong kết quả review code. Hãy yêu cầu "
                                                 "reviewer trả lời đúng định dạng cho cùng bundle rồi chạy lại review "
                                                 "findings.", result_file=args.result_file)
    bundle = _read_json(bundle_meta_path(root))
    uncommitted, committed = review_candidates(root, "origin/" + args.base)
    reason = stale_bundle_reason(bundle, reply_bundle_id, args.base, current_branch(root), head_sha(root),
                                 file_blobs(root, uncommitted))
    if reason is None and "code_review" not in bundle:
        reason = "no_code_bundle"  # the bundle was made without --to-file
    if reason:
        raise MpsError("review_stale", "Kết quả review này không khớp với các thay đổi hiện tại (%s). Hãy chạy lại git "
                                       "diff-for-review và nhờ reviewer review lại bundle mới." % reason, reason=reason)
    code_review = bundle["code_review"]
    verification = verify_findings(entries, code_review, set(uncommitted) | set(committed))
    _write_json(pending, _pending_review_record(bundle, committed, verification))
    result = {"bundle_id": bundle["bundle_id"], "complete": verification["complete"],
              "needs_reviewer_fix": not verification["complete"]}
    for name in ("findings", "blockers", "rule_warnings", "blockers_in_candidates", "blocked_paths",
                 "dropped_findings", "dropped_count", "duplicate_count"):
        result[name] = verification[name]
    result.update({"rules_applied": [rule["id"] for rule in code_review["rules"]],
                   "profiles": code_review["profiles"], "project_rules": code_review["project_rules"],
                   "code_bundle_truncated": code_review["truncated"], "truncated_paths": code_review["truncated_paths"],
                   "warnings": code_review["warnings"], "auto": code_review.get("auto"), "code_review_file": pending})
    return result


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")


def cmd_git_set_identity(args):
    root = find_project_root()
    name = " ".join(args.name.split())
    email = args.email.strip()
    if not name:
        raise MpsError("invalid_identity", "Tên hiển thị cho git đang trống.")
    if not _EMAIL_RE.match(email):
        raise MpsError("invalid_identity", "Email không hợp lệ: '%s'." % email)
    run_git(["config", "--local", "user.name", name], root)
    run_git(["config", "--local", "user.email", email], root)
    return {"name": name, "email": email, "scope": "local"}


def cmd_git_push(args):
    root = find_project_root()
    cfg = load_config(root)
    name = args.branch
    validate_branch_name(root, name)
    if is_protected_branch(name, cfg.branches()):
        raise MpsError("protected_branch", "Không đẩy thẳng lên nhánh %s. Code phải đi qua merge request." % name,
                       branch=name)
    if not ref_exists(root, "refs/heads/" + name):
        raise MpsError("branch_not_found", "Không có nhánh %s trên máy." % name)
    validate_branch_name(root, args.base)
    ensure_valid_base(args.base, cfg.branches())
    if not ref_exists(root, "refs/remotes/origin/" + args.base):
        raise MpsError("base_not_found", "Chưa có origin/%s trên máy. Hãy chạy git prepare-branch trước." % args.base,
                       base=args.base)
    ensure_recorded_base_matches(root, name, args.base)
    # Last gate before anything leaves the machine. Inspected per commit (git log), not as a net diff: a secret
    # added in one commit and deleted in a later one is gone from the diff but still published in history.
    publish_range = "origin/%s..refs/heads/%s" % (args.base, name)
    env_files = sorted(set(p for p in _commit_touched_files(root, publish_range) if is_env_file(p)))
    if env_files:
        raise MpsError("env_file", "Nhánh %s có commit chứa file .env (token/bí mật). Không được đẩy lên — hãy nhờ "
                                   "developer gỡ file khỏi các commit đó." % name, files=env_files)
    _ensure_no_hard_secrets(_commit_patches(root, publish_range), "các commit sắp đẩy lên")
    refspec = "refs/heads/%s:refs/heads/%s" % (name, name)
    pushed, used_token = run_git_network(root, ["push", "--recurse-submodules=no", "-u", "origin", refspec], cfg)
    if not pushed.ok:
        raise_git_network_error(pushed, "push")
    pushed_sha = run_git(["rev-parse", "refs/heads/" + name], root).stdout.strip()
    run_git(["config", "--local", pushed_config_key(name), pushed_sha], root)
    return {"branch": name, "pushed_commit": pushed_sha, "remote": sanitize_remote_url(origin_url(root)),
            "used_token_fallback": used_token}


# ---------------------------------------------------------------------------
# Commands: merge request
# ---------------------------------------------------------------------------


def _mr_summary(mr, existed):
    return {"existed": existed, "iid": mr.get("iid"), "web_url": mr.get("web_url"), "title": mr.get("title"),
            "source_branch": mr.get("source_branch"), "target_branch": mr.get("target_branch"),
            "state": mr.get("state")}


def _find_open_mr(gitlab, project_id, source):
    found = gitlab.get("/projects/%s/merge_requests" % project_id,
                       params={"state": "opened", "source_branch": source}) or []
    return found[0] if found else None


# Refusals of an optional MR update (assignee, label): reported as warnings, never fatal.
_MR_UPDATE_REFUSED = (400, 401, 403, 404, 409, 422)


def match_label_name(labels, wanted):
    """Exact name of the label whose name equals `wanted` ignoring case (labels: [{"name"}] or names), or None."""
    target = (wanted or "").strip().casefold()
    for label in labels or []:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.strip().casefold() == target:
            return name
    return None


def mr_assignee_usernames(mr):
    assignees = mr.get("assignees") or ([mr["assignee"]] if mr.get("assignee") else [])
    return [a.get("username") for a in assignees if isinstance(a, dict)]


def _assign_failed_warning(details):
    return {"code": "assign_failed", "details": details,
            "message": "Không tự giao (assign) được merge request cho bạn. Hãy tự assign trên trang MR."}


def _label_warning(code, label, details=None):
    if code == "label_not_found":
        message = ("Project GitLab chưa có nhãn (label) \"%s\" nên merge request chưa được gắn nhãn. Hãy nhờ lead tạo "
                   "nhãn này, hoặc tự chọn nhãn trên trang MR." % label)
    else:
        message = "Không gắn được nhãn \"%s\" cho merge request. Hãy tự gắn nhãn trên trang MR." % label
    return {"code": code, "label": label, "details": details, "message": message}


def _current_gitlab_user(gitlab, warnings):
    """The token's GitLab user (for "assign to me"), or None with an assign_failed warning."""
    try:
        user = gitlab.get("/user") or {}
    except MpsError as exc:
        warnings.append(_assign_failed_warning(exc.message))
        return None
    if not user.get("id"):
        warnings.append(_assign_failed_warning("GitLab /user returned no id"))
        return None
    return user


def find_gitlab_label(gitlab, project_id, wanted, warnings):
    """Exact name of an EXISTING project / group label matching `wanted` ignoring case, or None with a warning.

    The label is never created: GitLab would otherwise create a new, differently cased one on the fly.
    """
    try:
        labels = gitlab_get_all(gitlab, "/projects/%s/labels" % project_id,
                                {"search": wanted, "include_ancestor_groups": "true"})
    except MpsError as exc:
        warnings.append(_label_warning("label_failed", wanted, exc.message))
        return None
    name = match_label_name(labels, wanted)
    if name is None:
        warnings.append(_label_warning("label_not_found", wanted))
    return name


def _update_mr(gitlab, mr_path, body):
    """PUT an optional change; returns the updated MR, or None when GitLab refused it or could not be reached."""
    try:
        resp = gitlab.request("PUT", mr_path, body=body, allow_statuses=_MR_UPDATE_REFUSED)
    except MpsError:
        return None
    return resp.data if resp.status == 200 and isinstance(resp.data, dict) else None


def _create_mr(gitlab, project_id, body, extras, label, warnings):
    """POST the MR with the assignee / label extras; if GitLab rejects the request, retry without them (the MR
    itself matters more) and report what was dropped."""
    full = dict(body)
    full.update(extras)
    path = "/projects/%s/merge_requests" % project_id
    resp = gitlab.request("POST", path, body=full, allow_statuses=(400, 409, 422))
    if resp.status in (400, 422) and extras:
        resp = gitlab.request("POST", path, body=body, allow_statuses=(400, 409, 422))
        if resp.status in (200, 201):
            details = extract_server_message(resp.data)
            if "assignee_ids" in extras:
                warnings.append(_assign_failed_warning(details))
            if "labels" in extras:
                warnings.append(_label_warning("label_failed", label, details))
    return resp


def _complete_existing_mr(gitlab, project_id, mr, me, label, warnings):
    """Add what an existing MR lacks: the user as assignee only when it has NO assignee, and the missing label."""
    mr_path = "/projects/%s/merge_requests/%s" % (project_id, mr.get("iid"))
    if me and not mr_assignee_usernames(mr):
        updated = _update_mr(gitlab, mr_path, {"assignee_ids": [me["id"]]})
        if updated is None:
            warnings.append(_assign_failed_warning("PUT %s refused" % mr_path))
        else:
            mr = updated
    if label and match_label_name(mr.get("labels"), label) is None:
        updated = _update_mr(gitlab, mr_path, {"add_labels": label})
        if updated is None:
            warnings.append(_label_warning("label_failed", label, "PUT %s refused" % mr_path))
        else:
            mr = updated
    return mr


def _select_committed_review(root, source):
    """(review, None) when the last committed code review belongs to `source` and its commit is the newest commit of
    what the MR contains (origin/<source> preferred, as for the MR guard); otherwise (None, reason).

    Requiring the tip is the simplest sound rule: git commit replaces the record after every successful commit, so a
    record whose commit is not the tip means a later commit has no review of its own (made by hand, or its record
    could not be written after a crash or write error) and the report would describe older code. A commit that
    fails (e.g. a hook rejects it) leaves the still-valid record of the previous commit alone.
    """
    review = _read_json(committed_review_path(root))
    if review is None:
        return None, "no_review"
    if review.get("branch") != source:
        return None, "other_branch"
    sha = review.get("committed_as")
    source_ref = _source_ref(root, source)
    if not sha or not run_git(["merge-base", "--is-ancestor", sha, source_ref], root, check=False).ok:
        return None, "not_in_branch"
    if run_git(["rev-parse", source_ref], root).stdout.strip() != sha:
        return None, "outdated"
    return review, None


def _review_note_key(mr, review):
    return "%s:%s" % (mr.get("iid"), review.get("bundle_id"))


def _remember_review_note(root, review, key):
    """Record that this review is on this MR, so a rerun of mr ensure does not add it again."""
    review["mr_note"] = key
    try:
        _write_json(committed_review_path(root), review)
    except OSError:
        pass  # best effort: the report is on the MR; at worst a later rerun adds it once more


def _attach_review_note(root, gitlab, project_id, mr, review, section, warnings):
    """Existing MR: add the report once as a comment. Returns (attached, reason); a failure is only a warning."""
    key = _review_note_key(mr, review)
    if review.get("mr_note") == key:
        return "already", None
    try:
        gitlab.request("POST", "/projects/%s/merge_requests/%s/notes" % (project_id, mr.get("iid")),
                       body={"body": section})
    except MpsError as exc:
        warnings.append({"code": "code_review_note_failed", "details": exc.message,
                         "message": "Không thêm được ghi chú kết quả review code vào merge request đã có (merge request "
                                    "vẫn bình thường). Có thể chạy lại mr ensure sau."})
        return "none", "note_failed"
    _remember_review_note(root, review, key)
    return "note", None


def cmd_mr_ensure(args):
    root = find_project_root()
    cfg = load_config(root)
    # Enforced here, whatever the agent was told: no AI attribution in the MR the team reviews.
    title, title_stripped = strip_ai_attribution(args.title)
    description, description_stripped = strip_ai_attribution(args.description)
    if not title.strip() or not description.strip():
        raise MpsError("empty_message", "Tiêu đề hoặc mô tả merge request đang trống.")
    if args.source == args.target:
        raise MpsError("invalid_mr", "Nhánh nguồn và nhánh đích không được trùng nhau.")
    branches = cfg.branches()
    ensure_valid_base(args.target, branches)
    # The phase rules apply to the target too: no Story into a release branch or master.
    plan_phase(phase_of_branch(args.target, branches), args.type, branches)
    # Offline guard first: the MR must go back into the branch the work was based on, with only this ticket's commits.
    ensure_mr_target(root, args.source, args.target, normalize_issue_key(args.key), branches)
    review, review_reason = (None, None)
    if args.code_review:
        review, review_reason = _select_committed_review(root, args.source)
    # Built by the script from stored data and appended AFTER the attribution strip, which can never remove it.
    section = render_mr_review_section(review) if review else None
    attached = "none"
    gitlab = gitlab_client(cfg)
    project = resolve_gitlab_project(cfg, gitlab)
    # Assignee and label are best effort: their failures are warnings and never stop the MR.
    warnings = []
    me = _current_gitlab_user(gitlab, warnings)
    label = find_gitlab_label(gitlab, project["id"], MR_LABELS[args.type], warnings)
    existing = _find_open_mr(gitlab, project["id"], args.source)
    mr = None
    if existing is None:
        body = {"source_branch": args.source, "target_branch": args.target, "title": title,
                "description": description if section is None else description + "\n\n" + section,
                "remove_source_branch": True}
        extras = {}
        if me:
            extras["assignee_ids"] = [me["id"]]
        if label:
            extras["labels"] = label
        resp = _create_mr(gitlab, project["id"], body, extras, label, warnings)
        if resp.status in (200, 201):
            mr = resp.data
            if section is not None:
                attached = "description"
                _remember_review_note(root, review, _review_note_key(mr, review))
        else:
            # GitLab answers 409 or 422 when an open MR for the branch appeared meanwhile: reuse that one.
            existing = _find_open_mr(gitlab, project["id"], args.source) if resp.status in (409, 422) else None
            if existing is None:
                raise MpsError("mr_create_failed", "GitLab không tạo được merge request (nhánh đã được đẩy lên chưa?).",
                               details=extract_server_message(resp.data), status=resp.status)
    if mr is None:
        if existing.get("target_branch") != args.target:
            raise MpsError("mr_target_mismatch",
                           "Nhánh %s đã có merge request đang mở nhưng nhắm vào %s thay vì %s. Không dùng tiếp MR "
                           "này — hãy nhờ developer kiểm tra (có thể cần một nhánh khác cho giai đoạn này)."
                           % (args.source, existing.get("target_branch"), args.target),
                           existing_mr=_mr_summary(existing, True), expected_target=args.target)
        mr = _complete_existing_mr(gitlab, project["id"], existing, me, label, warnings)
        if section is not None:
            attached, review_reason = _attach_review_note(root, gitlab, project["id"], mr, review, section, warnings)
    result = _mr_summary(mr, existing is not None)
    result.update({"assignees": mr_assignee_usernames(mr), "labels": list(mr.get("labels") or []),
                   "warnings": warnings, "attribution_removed": title_stripped or description_stripped})
    if args.code_review:
        result["code_review_attached"] = attached
        result["code_review_warning_count"] = len(code_review_warning_items(review)) if attached != "none" else 0
        if attached == "none":
            result["code_review_reason"] = review_reason
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class JsonArgumentParser(argparse.ArgumentParser):
    """Argument errors are reported as JSON too."""

    def error(self, message):
        emit({"ok": False, "error": "usage_error", "message": "Tham số không hợp lệ: " + message,
              "usage": self.format_usage().strip()})
        sys.exit(EXIT_USAGE)


def _subcommands(parser, dest):
    sub = parser.add_subparsers(dest=dest, metavar="<%s>" % dest)
    sub.required = True
    return sub


def build_parser():
    parser = JsonArgumentParser(prog="mps.py", description="MPS git flow helper. Prints one JSON object per command.")
    parser.add_argument("--version", action="version", version=VERSION)
    groups = _subcommands(parser, "group")

    env = _subcommands(groups.add_parser("env", help="project .env configuration"), "command")
    p = env.add_parser("init", help="create .env from the template (never overwrites)")
    p.add_argument("--open", action="store_true", help="open .env in the default editor")
    p.set_defaults(handler=cmd_env_init)
    p = env.add_parser("check", help="validate .env and both connections")
    p.set_defaults(handler=cmd_env_check)
    p = env.add_parser("set", help="set a NON-secret key in .env")
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(handler=cmd_env_set)

    project = _subcommands(groups.add_parser("project", help="plugin integration for the project (lead)"), "command")
    p = project.add_parser("setup", help="add the plugin (auto-update on) to .claude/settings.json, git-ignore .env")
    p.add_argument("--review-rules", action="store_true",
                   help="also create %s from the template when the project has none" % PROJECT_RULES_PATH)
    p.set_defaults(handler=cmd_project_setup)

    jira = _subcommands(groups.add_parser("jira", help="Jira tickets"), "command")
    p = jira.add_parser("get", help="read a ticket")
    p.add_argument("key")
    p.set_defaults(handler=cmd_jira_get)
    p = jira.add_parser("create", help="create a Story or Bug assigned to you")
    p.add_argument("--type", required=True, choices=TICKET_TYPES)
    p.add_argument("--summary", required=True)
    desc = p.add_mutually_exclusive_group()
    desc.add_argument("--description", default="")
    desc.add_argument("--description-file", help="UTF-8 file with the description")
    p.add_argument("--field", action="append", default=[], metavar="NAME=VALUE",
                   help="extra field by id or name (repeatable); JSON values allowed")
    p.add_argument("--project", help="one-off Jira project key (e.g. the artist board); default MPS_JIRA_PROJECT_KEY")
    p.add_argument("--sprint", type=parse_sprint_choice, metavar="active|backlog|ID",
                   help="bug: default active (the running sprint); story: required when a sprint is running "
                        "(ask the user, it changes the sprint scope)")
    p.set_defaults(handler=cmd_jira_create)
    p = jira.add_parser("sprints", help="active sprints of the board a new ticket goes to")
    p.add_argument("--project", help="one-off Jira project key; default MPS_JIRA_PROJECT_KEY")
    p.set_defaults(handler=cmd_jira_sprints)
    p = jira.add_parser("projects", help="list Jira projects (boards) you can see")
    p.set_defaults(handler=cmd_jira_projects)
    p = jira.add_parser("transition", help="move a ticket to done/resolved")
    p.add_argument("key")
    p.add_argument("--to", required=True, choices=("done", "resolved"))
    p.set_defaults(handler=cmd_jira_transition)
    p = jira.add_parser("comment", help="add a comment")
    p.add_argument("key")
    body = p.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--body-file", help="UTF-8 file with the comment")
    p.set_defaults(handler=cmd_jira_comment)

    naming = _subcommands(groups.add_parser("naming", help="branch / commit / MR names"), "command")
    p = naming.add_parser("build", help="build names from a ticket")
    p.add_argument("--key", required=True)
    p.add_argument("--type", required=True, choices=tuple(NAMING_RULES))
    p.add_argument("--title", required=True)
    p.set_defaults(handler=cmd_naming_build)

    flow = _subcommands(groups.add_parser("flow", help="phase rules"), "command")
    p = flow.add_parser("plan", help="base/target branch and kind; phase detected from the current branch if omitted")
    p.add_argument("--phase", choices=PHASES, help="omit to detect it from the current branch")
    p.add_argument("--key", required=True, help="current Jira ticket; only its own ticket branch pins the phase")
    p.add_argument("--type", required=True, choices=TICKET_TYPES)
    p.set_defaults(handler=cmd_flow_plan)

    git = _subcommands(groups.add_parser("git", help="local git operations"), "command")
    p = git.add_parser("preflight", help="status + blockers before committing")
    p.add_argument("--base")
    p.add_argument("--branch", help="planned ticket branch name")
    p.set_defaults(handler=cmd_git_preflight)
    p = git.add_parser("prepare-branch", help="switch to / create the ticket branch")
    p.add_argument("--base", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--key", required=True, help="Jira key; existing branches must only hold commits for it")
    p.add_argument("--leave-commits", action="store_true",
                   help="user confirmed: leave unpushed commits of the current branch behind")
    p.set_defaults(handler=cmd_git_prepare_branch)
    p = git.add_parser("set-identity", help="set repo-local git user.name / user.email (with the user's consent)")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.set_defaults(handler=cmd_git_set_identity)
    p = git.add_parser("diff-for-review", help="changes vs origin/BASE for the scope reviewer and the code reviewer")
    p.add_argument("--base", required=True)
    p.add_argument("--to-file", action="store_true", help="write the bundles to <git-dir>/%s and <git-dir>/%s" % (
        REVIEW_BUNDLE_FILENAME, CODE_REVIEW_BUNDLE_FILENAME))
    p.set_defaults(handler=cmd_git_diff_for_review)
    p = git.add_parser("commit", help="commit exactly the listed files (no folders, no 'everything' mode)")
    p.add_argument("--message", required=True)
    p.add_argument("--files", nargs="+", required=True, help="root-relative file paths agreed with the user")
    p.add_argument("--include-out-of-scope", nargs="+", metavar="FILE",
                   help="files (also in --files) the user explicitly chose to commit although the review did not")
    p.set_defaults(handler=cmd_git_commit)
    p = git.add_parser("push", help="push the branch (never forced)")
    p.add_argument("--branch", required=True)
    p.add_argument("--base", required=True, help="base branch; commits in origin/BASE...BRANCH are checked first")
    p.set_defaults(handler=cmd_git_push)

    mr = _subcommands(groups.add_parser("mr", help="GitLab merge requests"), "command")
    p = mr.add_parser("ensure", help="find or create the MR")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--key", required=True, help="Jira key; every commit in origin/TARGET..SOURCE must mention it")
    p.add_argument("--type", required=True, choices=TICKET_TYPES, help="ticket type; checked against the target's phase")
    p.add_argument("--code-review", action="store_true",
                   help="add the report of the last committed code review (new MR: description; existing MR: one note)")
    p.set_defaults(handler=cmd_mr_ensure)

    review = _subcommands(groups.add_parser("review", help="scope review and code review results"), "command")
    p = review.add_parser("classify", help="check the reviewer's FILES: block, derive commit / exclude lists")
    p.add_argument("--base", required=True)
    p.add_argument("--result-file", required=True, help="file with the reviewer's full reply (in tmp_dir)")
    p.set_defaults(handler=cmd_review_classify)
    p = review.add_parser("findings", help="check the code reviewer's FINDINGS: block against the code bundle")
    p.add_argument("--base", required=True)
    p.add_argument("--result-file", required=True, help="file with the code reviewer's full reply (in tmp_dir)")
    p.set_defaults(handler=cmd_review_findings)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ensure_plugin_source_current(args.group, args.command, os.environ)
        result = args.handler(args)
    except MpsError as exc:
        payload = {"ok": False, "error": exc.code, "message": exc.message}
        payload.update(exc.extra)
        emit(payload)
        return EXIT_FAILURE
    except KeyboardInterrupt:
        emit({"ok": False, "error": "interrupted", "message": "Đã dừng theo yêu cầu."})
        return EXIT_FAILURE
    except Exception as exc:  # noqa: BLE001 - last-resort guard so the agent always gets JSON
        emit({"ok": False, "error": "internal_error", "message": "Lỗi không mong muốn trong script mps.py.",
              "details": "%s: %s" % (type(exc).__name__, exc)})
        return EXIT_INTERNAL
    payload = {"ok": True}
    payload.update(result)
    emit(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
