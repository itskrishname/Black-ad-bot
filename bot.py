# ╔══════════════════════════════════════════════════════════════════╗
# ║        𓂃❛ ʙ ʟ ᴀ ᴄ ᴋ ᴡ ᴏ ʟ ғ  ʙ ᴏ ᴛ 𓂃  v4.0                   ║
# ║        All-in-One Telegram Account Manager                       ║
# ║  FIXES in v4:                                                    ║
# ║   ✅ Inline Join = auto-detect & join force-sub channels         ║
# ║   ✅ Message ↔ Account pairing (each acc sends its own msg)      ║
# ║   ✅ Parallel messaging (all accounts run simultaneously)        ║
# ╚══════════════════════════════════════════════════════════════════╝

import subprocess, sys, asyncio, os, logging

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

def _pip(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                           "--disable-pip-version-check", pkg])

try:
    from pyrogram import Client as _C
except Exception:
    subprocess.call([sys.executable, "-m", "pip", "uninstall", "-y", "pyrogram"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("[BW] Installing pyrofork…"); _pip("pyrofork")

try:
    import tgcrypto
except ImportError:
    print("[BW] Installing TgCrypto…"); _pip("TgCrypto")

import sqlite3, random, re, json, time, traceback
from datetime import datetime
from typing import Dict, List, Optional, Callable, Tuple
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.enums import ParseMode
from pyrogram import errors as tg_errors
from pyrogram import errors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("BlackWolf")


# ══════════════════════════════════════════════════════════════════
# 2. CONFIG
# ══════════════════════════════════════════════════════════════════

class CF:
    BOT_TOKEN  = os.environ.get("BOT_TOKEN",  "8740942836:AAHm2V9OInYXj4F632E-9n-t6-CpuAg7_eM")
    API_ID     = int(os.environ.get("API_ID", "38177386"))
    API_HASH   = os.environ.get("API_HASH",   "bf371f9673ff4f61226e2ea8d3fabcee")
    OWNER_IDS  = [6209797666]
    LOGS       = -1003849706641
    DB_PATH    = os.environ.get("DB_PATH",    "bw_bot.db")

    JOIN_PATTERN = [(5, 30*60)]  # (joins, wait_seconds) repeating — 30 min fixed gap
    JOIN_DELAY   = (8, 18)
    MSG_DELAY    = (3, 8)
    FLOOD_EXTRA  = (60, 120)

    @classmethod
    def is_owner(cls, uid: int) -> bool:
        return uid in cls.OWNER_IDS


# ══════════════════════════════════════════════════════════════════
# 3. DATABASE
# ══════════════════════════════════════════════════════════════════

class DB:
    def __init__(self):
        self.path = CF.DB_PATH
        self._init()

    def cx(self):
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init(self):
        with self.cx() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS categories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id   INTEGER NOT NULL,
                name       TEXT    NOT NULL,
                gc_delay   INTEGER DEFAULT 3,
                rest_delay INTEGER DEFAULT 180,
                welcome    TEXT    DEFAULT '',
                created_at TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS accounts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                cat_id    INTEGER NOT NULL,
                phone     TEXT    NOT NULL,
                session   TEXT    NOT NULL DEFAULT '',
                status    TEXT    NOT NULL DEFAULT 'active',
                frozen_at TEXT,
                UNIQUE(cat_id, phone),
                FOREIGN KEY(cat_id) REFERENCES categories(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                cat_id INTEGER NOT NULL,
                text   TEXT    NOT NULL,
                FOREIGN KEY(cat_id) REFERENCES categories(id)
            );
            CREATE TABLE IF NOT EXISTS msg_accounts (
                msg_id INTEGER NOT NULL,
                acc_id INTEGER NOT NULL,
                PRIMARY KEY(msg_id, acc_id),
                FOREIGN KEY(msg_id) REFERENCES messages(id),
                FOREIGN KEY(acc_id) REFERENCES accounts(id)
            );
            CREATE TABLE IF NOT EXISTS groups (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                cat_id  INTEGER NOT NULL,
                link    TEXT    NOT NULL,
                chat_id INTEGER DEFAULT 0,
                title   TEXT    DEFAULT '',
                joined  INTEGER DEFAULT 0,
                UNIQUE(cat_id, link),
                FOREIGN KEY(cat_id) REFERENCES categories(id)
            );
            CREATE TABLE IF NOT EXISTS force_subs (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                cat_id INTEGER NOT NULL,
                link   TEXT    NOT NULL,
                UNIQUE(cat_id, link)
            );
            CREATE TABLE IF NOT EXISTS admins (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL UNIQUE,
                username   TEXT    DEFAULT '',
                name       TEXT    DEFAULT '',
                added_by   INTEGER NOT NULL,
                added_at   TEXT    DEFAULT (datetime('now'))
            );
            """)

    # ── Category ──────────────────────────────────────────────────
    def cat_create(self, owner_id: int, name: str) -> int:
        with self.cx() as c:
            return c.execute(
                "INSERT INTO categories(owner_id,name) VALUES(?,?)",
                (owner_id, name)
            ).lastrowid

    def cat_get(self, cat_id: int):
        with self.cx() as c:
            return c.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()

    def cat_list(self, owner_id: int) -> list:
        with self.cx() as c:
            return c.execute(
                "SELECT * FROM categories WHERE owner_id=? ORDER BY id", (owner_id,)
            ).fetchall()

    def cat_delete(self, cat_id: int):
        with self.cx() as c:
            c.executescript(f"""
                DELETE FROM msg_accounts WHERE msg_id IN
                    (SELECT id FROM messages WHERE cat_id={cat_id});
                DELETE FROM force_subs WHERE cat_id={cat_id};
                DELETE FROM groups     WHERE cat_id={cat_id};
                DELETE FROM messages   WHERE cat_id={cat_id};
                DELETE FROM accounts   WHERE cat_id={cat_id};
                DELETE FROM categories WHERE id={cat_id};
            """)

    def cat_update(self, cat_id: int, **kw):
        sets = ", ".join(f"{k}=?" for k in kw)
        with self.cx() as c:
            c.execute(f"UPDATE categories SET {sets} WHERE id=?",
                      list(kw.values()) + [cat_id])

    # ── Accounts ──────────────────────────────────────────────────
    def acc_add(self, cat_id: int, phone: str, session: str) -> int:
        with self.cx() as c:
            try:
                return c.execute(
                    "INSERT INTO accounts(cat_id,phone,session) VALUES(?,?,?)",
                    (cat_id, phone, session)
                ).lastrowid
            except sqlite3.IntegrityError:
                c.execute(
                    "UPDATE accounts SET session=?, status='active' WHERE cat_id=? AND phone=?",
                    (session, cat_id, phone)
                )
                row = c.execute(
                    "SELECT id FROM accounts WHERE cat_id=? AND phone=?", (cat_id, phone)
                ).fetchone()
                return row["id"] if row else 0

    def acc_list(self, cat_id: int) -> list:
        with self.cx() as c:
            return c.execute(
                "SELECT * FROM accounts WHERE cat_id=? ORDER BY id", (cat_id,)
            ).fetchall()

    def acc_active(self, cat_id: int) -> list:
        with self.cx() as c:
            return c.execute(
                "SELECT * FROM accounts WHERE cat_id=? AND status='active'", (cat_id,)
            ).fetchall()

    def acc_set_status(self, acc_id: int, status: str):
        frozen_at = datetime.now().isoformat() if status == "frozen" else None
        with self.cx() as c:
            c.execute("UPDATE accounts SET status=?, frozen_at=? WHERE id=?",
                      (status, frozen_at, acc_id))

    def acc_delete(self, acc_id: int):
        with self.cx() as c:
            c.execute("DELETE FROM msg_accounts WHERE acc_id=?", (acc_id,))
            c.execute("DELETE FROM accounts WHERE id=?", (acc_id,))

    def acc_count(self, cat_id: int) -> dict:
        with self.cx() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) as n FROM accounts WHERE cat_id=? GROUP BY status",
                (cat_id,)
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    # ── Messages ──────────────────────────────────────────────────
    def msg_add(self, cat_id: int, text: str) -> int:
        with self.cx() as c:
            return c.execute(
                "INSERT INTO messages(cat_id,text) VALUES(?,?)", (cat_id, text)
            ).lastrowid

    def msg_list(self, cat_id: int) -> list:
        with self.cx() as c:
            return c.execute(
                "SELECT * FROM messages WHERE cat_id=?", (cat_id,)
            ).fetchall()

    def msg_delete(self, msg_id: int):
        with self.cx() as c:
            c.execute("DELETE FROM msg_accounts WHERE msg_id=?", (msg_id,))
            c.execute("DELETE FROM messages WHERE id=?", (msg_id,))

    # ── Message ↔ Account assignments ────────────────────────────
    def msgacc_assign(self, msg_id: int, acc_id: int):
        """Assign an account to a message (this account will send this message)."""
        with self.cx() as c:
            try:
                c.execute("INSERT INTO msg_accounts(msg_id,acc_id) VALUES(?,?)",
                          (msg_id, acc_id))
            except sqlite3.IntegrityError:
                pass  # already assigned

    def msgacc_unassign(self, msg_id: int, acc_id: int):
        with self.cx() as c:
            c.execute("DELETE FROM msg_accounts WHERE msg_id=? AND acc_id=?",
                      (msg_id, acc_id))

    def msgacc_toggle(self, msg_id: int, acc_id: int) -> bool:
        """Toggle assignment. Returns True if now assigned, False if unassigned."""
        with self.cx() as c:
            row = c.execute(
                "SELECT 1 FROM msg_accounts WHERE msg_id=? AND acc_id=?",
                (msg_id, acc_id)
            ).fetchone()
            if row:
                c.execute("DELETE FROM msg_accounts WHERE msg_id=? AND acc_id=?",
                          (msg_id, acc_id))
                return False
            else:
                c.execute("INSERT INTO msg_accounts(msg_id,acc_id) VALUES(?,?)",
                          (msg_id, acc_id))
                return True

    def msgacc_assigned_accs(self, msg_id: int) -> list:
        """Get account IDs assigned to this message."""
        with self.cx() as c:
            return [r[0] for r in c.execute(
                "SELECT acc_id FROM msg_accounts WHERE msg_id=?", (msg_id,)
            ).fetchall()]

    def msgacc_for_account(self, acc_id: int) -> list:
        """Get all messages assigned to this account."""
        with self.cx() as c:
            return c.execute(
                "SELECT m.* FROM messages m "
                "JOIN msg_accounts ma ON m.id=ma.msg_id "
                "WHERE ma.acc_id=?", (acc_id,)
            ).fetchall()

    def msgacc_has_any(self, cat_id: int) -> bool:
        """Returns True if any message in this category has account assignments."""
        with self.cx() as c:
            row = c.execute(
                "SELECT 1 FROM msg_accounts ma "
                "JOIN messages m ON m.id=ma.msg_id "
                "WHERE m.cat_id=? LIMIT 1", (cat_id,)
            ).fetchone()
            return row is not None

    # ── Groups ────────────────────────────────────────────────────
    def grp_add(self, cat_id: int, link: str) -> bool:
        try:
            with self.cx() as c:
                c.execute("INSERT INTO groups(cat_id,link) VALUES(?,?)", (cat_id, link))
            return True
        except sqlite3.IntegrityError:
            return False

    def grp_unjoined(self, cat_id: int) -> list:
        with self.cx() as c:
            return c.execute(
                "SELECT * FROM groups WHERE cat_id=? AND joined=0", (cat_id,)
            ).fetchall()

    def grp_all(self, cat_id: int) -> list:
        with self.cx() as c:
            return c.execute("SELECT * FROM groups WHERE cat_id=?", (cat_id,)).fetchall()

    def grp_mark_joined(self, gid: int, chat_id: int = 0, title: str = ""):
        with self.cx() as c:
            c.execute("UPDATE groups SET joined=1, chat_id=?, title=? WHERE id=?",
                      (chat_id, title, gid))

    def grp_count(self, cat_id: int) -> dict:
        with self.cx() as c:
            total  = c.execute("SELECT COUNT(*) FROM groups WHERE cat_id=?",    (cat_id,)).fetchone()[0]
            joined = c.execute("SELECT COUNT(*) FROM groups WHERE cat_id=? AND joined=1", (cat_id,)).fetchone()[0]
        return {"total": total, "joined": joined, "pending": total - joined}

    def grp_delete_all(self, cat_id: int):
        with self.cx() as c:
            c.execute("DELETE FROM groups WHERE cat_id=?", (cat_id,))

    # ── Force Subs ────────────────────────────────────────────────
    def fsub_add(self, cat_id: int, link: str) -> bool:
        try:
            with self.cx() as c:
                c.execute("INSERT INTO force_subs(cat_id,link) VALUES(?,?)", (cat_id, link))
            return True
        except sqlite3.IntegrityError:
            return False

    def fsub_list(self, cat_id: int) -> list:
        with self.cx() as c:
            return c.execute("SELECT * FROM force_subs WHERE cat_id=?", (cat_id,)).fetchall()

    def fsub_delete(self, fid: int):
        with self.cx() as c:
            c.execute("DELETE FROM force_subs WHERE id=?", (fid,))

    # ── Admins ────────────────────────────────────────────────────
    def admin_add(self, user_id: int, username: str, name: str, added_by: int) -> bool:
        try:
            with self.cx() as c:
                c.execute(
                    "INSERT INTO admins(user_id,username,name,added_by) VALUES(?,?,?,?)",
                    (user_id, username, name, added_by)
                )
            return True
        except sqlite3.IntegrityError:
            return False  # already admin

    def admin_remove(self, user_id: int) -> bool:
        with self.cx() as c:
            r = c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
            return r.rowcount > 0

    def admin_list(self) -> list:
        with self.cx() as c:
            return c.execute(
                "SELECT * FROM admins ORDER BY added_at"
            ).fetchall()

    def admin_exists(self, user_id: int) -> bool:
        with self.cx() as c:
            row = c.execute(
                "SELECT 1 FROM admins WHERE user_id=?", (user_id,)
            ).fetchone()
            return row is not None


# ══════════════════════════════════════════════════════════════════
# 4. CLIENT POOL
# ══════════════════════════════════════════════════════════════════

class Pool:
    def __init__(self):
        self._cache: Dict[int, Client] = {}

    async def get(self, acc) -> Optional[Client]:
        acc_id = acc["id"]
        if acc_id in self._cache:
            cl = self._cache[acc_id]
            if getattr(cl, "is_connected", False):
                return cl
            try: await cl.stop()
            except Exception: pass
            self._cache.pop(acc_id, None)

        if not acc["session"]:
            return None
        try:
            cl = Client(
                name=f"bw_{acc_id}",
                api_id=CF.API_ID,
                api_hash=CF.API_HASH,
                session_string=acc["session"],
                no_updates=True,
                in_memory=True,
            )
            await cl.start()
            self._cache[acc_id] = cl
            return cl
        except Exception as e:
            log.warning(f"[Pool] acc {acc['phone']} connect failed: {e}")
            return None

    async def stop(self, acc_id: int):
        cl = self._cache.pop(acc_id, None)
        if cl:
            try: await cl.stop()
            except Exception: pass

    async def stop_all(self):
        for cl in list(self._cache.values()):
            try: await cl.stop()
            except Exception: pass
        self._cache.clear()

    async def validate_session(self, session_str: str) -> Tuple[bool, str, str]:
        try:
            cl = Client(
                name="bw_validate",
                api_id=CF.API_ID,
                api_hash=CF.API_HASH,
                session_string=session_str,
                no_updates=True,
                in_memory=True,
            )
            await cl.start()
            me    = await cl.get_me()
            phone = me.phone_number or "unknown"
            name  = f"{me.first_name or ''} {me.last_name or ''}".strip()
            await cl.stop()
            return True, phone, name
        except Exception as e:
            return False, "", str(e)

    async def otp_send_code(self, phone: str) -> Tuple[bool, object, str]:
        try:
            cl = Client(
                name=f"bw_otp_{phone.replace('+','')}",
                api_id=CF.API_ID,
                api_hash=CF.API_HASH,
                in_memory=True,
            )
            await cl.connect()
            sent = await cl.send_code(phone)
            return True, cl, sent.phone_code_hash
        except Exception as e:
            return False, None, str(e)

    async def otp_sign_in(self, cl, phone: str, phone_code_hash: str,
                          code: str) -> Tuple[bool, str, str, bool]:
        try:
            await cl.sign_in(phone, phone_code_hash, code)
            me      = await cl.get_me()
            session = await cl.export_session_string()
            name    = f"{me.first_name or ''} {me.last_name or ''}".strip()
            await cl.disconnect()
            return True, session, name, False
        except errors.SessionPasswordNeeded:
            return False, "", "", True
        except Exception as e:
            return False, "", str(e), False

    async def otp_check_password(self, cl, password: str) -> Tuple[bool, str, str]:
        try:
            await cl.check_password(password)
            me      = await cl.get_me()
            session = await cl.export_session_string()
            name    = f"{me.first_name or ''} {me.last_name or ''}".strip()
            await cl.disconnect()
            return True, session, name
        except Exception as e:
            return False, "", str(e)


# ══════════════════════════════════════════════════════════════════
# 5. INLINE JOIN HELPER  (auto-detect & join force-sub channels)
# ══════════════════════════════════════════════════════════════════

DEAD_ERRORS = {
    "BANNED", "DEACTIVATED", "AUTH_KEY_UNREGISTERED", "USER_DEACTIVATED",
    "SESSION_REVOKED", "SESSION_EXPIRED", "AUTH_KEY_INVALID",
    "USER_DEACTIVATED_BAN", "ACCOUNT_BANNED", "AUTH_KEY_DUPLICATED",
}
INVITE_ERRORS = {
    "INVITE_HASH_EXPIRED", "INVITE_HASH_INVALID",
    "INVITEHASHEXPIRED", "INVITEHASHINVALID",
}

def _extract_channel_from_error(error_str: str) -> Optional[str]:
    """
    Try to extract a @username or t.me/link from an error message.
    Telegram sometimes includes the required channel in error text.
    """
    # Look for @username pattern
    m = re.search(r"@([a-zA-Z0-9_]{4,32})", error_str)
    if m:
        return "@" + m.group(1)
    # Look for t.me/ pattern
    m = re.search(r"(t\.me/[a-zA-Z0-9_+/]+)", error_str)
    if m:
        link = m.group(1)
        return "https://" + link if not link.startswith("http") else link
    return None


async def try_join_channel(client: Client, link: str) -> bool:
    """
    Attempt to join a channel/group by link.
    Returns True if joined successfully (or already member).
    """
    try:
        link = link.strip()
        if re.search(r"t\.me/\+|t\.me/joinchat/", link):
            if not link.startswith("http"):
                link = "https://" + link
            h = re.split(r"joinchat/|\+", link)[-1].rstrip("/").strip()
            await client.join_chat(h)
        elif link.startswith("@"):
            await client.join_chat(link[1:])
        elif link.startswith("http"):
            slug = link.rstrip("/").split("/")[-1]
            await client.join_chat(slug)
        else:
            await client.join_chat(link)
        return True
    except tg_errors.UserAlreadyParticipant:
        return True
    except Exception as e:
        log.debug(f"[InlineJoin] join {link} failed: {e}")
        return False


async def join_force_subs(client: Client, fsubs: list, phone: str) -> int:
    """
    Join all stored force-sub channels for this category.
    Returns count of channels joined.
    """
    joined = 0
    for fsub in fsubs:
        link = fsub["link"]
        ok   = await try_join_channel(client, link)
        if ok:
            joined += 1
            log.info(f"[InlineJoin] {phone} joined force-sub: {link}")
        else:
            log.warning(f"[InlineJoin] {phone} failed force-sub: {link}")
        await asyncio.sleep(random.uniform(3, 8))
    return joined


def _friendly_error(e: Exception, phone: str) -> str:
    es = str(e).upper()
    if any(k in es for k in INVITE_ERRORS):
        return "Invite link expired or revoked"
    if "PEER_FLOOD" in es:
        return f"Account {phone} rate-limited (PEER_FLOOD)"
    if "CHANNELS_TOO_MUCH" in es:
        return f"Account {phone} in too many channels"
    if "USER_BANNED_IN_CHANNEL" in es:
        return "Account banned in this group"
    if "INVITE_REQUEST_SENT" in es:
        return "Join request sent — awaiting admin approval"
    if "CHANNEL_PRIVATE" in es:
        return "Group is private/deleted"
    if "USER_ALREADY_PARTICIPANT" in es:
        return "Already a member"
    if any(k in es for k in DEAD_ERRORS):
        return f"Account {phone} is banned/deactivated"
    return str(e)[:100]


# ══════════════════════════════════════════════════════════════════
# 6. JOIN ENGINE
# ══════════════════════════════════════════════════════════════════

class JoinEngine:
    def __init__(self, db: DB, pool: Pool, notify: Callable):
        self.db     = db
        self.pool   = pool
        self.notify = notify
        self._tasks: Dict[int, asyncio.Task] = {}
        self._stats: Dict[int, dict]         = {}

    def is_running(self, cat_id: int) -> bool:
        t = self._tasks.get(cat_id)
        return bool(t and not t.done())

    def get_stats(self, cat_id: int) -> dict:
        return self._stats.get(cat_id, {
            "joined": 0, "failed": 0, "total": 0,
            "active_accs": 0, "started": None, "failures": []
        })

    def stop(self, cat_id: int):
        t = self._tasks.pop(cat_id, None)
        if t and not t.done():
            t.cancel()

    async def start(self, cat_id: int, owner_id: int) -> Tuple[bool, str]:
        if self.is_running(cat_id):
            return False, "Already running for this category."

        accs   = self.db.acc_active(cat_id)
        groups = self.db.grp_unjoined(cat_id)

        if not accs:   return False, "No active accounts in this category."
        if not groups: return False, "No groups to join (all joined or none added)."

        groups_plain = [dict(g) for g in groups]

        self._stats[cat_id] = {
            "joined": 0, "failed": 0,
            "total": len(groups_plain), "active_accs": len(accs),
            "started": datetime.now().strftime("%H:%M:%S"),
            "failures": [],
            "_joined_ids": set(),
            "_dead_links": set(),  # links confirmed expired/invalid — skip for all accounts
        }

        t = asyncio.create_task(self._run(cat_id, owner_id, accs, groups_plain))
        self._tasks[cat_id] = t
        return True, (
            f"✅ Started! {len(accs)} account(s) will each join "
            f"all {len(groups_plain)} group(s)."
        )

    async def _run(self, cat_id, owner_id, accs, groups):
        cat      = self.db.cat_get(cat_id)
        cat_name = cat["name"] if cat else "?"
        fsubs    = self.db.fsub_list(cat_id)
        n_accs   = len(accs)

        await self.notify(owner_id,
            f"🔗 <b>Bulk Join Started</b>\n\n"
            f"📁 <b>{cat_name}</b>\n"
            f"👥 Accounts : <code>{n_accs}</code>\n"
            f"🌐 Groups   : <code>{len(groups)}</code>\n"
            f"🔄 Force-sub channels: <code>{len(fsubs)}</code>\n\n"
            f"<b>Rate limit per account (auto):</b>\n"
            f"  5 joins → 30 min wait\n"
            f"  (repeats — fully automatic)\n\n"
            f"All accounts run in parallel. Updates after each batch."
        )

        # Every account tries ALL groups in parallel
        workers = [
            self._worker(cat_id, owner_id, acc, list(groups), list(fsubs))
            for acc in accs
        ]

        stopped_early = False
        try:
            await asyncio.gather(*workers, return_exceptions=False)
        except asyncio.CancelledError:
            stopped_early = True
        except Exception as e:
            log.error(f"[Join] gather error: {e}\n{traceback.format_exc()}")
        finally:
            s        = self._stats[cat_id]
            failures = s.get("failures", [])
            seen: set = set()
            unique_f  = []
            for f in failures:
                if f["link"] not in seen:
                    seen.add(f["link"]); unique_f.append(f)

            fail_lines = ""
            if unique_f:
                fail_lines = "\n\n<b>❌ Failure Details:</b>\n"
                for f in unique_f[:10]:
                    short  = f["link"].split("/")[-1] or f["link"]
                    reason = f["reason"][:70]
                    fail_lines += f"• <code>{short}</code>\n  <i>{reason}</i>\n"
                if len(unique_f) > 10:
                    fail_lines += f"<i>…and {len(unique_f)-10} more</i>"

            word = "Stopped" if stopped_early else "Complete"
            await self.notify(owner_id,
                f"{'⏹' if stopped_early else '✅'} "
                f"<b>Bulk Join {word}</b>\n\n"
                f"📁 <b>{cat_name}</b>\n"
                f"✅ Joined  : <code>{s['joined']}</code> unique groups\n"
                f"❌ Failed  : <code>{s['failed']}</code> attempts\n"
                f"📋 Total   : <code>{s['total']}</code> groups\n"
                f"👥 Accounts: <code>{n_accs}</code>"
                + fail_lines
            )
            self._tasks.pop(cat_id, None)

    async def _worker(self, cat_id, owner_id, acc, groups, fsubs):
        acc_id = acc["id"]
        phone  = acc["phone"]

        # ── Step 1: Connect account ───────────────────────────────
        try:
            client = await self.pool.get(acc)
        except Exception:
            client = None

        if not client:
            reason = f"Session invalid/expired for {phone}"
            log.warning(f"[Join] {phone}: can't connect")
            self._stats[cat_id]["failed"] += len(groups)
            for row in groups:
                self._stats[cat_id]["failures"].append(
                    {"link": row["link"], "reason": reason})
            await self.notify(owner_id,
                f"⚠️ <b>Connect Failed</b>\n"
                f"📱 <code>{phone}</code> — session invalid\n"
                f"<i>Re-upload session for this account.</i>"
            )
            return

        # ── Step 2: Auto-join force-sub channels FIRST ────────────
        if fsubs:
            log.info(f"[Join] {phone}: joining {len(fsubs)} force-sub channels first…")
            await join_force_subs(client, fsubs, phone)
            # Small pause after joining channels
            await asyncio.sleep(random.uniform(5, 10))

        # ── Step 3: Join each group ───────────────────────────────
        pattern_idx = 0
        batch_done  = 0

        for row in groups:
            gid  = row["id"]
            link = row["link"]

            # Skip globally dead links (expired/invalid — confirmed by another account)
            if link in self._stats[cat_id].get("_dead_links", set()):
                log.info(f"[Join] {phone}: skipping dead link {link}")
                self._stats[cat_id]["failed"] += 1
                self._stats[cat_id]["failures"].append(
                    {"link": link, "reason": "Invite link expired or revoked (skipped)"})
                continue

            # Rate-limit batch check
            batch_size, wait_secs = CF.JOIN_PATTERN[pattern_idx % len(CF.JOIN_PATTERN)]
            if batch_done >= batch_size:
                jitter = random.uniform(10, 60)
                total  = wait_secs + jitter
                log.info(f"[Join] {phone}: batch done → sleeping {total:.0f}s")
                await self.notify(owner_id,
                    f"⏳ <b>{phone}</b> — batch of {batch_size} done.\n"
                    f"Sleeping <code>{int(total//60)}m {int(total%60)}s</code>…"
                )
                try:
                    await asyncio.sleep(total)
                except asyncio.CancelledError:
                    return
                batch_done  = 0
                pattern_idx += 1

            # Inter-join delay
            try:
                await asyncio.sleep(random.uniform(*CF.JOIN_DELAY))
            except asyncio.CancelledError:
                return

            # ── Attempt join ──────────────────────────────────────
            try:
                joined_entity = await self._do_join(client, link)
                if joined_entity:
                    cid   = getattr(joined_entity, "id",    0)
                    title = getattr(joined_entity, "title", "")
                    self.db.grp_mark_joined(gid, cid, title)
                    if gid not in self._stats[cat_id]["_joined_ids"]:
                        self._stats[cat_id]["_joined_ids"].add(gid)
                        self._stats[cat_id]["joined"] += 1
                    batch_done += 1
                    log.info(f"[Join] {phone}: ✅ {link}")
                else:
                    self._stats[cat_id]["failed"] += 1
                    self._stats[cat_id]["failures"].append(
                        {"link": link, "reason": "join_chat returned None"})

            except asyncio.CancelledError:
                return

            except tg_errors.UserAlreadyParticipant:
                self.db.grp_mark_joined(gid, 0, "")
                if gid not in self._stats[cat_id]["_joined_ids"]:
                    self._stats[cat_id]["_joined_ids"].add(gid)
                    self._stats[cat_id]["joined"] += 1
                batch_done += 1

            except tg_errors.InviteRequestSent:
                self._stats[cat_id]["failed"] += 1
                self._stats[cat_id]["failures"].append(
                    {"link": link, "reason": "Join request sent — needs admin approval"})

            except tg_errors.FloodWait as e:
                wait = e.value + random.randint(*CF.FLOOD_EXTRA)
                log.warning(f"[Join] {phone}: FloodWait {e.value}s → {wait}s")
                try:
                    await asyncio.sleep(wait)
                except asyncio.CancelledError:
                    return
                # Single retry
                try:
                    joined_entity = await self._do_join(client, link)
                    if joined_entity:
                        cid   = getattr(joined_entity, "id",    0)
                        title = getattr(joined_entity, "title", "")
                        self.db.grp_mark_joined(gid, cid, title)
                        if gid not in self._stats[cat_id]["_joined_ids"]:
                            self._stats[cat_id]["_joined_ids"].add(gid)
                            self._stats[cat_id]["joined"] += 1
                        batch_done += 1
                    else:
                        self._stats[cat_id]["failed"] += 1
                        self._stats[cat_id]["failures"].append(
                            {"link": link, "reason": "None after FloodWait retry"})
                except tg_errors.UserAlreadyParticipant:
                    self.db.grp_mark_joined(gid, 0, "")
                    if gid not in self._stats[cat_id]["_joined_ids"]:
                        self._stats[cat_id]["_joined_ids"].add(gid)
                        self._stats[cat_id]["joined"] += 1
                    batch_done += 1
                except asyncio.CancelledError:
                    return
                except Exception as re2:
                    self._stats[cat_id]["failed"] += 1
                    self._stats[cat_id]["failures"].append(
                        {"link": link, "reason": f"Retry: {_friendly_error(re2, phone)}"})

            except Exception as e:
                es     = str(e).upper()
                reason = _friendly_error(e, phone)

                # ── Expired/invalid invite link → mark dead globally ──
                if any(k in es for k in INVITE_ERRORS):
                    self._stats[cat_id]["_dead_links"].add(link)
                    self._stats[cat_id]["failed"] += 1
                    self._stats[cat_id]["failures"].append({"link": link, "reason": reason})
                    log.info(f"[Join] {phone}: marking dead link {link}")
                    continue

                # ── Dead account → stop this worker ──────────────
                if any(k in es for k in DEAD_ERRORS):
                    self.db.acc_set_status(acc_id, "frozen")
                    await self.notify(owner_id,
                        f"⚠️ <b>Account Frozen</b>\n"
                        f"📱 <code>{phone}</code>\n❌ <code>{reason}</code>"
                    )
                    remaining = [r for r in groups
                                 if r["id"] >= gid]
                    self._stats[cat_id]["failed"] += len(remaining)
                    for rl in remaining:
                        self._stats[cat_id]["failures"].append(
                            {"link": rl["link"], "reason": f"{phone} frozen"})
                    return

                # ── Too many channels ─────────────────────────────
                if "CHANNELS_TOO_MUCH" in es:
                    await self.notify(owner_id,
                        f"⚠️ <b>Too Many Channels</b>\n"
                        f"📱 <code>{phone}</code>\n"
                        f"<i>Leave some groups and retry.</i>"
                    )
                    remaining = [r for r in groups if r["id"] >= gid]
                    self._stats[cat_id]["failed"] += len(remaining)
                    for rl in remaining:
                        self._stats[cat_id]["failures"].append(
                            {"link": rl["link"], "reason": f"{phone}: too many channels"})
                    return

                # ── PEER_FLOOD → wait, skip this group ───────────
                if "PEER_FLOOD" in es:
                    wait_m = random.randint(30, 60)
                    await self.notify(owner_id,
                        f"⚠️ <b>PEER_FLOOD</b> on <code>{phone}</code>\n"
                        f"Waiting <code>{wait_m}</code> min…"
                    )
                    self._stats[cat_id]["failed"] += 1
                    self._stats[cat_id]["failures"].append({"link": link, "reason": reason})
                    try:
                        await asyncio.sleep(wait_m * 60)
                    except asyncio.CancelledError:
                        return
                    continue

                # ── Force-sub auto-detect ─────────────────────────
                # Some groups show "channel required" in error text.
                # Try to extract and join that channel, then retry once.
                detected_ch = _extract_channel_from_error(str(e))
                if detected_ch:
                    log.info(f"[InlineJoin] Auto-detected required channel: {detected_ch}")
                    joined_ch = await try_join_channel(client, detected_ch)
                    if joined_ch:
                        await asyncio.sleep(random.uniform(5, 10))
                        # Retry the group join once
                        try:
                            joined_entity = await self._do_join(client, link)
                            if joined_entity:
                                cid   = getattr(joined_entity, "id",    0)
                                title = getattr(joined_entity, "title", "")
                                self.db.grp_mark_joined(gid, cid, title)
                                if gid not in self._stats[cat_id]["_joined_ids"]:
                                    self._stats[cat_id]["_joined_ids"].add(gid)
                                    self._stats[cat_id]["joined"] += 1
                                batch_done += 1
                                log.info(f"[InlineJoin] Retry ✅ {link} after joining {detected_ch}")
                                continue
                        except Exception:
                            pass

                # ── All other errors ──────────────────────────────
                log.warning(f"[Join] {phone}: skip {link} → {e}")
                self._stats[cat_id]["failed"] += 1
                self._stats[cat_id]["failures"].append({"link": link, "reason": reason})

    async def _do_join(self, client: Client, link: str):
        link = link.strip()
        if re.search(r"t\.me/\+|t\.me/joinchat/", link):
            if not link.startswith("http"):
                link = "https://" + link
            h = re.split(r"joinchat/|\+", link)[-1].rstrip("/").strip()
            try:
                return await client.join_chat(h)
            except (
                tg_errors.InviteHashExpired,
                tg_errors.InviteHashInvalid,
                tg_errors.UserAlreadyParticipant,
                tg_errors.InviteRequestSent,
                tg_errors.FloodWait,
                asyncio.CancelledError,
            ):
                raise
            except Exception:
                return await client.join_chat(link)
        elif link.startswith("@"):
            return await client.join_chat(link[1:])
        elif link.startswith("http"):
            slug = link.rstrip("/").split("/")[-1]
            return await client.join_chat(slug)
        else:
            return await client.join_chat(link)


# ══════════════════════════════════════════════════════════════════
# 7. MESSAGING ENGINE  (parallel per-account + msg-account pairing)
# ══════════════════════════════════════════════════════════════════

class MsgEngine:
    def __init__(self, db: DB, pool: Pool, notify: Callable):
        self.db     = db
        self.pool   = pool
        self.notify = notify
        self._tasks: Dict[int, asyncio.Task] = {}
        self._stats: Dict[int, dict]         = {}

    def is_running(self, cat_id: int) -> bool:
        t = self._tasks.get(cat_id)
        return bool(t and not t.done())

    def get_stats(self, cat_id: int) -> dict:
        return self._stats.get(cat_id, {"sent": 0, "errors": 0, "loops": 0})

    def stop(self, cat_id: int):
        t = self._tasks.pop(cat_id, None)
        if t and not t.done():
            t.cancel()

    async def start(self, cat_id: int, owner_id: int) -> Tuple[bool, str]:
        if self.is_running(cat_id):
            return False, "Messaging already running."

        all_msgs = self.db.msg_list(cat_id)
        accs     = self.db.acc_active(cat_id)
        grps     = [g for g in self.db.grp_all(cat_id)
                    if g["joined"] and g["chat_id"]]

        if not all_msgs: return False, "No messages set. Add messages first."
        if not accs:     return False, "No active accounts."
        if not grps:     return False, "No joined groups to message."

        self._stats[cat_id] = {"sent": 0, "errors": 0, "loops": 0, "_running": True}
        t = asyncio.create_task(
            self._run(cat_id, owner_id, accs, grps, all_msgs)
        )
        self._tasks[cat_id] = t
        return True, f"🚀 Messaging started! {len(accs)} accounts → {len(grps)} groups."

    async def _run(self, cat_id, owner_id, accs, grps, all_msgs):
        cat      = self.db.cat_get(cat_id)
        gc_delay = cat["gc_delay"]   if cat else 3
        rest     = cat["rest_delay"] if cat else 180
        welcome  = cat["welcome"]    if cat else ""
        s        = self._stats[cat_id]
        fsubs    = self.db.fsub_list(cat_id)

        # ── Build per-account message list ────────────────────────
        # If assignments exist, each account uses only its assigned msgs.
        # If no assignments at all, every account gets all messages.
        has_assignments = self.db.msgacc_has_any(cat_id)

        def _msgs_for_acc(acc) -> list:
            if not has_assignments:
                return list(all_msgs)
            assigned = self.db.msgacc_for_account(acc["id"])
            return list(assigned) if assigned else list(all_msgs)

        acc_msgs = {acc["id"]: _msgs_for_acc(acc) for acc in accs}

        # ── Launch one coroutine per account (TRUE PARALLEL) ──────
        workers = [
            self._acc_worker(
                cat_id, owner_id, acc,
                list(grps), acc_msgs[acc["id"]],
                gc_delay, rest, welcome, fsubs, s
            )
            for acc in accs
        ]

        try:
            await asyncio.gather(*workers, return_exceptions=False)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"[Msg] gather error cat {cat_id}: {e}")
        finally:
            s["_running"] = False
            self._tasks.pop(cat_id, None)

    async def _acc_worker(self, cat_id, owner_id, acc,
                          grps, msgs, gc_delay, rest, welcome, fsubs, s):
        """
        One coroutine per account. Runs independently in parallel.
        Each account loops: send its assigned messages to all groups, then rest.
        """
        acc_id = acc["id"]
        phone  = acc["phone"]
        msg_idx = 0   # cycles through assigned messages in order

        # Connect and join force-subs first
        client = await self.pool.get(acc)
        if not client:
            log.warning(f"[Msg] {phone}: can't connect, skipping.")
            return

        if fsubs:
            await join_force_subs(client, fsubs, phone)
            await asyncio.sleep(random.uniform(3, 8))

        while s.get("_running", False) and self.is_running(cat_id):
            # Reconnect if dropped
            if not getattr(client, "is_connected", False):
                client = await self.pool.get(acc)
                if not client:
                    await asyncio.sleep(30)
                    continue

            # Pick the next message for this account (cycle in order)
            if not msgs:
                await asyncio.sleep(30)
                continue

            msg_text = msgs[msg_idx % len(msgs)]["text"]
            msg_idx += 1

            # Send to all groups this account is responsible for
            for grp in grps:
                if not s.get("_running", False) or not self.is_running(cat_id):
                    return

                # Inline join: if still needed for any reason
                try:
                    # Send welcome on first contact if set (best-effort)
                    pass  # welcome handled during group joining
                    await client.send_message(grp["chat_id"], msg_text)
                    s["sent"] += 1
                    log.info(f"[Msg] {phone} → {grp['chat_id']} ✅")

                except tg_errors.FloodWait as e:
                    wait = e.value + 30
                    log.warning(f"[Msg] {phone}: FloodWait {e.value}s")
                    try:
                        await asyncio.sleep(wait)
                    except asyncio.CancelledError:
                        return
                    continue

                except tg_errors.ChatWriteForbidden:
                    # Try joining force-sub channels and retry once
                    if fsubs:
                        await join_force_subs(client, fsubs, phone)
                        await asyncio.sleep(5)
                        try:
                            await client.send_message(grp["chat_id"], msg_text)
                            s["sent"] += 1
                            continue
                        except Exception:
                            pass
                    s["errors"] += 1

                except tg_errors.UserBannedInChannel:
                    s["errors"] += 1
                    log.warning(f"[Msg] {phone}: banned in {grp['chat_id']}")

                except Exception as e:
                    es = str(e).upper()
                    if any(k in es for k in DEAD_ERRORS):
                        self.db.acc_set_status(acc_id, "frozen")
                        await self.notify(owner_id,
                            f"⚠️ <b>Account Frozen During Messaging</b>\n"
                            f"📱 <code>{phone}</code>"
                        )
                        return
                    # Auto-detect force-sub channel from error
                    detected_ch = _extract_channel_from_error(str(e))
                    if detected_ch:
                        joined_ok = await try_join_channel(client, detected_ch)
                        if joined_ok:
                            await asyncio.sleep(5)
                            try:
                                await client.send_message(grp["chat_id"], msg_text)
                                s["sent"] += 1
                                continue
                            except Exception:
                                pass
                    s["errors"] += 1

                try:
                    await asyncio.sleep(gc_delay + random.uniform(0, 2))
                except asyncio.CancelledError:
                    return

            # Loop done — rest before next loop
            s["loops"] += 1
            log.info(f"[Msg] {phone} loop {s['loops']} done, resting {rest}s")
            try:
                await asyncio.sleep(rest)
            except asyncio.CancelledError:
                return


# ══════════════════════════════════════════════════════════════════
# 8. HELPERS
# ══════════════════════════════════════════════════════════════════

def parse_links(text: str) -> List[str]:
    links = []
    for ln in text.strip().splitlines():
        ln = ln.strip()
        if not ln: continue
        if "t.me/" in ln:
            if not ln.startswith("http"):
                ln = "https://" + ln
            links.append(ln)
        elif ln.startswith("@") and len(ln) > 2:
            links.append(ln)
        elif re.match(r"^[a-zA-Z0-9_]{4,32}$", ln):
            links.append(f"@{ln}")
    return list(dict.fromkeys(links))


def kb(*rows):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t, callback_data=d) for t, d in row]
        for row in rows
    ])


async def edit(msg: Message, text: str, markup=None):
    try:
        await msg.edit_text(text, reply_markup=markup,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)
    except Exception:
        try:
            await msg.reply_text(text, reply_markup=markup,
                                 parse_mode=ParseMode.HTML,
                                 disable_web_page_preview=True)
        except Exception: pass


async def reply(msg: Message, text: str, markup=None):
    await msg.reply_text(text, reply_markup=markup,
                         parse_mode=ParseMode.HTML,
                         disable_web_page_preview=True)


# ══════════════════════════════════════════════════════════════════
# 9. UI SCREENS
# ══════════════════════════════════════════════════════════════════

class UI:

    @staticmethod
    def home(cats: list) -> Tuple[str, InlineKeyboardMarkup]:
        text = (
            "🐺 <b>BlackWolf Bot</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Select a category to manage:"
        )
        rows = [[( f"📁  {cat['name']}", f"cat:{cat['id']}")] for cat in cats]
        rows.append([("➕  New Category", "cat:new"),
                     ("🗑  Delete Category", "cat:del_pick")])
        rows.append([("👑  Manage Admins", "adm:panel")])
        return text, kb(*rows)

    @staticmethod
    def dashboard(cat, acc_counts: dict, grp_counts: dict,
                  join_running: bool, msg_running: bool) -> Tuple[str, InlineKeyboardMarkup]:
        active  = acc_counts.get("active", 0)
        frozen  = acc_counts.get("frozen", 0)
        js      = "▶️ Running" if join_running else "⏸ Idle"
        ms      = "▶️ Running" if msg_running  else "⏸ Idle"
        text = (
            f"📁 <b>Category: {cat['name']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>⚙️ Configuration</b>\n"
            f"⏱ GC Delay      : <code>{cat['gc_delay']}s</code>\n"
            f"😴 Rest After    : <code>{cat['rest_delay']}s</code>\n"
            f"👋 Welcome Msg   : {'✅ Set' if cat['welcome'] else '❌ Not set'}\n\n"
            f"<b>📊 Stats</b>\n"
            f"👥 Accounts  : <code>{active}</code> active"
            + (f" | <code>{frozen}</code> frozen" if frozen else "") + "\n"
            f"🌐 Groups    : <code>{grp_counts['joined']}</code>/{grp_counts['total']} joined\n\n"
            f"<b>🔄 Status</b>\n"
            f"🔗 Join      : {js}\n"
            f"💬 Messaging : {ms}"
        )
        cid = cat["id"]
        markup = kb(
            [("👥 Manage Accounts",  f"acc:list:{cid}"),
             ("💬 Manage Messages",  f"msg:list:{cid}")],
            [("👋 Set Welcome",      f"cat:welcome:{cid}"),
             ("⏱ Manage Timer",     f"cat:timer:{cid}")],
            [("🔗 Join Groups",      f"join:menu:{cid}"),
             ("🔄 Inline Join",      f"fsub:menu:{cid}")],
            [("🚀 Start Messaging",  f"msg:start:{cid}"),
             ("⏹ Stop Messaging",   f"msg:stop:{cid}")],
            [("▶️ Start Joining",    f"join:start:{cid}"),
             ("⏹ Stop Joining",     f"join:stop:{cid}")],
            [("🔙 Back",            "home"),
             ("🔴 Kill All",         f"kill:{cid}")],
        )
        return text, markup

    @staticmethod
    def acc_list(cat_id: int, accs: list) -> Tuple[str, InlineKeyboardMarkup]:
        lines = ["👥 <b>Accounts</b>\n━━━━━━━━━━━━━━━━━━━━\n"]
        for a in accs:
            icon = "✅" if a["status"] == "active" else ("❄️" if a["status"] == "frozen" else "❌")
            lines.append(f"{icon} <code>{a['phone']}</code> — {a['status']}")
        if not accs:
            lines.append("No accounts yet.")
        rows = [[(f"🗑 {a['phone']}", f"acc:del:{cat_id}:{a['id']}")] for a in accs]
        rows.append([("📤 Upload Session", f"acc:upload:{cat_id}"),
                     ("📱 Login via OTP",  f"acc:otp:{cat_id}")])
        rows.append([("🔙 Back", f"cat:{cat_id}")])
        return "\n".join(lines), kb(*rows)

    @staticmethod
    def join_menu(cat_id: int, grp_counts: dict,
                  running: bool, stats: dict) -> Tuple[str, InlineKeyboardMarkup]:
        if running:
            total = stats["total"]
            done  = stats["joined"] + stats["failed"]
            pct   = int(done / max(total, 1) * 100)
            bar   = ("█" * (pct // 10) + "░" * (10 - pct // 10)) if total > 0 else "░" * 10
            failures = stats.get("failures", [])
            fp = ""
            if failures:
                fp = "\n\n<b>Recent Failures:</b>\n"
                for f in failures[-5:]:
                    short  = f["link"].split("/")[-1] or f["link"]
                    reason = f["reason"][:55]
                    fp += f"• <code>{short}</code>\n  <i>{reason}</i>\n"
            text = (
                f"🔗 <b>Group Joining — RUNNING</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"[{bar}] {pct}%\n\n"
                f"✅ Joined : <code>{stats['joined']}</code>\n"
                f"❌ Failed : <code>{stats['failed']}</code>\n"
                f"📋 Total  : <code>{stats['total']}</code>\n"
                f"👥 Accs   : <code>{stats['active_accs']}</code>\n"
                f"🕐 Started: <code>{stats.get('started','?')}</code>"
                + fp
            )
            markup = kb(
                [("🔄 Refresh", f"join:menu:{cat_id}"),
                 ("⏹ Stop",     f"join:stop:{cat_id}")],
                [("🔙 Back",    f"cat:{cat_id}")]
            )
        else:
            text = (
                f"🔗 <b>Group Joining</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🌐 Total groups  : <code>{grp_counts['total']}</code>\n"
                f"✅ Already joined: <code>{grp_counts['joined']}</code>\n"
                f"⏳ Pending       : <code>{grp_counts['pending']}</code>\n\n"
                f"<b>Rate limit per account (auto):</b>\n"
                f"  5 joins → 5 min wait\n"
                f"  5 joins → 20 min wait\n"
                f"  (repeats — all accounts run in parallel)"
            )
            markup = kb(
                [("➕ Add Group Links",  f"join:add:{cat_id}")],
                [("🚀 Start Joining",    f"join:start:{cat_id}")],
                [("🗑 Clear All Groups", f"join:clear:{cat_id}")],
                [("🔙 Back",            f"cat:{cat_id}")]
            )
        return text, markup

    @staticmethod
    def msg_list(cat_id: int, msgs: list,
                 has_assignments: bool) -> Tuple[str, InlineKeyboardMarkup]:
        lines = ["💬 <b>Messages</b>\n━━━━━━━━━━━━━━━━━━━━\n"]
        for i, m in enumerate(msgs, 1):
            preview = m["text"][:60].replace("\n", " ")
            lines.append(f"{i}. {preview}{'…' if len(m['text']) > 60 else ''}")
        if not msgs:
            lines.append("No messages yet.")

        assignment_note = (
            "\n\n✅ <b>Account assignments active.</b>\n"
            "<i>Each account sends only its assigned messages.</i>"
            if has_assignments else
            "\n\n<i>No assignments — all accounts send random messages.</i>"
        )
        lines.append(assignment_note)

        rows = []
        for m in msgs:
            preview = m["text"][:25]
            rows.append([
                (f"🗑 Delete: {preview}…", f"msg:del:{cat_id}:{m['id']}"),
                (f"👥 Assign Accounts",    f"msg:assign:{cat_id}:{m['id']}"),
            ])
        rows.append([("➕ Add Message", f"msg:add:{cat_id}")])
        rows.append([("🔙 Back",        f"cat:{cat_id}")])
        return "\n".join(lines), kb(*rows)

    @staticmethod
    def msg_assign(cat_id: int, msg_id: int, msg_preview: str,
                   accs: list, assigned_ids: list) -> Tuple[str, InlineKeyboardMarkup]:
        """
        Screen to assign/unassign accounts to a message.
        Green checkbox = assigned, red X = not assigned.
        """
        lines = [
            f"👥 <b>Assign Accounts to Message</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Message: <i>{msg_preview[:60]}</i>\n\n"
            "Tap an account to toggle assignment.\n"
            "✅ = this account will send this message\n"
            "❌ = not assigned\n"
        ]
        rows = []
        for acc in accs:
            is_assigned = acc["id"] in assigned_ids
            icon = "✅" if is_assigned else "❌"
            rows.append([(
                f"{icon} {acc['phone']}",
                f"msg:tog:{cat_id}:{msg_id}:{acc['id']}"
            )])
        rows.append([
            ("✅ Assign All",   f"msg:assignall:{cat_id}:{msg_id}"),
            ("❌ Clear All",    f"msg:clearall:{cat_id}:{msg_id}"),
        ])
        rows.append([("🔙 Back", f"msg:list:{cat_id}")])
        return "\n".join(lines), kb(*rows)

    @staticmethod
    def fsub_menu(cat_id: int, fsubs: list) -> Tuple[str, InlineKeyboardMarkup]:
        lines = [
            "🔄 <b>Inline Join / Force-Sub Channels</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>How it works:</b>\n"
            "• Before joining groups, ALL accounts automatically join these channels first.\n"
            "• During messaging, if an account gets blocked (ChatWriteForbidden), it re-joins these channels.\n"
            "• If a group join fails with a channel requirement in the error, the bot auto-detects and joins it.\n\n"
            "<b>Configured channels:</b>\n"
        ]
        if fsubs:
            for f in fsubs:
                lines.append(f"• <code>{f['link']}</code>")
        else:
            lines.append("None configured.")
        rows = [[(f"🗑 {f['link']}", f"fsub:del:{cat_id}:{f['id']}")] for f in fsubs]
        rows.append([("➕ Add Channel", f"fsub:add:{cat_id}")])
        rows.append([("🔙 Back",        f"cat:{cat_id}")])
        return "\n".join(lines), kb(*rows)

    @staticmethod
    def admin_panel(admins: list, is_true_owner: bool) -> Tuple[str, InlineKeyboardMarkup]:
        lines = [
            "👑 <b>Admin Management</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Permissions:</b>\n"
            "• <b>Owner</b>  — full access + manage admins\n"
            "• <b>Admin</b>  — full bot access, cannot manage admins\n\n"
            "<b>Current Admins:</b>\n"
        ]
        rows = []
        if admins:
            for a in admins:
                name     = a["name"] or "Unknown"
                uname    = f"@{a['username']}" if a["username"] else f"id:{a['user_id']}"
                added_at = (a["added_at"] or "")[:10]
                lines.append(f"• <b>{name}</b> ({uname})\n  Added: {added_at}")
                if is_true_owner:
                    rows.append([(
                        f"🗑 Remove {name} ({uname})",
                        f"adm:rm:{a['user_id']}"
                    )])
        else:
            lines.append("<i>No admins added yet.</i>")
        if is_true_owner:
            rows.append([("➕ Add Admin", "adm:add")])
        rows.append([("🔙 Back", "home")])
        return "\n".join(lines), kb(*rows)


# ══════════════════════════════════════════════════════════════════
# 10. BOT
# ══════════════════════════════════════════════════════════════════

class BlackWolfBot:
    def __init__(self):
        self.db   = DB()
        self.pool = Pool()
        self.app  = Client(
            name="blackwolf_main",
            api_id=CF.API_ID,
            api_hash=CF.API_HASH,
            bot_token=CF.BOT_TOKEN,
            in_memory=True,
        )
        self.states: Dict[int, dict]       = {}
        self.otp_clients: Dict[int, dict]  = {}

        async def _notify(uid: int, text: str):
            try:
                await self.app.send_message(uid, text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
            except Exception: pass
            try:
                await self.app.send_message(CF.LOGS,
                    f"<code>[uid {uid}]</code>\n{text}",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
            except Exception: pass

        self.notify = _notify
        self.joiner = JoinEngine(self.db, self.pool, _notify)
        self.msger  = MsgEngine(self.db,  self.pool, _notify)
        self._register()

    def _owner(self, uid: int) -> bool:
        """Returns True if user is owner OR admin — allowed to use the bot."""
        return CF.is_owner(uid) or self.db.admin_exists(uid)

    def _is_true_owner(self, uid: int) -> bool:
        """Returns True only for hardcoded owners (can add/remove admins)."""
        return CF.is_owner(uid)

    async def _log(self, text: str):
        try:
            await self.app.send_message(CF.LOGS, text,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception: pass

    def _set_state(self, uid: int, state: str, **data):
        self.states[uid] = {"state": state, **data}

    def _clear_state(self, uid: int):
        self.states.pop(uid, None)

    # ══════════════════════════════════════════════════════════════
    # REGISTER HANDLERS
    # ══════════════════════════════════════════════════════════════

    def _register(self):
        app = self.app

        @app.on_message(filters.command("start") & filters.private)
        async def cmd_start(_, m: Message):
            uid = m.from_user.id
            if not self._owner(uid):
                return await m.reply_text("⛔ Unauthorised.")
            self._clear_state(uid)
            # Admins see categories they own; owners see all their own
            cats = self.db.cat_list(uid)
            # If admin has no cats of their own, show a helpful message
            if not cats and not self._is_true_owner(uid):
                return await reply(m,
                    "👋 <b>Welcome, Admin!</b>\n\n"
                    "You have bot access. Create your first category to start:",
                    kb([("➕ New Category", "cat:new"),
                        ("👑 Admin Panel",  "adm:panel")]))
            text, markup = UI.home(cats)
            await reply(m, text, markup)

        @app.on_message(filters.private & filters.text & ~filters.command(["start"]))
        async def on_text(_, m: Message):
            uid = m.from_user.id
            if not self._owner(uid): return
            st = self.states.get(uid, {})
            if not st: return
            # Only true owners can be in adm_add state
            if st.get("state") == "adm_add" and not self._is_true_owner(uid):
                self._clear_state(uid)
                return
            await self._handle_state(m, uid, st)

        @app.on_message(filters.private & filters.forwarded)
        async def on_forward(_, m: Message):
            uid = m.from_user.id
            if not self._is_true_owner(uid): return
            st = self.states.get(uid, {})
            if st.get("state") != "adm_add": return
            # Extract user_id from forwarded message
            fwd = m.forward_from
            if not fwd:
                return await reply(m,
                    "❌ Cannot read user ID from this forward.\n"
                    "The user may have privacy settings on.\n"
                    "Try sending their user ID directly: <code>123456789</code>",
                    kb([("❌ Cancel", "adm:panel")]))
            target_id = fwd.id
            uname     = fwd.username or ""
            name      = f"{fwd.first_name or ''} {fwd.last_name or ''}".strip()
            await self._do_add_admin(m, uid, target_id, uname, name)

        @app.on_message(filters.private & filters.document)
        async def on_doc(_, m: Message):
            uid = m.from_user.id
            if not self._owner(uid): return
            st    = self.states.get(uid, {})
            state = st.get("state", "")
            if state == "upload_session":
                await self._process_session_file(m, uid, st)
            elif not state:
                fname = (m.document.file_name or "").lower()
                if any(fname.endswith(x) for x in (".session", ".txt", ".zip")):
                    await m.reply_text(
                        "📤 <b>Session file detected!</b>\n\n"
                        "Go to: <b>Category → Manage Accounts → Upload Session</b>",
                        parse_mode=ParseMode.HTML)

        @app.on_callback_query()
        async def on_cb(_, q: CallbackQuery):
            uid  = q.from_user.id
            if not self._owner(uid):
                return await q.answer("⛔ Unauthorised", show_alert=True)
            # Admins (non-owners) cannot access the admin management panel actions
            data = q.data or ""
            if not self._is_true_owner(uid) and data in ("adm:panel", "adm:add") or \
               (not self._is_true_owner(uid) and data.startswith("adm:rm:")):
                return await q.answer(
                    "⛔ Only Owners can manage admins.", show_alert=True)
            await self._handle_cb(q, uid, data)

    # ══════════════════════════════════════════════════════════════
    # CALLBACK DISPATCHER
    # ══════════════════════════════════════════════════════════════

    async def _handle_cb(self, q: CallbackQuery, uid: int, data: str):
        msg = q.message

        if data == "home":
            cats = self.db.cat_list(uid)
            text, markup = UI.home(cats)
            return await edit(msg, text, markup)

        # ── cat:<id> ──────────────────────────────────────────────
        if re.match(r"^cat:\d+$", data):
            return await self._show_dashboard(msg, uid, int(data.split(":")[1]))

        if data == "cat:new":
            self._set_state(uid, "new_cat")
            return await edit(msg,
                "📁 <b>New Category</b>\n\nSend the category name:",
                kb([("❌ Cancel", "home")]))

        if data == "cat:del_pick":
            cats = self.db.cat_list(uid)
            if not cats:
                return await q.answer("No categories.", show_alert=True)
            rows = [[(f"🗑 {c['name']}", f"cat:del:{c['id']}")] for c in cats]
            rows.append([("🔙 Back", "home")])
            return await edit(msg, "🗑 <b>Delete which category?</b>", kb(*rows))

        if re.match(r"^cat:del:\d+$", data):
            cat_id = int(data.split(":")[2])
            cat    = self.db.cat_get(cat_id)
            if not cat: return await q.answer("Not found.", show_alert=True)
            self.db.cat_delete(cat_id)
            await q.answer("🗑 Deleted!", show_alert=False)
            cats = self.db.cat_list(uid)
            return await edit(msg, *UI.home(cats))

        if re.match(r"^cat:timer:\d+$", data):
            cat_id = int(data.split(":")[2])
            self._set_state(uid, "set_timer", cat_id=cat_id)
            return await edit(msg,
                "⏱ <b>Set Timers</b>\n\n"
                "Send two numbers:\n"
                "<code>GC_DELAY REST_DELAY</code>\n\n"
                "Example: <code>3 180</code>",
                kb([("❌ Cancel", f"cat:{cat_id}")]))

        if re.match(r"^cat:welcome:\d+$", data):
            cat_id = int(data.split(":")[2])
            self._set_state(uid, "set_welcome", cat_id=cat_id)
            return await edit(msg,
                "👋 <b>Set Welcome Message</b>\n\n"
                "Send welcome text. Send <code>clear</code> to remove.",
                kb([("❌ Cancel", f"cat:{cat_id}")]))

        # ── acc:list / upload / otp / del ─────────────────────────
        if re.match(r"^acc:list:\d+$", data):
            cat_id = int(data.split(":")[2])
            accs   = self.db.acc_list(cat_id)
            return await edit(msg, *UI.acc_list(cat_id, accs))

        if re.match(r"^acc:upload:\d+$", data):
            cat_id = int(data.split(":")[2])
            self._set_state(uid, "upload_session", cat_id=cat_id)
            return await edit(msg,
                "📤 <b>Upload Session</b>\n\n"
                "Send Pyrogram StringSession as text,\n"
                "or send a <code>.session</code> file.",
                kb([("❌ Cancel", f"acc:list:{cat_id}")]))

        if re.match(r"^acc:otp:\d+$", data):
            cat_id = int(data.split(":")[2])
            self._set_state(uid, "otp_phone", cat_id=cat_id)
            return await edit(msg,
                "📱 <b>Login via OTP</b>\n\n"
                "Send phone number with country code:\n"
                "<code>+91xxxxxxxxxx</code>",
                kb([("❌ Cancel", f"acc:list:{cat_id}")]))

        if re.match(r"^acc:del:\d+:\d+$", data):
            _, _, cat_id, acc_id = data.split(":")
            cat_id, acc_id = int(cat_id), int(acc_id)
            self.db.acc_delete(acc_id)
            await self.pool.stop(acc_id)
            await q.answer("🗑 Removed.", show_alert=False)
            return await edit(msg, *UI.acc_list(cat_id, self.db.acc_list(cat_id)))

        # ── msg:list ──────────────────────────────────────────────
        if re.match(r"^msg:list:\d+$", data):
            cat_id = int(data.split(":")[2])
            msgs   = self.db.msg_list(cat_id)
            has_a  = self.db.msgacc_has_any(cat_id)
            return await edit(msg, *UI.msg_list(cat_id, msgs, has_a))

        if re.match(r"^msg:add:\d+$", data):
            cat_id = int(data.split(":")[2])
            self._set_state(uid, "add_msg", cat_id=cat_id)
            return await edit(msg,
                "💬 <b>Add Message</b>\n\nSend the message text to broadcast:",
                kb([("❌ Cancel", f"msg:list:{cat_id}")]))

        if re.match(r"^msg:del:\d+:\d+$", data):
            _, _, cat_id, msg_id = data.split(":")
            cat_id, msg_id = int(cat_id), int(msg_id)
            self.db.msg_delete(msg_id)
            await q.answer("🗑 Deleted.", show_alert=False)
            msgs  = self.db.msg_list(cat_id)
            has_a = self.db.msgacc_has_any(cat_id)
            return await edit(msg, *UI.msg_list(cat_id, msgs, has_a))

        # ── msg:assign — show assignment screen ───────────────────
        if re.match(r"^msg:assign:\d+:\d+$", data):
            _, _, cat_id, msg_id = data.split(":")
            cat_id, msg_id = int(cat_id), int(msg_id)
            accs        = self.db.acc_list(cat_id)
            assigned    = self.db.msgacc_assigned_accs(msg_id)
            # Get message preview
            msgs        = self.db.msg_list(cat_id)
            preview     = next((m["text"] for m in msgs if m["id"] == msg_id), "?")
            return await edit(msg, *UI.msg_assign(cat_id, msg_id, preview, accs, assigned))

        # ── msg:tog — toggle one account assignment ───────────────
        if re.match(r"^msg:tog:\d+:\d+:\d+$", data):
            parts = data.split(":")
            cat_id, msg_id, acc_id = int(parts[2]), int(parts[3]), int(parts[4])
            now_assigned = self.db.msgacc_toggle(msg_id, acc_id)
            await q.answer(
                f"{'✅ Assigned' if now_assigned else '❌ Unassigned'}",
                show_alert=False)
            accs     = self.db.acc_list(cat_id)
            assigned = self.db.msgacc_assigned_accs(msg_id)
            msgs     = self.db.msg_list(cat_id)
            preview  = next((m["text"] for m in msgs if m["id"] == msg_id), "?")
            return await edit(msg, *UI.msg_assign(cat_id, msg_id, preview, accs, assigned))

        # ── msg:assignall — assign all accounts to this message ───
        if re.match(r"^msg:assignall:\d+:\d+$", data):
            _, _, cat_id, msg_id = data.split(":")
            cat_id, msg_id = int(cat_id), int(msg_id)
            accs = self.db.acc_list(cat_id)
            for acc in accs:
                self.db.msgacc_assign(msg_id, acc["id"])
            await q.answer("✅ All accounts assigned.", show_alert=False)
            assigned = self.db.msgacc_assigned_accs(msg_id)
            msgs     = self.db.msg_list(cat_id)
            preview  = next((m["text"] for m in msgs if m["id"] == msg_id), "?")
            return await edit(msg, *UI.msg_assign(cat_id, msg_id, preview, accs, assigned))

        # ── msg:clearall — remove all assignments from message ────
        if re.match(r"^msg:clearall:\d+:\d+$", data):
            _, _, cat_id, msg_id = data.split(":")
            cat_id, msg_id = int(cat_id), int(msg_id)
            accs = self.db.acc_list(cat_id)
            for acc in accs:
                self.db.msgacc_unassign(msg_id, acc["id"])
            await q.answer("❌ All assignments cleared.", show_alert=False)
            assigned = self.db.msgacc_assigned_accs(msg_id)
            msgs     = self.db.msg_list(cat_id)
            preview  = next((m["text"] for m in msgs if m["id"] == msg_id), "?")
            return await edit(msg, *UI.msg_assign(cat_id, msg_id, preview, accs, assigned))

        # ── msg:start / stop ──────────────────────────────────────
        if re.match(r"^msg:start:\d+$", data):
            cat_id      = int(data.split(":")[2])
            ok, reason  = await self.msger.start(cat_id, uid)
            await q.answer(("✅ " if ok else "❌ ") + reason, show_alert=True)
            return await self._show_dashboard(msg, uid, cat_id)

        if re.match(r"^msg:stop:\d+$", data):
            cat_id = int(data.split(":")[2])
            self.msger.stop(cat_id)
            await q.answer("⏹ Messaging stopped.", show_alert=False)
            return await self._show_dashboard(msg, uid, cat_id)

        # ── join:menu / add / start / stop / clear ────────────────
        if re.match(r"^join:menu:\d+$", data):
            cat_id  = int(data.split(":")[2])
            running = self.joiner.is_running(cat_id)
            stats   = self.joiner.get_stats(cat_id)
            counts  = self.db.grp_count(cat_id)
            return await edit(msg, *UI.join_menu(cat_id, counts, running, stats))

        if re.match(r"^join:add:\d+$", data):
            cat_id = int(data.split(":")[2])
            self._set_state(uid, "add_groups", cat_id=cat_id)
            return await edit(msg,
                "🔗 <b>Add Group Links</b>\n\n"
                "Send all links — one per line.\n\n"
                "<b>Supported:</b>\n"
                "• <code>https://t.me/username</code>\n"
                "• <code>https://t.me/+inviteHash</code>\n"
                "• <code>@username</code>",
                kb([("❌ Cancel", f"join:menu:{cat_id}")]))

        if re.match(r"^join:start:\d+$", data):
            cat_id     = int(data.split(":")[2])
            ok, reason = await self.joiner.start(cat_id, uid)
            await q.answer(("✅ " if ok else "❌ ") + reason, show_alert=True)
            running = self.joiner.is_running(cat_id)
            stats   = self.joiner.get_stats(cat_id)
            counts  = self.db.grp_count(cat_id)
            return await edit(msg, *UI.join_menu(cat_id, counts, running, stats))

        if re.match(r"^join:stop:\d+$", data):
            cat_id = int(data.split(":")[2])
            self.joiner.stop(cat_id)
            await q.answer("⏹ Joining stopped.", show_alert=False)
            return await self._show_dashboard(msg, uid, cat_id)

        if re.match(r"^join:clear:\d+$", data):
            cat_id = int(data.split(":")[2])
            self.db.grp_delete_all(cat_id)
            await q.answer("🗑 All groups cleared.", show_alert=True)
            counts = self.db.grp_count(cat_id)
            return await edit(msg, *UI.join_menu(cat_id, counts, False, {}))

        # ── fsub:menu / add / del ─────────────────────────────────
        if re.match(r"^fsub:menu:\d+$", data):
            cat_id = int(data.split(":")[2])
            fsubs  = self.db.fsub_list(cat_id)
            return await edit(msg, *UI.fsub_menu(cat_id, fsubs))

        if re.match(r"^fsub:add:\d+$", data):
            cat_id = int(data.split(":")[2])
            self._set_state(uid, "add_fsub", cat_id=cat_id)
            return await edit(msg,
                "🔄 <b>Add Force-Sub Channel</b>\n\n"
                "Send channel username or link:",
                kb([("❌ Cancel", f"fsub:menu:{cat_id}")]))

        if re.match(r"^fsub:del:\d+:\d+$", data):
            _, _, cat_id, fid = data.split(":")
            cat_id, fid = int(cat_id), int(fid)
            self.db.fsub_delete(fid)
            await q.answer("🗑 Removed.", show_alert=False)
            fsubs = self.db.fsub_list(cat_id)
            return await edit(msg, *UI.fsub_menu(cat_id, fsubs))

        # ── kill ──────────────────────────────────────────────────
        if re.match(r"^kill:\d+$", data):
            cat_id = int(data.split(":")[1])
            self.joiner.stop(cat_id)
            self.msger.stop(cat_id)
            await q.answer("🔴 All tasks killed.", show_alert=True)
            return await self._show_dashboard(msg, uid, cat_id)

        # ── adm:panel — show admin list ───────────────────────────
        if data == "adm:panel":
            admins = self.db.admin_list()
            is_to  = self._is_true_owner(uid)
            return await edit(msg, *UI.admin_panel(admins, is_to))

        # ── adm:add — owner adds a new admin ─────────────────────
        if data == "adm:add":
            if not self._is_true_owner(uid):
                return await q.answer("⛔ Only owners can add admins.", show_alert=True)
            self._set_state(uid, "adm_add")
            return await edit(msg,
                "👑 <b>Add Admin</b>\n\n"
                "Forward a message from the user you want to add as admin,\n"
                "OR send their Telegram user ID:\n\n"
                "<code>123456789</code>",
                kb([("❌ Cancel", "adm:panel")]))

        # ── adm:rm:<user_id> — owner removes admin ────────────────
        if re.match(r"^adm:rm:\d+$", data):
            if not self._is_true_owner(uid):
                return await q.answer("⛔ Only owners can remove admins.", show_alert=True)
            target_id = int(data.split(":")[2])
            removed   = self.db.admin_remove(target_id)
            if removed:
                await q.answer("🗑 Admin removed.", show_alert=False)
                try:
                    await self.app.send_message(
                        target_id,
                        "ℹ️ Your admin access to <b>BlackWolf Bot</b> has been revoked.",
                        parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                await self._log(f"👑 Admin removed: <code>{target_id}</code> by <code>{uid}</code>")
            else:
                await q.answer("❌ Admin not found.", show_alert=True)
            admins = self.db.admin_list()
            return await edit(msg, *UI.admin_panel(admins, True))

        await q.answer("❓ Unknown action.", show_alert=True)

    # ══════════════════════════════════════════════════════════════
    # STATE MACHINE
    # ══════════════════════════════════════════════════════════════

    async def _handle_state(self, m: Message, uid: int, st: dict):
        state  = st["state"]
        cat_id = st.get("cat_id")
        text   = m.text.strip()

        if state == "new_cat":
            if not text:
                return await reply(m, "❌ Name cannot be empty.")
            cid = self.db.cat_create(uid, text)
            self._clear_state(uid)
            cats = self.db.cat_list(uid)
            t, markup = UI.home(cats)
            await reply(m, f"✅ Category <b>{text}</b> created! (ID {cid})", markup)

        elif state == "upload_session":
            await self._process_session_str(m, uid, cat_id, text)

        elif state == "add_groups":
            links = parse_links(text)
            if not links:
                return await reply(m, "❌ No valid links found. Try again.")
            added = sum(1 for l in links if self.db.grp_add(cat_id, l))
            self._clear_state(uid)
            counts = self.db.grp_count(cat_id)
            await reply(m,
                f"✅ <b>{added}</b> groups added "
                f"({len(links)-added} duplicates skipped)\n"
                f"📊 Total: <code>{counts['total']}</code>",
                kb(
                    [("🚀 Start Joining", f"join:start:{cat_id}")],
                    [("🔙 Back",          f"join:menu:{cat_id}")]
                ))

        elif state == "add_msg":
            self.db.msg_add(cat_id, text)
            self._clear_state(uid)
            msgs  = self.db.msg_list(cat_id)
            has_a = self.db.msgacc_has_any(cat_id)
            t, markup = UI.msg_list(cat_id, msgs, has_a)
            await reply(m, f"✅ Message added!\n\n" + t, markup)

        elif state == "set_timer":
            parts = text.split()
            if len(parts) < 2 or not all(p.isdigit() for p in parts[:2]):
                return await reply(m, "❌ Send two numbers, e.g. <code>3 180</code>")
            gc, rest = int(parts[0]), int(parts[1])
            self.db.cat_update(cat_id, gc_delay=gc, rest_delay=rest)
            self._clear_state(uid)
            await reply(m,
                f"✅ Timers updated!\n"
                f"⏱ GC Delay: <code>{gc}s</code>\n"
                f"😴 Rest: <code>{rest}s</code>",
                kb([("🔙 Back", f"cat:{cat_id}")]))

        elif state == "set_welcome":
            if text.lower() == "clear":
                self.db.cat_update(cat_id, welcome="")
                self._clear_state(uid)
                return await reply(m, "✅ Welcome message cleared.",
                                   kb([("🔙 Back", f"cat:{cat_id}")]))
            self.db.cat_update(cat_id, welcome=text)
            self._clear_state(uid)
            await reply(m, "✅ Welcome message saved.",
                        kb([("🔙 Back", f"cat:{cat_id}")]))

        elif state == "add_fsub":
            links = parse_links(text) or [text]
            added = sum(1 for l in links if self.db.fsub_add(cat_id, l))
            self._clear_state(uid)
            fsubs = self.db.fsub_list(cat_id)
            t, markup = UI.fsub_menu(cat_id, fsubs)
            await reply(m, f"✅ {added} channel(s) added.\n\n" + t, markup)

        elif state == "otp_phone":
            phone = text.strip()
            if not re.match(r"^\+?\d{7,15}$", phone):
                return await reply(m, "❌ Invalid phone. Include country code: <code>+91xxxxxxxxxx</code>")
            if not phone.startswith("+"):
                phone = "+" + phone
            wait_msg = await reply(m, f"📤 Sending OTP to <code>{phone}</code>…")
            ok, cl, result = await self.pool.otp_send_code(phone)
            try: await wait_msg.delete()
            except Exception: pass
            if not ok:
                return await reply(m, f"❌ <b>Failed to send OTP</b>\n<code>{result}</code>",
                                   kb([("🔙 Back", f"acc:list:{cat_id}")]))
            self.otp_clients[uid] = {
                "client": cl, "phone": phone, "hash": result, "cat_id": cat_id
            }
            self._set_state(uid, "otp_code", cat_id=cat_id)
            await reply(m,
                f"✅ OTP sent to <code>{phone}</code>\n\n"
                f"📩 Enter the OTP code:",
                kb([("❌ Cancel", f"acc:list:{cat_id}")]))

        elif state == "otp_code":
            code = text.strip().replace(" ", "").replace("-", "")
            otp  = self.otp_clients.get(uid)
            if not otp:
                self._clear_state(uid)
                return await reply(m, "❌ Session expired. Start again.",
                                   kb([("🔙 Back", f"acc:list:{cat_id}")]))
            wait_msg = await reply(m, "⏳ Verifying OTP…")
            ok, session, name, needs_2fa = await self.pool.otp_sign_in(
                otp["client"], otp["phone"], otp["hash"], code)
            try: await wait_msg.delete()
            except Exception: pass
            if needs_2fa:
                self._set_state(uid, "otp_2fa", cat_id=cat_id)
                return await reply(m,
                    "🔐 <b>2FA Enabled</b>\n\nSend your cloud password:",
                    kb([("❌ Cancel", f"acc:list:{cat_id}")]))
            if not ok:
                self.otp_clients.pop(uid, None)
                self._clear_state(uid)
                return await reply(m, f"❌ <b>Wrong OTP</b>\n<code>{name}</code>",
                                   kb([("📱 Try Again", f"acc:otp:{cat_id}"),
                                       ("🔙 Back",      f"acc:list:{cat_id}")]))
            self.otp_clients.pop(uid, None)
            self._clear_state(uid)
            self.db.acc_add(cat_id, otp["phone"], session)
            await self._log(f"📱 OTP login\n👤 {name} | 📱 {otp['phone']}")
            accs = self.db.acc_list(cat_id)
            t, markup = UI.acc_list(cat_id, accs)
            await reply(m,
                f"✅ <b>Account Added!</b>\n"
                f"👤 {name}\n📱 <code>{otp['phone']}</code>\n\n" + t, markup)

        elif state == "otp_2fa":
            password = text.strip()
            otp      = self.otp_clients.get(uid)
            if not otp:
                self._clear_state(uid)
                return await reply(m, "❌ Session expired. Start again.",
                                   kb([("🔙 Back", f"acc:list:{cat_id}")]))
            wait_msg = await reply(m, "⏳ Checking 2FA…")
            ok, session, result = await self.pool.otp_check_password(otp["client"], password)
            try: await wait_msg.delete()
            except Exception: pass
            if not ok:
                return await reply(m, f"❌ <b>Wrong password</b>\n<code>{result}</code>",
                                   kb([("❌ Cancel", f"acc:list:{cat_id}")]))
            self.otp_clients.pop(uid, None)
            self._clear_state(uid)
            self.db.acc_add(cat_id, otp["phone"], session)
            accs = self.db.acc_list(cat_id)
            t, markup = UI.acc_list(cat_id, accs)
            await reply(m,
                f"✅ <b>Account Added (2FA)!</b>\n📱 <code>{otp['phone']}</code>\n\n" + t,
                markup)

        elif state == "adm_add":
            # User typed a numeric user ID directly
            raw = text.strip()
            if not raw.isdigit():
                return await reply(m,
                    "❌ Please send a numeric user ID, e.g. <code>123456789</code>\n"
                    "Or forward a message from that user.",
                    kb([("❌ Cancel", "adm:panel")]))
            target_id = int(raw)
            await self._do_add_admin(m, uid, target_id, "", "")

    # ══════════════════════════════════════════════════════════════
    # SESSION UPLOAD
    # ══════════════════════════════════════════════════════════════

    async def _process_session_str(self, m: Message, uid: int, cat_id: int, session_str: str):
        wait_msg = await reply(m, "⏳ Validating session…")
        ok, phone, name = await self.pool.validate_session(session_str)
        try: await wait_msg.delete()
        except Exception: pass
        if not ok:
            return await reply(m, f"❌ <b>Invalid session!</b>\n<code>{phone or name}</code>",
                               kb([("🔙 Back", f"acc:list:{cat_id}")]))
        self.db.acc_add(cat_id, phone, session_str)
        self._clear_state(uid)
        await self._log(f"📤 Session added\n👤 {name} | 📱 {phone}")
        accs = self.db.acc_list(cat_id)
        t, markup = UI.acc_list(cat_id, accs)
        await reply(m,
            f"✅ <b>Session added!</b>\n👤 {name}\n📱 <code>{phone}</code>\n\n" + t, markup)

    async def _process_session_file(self, m: Message, uid: int, st: dict):
        cat_id = st.get("cat_id")
        path   = None
        try:
            path     = await m.download()
            sessions = await self._extract_sessions(path)
            if not sessions:
                return await reply(m,
                    "❌ No valid sessions found.\n\n"
                    "Supported: Pyrogram StringSession text, ZIP, Telethon .session",
                    kb([("🔙 Back", f"acc:list:{cat_id}")]))
            if len(sessions) == 1:
                await self._process_session_str(m, uid, cat_id, sessions[0])
            else:
                added = failed = 0
                for s in sessions:
                    ok, phone, name = await self.pool.validate_session(s)
                    if ok:
                        self.db.acc_add(cat_id, phone, s); added += 1
                    else:
                        failed += 1
                self._clear_state(uid)
                accs = self.db.acc_list(cat_id)
                t, markup = UI.acc_list(cat_id, accs)
                await reply(m,
                    f"✅ <b>Bulk Import Done!</b>\n"
                    f"✅ Added: <code>{added}</code>\n"
                    f"❌ Failed: <code>{failed}</code>\n\n" + t, markup)
        except Exception as e:
            await reply(m, f"❌ File error:\n<code>{e}</code>",
                        kb([("📱 Login via OTP", f"acc:otp:{cat_id}"),
                            ("🔙 Back",          f"acc:list:{cat_id}")]))
        finally:
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass

    async def _extract_sessions(self, path: str) -> list:
        import zipfile, tempfile
        sessions = []
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as z:
                for name in z.namelist():
                    if name.endswith("/"): continue
                    with z.open(name) as f: raw = f.read()
                    s = await self._parse_raw_session(name, raw)
                    if s: sessions.append(s)
            return sessions
        with open(path, "rb") as f:
            raw = f.read()
        s = await self._parse_raw_session(os.path.basename(path).lower(), raw)
        if s: sessions.append(s)
        return sessions

    async def _parse_raw_session(self, filename: str, raw: bytes) -> Optional[str]:
        import tempfile, base64
        try:
            text = raw.decode("utf-8").strip()
            if len(text) > 100 and "\n" not in text[:50]:
                return text
        except UnicodeDecodeError:
            pass
        try:
            import sqlite3 as _sq3
            tmp = tempfile.mktemp(suffix=".session")
            with open(tmp, "wb") as f: f.write(raw)
            conn = _sq3.connect(tmp)
            conn.row_factory = _sq3.Row
            cur  = conn.cursor()
            cur.execute("SELECT * FROM sessions LIMIT 1")
            row  = cur.fetchone()
            if not row:
                conn.close(); os.remove(tmp); return None
            dc_id    = row["dc_id"]
            auth_key = row["auth_key"]
            conn.close(); os.remove(tmp)
            if not auth_key: return None
            version   = b"\x01"
            dc_bytes  = dc_id.to_bytes(4, "big")
            auth_bytes = bytes.fromhex(auth_key) if isinstance(auth_key, str) else bytes(auth_key)
            auth_bytes = (auth_bytes + b"\x00" * 256)[:256]
            packed     = version + dc_bytes + auth_bytes
            return base64.urlsafe_b64encode(packed).decode()
        except Exception as e:
            log.warning(f"[Session] parse {filename}: {e}")
        return None

    # ══════════════════════════════════════════════════════════════
    # ADMIN HELPER
    # ══════════════════════════════════════════════════════════════

    async def _do_add_admin(self, m: Message, adder_id: int,
                             target_id: int, uname: str, name: str):
        """Shared logic for adding admin via typed ID or forwarded message."""
        self._clear_state(adder_id)

        # Cannot add an owner as admin (they already have full access)
        if CF.is_owner(target_id):
            return await reply(m,
                "ℹ️ That user is already an <b>Owner</b> — no need to add as admin.",
                kb([("🔙 Back", "adm:panel")]))

        # If name/uname not known, try to fetch from Telegram
        if not name:
            try:
                user  = await self.app.get_users(target_id)
                name  = f"{user.first_name or ''} {user.last_name or ''}".strip()
                uname = user.username or ""
            except Exception:
                name  = "Unknown"
                uname = ""

        ok = self.db.admin_add(target_id, uname, name, adder_id)
        if not ok:
            return await reply(m,
                f"ℹ️ <code>{target_id}</code> is already an admin.",
                kb([("🔙 Back", "adm:panel")]))

        # Notify new admin
        try:
            await self.app.send_message(
                target_id,
                "🎉 <b>You have been added as an Admin of BlackWolf Bot!</b>\n\n"
                "You now have full access to all bot features.\n"
                "Send /start to begin.",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass

        await self._log(
            f"👑 <b>Admin added</b>\n"
            f"👤 {name} (@{uname} | <code>{target_id}</code>)\n"
            f"Added by: <code>{adder_id}</code>"
        )
        admins = self.db.admin_list()
        disp   = f"@{uname}" if uname else f"id:{target_id}"
        await reply(m,
            f"✅ <b>{name}</b> ({disp}) added as Admin!\n\n"
            f"They have been notified and can now use the bot.",
            (UI.admin_panel(admins, True))[1])

    # ══════════════════════════════════════════════════════════════
    # DASHBOARD HELPER
    # ══════════════════════════════════════════════════════════════

    async def _show_dashboard(self, msg: Message, uid: int, cat_id: int):
        cat = self.db.cat_get(cat_id)
        if not cat:
            return await edit(msg, "❌ Category not found.", kb([("🔙 Home", "home")]))
        acc_counts   = self.db.acc_count(cat_id)
        grp_counts   = self.db.grp_count(cat_id)
        join_running = self.joiner.is_running(cat_id)
        msg_running  = self.msger.is_running(cat_id)
        text, markup = UI.dashboard(cat, acc_counts, grp_counts, join_running, msg_running)
        await edit(msg, text, markup)

    # ══════════════════════════════════════════════════════════════
    # RUN
    # ══════════════════════════════════════════════════════════════

    def run(self):
        log.info("🐺 BlackWolf Bot v4.0 starting…")
        self.app.run()


if __name__ == "__main__":
    BlackWolfBot().run()
