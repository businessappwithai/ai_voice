"""SQL safety guard for the read-only SQL MCP server (Phase 1 Epic
1.3). Uses sqlparse (MIT) to verify a submitted statement is a single
SELECT with no dangerous keywords, rather than a naive substring check
— this is the server-side half of the MCP threat model's "payload
injection" mitigation (see saap.core.mcp's docstring); the client-side
half is MCPClientPool's JSON-Schema re-validation before dispatch.

Checks operate on sqlparse's token *types*, not raw substrings, so a
disallowed keyword appearing inside a string literal (e.g. a WHERE
clause matching the literal text "DROP TABLE") does not false-positive
— only tokens sqlparse itself classifies as DML/DDL/Keyword count.
"""
from __future__ import annotations

import sqlparse
from sqlparse.tokens import CTE, DDL, DML, Keyword

DISALLOWED_KEYWORDS = frozenset(
    {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"}
)

# A statement may open with SELECT directly, or with WITH (a
# read-only CTE — "WITH x AS (SELECT ...) SELECT ... FROM x"). Either
# way, the keyword scan below still rejects any DML token other than
# SELECT appearing anywhere in the statement, which is what actually
# catches a data-modifying CTE arm like "WITH x AS (DELETE ... RETURNING *) ...".
_ALLOWED_FIRST_TOKENS = frozenset({(DML, "SELECT"), (CTE, "WITH")})


class UnsafeQuery(Exception):
    pass


def validate_select_only(sql: str) -> None:
    """Raises `UnsafeQuery` unless `sql` is exactly one read-only
    statement (SELECT, or WITH ... SELECT) with no disallowed keyword
    tokens anywhere in it."""
    statements = [s for s in sqlparse.parse(sql) if s.token_first(skip_cm=True) is not None]
    if len(statements) != 1:
        raise UnsafeQuery("exactly one SQL statement is allowed per call (no stacked queries)")

    statement = statements[0]
    first_token = statement.token_first(skip_cm=True)
    if first_token is None or (first_token.ttype, first_token.value.upper()) not in _ALLOWED_FIRST_TOKENS:
        raise UnsafeQuery("only SELECT (or WITH ... SELECT) statements are allowed")

    for token in statement.flatten():
        if token.ttype in (Keyword, DDL, DML) and token.value.upper() in DISALLOWED_KEYWORDS:
            raise UnsafeQuery(f"disallowed keyword detected: {token.value.upper()}")
