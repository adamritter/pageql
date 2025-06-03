"""
PageQL: A template language for embedding SQL inside HTML directly
"""

# Import the main classes from the PageQL modules
from .pageql import PageQL
from .render_context import RenderResult
from .reactive import ReadOnly
from .pageqlapp import PageQLApp
from .reactive_sql import parse_reactive
from .jws_utils import jws_serialize_compact, jws_deserialize_compact
# Define the version
__version__ = "0.1.0"

# Make these classes available directly from the package
__all__ = [
    "PageQL",
    "RenderResult",
    "ReadOnly",
    "PageQLApp",
    "parse_reactive",
    "jws_serialize_compact",
    "jws_deserialize_compact",
]
