import sys
from pathlib import Path
import types
import pytest

# Originally disabled due to intermittent failures; reenable the doctest now

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

__doc__ = """
>>> from pageql.pageql import PageQL
>>> r = PageQL(":memory:")
>>> _render = r.render
>>> def render_nonreactive(*a, **k):
...     k.setdefault('reactive', False)
...     return _render(*a, **k)
>>> r.render = render_nonreactive
>>> r.load_module("include_test", '''This is included
... {{#partial p}}
...   included partial {{z}}
... {{#endpartial}}
... ''')

>>> source_with_comment = '''
... {{#let :ww = 3+3}}
... Start Text.
... {{!-- This is a comment --}}
... {{ :hello }}
... {{ :ww + 4 }}
... {{#partial public add}}
... hello {{ :addparam }}
... {{#endpartial}}
... {{#if 3+3 == :ww }}
... :)
... {{#if 3+3 == 7 }}
... :(
... {{#endif}}
... {{#endif}}
... {{#ifdef :hello}}
... Hello is defined!
... {{#else}}
... Nothing is defined!
... {{#endif}}
... {{#ifndef :hello}}
... Hello is not defined!
... {{#else}}
... Hello is defined :)
... {{#endif}}
... {{#ifdef :hello2}}
... Hello is defined!
... {{#else}}
... Hello2 isn't defined!
... {{#endif}}
... {{#ifdef :he.lo}}
... He.lo is defined: {{he.lo}}, in expression: {{:he.lo || ':)'}}
... {{#else}}
... He.lo isn't defined!
... {{#endif}}
... {{#let a.b = he.lo}}
... {{#ifdef a.b}}
... a.b is defined
... {{#endif}}
... {{#create table if not exists todos (id primary key, text text, done boolean) }}
... {{#insert into todos (text) values ('hello sql')}}
... {{#insert into todos (text) values ('hello second row')}}
... {{count(*) from todos}}
... {{#from todos}}
... {{#from todos}} {{ text }} {{#endfrom}}
... {{#endfrom}}
... {{#delete from todos}}
... {{#from todos}}Bad Dobby{{#endfrom}}
... {{#render add addparam='world'}}
... {{#if 2<1}}
... 2<1
... {{#elif 2<2}}
... 2<2
... {{#elif 2<3}}
... 2<3
... {{#endif}}
... {{'&amp;'}}
... {{{'&amp;'}}}
... {{#import include_test as it}}
... {{#render it}}
... {{#render it/p z=3}}
... End Text.
... '''
>>> r.load_module("comment_test", source_with_comment)
>>> result1 = r.render("/comment_test", {'hello': 'world', 'he': {'lo': 'wor'}})
>>> print(result1.status_code)
200
>>> print(result1.body.strip())
Start Text.
world
10
:)
Hello is defined!
Hello is defined :)
Hello2 isn't defined!
He.lo is defined: wor, in expression: wor:)
a.b is defined
2
hello sql
hello second row
hello sql
hello second row
hello world
2<3
&amp;amp;
&amp;
This is included
included partial 3
End Text.
>>> # Simulate GET /nonexistent
>>> print(r.render("/nonexistent").status_code)
404
>>> print(r.render("/comment_test", {'addparam': 'world'}, 'add').body)
hello world
>>> print(r.render("/comment_test/add", {'addparam': 'world'}).body)
hello world
>>> # Test HTTP verb-specific partials
>>> r.load_module("verbs", '''
... {{#partial public endpoint}}Default handler{{#endpartial}}
... {{#partial get endpoint}}GET handler{{#endpartial}}
... {{#partial post endpoint}}POST handler{{#endpartial}}
... ''')
>>> print(r.render("/verbs", partial="endpoint").body)
Default handler
>>> print(r.render("/verbs", partial="endpoint", http_verb="GET").body)
GET handler
>>> print(r.render("/verbs", partial="endpoint", http_verb="POST").body)
POST handler
>>> r.load_module("a/b/c", "hello")
>>> print(r.render("/a/b/c").body)
hello
>>> r.load_module("a/b/d", "{{#partial public e}}abde{{#endpartial}}")
>>> print(r.render("/a/b/d", partial="e").body)
abde
>>> print(r.render("/a/b/d", partial="e", http_verb="GET").body)
abde
>>> print(r.render("/a/b/d", partial="e", http_verb="POST").body)
abde
>>> print(r.render("/a/b/d/e").body)
abde
>>> print(r.render("/a/b/d/e", http_verb="POST").body)
abde
>>> r.load_module("a/b/e", "{{#partial public f/g}}abefg{{#endpartial}}{{#render f/g}}{{#render f/g}}")
>>> print(r.render("/a/b/e", partial="f/g").body)
abefg
>>> print(r.render("/a/b/e").body)
abefgabefg
>>> r.load_module("x", "{{#partial public :id/toggle}}toggled {{id}}{{#endpartial}}")
>>> print(r.render("/x", partial="5/toggle").body)
toggled 5
>>> r.load_module("xx", "{{#partial public :id}}now {{id}}{{#endpartial}}")
>>> print(r.render("/xx", partial="5").body)
now 5
>>> r.load_module("y", "{{#partial public :a/b/:c}}a is {{a}}, c is {{c}}{{#endpartial}}{{#render :a/b/:c}}")
>>> print(r.render("/y", params={'a': 5, 'c': 'cc'}).body)
a is 5, c is cc
>>> r.load_module("redirect", "{{#redirect '/redirected'}}")
>>> print(r.render("/redirect").status_code)
302
>>> r.load_module("optional", "{{#param text optional}}cool{{/param}}")
>>> print(r.render("/optional").body)
cool
>>> r.load_module("delete_test", "{{#partial delete :id}}deleted[{{id}}]{{#endpartial}}")
>>> print(r.render("/delete_test/1", http_verb="DELETE").body)
deleted[1]
>>> r.load_module("varnum", "{{#let idd0 = 3}}{{idd0}}")
>>> print(r.render("/varnum").body)
3
>>> r.load_module("fromtest", "{{#from (select 1 as id)}}[{{id}}]{{#endfrom}}")
>>> print(r.render("/fromtest").body)
[1]
"""
