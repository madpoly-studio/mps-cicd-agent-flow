# -*- coding: utf-8 -*-
"""Unit tests for the pure functions of plugins/mps-git-flow/skills/mps-git-flow/scripts/mps.py (no network, no git)."""

import copy
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "mps-git-flow", "skills",
                           "mps-git-flow", "scripts", "mps.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("mps", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mps = _load_module()
BRANCHES = {"dev": "develop", "beta_prefix": "release/", "prod": "master"}


class ParseEnvTests(unittest.TestCase):
    def test_basic_comments_quotes_and_export(self):
        text = "\n".join([
            "# comment",
            "",
            "MPS_JIRA_URL=https://jira.example",
            "MPS_JIRA_PAT=abc123",
            "MPS_JIRA_PROJECT_KEY=          # inline comment only",
            "MPS_BRANCH_DEV = 'develop'",
            'MPS_CA_BUNDLE="C:/certs/my ca.pem"',
            "export MPS_BRANCH_PROD=main # trailing comment",
            "not a valid line",
        ])
        env = mps.parse_env(text)
        self.assertEqual(env["MPS_JIRA_URL"], "https://jira.example")
        self.assertEqual(env["MPS_JIRA_PAT"], "abc123")
        self.assertEqual(env["MPS_JIRA_PROJECT_KEY"], "")
        self.assertEqual(env["MPS_BRANCH_DEV"], "develop")
        self.assertEqual(env["MPS_CA_BUNDLE"], "C:/certs/my ca.pem")
        self.assertEqual(env["MPS_BRANCH_PROD"], "main")
        self.assertEqual(len(env), 6)

    def test_crlf_and_last_duplicate_wins(self):
        env = mps.parse_env("A=1\r\nA=2\r\n")
        self.assertEqual(env, {"A": "2"})

    def test_update_env_text_replaces_and_dedupes(self):
        text = "A=1\nMPS_JIRA_PROJECT_KEY=\nB=2\nMPS_JIRA_PROJECT_KEY=OLD\n"
        updated = mps.update_env_text(text, "MPS_JIRA_PROJECT_KEY", "MPS")
        self.assertEqual(updated, "A=1\nMPS_JIRA_PROJECT_KEY=MPS\nB=2\n")
        self.assertEqual(mps.parse_env(updated)["MPS_JIRA_PROJECT_KEY"], "MPS")

    def test_update_env_text_appends_and_keeps_crlf(self):
        updated = mps.update_env_text("A=1\r\n", "MPS_GITLAB_PROJECT", "group/sub/proj")
        self.assertEqual(updated, "A=1\r\nMPS_GITLAB_PROJECT=group/sub/proj\r\n")

    def test_update_env_text_quotes_values_with_spaces(self):
        updated = mps.update_env_text("", "MPS_CA_BUNDLE", "C:/my certs/ca.pem")
        self.assertEqual(mps.parse_env(updated)["MPS_CA_BUNDLE"], "C:/my certs/ca.pem")


class SlugifyTests(unittest.TestCase):
    def test_vietnamese_fold(self):
        self.assertEqual(mps.slugify("Sửa lỗi đăng nhập Đặc biệt!"), "sua-loi-dang-nhap-dac-biet")

    def test_collapse_and_trim(self):
        self.assertEqual(mps.slugify("  --Hello,   World__2.0--  "), "hello-world-2-0")

    def test_length_cap_cuts_at_dash_boundary(self):
        title = "Thêm màn hình quản lý người dùng cho trang quản trị hệ thống nội bộ"
        slug = mps.slugify(title)
        self.assertLessEqual(len(slug), mps.SLUG_MAX_LEN)
        self.assertFalse(slug.endswith("-"))
        self.assertTrue(("them-man-hinh-quan-ly-nguoi-dung-cho-trang-quan-tri-he-thong").startswith(slug))
        self.assertEqual(slug, "them-man-hinh-quan-ly-nguoi-dung-cho-trang-quan")

    def test_single_long_word_is_hard_cut(self):
        self.assertEqual(len(mps.slugify("a" * 80)), mps.SLUG_MAX_LEN)

    def test_symbols_only_gives_empty_slug(self):
        self.assertEqual(mps.slugify("!!! ???"), "")


class BuildNamesTests(unittest.TestCase):
    def test_story(self):
        names = mps.build_names("mps-123", "story", "Thêm màn hình Đăng nhập")
        self.assertEqual(names["branch"], "feature/MPS-123-them-man-hinh-dang-nhap")
        self.assertEqual(names["commit_message"], "feat: MPS-123 Thêm màn hình Đăng nhập")
        self.assertEqual(names["mr_title"], "MPS-123 Thêm màn hình Đăng nhập")
        self.assertEqual(names["mr_description"], "Close MPS-123")

    def test_bug(self):
        names = mps.build_names("MPS-7", "bug", "Sửa lỗi  crash khi mở app")
        self.assertEqual(names["branch"], "bugfix/MPS-7-sua-loi-crash-khi-mo-app")
        self.assertEqual(names["commit_message"], "fix: MPS-7 Sửa lỗi crash khi mở app")
        self.assertEqual(names["mr_title"], "MPS-7 Sửa lỗi crash khi mở app")
        self.assertEqual(names["mr_description"], "Close MPS-7")

    def test_hotfix(self):
        names = mps.build_names("MPS-9", "hotfix", "Lỗi thanh toán")
        self.assertEqual(names["branch"], "hotfix/MPS-9-loi-thanh-toan")
        self.assertEqual(names["commit_message"], "fix: MPS-9 Lỗi thanh toán")
        self.assertEqual(names["mr_title"], "MPS-9 Lỗi thanh toán")
        self.assertEqual(names["mr_description"], "Close MPS-9")

    def test_invalid_key_and_type(self):
        with self.assertRaises(mps.MpsError) as ctx:
            mps.build_names("123", "story", "x")
        self.assertEqual(ctx.exception.code, "invalid_ticket_key")
        with self.assertRaises(mps.MpsError) as ctx:
            mps.build_names("MPS-1", "task", "x")
        self.assertEqual(ctx.exception.code, "invalid_type")
        with self.assertRaises(mps.MpsError) as ctx:
            mps.build_names("MPS-1", "bug", "   ")
        self.assertEqual(ctx.exception.code, "empty_title")


class PhaseRuleTests(unittest.TestCase):
    def test_dev_story_and_bug(self):
        story = mps.plan_phase("dev", "story", BRANCHES)
        self.assertEqual((story["kind"], story["base_branch"], story["target_branch"]),
                         ("feature", "develop", "develop"))
        self.assertEqual(story["naming_type"], "story")
        bug = mps.plan_phase("dev", "bug", BRANCHES)
        self.assertEqual(bug["kind"], "bugfix")
        self.assertEqual(bug["naming_type"], "bug")

    def test_beta_story_rejected(self):
        with self.assertRaises(mps.MpsError) as ctx:
            mps.plan_phase("beta", "story", BRANCHES)
        self.assertEqual(ctx.exception.code, "phase_rule_violation")

    def test_beta_bug_needs_release_lookup(self):
        plan = mps.plan_phase("beta", "bug", BRANCHES)
        self.assertEqual(plan["kind"], "bugfix")
        self.assertTrue(plan["needs_release_lookup"])
        self.assertIsNone(plan["base_branch"])

    def test_production_story_rejected(self):
        with self.assertRaises(mps.MpsError) as ctx:
            mps.plan_phase("production", "story", BRANCHES)
        self.assertEqual(ctx.exception.code, "phase_rule_violation")

    def test_production_bug_is_hotfix_with_warning(self):
        plan = mps.plan_phase("production", "bug", BRANCHES, access_level=40)
        self.assertEqual((plan["kind"], plan["base_branch"], plan["target_branch"]), ("hotfix", "master", "master"))
        self.assertEqual(plan["naming_type"], "hotfix")
        self.assertTrue(plan["requires_explicit_confirmation"])
        self.assertIn("CẢNH BÁO", plan["warning"])
        self.assertEqual(plan["access_level_name"], "Maintainer")

    def test_production_warning_stronger_below_maintainer(self):
        developer = mps.plan_phase("production", "bug", BRANCHES, access_level=30)["warning"]
        maintainer = mps.plan_phase("production", "bug", BRANCHES, access_level=40)["warning"]
        self.assertGreater(len(developer), len(maintainer))
        self.assertIn("Developer", developer)

    def test_protected_branches(self):
        self.assertTrue(mps.is_protected_branch("develop", BRANCHES))
        self.assertTrue(mps.is_protected_branch("master", BRANCHES))
        self.assertTrue(mps.is_protected_branch("release/1.2.0", BRANCHES))
        self.assertFalse(mps.is_protected_branch("feature/MPS-1-x", BRANCHES))


class ReleaseSortTests(unittest.TestCase):
    def test_version_order(self):
        branches = [
            {"name": "release/1.9.2", "committed_date": "2024-05-01T10:00:00.000+07:00"},
            {"name": "release/1.10.0", "committed_date": "2024-01-01T10:00:00.000+07:00"},
            {"name": "release/1.2", "committed_date": "2024-06-01T10:00:00Z"},
            {"name": "feature/x", "committed_date": "2025-01-01T10:00:00Z"},
        ]
        names = [b["name"] for b in mps.sort_release_branches(branches, "release/")]
        self.assertEqual(names, ["release/1.10.0", "release/1.9.2", "release/1.2"])
        self.assertEqual(mps.release_sort_method(branches, "release/"), "version")

    def test_fallback_to_committed_date(self):
        branches = [
            {"name": "release/1.10.0", "committed_date": "2024-01-01T10:00:00.000+07:00"},
            {"name": "release/next", "committed_date": "2024-03-01T03:00:00.000+00:00"},
            {"name": "release/1.9.2", "committed_date": "2024-02-01T10:00:00.123456789+07:00"},
        ]
        names = [b["name"] for b in mps.sort_release_branches(branches, "release/")]
        self.assertEqual(names, ["release/next", "release/1.9.2", "release/1.10.0"])
        self.assertEqual(mps.release_sort_method(branches, "release/"), "committed_date")

    def test_timezone_aware_date_compare(self):
        branches = [
            {"name": "release/a", "committed_date": "2024-01-01T08:00:00+07:00"},
            {"name": "release/b", "committed_date": "2024-01-01T02:00:00Z"},
        ]
        names = [b["name"] for b in mps.sort_release_branches(branches, "release/")]
        self.assertEqual(names, ["release/b", "release/a"])

    def test_empty(self):
        self.assertEqual(mps.sort_release_branches([{"name": "develop"}], "release/"), [])


class ScanSecretsTests(unittest.TestCase):
    DIFF = "\n".join([
        "diff --git a/app/config.py b/app/config.py",
        "index 111..222 100644",
        "--- a/app/config.py",
        "+++ b/app/config.py",
        "@@ -10,2 +10,4 @@ def x():",
        " unchanged = 1",
        "-password = 'old-removed-value'",
        "+GITLAB = 'glpat-abcdefghij1234567890'",
        "+db_password = 'hunter22secret'",
        "+name = 'ok'",
        "diff --git a/keys/id_rsa b/keys/id_rsa",
        "new file mode 100644",
        "--- /dev/null",
        "+++ b/keys/id_rsa",
        "@@ -0,0 +1,2 @@",
        "+-----BEGIN OPENSSH PRIVATE KEY-----",
        "++++ not a header, an added line starting with ++",
        "diff --git a/.env.example b/.env.example",
        "--- a/.env.example",
        "+++ b/.env.example",
        "@@ -1 +1 @@",
        "-MPS_JIRA_PAT=",
        "+MPS_JIRA_PAT=realtoken123",
    ])

    def test_findings(self):
        findings = mps.scan_secrets(self.DIFF)
        summary = sorted((f["file"], f["line"], f["rule"]) for f in findings)
        self.assertEqual(summary, [
            (".env.example", 1, "mps_pat"),
            ("app/config.py", 11, "gitlab_token"),
            ("app/config.py", 12, "generic_secret"),
            ("keys/id_rsa", 1, "private_key"),
        ])
        generic = [f for f in findings if f["rule"] == "generic_secret"][0]
        self.assertTrue(generic["confirmable"])

    def test_removed_lines_and_empty_values_ignored(self):
        diff = "+++ b/a.txt\n@@ -1,2 +1,1 @@\n-token = 'abcdefgh'\n+MPS_GITLAB_PAT=\n"
        self.assertEqual(mps.scan_secrets(diff), [])

    def test_findings_never_contain_secret_text(self):
        for finding in mps.scan_secrets(self.DIFF):
            self.assertNotIn("glpat-abcdefghij", str(finding))

    def test_scan_text(self):
        findings = mps.scan_text("new.cfg", "a=1\npassword: superSecret!\n")
        self.assertEqual([(f["line"], f["rule"]) for f in findings], [(2, "generic_secret")])


class GitParsingTests(unittest.TestCase):
    def test_parse_porcelain_z(self):
        output = "M  staged.txt\0 M unstaged.txt\0MM both.txt\0R  new.txt\0old.txt\0?? untracked.txt\0UU conflict.txt\0"
        status = mps.parse_porcelain_z(output)
        self.assertEqual(status["staged"], ["staged.txt", "both.txt", "old.txt", "new.txt"])
        self.assertEqual(status["unstaged"], ["unstaged.txt", "both.txt"])
        self.assertEqual(status["untracked"], ["untracked.txt"])
        self.assertEqual(status["unmerged"], ["conflict.txt"])
        self.assertEqual(status["renames"], {"new.txt": "old.txt"})

    def test_targets_and_renames(self):
        targets = [mps.normalize_target_path(p) for p in ["./cfg/", "src\\a.py", "."]]
        self.assertEqual(targets, ["cfg", "src/a.py", "."])
        self.assertTrue(mps.path_in_targets("cfg/.env.local", ["cfg"]))
        self.assertFalse(mps.path_in_targets("cfgx/a", ["cfg"]))
        self.assertTrue(mps.path_in_targets("anything", ["."]))
        self.assertEqual(mps.expand_rename_sources(["new.txt"], {"new.txt": "old.txt"}), ["new.txt", "old.txt"])
        self.assertEqual(mps.expand_rename_sources(["old.txt"], {"new.txt": "old.txt"}), ["old.txt", "new.txt"])
        self.assertEqual(mps.expand_rename_sources(["x"], {"new.txt": "old.txt"}), ["x"])

    def test_parse_check_attr_z(self):
        output = "big.bin\0filter\0lfs\0a.txt\0filter\0unspecified\0"
        self.assertEqual(mps.parse_check_attr_z(output), {"big.bin": "lfs", "a.txt": "unspecified"})

    def test_find_foreign_commits(self):
        log = "aaaa\tfix: MPS-2 Sửa lỗi\nbbbb\tfeat: MPS-5 unreleased\ncccc\tfix: mps-2 lower case\ndddd\tfix: MPS-20 other\n"
        foreign = mps.find_foreign_commits(log, "MPS-2")
        self.assertEqual([c["sha"] for c in foreign], ["bbbb", "dddd"])

    def test_is_env_file(self):
        self.assertTrue(mps.is_env_file(".env"))
        self.assertTrue(mps.is_env_file("server/.env.production"))
        self.assertFalse(mps.is_env_file(".env.example"))
        self.assertFalse(mps.is_env_file("docs/environment.md"))

    def test_parse_remote_project_path(self):
        gitlab = "https://git-gst.mto.zing.vn"
        self.assertEqual(mps.parse_remote_project_path("https://git-gst.mto.zing.vn/grp/sub/proj.git", gitlab),
                         "grp/sub/proj")
        self.assertEqual(mps.parse_remote_project_path("https://user:pw@GIT-GST.mto.zing.vn:8443/grp/proj", gitlab),
                         "grp/proj")
        self.assertEqual(mps.parse_remote_project_path("git@git-gst.mto.zing.vn:grp/proj.git", gitlab), "grp/proj")
        self.assertEqual(mps.parse_remote_project_path("ssh://git@git-gst.mto.zing.vn:2222/grp/proj.git", gitlab),
                         "grp/proj")
        self.assertIsNone(mps.parse_remote_project_path("https://github.com/grp/proj.git", gitlab))

    def test_sanitize_remote_url(self):
        self.assertEqual(mps.sanitize_remote_url("https://oauth2:glpat-x@host/g/p.git"), "https://host/g/p.git")
        self.assertEqual(mps.sanitize_remote_url("git@host:g/p.git"), "git@host:g/p.git")

    def test_classify_git_network_error(self):
        rejected = " ! [rejected]        x -> x (fetch first)\nerror: failed to push some refs"
        self.assertEqual(mps.classify_git_network_error(rejected, "push")[0], "push_rejected")
        auth = "remote: HTTP Basic: Access denied\nfatal: Authentication failed for 'https://h/g/p.git/'"
        self.assertEqual(mps.classify_git_network_error(auth, "push")[0], "auth_failed")
        self.assertTrue(mps.is_git_auth_error(auth))
        dns = "fatal: unable to access 'https://h/': Could not resolve host: h"
        self.assertEqual(mps.classify_git_network_error(dns, "fetch")[0], "network_unreachable")

    def test_apply_budget(self):
        self.assertEqual(mps.apply_budget(["abc", "defg", "hi"], 5), [("abc", False), ("de", True), ("", True)])


class JiraHelperTests(unittest.TestCase):
    def test_normalize_issue_type(self):
        self.assertEqual(mps.normalize_issue_type("Story"), "story")
        self.assertEqual(mps.normalize_issue_type("BUG"), "bug")
        self.assertIsNone(mps.normalize_issue_type("Task"))

    def test_pick_transition(self):
        transitions = [{"id": "11", "name": "In Progress", "to": {"name": "In Progress"}},
                       {"id": "21", "name": "Resolve Issue", "to": {"name": "Resolved"}},
                       {"id": "31", "name": "Finish", "to": {"name": "Closed"}}]
        self.assertEqual(mps.pick_transition(transitions, "resolved")["id"], "21")
        self.assertEqual(mps.pick_transition(transitions, "done")["id"], "31")
        self.assertIsNone(mps.pick_transition(transitions[:1], "done"))
        vietnamese = [{"id": "5", "name": "Hoàn thành", "to": {"name": "Xong"}}]
        self.assertEqual(mps.pick_transition(vietnamese, "done")["id"], "5")

    def test_resolved_falls_back_to_done_transition(self):
        no_resolve = [{"id": "11", "name": "In Progress", "to": {"name": "In Progress"}},
                      {"id": "41", "name": "Done", "to": {"name": "Done"}}]
        self.assertEqual(mps.pick_transition(no_resolve, "resolved")["id"], "41")
        self.assertTrue(mps.is_in_target_state("Closed", "done", "resolved"))
        self.assertTrue(mps.is_in_target_state("Done", "done", "resolved"))

    def test_is_in_target_state(self):
        self.assertTrue(mps.is_in_target_state("Done", "done", "done"))
        self.assertFalse(mps.is_in_target_state("Resolved", "indeterminate", "done"))
        self.assertTrue(mps.is_in_target_state("Resolved", "indeterminate", "resolved"))
        self.assertFalse(mps.is_in_target_state("In Progress", "indeterminate", "resolved"))

    def test_missing_required_fields_and_field_args(self):
        meta = mps.normalize_field_meta_list([
            {"fieldId": "summary", "name": "Summary", "required": True},
            {"fieldId": "reporter", "name": "Reporter", "required": True},
            {"fieldId": "priority", "name": "Priority", "required": True, "hasDefaultValue": True},
            {"fieldId": "customfield_1", "name": "Team", "required": True, "schema": {"type": "option"},
             "allowedValues": [{"id": "100", "value": "Client"}, {"id": "101", "value": "Server"}]},
            {"fieldId": "components", "name": "Component/s", "required": True,
             "schema": {"type": "array", "items": "component"}, "allowedValues": [{"id": "7", "name": "Core"}]},
        ])
        missing = mps.find_missing_required_fields(meta, {})
        self.assertEqual([m["id"] for m in missing], ["components", "customfield_1"])
        self.assertEqual(missing[1]["allowed_values"][1], {"id": "101", "value": "Server"})
        provided = mps.parse_field_args(["team=server", "customfield_1=Client", "Component/s=core"], meta)
        self.assertEqual(provided, {"customfield_1": {"id": "100"}, "components": [{"id": "7"}]})
        self.assertEqual(mps.find_missing_required_fields(meta, provided), [])
        with self.assertRaises(mps.MpsError) as ctx:
            mps.parse_field_args(["Team=Nope"], meta)
        self.assertEqual(ctx.exception.code, "invalid_field_value")
        with self.assertRaises(mps.MpsError) as ctx:
            mps.parse_field_args(["Unknown=1"], meta)
        self.assertEqual(ctx.exception.code, "unknown_field")

    def test_choose_resolution(self):
        self.assertEqual(mps.choose_resolution([{"id": "1", "name": "Done"}, {"id": "2", "name": "Fixed"}])["id"], "2")
        self.assertEqual(mps.choose_resolution([{"id": "1", "name": "Done"}])["id"], "1")
        self.assertIsNone(mps.choose_resolution([{"id": "3", "name": "Won't Fix"}, {"id": "4", "name": "Duplicate"}]))
        self.assertIsNone(mps.choose_resolution([]))


class RedactTests(unittest.TestCase):
    def test_registered_secret_is_masked(self):
        mps.register_secret("supersecretvalue")
        self.assertEqual(mps.redact('{"x": "supersecretvalue"}'), '{"x": "****"}')


class JiraProjectChoiceTests(unittest.TestCase):
    """R1: the ticket's project may differ from the GitLab project; --project overrides the configured default."""

    def test_override_wins_and_is_normalized(self):
        self.assertEqual(mps.choose_create_project("art", "MPS"), "ART")
        self.assertEqual(mps.choose_create_project(None, "mps"), "MPS")
        self.assertEqual(mps.choose_create_project("", "MPS"), "MPS")

    def test_invalid_key_rejected(self):
        with self.assertRaises(mps.MpsError) as ctx:
            mps.choose_create_project("ART-12", "MPS")
        self.assertEqual(ctx.exception.code, "invalid_project_key")

    def test_ticket_keys_from_any_board_are_accepted(self):
        self.assertEqual(mps.normalize_issue_key("art-12"), "ART-12")
        names = mps.build_names("ART-12", "story", "Vẽ lại icon")
        self.assertEqual(names["branch"], "feature/ART-12-ve-lai-icon")
        self.assertEqual(names["mr_description"], "Close ART-12")
        self.assertTrue(mps.mentions_key("feat: ART-12 Vẽ lại icon", "ART-12"))


class ReviewClassifyTests(unittest.TestCase):
    """R2: the reviewer's FILES block drives the default commit set; out-of-scope is excluded by default."""

    REPLY = "\n".join([
        "### Kết quả review phạm vi - MPS-1",
        "| a | b | c | d |",
        "VERDICT: FAIL",
        "",
        "FILES:",
        "in_scope: src/login.cs",
        "out_of_scope: ProjectSettings/ProjectSettings.asset",
        "mixed: src/menu.cs   (rename of unrelated variable)",
        "- concern: `src/debug.cs`",
        "in_scope: src/login.cs",
        "in_scope: not/in/bundle.cs",
        "",
        "BUNDLE: `AB12CD`",
        "VERDICT: FAIL",
    ])

    def test_parse_review_files(self):
        entries, verdict, bundle_id = mps.parse_review_files(self.REPLY)
        self.assertEqual((verdict, bundle_id), ("FAIL", "ab12cd"))
        self.assertEqual(entries[0], ("in_scope", "src/login.cs"))
        self.assertEqual(entries[3], ("concern", "src/debug.cs"))
        self.assertEqual(len(entries), 6)

    def test_classify_review(self):
        entries, _, _ = mps.parse_review_files(self.REPLY)
        uncommitted = ["src/login.cs", "ProjectSettings/ProjectSettings.asset", "src/menu.cs", "src/debug.cs",
                       "package-lock.json"]
        result = mps.classify_review(entries, uncommitted, ["src/old.cs"], "PASS")
        self.assertEqual(result["commit_files"], ["src/login.cs", "src/debug.cs"])
        self.assertEqual(result["concern_files"], ["src/debug.cs"])
        self.assertEqual(result["needs_decision"], [])
        self.assertEqual(result["excluded_files"], ["ProjectSettings/ProjectSettings.asset"])
        self.assertEqual(result["mixed_files"], ["src/menu.cs"])
        self.assertEqual(result["unclassified_files"], ["package-lock.json"])
        self.assertEqual(result["duplicate_paths"], ["src/login.cs"])
        self.assertEqual(result["unknown_paths"], ["not/in/bundle.cs"])
        self.assertFalse(result["complete"])

    def test_complete_classification(self):
        entries, verdict, _ = mps.parse_review_files("FILES:\nin_scope: a.cs\nout_of_scope: b.meta\nVERDICT: PASS\n")
        result = mps.classify_review(entries, ["a.cs", "b.meta"], [], verdict)
        self.assertTrue(result["complete"])
        self.assertEqual(verdict, "PASS")
        self.assertEqual(result["commit_files"], ["a.cs"])

    def test_fail_verdict_moves_concerns_to_needs_decision(self):
        entries, verdict, _ = mps.parse_review_files("FILES:\nin_scope: a.cs\nconcern: d.cs\nVERDICT: FAIL\n")
        result = mps.classify_review(entries, ["a.cs", "d.cs"], [], verdict)
        self.assertEqual((result["commit_files"], result["needs_decision"]), (["a.cs"], ["d.cs"]))
        self.assertTrue(result["complete"])
        no_verdict = mps.classify_review(entries, ["a.cs", "d.cs"], [], None)
        self.assertEqual(no_verdict["commit_files"], ["a.cs"])
        self.assertFalse(no_verdict["complete"])

    def test_no_files_block(self):
        self.assertEqual(mps.parse_review_files("in_scope: a.cs\nVERDICT: PASS"), ([], "PASS", None))

    def test_stale_bundle_reason(self):
        bundle = {"bundle_id": "ab12", "base": "develop", "branch": "feature/X-1-a", "head": "h1",
                  "blobs": {"a.txt": "b1"}}
        ok_args = ("develop", "feature/X-1-a", "h1", {"a.txt": "b1"})
        self.assertIsNone(mps.stale_bundle_reason(bundle, "ab12", *ok_args))
        self.assertEqual(mps.stale_bundle_reason(None, "ab12", *ok_args), "no_bundle")
        self.assertEqual(mps.stale_bundle_reason(bundle, None, *ok_args), "reply_without_bundle_id")
        self.assertEqual(mps.stale_bundle_reason(bundle, "ffff", *ok_args), "reply_for_other_bundle")
        self.assertEqual(mps.stale_bundle_reason(bundle, "ab12", "release/1.0", "feature/X-1-a", "h1",
                                                 {"a.txt": "b1"}), "base_changed")
        self.assertEqual(mps.stale_bundle_reason(bundle, "ab12", "develop", "feature/X-1-a", "h2",
                                                 {"a.txt": "b1"}), "branch_or_commit_changed")
        self.assertEqual(mps.stale_bundle_reason(bundle, "ab12", "develop", "feature/X-1-a", "h1",
                                                 {"a.txt": "b2"}), "files_changed")
        self.assertEqual(mps.stale_bundle_reason(bundle, "ab12", "develop", "feature/X-1-a", "h1",
                                                 {"a.txt": "b1", "new.txt": "b3"}), "files_changed")

    def test_inferred_target_verdict(self):
        self.assertEqual(mps.inferred_target_verdict("develop", ["develop"], "develop"), "ok")
        self.assertEqual(mps.inferred_target_verdict("release/1.0", ["develop"], "develop"), "mismatch")
        self.assertEqual(mps.inferred_target_verdict("develop", ["develop", "master"], "develop"), "ok")
        self.assertEqual(mps.inferred_target_verdict("master", ["develop", "master"], "develop"), "ambiguous")
        self.assertEqual(mps.inferred_target_verdict("release/1.0", ["release/1.0"], "develop"), "ok")


class BranchContextTests(unittest.TestCase):
    """R3: the MR goes back into exactly the branch the work was based on."""

    def test_detect_roles(self):
        ctx = mps.detect_branch_context
        self.assertEqual(ctx("develop", BRANCHES, None)["detected_phase"], "dev")
        beta = ctx("release/1.1", BRANCHES, None)
        self.assertEqual((beta["current_branch_role"], beta["detected_phase"], beta["detected_base"]),
                         ("beta", "beta", "release/1.1"))
        self.assertEqual(ctx("master", BRANCHES, None)["detected_phase"], "production")
        ticket = ctx("bugfix/MPS-2-x", BRANCHES, "release/1.0")
        self.assertEqual((ticket["current_branch_role"], ticket["detected_phase"], ticket["detected_base"]),
                         ("ticket", "beta", "release/1.0"))
        self.assertEqual(ctx("bugfix/MPS-2-x", BRANCHES, None)["current_branch_role"], "other")
        self.assertEqual(ctx("my-work", BRANCHES, None)["current_branch_role"], "other")
        self.assertEqual(ctx(None, BRANCHES, None)["current_branch_role"], "detached")

    def assert_error(self, code, func, *args):
        with self.assertRaises(mps.MpsError) as ctx:
            func(*args)
        self.assertEqual(ctx.exception.code, code)

    def test_reconcile_phase_dirty_tree_pins(self):
        on_develop = mps.detect_branch_context("develop", BRANCHES, None)
        self.assertEqual(mps.reconcile_phase(on_develop, None, True), ("dev", "detected", True))
        self.assertEqual(mps.reconcile_phase(on_develop, "dev", True), ("dev", "detected", True))
        self.assert_error("phase_conflict", mps.reconcile_phase, on_develop, "beta", True)

    def test_reconcile_phase_clean_tree_follows_request(self):
        on_develop = mps.detect_branch_context("develop", BRANCHES, None)
        self.assertEqual(mps.reconcile_phase(on_develop, "beta", False), ("beta", "requested_clean_tree", False))
        self.assert_error("phase_required", mps.reconcile_phase, on_develop, None, False)
        on_master = mps.detect_branch_context("master", BRANCHES, None)
        self.assert_error("phase_required", mps.reconcile_phase, on_master, None, False)
        other = mps.detect_branch_context("my-work", BRANCHES, None)
        self.assertEqual(mps.reconcile_phase(other, "beta", True), ("beta", "requested", False))
        self.assert_error("phase_required", mps.reconcile_phase, other, None, True)

    def test_own_ticket_branch_pins_even_when_clean(self):
        own = mps.detect_branch_context("bugfix/MPS-2-x", BRANCHES, "release/1.0", key="MPS-2")
        self.assertEqual(own["current_branch_role"], "ticket")
        self.assertEqual(mps.reconcile_phase(own, None, False), ("beta", "detected", True))
        self.assert_error("phase_conflict", mps.reconcile_phase, own, "dev", False)
        foreign = mps.detect_branch_context("bugfix/MPS-2-x", BRANCHES, "release/1.0", key="MPS-3")
        self.assertEqual((foreign["current_branch_role"], foreign["branch_ticket_key"]), ("other", "MPS-2"))
        self.assertEqual(mps.reconcile_phase(foreign, "dev", True), ("dev", "requested", False))

    def test_recorded_base_gone(self):
        gone = mps.detect_branch_context("bugfix/MPS-2-x", BRANCHES, "release/0.9", key="MPS-2",
                                         recorded_base_exists=False)
        self.assertEqual((gone["current_branch_role"], gone["recorded_base_gone"]), ("other", True))
        self.assertEqual(mps.reconcile_phase(gone, "beta", False)[0], "beta")
        self.assert_error("recorded_base_gone", mps.reconcile_phase, gone, "beta", True)

    def test_detached_head(self):
        self.assertEqual(mps.unique_protected_branch(["HEAD", "develop", "feature/x"], BRANCHES), "develop")
        self.assertIsNone(mps.unique_protected_branch(["develop", "master"], BRANCHES))
        on_develop = mps.detect_branch_context(None, BRANCHES, None, detached_at="develop")
        self.assertEqual((on_develop["current_branch_role"], on_develop["detached"]), ("dev", True))
        unknown = mps.detect_branch_context(None, BRANCHES, None)
        self.assertEqual(unknown["current_branch_role"], "detached")
        self.assert_error("detached_head", mps.reconcile_phase, unknown, "dev", True)
        self.assertEqual(mps.reconcile_phase(unknown, "dev", False)[0], "dev")

    def test_release_branch_checks(self):
        branches = [{"name": "release/1.1", "committed_date": "2024-01-01T00:00:00Z"},
                    {"name": "release/1.2", "committed_date": "2024-02-01T00:00:00Z"}]
        names = [b["name"] for b in mps.sort_release_branches(branches, "release/")]
        warning = mps.check_release_branch("release/1.1", names)
        self.assertEqual((warning["code"], warning["latest"]), ("not_latest_release", "release/1.2"))
        self.assertIsNone(mps.check_release_branch("release/1.2", names))
        self.assert_error("release_branch_gone", mps.check_release_branch, "release/1.0", names)
        self.assert_error("release_branch_gone", mps.check_release_branch, "release/1.1", [])

    def test_closest_bases(self):
        self.assertEqual(mps.closest_bases({"develop": 1, "release/1.0": 2, "master": 1}), ["develop", "master"])
        self.assertEqual(mps.closest_bases({}), [])
        self.assertEqual(mps.ticket_key_of_branch("bugfix/art-12-x"), "ART-12")
        self.assertIsNone(mps.ticket_key_of_branch("develop"))


class GeneratedFilesTests(unittest.TestCase):
    """Tool-generated files (Unity) never make the current branch 'hold work' for phase pinning."""

    UNITY_AT_ROOT = mps.generated_rules([""], [])

    def test_default_patterns_at_the_unity_root(self):
        generated = ["ProjectSettings/ProjectSettings.asset", "ProjectSettings/Sub/Deep.asset",
                     "Packages/packages-lock.json", "UserSettings/EditorUserSettings.asset", "Game.csproj",
                     "Assembly-CSharp.csproj", "Game.sln", "Library/ScriptAssemblies/x.dll"]
        for path in generated:
            self.assertTrue(mps.is_generated_path(path, self.UNITY_AT_ROOT), path)
        real = ["Assets/Scripts/Login.cs", "Packages/manifest.json", "Docs/ProjectSettings.md",
                "ProjectSettingsBackup/x.asset", "src/Game.csproj.bak", "LibraryCode/a.cs"]
        for path in real:
            self.assertFalse(mps.is_generated_path(path, self.UNITY_AT_ROOT), path)

    def test_patterns_are_anchored_to_unity_roots(self):
        """G1: a folder that merely has the same name deeper down is real work."""
        for path in ("Assets/Plugins/Library/Core.cs", "Assets/Editor/ProjectSettings/Tool.cs",
                     "Assets/Scripts/Game.csproj", "Tools/Build.sln"):
            self.assertFalse(mps.is_generated_path(path, self.UNITY_AT_ROOT), path)

    def test_nested_unity_project_and_windows_paths(self):
        rules = mps.generated_rules(["Client/Game"], [])
        self.assertTrue(mps.is_generated_path("Client/Game/ProjectSettings/TagManager.asset", rules))
        self.assertTrue(mps.is_generated_path("Client\\Game\\Packages\\packages-lock.json", rules))
        self.assertTrue(mps.is_generated_path("Client/Game/Game.csproj", rules))
        self.assertFalse(mps.is_generated_path("Client/Game/Assets/a.cs", rules))
        self.assertFalse(mps.is_generated_path("ProjectSettings/TagManager.asset", rules))  # repo root is not Unity
        self.assertFalse(mps.is_generated_path("Server/Server.csproj", rules))

    def test_no_unity_project_means_no_defaults(self):
        rules = mps.generated_rules([], [])
        self.assertEqual(rules, [])
        self.assertFalse(mps.is_generated_path("Server.sln", rules))
        self.assertFalse(mps.is_generated_path("ProjectSettings/x.asset", rules))

    def test_user_patterns_are_validated(self):
        """G2: wildcard-only or wildcard-first patterns are rejected."""
        valid, rejected = mps.parse_generated_patterns(
            " Assets/Gen/** , *, **, **/*, */**, /, *.lock, */Gen/**, ?x/y, yarn.lock, Assets\\Data\\*.json,")
        self.assertEqual(valid, ["Assets/Gen/**", "yarn.lock", "Assets/Data/*.json"])
        self.assertEqual(rejected, ["*", "**", "**/*", "*/**", "/", "*.lock", "*/Gen/**", "?x/y"])
        self.assertEqual(mps.parse_generated_patterns(None), ([], []))
        rules = mps.generated_rules([], valid)  # extra patterns apply even without a Unity project
        self.assertTrue(mps.is_generated_path("Assets/Gen/a/b.cs", rules))
        self.assertTrue(mps.is_generated_path("yarn.lock", rules))
        self.assertFalse(mps.is_generated_path("web/yarn.lock", rules))
        self.assertTrue(mps.is_generated_path("Assets/Data/settings.json", rules))
        self.assertFalse(mps.is_generated_path("Assets/Data/Sub/settings.json", rules))
        self.assertIn("MPS_GENERATED_PATTERNS", mps.KNOWN_KEYS)


GIT = shutil.which("git")
LARGE_FILE_BYTES = mps.MAX_FILE_BYTES + 1024


class FakeService(object):
    """Stands in for ServiceClient: routes (method, path) to canned JSON and records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.params = []  # (method, path, params) of every call, to check query parameters

    def request(self, method, path, params=None, body=None, allow_statuses=()):
        self.calls.append((method, path, body))
        self.params.append((method, path, params))
        if (method, path) not in self.routes:
            raise AssertionError("unexpected call %s %s" % (method, path))
        status, data = self.routes[(method, path)]
        if status >= 400 and status not in allow_statuses:
            raise mps.MpsError("http_error", "fake %d" % status, status=status)
        return mps.HttpResponse(status, data, {})

    def get(self, path, params=None):
        return self.request("GET", path, params=params).data


class FakeMrGitLab(object):
    """A GitLab project (grp/proj, id 1) with labels and merge requests that POST / PUT really change.

    reject_extras: the POST is refused (400) while it carries assignee_ids or labels.
    race_status: another open MR for the branch appears just before the POST, which GitLab refuses with this status.
    notes_status: the HTTP status GitLab answers to a new MR note (comment).
    """

    def __init__(self, labels=("Enhancement", "Bug"), mrs=(), reject_extras=False, race_status=None, notes_status=201):
        self.user = {"id": 7, "username": "hung"}
        self.labels = [{"name": name} for name in labels]
        self.mrs = [dict(mr) for mr in mrs]
        self.reject_extras = reject_extras
        self.race_status = race_status
        self.notes_status = notes_status
        self.notes = []
        self.calls = []

    def respond(self, status, data):
        return mps.HttpResponse(status, json.loads(json.dumps(data)), {})

    def find_mr(self, path):
        return [mr for mr in self.mrs if "/merge_requests/%s" % mr["iid"] == path[len("/projects/1"):]][0]

    def request(self, method, path, params=None, body=None, allow_statuses=()):
        self.calls.append((method, path, body))
        if (method, path) == ("GET", "/projects/grp%2Fproj"):
            return self.respond(200, {"id": 1, "path_with_namespace": "grp/proj", "web_url": "u"})
        if (method, path) == ("GET", "/user"):
            return self.respond(200, self.user)
        if (method, path) == ("GET", "/projects/1/labels"):
            assert params["include_ancestor_groups"] == "true"
            wanted = params["search"].lower()
            return self.respond(200, [label for label in self.labels if wanted in label["name"].lower()])
        if (method, path) == ("GET", "/projects/1/merge_requests"):
            return self.respond(200, [mr for mr in self.mrs if mr["source_branch"] == params["source_branch"]])
        if (method, path) == ("POST", "/projects/1/merge_requests"):
            if self.race_status:
                self.mrs.append({"iid": 9, "web_url": "u", "title": "t", "source_branch": body["source_branch"],
                                 "target_branch": body["target_branch"], "state": "opened", "labels": [],
                                 "assignees": []})
                return self.respond(self.race_status, {"message": ["Another open merge request already exists"]})
            if self.reject_extras and ("labels" in body or "assignee_ids" in body):
                return self.respond(400, {"message": "invalid assignee or label"})
            mr = {"iid": len(self.mrs) + 1, "web_url": "https://git.example/mr", "title": body["title"],
                  "description": body["description"], "source_branch": body["source_branch"],
                  "target_branch": body["target_branch"], "state": "opened",
                  "labels": [body["labels"]] if body.get("labels") else [],
                  "assignees": [self.user] if body.get("assignee_ids") == [self.user["id"]] else []}
            self.mrs.append(mr)
            return self.respond(201, mr)
        if method == "POST" and path.startswith("/projects/1/merge_requests/") and path.endswith("/notes"):
            if self.notes_status >= 400 and self.notes_status not in allow_statuses:
                raise mps.MpsError("server_error", "fake %d" % self.notes_status, status=self.notes_status)
            self.notes.append((path, body["body"]))
            return self.respond(self.notes_status, {"id": len(self.notes)})
        if method == "PUT" and path.startswith("/projects/1/merge_requests/"):
            mr = self.find_mr(path)
            if "assignee_ids" in body:
                mr["assignees"] = [self.user]
            if "add_labels" in body:
                mr["labels"] = mr["labels"] + [body["add_labels"]]
            return self.respond(200, mr)
        raise AssertionError("unexpected call %s %s" % (method, path))

    def get(self, path, params=None):
        return self.request("GET", path, params=params).data

    def bodies(self, method):
        return [call[2] for call in self.calls if call[0] == method]


def fake_gitlab(release_branches):
    return FakeService({
        ("GET", "/projects/grp%2Fproj"): (200, {"id": 1, "path_with_namespace": "grp/proj", "web_url": "u"}),
        ("GET", "/projects/1/repository/branches"): (200, [{"name": n, "commit": {"committed_date": None}}
                                                           for n in release_branches]),
    })


SPRINT_12 = {"id": 12, "name": "Sprint 12", "state": "active", "startDate": "2026-11-02T09:00:00.000+07:00",
             "endDate": "2026-11-15T18:00:00.000+07:00", "originBoardId": 5, "goal": "Ra mắt event"}
SPRINT_13 = {"id": 13, "name": "Art Sprint 3", "state": "active", "originBoardId": 6}


def fake_jira(boards=None, sprints_by_board=None, move_status=204):
    """Jira with Story (id 10) and Bug (id 11). boards=None: no Scrum board at all; an int: the agile API refuses."""
    story_fields = [{"fieldId": "summary", "name": "Summary", "required": True},
                    {"fieldId": "assignee", "name": "Assignee", "required": False}]
    routes = {
        ("GET", "/rest/api/2/myself"): (200, {"name": "hung"}),
        ("GET", "/rest/api/2/project"): (200, [{"key": "MPS", "name": "Game"}, {"key": "ART", "name": "Artist"}]),
        ("GET", "/rest/api/2/project/ART"): (200, {"key": "ART", "name": "Artist"}),
        ("GET", "/rest/api/2/project/NOPE"): (404, None),
        ("POST", "/rest/api/2/issue"): (201, {"key": "ART-1"}),
    }
    for project in ("ART", "MPS"):
        base = "/rest/api/2/issue/createmeta/%s/issuetypes" % project
        routes[("GET", base)] = (200, {"values": [{"id": "10", "name": "Story"}, {"id": "11", "name": "Bug"}],
                                       "isLast": True})
        routes[("GET", base + "/10")] = (200, {"values": story_fields, "isLast": True})
        routes[("GET", base + "/11")] = (200, {"values": story_fields, "isLast": True})
    if isinstance(boards, int):
        routes[("GET", "/rest/agile/1.0/board")] = (boards, {"errorMessages": ["refused"]})
    else:
        routes[("GET", "/rest/agile/1.0/board")] = (200, {"values": boards or [], "isLast": True})
    for board_id, sprints in (sprints_by_board or {}).items():
        if isinstance(sprints, int):  # e.g. 400: "The board does not support sprints"
            routes[("GET", "/rest/agile/1.0/board/%s/sprint" % board_id)] = (sprints, {"errorMessages": ["no"]})
        else:
            routes[("GET", "/rest/agile/1.0/board/%s/sprint" % board_id)] = (200, {"values": sprints,
                                                                                  "isLast": True})
    for sprint_id in (12, 13):
        routes[("POST", "/rest/agile/1.0/sprint/%d/issue" % sprint_id)] = (move_status, None)
    return FakeService(routes)


def _rmtree(path):
    # git marks object files read-only, which rmtree cannot delete on Windows.
    for folder, _, files in os.walk(path):
        for name in files:
            try:
                os.chmod(os.path.join(folder, name), stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


@unittest.skipIf(GIT is None, "git is not installed")
class GitFlowTests(unittest.TestCase):
    """End-to-end git behaviour against a local bare origin (offline). Calls mps.main() in-process."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mps-test-")
        self.addCleanup(_rmtree, self.tmp)
        self.addCleanup(os.chdir, os.getcwd())
        empty_config = os.path.join(self.tmp, "empty.gitconfig")
        open(empty_config, "w").close()
        # The machine's own Claude Code plugin registry must not decide whether commands run (plugin_source_legacy).
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": empty_config, "GIT_CONFIG_NOSYSTEM": "1",
                                           mps.PLUGINS_DIR_ENV: os.path.join(self.tmp, "no-plugins")})
        env.start()
        self.addCleanup(env.stop)
        self.origin = os.path.join(self.tmp, "origin.git")
        self.repo = os.path.join(self.tmp, "repo")
        self.other = os.path.join(self.tmp, "other")
        self.git("init", "--bare", "-b", "develop", self.origin, cwd=self.tmp)
        self.git("clone", "-q", self.origin, self.repo, cwd=self.tmp)
        self.set_identity(self.repo)
        self.write("app.txt", "line1\nline2\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "init")
        self.git("push", "-q", "-u", "origin", "develop")
        self.git("push", "-q", "origin", "develop:release/1.0")
        self.write("feature.txt", "unreleased\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "feat: MPS-5 unreleased feature")
        self.git("push", "-q")
        os.chdir(self.repo)

    # -- helpers ---------------------------------------------------------

    def git(self, *args, cwd=None):
        return subprocess.run(["git"] + list(args), cwd=cwd or self.repo, check=True, capture_output=True,
                              encoding="utf-8").stdout

    def set_identity(self, path):
        self.git("config", "user.name", "Tester", cwd=path)
        self.git("config", "user.email", "tester@example.com", cwd=path)

    def write(self, path, text, root=None):
        full = os.path.join(root or self.repo, path)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    def read(self, path):
        with open(os.path.join(self.repo, path), encoding="utf-8") as handle:
            return handle.read()

    def mps(self, *argv):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="utf-8")
        with mock.patch.object(sys, "stdout", stream):
            code = mps.main(list(argv))
        stream.flush()
        result = json.loads(buffer.getvalue().decode("utf-8"))
        self.assertEqual(result["ok"], code == 0, result)
        return result

    def push_upstream(self, branch, path, text, message):
        if not os.path.isdir(self.other):
            self.git("clone", "-q", self.origin, self.other, cwd=self.tmp)
            self.set_identity(self.other)
        self.git("fetch", "-q", cwd=self.other)
        self.git("switch", "-q", "-C", branch, "origin/" + branch, cwd=self.other)
        self.write(path, text, root=self.other)
        self.git("add", ".", cwd=self.other)
        self.git("commit", "-q", "-m", message, cwd=self.other)
        self.git("push", "-q", "origin", branch, cwd=self.other)

    def prepare(self, branch, key, base="develop", *extra):
        return self.mps("git", "prepare-branch", "--base", base, "--branch", branch, "--key", key, *extra)

    def make_bundle(self, base="develop"):
        return self.mps("git", "diff-for-review", "--base=" + base, "--to-file")["bundle_id"]

    def write_reply(self, bundle_id, in_scope, out_of_scope=(), mixed=(), concern=(), verdict="PASS", name="review"):
        """A scope reviewer's reply in the required format; bundle_id/verdict None leave that line out."""
        lines = ["FILES:"]
        for category, paths in (("in_scope", in_scope), ("out_of_scope", out_of_scope), ("mixed", mixed),
                                ("concern", concern)):
            lines.extend("%s: %s" % (category, path) for path in paths)
        if bundle_id:
            lines.append("BUNDLE: " + bundle_id)
        if verdict:
            lines.append("VERDICT: " + verdict)
        reply = os.path.join(mps.mps_tmp_dir(self.repo), name + ".txt")
        with open(reply, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return reply

    def classify(self, reply, base="develop"):
        return self.mps("review", "classify", "--base=" + base, "--result-file=" + reply)

    def approve_scope_only(self, in_scope, base="develop", **reply_args):
        """diff-for-review, a reviewer reply for that bundle, then `review classify` (writes scope.json)."""
        bundle_id = self.make_bundle(base)
        return self.classify(self.write_reply(bundle_id, in_scope, **reply_args), base)

    def approve(self, in_scope, base="develop", code_findings=(), **reply_args):
        """Both reviews of one bundle: the scope review (returns its classify result) and a code review with
        `code_findings` (`FINDINGS: none` by default)."""
        bundle_id = self.make_bundle(base)
        result = self.classify(self.write_reply(bundle_id, in_scope, **reply_args), base)
        self.review_code(bundle_id, code_findings, base)
        return result

    def write_code_reply(self, bundle_id, findings=(), name="code_review"):
        """A code reviewer's reply: `FINDINGS: none` (or the finding lines), then `BUNDLE:` (None leaves it out)."""
        lines = ["### Kết quả review code", "", "FINDINGS:" if findings else "FINDINGS: none"] + list(findings)
        if bundle_id:
            lines.append("BUNDLE: " + bundle_id)
        reply = os.path.join(mps.mps_tmp_dir(self.repo), name + ".txt")
        with open(reply, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return reply

    def review_code(self, bundle_id, findings=(), base="develop"):
        """`review findings` for a code reviewer reply (writes code_review.json)."""
        reply = self.write_code_reply(bundle_id, findings)
        return self.mps("review", "findings", "--base=" + base, "--result-file=" + reply)

    def commit(self, message, *files):
        return self.mps("git", "commit", "--message=" + message, "--files", *files)

    def write_env(self, **values):
        self.write(".env", "".join("%s=%s\n" % item for item in values.items()))
        self.write(".gitignore", ".env\n")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "chore: ignore env")
        self.git("push", "-q", "origin", "HEAD")

    def head(self):
        return self.git("rev-parse", "HEAD").strip()

    # -- C1 --------------------------------------------------------------

    def test_stash_conflict_blocks_rerun_commit_and_preflight(self):
        self.push_upstream("develop", "app.txt", "line1\nline2 upstream\n", "upstream edit")
        self.write("app.txt", "line1\nline2 mine\n")
        conflict = self.prepare("feature/MPS-1-x", "MPS-1")
        self.assertEqual(conflict["error"], "stash_conflict")
        self.assertIn("mps-auto", self.git("stash", "list"))
        self.assertEqual(self.prepare("feature/MPS-1-x", "MPS-1")["error"], "unmerged_files")
        before = self.head()
        self.assertEqual(self.mps("git", "commit", "--message=feat: MPS-1 x", "--files", "app.txt")["error"],
                         "unmerged_files")
        self.assertEqual(self.head(), before)
        preflight = self.mps("git", "preflight", "--base", "develop")
        self.assertIn("unmerged_files", [b["code"] for b in preflight["blockers"]])

    # -- C2 --------------------------------------------------------------

    def test_commit_never_includes_env_files_or_secrets(self):
        self.prepare("feature/MPS-1-x", "MPS-1")
        self.write("cfg/app.ini", "a=1\n")
        self.write("cfg/.env.local", "MPS_GITLAB_PAT=glpat-abcdefghijklmnop\n")
        self.write("cfg/token.py", "GITLAB = 'glpat-abcdefghijklmnop'\n")
        before = self.head()
        for files in (["cfg"], ["."], ["./"], ["cfg/typo.ini"]):
            result = self.commit("feat: MPS-1 x", *files)
            self.assertEqual(result["error"], "explicit_files_required")
            self.assertEqual(self.head(), before)
        self.assertEqual(self.commit("x", "cfg/.env.local")["error"], "env_file")
        approved = self.approve(["cfg/app.ini", "cfg/token.py"])
        self.assertEqual(approved["files_to_classify"], ["cfg/app.ini", "cfg/token.py"])  # .env never offered
        # A .env staged earlier (e.g. by an IDE) is caught too, and nothing is committed.
        self.git("add", "-f", "cfg/.env.local")
        result = self.commit("feat: MPS-1 x", "cfg/app.ini")
        self.assertEqual(result["error"], "env_file")
        self.assertEqual(result["files"], ["cfg/.env.local"])
        self.assertEqual(self.head(), before)
        self.assertEqual(self.git("diff", "--cached", "--name-only").strip(), "")
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "cfg", ".env.local")))
        result = self.commit("feat: MPS-1 x", "cfg/token.py")
        self.assertEqual(result["error"], "secret_detected")
        self.assertEqual(self.head(), before)
        ok = self.commit("feat: MPS-1 x", "cfg/app.ini")
        self.assertEqual(ok["files"], ["A\tcfg/app.ini"])
        self.assertEqual(sorted(ok["left_uncommitted"]), ["cfg/.env.local", "cfg/token.py"])

    def test_push_checks_every_commit_for_env_files_and_secrets(self):
        self.prepare("feature/MPS-1-x", "MPS-1")
        self.write(".env.local", "X=1\n")
        self.git("add", "-f", ".env.local")
        self.git("commit", "-q", "-m", "feat: MPS-1 sneaky env")
        self.write("later.txt", "fine\n")
        self.git("add", "later.txt")
        self.git("commit", "-q", "-m", "feat: MPS-1 later")
        result = self.mps("git", "push", "--branch", "feature/MPS-1-x", "--base", "develop")
        self.assertEqual(result["error"], "env_file")
        self.git("rm", "-q", "--cached", ".env.local")
        self.write("key.pem", "-----BEGIN RSA PRIVATE KEY-----\n")
        self.git("add", "key.pem")
        self.git("commit", "-q", "-m", "feat: MPS-1 key")
        # The branch is pushed as ONE commit: the .env removed by a later commit is not published any more, but the
        # key in the final content still is, and blocks.
        self.assertEqual(self.mps("git", "push", "--branch", "feature/MPS-1-x", "--base", "develop")["error"],
                         "secret_detected")
        self.assertEqual(self.git("ls-remote", "--heads", "origin", "feature/MPS-1-x").strip(), "")
        self.assertEqual(self.git("for-each-ref", mps.BACKUP_REF_PREFIX).strip(), "")  # refused before any rewrite

    # -- one commit per merge request, rebase instead of merge commits ----

    def remote_commits(self, branch, base="develop"):
        self.git("fetch", "-q", "origin")
        return self.git("rev-list", "origin/%s..origin/%s" % (base, branch)).split()

    def commit_file(self, path, text, message, cwd=None):
        self.write(path, text, root=cwd)
        self.git("add", path, cwd=cwd)
        self.git("commit", "-q", "-m", message, cwd=cwd)

    def push(self, branch, *extra):
        return self.mps("git", "push", "--branch=" + branch, "--base=develop", *extra)

    def test_push_squashes_own_commits_into_one_rebased_commit(self):
        branch = "feature/MPS-90-a"
        self.prepare(branch, "MPS-90")
        self.commit_file("a.txt", "a\n", "feat: MPS-90 a")
        # The pattern from the team's history: develop merged INTO the ticket branch, plus an AI-attributed commit.
        self.push_upstream("develop", "dev1.txt", "1\n", "feat: MPS-91 other work")
        self.git("fetch", "-q", "origin")
        self.git("merge", "-q", "--no-edit", "origin/develop")
        self.commit_file("b.txt", "b\n", "wip\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
        self.push_upstream("develop", "dev2.txt", "2\n", "feat: MPS-92 more work")
        old_head = self.head()
        pushed = self.push(branch, "--message=feat: MPS-90 Tính năng A")
        self.assertEqual((pushed["rewrite"], pushed["commits_combined"], pushed["rebased"], pushed["forced"]),
                         ("squashed", 3, True, False))
        commits = self.remote_commits(branch)
        self.assertEqual(commits, [pushed["pushed_commit"]])
        self.assertEqual(self.git("rev-parse", commits[0] + "^").strip(), self.git("rev-parse", "origin/develop").strip())
        self.assertEqual(self.git("log", "-1", "--format=%B", commits[0]).strip(), "feat: MPS-90 Tính năng A")
        self.assertEqual(sorted(self.git("show", "--name-only", "--format=", commits[0]).split()), ["a.txt", "b.txt"])
        self.assertEqual(self.head(), commits[0])
        self.assertEqual(self.read("dev2.txt"), "2\n")  # the rebase brought the base's new work into the work tree
        self.assertEqual(self.git("rev-parse", pushed["backup_ref"]).strip(), old_head)  # nothing is lost
        self.assertEqual(self.git("rev-list", "--merges", "origin/develop.." + branch).strip(), "")

    def test_review_fix_is_folded_in_with_a_lease_protected_force_push(self):
        branch = "feature/MPS-93-a"
        self.prepare(branch, "MPS-93")
        self.commit_file("a.txt", "a\n", "feat: MPS-93 a")
        first = self.push(branch)
        self.assertEqual((first["rewrite"], first["forced"], first["backup_ref"]), ("none", False, None))
        self.assertEqual(self.push(branch)["rewrite"], "none")  # already in shape: nothing rewritten again
        self.commit_file("a.txt", "a fixed after review\n", "feat: MPS-93 a")
        second = self.push(branch)
        self.assertEqual((second["rewrite"], second["commits_combined"], second["forced"]), ("squashed", 2, True))
        self.assertEqual(self.remote_commits(branch), [second["pushed_commit"]])
        self.assertEqual(self.git("show", "origin/%s:a.txt" % branch), "a fixed after review\n")
        # Someone pushed to the branch meanwhile: never overwritten, nothing changed here.
        self.push_upstream(branch, "x.txt", "x\n", "feat: MPS-93 colleague")
        self.commit_file("c.txt", "c\n", "feat: MPS-93 c")
        before = self.head()
        self.assertEqual(self.push(branch)["error"], "remote_branch_ahead")
        self.assertEqual(self.head(), before)
        self.assertEqual(len(self.remote_commits(branch)), 2)

    def test_lease_refuses_a_push_that_raced_with_a_colleague(self):
        branch = "feature/MPS-94-a"
        self.prepare(branch, "MPS-94")
        self.commit_file("a.txt", "a\n", "feat: MPS-94 a")
        self.push(branch)
        self.commit_file("b.txt", "b\n", "feat: MPS-94 a")
        real = mps.run_git_network

        def racing(root, args, cfg):
            if args[0] == "push":  # a colleague pushes between our fetch and our push
                self.push_upstream(branch, "x.txt", "x\n", "feat: MPS-94 colleague")
            return real(root, args, cfg)
        with mock.patch.object(mps, "run_git_network", side_effect=racing):
            raced = self.push(branch)
        self.assertEqual(raced["error"], "remote_branch_changed")
        self.assertTrue(raced["backup_ref"].startswith(mps.BACKUP_REF_PREFIX))
        self.git("fetch", "-q", "origin")
        self.assertIn("feat: MPS-94 colleague", self.git("log", "-1", "--format=%s", "origin/" + branch))

    def test_colleague_commits_are_amended_only_after_consent(self):
        branch = "feature/MPS-95-a"
        if not os.path.isdir(self.other):
            self.git("clone", "-q", self.origin, self.other, cwd=self.tmp)
        self.git("config", "user.name", "Colleague", cwd=self.other)
        self.git("config", "user.email", "colleague@example.com", cwd=self.other)
        self.git("switch", "-q", "-c", branch, "origin/develop", cwd=self.other)
        self.commit_file("x.txt", "x\n", "feat: MPS-95 Phần của đồng nghiệp", cwd=self.other)
        self.git("push", "-q", "origin", branch, cwd=self.other)
        theirs = self.git("rev-parse", "HEAD", cwd=self.other).strip()
        self.assertEqual(self.prepare(branch, "MPS-95")["action"], "created_tracking")
        self.commit_file("mine.txt", "m\n", "feat: MPS-95 Phần của tôi")
        before = self.head()
        asked = self.push(branch)
        self.assertEqual(asked["error"], "amend_confirmation_required")
        self.assertEqual(asked["other_authors"], ["Colleague <colleague@example.com>"])
        self.assertEqual(asked["last_commit"]["sha"], theirs)
        self.assertEqual((self.head(), self.remote_commits(branch)), (before, [theirs]))  # nothing changed yet
        amended = self.push(branch, "--amend-confirmed")
        self.assertEqual((amended["rewrite"], amended["forced"]), ("amended", True))
        commits = self.remote_commits(branch)
        self.assertEqual(commits, [amended["pushed_commit"]])
        self.assertEqual(self.git("log", "-1", "--format=%an|%cn|%s", commits[0]).strip(),
                         "Colleague|Tester|feat: MPS-95 Phần của đồng nghiệp")
        self.assertEqual(sorted(self.git("show", "--name-only", "--format=", commits[0]).split()),
                         ["mine.txt", "x.txt"])

    def test_rebase_is_skipped_instead_of_touching_local_changes_or_conflicting(self):
        branch = "feature/MPS-96-a"
        self.prepare(branch, "MPS-96")
        self.commit_file("a.txt", "a\n", "feat: MPS-96 a")
        merge_base = self.git("rev-parse", "origin/develop").strip()
        self.push_upstream("develop", "app.txt", "line1\nline2 upstream\n", "feat: MPS-97 upstream")
        self.write("app.txt", "line1\nline2 local edit\n")  # uncommitted, would be overwritten by the rebase
        local = self.push(branch)
        self.assertEqual((local["rebased"], local["rebase_skipped"]), (False, "local_changes"))
        self.assertEqual(self.git("rev-parse", local["pushed_commit"] + "^").strip(), merge_base)
        self.assertEqual(self.read("app.txt"), "line1\nline2 local edit\n")
        self.git("checkout", "-q", "--", "app.txt")
        self.commit_file("app.txt", "line1\nline2 mine\n", "feat: MPS-96 a")
        conflict = self.push(branch)
        self.assertEqual((conflict["rewrite"], conflict["rebased"], conflict["rebase_skipped"]),
                         ("squashed", False, "conflict"))
        self.assertEqual(self.remote_commits(branch), [conflict["pushed_commit"]])

    def test_merged_in_work_from_other_branches_is_never_squashed_in(self):
        # Unreleased develop work merged into a release bugfix branch must not ship as "fix: MPS-7".
        self.prepare("bugfix/MPS-7-x", "MPS-7", "release/1.0")
        self.commit_file("fix.txt", "fix\n", "fix: MPS-7 x")
        self.git("merge", "-q", "--no-edit", "origin/develop")
        refused = self.mps("git", "push", "--branch=bugfix/MPS-7-x", "--base=release/1.0")
        self.assertEqual(refused["error"], "merged_foreign_work")
        self.assertEqual([c["subject"] for c in refused["commits"]], ["feat: MPS-5 unreleased feature"])
        self.assertEqual(self.git("ls-remote", "--heads", "origin", "bugfix/MPS-7-x").strip(), "")
        # A colleague's ticket branch merged into mine: their work never lands in my MR under my name.
        self.git("switch", "-q", "develop")
        self.git("clone", "-q", self.origin, self.other, cwd=self.tmp)
        self.set_identity(self.other)
        self.git("switch", "-q", "-c", "feature/MPS-8-y", "origin/develop", cwd=self.other)
        self.commit_file("y.txt", "y\n", "feat: MPS-8 y", cwd=self.other)
        self.git("push", "-q", "origin", "feature/MPS-8-y", cwd=self.other)
        self.prepare("feature/MPS-98-a", "MPS-98")
        self.commit_file("a.txt", "a\n", "feat: MPS-98 a")
        self.git("fetch", "-q", "origin")
        self.git("merge", "-q", "--no-edit", "origin/feature/MPS-8-y")
        self.assertEqual(self.push("feature/MPS-98-a")["error"], "merged_foreign_work")
        # A local commit written by someone else is not folded in silently either.
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.write("z.txt", "z\n")
        self.git("add", "z.txt")
        self.git("commit", "-q", "--author=Someone <someone@example.com>", "-m", "feat: MPS-98 z")
        foreign = self.push("feature/MPS-98-a")
        self.assertEqual((foreign["error"], foreign["other_authors"]),
                         ("foreign_author_commits", ["Someone <someone@example.com>"]))

    def test_failed_push_after_the_rewrite_is_resumed(self):
        branch = "feature/MPS-99-a"
        self.prepare(branch, "MPS-99")
        self.commit_file("a.txt", "a\n", "feat: MPS-99 a")
        self.push(branch)
        self.commit_file("b.txt", "b\n", "feat: MPS-99 a")
        real = mps.run_git_network

        def offline(root, args, cfg):
            if args[0] == "push":
                return mps.GitResult(128, "", "fatal: unable to access 'https://git/': Could not resolve host: git"), \
                    False
            return real(root, args, cfg)
        with mock.patch.object(mps, "run_git_network", side_effect=offline):
            failed = self.push(branch)
        self.assertEqual(failed["error"], "network_unreachable")
        self.assertEqual(len(self.git("rev-list", "origin/develop.." + branch).split()), 1)  # rewritten locally
        retried = self.push(branch)  # same command again, once the VPN is back
        self.assertEqual((retried["ok"], retried["resumed"], retried["forced"]), (True, True, True))
        self.assertEqual(self.remote_commits(branch), [retried["pushed_commit"]])
        pending = subprocess.run(["git", "config", "--local", "--get-regexp", "mps-rewrite"], cwd=self.repo,
                                 capture_output=True, encoding="utf-8").stdout
        self.assertEqual(pending.strip(), "")  # the pending-rewrite note is cleared after a successful push
        # Failed again, then one more commit before the retry: still one commit, nothing lost.
        self.commit_file("c.txt", "c\n", "feat: MPS-99 a")
        with mock.patch.object(mps, "run_git_network", side_effect=offline):
            self.assertEqual(self.push(branch)["error"], "network_unreachable")
        self.commit_file("d.txt", "d\n", "feat: MPS-99 a")
        again = self.push(branch)
        self.assertEqual((again["resumed"], again["forced"]), (True, True))
        commits = self.remote_commits(branch)
        self.assertEqual(len(commits), 1)
        self.assertEqual(sorted(self.git("show", "--name-only", "--format=", commits[0]).split()),
                         ["a.txt", "b.txt", "c.txt", "d.txt"])

    def test_rebase_never_touches_untracked_ignored_or_staged_files(self):
        branch = "feature/MPS-100-a"
        self.prepare(branch, "MPS-100")
        self.commit_file("a.txt", "a\n", "feat: MPS-100 a")
        self.push_upstream("develop", "cfg/local.txt", "from develop\n", "feat: MPS-101 adds cfg/local.txt")
        self.write("cfg/local.txt", "MY LOCAL WORK\n")  # untracked here (ignored works the same)
        skipped = self.push(branch)
        self.assertEqual((skipped["rebased"], skipped["rebase_skipped"]), (False, "local_files"))
        self.assertEqual(self.read("cfg/local.txt"), "MY LOCAL WORK\n")
        os.remove(os.path.join(self.repo, "cfg", "local.txt"))
        self.write("app.txt", "line1\nstaged\n")
        self.git("add", "app.txt")
        staged = self.push(branch)
        self.assertEqual(staged["rebase_skipped"], "staged_changes")
        self.assertEqual(self.git("diff", "--cached", "--name-only").split(), ["app.txt"])  # still staged

    def test_half_updated_work_tree_stops_before_pushing(self):
        branch = "feature/MPS-102-a"
        self.prepare(branch, "MPS-102")
        self.commit_file("a.txt", "a\n", "feat: MPS-102 a")
        self.push_upstream("develop", "dev.txt", "d\n", "feat: MPS-103 upstream")
        before = self.head()
        real = mps.run_git

        def locked(args, cwd, **kwargs):
            if args[:2] == ["reset", "-q"] and "--keep" in args:  # e.g. Windows: a file held open by the editor
                with open(os.path.join(cwd, "dev.txt"), "w") as handle:
                    handle.write("d\n")
                return mps.GitResult(128, "", "error: unable to unlink old 'x': Permission denied")
            return real(args, cwd, **kwargs)
        with mock.patch.object(mps, "run_git", side_effect=locked):
            stopped = self.push(branch)
        self.assertEqual(stopped["error"], "rebase_partial")
        self.assertEqual(self.head(), before)
        self.assertEqual(self.git("rev-parse", stopped["backup_ref"]).strip(), before)
        self.assertEqual(self.git("ls-remote", "--heads", "origin", branch).strip(), "")

    def test_amend_never_targets_a_commit_without_the_ticket_key(self):
        branch = "feature/MPS-104-a"
        self.git("clone", "-q", self.origin, self.other, cwd=self.tmp)
        self.git("config", "user.name", "Tester", cwd=self.other)  # same name, another email (e.g. a 2nd laptop)
        self.git("config", "user.email", "tester@home.example", cwd=self.other)
        self.git("switch", "-q", "-c", branch, "origin/develop", cwd=self.other)
        self.commit_file("x.txt", "x\n", "feat: MPS-104 a", cwd=self.other)
        self.git("push", "-q", "origin", branch, cwd=self.other)
        self.prepare(branch, "MPS-104")
        self.commit_file("mine.txt", "m\n", "feat: MPS-104 a")
        asked = self.push(branch)
        self.assertEqual((asked["error"], asked["same_name_as_you"]), ("amend_confirmation_required", True))
        # A reviewer's suggestion applied on GitLab: no ticket key, someone else's name -> never amended into.
        self.commit_file("x.txt", "x suggested\n", "Apply 1 suggestion(s) to 1 file(s)", cwd=self.other)
        self.git("push", "-q", "origin", branch, cwd=self.other)
        self.git("fetch", "-q", "origin")
        self.git("reset", "-q", "--hard", "origin/" + branch)
        self.commit_file("mine.txt", "m\n", "feat: MPS-104 a")
        refused = self.push(branch, "--amend-confirmed")
        self.assertEqual(refused["error"], "amend_target_foreign")
        self.assertEqual(refused["last_commit"]["subject"], "Apply 1 suggestion(s) to 1 file(s)")

    def test_push_refuses_secret_and_review_bundle_hides_env(self):
        self.prepare("feature/MPS-1-x", "MPS-1")
        self.write("key.pem", "-----BEGIN RSA PRIVATE KEY-----\n")
        self.git("add", "key.pem")
        self.git("commit", "-q", "-m", "feat: MPS-1 key")
        result = self.mps("git", "push", "--branch", "feature/MPS-1-x", "--base", "develop")
        self.assertEqual(result["error"], "secret_detected")
        self.assertEqual(result["findings"][0]["rule"], "private_key")
        self.write("cfg/.env.local", "SECRET_VALUE_XYZ=1\n")
        review = self.mps("git", "diff-for-review", "--base", "develop", "--to-file")
        self.assertEqual(review["hidden_files"], ["cfg/.env.local"])
        with open(review["bundle_path"], encoding="utf-8") as handle:
            bundle = handle.read()
        self.assertIn("cfg/.env.local: [content hidden]", bundle)
        self.assertNotIn("SECRET_VALUE_XYZ", bundle)

    # -- C3 --------------------------------------------------------------

    def test_beta_refuses_dev_based_branch(self):
        self.prepare("bugfix/MPS-2-x", "MPS-2")
        self.write("fix.txt", "fix\n")
        self.approve(["fix.txt"])
        self.commit("fix: MPS-2 x", "fix.txt")
        # R3: the recorded base answers first ...
        self.assertEqual(self.prepare("bugfix/MPS-2-x", "MPS-2", "release/1.0")["error"], "base_mismatch")
        # ... and without a recorded base (e.g. branch made by hand) the foreign-commit check still catches it.
        self.git("config", "--unset", "branch.bugfix/MPS-2-x.mps-base")
        result = self.prepare("bugfix/MPS-2-x", "MPS-2", "release/1.0")
        self.assertEqual(result["error"], "branch_base_mismatch")
        self.assertEqual([c["subject"] for c in result["foreign_commits"]], ["feat: MPS-5 unreleased feature"])
        self.git("switch", "-q", "develop")
        self.assertEqual(self.prepare("bugfix/MPS-2-x", "MPS-2", "release/1.0")["error"], "branch_base_mismatch")
        self.assertEqual(self.git("branch", "--show-current").strip(), "develop")
        same = self.prepare("bugfix/MPS-2-x", "MPS-2")
        self.assertEqual((same["action"], same["base_recorded"]), ("switched_existing", True))
        self.assertEqual(mps.recorded_base(self.repo, "bugfix/MPS-2-x"), "develop")

    # -- M1 --------------------------------------------------------------

    def test_local_commits_not_carried(self):
        self.git("switch", "-q", "-c", "my-work")
        self.write("work.txt", "ide commit\n")
        self.git("add", "work.txt")
        self.git("commit", "-q", "-m", "work from IDE")
        preflight = self.mps("git", "preflight", "--base", "develop", "--branch", "feature/MPS-3-y")
        warning = [w for w in preflight["warnings"] if w["code"] == "local_commits_not_carried"]
        self.assertEqual(warning[0]["count"], 1)
        refused = self.prepare("feature/MPS-3-y", "MPS-3")
        self.assertEqual(refused["error"], "local_commits_not_carried")
        self.assertEqual(self.git("branch", "--show-current").strip(), "my-work")
        created = self.prepare("feature/MPS-3-y", "MPS-3", "develop", "--leave-commits")
        self.assertEqual((created["action"], created["commits_left_behind"]), ("created_from_base", 1))
        self.assertIn("work from IDE", self.git("log", "-1", "--format=%s", "my-work"))

    # -- M2 --------------------------------------------------------------

    def test_large_file_blocker_skips_lfs(self):
        self.write(".gitattributes", "*.bin filter=lfs diff=lfs merge=lfs -text\n")
        with open(os.path.join(self.repo, "asset.bin"), "wb") as handle:
            handle.write(b"x" * LARGE_FILE_BYTES)
        with open(os.path.join(self.repo, "dump.dat"), "wb") as handle:
            handle.write(b"x" * LARGE_FILE_BYTES)
        with open(os.path.join(self.repo, "texture.dat"), "wb") as handle:
            handle.write(b"x" * (LARGE_FILE_BYTES // 2))
        with mock.patch.object(mps, "LARGE_FILE_BLOCK_BYTES", LARGE_FILE_BYTES - 1024):
            preflight = self.mps("git", "preflight", "--base", "develop")
        large = [b for b in preflight["blockers"] if b["code"] == "large_file"][0]
        self.assertEqual([f["file"] for f in large["files"]], ["dump.dat"])

    def test_large_file_limit_is_above_review_read_limit(self):
        # Files over the review read limit (5MB) are still allowed up to the push limit (GitLab has no size limit).
        self.assertGreater(mps.LARGE_FILE_BLOCK_BYTES, mps.MAX_FILE_BYTES)
        with open(os.path.join(self.repo, "texture.dat"), "wb") as handle:
            handle.write(b"x" * (mps.MAX_FILE_BYTES + 1024))
        preflight = self.mps("git", "preflight", "--base", "develop")
        self.assertEqual([b for b in preflight["blockers"] if b["code"] == "large_file"], [])

    # -- M5 --------------------------------------------------------------

    def test_failed_switch_restores_stashed_changes(self):
        self.write("app.txt", "line1\nline2 dirty\n")
        self.write("new.txt", "untracked\n")
        with self.assertRaises(mps.MpsError) as ctx:
            mps._switch_with_stash(self.repo, ["switch", "no-such-branch"])
        self.assertEqual(ctx.exception.code, "switch_failed")
        self.assertEqual(self.read("app.txt"), "line1\nline2 dirty\n")
        self.assertEqual(self.read("new.txt"), "untracked\n")
        self.assertEqual(self.git("stash", "list").strip(), "")

    # -- M6 --------------------------------------------------------------

    def test_missing_git_identity(self):
        self.git("config", "--unset", "user.name")
        self.git("config", "--unset", "user.email")
        preflight = self.mps("git", "preflight")
        self.assertIn("missing_git_identity", [b["code"] for b in preflight["blockers"]])
        self.assertEqual(self.mps("git", "set-identity", "--name=Nguyễn Văn A", "--email", "a@example.com")["scope"],
                         "local")
        preflight = self.mps("git", "preflight")
        self.assertNotIn("missing_git_identity", [b["code"] for b in preflight["blockers"]])
        self.assertEqual(self.mps("git", "set-identity", "--name", "A", "--email", "bad")["error"], "invalid_identity")

    # -- resume + rename (m6) -------------------------------------------

    def test_resume_after_push_and_rename_commit(self):
        self.prepare("feature/MPS-4-z", "MPS-4")
        self.git("mv", "app.txt", "renamed.txt")
        self.assertEqual(self.approve(["renamed.txt"])["files_to_classify"], ["renamed.txt"])
        committed = self.commit("feat: MPS-4 Đổi tên", "renamed.txt")
        self.assertEqual(committed["files"], ["R100\tapp.txt\trenamed.txt"])
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "feat: MPS-4 Đổi tên")
        self.assertEqual(self.git("status", "--porcelain").strip(), "")
        self.mps("git", "push", "--branch", "feature/MPS-4-z", "--base", "develop")
        self.assertEqual(self.mps("git", "commit", "--message=feat: MPS-4 again", "--files", "renamed.txt")["error"],
                         "nothing_to_commit")
        self.assertEqual(self.prepare("feature/MPS-4-z", "MPS-4")["action"], "already_on_branch")
        self.assertTrue(self.mps("git", "push", "--branch", "feature/MPS-4-z", "--base", "develop")["ok"])

    # -- R2: explicit file lists, out-of-scope files stay on disk ----------

    def test_all_flag_is_gone(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="utf-8")
        with mock.patch.object(sys, "stdout", stream), self.assertRaises(SystemExit) as ctx:
            mps.main(["git", "commit", "--message=x", "--all"])
        stream.flush()
        self.assertEqual(ctx.exception.code, mps.EXIT_USAGE)
        self.assertEqual(json.loads(buffer.getvalue().decode("utf-8"))["error"], "usage_error")

    def test_out_of_scope_files_are_left_uncommitted(self):
        self.prepare("feature/MPS-6-login", "MPS-6")
        self.write("src/login.cs", "class Login {}\n")
        self.write("ProjectSettings/ProjectSettings.asset", "unity: regenerated\n")
        self.write("app.txt", "line1\nline2 edited by unity import\n")
        review = self.mps("git", "diff-for-review", "--base=develop", "--to-file")
        self.assertEqual(sorted(review["files_to_classify"]),
                         ["ProjectSettings/ProjectSettings.asset", "app.txt", "src/login.cs"])
        with open(review["bundle_path"], encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("## 0. Files to classify", text)
        self.assertIn("Bundle-ID: " + review["bundle_id"], text)
        reply = self.write_reply(review["bundle_id"], ["src/login.cs"],
                                 out_of_scope=["ProjectSettings/ProjectSettings.asset", "app.txt"], verdict="FAIL")
        classified = self.classify(reply)
        self.assertTrue(classified["complete"])
        self.assertEqual(classified["commit_files"], ["src/login.cs"])
        self.review_code(review["bundle_id"])
        # M1: an excluded file cannot slip into the commit just by being listed.
        sneaky = self.commit("feat: MPS-6 Login", "src/login.cs", "ProjectSettings/ProjectSettings.asset")
        self.assertEqual((sneaky["error"], sneaky["files"]), ("not_in_scope", ["ProjectSettings/ProjectSettings.asset"]))
        committed = self.commit("feat: MPS-6 Login", *classified["commit_files"])
        self.assertEqual(committed["files"], ["A\tsrc/login.cs"])
        self.assertEqual(sorted(committed["left_uncommitted"]), ["ProjectSettings/ProjectSettings.asset", "app.txt"])
        self.assertIn("unity import", self.read("app.txt"))
        self.assertNotIn("mps-tmp", self.git("status", "--porcelain", "-uall"))
        self.assertFalse(os.path.exists(mps.scope_path(self.repo)))  # one review approves one commit
        self.assertFalse(os.path.exists(mps.code_review_path(self.repo)))
        self.assertEqual(mps._read_json(mps.committed_review_path(self.repo))["committed_as"], self.head())

    # -- R3: recorded base, base_mismatch, MR guard, phase detection --------

    def test_recorded_base_and_mismatch(self):
        created = self.prepare("bugfix/MPS-7-x", "MPS-7", "release/1.0")
        self.assertEqual((created["action"], created["base_recorded"]), ("created_from_base", True))
        self.assertEqual(self.git("config", "--local", "--get", "branch.bugfix/MPS-7-x.mps-base").strip(),
                         "release/1.0")
        mismatch = self.prepare("bugfix/MPS-7-x", "MPS-7", "develop")
        self.assertEqual((mismatch["error"], mismatch["recorded_base"]), ("base_mismatch", "release/1.0"))
        self.write("fix.txt", "fix\n")
        self.approve(["fix.txt"], base="release/1.0")
        self.commit("fix: MPS-7 x", "fix.txt")
        self.assertEqual(self.mps("git", "push", "--branch=bugfix/MPS-7-x", "--base=develop")["error"], "base_mismatch")
        self.assertEqual(self.mps("git", "push", "--branch=bugfix/MPS-7-x", "--base=feature/x")["error"],
                         "invalid_base")
        self.assertEqual(self.prepare("bugfix/MPS-7-x", "MPS-7", "my-work")["error"], "invalid_base")
        preflight = self.mps("git", "preflight")
        self.assertEqual((preflight["current_branch_role"], preflight["recorded_base"], preflight["detected_phase"]),
                         ("ticket", "release/1.0", "beta"))

    def guard_error(self, *args):
        with self.assertRaises(mps.MpsError) as ctx:
            mps.ensure_mr_target(self.repo, *args)
        return ctx.exception.code

    def test_mr_guard(self):
        self.prepare("feature/MPS-8-y", "MPS-8")
        self.write("y.txt", "y\n")
        self.approve(["y.txt"])
        self.commit("feat: MPS-8 y", "y.txt")
        self.assertEqual(mps.ensure_mr_target(self.repo, "feature/MPS-8-y", "develop", "MPS-8", BRANCHES), "develop")
        self.assertEqual(self.guard_error("feature/MPS-8-y", "release/1.0", "MPS-8", BRANCHES),
                         "target_mismatch_recorded_base")
        self.assertEqual(self.guard_error("feature/MPS-8-y", "feature/x", "MPS-8", BRANCHES), "invalid_base")
        self.assertEqual(self.guard_error("feature/MPS-0-none", "develop", "MPS-8", BRANCHES), "branch_not_found")
        # m2: without a recorded base the target must be the closest protected branch ...
        self.git("config", "--unset", "branch.feature/MPS-8-y.mps-base")
        self.assertEqual(self.guard_error("feature/MPS-8-y", "release/9.9", "MPS-8", BRANCHES), "base_not_found")
        self.assertEqual(self.guard_error("feature/MPS-8-y", "release/1.0", "MPS-8", BRANCHES),
                         "target_mismatch_inferred_base")
        self.assertIsNone(mps.ensure_mr_target(self.repo, "feature/MPS-8-y", "develop", "MPS-8", BRANCHES))
        # ... and every commit must belong to the ticket.
        self.assertEqual(self.guard_error("feature/MPS-8-y", "develop", "MPS-9", BRANCHES), "branch_base_mismatch")
        # ... checked on the pushed branch when there is one (that is what the MR contains).
        self.mps("git", "push", "--branch=feature/MPS-8-y", "--base=develop")
        self.git("commit", "-q", "--allow-empty", "-m", "local only, not pushed")
        self.assertIsNone(mps.ensure_mr_target(self.repo, "feature/MPS-8-y", "develop", "MPS-8", BRANCHES))
        # The CLI applies the guard before any GitLab call (none is configured here).
        refused = self.mps("mr", "ensure", "--source=feature/MPS-8-y", "--target=release/1.0", "--title=t",
                           "--description=Close MPS-8", "--key=MPS-8", "--type=bug")
        self.assertEqual(refused["error"], "target_mismatch_inferred_base")
        # m3: a Story can never go into a release branch, whatever the branches say.
        story = self.mps("mr", "ensure", "--source=feature/MPS-8-y", "--target=release/1.0", "--title=t",
                         "--description=Close MPS-8", "--key=MPS-8", "--type=story")
        self.assertEqual(story["error"], "phase_rule_violation")

    def plan(self, *args):
        return self.mps("flow", "plan", *args)

    def test_flow_plan_dirty_tree_and_ticket_branch(self):
        # M2: a clean develop does not pin the phase; the user's choice wins.
        self.assertEqual(self.plan("--type=story", "--key=MPS-9")["error"], "phase_required")
        clean = self.plan("--type=story", "--key=MPS-9", "--phase=dev")
        self.assertEqual((clean["phase"], clean["phase_source"]), ("dev", "requested_clean_tree"))
        self.write("wip.txt", "work\n")
        dirty = self.plan("--type=story", "--key=MPS-9")
        self.assertEqual((dirty["phase"], dirty["phase_source"], dirty["target_branch"]), ("dev", "detected", "develop"))
        self.assertEqual(self.plan("--type=bug", "--key=MPS-9", "--phase=production")["error"], "phase_conflict")
        os.remove(os.path.join(self.repo, "wip.txt"))
        # The current ticket's own branch pins its recorded base even when clean.
        self.prepare("bugfix/MPS-9-z", "MPS-9", "release/1.0")
        self.assertEqual(self.plan("--type=bug", "--key=MPS-9", "--phase=dev")["error"], "phase_conflict")
        self.assertEqual(self.plan("--type=story", "--key=MPS-9")["error"], "phase_rule_violation")
        # M3c: another ticket's branch does not pin anything.
        other = self.plan("--type=bug", "--key=MPS-10", "--phase=dev")
        self.assertEqual((other["phase"], other["current_branch_role"]), ("dev", "other"))
        self.assertIn("other_ticket_branch", [w["code"] for w in other["warnings"]])
        self.git("switch", "-q", "-c", "my-work")
        self.assertEqual(self.plan("--type=bug", "--key=MPS-9")["error"], "phase_required")

    def test_flow_plan_recorded_base_gone(self):
        self.git("push", "-q", "origin", "develop:release/2.0")
        self.prepare("bugfix/MPS-11-x", "MPS-11", "release/2.0")
        self.git("push", "-q", "origin", "--delete", "release/2.0")
        self.git("update-ref", "refs/remotes/origin/release/2.0", "HEAD")  # stale local ref: the pruned fetch clears it
        clean = self.plan("--type=bug", "--key=MPS-11", "--phase=dev")
        self.assertEqual((clean["phase"], clean["current_branch_role"]), ("dev", "other"))
        self.assertIn("recorded_base_gone", [w["code"] for w in clean["warnings"]])
        self.assertFalse(mps.ref_exists(self.repo, "refs/remotes/origin/release/2.0"))
        self.write("wip.txt", "work\n")
        self.assertEqual(self.plan("--type=bug", "--key=MPS-11", "--phase=dev")["error"], "recorded_base_gone")

    def test_flow_plan_detached_head(self):
        self.git("switch", "-q", "--detach", "origin/develop")
        self.write("wip.txt", "work\n")
        plan = self.plan("--type=bug", "--key=MPS-12")
        self.assertEqual((plan["phase"], plan["base_branch"], plan["detached"]), ("dev", "develop", True))
        self.git("commit", "-q", "--allow-empty", "-m", "detached work")  # a commit no origin branch points at
        self.assertEqual(self.plan("--type=bug", "--key=MPS-12", "--phase=dev")["error"], "detached_head")

    def test_flow_plan_beta_with_mocked_gitlab(self):
        self.write_env(MPS_GITLAB_URL="https://git.example", MPS_GITLAB_PAT="x", MPS_GITLAB_PROJECT="grp/proj")
        with mock.patch.object(mps, "gitlab_client", return_value=fake_gitlab(["release/1.0", "release/1.1"])):
            latest = self.plan("--type=bug", "--key=MPS-13", "--phase=beta")
            self.assertEqual((latest["base_branch"], latest["phase_source"]), ("release/1.1", "requested_clean_tree"))
            self.git("switch", "-q", "release/1.0")
            self.write("wip.txt", "work\n")
            pinned = self.plan("--type=bug", "--key=MPS-13")
            self.assertEqual((pinned["phase"], pinned["base_branch"], pinned["target_branch"]),
                             ("beta", "release/1.0", "release/1.0"))
            self.assertEqual([w["code"] for w in pinned["warnings"]], ["not_latest_release"])
        with mock.patch.object(mps, "gitlab_client", return_value=fake_gitlab(["release/1.1"])):
            self.assertEqual(self.plan("--type=bug", "--key=MPS-13")["error"], "release_branch_gone")

    def test_jira_create_on_another_board_with_mocked_jira(self):
        self.write_env(MPS_JIRA_URL="https://jira.example", MPS_JIRA_PAT="x", MPS_JIRA_PROJECT_KEY="MPS")
        jira = fake_jira()
        with mock.patch.object(mps, "jira_client", return_value=jira):
            created = self.mps("jira", "create", "--type=story", "--summary=Vẽ lại icon", "--project=art",
                               "--sprint=backlog")
            self.assertEqual((created["key"], created["project"]), ("ART-1", "ART"))
            body = [call[2] for call in jira.calls if call[0] == "POST"][0]
            self.assertEqual(body["fields"]["project"], {"key": "ART"})
            self.assertEqual(body["fields"]["assignee"], {"name": "hung"})
            missing = self.mps("jira", "create", "--type=story", "--summary=x", "--project=NOPE")
            self.assertEqual(missing["error"], "jira_project_not_found")
            self.assertEqual([p["key"] for p in missing["available_projects"]], ["ART", "MPS"])
            default = self.mps("jira", "create", "--type=story", "--summary=x", "--sprint=backlog")
            self.assertEqual(default["project"], "MPS")
            self.assertNotIn(("GET", "/rest/api/2/project/MPS", None), jira.calls)  # default is not re-validated

    # -- sprint placement of new tickets -----------------------------------

    def _jira_env(self):
        self.write_env(MPS_JIRA_URL="https://jira.example", MPS_JIRA_PAT="x", MPS_JIRA_PROJECT_KEY="MPS")

    def _created(self, jira):
        return [call for call in jira.calls if call[:2] == ("POST", "/rest/api/2/issue")]

    def _moves(self, jira):
        return [(call[1], call[2]) for call in jira.calls if call[1].startswith("/rest/agile/1.0/sprint/")]

    def test_bug_goes_into_the_active_sprint_automatically(self):
        self._jira_env()
        jira = fake_jira(boards=[{"id": 5}], sprints_by_board={5: [SPRINT_12]})
        with mock.patch.object(mps, "jira_client", return_value=jira):
            created = self.mps("jira", "create", "--type=bug", "--summary=Crash khi mở shop")
        self.assertTrue(created["ok"], created)
        self.assertEqual((created["placement"], created["sprint"]["id"], created["sprint"]["name"]),
                         ("sprint", 12, "Sprint 12"))
        self.assertEqual(created["sprint"]["end_date"], "2026-11-15")
        self.assertEqual(self._moves(jira), [("/rest/agile/1.0/sprint/12/issue", {"issues": ["ART-1"]})])
        self.assertFalse(created["sprint_failed"])
        queries = dict(((path, method), params) for method, path, params in jira.params)
        board_query = queries[("/rest/agile/1.0/board", "GET")]
        self.assertEqual((board_query["projectKeyOrId"], board_query["type"]), ("MPS", "scrum"))
        self.assertEqual(queries[("/rest/agile/1.0/board/5/sprint", "GET")]["state"], "active")

    def test_sprint_of_another_board_is_not_used(self):
        self._jira_env()
        # An ART sprint holding one MPS issue shows up on the MPS board: it is not the MPS team's sprint.
        foreign = dict(SPRINT_13, originBoardId=99)
        jira = fake_jira(boards=[{"id": 5}], sprints_by_board={5: [foreign]})
        with mock.patch.object(mps, "jira_client", return_value=jira):
            created = self.mps("jira", "create", "--type=bug", "--summary=x")
            self.assertEqual(created["placement"], "backlog")
            self.assertEqual(self._moves(jira), [])
        jira = fake_jira(boards=[{"id": 5}], sprints_by_board={5: [foreign, SPRINT_12]})
        with mock.patch.object(mps, "jira_client", return_value=jira):
            self.assertEqual(self.mps("jira", "create", "--type=bug", "--summary=x")["sprint"]["id"], 12)

    def test_story_needs_an_explicit_choice_before_anything_is_created(self):
        self._jira_env()
        jira = fake_jira(boards=[{"id": 5}], sprints_by_board={5: [SPRINT_12]})
        with mock.patch.object(mps, "jira_client", return_value=jira):
            asked = self.mps("jira", "create", "--type=story", "--summary=Thêm event Tết")
            self.assertEqual(asked["error"], "sprint_choice_required")
            self.assertEqual([s["id"] for s in asked["active_sprints"]], [12])
            self.assertIn("Sprint 12 (kết thúc 2026-11-15)", asked["message"])
            self.assertEqual(self._created(jira), [])
            into_sprint = self.mps("jira", "create", "--type=story", "--summary=Thêm event Tết", "--sprint=active")
            self.assertEqual((into_sprint["placement"], into_sprint["sprint"]["id"]), ("sprint", 12))
            jira.calls[:] = []
            backlog = self.mps("jira", "create", "--type=story", "--summary=Thêm event Tết", "--sprint=Backlog")
            self.assertEqual((backlog["placement"], backlog["sprint"], backlog["notes"]), ("backlog", None, []))
            self.assertEqual([c for c in jira.calls if "/rest/agile/" in c[1]], [])  # backlog needs no agile call

    def test_no_running_sprint_means_backlog_without_a_question(self):
        self._jira_env()
        for jira in (fake_jira(), fake_jira(boards=[{"id": 5}], sprints_by_board={5: []}),
                     fake_jira(boards=[{"id": 5}, {"id": 7}], sprints_by_board={5: [], 7: 400})):
            with mock.patch.object(mps, "jira_client", return_value=jira):
                for ticket_type in ("story", "bug"):
                    created = self.mps("jira", "create", "--type=" + ticket_type, "--summary=x")
                    self.assertEqual((created["ok"], created["placement"]), (True, "backlog"), created)
                    self.assertIn("không có sprint nào đang chạy", created["notes"][0])
            self.assertEqual(self._moves(jira), [])

    def test_agile_api_unavailable_falls_back_to_backlog_with_a_note(self):
        self._jira_env()
        # No agile API at all, or every board's sprint list refused (no permission): Jira cannot tell.
        for jira in (fake_jira(boards=404), fake_jira(boards=[{"id": 5}], sprints_by_board={5: 403})):
            with mock.patch.object(mps, "jira_client", return_value=jira):
                created = self.mps("jira", "create", "--type=bug", "--summary=x")
                self.assertEqual(created["placement"], "backlog")
                self.assertIn("Jira Software", created["notes"][0])
                story = self.mps("jira", "create", "--type=story", "--summary=x")
                self.assertEqual(story["placement"], "backlog")
                listed = self.mps("jira", "sprints")
                self.assertEqual((listed["sprint_info_available"], listed["active_sprints"]), (False, []))

    def test_parallel_sprints_ask_which_one(self):
        self._jira_env()
        # Board 6 also shows sprint 12 (shared filter): it is listed once.
        jira = fake_jira(boards=[{"id": 5}, {"id": 6}], sprints_by_board={5: [SPRINT_12], 6: [SPRINT_13, SPRINT_12]})
        with mock.patch.object(mps, "jira_client", return_value=jira):
            for extra in ((), ("--sprint=active",)):
                asked = self.mps("jira", "create", "--type=bug", "--summary=x", *extra)
                self.assertEqual(asked["error"], "sprint_ambiguous")
                self.assertEqual([s["id"] for s in asked["active_sprints"]], [12, 13])
            self.assertEqual(self._created(jira), [])
            wrong = self.mps("jira", "create", "--type=bug", "--summary=x", "--sprint=99")
            self.assertEqual(wrong["error"], "sprint_not_active")
            picked = self.mps("jira", "create", "--type=story", "--summary=x", "--sprint=13")
            self.assertEqual(picked["sprint"]["id"], 13)
            self.assertEqual(self._moves(jira), [("/rest/agile/1.0/sprint/13/issue", {"issues": ["ART-1"]})])
            listed = self.mps("jira", "sprints")
            self.assertEqual((listed["project"], [s["id"] for s in listed["active_sprints"]]), ("MPS", [12, 13]))

    def test_refused_sprint_move_keeps_the_ticket_and_reports_it(self):
        self._jira_env()
        # 403: refused. 500: a server error after the ticket exists must not hide its key (a retry would duplicate).
        for status in (403, 500):
            jira = fake_jira(boards=[{"id": 5}], sprints_by_board={5: [SPRINT_12]}, move_status=status)
            with mock.patch.object(mps, "jira_client", return_value=jira):
                created = self.mps("jira", "create", "--type=bug", "--summary=x")
            self.assertEqual((created["ok"], created["key"], created["placement"], created["sprint_failed"]),
                             (True, "ART-1", "backlog", True))
            self.assertIn("KHÔNG tạo lại ticket", created["notes"][-1])

    def test_invalid_sprint_value_is_rejected(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="utf-8")
        with mock.patch.object(sys, "stdout", stream), self.assertRaises(SystemExit):
            mps.build_parser().parse_args(["jira", "create", "--type=bug", "--summary=x", "--sprint=next"])
        stream.flush()
        result = json.loads(buffer.getvalue().decode("utf-8"))
        self.assertEqual(result["error"], "usage_error")
        self.assertIn("sprint id", result["message"])
        self.assertEqual(mps.parse_sprint_choice(" 12 "), 12)
        self.assertEqual(mps.parse_sprint_choice("ACTIVE"), "active")

    # -- round 2: M1 scope gate, M5 exact paths ----------------------------

    def test_commit_requires_fresh_review(self):
        self.prepare("feature/MPS-14-a", "MPS-14")
        self.write("a.txt", "a\n")
        self.write("b.txt", "b\n")
        self.assertEqual(self.commit("feat: MPS-14 a", "a.txt")["error"], "scope_review_required")
        self.approve(["a.txt"], out_of_scope=["b.txt"], mixed=[])
        self.assertEqual(self.commit("feat: MPS-14 a", "a.txt", "b.txt")["error"], "not_in_scope")
        self.assertEqual(self.mps("git", "commit", "--message=x", "--files", "a.txt",
                                  "--include-out-of-scope", "c.txt")["error"], "invalid_include")
        self.write("a.txt", "a changed after review\n")
        self.assertEqual(self.commit("feat: MPS-14 a", "a.txt")["error"], "changed_since_review")
        self.approve(["a.txt"], out_of_scope=["b.txt"])
        self.git("commit", "-q", "--allow-empty", "-m", "feat: MPS-14 head moved")
        self.assertEqual(self.commit("feat: MPS-14 a", "a.txt")["error"], "scope_review_required")
        self.approve(["a.txt"], out_of_scope=["b.txt"])
        # The user explicitly named b.txt: it may be included.
        done = self.mps("git", "commit", "--message=feat: MPS-14 a", "--files", "a.txt", "b.txt",
                        "--include-out-of-scope", "b.txt")
        self.assertEqual(sorted(done["files"]), ["A\ta.txt", "A\tb.txt"])
        self.assertFalse(os.path.exists(mps.scope_path(self.repo)))
        self.assertFalse(os.path.exists(mps.code_review_path(self.repo)))
        committed = mps._read_json(mps.committed_review_path(self.repo))
        self.assertEqual((committed["committed_as"], committed["committed_paths"]), (self.head(), ["a.txt", "b.txt"]))

    def test_mixed_and_needs_decision_require_explicit_choice(self):
        self.prepare("feature/MPS-15-a", "MPS-15")
        self.write("a.txt", "a\n")
        self.write("m.txt", "m\n")
        self.write("c.txt", "c\n")
        result = self.approve(["a.txt"], mixed=["m.txt"], concern=["c.txt"], verdict="FAIL")
        self.assertEqual((result["commit_files"], result["needs_decision"], result["mixed_files"]),
                         (["a.txt"], ["c.txt"], ["m.txt"]))
        self.assertEqual(self.commit("feat: MPS-15 a", "a.txt", "m.txt")["error"], "not_in_scope")
        self.assertEqual(self.commit("feat: MPS-15 a", "a.txt", "c.txt")["error"], "not_in_scope")

    def test_deleted_folder_is_not_accepted(self):
        self.prepare("feature/MPS-16-cleanup", "MPS-16")
        self.write("Assets/Old/a.txt", "a\n")
        self.write("Assets/Old/b.txt", "b\n")
        self.git("add", "Assets")
        self.git("commit", "-q", "-m", "feat: MPS-16 add old assets")
        shutil.rmtree(os.path.join(self.repo, "Assets"))
        refused = self.commit("feat: MPS-16 cleanup", "Assets/Old")
        self.assertEqual(refused["error"], "explicit_files_required")
        self.assertEqual((refused["files"], refused["changed_files_inside"]),
                         (["Assets/Old"], ["Assets/Old/a.txt", "Assets/Old/b.txt"]))
        self.approve(["Assets/Old/a.txt", "Assets/Old/b.txt"])
        done = self.commit("feat: MPS-16 cleanup", "Assets/Old/a.txt", "Assets/Old/b.txt")
        self.assertEqual(sorted(done["files"]), ["D\tAssets/Old/a.txt", "D\tAssets/Old/b.txt"])

    # -- round 3 -----------------------------------------------------------

    def test_edit_between_bundle_and_classify_is_stale(self):
        """M1: the approval is bound to what the reviewer saw, not to the state at classify time."""
        self.prepare("feature/MPS-17-a", "MPS-17")
        self.write("a.txt", "reviewed\n")
        bundle_id = self.make_bundle()
        self.write("a.txt", "reviewed\nplus an unreviewed line\n")
        stale = self.classify(self.write_reply(bundle_id, ["a.txt"]))
        self.assertEqual((stale["error"], stale["reason"]), ("review_stale", "files_changed"))
        self.write("new.txt", "appeared after the bundle\n")
        self.assertEqual(self.classify(self.write_reply(bundle_id, ["a.txt"]))["reason"], "files_changed")
        self.assertEqual(self.commit("feat: MPS-17 a", "a.txt")["error"], "scope_review_required")

    def test_old_or_incomplete_reviews_never_approve(self):
        """M2: reused reply, reply without BUNDLE, reply without VERDICT, include on an incomplete scope."""
        self.prepare("feature/MPS-18-a", "MPS-18")
        self.write("a.txt", "a\n")
        old_bundle = self.make_bundle()
        old_reply = self.write_reply(old_bundle, ["a.txt"], name="old")
        self.write("b.txt", "b\n")
        new_bundle = self.make_bundle()
        reused = self.classify(old_reply)
        self.assertEqual((reused["error"], reused["reason"]), ("review_stale", "reply_for_other_bundle"))
        no_id = self.classify(self.write_reply(None, ["a.txt", "b.txt"]))
        self.assertEqual((no_id["error"], no_id["reason"]), ("review_stale", "reply_without_bundle_id"))
        no_verdict = self.classify(self.write_reply(new_bundle, ["a.txt", "b.txt"], verdict=None))
        self.assertFalse(no_verdict["complete"])
        self.assertEqual(self.commit("feat: MPS-18 a", "a.txt")["error"], "scope_incomplete")
        partial = self.classify(self.write_reply(new_bundle, ["a.txt"]))  # b.txt not classified
        self.assertFalse(partial["complete"])
        forced = self.mps("git", "commit", "--message=feat: MPS-18 a", "--files", "a.txt", "b.txt",
                          "--include-out-of-scope", "b.txt")
        self.assertEqual(forced["error"], "scope_incomplete")
        self.assertTrue(self.classify(self.write_reply(new_bundle, ["a.txt"], out_of_scope=["b.txt"]))["complete"])
        self.review_code(new_bundle)
        self.assertTrue(self.commit("feat: MPS-18 a", "a.txt")["ok"])

    def test_squash_merged_branch_is_not_unpushed_work(self):
        """M3: after squash-merge + branch deletion + prune, the old ticket's commits are not 'unpushed'."""
        self.prepare("feature/MPS-19-a", "MPS-19")
        self.write("a.txt", "a\n")
        self.approve(["a.txt"])
        self.commit("feat: MPS-19 a", "a.txt")
        pushed = self.mps("git", "push", "--branch=feature/MPS-19-a", "--base=develop")
        self.assertEqual(mps.last_pushed_commit(self.repo, "feature/MPS-19-a"), pushed["pushed_commit"])
        # A maintainer squash-merges on GitLab, which then deletes the source branch.
        self.push_upstream("develop", "a.txt", "a\n", "MPS-19 a (squashed)")
        self.git("push", "-q", "origin", "--delete", "feature/MPS-19-a", cwd=self.other)
        self.git("fetch", "-q", "--prune")
        self.assertFalse(mps.ref_exists(self.repo, "refs/remotes/origin/feature/MPS-19-a"))
        self.assertEqual(mps.unpushed_commit_count(self.repo), 0)
        self.assertEqual(mps.work_in_progress(self.repo, mps.DEFAULT_GENERATED_PATTERNS), (False, []))
        preflight = self.mps("git", "preflight", "--base=develop", "--branch=feature/MPS-20-b")
        self.assertNotIn("local_commits_not_carried", [w["code"] for w in preflight["warnings"]])
        nxt = self.prepare("feature/MPS-20-b", "MPS-20")
        self.assertEqual((nxt["action"], nxt["commits_left_behind"]), ("created_from_base", 0))
        # Without the record the same commit would count as unpushed (the regression this guards against).
        self.git("config", "--unset", "branch.feature/MPS-19-a.mps-pushed")
        self.git("switch", "-q", "feature/MPS-19-a")
        self.assertEqual(mps.unpushed_commit_count(self.repo), 1)

    def test_resume_commit_with_leftover_files(self):
        """m2: re-running the same commit after success is nothing_to_commit, even with other files still changed."""
        self.prepare("feature/MPS-21-a", "MPS-21")
        self.write("a.txt", "a\n")
        self.write("left.txt", "not for this ticket\n")
        self.approve(["a.txt"], out_of_scope=["left.txt"])
        self.assertEqual(self.commit("feat: MPS-21 a", "a.txt")["left_uncommitted"], ["left.txt"])
        again = self.commit("feat: MPS-21 a", "a.txt")
        self.assertEqual((again["error"], again["already_committed"]), ("nothing_to_commit", ["a.txt"]))
        self.assertEqual(self.commit("feat: MPS-21 a", "a.txt", "typo.txt")["error"], "explicit_files_required")

    def test_inferred_base_tie_is_ambiguous(self):
        """m3: develop and master on the same commit: only develop may be inferred."""
        self.git("push", "-q", "origin", "develop:master")
        self.git("fetch", "-q")
        self.prepare("feature/MPS-22-a", "MPS-22")
        self.write("a.txt", "a\n")
        self.approve(["a.txt"])
        self.commit("feat: MPS-22 a", "a.txt")
        self.git("config", "--unset", "branch.feature/MPS-22-a.mps-base")
        with self.assertRaises(mps.MpsError) as ctx:
            mps.ensure_mr_target(self.repo, "feature/MPS-22-a", "master", "MPS-22", BRANCHES)
        self.assertEqual((ctx.exception.code, ctx.exception.extra["inferred_bases"]),
                         ("target_ambiguous", ["develop", "master"]))
        self.assertIsNone(mps.ensure_mr_target(self.repo, "feature/MPS-22-a", "develop", "MPS-22", BRANCHES))

    # -- generated files and phase pinning ----------------------------------

    def make_unity_project(self, folder=""):
        """Commit ProjectSettings/ProjectVersion.txt (marks a Unity project root) on the current branch and push."""
        self.write(os.path.join(folder, "ProjectSettings", "ProjectVersion.txt"), "m_EditorVersion: 2022.3.0f1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "chore: unity project")
        self.git("push", "-q", "origin", "HEAD")

    def test_generated_files_do_not_pin_the_phase(self):
        self.git("switch", "-q", "release/1.0")
        self.make_unity_project()
        self.write("ProjectSettings/ProjectSettings.asset", "unity rewrote this\n")
        self.write("Game.csproj", "<Project/>\n")
        plan = self.plan("--type=bug", "--key=MPS-30", "--phase=dev")
        self.assertEqual((plan["phase"], plan["phase_source"], plan["work_in_progress"]),
                         ("dev", "requested_clean_tree", False))
        self.assertEqual(sorted(plan["generated_changes"]), ["Game.csproj", "ProjectSettings/ProjectSettings.asset"])
        required = self.plan("--type=bug", "--key=MPS-30")
        self.assertEqual((required["error"], len(required["generated_changes"])), ("phase_required", 2))
        # A real source change on the release branch does pin it.
        self.write("src/fix.cs", "class Fix {}\n")
        conflict = self.plan("--type=bug", "--key=MPS-30", "--phase=dev")
        self.assertEqual(conflict["error"], "phase_conflict")
        self.assertEqual(len(conflict["generated_changes"]), 2)
        # Committing is unaffected: the generated files are still offered to the scope review.
        uncommitted, _ = mps.review_candidates(self.repo, "origin/release/1.0")
        self.assertIn("ProjectSettings/ProjectSettings.asset", uncommitted)

    def test_folder_named_like_generated_one_is_real_work(self):
        """G1: Assets/Plugins/Library/Core.cs is code, not Unity's Library/ folder."""
        self.git("switch", "-q", "release/1.0")
        self.make_unity_project()
        self.write("Assets/Plugins/Library/Core.cs", "class Core {}\n")
        conflict = self.plan("--type=bug", "--key=MPS-32", "--phase=dev")
        self.assertEqual((conflict["error"], conflict["generated_changes"]), ("phase_conflict", []))

    def test_non_unity_repo_does_not_use_the_defaults(self):
        self.git("switch", "-q", "release/1.0")
        self.write("Server.sln", "solution\n")
        self.write("ProjectSettings/x.asset", "not unity\n")
        conflict = self.plan("--type=bug", "--key=MPS-33", "--phase=dev")
        self.assertEqual((conflict["error"], conflict["generated_changes"]), ("phase_conflict", []))

    def test_nested_unity_project_found_on_disk(self):
        self.git("switch", "-q", "release/1.0")
        # Untracked version file: the Unity root is found on disk, not only through git.
        self.write("Client/Game/ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 2022.3.0f1\n")
        self.write("Client/Game/ProjectSettings/TagManager.asset", "tags\n")
        self.write("Client/Game/Game.csproj", "<Project/>\n")
        plan = self.plan("--type=bug", "--key=MPS-34", "--phase=dev")
        self.assertEqual(plan["phase_source"], "requested_clean_tree")
        self.assertEqual(sorted(plan["generated_changes"]),
                         ["Client/Game/Game.csproj", "Client/Game/ProjectSettings/ProjectVersion.txt",
                          "Client/Game/ProjectSettings/TagManager.asset"])
        self.write("Client/Server.csproj", "<Project/>\n")  # outside the Unity root: real work
        self.assertEqual(self.plan("--type=bug", "--key=MPS-34", "--phase=dev")["error"], "phase_conflict")

    def test_generated_patterns_from_env(self):
        self.write(".env", "MPS_GENERATED_PATTERNS=Assets/Gen/**,*\n")  # untracked .env never counts as work
        self.git("switch", "-q", "release/1.0")
        self.write("Assets/Gen/Bindings.cs", "// generated\n")
        plan = self.plan("--type=bug", "--key=MPS-31", "--phase=dev")
        self.assertEqual((plan["phase_source"], plan["generated_changes"]),
                         ("requested_clean_tree", ["Assets/Gen/Bindings.cs"]))
        self.assertEqual([(w["code"], w["patterns"]) for w in plan["warnings"]],
                         [("invalid_generated_pattern", ["*"])])
        # G2: the rejected '*' does not hide real work.
        self.write("src/fix.cs", "class Fix {}\n")
        conflict = self.plan("--type=bug", "--key=MPS-31", "--phase=dev")
        self.assertEqual(conflict["error"], "phase_conflict")
        self.assertEqual(conflict["warnings"][0]["code"], "invalid_generated_pattern")
        # Only the user edits this key, by hand.
        refused = self.mps("env", "set", "MPS_GENERATED_PATTERNS", "*")
        self.assertEqual(refused["error"], "manual_edit_required")
        self.assertNotIn("MPS_GENERATED_PATTERNS", self.mps("env", "set", "FOO", "x")["allowed_keys"])

    def test_closed_unmerged_branch_counts_again(self):
        """m1: pushed but never merged (MR closed, branch deleted) -> still unpushed work."""
        self.prepare("feature/MPS-35-a", "MPS-35")
        self.write("a.txt", "a\n")
        self.approve(["a.txt"])
        self.commit("feat: MPS-35 a", "a.txt")
        self.mps("git", "push", "--branch=feature/MPS-35-a", "--base=develop")
        self.git("push", "-q", "origin", "--delete", "feature/MPS-35-a")
        self.git("fetch", "-q", "--prune")
        self.assertEqual(mps.unpushed_commit_count(self.repo), 1)
        refused = self.prepare("feature/MPS-36-b", "MPS-36")
        self.assertEqual((refused["error"], refused["count"]), ("local_commits_not_carried", 1))

    # -- 0.1.1: project setup, version check, .env onboarding ----------------

    def settings_bytes(self):
        with open(os.path.join(self.repo, ".claude", "settings.json"), "rb") as handle:
            return handle.read()

    def env_check(self, latest=None):
        """`env check` with the GitHub version lookup replaced (tests never reach the network)."""
        with mock.patch.object(mps, "fetch_latest_plugin_version", return_value=latest):
            return self.mps("env", "check")

    def write_connected_env(self):
        self.write_env(MPS_JIRA_URL="https://jira.example", MPS_JIRA_PAT="jira-token", MPS_JIRA_PROJECT_KEY="MPS",
                       MPS_GITLAB_URL="https://git.example", MPS_GITLAB_PAT="gitlab-token",
                       MPS_GITLAB_PROJECT="grp/proj")

    def connected_env_check(self, latest=None):
        """A successful `env check` (after write_connected_env) with Jira and GitLab faked."""
        jira = FakeService({("GET", "/rest/api/2/myself"): (200, {"name": "hung"}),
                            ("GET", "/rest/api/2/project/MPS"): (200, {"key": "MPS", "name": "Game"})})
        gitlab = FakeService({("GET", "/user"): (200, {"id": 7, "username": "hung"}),
                              ("GET", "/projects/grp%2Fproj"): (200, {"id": 1, "path_with_namespace": "grp/proj"}),
                              ("GET", "/projects/1/members/all/7"): (200, {"access_level": 30})})
        with mock.patch.object(mps, "jira_client", return_value=jira), \
                mock.patch.object(mps, "gitlab_client", return_value=gitlab):
            return self.env_check(latest)

    def test_project_setup_creates_settings_and_is_idempotent(self):
        """P1."""
        first = self.mps("project", "setup")
        expected = mps.render_settings_json(mps.merge_project_settings({})[0], "\n").encode("utf-8")
        self.assertEqual(self.settings_bytes(), expected)
        self.assertEqual((first["created"], first["changed"], first["changes"]),
                         (True, True, NEW_SETTINGS_CHANGES))
        self.assertTrue(first["gitignore_updated"])
        self.assertIn(".env", self.read(".gitignore").splitlines())
        self.assertEqual(first["files_to_commit"], [".claude/settings.json", ".gitignore"])
        self.assertEqual((first["warnings"], first["next"]), ([], "commit_with_mps_git_flow"))
        second = self.mps("project", "setup")
        self.assertEqual((second["created"], second["changed"], second["changes"]), (False, False, []))
        self.assertEqual(self.settings_bytes(), expected)

    def test_project_setup_keeps_keys_and_crlf_and_refuses_invalid_json(self):
        """P2."""
        os.makedirs(os.path.join(self.repo, ".claude"))
        path = os.path.join(self.repo, ".claude", "settings.json")
        with open(path, "wb") as handle:
            handle.write(b'{\r\n  "permissions": {"allow": ["Bash(ls)"]},\r\n  "env": {"A": "1"}\r\n}\r\n')
        result = self.mps("project", "setup")
        self.assertEqual(result["changes"], NEW_SETTINGS_CHANGES)
        written = self.settings_bytes()
        self.assertNotIn(b"\n", written.replace(b"\r\n", b""))
        data = json.loads(written.decode("utf-8"))
        self.assertEqual(list(data), ["permissions", "env", "extraKnownMarketplaces", "enabledPlugins", "attribution"])
        self.assertEqual((data["permissions"], data["env"]), ({"allow": ["Bash(ls)"]}, {"A": "1"}))
        broken = b'{"permissions": {'
        with open(path, "wb") as handle:
            handle.write(broken)
        refused = self.mps("project", "setup")
        self.assertEqual(refused["error"], "settings_invalid_json")
        self.assertIsInstance(refused["line"], int)
        self.assertEqual(self.settings_bytes(), broken)

    def write_settings(self, data):
        os.makedirs(os.path.join(self.repo, ".claude"), exist_ok=True)
        with open(os.path.join(self.repo, ".claude", "settings.json"), "wb") as handle:
            handle.write(data)

    def test_project_setup_rerun_before_commit_still_lists_files(self):
        """M4: changed false does not mean committed."""
        self.mps("project", "setup")
        again = self.mps("project", "setup")
        self.assertFalse(again["changed"])
        self.assertEqual(again["files_to_commit"], [".claude/settings.json", ".gitignore"])
        self.assertEqual(again["next"], "commit_with_mps_git_flow")
        self.git("add", ".claude/settings.json", ".gitignore")
        self.git("commit", "-q", "-m", "chore: integrate plugin")
        done = self.mps("project", "setup")
        self.assertEqual((done["changed"], done["files_to_commit"], done["next"]), (False, [], None))

    def test_project_setup_is_a_no_op_on_integrated_crlf_bom_file(self):
        rendered = mps.render_settings_json(mps.merge_project_settings({"model": "x"})[0], "\r\n")
        original = UTF8_BOM + rendered.encode("utf-8")
        self.write_settings(original)
        result = self.mps("project", "setup")
        self.assertEqual((result["changed"], result["changes"]), (False, []))
        self.assertEqual(self.settings_bytes(), original)

    def test_project_setup_keeps_the_file_indent(self):
        self.write_settings(b'{\n    "model": "x"\n}\n')
        self.mps("project", "setup")
        text = self.settings_bytes().decode("utf-8")
        self.assertTrue(text.startswith('{\n    "model": "x",\n    "extraKnownMarketplaces": {\n        "'), text)
        self.assertEqual([name for name in os.listdir(os.path.join(self.repo, ".claude"))], ["settings.json"])

    def test_tracked_settings_are_not_reported_as_ignored(self):
        """m2: git keeps committing a tracked file whatever .gitignore says."""
        self.write_settings(b"{}\n")
        self.git("add", ".claude/settings.json")
        self.git("commit", "-q", "-m", "chore: settings")
        self.write(".gitignore", ".claude/\n")
        result = self.mps("project", "setup")
        self.assertEqual(result["warnings"], [])
        self.assertIn(".claude/settings.json", result["files_to_commit"])

    def test_invalid_settings_count_as_not_integrated(self):
        self.write_settings(b'{"enabledPlugins": ')
        self.assertEqual(mps.project_settings_status(self.repo), "missing")
        self.assertIsNone(mps.load_project_settings(self.repo))

    def test_env_check_skips_version_check_when_pinned(self):
        """M3: a ref-pinned marketplace is a deliberate version choice."""
        settings = mps.merge_project_settings({})[0]
        settings["extraKnownMarketplaces"]["mps-cdci-agents"]["source"]["ref"] = "v0.1.1"
        self.write_settings(mps.render_settings_json(settings, "\n").encode("utf-8"))
        self.write_connected_env()
        with mock.patch.object(mps, "fetch_latest_plugin_version", return_value="99.0.0") as fetch:
            result = self.connected_env_check(latest="99.0.0")
            fetch.assert_not_called()
        self.assertEqual(result["plugin_version"],
                         {"running": mps.VERSION, "latest": None, "checked": False, "pinned": "v0.1.1"})
        codes = [w["code"] for w in result["warnings"]]
        self.assertNotIn("plugin_outdated", codes)
        self.assertNotIn("project_not_integrated", codes)

    def test_project_setup_scaffolds_review_rules_on_request(self):
        """0.2.0 hook point (R.4): review_rules is reported; --review-rules creates the file, never overwrites it."""
        first = self.mps("project", "setup")
        self.assertEqual((first["review_rules"], first["review_rules_problems"]), ("absent", []))
        self.assertNotIn(".mps/review.md", first["files_to_commit"])
        created = self.mps("project", "setup", "--review-rules")
        self.assertEqual(created["review_rules"], "created")
        self.assertEqual(created["files_to_commit"], [".claude/settings.json", ".gitignore", ".mps/review.md"])
        self.assertEqual(_read_bytes(created["review_rules_path"]), _read_bytes(mps.REVIEW_RULES_TEMPLATE_PATH))
        self.write(".mps/review.md", "## BAD [oops] x\n")
        present = self.mps("project", "setup", "--review-rules")
        self.assertEqual((present["review_rules"], [p["line"] for p in present["review_rules_problems"]]),
                         ("present", [1]))
        self.assertEqual(self.read(".mps/review.md"), "## BAD [oops] x\n")

    def test_project_setup_warns_when_settings_are_ignored(self):
        """P3."""
        self.write(".gitignore", ".claude/\n")
        result = self.mps("project", "setup")
        self.assertEqual([w["code"] for w in result["warnings"]], ["settings_ignored_by_git"])

    def test_env_check_reports_newer_plugin_version(self):
        """P4: plugin_outdated on success and on errors; an unreachable GitHub is silent."""
        self.write_connected_env()
        outdated = self.connected_env_check(latest="99.0.0")
        self.assertEqual(outdated["plugin_version"], {"running": mps.VERSION, "latest": "99.0.0", "checked": True})
        warning = [w for w in outdated["warnings"] if w["code"] == "plugin_outdated"][0]
        self.assertEqual((warning["latest"], warning["running"]), ("99.0.0", mps.VERSION))
        self.assertEqual(warning["commands"], ["claude plugin marketplace update mps-cdci-agents",
                                               "claude plugin update mps-git-flow@mps-cdci-agents"])
        self.assertEqual(outdated["gitlab_access_level"], 30)
        offline = self.connected_env_check(latest=None)
        self.assertEqual(offline["plugin_version"], {"running": mps.VERSION, "latest": None, "checked": False})
        self.assertNotIn("plugin_outdated", [w["code"] for w in offline["warnings"]])
        os.remove(os.path.join(self.repo, ".env"))
        missing = self.env_check(latest="99.0.0")
        self.assertEqual((missing["error"], missing["next"]), ("env_missing", "env init --open"))
        self.assertEqual(missing["plugin_version"]["latest"], "99.0.0")
        self.assertIn("plugin_outdated", [w["code"] for w in missing["warnings"]])

    def test_env_check_reports_project_not_integrated(self):
        """P5."""
        self.write_connected_env()
        before = self.connected_env_check()
        self.assertIn("project_not_integrated", [w["code"] for w in before["warnings"]])
        self.mps("project", "setup")
        after = self.connected_env_check()
        self.assertNotIn("project_not_integrated", [w["code"] for w in after["warnings"]])

    def test_env_init_gives_fill_guide_for_blank_member_keys(self):
        """R.11.4: a new .env needs the three member keys; a filled one needs nothing."""
        created = self.mps("env", "init")
        self.assertTrue(created["created"])
        self.assertEqual(created["keys_to_fill"], list(mps.MEMBER_KEYS))
        self.assertEqual([entry["key"] for entry in created["fill_guide"]], list(mps.MEMBER_KEYS))
        with open(os.path.join(self.repo, ".env"), "rb") as handle:
            text = handle.read().decode("utf-8")
        for key, value in (("MPS_JIRA_PAT", "jira-token"), ("MPS_JIRA_PROJECT_KEY", "MPS"),
                           ("MPS_GITLAB_PAT", "gitlab-token")):
            text = mps.update_env_text(text, key, value)
        with open(os.path.join(self.repo, ".env"), "wb") as handle:
            handle.write(text.encode("utf-8"))
        again = self.mps("env", "init")
        self.assertEqual((again["created"], again["fill_guide"], again["keys_to_fill"]), (False, [], []))

    def test_env_check_missing_tokens_gives_fill_guide(self):
        """R.11.4: blank PATs -> missing_config with a guide for exactly those keys."""
        self.write_env(MPS_JIRA_PAT="", MPS_JIRA_PROJECT_KEY="MPS", MPS_GITLAB_PAT="")
        result = self.env_check()
        self.assertEqual(result["error"], "missing_config")
        self.assertEqual(result["missing_keys"], ["MPS_JIRA_PAT", "MPS_GITLAB_PAT"])
        self.assertEqual([entry["key"] for entry in result["fill_guide"]], ["MPS_JIRA_PAT", "MPS_GITLAB_PAT"])
        self.assertIn("plugin_version", result)

    def test_env_check_rejected_token_gives_fill_guide(self):
        """R.11.2: a 401 from GitLab during env check carries the guide for that one token."""
        self.write_env(MPS_JIRA_URL="https://jira.example", MPS_JIRA_PAT="jira-token", MPS_JIRA_PROJECT_KEY="MPS",
                       MPS_GITLAB_URL="https://git.example", MPS_GITLAB_PAT="gitlab-token")
        jira = FakeService({("GET", "/rest/api/2/myself"): (200, {"name": "hung"})})
        gitlab = mock.Mock()
        gitlab.get.side_effect = mps.MpsError("auth_failed", "401", service="gitlab", status=401)
        with mock.patch.object(mps, "jira_client", return_value=jira), \
                mock.patch.object(mps, "gitlab_client", return_value=gitlab):
            result = self.env_check()
        self.assertEqual(result["error"], "auth_failed")
        self.assertEqual([entry["key"] for entry in result["fill_guide"]], ["MPS_GITLAB_PAT"])
        self.assertIn("hết hạn", result["fill_guide"][0]["steps"][0])

    # -- 0.1.1: MR assignee, labels, no AI attribution ------------------------

    def pushed_ticket_branch(self, key):
        """A pushed ticket branch with one commit for `key`, ready for `mr ensure`."""
        if not os.path.isfile(os.path.join(self.repo, ".env")):
            self.write_env(MPS_GITLAB_URL="https://git.example", MPS_GITLAB_PAT="gitlab-token",
                           MPS_GITLAB_PROJECT="grp/proj")
        branch = "feature/%s-a" % key
        self.prepare(branch, key)
        self.write("a.txt", "a %s\n" % key)
        self.approve(["a.txt"])
        self.commit("feat: %s a" % key, "a.txt")
        self.mps("git", "push", "--branch=" + branch, "--base=develop")
        return branch

    def ensure_mr(self, gitlab, branch, key, kind="story", description=None, code_review=False):
        extra = ["--code-review"] if code_review else []
        with mock.patch.object(mps, "gitlab_client", return_value=gitlab):
            return self.mps("mr", "ensure", "--source=" + branch, "--target=develop", "--title=%s a" % key,
                            "--description=" + (description or "Close " + key), "--key=" + key, "--type=" + kind,
                            *extra)

    def test_mr_created_with_assignee_and_label(self):
        branch = self.pushed_ticket_branch("MPS-40")
        gitlab = FakeMrGitLab()
        result = self.ensure_mr(gitlab, branch, "MPS-40", "story")
        self.assertEqual((result["existed"], result["assignees"], result["labels"], result["warnings"]),
                         (False, ["hung"], ["Enhancement"], []))
        body = gitlab.bodies("POST")[0]
        self.assertEqual((body["assignee_ids"], body["labels"]), ([7], "Enhancement"))
        self.assertFalse(result["attribution_removed"])

    def test_existing_mr_gets_missing_assignee_and_label(self):
        branch = self.pushed_ticket_branch("MPS-41")
        mr = {"iid": 5, "web_url": "u", "title": "t", "source_branch": branch, "target_branch": "develop",
              "state": "opened", "labels": [], "assignees": []}
        gitlab = FakeMrGitLab(mrs=[mr])
        result = self.ensure_mr(gitlab, branch, "MPS-41", "bug")
        self.assertEqual((result["existed"], result["assignees"], result["labels"]), (True, ["hung"], ["Bug"]))
        self.assertEqual(gitlab.bodies("PUT"), [{"assignee_ids": [7]}, {"add_labels": "Bug"}])
        self.assertEqual(gitlab.bodies("POST"), [])

    def test_existing_assignee_is_left_alone(self):
        branch = self.pushed_ticket_branch("MPS-42")
        mr = {"iid": 6, "web_url": "u", "title": "t", "source_branch": branch, "target_branch": "develop",
              "state": "opened", "labels": ["Bug"], "assignees": [{"id": 9, "username": "lead"}]}
        gitlab = FakeMrGitLab(mrs=[mr])
        result = self.ensure_mr(gitlab, branch, "MPS-42", "bug")
        self.assertEqual((result["assignees"], result["labels"], result["warnings"]), (["lead"], ["Bug"], []))
        self.assertEqual(gitlab.bodies("PUT"), [])

    def test_missing_label_warns_and_still_creates_the_mr(self):
        branch = self.pushed_ticket_branch("MPS-43")
        gitlab = FakeMrGitLab(labels=("Bug report",))
        result = self.ensure_mr(gitlab, branch, "MPS-43", "bug")
        self.assertEqual((result["existed"], result["labels"], result["assignees"]), (False, [], ["hung"]))
        self.assertEqual([(w["code"], w["label"]) for w in result["warnings"]], [("label_not_found", "Bug")])
        self.assertNotIn("labels", gitlab.bodies("POST")[0])

    def test_label_with_other_case_uses_the_existing_name(self):
        branch = self.pushed_ticket_branch("MPS-44")
        gitlab = FakeMrGitLab(labels=("bug", "enhancement"))
        result = self.ensure_mr(gitlab, branch, "MPS-44", "bug")
        self.assertEqual(result["labels"], ["bug"])
        self.assertEqual(gitlab.bodies("POST")[0]["labels"], "bug")

    def test_rejected_extras_still_create_the_mr(self):
        branch = self.pushed_ticket_branch("MPS-46")
        gitlab = FakeMrGitLab(reject_extras=True)
        result = self.ensure_mr(gitlab, branch, "MPS-46", "story")
        self.assertEqual((result["existed"], result["iid"]), (False, 1))
        self.assertEqual(sorted(w["code"] for w in result["warnings"]), ["assign_failed", "label_failed"])
        self.assertEqual(len(gitlab.bodies("POST")), 2)

    def test_mr_appearing_during_create_is_reused(self):
        """n2: GitLab may answer 409 or 422 when an open MR for the branch already exists."""
        branch = self.pushed_ticket_branch("MPS-47")
        for status in (409, 422):
            gitlab = FakeMrGitLab(race_status=status)
            result = self.ensure_mr(gitlab, branch, "MPS-47", "bug")
            self.assertEqual((result["existed"], result["iid"], result["assignees"], result["labels"]),
                             (True, 9, ["hung"], ["Bug"]), status)

    def test_ai_attribution_stripped_from_commit_and_mr(self):
        branch = "feature/MPS-45-a"
        self.write_env(MPS_GITLAB_URL="https://git.example", MPS_GITLAB_PAT="gitlab-token",
                       MPS_GITLAB_PROJECT="grp/proj")
        self.prepare(branch, "MPS-45")
        self.write("a.txt", "a\n")
        self.approve(["a.txt"])
        only_ai = self.commit("Co-Authored-By: Claude <noreply@anthropic.com>", "a.txt")
        self.assertEqual(only_ai["error"], "empty_message")
        human = "Co-Authored-By: Lan Nguyen <lan@example.com>"
        message = "feat: MPS-45 a\n\n%s\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n" % human
        done = self.commit(message, "a.txt")
        self.assertTrue(done["attribution_removed"])
        self.assertEqual(self.git("log", "-1", "--format=%B").strip(), "feat: MPS-45 a\n\n" + human)
        self.mps("git", "push", "--branch=" + branch, "--base=develop")
        gitlab = FakeMrGitLab()
        description = ("Close MPS-45\n%s\n\n\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)"
                       % human)
        result = self.ensure_mr(gitlab, branch, "MPS-45", "story", description)
        self.assertTrue(result["attribution_removed"])
        self.assertEqual(gitlab.bodies("POST")[0]["description"], "Close MPS-45\n" + human)

    # -- 0.2.0: code review ------------------------------------------------------

    def golden_scope_bundle(self):
        """R1 fixture: committed + working + untracked + .env.local changes; the scope bundle with its id masked."""
        self.prepare("feature/MPS-60-golden", "MPS-60")
        self.write("src/a.txt", "a1\na2\n")
        self.git("add", "src/a.txt")
        self.git("commit", "-q", "-m", "feat: MPS-60 a")
        self.write("app.txt", "line1\nline2 edited\n")
        self.write("new.txt", "brand new\n")
        self.write("cfg/.env.local", "SECRET_VALUE_XYZ=1\n")
        review = self.mps("git", "diff-for-review", "--base=develop", "--to-file")
        with open(review["bundle_path"], "rb") as handle:
            text = handle.read().decode("utf-8")
        return text.replace(review["bundle_id"], "<BUNDLE-ID>")

    def test_scope_bundle_is_unchanged(self):
        """R1: the scope bundle stays byte-identical; bundle.json without --to-file has no code_review key."""
        self.assertEqual(self.golden_scope_bundle(), GOLDEN_SCOPE_BUNDLE)
        self.mps("git", "diff-for-review", "--base=develop")
        self.assertNotIn("code_review", mps._read_json(mps.bundle_meta_path(self.repo)))

    def bundle(self, base="develop"):
        return self.mps("git", "diff-for-review", "--base=" + base, "--to-file")

    def code_bundle_text(self, review):
        with open(review["code_bundle_path"], encoding="utf-8") as handle:
            return handle.read()

    def push_project_rules(self, text, branch="develop"):
        """Commit .mps/review.md on origin/<branch> (from the second clone) and fetch it."""
        self.push_upstream(branch, ".mps/review.md", text, "chore: review rules")
        self.git("fetch", "-q")

    def test_code_bundle_without_project_rules(self):
        """I3."""
        self.prepare("feature/MPS-61-a", "MPS-61")
        self.write("a.txt", "a\n")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "feat: MPS-61 a")
        self.write("app.txt", "line1\nline2 edited\nline3\n")
        self.write(".env.local", "SECRET_VALUE_XYZ=1\n")
        review = self.bundle()
        self.assertEqual((review["rules"]["project_rules"]["status"], review["code_review_needed"]), ("absent", True))
        self.assertIn("BASE-HARDCODED-SECRET", review["rules"]["applied"])
        self.assertEqual((review["reviewed_files"], review["ignored_files"], review["warnings"]),
                         (["a.txt", "app.txt"], [], []))
        text = self.code_bundle_text(review)
        self.assertIn("Bundle-ID: " + review["bundle_id"], text)
        self.assertIn("### a.txt  [added]\n@@ -0,0 +1 @@\n     1 + a\n", text)
        self.assertIn("     2 + line2 edited\n     3 + line3\n", text)
        self.assertNotIn("SECRET_VALUE_XYZ", text)
        code_review = mps._read_json(mps.bundle_meta_path(self.repo))["code_review"]
        self.assertEqual(code_review["ranges"], {"a.txt": [[1, 1]], "app.txt": [[1, 3]]})
        self.assertFalse(os.path.exists(mps.code_review_path(self.repo)))

    def test_project_rules_come_from_the_base_branch(self):
        """I2 (bundle part): a local edit of .mps/review.md changes nothing until it is merged."""
        self.push_project_rules(PROJECT_RULES)
        self.prepare("feature/MPS-62-a", "MPS-62")
        self.write(".mps/review.md", "---\nversion: 1\n---\n")
        self.write("a.txt", "a\n")
        review = self.bundle()
        rules = review["rules"]
        self.assertIn("SH-NO-PRINT", rules["applied"])
        self.assertEqual((rules["blocker_rule_count"], rules["project_rules"]["status"],
                          rules["project_rules"]["pending_change"], rules["project_rules"]["source"]),
                         (1, "applied", True, "origin/develop:.mps/review.md"))
        self.assertEqual([w["code"] for w in review["warnings"]], ["project_rules_pending"])
        self.assertIn("### SH-NO-PRINT [blocker]", self.code_bundle_text(review))
        self.approve([".mps/review.md", "a.txt"], code_findings=["SH-NO-PRINT | blocker | a.txt:1 | p | s"])
        self.assertEqual(self.commit("feat: MPS-62 a", ".mps/review.md", "a.txt")["error"], "code_review_blocked")

    def test_invalid_project_rules_warn_and_continue(self):
        """I6 (bundle part)."""
        self.push_project_rules(PROJECT_RULES.replace("[blocker]", "[fatal]") + "\n## SH-OK [major] ok\n")
        self.prepare("feature/MPS-63-a", "MPS-63")
        self.write("a.txt", "a\n")
        review = self.bundle()
        project = review["rules"]["project_rules"]
        self.assertEqual((project["status"], [p["line"] for p in project["problems"]]), ("invalid", [5]))
        warning = review["warnings"][0]
        self.assertEqual((warning["code"], warning["problems"]), ("project_rules_invalid", project["problems"]))
        self.assertIn("KHÔNG được áp dụng", warning["message"])
        self.assertNotIn("SH-OK", review["rules"]["applied"])
        text = self.code_bundle_text(review)
        self.assertNotIn("SH-OK", text)
        self.assertNotIn("SH-NO-PRINT", text)
        self.assertTrue(review["code_review_needed"])
        # A finding citing a rule of the broken file is dropped without making the review incomplete (the reviewer
        # never sees a blocker rule then); had the reviewer called it a blocker, it would have to fix its reply.
        self.classify(self.write_reply(review["bundle_id"], ["a.txt"]))
        claimed = self.review_code(review["bundle_id"], ["SH-NO-PRINT | blocker | a.txt:1 | p | s"])
        self.assertEqual((claimed["complete"], claimed["dropped_findings"][0]["blocker_claimed"]), (False, True))
        findings = self.review_code(review["bundle_id"], ["SH-NO-PRINT | major | a.txt:1 | p | s"])
        self.assertEqual((findings["complete"], findings["dropped_findings"][0]["reason"],
                          findings["dropped_findings"][0]["blocker_rule"]), (True, "unknown_rule", False))
        self.assertEqual(findings["warnings"][0]["code"], "project_rules_invalid")
        self.assertTrue(self.commit("feat: MPS-63 a", "a.txt")["ok"])
        section = mps.render_mr_review_section(mps._read_json(mps.committed_review_path(self.repo)))
        self.assertIn("Quy tắc riêng của dự án KHÔNG được áp dụng", section)
        self.assertIn("dòng 5:", section)

    def test_unity_profile_in_a_subfolder(self):
        """I7 (bundle part)."""
        self.make_unity_project("Game")
        self.prepare("feature/MPS-64-a", "MPS-64")
        self.write("Game/Assets/Main.prefab", "prefab: yaml\n")
        self.write("Game/Assets/X.cs", "class X {}\n")
        self.write("Tools/X.cs", "class T {}\n")
        review = self.bundle()
        self.assertEqual(review["rules"]["profiles"], [{"name": "unity-csharp", "roots": ["Game"],
                                                        "source": "detected"}])
        self.assertEqual((review["reviewed_files"], review["ignored_files"]),
                         (["Game/Assets/X.cs", "Tools/X.cs"], ["Game/Assets/Main.prefab"]))
        self.assertIn("UNITY-NO-FIND-IN-UPDATE", review["rules"]["applied"])
        text = self.code_bundle_text(review)
        self.assertIn("Applies to: `**/*.cs` (relative to `Game`)", text)
        self.assertNotIn("prefab: yaml", text)

    def test_nothing_to_review_records_an_empty_review(self):
        """I11 (bundle part): an artist-only change needs no code reviewer."""
        self.make_unity_project("Game")
        self.prepare("feature/MPS-65-a", "MPS-65")
        self.write("Game/Assets/Main.prefab", "prefab: yaml\n")
        review = self.bundle()
        self.assertEqual((review["code_review_needed"], review["reviewed_files"], review["rules"]["applied"]),
                         (False, [], []))
        record = mps._read_json(mps.code_review_path(self.repo))
        self.assertEqual((record["auto"], record["complete"], record["bundle_id"], record["findings"]),
                         ("nothing_to_review", True, review["bundle_id"], []))
        self.approve_scope_only(["Game/Assets/Main.prefab"])
        done = self.commit("feat: MPS-65 a", "Game/Assets/Main.prefab")
        self.assertEqual((done["ok"], done["code_review_warning_count"]), (True, 0))

    def test_project_rule_beats_profile_ignore_and_unmatched_rules_warn(self):
        """M1: a prefab-only change under an L3 prefab blocker is reviewed (no auto shortcut); an L3 rule whose
        root-anchored paths miss the Unity subfolder is reported."""
        self.write("Game/ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 2022.3.0f1\n")
        self.write("Game/Assets/Old.prefab", "old: yaml\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "chore: unity project")
        self.git("push", "-q", "origin", "HEAD")
        self.push_project_rules("\n".join([
            "## SH-PREFAB [blocker] Prefab phải có tên tiếng Anh", "paths: **/*.prefab", "",
            "## SH-WRONG [blocker] Sai gốc đường dẫn", "paths: Assets/Scripts/**/*.cs", ""]))
        self.prepare("feature/MPS-74-a", "MPS-74")
        self.write("Game/Assets/Main.prefab", "prefab: yaml\n")
        review = self.bundle()
        self.assertEqual((review["code_review_needed"], review["reviewed_files"], review["ignored_files"]),
                         (True, ["Game/Assets/Main.prefab"], []))
        self.assertIn("SH-PREFAB", review["rules"]["applied"])
        self.assertEqual([(w["code"], w["rule"]) for w in review["warnings"]],
                         [("project_rule_matches_nothing", "SH-WRONG")])
        self.assertFalse(os.path.exists(mps.code_review_path(self.repo)))  # no auto "nothing to review" record
        self.approve(["Game/Assets/Main.prefab"],
                     code_findings=["SH-PREFAB | blocker | Game/Assets/Main.prefab:1 | p | s"])
        self.assertEqual(self.commit("feat: MPS-74 a", "Game/Assets/Main.prefab")["error"], "code_review_blocked")
        # project setup checks the local copy against the tracked files.
        setup = self.mps("project", "setup")
        self.assertEqual([(w["code"], w["rule"]) for w in setup["warnings"]],
                         [("project_rule_matches_nothing", "SH-WRONG")])

    def test_rule_for_a_folder_this_change_adds_does_not_warn(self):
        """m-c: base files plus the changed paths are searched; a project ignore hiding a rule's files warns (m-b)."""
        self.push_project_rules("\n".join([
            "---", "ignore: Docs/**", "---",
            "## SH-NEW [major] Công cụ mới", "paths: Tools/New/**", "",
            "## SH-DOCS [blocker] Tài liệu", "paths: Docs/**", ""]))
        self.prepare("feature/MPS-77-a", "MPS-77")
        self.write("other.txt", "x\n")
        before = self.bundle()
        self.assertEqual(sorted(w["rule"] for w in before["warnings"] if w["code"] == "project_rule_matches_nothing"),
                         ["SH-DOCS", "SH-NEW"])
        self.write("Tools/New/a.txt", "new tool\n")
        self.write("Docs/guide.md", "guide\n")
        after = self.bundle()
        self.assertEqual([w["rule"] for w in after["warnings"] if w["code"] == "project_rule_matches_nothing"],
                         ["SH-DOCS"])
        self.assertIn("Docs/guide.md", after["ignored_files"])

    def test_reviews_must_use_the_recorded_base(self):
        """M2: the project rules come from origin/<base>, so a different base than the recorded one is refused."""
        self.prepare("feature/MPS-75-a", "MPS-75")
        self.write("a.txt", "a\n")
        refused = self.mps("git", "diff-for-review", "--base=release/1.0", "--to-file")
        self.assertEqual((refused["error"], refused["recorded_base"]), ("base_mismatch", "develop"))
        # Reviews made against another base (no record at that time) cannot be used once the base is recorded.
        self.git("config", "--unset", "branch.feature/MPS-75-a.mps-base")
        self.approve(["a.txt", "feature.txt"], base="release/1.0")
        self.git("config", "branch.feature/MPS-75-a.mps-base", "develop")
        before = self.head()
        self.assertEqual(self.commit("feat: MPS-75 a", "a.txt")["error"], "base_mismatch")
        self.assertEqual(self.head(), before)

    def test_mr_never_gets_an_outdated_review(self):
        """m1: a commit without its own record (write failed, or made by hand) never shows an older commit's report;
        a commit that fails keeps the previous, still valid record (m-a)."""
        branch = self.pushed_ticket_branch("MPS-76")
        with open(mps.committed_review_path(self.repo), "rb") as handle:
            record_a = handle.read()
        self.write("b.txt", "b\n")
        self.approve(["a.txt", "b.txt"])
        hook = os.path.join(self.repo, ".git", "hooks", "pre-commit")
        with open(hook, "w", newline="\n") as handle:
            handle.write("#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)
        self.assertEqual(self.commit("feat: MPS-76 b", "b.txt")["error"], "commit_failed")
        os.remove(hook)
        with open(mps.committed_review_path(self.repo), "rb") as handle:
            self.assertEqual(handle.read(), record_a)  # the rejected commit did not destroy A's record
        self.git("reset", "-q")  # the failed attempt left b.txt staged
        with mock.patch.object(mps, "_write_json", side_effect=OSError("disk full")):
            failed = self.commit("feat: MPS-76 b", "b.txt")
        self.assertEqual((failed["ok"], failed["code_review_recorded"]), (True, False))
        self.mps("git", "push", "--branch=" + branch, "--base=develop")
        gitlab = FakeMrGitLab()
        stale = self.ensure_mr(gitlab, branch, "MPS-76", code_review=True)
        self.assertEqual((stale["code_review_attached"], stale["code_review_reason"]), ("none", "outdated"))
        self.commit_and_push(branch, "MPS-76", "c.txt")
        self.git("commit", "-q", "--allow-empty", "-m", "feat: MPS-76 by hand")
        self.mps("git", "push", "--branch=" + branch, "--base=develop")
        outdated = self.ensure_mr(gitlab, branch, "MPS-76", code_review=True)
        self.assertEqual((outdated["code_review_attached"], outdated["code_review_reason"]), ("none", "outdated"))

    def test_commit_requires_a_code_review_of_the_same_bundle(self):
        """I1."""
        self.prepare("feature/MPS-67-a", "MPS-67")
        self.write("a.txt", "a\n")
        self.approve_scope_only(["a.txt"])
        missing = self.commit("feat: MPS-67 a", "a.txt")
        self.assertEqual((missing["error"], missing["reason"]), ("code_review_required", "missing"))
        bundle_a = self.make_bundle()
        self.review_code(bundle_a)
        with open(mps.code_review_path(self.repo), "rb") as handle:
            review_a = handle.read()
        self.approve_scope_only(["a.txt"])  # bundle B (it drops the pending review of A) ...
        with open(mps.code_review_path(self.repo), "wb") as handle:
            handle.write(review_a)  # ... even if A's review were put back, it does not count for B
        other = self.commit("feat: MPS-67 a", "a.txt")
        self.assertEqual((other["error"], other["reason"]), ("code_review_required", "other_bundle"))
        self.approve(["a.txt"])
        record = mps._read_json(mps.code_review_path(self.repo))
        mps._write_json(mps.code_review_path(self.repo), dict(record, head="0" * 40))
        moved = self.commit("feat: MPS-67 a", "a.txt")
        self.assertEqual((moved["error"], moved["reason"]), ("code_review_required", "branch_or_commit_changed"))
        bundle_id = self.make_bundle()
        self.classify(self.write_reply(bundle_id, ["a.txt"]))
        self.review_code(bundle_id, ["BASE-NEW-TODO | minor | a.txt:1 | p"])  # a malformed line
        self.assertEqual(self.commit("feat: MPS-67 a", "a.txt")["error"], "code_review_incomplete")
        self.assertEqual(self.git("diff", "--cached", "--name-only").strip(), "")

    def test_project_blocker_stops_the_commit_until_fixed(self):
        """I4: the Q1 path - nothing is staged; after a fix and two fresh reviews the commit goes through."""
        self.push_project_rules(PROJECT_RULES)
        self.prepare("feature/MPS-68-a", "MPS-68")
        self.write("a.txt", "print('debug')\n")
        before = self.head()
        self.approve(["a.txt"], code_findings=["SH-NO-PRINT | blocker | a.txt:1 | In ra console | Xoá dòng print"])
        blocked = self.commit("feat: MPS-68 a", "a.txt")
        self.assertEqual(blocked["error"], "code_review_blocked")
        self.assertEqual(blocked["blockers"], [{"rule": "SH-NO-PRINT", "title": "Không để lệnh print trong file",
                                                "path": "a.txt", "line": "1", "problem": "In ra console",
                                                "suggestion": "Xoá dòng print"}])
        self.assertEqual(self.head(), before)
        self.assertEqual(self.git("diff", "--cached", "--name-only").strip(), "")
        self.assertTrue(os.path.exists(mps.code_review_path(self.repo)))
        self.write("a.txt", "fixed\n")
        self.assertEqual(self.commit("feat: MPS-68 a", "a.txt")["error"], "changed_since_review")
        self.approve(["a.txt"])
        done = self.commit("feat: MPS-68 a", "a.txt")
        self.assertEqual((done["ok"], done["code_review_warning_count"], done["code_review_recorded"]), (True, 0, True))

    def test_warnings_never_block(self):
        """I5: severity comes from the rule; the review moves to committed_review.json."""
        self.prepare("feature/MPS-69-a", "MPS-69")
        self.write("a.txt", "a\n")
        self.approve(["a.txt"], code_findings=["BASE-DEBUG-LEFTOVER | major | a.txt:1 | p | s"])
        done = self.commit("feat: MPS-69 a", "a.txt")
        self.assertEqual((done["ok"], done["code_review_warning_count"]), (True, 1))
        committed = mps._read_json(mps.committed_review_path(self.repo))
        self.assertEqual((committed["committed_as"], committed["findings"][0]["severity"],
                          committed["findings"][0]["severity_corrected"]), (self.head(), "minor", True))
        self.assertFalse(os.path.exists(mps.code_review_path(self.repo)))

    def test_blocker_in_an_excluded_file(self):
        """I8: it does not stop the other files, and the file cannot be force-included."""
        self.push_project_rules(PROJECT_RULES)
        self.prepare("feature/MPS-71-a", "MPS-71")
        self.write("a.txt", "a\n")
        self.write("b.txt", "print('x')\n")
        blocker = ["SH-NO-PRINT | blocker | b.txt:1 | p | s"]
        self.approve(["a.txt"], out_of_scope=["b.txt"], code_findings=blocker)
        self.assertTrue(self.commit("feat: MPS-71 a", "a.txt")["ok"])
        self.approve(["a.txt"], out_of_scope=["b.txt"], code_findings=blocker)  # a.txt: already committed
        forced = self.mps("git", "commit", "--message=feat: MPS-71 b", "--files", "b.txt",
                          "--include-out-of-scope", "b.txt")
        self.assertEqual((forced["error"], forced["blockers"][0]["path"]), ("code_review_blocked", "b.txt"))

    def test_review_findings_end_to_end(self):
        """Checkpoint 2 + I10: findings are matched against the real bundle; a non-ASCII path is accepted."""
        self.push_project_rules(PROJECT_RULES)
        self.prepare("feature/MPS-66-a", "MPS-66")
        self.write("a.txt", "print('x')\n")
        self.write("Assets/Tiếng Việt/Chào.cs", "class C {}\n")
        self.assertEqual(self.review_code("0" * 32)["reason"], "no_bundle")
        bundle_id = self.bundle()["bundle_id"]
        result = self.review_code(bundle_id, ["SH-NO-PRINT | blocker | a.txt:1 | In ra console | Xoá dòng print",
                                              "BASE-DEBUG-LEFTOVER | minor | Assets/Tiếng Việt/Chào.cs:1 | p | s",
                                              "BASE-NOPE | major | a.txt:1 | p | s"])
        self.assertEqual((result["complete"], result["needs_reviewer_fix"], result["dropped_count"]), (True, False, 1))
        self.assertEqual([(f["rule"], f["path"]) for f in result["blockers_in_candidates"]], [("SH-NO-PRINT", "a.txt")])
        self.assertEqual([f["path"] for f in result["rule_warnings"]], ["Assets/Tiếng Việt/Chào.cs"])
        self.assertEqual(result["dropped_findings"][0]["reason"], "unknown_rule")
        record = mps._read_json(mps.code_review_path(self.repo))
        self.assertEqual((record["bundle_id"], record["complete"], len(record["blockers"])), (bundle_id, True, 1))
        # Fail-closed: an unparsable reply or a bundle without the code review removes the pending record.
        unparsable = self.mps("review", "findings", "--base=develop",
                              "--result-file=" + self.write_reply(bundle_id, ["a.txt"]))
        self.assertEqual(unparsable["error"], "code_review_unparsable")
        self.assertFalse(os.path.exists(mps.code_review_path(self.repo)))
        plain = self.mps("git", "diff-for-review", "--base=develop")["bundle_id"]
        self.assertEqual(self.review_code(plain)["reason"], "no_code_bundle")
        bundle_id = self.bundle()["bundle_id"]
        self.write("a.txt", "print('x')\nprint('y')\n")
        self.assertEqual(self.review_code(bundle_id)["reason"], "files_changed")

    def commit_and_push(self, branch, key, path, findings=()):
        """Write `path`, review both ways (every earlier file of the branch is already committed), commit, push."""
        self.write(path, "%s %s\n" % (path, key))
        committed = [p for p in self.git("diff", "--name-only", "origin/develop...HEAD").split() if p != path]
        self.approve(committed + [path], code_findings=findings)
        self.assertTrue(self.commit("feat: %s %s" % (key, path), path)["ok"])
        self.mps("git", "push", "--branch=" + branch, "--base=develop")

    def test_mr_gets_the_code_review_report(self):
        """I9: new MR -> description; existing MR -> one note per committed review; failures are warnings."""
        branch = self.pushed_ticket_branch("MPS-72")
        gitlab = FakeMrGitLab()
        created = self.ensure_mr(gitlab, branch, "MPS-72", code_review=True)
        self.assertEqual((created["existed"], created["code_review_attached"], created["code_review_warning_count"]),
                         (False, "description", 0))
        description = gitlab.bodies("POST")[0]["description"]
        self.assertTrue(description.startswith("Close MPS-72\n\n### Kết quả review code tự động\n"), description)
        review = mps._read_json(mps.committed_review_path(self.repo))
        self.assertEqual(review["mr_note"], "1:" + review["bundle_id"])
        again = self.ensure_mr(gitlab, branch, "MPS-72", code_review=True)
        self.assertEqual((again["existed"], again["code_review_attached"], gitlab.notes), (True, "already", []))
        self.commit_and_push(branch, "MPS-72", "b.txt", ["BASE-DEBUG-LEFTOVER | minor | b.txt:1 | Còn log | Xoá"])
        noted = self.ensure_mr(gitlab, branch, "MPS-72", code_review=True)
        self.assertEqual((noted["code_review_attached"], noted["code_review_warning_count"]), ("note", 1))
        self.assertEqual([path for path, _ in gitlab.notes], ["/projects/1/merge_requests/1/notes"])
        self.assertIn("`BASE-DEBUG-LEFTOVER` · `b.txt:1` · Còn log", gitlab.notes[0][1])
        self.assertEqual(self.ensure_mr(gitlab, branch, "MPS-72", code_review=True)["code_review_attached"], "already")
        self.commit_and_push(branch, "MPS-72", "c.txt")
        failing = FakeMrGitLab(mrs=gitlab.mrs, notes_status=500)
        failed = self.ensure_mr(failing, branch, "MPS-72", code_review=True)
        self.assertEqual((failed["ok"], failed["code_review_attached"], failed["code_review_reason"]),
                         (True, "none", "note_failed"))
        self.assertEqual([w["code"] for w in failed["warnings"]], ["code_review_note_failed"])
        self.write("d.txt", "not pushed\n")
        self.approve(["a.txt", "b.txt", "c.txt", "d.txt"])
        self.commit("feat: MPS-72 d", "d.txt")
        unpushed = self.ensure_mr(gitlab, branch, "MPS-72", code_review=True)
        self.assertEqual((unpushed["code_review_attached"], unpushed["code_review_reason"]), ("none", "not_in_branch"))
        self.assertEqual(mps._select_committed_review(self.repo, "feature/MPS-1-other"), (None, "other_branch"))
        plain = self.ensure_mr(gitlab, branch, "MPS-72")
        self.assertNotIn("code_review_attached", plain)

    def test_resume_keeps_the_mr_report(self):
        """I12: step 6 running again after the commit does not touch the committed review."""
        self.write_env(MPS_GITLAB_URL="https://git.example", MPS_GITLAB_PAT="gitlab-token",
                       MPS_GITLAB_PROJECT="grp/proj")
        branch = "feature/MPS-73-a"
        self.prepare(branch, "MPS-73")
        self.write("a.txt", "a\n")
        self.write("left.txt", "not for this ticket\n")
        self.approve(["a.txt"], out_of_scope=["left.txt"], code_findings=["BASE-NEW-TODO | minor | a.txt:1 | p | s"])
        self.commit("feat: MPS-73 a", "a.txt")
        with open(mps.committed_review_path(self.repo), "rb") as handle:
            before = handle.read()
        bundle_id = self.make_bundle()
        self.review_code(bundle_id)
        with open(mps.committed_review_path(self.repo), "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.mps("git", "push", "--branch=" + branch, "--base=develop")
        result = self.ensure_mr(FakeMrGitLab(), branch, "MPS-73", code_review=True)
        self.assertEqual((result["code_review_attached"], result["code_review_warning_count"]), ("description", 1))


# ---------------------------------------------------------------------------
# 0.1.1: project integration, version check, release discipline, bootstrap
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PLUGIN_DIR = os.path.join(REPO_ROOT, "plugins", "mps-git-flow")
SCRIPTS_DIR = os.path.join(PLUGIN_DIR, "skills", "mps-git-flow", "scripts")
BOOTSTRAP_PS1 = os.path.join(SCRIPTS_DIR, "bootstrap.ps1")
BOOTSTRAP_SH = os.path.join(SCRIPTS_DIR, "bootstrap.sh")
UTF8_BOM = b"\xef\xbb\xbf"
NEW_SETTINGS_CHANGES = ["marketplace_added", "plugin_enabled", "attribution_disabled"]
EXPECTED_MARKETPLACE = {"source": {"source": "github", "repo": "madpoly-studio/mps-cicd-agent-flow"}, "autoUpdate": True}
BOOTSTRAP_KEYS = ("ok", "os", "python_cmd", "missing", "manual_steps")
BOOTSTRAP_TIMEOUT_SECONDS = 120
# A fake installer outlives the tiny test budget by far; the pipe must close long before it ends.
SLOW_INSTALLER_SECONDS = 25
PIPE_CLOSE_MAX_SECONDS = 15
# The stalled lookup is given 0.2 s; anything near the real 3 s would mean the thread limit does not work.
STALLED_LOOKUP_MAX_SECONDS = 2
# A project rule file with one blocker rule for the .txt files of the test repo (pushed to origin/develop).
PROJECT_RULES = "\n".join([
    "---", "version: 1", "---", "# Quy tắc dự án",
    "## SH-NO-PRINT [blocker] Không để lệnh print trong file", "paths: **/*.txt", "",
    "Không in ra console.", ""])
# R1: the scope bundle of GitFlowTests.golden_scope_bundle(), recorded from 0.1.1 before the code review was added.
GOLDEN_SCOPE_BUNDLE = "\n".join([
    "# Change bundle for scope review",
    "",
    "Bundle-ID: <BUNDLE-ID>",
    "(copy it into your reply as the line `BUNDLE: <BUNDLE-ID>`)",
    "",
    "Base: origin/develop. Truncated: no.",
    "",
    "## 0. Files to classify (each must appear exactly once in your FILES: block)",
    "",
    "- app.txt",
    "- new.txt",
    "- src/a.txt",
    "",
    "## 1. Commits on this branch not yet in origin/develop",
    "",
    "```diff",
    "diff --git a/src/a.txt b/src/a.txt",
    "new file mode 100644",
    "index 0000000..0016606",
    "--- /dev/null",
    "+++ b/src/a.txt",
    "@@ -0,0 +1,2 @@",
    "+a1",
    "+a2",
    "",
    "```",
    "",
    "## 2. Uncommitted changes (staged + unstaged)",
    "",
    "```diff",
    "diff --git a/app.txt b/app.txt",
    "index c0d0fb4..b87cf49 100644",
    "--- a/app.txt",
    "+++ b/app.txt",
    "@@ -1,2 +1,2 @@",
    " line1",
    "-line2",
    "+line2 edited",
    "",
    "```",
    "",
    "## 3. New untracked files",
    "",
    "### new.txt",
    "",
    "```",
    "brand new",
    "",
    "```",
    "",
    "",
    "## 4. Secret files (changed, content hidden)",
    "",
    "- cfg/.env.local: [content hidden]",
]) + "\n"


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


class MergeProjectSettingsTests(unittest.TestCase):
    """U1."""

    def test_empty_settings_get_both_entries(self):
        merged, changes, warnings = mps.merge_project_settings({})
        self.assertEqual(merged, {"extraKnownMarketplaces": {"mps-cdci-agents": EXPECTED_MARKETPLACE},
                                  "enabledPlugins": {"mps-git-flow@mps-cdci-agents": True},
                                  "attribution": {"commit": "", "pr": "", "sessionUrl": False}})
        self.assertEqual((changes, warnings), (NEW_SETTINGS_CHANGES, []))

    def test_unrelated_keys_and_order_kept_input_not_mutated(self):
        settings = {"permissions": {"allow": ["Bash(ls)"]}, "env": {"A": "1"}, "hooks": {"Stop": []}}
        original = json.loads(json.dumps(settings))
        merged, _, _ = mps.merge_project_settings(settings)
        self.assertEqual(list(merged), ["permissions", "env", "hooks", "extraKnownMarketplaces", "enabledPlugins",
                                        "attribution"])
        self.assertEqual(merged["hooks"], {"Stop": []})
        self.assertEqual(settings, original)

    def test_existing_entry_auto_update_turned_on(self):
        settings = {"extraKnownMarketplaces": {"mps-cdci-agents": {
            "source": {"source": "github", "repo": "madpoly-studio/mps-cicd-agent-flow"}, "autoUpdate": False}},
            "enabledPlugins": {"mps-git-flow@mps-cdci-agents": False}}
        merged, changes, warnings = mps.merge_project_settings(settings)
        self.assertEqual(changes, ["auto_update_enabled", "plugin_enabled", "attribution_disabled"])
        self.assertEqual(warnings, [])
        self.assertIs(merged["extraKnownMarketplaces"]["mps-cdci-agents"]["autoUpdate"], True)
        self.assertIs(merged["enabledPlugins"]["mps-git-flow@mps-cdci-agents"], True)

    def test_pinned_ref_is_not_a_different_source(self):
        entry = {"source": {"source": "github", "repo": "madpoly-studio/mps-cicd-agent-flow", "ref": "v0.1.1"},
                 "autoUpdate": True}
        merged, changes, warnings = mps.merge_project_settings({"extraKnownMarketplaces": {"mps-cdci-agents": entry}})
        self.assertEqual((changes, warnings), (["plugin_enabled", "attribution_disabled"], []))
        self.assertEqual(merged["extraKnownMarketplaces"]["mps-cdci-agents"]["source"]["ref"], "v0.1.1")

    def test_legacy_repo_is_migrated_keeping_ref(self):
        for legacy in mps.LEGACY_MARKETPLACE_REPOS:
            for extra in ({}, {"ref": "v0.1.1"}):
                source = dict({"source": "github", "repo": legacy}, **extra)
                settings = {"extraKnownMarketplaces": {"mps-cdci-agents": {"source": source, "autoUpdate": True}},
                            "enabledPlugins": {"mps-git-flow@mps-cdci-agents": True}, "attribution": False}
                original = copy.deepcopy(settings)
                merged, changes, warnings = mps.merge_project_settings(settings)
                self.assertEqual((changes, warnings), (["marketplace_source_migrated"], []))
                self.assertEqual(merged["extraKnownMarketplaces"]["mps-cdci-agents"]["source"],
                                 dict({"source": "github", "repo": mps.MARKETPLACE_REPO}, **extra))
                self.assertEqual(settings, original)

    def test_legacy_repo_migration_edge_cases(self):
        upper = {"source": {"source": "github", "repo": "Hung-Bui-121/MPS-CDCI-Agents"}, "autoUpdate": False}
        merged, changes, warnings = mps.merge_project_settings({"extraKnownMarketplaces": {"mps-cdci-agents": upper}})
        self.assertEqual((changes[:2], warnings), (["marketplace_source_migrated", "auto_update_enabled"], []))
        self.assertEqual(merged["extraKnownMarketplaces"]["mps-cdci-agents"]["source"]["repo"], mps.MARKETPLACE_REPO)
        # Every form the legacy check recognises is moved, so `legacy_project_source` always has a fix.
        for legacy, expected in (
                ({"source": "github", "repo": mps.LEGACY_MARKETPLACE_REPOS[0], "path": "x"},
                 mps._expected_marketplace_source()),
                ({"source": "git", "url": "https://github.com/hung-bui-121/mps-cdci-agents.git", "ref": "main"},
                 dict(mps._expected_marketplace_source(), ref="main"))):
            merged, changes, warnings = mps.merge_project_settings(
                {"extraKnownMarketplaces": {"mps-cdci-agents": {"source": legacy, "autoUpdate": True}}})
            self.assertEqual(changes[:1], ["marketplace_source_migrated"])
            self.assertEqual(warnings, [])
            self.assertEqual(merged["extraKnownMarketplaces"]["mps-cdci-agents"]["source"], expected)
            self.assertFalse(mps.project_declares_legacy_source(merged))

    def test_different_source_is_kept_and_reported(self):
        local = {"source": "directory", "path": "D:/work/mps-cdci-agents"}
        settings = {"extraKnownMarketplaces": {"mps-cdci-agents": {"source": local, "autoUpdate": True}}}
        merged, _, warnings = mps.merge_project_settings(settings)
        self.assertEqual(merged["extraKnownMarketplaces"]["mps-cdci-agents"]["source"], local)
        self.assertEqual([(w["code"], w["source"]) for w in warnings], [("marketplace_source_differs", local)])
        self.assertIn("D:/work/mps-cdci-agents", warnings[0]["message"])

    def test_second_merge_is_a_no_op(self):
        merged, _, _ = mps.merge_project_settings({"model": "x"})
        again, changes, warnings = mps.merge_project_settings(merged)
        self.assertEqual((again, changes, warnings), (merged, [], []))

    def test_unexpected_types_conflict(self):
        for settings, key in (({"extraKnownMarketplaces": []}, "extraKnownMarketplaces"),
                              ({"extraKnownMarketplaces": {"mps-cdci-agents": "x"}},
                               "extraKnownMarketplaces.mps-cdci-agents"),
                              ({"extraKnownMarketplaces": {"mps-cdci-agents": None}},
                               "extraKnownMarketplaces.mps-cdci-agents"),
                              ({"enabledPlugins": ["mps-git-flow@mps-cdci-agents"]}, "enabledPlugins")):
            with self.assertRaises(mps.MpsError) as ctx:
                mps.merge_project_settings(settings)
            self.assertEqual((ctx.exception.code, ctx.exception.extra["key"]), ("settings_conflict", key))


class AttributionSettingTests(unittest.TestCase):
    """`project setup` hides Claude Code's commit / PR attribution without overwriting the project's own choice."""

    def test_partial_attribution_gets_only_the_missing_parts(self):
        merged, changes, warnings = mps.merge_project_settings({"attribution": {"pr": ""}})
        self.assertEqual(merged["attribution"], {"pr": "", "commit": "", "sessionUrl": False})
        self.assertIn("attribution_disabled", changes)
        self.assertEqual(warnings, [])

    def test_custom_attribution_is_kept_and_reported(self):
        custom = {"commit": "Made by the team", "pr": "", "sessionUrl": True}
        merged, changes, warnings = mps.merge_project_settings({"attribution": dict(custom)})
        self.assertEqual(merged["attribution"], custom)
        self.assertNotIn("attribution_disabled", changes)
        self.assertEqual([(w["code"], w["keys"]) for w in warnings], [("attribution_kept", ["commit", "sessionUrl"])])

    def test_false_already_hides_everything(self):
        merged, changes, _ = mps.merge_project_settings({"attribution": False})
        self.assertIs(merged["attribution"], False)
        self.assertNotIn("attribution_disabled", changes)

    def test_unexpected_type_conflicts(self):
        with self.assertRaises(mps.MpsError) as ctx:
            mps.merge_project_settings({"attribution": "none"})
        self.assertEqual((ctx.exception.code, ctx.exception.extra["key"]), ("settings_conflict", "attribution"))


class StripAiAttributionTests(unittest.TestCase):
    def test_claude_lines_removed_human_lines_kept(self):
        text = "\n".join([
            "feat: MPS-1 Thêm màn hình",
            "",
            "Close MPS-1",
            "Co-Authored-By: Lan Nguyen <lan@example.com>",
            "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
            "  co-authored-by: Someone <bot@anthropic.com>  ",
            "Claude-Session: https://claude.ai/code/session_1",
            "\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)",
            "Generated with Claude Code",
            "",
            "",
        ])
        cleaned, removed = mps.strip_ai_attribution(text)
        self.assertTrue(removed)
        self.assertEqual(cleaned, "feat: MPS-1 Thêm màn hình\n\nClose MPS-1\n"
                                  "Co-Authored-By: Lan Nguyen <lan@example.com>")

    def test_text_without_attribution_is_untouched(self):
        for text in ("Close MPS-2\n\n", "fix: MPS-3 Claude là tên nhân vật trong game", "Generated with care", ""):
            self.assertEqual(mps.strip_ai_attribution(text), (text, False))

    def test_human_lines_mentioning_claude_are_kept(self):
        for line in ("Co-Authored-By: Claude Martin <claude.martin@vng.com.vn>", "claude-api: bump SDK",
                     "Generated with the OpenAPI generator for the claude endpoint", "Close MPS-12",
                     "Claude-Version: 3 (header documented in the API)", "See https://claude.ai/code for details"):
            self.assertEqual(mps.strip_ai_attribution(line), (line, False), line)

    def test_ai_forms_are_stripped(self):
        for line in ("Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>",
                     "Co-Authored-By: Claude <noreply@anthropic.com>",
                     "Co-Authored-By: Claude Code",
                     "\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)",
                     "Generated by Claude Code",
                     "https://claude.ai/code/session_01AbCdEf",
                     "Claude-Session: abc"):
            self.assertEqual(mps.strip_ai_attribution("Close MPS-12\n" + line), ("Close MPS-12", True), line)

    def test_only_attribution_leaves_nothing(self):
        self.assertEqual(mps.strip_ai_attribution("Co-Authored-By: Claude <noreply@anthropic.com>\n"), ("", True))


class LabelMatchTests(unittest.TestCase):
    def test_match_ignores_case_and_returns_the_exact_name(self):
        self.assertEqual(mps.match_label_name([{"name": "Bug report"}, {"name": "bug"}], "Bug"), "bug")
        self.assertEqual(mps.match_label_name(["ENHANCEMENT"], "Enhancement"), "ENHANCEMENT")
        self.assertIsNone(mps.match_label_name([{"name": "Bugfix"}], "Bug"))
        self.assertIsNone(mps.match_label_name(None, "Bug"))

    def test_assignee_usernames(self):
        self.assertEqual(mps.mr_assignee_usernames({"assignees": [{"username": "a"}, {"username": "b"}]}), ["a", "b"])
        self.assertEqual(mps.mr_assignee_usernames({"assignees": [], "assignee": {"username": "c"}}), ["c"])
        self.assertEqual(mps.mr_assignee_usernames({}), [])


class SettingsTextTests(unittest.TestCase):
    """U2."""

    def test_bom_and_empty_text(self):
        self.assertEqual(mps.parse_settings_text(chr(0xFEFF) + '{"a": 1}'), {"a": 1})
        self.assertEqual(mps.parse_settings_text(" \r\n"), {})

    def test_not_object_and_invalid_json(self):
        with self.assertRaises(mps.MpsError) as ctx:
            mps.parse_settings_text("[1]")
        self.assertEqual(ctx.exception.code, "settings_not_object")
        with self.assertRaises(mps.MpsError) as ctx:
            mps.parse_settings_text('{\n  "a":')
        self.assertEqual(ctx.exception.code, "settings_invalid_json")
        self.assertEqual((ctx.exception.extra["line"], ctx.exception.extra["column"]), (2, 7))

    def test_render_keeps_vietnamese_and_newline_style(self):
        settings = {"note": "Tiếng Việt", "nested": {"a": [1, 2]}}
        text = mps.render_settings_json(settings, "\r\n")
        self.assertIn('"Tiếng Việt"', text)
        self.assertTrue(text.endswith("}\r\n"))
        self.assertNotIn("\n", text.replace("\r\n", ""))
        self.assertEqual(mps.parse_settings_text(text), settings)
        self.assertTrue(mps.render_settings_json({}, "\n").endswith("\n"))


class PluginVersionTests(unittest.TestCase):
    """U3, U4."""

    def test_parse_and_compare(self):
        self.assertEqual(mps.parse_plugin_version("0.1.10"), (0, 1, 10))
        self.assertEqual(mps.parse_plugin_version("v0.2.0"), (0, 2, 0))
        self.assertTrue(mps.is_newer_version("0.1.10", "0.1.9"))
        self.assertTrue(mps.is_newer_version("0.2.0", "0.1.99"))
        self.assertTrue(mps.is_newer_version("v0.2.0", "0.1.1"))
        self.assertFalse(mps.is_newer_version("0.1.1", "0.1.1"))
        self.assertFalse(mps.is_newer_version("0.1.0", "0.1.1"))
        for bad in ("", "1.x", "1.2", None, 3):
            self.assertIsNone(mps.parse_plugin_version(bad))
            self.assertFalse(mps.is_newer_version(bad, "0.1.0"))
            self.assertFalse(mps.is_newer_version("9.9.9", bad))

    def test_update_blockers(self):
        self.assertEqual(mps.update_blockers({}), [])
        self.assertEqual(mps.update_blockers({"DISABLE_AUTOUPDATER": "1", "DISABLE_UPDATES": "",
                                              "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}),
                         ["DISABLE_AUTOUPDATER", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"])
        self.assertEqual(mps.update_blockers({"DISABLE_UPDATES": "1", "FORCE_AUTOUPDATE_PLUGINS": "1"}), [])


class FakeHttpResponse(object):
    def __init__(self, status, body):
        self.status = status
        self.body = body

    def read(self, size=-1):
        self.size = size
        return self.body if size < 0 else self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FetchLatestVersionTests(unittest.TestCase):
    """U4: the GitHub lookup never raises and never sends a token."""

    def setUp(self):
        self.cfg = mps.Config(tempfile.gettempdir(), {"MPS_GITLAB_PAT": "gitlab-token"}, True)

    def fetch(self, outcome, environ=None):
        opener = mock.Mock()
        if isinstance(outcome, BaseException):
            opener.open.side_effect = outcome
        else:
            opener.open.return_value = outcome
        with mock.patch.object(mps.urllib.request, "build_opener", return_value=opener) as build:
            version = mps.fetch_latest_plugin_version(self.cfg, environ if environ is not None else {})
        return version, build, opener

    def test_version_from_manifest(self):
        version, _, opener = self.fetch(FakeHttpResponse(200, b'{"name": "mps-git-flow", "version": "0.2.0"}'))
        self.assertEqual(version, "0.2.0")
        request = opener.open.call_args[0][0]
        self.assertEqual(request.full_url, mps.PLUGIN_MANIFEST_URL)
        self.assertEqual(set(k.lower() for k in request.headers), {"user-agent"})
        self.assertEqual(opener.open.call_args[1]["timeout"], mps.VERSION_CHECK_TIMEOUT_SECONDS)

    def test_failures_give_none(self):
        not_found = mps.urllib.error.HTTPError(mps.PLUGIN_MANIFEST_URL, 404, "Not Found", {}, io.BytesIO(b""))
        for outcome in (socket.timeout("timed out"), not_found, FakeHttpResponse(200, b"<html>"),
                        FakeHttpResponse(200, b'{"name": "x"}'), FakeHttpResponse(200, b'{"version": "1.x"}'),
                        FakeHttpResponse(204, b"")):
            self.assertIsNone(self.fetch(outcome)[0], outcome)

    def test_nonessential_traffic_off_makes_no_request(self):
        version, build, _ = self.fetch(FakeHttpResponse(200, b'{"version": "9.9.9"}'),
                                       environ={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
        self.assertIsNone(version)
        build.assert_not_called()

    def test_disable_autoupdater_still_checks(self):
        version, _, _ = self.fetch(FakeHttpResponse(200, b'{"version": "9.9.9"}'), environ={"DISABLE_AUTOUPDATER": "1"})
        self.assertEqual(version, "9.9.9")

    def test_body_read_is_bounded(self):
        response = FakeHttpResponse(200, b'{"version": "0.3.0"}')
        self.assertEqual(self.fetch(response)[0], "0.3.0")
        self.assertEqual(response.size, mps.MANIFEST_MAX_BYTES)

    def test_stalled_lookup_returns_within_the_limit(self):
        """A lookup that hangs (e.g. DNS) is abandoned after the timeout; env check is not delayed further."""
        release = threading.Event()
        self.addCleanup(release.set)
        opener = mock.Mock()
        opener.open.side_effect = lambda *args, **kwargs: release.wait(30)
        with mock.patch.object(mps.urllib.request, "build_opener", return_value=opener), \
                mock.patch.object(mps, "VERSION_CHECK_TIMEOUT_SECONDS", 0.2):
            started = time.monotonic()
            version = mps.fetch_latest_plugin_version(self.cfg, {})
            elapsed = time.monotonic() - started
        self.assertIsNone(version)
        self.assertLess(elapsed, STALLED_LOOKUP_MAX_SECONDS)


class IntegrationStatusTests(unittest.TestCase):
    """U5."""

    def test_pinned_marketplace_ref(self):
        def settings(source):
            return {"extraKnownMarketplaces": {"mps-cdci-agents": {"source": source}}}
        self.assertEqual(mps.pinned_marketplace_ref(settings({"source": "github", "repo": "r", "ref": "v0.1.1"})),
                         "v0.1.1")
        for value in (settings({"source": "github", "repo": "r"}), settings({"ref": " "}), settings("x"), None, {},
                      {"extraKnownMarketplaces": {"mps-cdci-agents": None}}):
            self.assertIsNone(mps.pinned_marketplace_ref(value))

    def test_detect_json_indent(self):
        self.assertEqual(mps.detect_json_indent('{\n    "a": 1\n}\n'), 4)
        self.assertEqual(mps.detect_json_indent('{\r\n\t"a": 1\r\n}\r\n'), "\t")
        self.assertEqual(mps.detect_json_indent('{"a": 1}'), mps.DEFAULT_SETTINGS_INDENT)
        self.assertEqual(mps.detect_json_indent(""), mps.DEFAULT_SETTINGS_INDENT)
        self.assertIn('\n\t"a"', mps.render_settings_json({"a": 1}, "\n", "\t"))

    def test_status(self):
        self.assertEqual(mps.project_integration_status({}), "missing")
        self.assertEqual(mps.project_integration_status({"enabledPlugins": {mps.PLUGIN_KEY: False}}), "missing")
        self.assertEqual(mps.project_integration_status({"enabledPlugins": {mps.PLUGIN_KEY: True}}), "integrated")
        self.assertEqual(mps.project_integration_status({"enabledPlugins": [mps.PLUGIN_KEY]}), "missing")


class ReleaseDisciplineTests(unittest.TestCase):
    """U6: every release bumps mps.VERSION and plugin.json together and documents itself."""

    def test_plugin_json_version_matches_script(self):
        manifest = json.loads(_read_bytes(os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json")).decode("utf-8"))
        self.assertEqual(manifest["version"], mps.VERSION)

    def test_changelog_has_entry(self):
        changelog = _read_bytes(os.path.join(REPO_ROOT, "CHANGELOG.md")).decode("utf-8")
        self.assertRegex(changelog, r"(?m)^## " + re.escape(mps.VERSION) + r"(\s|$)")

    def test_release_notes_cover_every_version_newest_first(self):
        """What members see after an update (hooks/whats-new.sh) must exist for every version, newest on top."""
        def versions(path):
            text = _read_bytes(path).decode("utf-8").replace("\r\n", "\n")
            return re.findall(r"(?m)^## (\S+)", text), text
        notes, text = versions(os.path.join(PLUGIN_DIR, "RELEASE_NOTES.md"))
        changelog, _ = versions(os.path.join(REPO_ROOT, "CHANGELOG.md"))
        self.assertEqual(notes[0], mps.VERSION)
        self.assertEqual(notes, changelog)
        for section in re.split(r"(?m)^## \S+.*$", text)[1:]:
            self.assertRegex(section, r"(?m)^- \S")  # at least one bullet per version

    def test_marketplace_has_no_plugin_version(self):
        marketplace = json.loads(_read_bytes(os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json"))
                                 .decode("utf-8"))
        entry = [p for p in marketplace["plugins"] if p["name"] == "mps-git-flow"][0]
        self.assertNotIn("version", entry)

    def test_readme_settings_block_matches_project_setup(self):
        readme = _read_bytes(os.path.join(REPO_ROOT, "README.md")).decode("utf-8")
        blocks = [b for b in re.findall(r"```json\n(.*?)```", readme, re.DOTALL) if "extraKnownMarketplaces" in b]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(json.loads(textwrap.dedent(blocks[0])), mps.merge_project_settings({})[0])


class BootstrapFileHygieneTests(unittest.TestCase):
    """U7: encodings and PowerShell 5.1 / POSIX guards that a casual edit could break."""

    def test_ps1_has_bom_and_no_ps6_tokens(self):
        data = _read_bytes(BOOTSTRAP_PS1)
        self.assertTrue(data.startswith(UTF8_BOM))
        text = data.decode("utf-8")
        for token in ("??", "&&", "$IsWindows"):
            self.assertNotIn(token, text)

    def test_sh_is_lf_without_bom(self):
        data = _read_bytes(BOOTSTRAP_SH)
        self.assertNotIn(b"\r", data)
        self.assertFalse(data.startswith(UTF8_BOM))

    def test_no_prompts(self):
        for path in (BOOTSTRAP_PS1, BOOTSTRAP_SH):
            text = _read_bytes(path).decode("utf-8-sig")
            self.assertNotIn("Read-Host", text)
            self.assertIsNone(re.search(r"(^|[\s;&|(])read\s", text, re.MULTILINE), path)


class EnvTemplateTests(unittest.TestCase):
    """R.11.4: the member keys come first and blank; everything else keeps the defaults."""

    def setUp(self):
        self.text = _read_bytes(mps.ENV_TEMPLATE_PATH).decode("utf-8")
        self.values = mps.parse_env(self.text)

    def test_member_keys_first_and_blank(self):
        keys = [m.group(1) for m in (mps._ENV_LINE_RE.match(line.strip()) for line in self.text.splitlines()
                                     if line.strip() and not line.strip().startswith("#")) if m]
        self.assertEqual(keys[:3], list(mps.MEMBER_KEYS))
        for key in mps.MEMBER_KEYS:
            self.assertEqual(self.values[key], "")

    def test_every_other_key_present_with_default(self):
        for key in mps.KNOWN_KEYS:
            self.assertIn(key, self.values)
            if key in mps.DEFAULTS:
                self.assertEqual(self.values[key], mps.DEFAULTS[key])

    def test_template_holds_no_secret_pattern(self):
        self.assertEqual([f for f in mps.scan_text("env.example", self.text) if not f["confirmable"]], [])


class EnvFillGuideTests(unittest.TestCase):
    """R.11.2 / R.11.4."""

    def test_blank_member_keys_in_order_with_links(self):
        guide = mps.env_fill_guide({"MPS_JIRA_PROJECT_KEY": " "}, "https://jira.example/", "https://git.example")
        self.assertEqual([g["key"] for g in guide], list(mps.MEMBER_KEYS))
        links = dict((g["key"], g["link"]) for g in guide)
        self.assertEqual(links["MPS_JIRA_PAT"], "https://jira.example" + mps.JIRA_PAT_PAGE)
        self.assertEqual(links["MPS_GITLAB_PAT"], "https://git.example/-/user_settings/personal_access_tokens"
                                                  "?name=mps-git-flow&scopes=api,write_repository")
        self.assertIsNone(links["MPS_JIRA_PROJECT_KEY"])
        self.assertTrue(all(g["label"] and g["steps"] for g in guide))

    def test_subset_is_ordered_and_tokens_never_copied(self):
        values = {"MPS_JIRA_PAT": "super-secret-jira", "MPS_GITLAB_PAT": "super-secret-gitlab"}
        self.assertEqual([g["key"] for g in mps.env_fill_guide(values, "https://j", "https://g")],
                         ["MPS_JIRA_PROJECT_KEY"])
        guide = mps.env_fill_guide(values, "https://j", "https://g", keys=["MPS_GITLAB_PAT", "MPS_JIRA_PAT"],
                                   token_rejected=True)
        self.assertEqual([g["key"] for g in guide], ["MPS_JIRA_PAT", "MPS_GITLAB_PAT"])
        self.assertTrue(all("hết hạn" in g["steps"][0] for g in guide))
        dumped = json.dumps(guide, ensure_ascii=False)
        self.assertNotIn("super-secret", dumped)

    def test_deleted_default_line_is_restored(self):
        guide = mps.env_fill_guide({}, "https://j", "https://g", keys=["MPS_GITLAB_URL"])
        self.assertEqual(guide[0]["steps"], ["Khôi phục dòng mặc định trong file .env: "
                                             "MPS_GITLAB_URL=https://git-gst.mto.zing.vn"])


# ---------------------------------------------------------------------------
# 0.2.0: code review rules, numbered net diff, findings (pure)
# ---------------------------------------------------------------------------

REVIEW_DIR = os.path.join(SCRIPTS_DIR, "..", "references", "review")
JIRA_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*-[0-9]+")


def rule_file(*rules, **frontmatter):
    """A rule file: optional frontmatter (key=value), then `rules` given as (heading, body) pairs or full text."""
    parts = []
    if frontmatter:
        parts.append("---")
        parts.extend("%s: %s" % item for item in frontmatter.items())
        parts.append("---")
    parts.append("# Title")
    for rule in rules:
        parts.extend(["", rule[0], "", rule[1]] if isinstance(rule, tuple) else ["", rule])
    return "\n".join(parts) + "\n"


def problem_lines(parsed):
    return [p["line"] for p in parsed["problems"]]


class ParseRuleFileTests(unittest.TestCase):
    """T1."""

    def test_frontmatter_lists_and_rules(self):
        text = "\n".join([
            "---", "version: 1", "# a comment", "extends: [unity-csharp, 'python']", "ignore: Assets/Gen/**, `*.bak`",
            "disable: [BASE-NEW-TODO]  # not supported in phase 1", "---", "Preamble text, ignored.", "",
            "## SH-NO-SYNC-IO [Blocker] Không đọc file đồng bộ", "", "", "paths: [Assets/**/*.cs, \"Tools/*.cs\"]",
            "Body line.", "", "### a sub heading is body text", "```python", "## a comment inside a fence", "```",
            "##not-a-heading", "", "## SH-OTHER [minor] Khác", "No paths line here.", ""])
        parsed = mps.parse_rule_file(text, "project")
        self.assertEqual(parsed["problems"], [])
        self.assertEqual((parsed["version"], parsed["extends"], parsed["ignore"], parsed["unknown_keys"]),
                         (1, ["unity-csharp", "python"], ["Assets/Gen/**", "*.bak"], ["disable"]))
        first, second = parsed["rules"]
        self.assertEqual((first["id"], first["severity"], first["title"], first["paths"], first["line"]),
                         ("SH-NO-SYNC-IO", "blocker", "Không đọc file đồng bộ", ["Assets/**/*.cs", "Tools/*.cs"], 10))
        self.assertEqual(first["body"].splitlines()[0], "Body line.")
        self.assertIn("## a comment inside a fence", first["body"])
        self.assertIn("##not-a-heading", first["body"])
        self.assertEqual((second["paths"], second["body"]), (["**"], "No paths line here."))

    def test_missing_frontmatter_bom_crlf_and_lone_cr(self):
        for newline in ("\n", "\r\n", "\r"):
            text = mps._BOM + newline.join(["# T", "", "## A-B [major] X", "body", ""])
            parsed = mps.parse_rule_file(text, "project")
            self.assertEqual(parsed["problems"], [], newline)
            self.assertEqual([(r["id"], r["line"]) for r in parsed["rules"]], [("A-B", 3)], newline)

    def test_problems_make_rules_invalid(self):
        text = "\n".join([
            "---", "version: 2", "ignore: a//b", "ignore: x", "just text", "extends: Unity", "---",
            "## Overview", "## ABC-12 [major] Jira shaped", "## SH-2-NULL [major] Jira shaped too",
            "## mps-a [major] lower case", "## A_B [minor] underscore", "## GOOD [critical] bad severity",
            "## DUP [major] first", "## DUP [minor] second", "## GLOB [minor] bad glob", "paths: ../x", "```", "open"])
        parsed = mps.parse_rule_file(text, "project")
        self.assertEqual(problem_lines(parsed), [2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 15, 17, 18])
        messages = dict((p["line"], p["message"]) for p in parsed["problems"])
        self.assertIn("đã có ở dòng 14", messages[15])
        self.assertIn("ABC-12", messages[9])
        self.assertEqual([r["id"] for r in parsed["rules"]], ["DUP", "GLOB"])

    def test_unclosed_frontmatter_stops_parsing(self):
        parsed = mps.parse_rule_file("---\nversion: 1\n## A [major] x\n", "project")
        self.assertEqual((problem_lines(parsed), parsed["rules"]), ([1], []))

    def test_frontmatter_only_file_is_valid(self):
        parsed = mps.parse_rule_file("---\nversion: 1\nextends: web\n---\n", "project")
        self.assertEqual((parsed["problems"], parsed["rules"], parsed["extends"]), ([], [], ["web"]))

    def test_oversized_project_file_is_one_problem(self):
        parsed = mps.parse_rule_file("x" * (mps.PROJECT_RULES_MAX_CHARS + 1), "project")
        self.assertEqual(problem_lines(parsed), [1])

    def test_extends_is_a_problem_in_shipped_files(self):
        self.assertEqual(problem_lines(mps.parse_rule_file("---\nextends: web\n---\n", "base")), [2])

    def test_readme_example_file_parses(self):
        readme = _read_bytes(os.path.join(REPO_ROOT, "README.md")).decode("utf-8")
        section = readme[readme.index("## Quy tắc review code theo dự án"):]
        example = re.search(r"````markdown\n(.*?)````", section, re.DOTALL).group(1)
        parsed = mps.parse_rule_file(example, "project")
        self.assertEqual(parsed["problems"], [])
        self.assertEqual([(r["id"], r["severity"]) for r in parsed["rules"]],
                         [("SH-NO-SYNC-IO", "blocker"), ("SH-SCORE-ON-SERVER", "major"),
                          ("UNITY-NO-FIND-IN-UPDATE", "blocker")])
        self.assertEqual((parsed["extends"], parsed["ignore"]),
                         (["unity-csharp"], ["**/Assets/ThirdParty/**", "**/Assets/Generated/**"]))


class ShippedRuleFileTests(unittest.TestCase):
    """T2."""

    def test_blocker_is_lowered_in_shipped_layers(self):
        parsed = mps.parse_rule_file("## BASE-X [blocker] x\nbody\n", "base")
        self.assertEqual((parsed["rules"][0]["severity"], parsed["rules"][0]["downgraded"], parsed["downgraded"]),
                         ("major", True, ["BASE-X"]))

    def test_real_files_parse_cleanly(self):
        base, profiles = mps._load_shipped_rules()
        self.assertEqual(sorted(profiles), sorted(mps.SHIPPED_PROFILES))
        seen = []
        for layer, text in [("base", base)] + [("profile:" + n, t) for n, t in sorted(profiles.items())]:
            parsed = mps.parse_rule_file(text, layer)
            self.assertEqual((parsed["problems"], parsed["version"], parsed["downgraded"]), ([], 1, []), layer)
            self.assertGreaterEqual(len(parsed["rules"]), 4, layer)
            for rule in parsed["rules"]:
                self.assertIn(rule["severity"], ("major", "minor"), rule["id"])
                self.assertRegex(rule["id"], mps._RULE_ID_RE)
                self.assertIn("```", rule["body"], rule["id"])
                self.assertIsNone(JIRA_KEY_RE.search(rule["id"]))
                seen.append(rule["id"])
            self.assertNotRegex(text, r"\[blocker\]")
        self.assertEqual(len(seen), len(set(seen)))

    def test_scaffold_template_is_valid_and_has_no_active_rule(self):
        parsed = mps.parse_rule_file(_read_bytes(mps.REVIEW_RULES_TEMPLATE_PATH).decode("utf-8"), "project")
        self.assertEqual((parsed["problems"], parsed["rules"], parsed["unknown_keys"]), ([], [], []))

    def test_broken_shipped_file_is_an_internal_error(self):
        with self.assertRaises(mps.MpsError) as ctx:
            mps.build_effective_rules("## BAD [oops] x\n", {}, None, {})
        self.assertEqual(ctx.exception.code, "internal_error")
        with self.assertRaises(mps.MpsError) as ctx:
            mps.build_effective_rules("", {"web": "## W [major] x\n```\n"}, None, {"web": [""]})
        self.assertIn("profiles/web.md", ctx.exception.message)


BASE_TEXT = rule_file(("## BASE-A [major] a", "body a"), ("## BASE-B [minor] b", "body b"))
PROFILE_TEXTS = {
    "unity-csharp": rule_file(("## UNITY-A [major] u", "paths: **/*.cs\n\nbody"), ignore="[**/*.prefab]"),
    "web": rule_file(("## WEB-A [minor] w", "paths: *.js\n\nbody")),
}


class EffectiveRulesTests(unittest.TestCase):
    """T3."""

    def ids(self, effective):
        return [(r["id"], r["severity"], r["layer"]) for r in effective["rules"]]

    def test_absent_project_and_detected_profile(self):
        effective = mps.build_effective_rules(BASE_TEXT, PROFILE_TEXTS, None, {"unity-csharp": ["Game"]})
        self.assertEqual(self.ids(effective), [("BASE-A", "major", "base"), ("UNITY-A", "major", "profile:unity-csharp"),
                                               ("BASE-B", "minor", "base")])
        self.assertEqual(effective["project_rules"], {"status": "absent", "problems": [], "unknown_keys": []})
        self.assertEqual(effective["profiles"], [{"name": "unity-csharp", "roots": ["Game"], "source": "detected"}])
        self.assertEqual(effective["ignore"], [{"glob": "**/*.prefab", "roots": ["Game"],
                                                "source": "profile:unity-csharp"}])

    def test_project_replaces_in_place_extends_and_unknown_profiles(self):
        project = rule_file(("## BASE-B [blocker] stricter", "body"), ("## SH-NEW [minor] new", "body"),
                            extends="[web, unity-csharp, unity]", ignore="Docs/**")
        effective = mps.build_effective_rules(BASE_TEXT, PROFILE_TEXTS, project, {"unity-csharp": ["Game"]})
        self.assertEqual(self.ids(effective), [("BASE-B", "blocker", "project"), ("BASE-A", "major", "base"),
                                               ("UNITY-A", "major", "profile:unity-csharp"),
                                               ("WEB-A", "minor", "profile:web"), ("SH-NEW", "minor", "project")])
        self.assertEqual(effective["profiles"], [{"name": "unity-csharp", "roots": ["", "Game"], "source": "both"},
                                                 {"name": "web", "roots": [""], "source": "extends"}])
        self.assertEqual(effective["unknown_profiles"], ["unity"])
        self.assertEqual(effective["project_rules"]["status"], "applied")
        self.assertIn({"glob": "Docs/**", "roots": [""], "source": "project"}, effective["ignore"])

    def test_invalid_project_is_skipped_entirely(self):
        project = rule_file(("## SH-STOP [blocker] stop", "body"), ("## SH-BAD [fatal] bad", "body"),
                            extends="web", ignore="Docs/**")
        effective = mps.build_effective_rules(BASE_TEXT, PROFILE_TEXTS, project, {})
        self.assertEqual(self.ids(effective), [("BASE-A", "major", "base"), ("BASE-B", "minor", "base")])
        self.assertEqual(effective["project_rules"]["status"], "invalid")
        self.assertEqual(problem_lines(effective["project_rules"]), [11])
        self.assertEqual((effective["profiles"], effective["ignore"]), ([], []))


class RuleGlobTests(unittest.TestCase):
    """T4."""

    def check(self, glob, matching, other):
        for path in matching:
            self.assertTrue(mps.rule_glob_regex(glob).match(path), (glob, path))
        for path in other:
            self.assertFalse(mps.rule_glob_regex(glob).match(path), (glob, path))

    def test_semantics(self):
        self.check("**/*.cs", ["A.cs", "a/b/C.cs"], ["A.csx", "a/b.cs/x"])
        self.check("*.cs", ["A.cs", "a/b/C.cs"], ["A.txt"])
        self.check("Assets/**", ["Assets/x", "Assets/a/b"], ["Assets", "X/Assets/y"])
        self.check("Assets/**/Editor/*.cs", ["Assets/Editor/a.cs", "Assets/a/b/Editor/c.cs"], ["Editor/a.cs"])
        self.check("**", ["a", "a/b/c"], [])
        self.check("./Docs/", ["Docs/x.md"], ["Docs"])
        self.check("a?c/[x].txt", ["abc/[x].txt"], ["abc/x.txt", "a/c/[x].txt"])

    def test_invalid_globs(self):
        for glob in ("", "   ", "a//b", "../x", "a/./b", "a\0b"):
            with self.assertRaises(ValueError, msg=glob):
                mps.rule_glob_regex(glob)

    def test_anchoring_to_roots(self):
        rule = {"paths": ["**/*.cs"], "roots": ["Game"]}
        self.assertTrue(mps.rule_applies(rule, "Game/Assets/X.cs"))
        self.assertFalse(mps.rule_applies(rule, "Tools/X.cs"))
        self.assertTrue(mps.path_matches("Game\\Assets\\X.cs", ["Assets/*.cs"], ["Game"]))
        # The generated-pattern helper keeps its own semantics (no root match for **/).
        self.assertIsNone(mps._glob_regex("**/*.cs").match("A.cs"))


class FilterRulesTests(unittest.TestCase):
    """T5."""

    def rule(self, rule_id, severity, paths=None, body="x"):
        """A project rule; paths None = no `paths:` line (the default `**`)."""
        return {"id": rule_id, "severity": severity, "title": "t", "paths": list(paths or ["**"]),
                "explicit_paths": paths is not None, "roots": [""], "layer": "project", "body": body}

    def test_split_ignored_keeps_order(self):
        entries = [{"glob": "**/*.prefab", "roots": ["Game"]}]
        self.assertEqual(mps.split_ignored(["Game/A.prefab", "a.cs", "B.prefab"], entries),
                         (["a.cs", "B.prefab"], ["Game/A.prefab"]))

    def test_project_rules_override_profile_ignores_only(self):
        """M1b: an L3 rule makes a profile-ignored file reviewed; the project's own ignore still wins."""
        entries = [{"glob": "**/*.prefab", "roots": ["Game"], "source": "profile:unity-csharp"},
                   {"glob": "Game/Old/**", "roots": [""], "source": "project"}]
        rules = [self.rule("SH-PREFAB", "blocker", ["**/*.prefab"]),
                 dict(self.rule("BASE-ALL", "major"), layer="base")]
        self.assertEqual(mps.split_ignored(["Game/A.prefab", "Game/Old/B.prefab", "Game/C.cs"], entries, rules),
                         (["Game/A.prefab", "Game/C.cs"], ["Game/Old/B.prefab"]))
        self.assertEqual(mps.split_ignored(["Game/A.prefab"], entries, rules[1:]), ([], ["Game/A.prefab"]))
        # M1 round 2: only an explicit paths: line overrides a profile ignore; a project rule without one (default
        # **) keeps every Unity asset ignored.
        self.assertEqual(mps.split_ignored(["Game/A.prefab", "Game/C.cs"], entries, [self.rule("SH-ALL", "blocker")]),
                         (["Game/C.cs"], ["Game/A.prefab"]))
        self.assertEqual(mps.parse_rule_file("## A-B [major] x\nbody\n", "project")["rules"][0]["explicit_paths"], False)
        self.assertEqual(mps.parse_rule_file("## A-B [major] x\npaths: **/*.prefab\n", "project")["rules"][0]
                         ["explicit_paths"], True)

    def test_project_rules_matching_nothing(self):
        """M1a: root-anchored paths that miss a Unity project in a subfolder are reported."""
        rules = [self.rule("SH-WRONG", "blocker", ["Assets/Scripts/**/*.cs"]),
                 self.rule("SH-RIGHT", "blocker", ["**/Assets/Scripts/**/*.cs"]),
                 dict(self.rule("BASE-X", "major", ["nothing/**"]), layer="base")]
        files = ["Client/Game/Assets/Scripts/Player.cs", "README.md"]
        self.assertEqual([r["id"] for r in mps.project_rules_matching_nothing(rules, files)], ["SH-WRONG"])
        # m-b: a file hidden by the project's own ignore is never reviewed, so it does not count as a match.
        own_ignore = [{"glob": "**/Assets/Scripts/**", "roots": [""], "source": "project"}]
        self.assertEqual([r["id"] for r in mps.project_rules_matching_nothing(rules, files, own_ignore)],
                         ["SH-WRONG", "SH-RIGHT"])
        profile_ignore = [{"glob": "**/Assets/Scripts/**", "roots": [""], "source": "profile:unity-csharp"}]
        self.assertEqual([r["id"] for r in mps.project_rules_matching_nothing(rules, files, profile_ignore)],
                         ["SH-WRONG"])
        warning = mps.rule_matches_nothing_warning(rules[0], "trên nhánh develop")
        self.assertEqual((warning["code"], warning["rule"], warning["paths"]),
                         ("project_rule_matches_nothing", "SH-WRONG", ["Assets/Scripts/**/*.cs"]))

    def test_only_rules_matching_a_path(self):
        rules = [self.rule("CS", "major", ["*.cs"]), self.rule("PY", "major", ["*.py"])]
        self.assertEqual(mps.filter_rules(rules, ["a/b.cs"], 10 ** 6), ([rules[0]], []))
        self.assertEqual(mps.filter_rules(rules, [], 10 ** 6), ([], []))

    def test_cap_keeps_blockers_and_drops_minor_first(self):
        rules = [self.rule("STOP", "blocker", body="x" * 300), self.rule("MAJ", "major", body="y" * 100),
                 self.rule("MIN", "minor", body="z" * 100), self.rule("MIN-B", "minor", body="z")]
        kept, dropped = mps.filter_rules(rules, ["a"], 200)
        self.assertEqual(([r["id"] for r in kept], dropped), (["STOP"], ["MAJ", "MIN", "MIN-B"]))
        size = len(mps._render_rule_block(rules[1])) + 1
        kept, dropped = mps.filter_rules(rules, ["a"], 400 + size)
        self.assertEqual(([r["id"] for r in kept], dropped), (["STOP", "MAJ"], ["MIN", "MIN-B"]))


MULTI_HUNK_DIFF = "\n".join([
    "diff --git a/src/A.cs b/src/A.cs", "index 1111111..2222222 100644", "--- a/src/A.cs", "+++ b/src/A.cs",
    "@@ -1,4 +1,5 @@ class A", " l1", "+added2", " l2", " l3", " l4",
    "@@ -20,3 +21,3 @@ void F()", " c21", "-old", "+new22", " c23",
    "@@ -40,4 +41,3 @@", " c41", "-gone", " c42", " c43",
    "diff --git a/e.txt b/e.txt", "index 3333333..e69de29 100644", "--- a/e.txt", "+++ b/e.txt",
    "@@ -1,2 +0,0 @@", "-x", "-y",
    "diff --git a/nl.txt b/nl.txt", "index 1..2 100644", "--- a/nl.txt", "+++ b/nl.txt",
    "@@ -1 +1 @@", "-old", "\\ No newline at end of file", "+new", "\\ No newline at end of file",
    "diff --git a/old/N.cs b/new/N.cs", "similarity index 90%", "rename from old/N.cs", "rename to new/N.cs",
    "index 4444444..5555555 100644", "--- a/old/N.cs", "+++ b/new/N.cs", "@@ -1,2 +1,2 @@", " keep", "-before",
    "+after",
    "diff --git a/r1.txt b/r2.txt", "similarity index 100%", "rename from r1.txt", "rename to r2.txt",
    "diff --git a/n.txt b/n.txt", "new file mode 100644", "index 0000000..6666666", "--- /dev/null", "+++ b/n.txt",
    "@@ -0,0 +1,2 @@", "+a", "+b",
    "diff --git a/d.txt b/d.txt", "deleted file mode 100644", "index 7777777..0000000", "--- a/d.txt",
    "+++ /dev/null", "@@ -1,2 +0,0 @@", "-a", "-b",
    "diff --git a/Art/my logo.png b/Art/my logo.png", "index 8888888..9999999 100644",
    "Binary files a/Art/my logo.png and b/Art/my logo.png differ",
    "diff --git a/my file.txt b/my file.txt", "index 1..2 100644", "--- a/my file.txt\t", "+++ b/my file.txt\t",
    "@@ -1,2 +1,2 @@", "---- x", "+--- y", " ctx\r",
    "diff --git a/mode.sh b/mode.sh", "old mode 100644", "new mode 100755",
]) + "\n"


class NetDiffTests(unittest.TestCase):
    """T6."""

    def test_parse_and_ranges(self):
        files = mps.parse_diff_files(MULTI_HUNK_DIFF)
        self.assertEqual([(f["path"], f["status"]) for f in files], [
            ("src/A.cs", "modified"), ("e.txt", "modified"), ("nl.txt", "modified"), ("new/N.cs", "renamed"),
            ("r2.txt", "renamed"), ("n.txt", "added"), ("d.txt", "deleted"), ("Art/my logo.png", "modified"),
            ("my file.txt", "modified"), ("mode.sh", "modified")])
        self.assertEqual(files[3]["old_path"], "old/N.cs")
        self.assertTrue(files[7]["binary"])
        self.assertTrue(files[9]["mode_only"])
        self.assertFalse(files[4]["mode_only"])
        self.assertEqual(mps.parse_changed_ranges(MULTI_HUNK_DIFF), {
            "src/A.cs": [[1, 5], [21, 23], [41, 43]], "e.txt": [[1, 1]], "nl.txt": [[1, 1]], "new/N.cs": [[1, 2]],
            "r2.txt": [], "n.txt": [[1, 2]], "my file.txt": [[1, 2]], "mode.sh": []})

    def test_rendering_and_kinds(self):
        rendered = mps.render_numbered_diff(mps.parse_diff_files(MULTI_HUNK_DIFF), None)
        text = rendered["text"]
        self.assertIn("### src/A.cs  [modified]\n@@ -1,4 +1,5 @@ class A\n     1   l1\n     2 + added2\n", text)
        self.assertIn("       - old\n    22 + new22\n", text)
        self.assertIn("       \\ No newline at end of file\n", text)
        self.assertIn("### new/N.cs  [renamed from old/N.cs]", text)
        self.assertIn("### d.txt  [deleted - only file-level findings, use line -]\n### Art/my logo.png  [binary", text)
        self.assertIn("       - --- x\n     1 + --- y\n     2   ctx\n", text)
        self.assertIn("### mode.sh  [mode change only]", text)
        self.assertNotIn("\r", text)
        self.assertEqual((rendered["file_kinds"]["d.txt"], rendered["file_kinds"]["Art/my logo.png"]),
                         ("deleted", "binary"))
        self.assertEqual(rendered["truncated_paths"], [])

    def test_quoted_path_and_line_separator_characters(self):
        quoted = "\n".join(['diff --git "a/\\303\\251 x.cs" "b/\\303\\251 x.cs"', "index 1..2 100644",
                            '--- "a/\\303\\251 x.cs"', '+++ "b/\\303\\251 x.cs"', "@@ -1,2 +1,2 @@",
                            " a" + chr(0x2028) + "b", "-c", "+d", ""])
        self.assertEqual(mps._unquote_git_path('"a/\\303\\251\\t\\"q\\""'), 'a/' + chr(0xE9) + '\t"q"')
        self.assertEqual(mps.parse_changed_ranges(quoted), {chr(0xE9) + " x.cs": [[1, 2]]})
        binary = 'diff --git "a/\\303\\251.png" "b/\\303\\251.png"\nBinary files differ\n'
        self.assertEqual(mps.parse_diff_files(binary)[0]["path"], chr(0xE9) + ".png")

    def test_budget_cuts_at_line_boundaries(self):
        files = mps.parse_diff_files(MULTI_HUNK_DIFF)
        full = mps.render_numbered_diff(files, None)["text"]
        cut_at = full.index("    22 + new22")
        rendered = mps.render_numbered_diff(files, cut_at)
        self.assertLessEqual(len(rendered["text"]), cut_at + 60)
        self.assertEqual(rendered["ranges"]["src/A.cs"], [[1, 5], [21, 21]])
        self.assertEqual(rendered["truncated_paths"][0], "src/A.cs")
        self.assertIn("### src/A.cs  [modified] - TRUNCATED: shown up to line 21", rendered["text"])
        self.assertEqual(rendered["file_kinds"]["e.txt"], "not_shown")
        self.assertNotIn("e.txt", rendered["ranges"])
        self.assertEqual(set(rendered["truncated_paths"]), set(f["path"] for f in files))

    def test_long_lines_are_capped(self):
        diff = "diff --git a/m.js b/m.js\n--- a/m.js\n+++ b/m.js\n@@ -0,0 +1 @@\n+" + "x" * 50 + "\n"
        rendered = mps.render_numbered_diff(mps.parse_diff_files(diff), None, line_cap=10)
        self.assertIn("     1 + xxxxxxxxxx [... dòng bị cắt bớt ...]\n", rendered["text"])
        self.assertEqual(rendered["ranges"]["m.js"], [[1, 1]])

    def test_untracked_files(self):
        files = [mps.untracked_file_diff("u.txt", "a\r\nb\n", "text", False),
                 mps.untracked_file_diff("big.txt", "1\n2\n", "text", True),
                 mps.untracked_file_diff("img.png", None, "binary", False),
                 mps.untracked_file_diff("huge.bin", None, "too_large", False),
                 mps.untracked_file_diff("empty.txt", "", "text", False)]
        rendered = mps.render_numbered_diff(files, None)
        self.assertIn("### u.txt  [untracked (new file)]\n     1 + a\n     2 + b\n", rendered["text"])
        self.assertIn("### big.txt  [untracked (new file)] - TRUNCATED: shown up to line 2", rendered["text"])
        self.assertEqual(rendered["truncated_paths"], ["big.txt"])
        self.assertEqual((rendered["file_kinds"]["img.png"], rendered["file_kinds"]["huge.bin"]),
                         ("binary", "too_large"))
        self.assertEqual((rendered["ranges"]["u.txt"], rendered["ranges"]["empty.txt"]), ([[1, 2]], []))


def finding_lines(*lines):
    entries, _ = mps.parse_findings("\n".join(("FINDINGS:",) + lines + ("BUNDLE: ab12",)))
    return entries


class ParseFindingsTests(unittest.TestCase):
    """T7."""

    def test_none_and_bundle_line(self):
        self.assertEqual(mps.parse_findings("x\nFINDINGS: none\n\nBUNDLE: ABCdef12\n"), ([], "abcdef12"))
        self.assertEqual(mps.parse_findings("- FINDINGS: `None`\r\nBUNDLE: `ab12`\r\n"), ([], "ab12"))
        self.assertEqual(mps.parse_findings("FINDINGS: none\nBUNDLE missing\n")[1], None)
        self.assertEqual(mps.parse_findings("no block here\nBUNDLE: ab12\n"), (None, None))

    def test_well_formed_lines(self):
        a, b, c, d = finding_lines("- `R-A` | `Major` | `src/a b.cs:10-12` | p1 | fix a | then b",
                                   "* R-B | minor | ./x\\y.cs:3 " + chr(0x2013) + " 4 | p | s",
                                   "R-C | blocker | Builds/game.apk:- | p | s",
                                   "R-D | minor | dir:odd/a.cs:7 | p | s")
        self.assertEqual((a["rule"], a["severity"], a["path"], a["line"], a["line_start"], a["line_end"],
                          a["problem"], a["suggestion"]),
                         ("R-A", "major", "src/a b.cs", "10-12", 10, 12, "p1", "fix a | then b"))
        self.assertEqual((b["path"], b["line"]), ("x/y.cs", "3-4"))
        self.assertEqual((c["line"], c["line_start"], c["line_end"]), ("-", None, None))
        self.assertEqual((d["path"], d["line"]), ("dir:odd/a.cs", "7"))

    def test_bad_lines(self):
        entries = finding_lines("R-D | major | a.cs:0 | p | s", "R-E | major | a.cs:12-10 | p | s",
                                "R-F | major | a.cs | p | s", "| R-G | major | a.cs:1 | p | s |",
                                "R-H | serious | a.cs:1 | p | s", "R-I | major | a.cs:1 | p |", "only text")
        self.assertEqual([e["ok"] for e in entries], [False] * 7)

    def test_fence_ends_the_block_and_identical_repeats_are_fine(self):
        text = "\n".join(["```", "FINDINGS:", "R-NEW | major | b.cs:2 | p | s", "```", "BUNDLE: 22"])
        entries, bundle_id = mps.parse_findings(text)
        self.assertEqual(([e["rule"] for e in entries], bundle_id), (["R-NEW"], "22"))
        entries, bundle_id = mps.parse_findings(text + "\n\nNhắc lại:\n" + text)
        self.assertEqual(([e["rule"] for e in entries], bundle_id), (["R-NEW"], "22"))

    def test_different_blocks_are_ambiguous(self):
        """Fail closed: an earlier quoted example is never silently skipped, even with another bundle id."""
        text = "\n".join(["Example:", "FINDINGS:", "R-OLD | major | a.cs:1 | p | s", "BUNDLE: 11", "",
                          "FINDINGS:", "R-NEW | major | b.cs:2 | p | s", "BUNDLE: 22"])
        entries, bundle_id = mps.parse_findings(text)
        self.assertEqual(([(e["ok"], e["error"]) for e in entries], bundle_id),
                         ([(False, mps._AMBIGUOUS_FINDINGS)], "22"))

    def test_none_followed_by_findings_is_bad_format(self):
        entries, _ = mps.parse_findings("FINDINGS: none\nR-A | major | a.cs:1 | p | s\nBUNDLE: ab\n")
        self.assertEqual([e["ok"] for e in entries], [False])

    def test_fenced_block_body_is_read(self):
        """C1a: a fence right after the header opens the block; the next fence closes it."""
        text = "\n".join(["FINDINGS:", "", "```", "SH-NO-SYNC-IO | blocker | a.cs:3 | p | s", "R-B | minor | b.cs:1 | p | s",
                          "```", "BUNDLE: ab12"])
        entries, bundle_id = mps.parse_findings(text)
        self.assertEqual(([e["rule"] for e in entries], bundle_id), (["SH-NO-SYNC-IO", "R-B"], "ab12"))

    def test_empty_header_is_bad_format(self):
        """C1b: the reviewer must write `none` when there is nothing."""
        for text in ("FINDINGS:\nBUNDLE: ab12\n", "FINDINGS:\n```\n```\nBUNDLE: ab12\n"):
            entries, bundle_id = mps.parse_findings(text)
            self.assertEqual(([e["ok"] for e in entries], bundle_id), ([False], "ab12"), text)

    def test_numbered_and_bold_rule_ids(self):
        """C1c."""
        entries = finding_lines("1. SH-NO-SYNC-IO | blocker | a.cs:3 | p | s",
                                "2) **SH-NO-SYNC-IO** | blocker | a.cs:4 | p | s",
                                "- __`SH-NO-SYNC-IO`__ | blocker | a.cs:5 | p | s")
        self.assertEqual([(e["ok"], e["rule"], e["line"]) for e in entries],
                         [(True, "SH-NO-SYNC-IO", "3"), (True, "SH-NO-SYNC-IO", "4"), (True, "SH-NO-SYNC-IO", "5")])

    def test_header_quoted_after_the_block_is_ambiguous(self):
        """A "FINDINGS: none" quoted after the real block can never win: the reply is sent back."""
        text = "\n".join(["FINDINGS:", "R-A | major | a.cs:1 | p | s", "BUNDLE: ab12", "",
                          "Nếu không có lỗi thì ghi:", "FINDINGS: none"])
        entries, bundle_id = mps.parse_findings(text)
        self.assertEqual(([e["ok"] for e in entries], bundle_id), ([False], "ab12"))

    def test_text_after_a_fenced_block_is_bad(self):
        entries, _ = mps.parse_findings("FINDINGS:\n```\nR-A | major | a.cs:1 | p | s\n```\nR-B | minor | b.cs:1 | p "
                                        "| s\nBUNDLE: ab12\n")
        self.assertEqual([(e["ok"], e.get("error")) for e in entries],
                         [(True, None), (False, mps._TEXT_AFTER_BLOCK)])


VERIFY_REVIEW = {
    "rules": [
        {"id": "SH-STOP", "severity": "blocker", "layer": "project", "title": "stop", "paths": ["**/*.txt"],
         "roots": [""]},
        {"id": "BASE-A", "severity": "major", "layer": "base", "title": "a", "paths": ["**"], "roots": [""]},
        {"id": "UNITY-A", "severity": "minor", "layer": "profile:unity-csharp", "title": "u", "paths": ["**/*.cs"],
         "roots": ["Game"]},
    ],
    "reviewed_paths": ["a.txt", "Game/X.cs", "Tools/X.cs", "logo.png", "big.txt"],
    "ignored_paths": ["Game/M.prefab"],
    "ranges": {"a.txt": [[1, 5], [20, 22]], "Game/X.cs": [[1, 3]], "Tools/X.cs": [[1, 1]]},
    "file_kinds": {"a.txt": "text", "Game/X.cs": "text", "Tools/X.cs": "text", "logo.png": "binary",
                   "big.txt": "not_shown"},
}


class VerifyFindingsTests(unittest.TestCase):
    """T8 / T9."""

    def verify(self, *lines):
        return mps.verify_findings(finding_lines(*lines), VERIFY_REVIEW, set(["a.txt"]))

    def test_drop_reasons_dedup_and_severity_from_the_rule(self):
        result = self.verify(
            "SH-STOP | major | a.txt:4-8 | p | s", "SH-STOP | blocker | a.txt:4-8 | p | s",
            "BASE-A | major | a.txt:10 | p | s", "BASE-A | major | a.txt:- | p | s",
            "BASE-A | major | logo.png:- | p | s", "BASE-A | major | logo.png:3 | p | s",
            "BASE-A | major | big.txt:1 | p | s", "NOPE | major | a.txt:1 | p | s",
            "BASE-A | major | Game/M.prefab:1 | p | s", "BASE-A | major | other.txt:1 | p | s",
            "UNITY-A | minor | Tools/X.cs:1 | p | s", "UNITY-A | minor | Game/X.cs:2 | p | s",
            "BASE-A | minor | a.txt:21 | p | s")
        self.assertEqual([d["reason"] for d in result["dropped_findings"]], [
            "duplicate", "line_outside_changes", "line_outside_changes", "line_outside_changes",
            "line_outside_changes", "unknown_rule", "path_ignored", "path_not_reviewed", "rule_not_applicable"])
        self.assertEqual((result["complete"], result["dropped_count"], result["duplicate_count"]), (True, 8, 1))
        blocker = result["blockers"][0]
        self.assertEqual((blocker["rule"], blocker["severity"], blocker["severity_corrected"], blocker["line"]),
                         ("SH-STOP", "blocker", True, "4-8"))
        self.assertEqual([(f["rule"], f["path"], f["severity"]) for f in result["rule_warnings"]],
                         [("BASE-A", "logo.png", "major"), ("BASE-A", "a.txt", "major"),
                          ("UNITY-A", "Game/X.cs", "minor")])
        self.assertEqual((result["blockers_in_candidates"], result["blocked_paths"]), ([blocker], ["a.txt"]))

    def test_completeness(self):
        self.assertFalse(self.verify("SH-STOP | blocker | a.txt:9 | p | s")["complete"])
        self.assertFalse(self.verify("BASE-A | major | a.txt:1 | p")["complete"])
        self.assertTrue(self.verify("BASE-A | major | a.txt:9 | p | s")["complete"])
        # C1d: a finding the reviewer called a blocker is never dropped silently, even for an unknown rule id.
        claimed = self.verify("SH-STOPP | blocker | a.txt:1 | p | s")
        self.assertEqual((claimed["complete"], claimed["dropped_findings"][0]["reason"],
                          claimed["dropped_findings"][0]["blocker_claimed"]), (False, "unknown_rule", True))
        self.assertTrue(self.verify("SH-STOP | blocker | a.txt:1 | p | s", "SH-STOP | blocker | a.txt:1 | p | s")
                        ["complete"])  # a duplicate is fine
        # The reviewer's probes: fenced body, numbered list, bold id - each blocker is found, or the review is
        # incomplete; never complete without it.
        for reply in ("FINDINGS:\n```\nSH-STOP | blocker | a.txt:3 | p | s\n```\nBUNDLE: ab\n",
                      "FINDINGS:\n1. SH-STOP | blocker | a.txt:3 | p | s\nBUNDLE: ab\n",
                      "FINDINGS:\n**SH-STOP** | blocker | a.txt:3 | p | s\nBUNDLE: ab\n"):
            result = mps.verify_findings(mps.parse_findings(reply)[0], VERIFY_REVIEW, set(["a.txt"]))
            self.assertEqual((result["complete"], [f["rule"] for f in result["blockers"]]), (True, ["SH-STOP"]), reply)
        empty = mps.verify_findings(mps.parse_findings("FINDINGS:\nBUNDLE: ab\n")[0], VERIFY_REVIEW, set())
        self.assertFalse(empty["complete"])

    def test_round2_layouts_never_lose_a_blocker(self):
        """C1 round 2: each layout used to drop the blocker line L and report complete; now it is incomplete."""
        blocker = "SH-STOP | blocker | a.txt:3 | p | s"
        major = "BASE-A | major | a.txt:2 | p | s"
        layouts = {
            "two headers, one BUNDLE": ["FINDINGS:", blocker, "FINDINGS: none", "BUNDLE: ab"],
            "quoted none block after": ["FINDINGS:", blocker, "BUNDLE: ab", "", "Sau khi sửa sẽ là:",
                                        "FINDINGS: none", "BUNDLE: ab"],
            "fix snippet inside the block": ["FINDINGS:", major, "```csharp", "var x = 1;", "```", blocker,
                                             "BUNDLE: ab"],
            "fenced findings, blocker outside": ["FINDINGS:", "```", major, "```", blocker, "BUNDLE: ab"],
        }
        for name, lines in layouts.items():
            entries, bundle_id = mps.parse_findings("\n".join(lines) + "\n")
            result = mps.verify_findings(entries, VERIFY_REVIEW, set(["a.txt"]))
            self.assertEqual((result["complete"], bundle_id), (False, "ab"), name)
            self.assertIn("bad_format", [d["reason"] for d in result["dropped_findings"]], name)

    def test_blockers_for_commit(self):
        review = {"blockers": [{"path": "b.txt"}, {"path": "c.txt"}, {"path": "old.txt"}],
                  "already_committed": ["c.txt"]}
        self.assertEqual(mps.blockers_for_commit(review, ["a.txt"]), [{"path": "c.txt"}])
        self.assertEqual(mps.blockers_for_commit(review, ["a.txt", "b.txt"]), [{"path": "b.txt"}, {"path": "c.txt"}])
        self.assertEqual(mps.blockers_for_commit(review, ["new.txt", "old.txt"]), [{"path": "c.txt"},
                                                                                   {"path": "old.txt"}])


def mr_finding(rule, path, severity="major", line="3", problem="p", suggestion="s"):
    return {"rule": rule, "severity": severity, "path": path, "line": line, "problem": problem,
            "suggestion": suggestion}


def committed_review(findings=(), **extra):
    review = {"base": "develop", "findings": list(findings), "committed_paths": ["a.cs", "Assets/UI-2.png"],
              "profiles": [{"name": "unity-csharp", "roots": ["Client/Game"], "source": "detected"}],
              "project_rules": {"status": "applied", "pending_change": False, "problems": []},
              "truncated": False, "truncated_paths": [], "auto": None}
    review.update(extra)
    return review


def outside_code_spans(markdown):
    return re.sub(r"`[^`]*`", "", markdown)


class MrReviewSectionTests(unittest.TestCase):
    """T10."""

    def test_empty_and_rules_line(self):
        text = mps.render_mr_review_section(committed_review())
        self.assertTrue(text.startswith("### Kết quả review code tự động\n"))
        self.assertIn("Không có cảnh báo.", text)
        self.assertIn("công nghệ: `unity-csharp` (`Client/Game`); dự án: `origin/develop:.mps/review.md`.", text)
        self.assertNotIn("KHÔNG được áp dụng", text)

    def test_items_capping_and_filtering(self):
        findings = [mr_finding("BASE-MINOR", "a.cs", "minor", str(n)) for n in range(25)]
        findings += [mr_finding("BASE-MAJOR", "a.cs", "major", str(n)) for n in range(10)]
        findings.append(mr_finding("BASE-ELSEWHERE", "not/committed.cs"))
        text = mps.render_mr_review_section(committed_review(findings))
        self.assertLess(text.index("**Cảnh báo mức major:**"), text.index("**Cảnh báo mức minor:**"))
        self.assertEqual(text.count("`BASE-MAJOR`"), 10)
        self.assertEqual(text.count("`BASE-MINOR`"), 20)
        self.assertIn("… và 5 mục khác", text)
        self.assertNotIn("ELSEWHERE", text)
        self.assertEqual(len(mps.code_review_warning_items(committed_review(findings))), 35)

    def test_escaping_and_no_references_outside_code_spans(self):
        finding = mr_finding("BASE-A", "Assets/UI-2.png", line="-",
                             problem="Dùng UTF-8 và ABC-12 | x `y`\nnext @Override #12 !3 a@b.com",
                             suggestion="Xem MPS-7")
        problems = [{"line": n, "message": "Mã quy tắc 'ABC-%d' không hợp lệ" % n} for n in range(1, 8)]
        text = mps.render_mr_review_section(committed_review(
            [finding], project_rules={"status": "invalid", "pending_change": True, "problems": problems},
            truncated=True, truncated_paths=["big/Gen-1.cs"] + ["f%d.cs" % n for n in range(11)]))
        self.assertIn("- `BASE-A` · `Assets/UI-2.png` · Dùng `UTF-8` và `ABC-12` \\| x 'y' next `@Override` `#12` "
                      "`!3` `a@b.com` · Gợi ý: Xem `MPS-7`", text)
        self.assertIsNone(JIRA_KEY_RE.search(outside_code_spans(text)), text)
        item = [line for line in text.splitlines() if line.startswith("- `BASE-A`")][0]
        self.assertNotRegex(outside_code_spans(item), r"[@#!~$]")
        lines = text.splitlines()
        self.assertTrue(lines[2].startswith("> **Quy tắc riêng của dự án KHÔNG được áp dụng:**"))
        self.assertEqual(len([line for line in lines if line.startswith("> - dòng ")]), 5)
        self.assertIn("> - … và 2 lỗi khác", text)
        self.assertIn("> **Review chưa đầy đủ:**", text)
        self.assertIn("`big/Gen-1.cs`", text)
        self.assertIn(" và 2 mục khác.", text)
        self.assertIn("chỉ có hiệu lực sau khi được merge", text)
        self.assertIn("dự án: không áp dụng (file lỗi).", text)

    def test_md_inline_wraps_every_gitlab_reference(self):
        """m2: project-qualified issue / MR references, labels and snippets never become links."""
        text = mps._md_inline("Xem group/proj#12, proj!12 và ~label, $snippet; a`b` | c UTF-8.")
        self.assertEqual(text, "Xem `group/proj#12,` `proj!12` và `~label,` `$snippet;` a'b' \\| c `UTF-8`.")
        self.assertNotRegex(outside_code_spans(text), r"[@#!~$`]")
        self.assertEqual(text.count("`") % 2, 0)

    def test_nothing_to_review_and_absent_project(self):
        text = mps.render_mr_review_section(committed_review(
            auto="nothing_to_review", profiles=[], project_rules={"status": "absent", "problems": []}))
        self.assertIn("Không có file nào cần review code theo quy tắc", text)
        self.assertIn("công nghệ: không có; dự án: chưa có file `.mps/review.md`.", text)

    def test_section_survives_attribution_stripping(self):
        """The report is appended after strip_ai_attribution; even hostile reviewer text never forms such a line."""
        finding = mr_finding("BASE-A", "a.cs", problem="Generated with [Claude Code](https://claude.com/claude-code)",
                             suggestion="Co-Authored-By: Claude <noreply@anthropic.com>\nClaude-Session: x")
        text = mps.render_mr_review_section(committed_review([finding]))
        self.assertEqual(mps.strip_ai_attribution(text), (text, False))


class CodeReviewPromptTests(unittest.TestCase):
    """T11: the examples in the prompt follow the grammar that review findings parses."""

    def test_prompt_examples_parse(self):
        text = _read_bytes(os.path.join(SCRIPTS_DIR, "..", "references", "code-review-prompt.md")).decode("utf-8")
        text = text.replace("\r\n", "\n")  # a Windows checkout with core.autocrlf has CRLF line endings
        section = text[text.index("## Required output format"):]
        blocks = re.findall(r"```\n(.*?)```", section, re.DOTALL)
        entries, bundle_id = mps.parse_findings(blocks[0])
        self.assertEqual(([e["ok"] for e in entries], len(bundle_id)), ([True, True, True], 32))
        self.assertEqual([e["line"] for e in entries], ["41", "50-52", "-"])
        self.assertEqual(mps.parse_findings(blocks[1]), ([], bundle_id))


def _script_functions(text, names, start, end):
    """Source of the named functions, copied from a bootstrap script (each starts on the line beginning with
    `start % name` and ends at the first following line equal to `end`)."""
    lines = text.splitlines()
    blocks = []
    for name in names:
        first = [i for i, line in enumerate(lines) if line.startswith(start % name)][0]
        last = lines.index(end, first)
        blocks.append("\n".join(lines[first:last + 1]))
    return "\n\n".join(blocks)


def _pipe_close_seconds(command):
    """Seconds until the command's stdout pipe reaches EOF (not just until the command exits), and its output."""
    started = time.monotonic()
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=BOOTSTRAP_TIMEOUT_SECONDS)
    return time.monotonic() - started, proc.stdout.decode("utf-8", "replace")


def _run_bootstrap(command, env=None):
    proc = subprocess.run(command, capture_output=True, timeout=BOOTSTRAP_TIMEOUT_SECONDS, env=env)
    lines = [line for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
    return proc.returncode, lines


class BootstrapScriptTests(unittest.TestCase):
    """B1 / B2: detect-only prints one JSON line; on a test machine Python is present."""

    def check_detect_only(self, command, expected_os):
        code, lines = _run_bootstrap(command)
        self.assertEqual(len(lines), 1, lines)
        result = json.loads(lines[0])
        for key in BOOTSTRAP_KEYS:
            self.assertIn(key, result)
        self.assertEqual((result["os"], result["mode"]), (expected_os, "detect"))
        self.assertTrue(result["ok"], result)
        self.assertEqual(code, 0)
        version = subprocess.run([result["python_cmd"], "--version"], capture_output=True, timeout=60)
        self.assertEqual(version.returncode, 0)

    @unittest.skipUnless(sys.platform.startswith("win") and shutil.which("powershell.exe"), "Windows PowerShell only")
    def test_ps1_detect_only(self):
        self.check_detect_only(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", BOOTSTRAP_PS1,
                                "-DetectOnly"], "windows")

    @unittest.skipUnless(sys.platform.startswith("win") and shutil.which("powershell.exe"), "Windows PowerShell only")
    def test_ps1_survives_a_missing_drive_on_path(self):
        """C1: a PATH entry on a drive that does not exist must not turn detection into bootstrap_failed."""
        env = dict(os.environ)
        env["PATH"] = "Q:\\nope;" + env.get("PATH", "")
        code, lines = _run_bootstrap(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                      BOOTSTRAP_PS1, "-DetectOnly"], env)
        self.assertEqual(len(lines), 1, lines)
        result = json.loads(lines[0])
        self.assertTrue(result["ok"], result)
        self.assertEqual(code, 0)

    @unittest.skipUnless(sys.platform.startswith("win") and shutil.which("powershell.exe"), "Windows PowerShell only")
    def test_ps1_timed_out_installer_does_not_hold_stdout(self):
        """N1: a winget still running after the budget must not keep the agent's stdout pipe open."""
        folder = tempfile.mkdtemp(prefix="mps-ps1-")
        self.addCleanup(shutil.rmtree, folder, True)
        functions = _script_functions(_read_bytes(BOOTSTRAP_PS1).decode("utf-8-sig"),
                                      ("Write-Log", "Invoke-Detached"), "function %s(", "}")
        ping = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "PING.EXE")
        harness = os.path.join(folder, "harness.ps1")
        with open(harness, "wb") as handle:
            handle.write(UTF8_BOM + "\r\n".join([
                "$ErrorActionPreference = 'Stop'",
                "$script:LogPath = '%s'" % os.path.join(folder, "install.log"),
                functions,
                "$quick = Invoke-Detached '%s' '-n 1 127.0.0.1' 30000" % ping,
                "$slow = Invoke-Detached '%s' '-n %d 127.0.0.1' 500" % (ping, SLOW_INSTALLER_SECONDS),
                "[Console]::Out.WriteLine('{\"quick\":' + $quick.Code + ',\"slow_timed_out\":' + "
                "([string]$slow.TimedOut).ToLower() + '}')",
                "exit 0", ""]).encode("utf-8"))
        elapsed, out = _pipe_close_seconds(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                            harness])
        self.assertEqual(json.loads(out.strip()), {"quick": 0, "slow_timed_out": True})
        self.assertLess(elapsed, PIPE_CLOSE_MAX_SECONDS)
        with open(os.path.join(folder, "install.log"), "rb") as handle:
            self.assertIn(b"127.0.0.1", handle.read())

    @unittest.skipUnless(shutil.which("sh"), "needs sh")
    def test_sh_timed_out_installer_does_not_hold_stdout(self):
        """N1: an installer still running after the budget must not keep the agent's stdout pipe open."""
        folder = tempfile.mkdtemp(prefix="mps-sh-")
        self.addCleanup(shutil.rmtree, folder, True)
        functions = _script_functions(_read_bytes(BOOTSTRAP_SH).decode("utf-8"),
                                      ("log", "now_seconds", "remaining_seconds", "run_install"), "%s() {", "}")
        harness = os.path.join(folder, "harness.sh")
        with open(harness, "wb") as handle:
            handle.write("\n".join([
                "LOG_PATH=/dev/null", "INSTALL_BUDGET_SECONDS=1", "MIN_INSTALL_SECONDS=0", functions,
                "START_SECONDS=$(now_seconds)",
                "run_install sleep %d" % SLOW_INSTALLER_SECONDS,
                "printf '{\"status\":\"%s\"}\\n' \"$INSTALL_STATUS\"", "exit 0", ""]).encode("utf-8"))
        elapsed, out = _pipe_close_seconds(["sh", harness])
        self.assertEqual(json.loads(out.strip()), {"status": "timeout"})
        self.assertLess(elapsed, PIPE_CLOSE_MAX_SECONDS)

    @unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "POSIX only")
    def test_sh_detect_only(self):
        self.check_detect_only(["sh", BOOTSTRAP_SH, "--detect-only"],
                               "macos" if sys.platform == "darwin" else "linux")


LEGACY_REPO = "hung-bui-121/mps-cdci-agents"
HOOKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "mps-git-flow", "hooks")
LEGACY_HOOK_SH = os.path.join(HOOKS_DIR, "legacy-source-check.sh")


def _find_bash():
    """bash for the hook script; on Windows only Git Bash (what Claude Code runs hooks with), never WSL's bash."""
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if not git:
        return None
    folder = os.path.dirname(git)
    for _ in range(3):
        folder = os.path.dirname(folder)
        candidate = os.path.join(folder, "bin", "bash.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


BASH = _find_bash()


def _known(source):
    return {"mps-cdci-agents": {"source": source, "installLocation": "x", "lastUpdated": "2026-11-07T00:00:00Z"}}


class LegacyPluginSourceTests(unittest.TestCase):
    """Machines that still install the plugin from the personal repo must move to the shared repo."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mps-legacy-")
        self.addCleanup(_rmtree, self.tmp)
        self.environ = {mps.PLUGINS_DIR_ENV: self.tmp}

    def write_known(self, data):
        with open(os.path.join(self.tmp, mps.KNOWN_MARKETPLACES_FILE), "w", encoding="utf-8") as handle:
            handle.write(data if isinstance(data, str) else json.dumps(data))

    def test_points_to_legacy_repo(self):
        for source in ({"source": "github", "repo": LEGACY_REPO},
                       {"source": "github", "repo": "Hung-Bui-121/MPS-CDCI-Agents", "ref": "main"},
                       {"source": "git", "url": "https://github.com/hung-bui-121/mps-cdci-agents.git"},
                       {"source": "url", "url": "git@github.com:hung-bui-121/mps-cdci-agents.git"}):
            self.assertTrue(mps.points_to_legacy_repo(source), source)
        for source in ({"source": "github", "repo": mps.MARKETPLACE_REPO},
                       {"source": "github", "repo": "someone/hung-bui-121-mps-cdci-agents"},
                       {"source": "directory", "path": "D:/work/" + LEGACY_REPO},
                       {"source": "github"}, LEGACY_REPO, None):
            self.assertFalse(mps.points_to_legacy_repo(source), source)

    def test_known_marketplaces_path(self):
        self.assertEqual(mps.known_marketplaces_path({mps.PLUGINS_DIR_ENV: "P"}),
                         os.path.join("P", "known_marketplaces.json"))
        self.assertEqual(mps.known_marketplaces_path({mps.CLAUDE_CONFIG_DIR_ENV: "C"}),
                         os.path.join("C", "plugins", "known_marketplaces.json"))

    def test_missing_or_broken_registry_never_blocks(self):
        self.assertEqual(mps.load_known_marketplaces(self.environ), {})
        for text in ("{not json", "[1, 2]"):
            self.write_known(text)
            self.assertEqual(mps.load_known_marketplaces(self.environ), {})

    def test_status(self):
        legacy = _known({"source": "github", "repo": LEGACY_REPO})
        shared = _known({"source": "github", "repo": mps.MARKETPLACE_REPO})
        project_legacy = {"extraKnownMarketplaces": {"mps-cdci-agents": {"source": {"source": "github",
                                                                                     "repo": LEGACY_REPO}}}}
        project_shared = {"extraKnownMarketplaces": {"mps-cdci-agents": {"source": mps._expected_marketplace_source()}}}
        self.assertEqual(mps.legacy_plugin_source_status(shared, project_legacy), (None, []))
        self.assertEqual(mps.legacy_plugin_source_status(legacy, None), ("machine", ["mps-cdci-agents"]))
        self.assertEqual(mps.legacy_plugin_source_status(legacy, project_shared), ("machine", ["mps-cdci-agents"]))
        self.assertEqual(mps.legacy_plugin_source_status(legacy, project_legacy), ("project", ["mps-cdci-agents"]))
        self.assertTrue(mps.project_declares_legacy_source(project_legacy))
        self.assertFalse(mps.project_declares_legacy_source(project_shared))
        self.assertFalse(mps.project_declares_legacy_source({"extraKnownMarketplaces": []}))

    def run_main(self, argv):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="utf-8")
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.tmp)  # not a git project: settings are None
        with mock.patch.object(sys, "stdout", stream), mock.patch.dict(os.environ, self.environ):
            code = mps.main(argv)
        stream.flush()
        return code, json.loads(buffer.getvalue().decode("utf-8"))

    def test_commands_blocked_with_friendly_message(self):
        self.write_known(_known({"source": "github", "repo": LEGACY_REPO}))
        code, result = self.run_main(["jira", "projects"])
        self.assertNotEqual(code, 0)
        self.assertEqual(result["error"], "plugin_source_legacy")
        self.assertEqual(result["marketplaces"], ["mps-cdci-agents"])
        self.assertEqual(result["commands"], ["claude plugin marketplace remove mps-cdci-agents",
                                              "claude plugin marketplace add " + mps.MARKETPLACE_REPO,
                                              "claude plugin install mps-git-flow@mps-cdci-agents"])
        for text in ("repo dùng chung", "repo cá nhân của hungbt", mps.MARKETPLACE_REPO, LEGACY_REPO,
                     "/plugin marketplace remove mps-cdci-agents"):
            self.assertIn(text, result["message"])

    def test_project_setup_is_never_blocked(self):
        self.write_known(_known({"source": "github", "repo": LEGACY_REPO}))
        _, result = self.run_main(["project", "setup"])
        self.assertEqual(result["error"], "not_git_repo")

    def test_shared_source_runs(self):
        self.write_known(_known({"source": "github", "repo": mps.MARKETPLACE_REPO}))
        _, result = self.run_main(["jira", "projects"])
        self.assertNotEqual(result.get("error"), "plugin_source_legacy")

    def make_project(self, source):
        """A git project in the temp folder whose .claude/settings.json declares the marketplace with `source`."""
        project = os.path.join(self.tmp, "project")
        os.makedirs(os.path.join(project, ".claude"), exist_ok=True)
        subprocess.run(["git", "init", "-q", project], check=True, capture_output=True)
        with open(os.path.join(project, ".claude", "settings.json"), "w", encoding="utf-8") as handle:
            json.dump({"extraKnownMarketplaces": {"mps-cdci-agents": {"source": source, "autoUpdate": True}},
                       "enabledPlugins": {"mps-git-flow@mps-cdci-agents": True}, "attribution": False}, handle)
        return project

    def run_in(self, folder, argv, extra_env=None):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="utf-8")
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(folder)
        env = dict(self.environ, GIT_CONFIG_NOSYSTEM="1", **(extra_env or {}))
        with mock.patch.object(sys, "stdout", stream), mock.patch.dict(os.environ, env):
            mps.main(argv)
        stream.flush()
        return json.loads(buffer.getvalue().decode("utf-8"))

    @unittest.skipIf(GIT is None, "git is not installed")
    def test_project_on_legacy_repo_exempts_members_until_it_moves(self):
        self.write_known(_known({"source": "github", "repo": LEGACY_REPO}))
        project = self.make_project({"source": "github", "repo": LEGACY_REPO})
        result = self.run_in(project, ["env", "check"], {mps.NONESSENTIAL_TRAFFIC_ENV: "1"})
        self.assertEqual(result["error"], "env_missing")  # not blocked
        self.assertIn("legacy_project_source", [w["code"] for w in result["warnings"]])
        # The lead moves the project: setup is exempt and says the lead's own machine must switch first.
        setup = self.run_in(project, ["project", "setup"])
        self.assertTrue(setup["ok"], setup)
        self.assertEqual(setup["changes"], ["marketplace_source_migrated"])
        self.assertEqual(setup["machine_source_legacy"]["marketplaces"], ["mps-cdci-agents"])
        self.assertEqual(setup["machine_source_legacy"]["commands"][0],
                         "claude plugin marketplace remove mps-cdci-agents")
        # From now on the project names the shared repo, so this machine is blocked until it switches.
        self.assertEqual(self.run_in(project, ["env", "check"])["error"], "plugin_source_legacy")
        self.write_known(_known({"source": "github", "repo": mps.MARKETPLACE_REPO}))
        self.assertNotIn("machine_source_legacy", self.run_in(project, ["project", "setup"]))
        self.assertEqual(self.run_in(project, ["env", "check"], {mps.NONESSENTIAL_TRAFFIC_ENV: "1"})["error"],
                         "env_missing")

    def test_hooks_json(self):
        with open(os.path.join(HOOKS_DIR, "hooks.json"), encoding="utf-8") as handle:
            hooks = json.load(handle)["hooks"]
        command = hooks["SessionStart"][0]["hooks"][0]["command"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/legacy-source-check.sh", command)

    def test_hook_script_is_lf_and_in_sync(self):
        data = _read_bytes(LEGACY_HOOK_SH)
        self.assertNotIn(b"\r", data)
        text = data.decode("utf-8")
        self.assertIn('legacy_repo="%s"' % mps.LEGACY_MARKETPLACE_REPOS[0], text)
        self.assertIn('shared_repo="%s"' % mps.MARKETPLACE_REPO, text)

    def run_hook(self, project_settings=None):
        project = os.path.join(self.tmp, "project")
        os.makedirs(os.path.join(project, ".claude"), exist_ok=True)
        if project_settings is not None:
            with open(os.path.join(project, ".claude", "settings.json"), "w", encoding="utf-8") as handle:
                json.dump(project_settings, handle)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=project.replace("\\", "/"),
                   **{mps.PLUGINS_DIR_ENV: self.tmp.replace("\\", "/")})
        result = subprocess.run([BASH, LEGACY_HOOK_SH.replace("\\", "/")], env=env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.decode("utf-8").strip()
        return json.loads(out) if out else None

    @unittest.skipIf(BASH is None, "bash (Git Bash on Windows) not found")
    def test_hook_script(self):
        self.assertIsNone(self.run_hook())  # no registry at all
        self.write_known(_known({"source": "github", "repo": mps.MARKETPLACE_REPO}))
        self.assertIsNone(self.run_hook())
        self.write_known(_known({"source": "github", "repo": LEGACY_REPO}))
        machine = self.run_hook()
        self.assertEqual(machine["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("repo cá nhân của hungbt", machine["systemMessage"])
        self.assertIn("/plugin marketplace remove mps-cdci-agents", machine["systemMessage"])
        self.assertIn("plugin_source_legacy", machine["hookSpecificOutput"]["additionalContext"])
        project = self.run_hook({"extraKnownMarketplaces": {"mps-cdci-agents": {
            "source": {"source": "github", "repo": LEGACY_REPO}}}})
        self.assertIn("lead", project["systemMessage"])
        self.assertNotIn("/plugin marketplace remove", project["systemMessage"])
        # Only a real source counts, like points_to_legacy_repo: a look-alike repo or a local folder is ignored.
        for source in ({"source": "github", "repo": LEGACY_REPO + "-fork"},
                       {"source": "directory", "path": "/home/me/ghq/github.com-mirror/" + LEGACY_REPO + "/x"}):
            self.write_known(_known(source))
            self.assertIsNone(self.run_hook(), source)
        self.write_known(_known({"source": "git", "url": "git@github.com:hung-bui-121/mps-cdci-agents.git"}))
        self.assertIsNotNone(self.run_hook())


WHATS_NEW_SH = os.path.join(HOOKS_DIR, "whats-new.sh")


class WhatsNewHookTests(unittest.TestCase):
    """hooks/whats-new.sh: release notes shown once per new version, from the notes shipped with the plugin."""

    NOTES = ("# Có gì mới\n\nGiới thiệu.\n\n"
             "## 0.4.0 - 2026-12-01\n- Chưa phát hành.\n\n"
             "## 0.3.0 - 2026-11-20\n- Tính năng \"mới\" C:\\path\tvới tab.\n- Dòng dài\n  được nối tiếp.\n\n"
             "## 0.2.0 - 2026-11-10\n- Bản hai.\n\n"
             "## 0.1.0\n- Bản đầu.\n")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mps-whatsnew-")
        self.addCleanup(_rmtree, self.tmp)
        self.root = os.path.join(self.tmp, "plugin")
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(os.path.join(self.root, ".claude-plugin"))
        self.install("0.3.0")
        # Windows checkouts (autocrlf) give the notes CRLF line endings: the hook must cope.
        with open(os.path.join(self.root, "RELEASE_NOTES.md"), "w", encoding="utf-8", newline="\r\n") as handle:
            handle.write(self.NOTES)

    def install(self, version):
        with open(os.path.join(self.root, ".claude-plugin", "plugin.json"), "w", encoding="utf-8",
                  newline="\r\n") as handle:
            handle.write('{\n  "name": "mps-git-flow",\n  "version": "%s"\n}\n' % version)

    def state_path(self):
        return os.path.join(self.config, "mps-git-flow", "last_seen_version")

    def seen(self, version):
        os.makedirs(os.path.dirname(self.state_path()), exist_ok=True)
        with open(self.state_path(), "w", encoding="utf-8") as handle:
            handle.write(version + "\n")

    def run_hook(self):
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT=self.root.replace("\\", "/"),
                   CLAUDE_CONFIG_DIR=self.config.replace("\\", "/"))
        result = subprocess.run([BASH, WHATS_NEW_SH.replace("\\", "/")], env=env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.decode("utf-8").strip()
        return json.loads(out) if out else None

    def test_shipped_hook_is_registered_and_lf(self):
        with open(os.path.join(HOOKS_DIR, "hooks.json"), encoding="utf-8") as handle:
            commands = [hook["command"] for group in json.load(handle)["hooks"]["SessionStart"]
                        for hook in group["hooks"]]
        self.assertIn('bash "${CLAUDE_PLUGIN_ROOT}/hooks/whats-new.sh"', commands)
        self.assertNotIn(b"\r", _read_bytes(WHATS_NEW_SH))

    @unittest.skipIf(BASH is None, "bash (Git Bash on Windows) not found")
    def test_first_run_shows_only_the_installed_version_once(self):
        shown = self.run_hook()
        message = shown["systemMessage"]
        self.assertTrue(message.startswith("mps-git-flow bản 0.3.0 - có gì mới:\nBản 0.3.0:\n"), message)
        self.assertIn('- Tính năng "mới" C:\\path với tab.', message)  # quotes / backslash / tab survive JSON
        self.assertIn("- Dòng dài được nối tiếp.", message)
        for other in ("0.4.0", "0.2.0", "Bản đầu", "Giới thiệu", "\r"):
            self.assertNotIn(other, message)
        self.assertIn("RELEASE_NOTES.md", message)
        self.assertEqual(shown["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("0.3.0", shown["hookSpecificOutput"]["additionalContext"])
        with open(self.state_path(), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "0.3.0")
        self.assertIsNone(self.run_hook())  # once per version

    @unittest.skipIf(BASH is None, "bash (Git Bash on Windows) not found")
    def test_update_shows_every_version_since_the_last_one_seen(self):
        self.seen("0.1.0")
        message = self.run_hook()["systemMessage"]
        self.assertIn("Bản 0.3.0:", message)
        self.assertIn("Bản 0.2.0:\n- Bản hai.", message)
        self.assertNotIn("Bản 0.1.0", message)
        self.assertNotIn("0.4.0", message)  # newer than what is installed
        self.assertLess(message.index("Bản 0.3.0"), message.index("Bản 0.2.0"))
        self.install("0.4.0")
        newer = self.run_hook()["systemMessage"]  # last seen is now 0.3.0
        self.assertIn("Bản 0.4.0:\n- Chưa phát hành.", newer)
        self.assertNotIn("Bản 0.3.0", newer)

    @unittest.skipIf(BASH is None, "bash (Git Bash on Windows) not found")
    def test_unknown_last_version_or_missing_notes(self):
        self.seen("9.9.9")  # e.g. a downgrade: only the installed version
        message = self.run_hook()["systemMessage"]
        self.assertIn("Bản 0.3.0:", message)
        self.assertNotIn("Bản 0.2.0", message)
        self.install("0.5.0")  # a version without notes: nothing to show, nothing breaks
        self.assertIsNone(self.run_hook())
        os.remove(os.path.join(self.root, "RELEASE_NOTES.md"))
        self.install("0.6.0")
        self.assertIsNone(self.run_hook())


if __name__ == "__main__":
    unittest.main()
