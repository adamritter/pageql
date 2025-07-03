<link rel="stylesheet" href="/pygments.css">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
   /* 7 lines, Better Motherf*** Website */
html{margin: auto;max-width:70ch;line-height:1.4;
background-color:rgb(19, 20, 23);
font-family:'Inter',sans-serif;
font-size:1.1em;color:#222;padding:0 10px}
body{color:rgb(231, 231, 231)}
h1,h2,h3{line-height:1.2; color:rgb(166, 88, 60)}
</style>
# I built a real‑time multi‑user web app in 100 lines
## - without React or JavaScript

The hardest problem in web development is the network latency between the user that decides on what action to take and the server that stores the database.

The database may be too big,
and / or it contains too sensitive data to be transferred to the users device, or quite often users communicate with eachother, which means that network communication can't be skipped.

Modern web frameworks are trying to solve two problems at once:

  - responding to the user's action in real time, even optimistically until the frontend gets feedback from the server
  - updating the UI as fast and with as little bandwidth and code as possible to respond to changes in the database

Popular frontend frameworks like React / Svelte / Vue are great at solving the first problem: they create an in memory representation of the data on the client side
that is needed to render the UI, by updating a small part of it the frameworks reactively and efficiently update the UI. Before frontend frameworks became popular, pages in the web 1.0 era were quite boring and slow, as they refreshed the whole web page in every request - with some exceptions using XMLHTTPRequest.

Unfortunatly this magical developer experience at the start of the development cycle when working with these frontend frameworks give a false sense of fast development that breaks down when the developer wants to extend this
reactive experience to the backend when access to a part of the big data and reactive updates from other data sources / users are needed. Some real-world examples of this are:

  - A banking application can show a negative balance on a debit account temporarily because it updates spending money at a shop just after somebody sent money to spend.
  - Github may show that a test is running, so the user needs to try to refresh the page.
  - ChatGPT may not update threads that were created on another device, or stops showing data on transient connection loss with the server
  - While buying a ticket on a website the user needs to go through an 8 page form just to find out at the end that the tickt's price has changed and has to restart the whole process.

While optimistic UIs are great to experience, and I'm not arguing against it
(and I would do everything to keep it working),
in my opinion in most cases it's not worth more than the update consistency
from the backend and the developer experience that comes with this guaranteed
consistency.

When the user is required to refresh the website, it can lead to a more frustrating
experience than going back to web 1.0 when the user exactly knows how fresh is
the data.

The frontend frameworks can use JSON RPCs to get new data periodically, but it means that the data synchronization is not automatic, and the frontend developer has to maintain a client state and server state, and the server also has to know when to refresh which UI and what data to send to which server.

On the client a React.js app has to be extended like this if it chooses socket.io and full refresh:

```javascript

  /* ---------------- helpers ---------------- */
  const fetchTodos = useCallback(async () => {
    const r = await fetch('/api/todos')
    const data = await r.json()
    setTodos(data.todos as Todo[])
  }, [])

  /* ---------------- socket + first load ---------------- */
  useEffect(() => {
    fetchTodos()                    // initial
    fetch('/api/socket')            // boot socket endpoint (cold-start safe)
    const socket = io()
    socket.on('todosUpdated', fetchTodos)
    return () => socket.disconnect()
  }, [fetchTodos])

  /* ---------------- CRUD ---------------- */
  const createTodo = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newTitle.trim()) return
    await fetch('/api/todos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'create', title: newTitle.trim() })
    })
    setNewTitle('')
  }
  ... for each event
```

the server, after modifying the database, needs to know what update method to call, and not forget it:

```javascript
    io?.emit('todosUpdated')          // 🔔 broadcast change
```

Another option is to do fine grained database change, which makes even more work for the developer, but it makes much more sense to just send 1 line change when 1 row was changed in the database.

A much better general solution is database change broadcasting for custom queries
and using that as the main source of data.

Here's an example for how it is achieved using Supabase:

```javascript
  const fetchTodos = useCallback(async () => {
    const { data, error } = await supabase
      .from("todos")
      .select("*")
      .order("inserted_at", { ascending: true });
    if (!error) setTodos(data);
  }, []);

  // Subscribe to realtime changes
  useEffect(() => {
    fetchTodos();

    const channel = supabase
      .channel("public:todos")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "todos" },
        (payload) => {
          setTodos((current) => {
            switch (payload.eventType) {
              case "INSERT":
                return [...current, payload.new];
              case "UPDATE":
                return current.map((t) =>
                  t.id === payload.new.id ? payload.new : t
                );
              case "DELETE":
                return current.filter((t) => t.id !== payload.old.id);
              default:
                return current;
            }
          });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchTodos]);
```

Although it's much nicer, as the only logic of converting the collection to an array is in one place, this is again something that developers shouldn't be worried about in a well designed framework. Also Supabase is mostly a payed external service as it's harder to setup / manage than just a simple SQLite db, and costs can go up very easily, unlike with a Hetzner payed machine instance.

Still, even with the example the whole todos table is synced, and when many people's data
is getting in that database, and they start sharing socially with eachother, a filtering needs
to be set and it gets very tricky: listening for joins are not supported in supabase, so
for example listening to all todos that the user has access to can't be done without first
having another query that reads the groups.

Another tricky multi-user question is to see 
the name of the user who is assigned a TODO to, if the todos table only contains a user_id.
In this case whenever a new TODO is inserted and an insert event comes from supabase, a new
query needs to be created by the client which can slow down the server serving lots of point
queries from lots of users at the same time (n+1 problem).  For changes it needs to be cached
as the user_id may not change when a TODO is updated (but a user name change without user_id change should change what's shown). Of course projects/labels/timers can come into the picture to complicate things even more.

This looks like a complicated made up scenario, but the point is that it's just impossible to think about all the
possible effects of changes as a developer, and, while it's far from trivial, it's worthwhile to use a web framework that completely automates this problem for all queries.

The only technology that provides live queries for joins as well, not just table subscriptions with filters, are
GraphQL web service and 




- finish this essay
- it should show the main ways to implement reactive sql with their pros and cos:
  - graphql: specify both sql and other dependencies on the client side: works great for facebook,
    but makes the client side complex, no easy way to handle conditionals / reactive data fetching for example
    which is much easier on server side.

  - electricsql: sync all data to frontend. Amazing for offline first apps, but terrible for normal
    web sites with larger databases for the first sync (especially when that data is wiped out by
    web browsers periodically). Also with its current HTTP based sync solution real-time chat is not advised.
     
- server side reactive sql, keeping a minimal client state on server side, but must be done smartly:
  for example joins shouldn't be stored on server side. If a table changes, another should be looked up
  in the same 

This is a good start:

```
{% from todos %}
{{text}}
{% end from %}
```

Explain that this is already reactive, but only HTML travels through the wire. If todos are inserted/deleted/updated,
the a row will be inserted/updated/deleted and just the changed HTML sent through a websocket.

To show this add this code:
      <input name="text" placeholder="What needs to be done?" maxlength="100" autofocus autocomplete="off"
        hx-post="/todos/add" hx-trigger="keyup[key=='Enter']" hx-on:htmx:after-on-load="this.value=''">

{% 
  partial post add;
  insert into todos(text) values (:text)
%}

