#!/usr/bin/env python3
"""
PageQL command-line interface
"""

import argparse
import os
import sys
import uvicorn

from .pageql import PageQL, RenderContext
from .pageqlapp import PageQLApp


def run_pageql_tests(templates_dir: str) -> bool:
    """Load ``.pageql`` files from *templates_dir* and run all ``#test`` blocks."""

    engine = PageQL(":memory:")

    for root, _dirs, files in os.walk(templates_dir):
        for name in files:
            if not name.endswith(".pageql"):
                continue
            file_path = os.path.join(root, name)
            module_name = os.path.splitext(os.path.relpath(file_path, templates_dir))[0]
            module_name = module_name.replace(os.sep, "/")
            with open(file_path, "r", encoding="utf-8") as f:
                engine.load_module(module_name, f.read())

    total = 0
    passed = 0

    for module, tests in engine.tests.items():
        for name, body in tests.items():
            total += 1
            ctx = RenderContext()
            try:
                engine.process_nodes(body, {}, module, {None: module}, None, False, ctx)
                engine.db.commit()
                print(f"PASS {module}:{name}")
                passed += 1
            except Exception as e:
                engine.db.rollback()
                print(f"FAIL {module}:{name} {e}")

    print(f"{passed}/{total} tests passed")
    return passed == total

def main():
    """Entry point for the pageql command-line tool."""
    parser = argparse.ArgumentParser(description="Run the PageQL development server.")

    # Add positional arguments - these will be the primary way to use the command
    parser.add_argument('templates_dir', help="Path to the directory containing .pageql template and static files")
    parser.add_argument('db_file', help="Path to the SQLite database file or a database URL")
    parser.add_argument('--host', default='127.0.0.1', help="Host interface to bind the server.")
    parser.add_argument('--port', type=int, default=8000, help="Port number to run the server on.")
    parser.add_argument('--create', action='store_true', help="Create the database file if it doesn't exist.")
    parser.add_argument('--no-reload', action='store_true', help="Do not reload and refresh the templates on file changes.")
    parser.add_argument('-q', '--quiet', action='store_true', help="Only show errors in output.")
    parser.add_argument('--fallback-url', help="Forward unknown routes to this base URL")
    parser.add_argument('--no-csrf', action='store_true', help="Disable CSRF protection")
    parser.add_argument('--test', action='store_true', help="Run tests instead of serving")
    parser.add_argument(
        '--profile',
        action='store_true',
        help='Profile the server and display stats when it stops.',
    )
    parser.add_argument(
        '--http-disconnect-cleanup-timeout',
        type=float,
        default=10.0,
        metavar='SECONDS',
        help='Delay before cleaning up HTTP disconnects.',
    )
    parser.add_argument('--log-level', default='info', help="Log level")

    # If no arguments were provided (only the script name), print help and exit.
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    if args.test:
        success = run_pageql_tests(args.templates_dir)
        sys.exit(0 if success else 1)

    if args.db_file is None or args.templates_dir is None:
        parser.error("db_file and templates_dir are required")

    if args.quiet:
        args.log_level = "error"

    kwargs = {
        "create_db": args.create,
        "should_reload": not args.no_reload,
        "quiet": args.quiet,
        "fallback_url": args.fallback_url,
        "csrf_protect": not args.no_csrf,
        "http_disconnect_cleanup_timeout": args.http_disconnect_cleanup_timeout,
    }
    app = PageQLApp(args.db_file, args.templates_dir, **kwargs)
    app.log_level = args.log_level

    if not args.quiet:
        print(f"\nPageQL server running on http://{args.host}:{args.port}")
        print(f"Using database: {args.db_file}")
        print(f"Serving templates from: {args.templates_dir}")
        print("Press Ctrl+C to stop.")

    if args.profile:
        import cProfile
        import pstats

        profiler = cProfile.Profile()
        try:
            profiler.runcall(
                uvicorn.run,
                app,
                host=args.host,
                port=args.port,
                log_level=args.log_level,
            )
        finally:
            pstats.Stats(profiler).sort_stats("cumulative").print_stats(20)
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)

if __name__ == "__main__":
    main() 
