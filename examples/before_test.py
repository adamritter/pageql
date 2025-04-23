import pageql
import argparse
import uvicorn
import sqlite3, base64


parser = argparse.ArgumentParser(description="Run the PageQL development server.")
parser.add_argument('--db', default='data.db', help="Path to the SQLite database file.")
parser.add_argument('--dir', default='templates', help="Path to the directory containing .pageql template files.")
parser.add_argument('--port', type=int, default=8000, help="Port number to run the server on.")
parser.add_argument('--create', action='store_true', help="Create the database file if it doesn't exist.")
parser.add_argument('--no-reload', action='store_true', help="Do not reload and refresh the templates on file changes.")

args = parser.parse_args()
app = pageql.PageQLApp(args.db, args.dir, create_db=args.create, should_reload=not args.no_reload)

app.conn.create_function('base64_encode', 1, lambda x: base64.b64encode(x).decode('utf-8'))

@app.before('/before')
async def get(params):
    print("params", params)
    params['title'] = 'horse'
    horse_jpg = open('horse.jpg', 'rb').read()
    params['image'] = horse_jpg
    return params

print(f"\nVisit before_test test page at http://localhost:{args.port}/before")
print(f"Using database: {args.db}")
print(f"Serving templates from: {args.dir}")
print("Press Ctrl+C to stop.")

uvicorn.run(app, host="0.0.0.0", port=args.port)