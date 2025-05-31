"""
PageQL: A template language for embedding SQL inside HTML directly
"""

# Import the main classes from the PageQL modules
from .pageql import PageQL, RenderResult
from .reactive import ReadOnly
from .pageqlapp import PageQLApp
from .reactive_sql import parse_reactive
from .tokens import (
    generate_token,
    hash_token,
    create_tokens_table,
    store_token,
    get_and_delete_token,
)
from .sessions import (
    create_session,
    validate_session,
    extend_session,
    delete_session,
    invalidate_user_sessions,
)
# Define the version
__version__ = "0.1.0"

# Make these classes available directly from the package
__all__ = [
    "PageQL",
    "RenderResult",
    "ReadOnly",
    "PageQLApp",
    "parse_reactive",
    "generate_token",
    "hash_token",
    "create_tokens_table",
    "store_token",
    "get_and_delete_token",
    "create_session",
    "validate_session",
    "extend_session",
    "delete_session",
    "invalidate_user_sessions",
]
