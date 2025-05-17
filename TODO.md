

- "Reactive" Aspect:
As the README.md clearly states, the core "reactive query" vision (automatic UI updates on data change) is a future goal and not implemented. Currently, it functions as a server-side templating engine that queries a database on request.

I'm thinking of just rewriting rsql.py for this


Later:
- Code completion (language server) / VS code pluigin

- #each (or similar looping): Needed for iterating over data structures passed as parameters, not just database results from #from.
- #header, #cookie, #contenttype: Crucial for controlling HTTP responses (caching, sessions, API content types, etc.).

- View Definition (#view): While mentioned, it's unclear if #view is fully implemented for defining reusable SQL views within the templates.

- Parsing Robustness: The parse_simple function in pageql.py is very basic (simple regex split). It might struggle with nested tags, complex attribute quoting, or minor syntax variations, making templates potentially brittle.
- HTTP Server & Request Handling (pageql_server.py):
Limited Request Handling: Currently handles URL query parameters and basic application/x-www-form-urlencoded POST data. It lacks built-in support for other common needs like JSON payloads, multipart/form-data (file uploads), accessing request headers easily within templates, or differentiating easily between PUT, DELETE, etc.

No Middleware Concept: Frameworks often use middleware for handling tasks across many requests (e.g., authentication, logging, CORS).

Session Management: No built-in mechanism for user sessions, which usually relies on server-side storage and cookies (requires #cookie support).
Robustness & Security:
Error Handling: Error reporting is basic. More detailed error messages (including template file and line number) would significantly aid debugging. Production environments would need user-friendly error pages instead of showing raw exceptions.

Transaction Management: The README.md mentions atomic transactions per request, but the implementation relies on a single db.commit() at the end of render in the server. This might not cover all cases or provide fine-grained control if needed.

Examples: More examples covering different use cases beyond the TodoMVC.
Testing Support: No defined way to easily unit or integration test PageQL applications.
Debugging: Better debugging tools beyond #log and #dump would be helpful.
Packaging: Needs to be packaged (e.g., for PyPI) with clear dependencies for easy installation.


In essence, it's a neat proof-of-concept for embedding SQL in HTML but needs significant feature additions, robustness improvements, and developer tooling to be considered a generally useful micro-framework for broader adoption.
