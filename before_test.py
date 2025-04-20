import pageql_server
import argparse
import uvicorn

parser = argparse.ArgumentParser(description="Run the PageQL development server.")
parser.add_argument('--db', required=True, help="Path to the SQLite database file.")
parser.add_argument('--dir', required=True, help="Path to the directory containing .pageql template files.")
parser.add_argument('--port', type=int, default=8000, help="Port number to run the server on.")
parser.add_argument('--create', action='store_true', help="Create the database file if it doesn't exist.")
parser.add_argument('--no-reload', action='store_true', help="Do not reload and refresh the templates on file changes.")

args = parser.parse_args()
app = pageql_server.PageQLApp(args.db, args.dir, create_db=args.create, should_reload=not args.no_reload)

@app.before('/todos2')
async def get(params):
    params['title'] = 'horse'

print(f"\nPageQL server running on http://localhost:{args.port}")
print(f"Using database: {args.db}")
print(f"Serving templates from: {args.dir}")
print("Press Ctrl+C to stop.")

uvicorn.run(app, host="0.0.0.0", port=args.port)