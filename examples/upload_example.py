import pageql
import argparse
import uvicorn
import base64

parser = argparse.ArgumentParser(description="Run the file upload example")
parser.add_argument('--db', default='data.db')
parser.add_argument('--dir', default='templates')
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--port', type=int, default=8000)
parser.add_argument('--create', action='store_true')
parser.add_argument('--no-reload', action='store_true')
args = parser.parse_args()

app = pageql.PageQLApp(args.db, args.dir, create_db=args.create, should_reload=not args.no_reload)
app.conn.create_function('base64_encode', 1, lambda x: base64.b64encode(x).decode('utf-8'))

print(f"\nVisit file upload page at http://{args.host}:{args.port}/upload")
print(f"Using database: {args.db}")
print(f"Serving templates from: {args.dir}")
print("Press Ctrl+C to stop.")

uvicorn.run(app, host=args.host, port=args.port)
