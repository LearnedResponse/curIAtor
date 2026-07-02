"""CLI handlers for local users and auth-mode configuration."""
from __future__ import annotations

import re
from pathlib import Path

from . import auth
from .config import load_config


def cmd_user(args) -> int:
    """Manage local-login users (`auth.mode: local`) — hashed passwords in the gitignored users file.
    `add` upserts (re-running it keeps the existing name/groups unless you pass --name/--groups);
    `passwd` changes only the password (so it can't silently wipe the groups that gate elevated runs)."""
    cfg = load_config()
    users_file = (cfg.get("auth") or {}).get("users_file")
    users = auth.load_users_file(users_file)
    if args.action == "list":
        if not users:
            print("curiator: no local users yet — `curiator user add <email>`")
        for email, u in sorted(users.items()):
            state = "disabled" if u.get("disabled") else "active"
            print(f"  {email}  ·  {u.get('name') or '—'}  ·  groups={u.get('groups') or []}  ·  {state}")
        return 0
    if not args.email:
        print(f"curiator: `user {args.action}` needs an <email>"); return 1
    if args.action in {"disable", "enable"}:
        existing = users.get(args.email)
        if not existing:
            print(f"curiator: no such user {args.email}"); return 1
        existing["disabled"] = args.action == "disable"
        users[args.email] = existing
        auth.save_users_file(users_file, users)
        print(f"curiator: {args.action}d {args.email}")
        return 0
    if args.action == "remove":
        if users.pop(args.email, None) is None:
            print(f"curiator: no such user {args.email}"); return 1
        auth.save_users_file(users_file, users)
        print(f"curiator: removed {args.email}")
        return 0
    # add (upsert) / passwd (change only the password)
    existing = users.get(args.email) or {}
    if args.action == "passwd" and not existing:
        print(f"curiator: no such user {args.email} — `curiator user add {args.email}` to create it"); return 1
    from werkzeug.security import generate_password_hash
    pw = args.password
    if not pw:
        import getpass
        pw = getpass.getpass("password: ")
        if pw != getpass.getpass("confirm:  "):
            print("curiator: passwords don't match"); return 1
    if not pw:
        print("curiator: empty password"); return 1
    if args.action == "passwd":                          # change ONLY the password — keep name/groups/etc.
        rec = {**existing, "password_hash": generate_password_hash(pw)}
    else:                                                # add: merge — keep existing name/groups unless overridden
        name = args.name if args.name is not None else (existing.get("name") or args.email.split("@")[0])
        groups = ([g.strip() for g in args.groups.split(",") if g.strip()]
                  if args.groups is not None else (existing.get("groups") or []))
        rec = {"name": name, "groups": groups, "password_hash": generate_password_hash(pw)}
        if existing.get("disabled"):
            rec["disabled"] = True
    users[args.email] = rec
    auth.save_users_file(users_file, users)
    verb = "changed password for" if args.action == "passwd" else ("updated" if existing else "added")
    print(f"curiator: {verb} local user {args.email} → {users_file}")
    return 0


def cmd_auth(args) -> int:
    """Show or set `auth.mode` in gallery.yaml (none | local | header | oidc), preserving comments."""
    cfg = load_config()
    gallery = Path(cfg["gallery_path"])
    if not args.mode:
        print(f"curiator: auth.mode = {cfg['auth']['mode']}  ({gallery})")
        return 0
    text = gallery.read_text()
    pat = re.compile(r"(?ms)^(auth:[^\n]*\n(?:[ \t]+[^\n]*\n)*?[ \t]+mode:[ \t]*)(\S+)")
    if pat.search(text):
        text = pat.sub(lambda m: m.group(1) + args.mode, text, count=1)   # keep the inline comment
    else:
        text += ("" if text.endswith("\n") else "\n") + f"\nauth:\n  mode: {args.mode}\n"
    gallery.write_text(text)
    print(f"curiator: auth.mode → {args.mode}  ({gallery})  — restart `curiator up` to apply")
    if args.mode == "local":
        if not auth.load_users_file(cfg["auth"]["users_file"]):
            print("curiator: no local users yet — create one with `curiator user add <email>`")
    return 0
