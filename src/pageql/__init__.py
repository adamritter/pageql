"""
PageQL: A template language for embedding SQL inside HTML directly
"""

# Import the main classes from the PageQL modules
from .pageql import PageQL, RenderResult
from .reactive import ReadOnly
from .pageqlapp import PageQLApp
from .reactive_sql import parse_reactive
# Define the version
__version__ = "0.1.0"

# Make these classes available directly from the package
__all__ = [
    "PageQL",
    "RenderResult",
    "ReadOnly",
    "PageQLApp",
    "parse_reactive",
]
