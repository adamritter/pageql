import sys
from pathlib import Path
import types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

__doc__ = """
>>> from pageql.pageql import PageQL
>>> r = PageQL(":memory:")
>>> r.load_module("include_test", '''This is included
... {{#partial p}}
...   included partial {{z}}
... {{/partial}}
... ''')

>>> source_with_comment = '''
... {{#set :ww 3+3}}
... Start Text.
... {{!-- This is a comment --}}
... {{ :hello }}
... {{ :ww + 4 }}
... {{#partial public add}}
... hello {{ :addparam }}
... {{/partial}}
... {{#if 3+3 == :ww }}
... :)
... {{#if 3+3 == 7 }}
... :(
... {{/if}}
... {{/if}}
... {{#ifdef :hello}}
... Hello is defined!
... {{#else}}
... Nothing is defined!
... {{/ifdef}}
... {{#ifndef :hello}}
... Hello is not defined!
... {{#else}}
... Hello is defined :)
... {{/ifndef}}
... {{#ifdef :hello2}}
... Hello is defined!
... {{#else}}
... Hello2 isn't defined!
... {{/ifdef}}
... {{#ifdef :he.lo}}
... He.lo is defined: {{he.lo}}, in expression: {{:he.lo || ':)'}}
... {{#else}}
... He.lo isn't defined!
... {{/ifdef}}
... {{#set a.b he.lo}}
... {{#ifdef a.b}}
... a.b is defined
... {{/ifdef}}
... {{#create table if not exists todos (id primary key, text text, done boolean) }}
... {{#insert into todos (text) values ('hello sql')}}
... {{#insert into todos (text) values ('hello second row')}}
... {{count(*) from todos}}
... {{#from todos}}
... {{#from todos}} {{ text }} {{/from}}
... {{/from}}
... {{#delete from todos}}
... {{#from todos}}Bad Dobby{{/from}}
... {{#render add addparam='world'}}
... {{#if 2<1}}
... 2<1
... {{#elif 2<2}}
... 2<2
... {{#elif 2<3}}
... 2<3
... {{/if}}
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
... {{#partial public endpoint}}Default handler{{/partial}}
... {{#partial get endpoint}}GET handler{{/partial}}
... {{#partial post endpoint}}POST handler{{/partial}}
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
>>> r.load_module("a/b/d", "{{#partial public e}}abde{{/partial}}")
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
>>> r.load_module("a/b/e", "{{#partial public f/g}}abefg{{/partial}}{{#render f/g}}{{#render f/g}}")
>>> print(r.render("/a/b/e", partial="f/g").body)
abefg
>>> print(r.render("/a/b/e").body)
abefgabefg
>>> r.load_module("x", "{{#partial public :id/toggle}}toggled {{id}}{{/partial}}")
>>> print(r.render("/x", partial="5/toggle").body)
toggled 5
>>> r.load_module("xx", "{{#partial public :id}}now {{id}}{{/partial}}")
>>> print(r.render("/xx", partial="5").body)
now 5
>>> r.load_module("y", "{{#partial public :a/b/:c}}a is {{a}}, c is {{c}}{{/partial}}{{#render :a/b/:c}}")
>>> print(r.render("/y", params={'a': 5, 'c': 'cc'}).body)
a is 5, c is cc
>>> r.load_module("redirect", "{{#redirect '/redirected'}}")
>>> print(r.render("/redirect").status_code)
302
>>> r.load_module("optional", "{{#param text optional}}cool{{/param}}")
>>> print(r.render("/optional").body)
cool
>>> r.load_module("delete_test", "{{#partial delete :id}}deleted<{{id}}>{{/partial}}")
>>> print(r.render("/delete_test/1", http_verb="DELETE").body)
deleted<1>
>>> r.load_module("varnum", "{{#set idd0 3}}{{idd0}}")
>>> print(r.render("/varnum").body)
3
>>> r.load_module("fromtest", "{{#from (select 1 as id)}}<{{id}}>{{/from}}")
>>> print(r.render("/fromtest").body)
<1>
"""
