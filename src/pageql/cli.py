#!/usr/bin/env python3
"""
PageQL command-line interface
"""

import argparse
import asyncio
import os
import sys
import uvicorn

from .pageqlapp import PageQLApp

def main():
    """Entry point for the pageql command-line tool."""
    parser = argparse.ArgumentParser(description="Run the PageQL development server.")
    
    # Add positional arguments - these will be the primary way to use the command
    parser.add_argument('db_file', help="Path to the SQLite database file")
    parser.add_argument('templates_dir', help="Path to the directory containing .pageql template and static files")
    parser.add_argument('--port', type=int, default=8000, help="Port number to run the server on.")
    parser.add_argument('--create', action='store_true', help="Create the database file if it doesn't exist.")
    parser.add_argument('--no-reload', action='store_true', help="Do not reload and refresh the templates on file changes.")

    # If no arguments were provided (only the script name), print help and exit.
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    
    app = PageQLApp(args.db_file, args.templates_dir, create_db=args.create, should_reload=not args.no_reload)

    print(f"\nPageQL server running on http://localhost:{args.port}")
    print(f"Using database: {args.db_file}")
    print(f"Serving templates from: {args.templates_dir}")
    print("Press Ctrl+C to stop.")

    uvicorn.run(app, host="0.0.0.0", port=args.port)

if __name__ == "__main__":
    main() 