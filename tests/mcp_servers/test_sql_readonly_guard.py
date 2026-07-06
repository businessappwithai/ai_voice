import pytest

from tests.mcp_servers._loader import load_server_module

guard_module = load_server_module("sql-readonly", "guard.py")
UnsafeQuery = guard_module.UnsafeQuery
validate_select_only = guard_module.validate_select_only


def test_plain_select_passes() -> None:
    validate_select_only("SELECT * FROM patients")  # no raise


def test_select_with_where_clause_passes() -> None:
    validate_select_only("SELECT name, dob FROM patients WHERE clinic_id = :clinic_id")


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM patients",
        "UPDATE patients SET name = 'x'",
        "DROP TABLE patients",
        "INSERT INTO patients (name) VALUES ('x')",
        "TRUNCATE patients",
        "ALTER TABLE patients ADD COLUMN x TEXT",
        "GRANT ALL ON patients TO public",
    ],
)
def test_non_select_statements_are_rejected(statement: str) -> None:
    with pytest.raises(UnsafeQuery):
        validate_select_only(statement)


def test_stacked_query_is_rejected() -> None:
    with pytest.raises(UnsafeQuery):
        validate_select_only("SELECT * FROM patients; DROP TABLE patients;")


def test_stacked_query_hidden_after_select_is_rejected() -> None:
    with pytest.raises(UnsafeQuery):
        validate_select_only("SELECT 1; DELETE FROM patients WHERE 1=1;")


def test_disallowed_keyword_inside_a_string_literal_does_not_false_positive() -> None:
    # The literal text "DROP TABLE" appears only inside a quoted string
    # (e.g. matching a column value), not as an actual SQL keyword —
    # sqlparse's token typing must distinguish this from a real DROP.
    validate_select_only("SELECT * FROM patients WHERE notes = 'DROP TABLE'")  # no raise


def test_trailing_semicolon_and_whitespace_is_tolerated() -> None:
    validate_select_only("SELECT * FROM patients;  ")


def test_leading_comment_is_tolerated() -> None:
    validate_select_only("-- fetch patients\nSELECT * FROM patients")


def test_cte_with_select_only_passes() -> None:
    validate_select_only("WITH recent AS (SELECT * FROM patients) SELECT * FROM recent")


def test_data_modifying_cte_is_rejected() -> None:
    with pytest.raises(UnsafeQuery):
        validate_select_only("WITH x AS (DELETE FROM patients RETURNING *) SELECT * FROM x")
