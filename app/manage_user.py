#!/usr/bin/env python3
import argparse
import getpass
import os
import sqlite3
from argon2 import PasswordHasher

DB_PATH = os.environ.get("DB_PATH", "/data/sync.db")
PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)

def conn():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def list_users(_args):
    with conn() as db:
        rows = db.execute("SELECT id, username, role, active, totp_enabled, failed_attempts, locked_until FROM users ORDER BY username").fetchall()
    for row in rows:
        print(dict(row))

def reset_password(args):
    password = getpass.getpass("New password: ")
    confirm = getpass.getpass("Confirm password: ")
    if len(password) < 12 or password != confirm:
        raise SystemExit("Password must be at least 12 characters and both entries must match.")
    with conn() as db:
        cur = db.execute("UPDATE users SET password_hash=?, session_version=session_version+1, failed_attempts=0, locked_until=NULL WHERE username=?", (PH.hash(password), args.username.lower()))
        if not cur.rowcount: raise SystemExit("User not found.")
    print("Password reset and existing sessions invalidated.")

def disable_2fa(args):
    with conn() as db:
        cur = db.execute("UPDATE users SET totp_secret=NULL, totp_enabled=0, recovery_code_hashes='[]', session_version=session_version+1 WHERE username=?", (args.username.lower(),))
        if not cur.rowcount: raise SystemExit("User not found.")
    print("2FA disabled and existing sessions invalidated.")

def unlock(args):
    with conn() as db:
        cur = db.execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username=?", (args.username.lower(),))
        if not cur.rowcount: raise SystemExit("User not found.")
    print("Account unlocked.")

parser=argparse.ArgumentParser(description="YouTube Pinchflat Sync account recovery utility")
sub=parser.add_subparsers(dest="command", required=True)
sub.add_parser("list").set_defaults(func=list_users)
p=sub.add_parser("reset-password"); p.add_argument("username"); p.set_defaults(func=reset_password)
p=sub.add_parser("disable-2fa"); p.add_argument("username"); p.set_defaults(func=disable_2fa)
p=sub.add_parser("unlock"); p.add_argument("username"); p.set_defaults(func=unlock)
args=parser.parse_args(); args.func(args)
