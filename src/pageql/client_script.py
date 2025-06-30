_CLIENT_SCRIPT_TEMPLATE = """<!doctype html>
<script src="/htmx.js"></script>
<script>
  htmx.config.defaultSwapStyle = 'none';
  window.pageqlMarkers={};
  function getBodyTextContent(){return document.body?document.body.textContent:'';}
  function pstart(i){var s=document.currentScript,c=document.createComment('pageql-start:'+i);var p=s.parentNode;if(p&&p.tagName==='HEAD'&&document.body){p.removeChild(s);document.body.appendChild(c);}else{s.replaceWith(c);}var a=window.pageqlMarkers[i];if(!a)a=window.pageqlMarkers[i]=[];a.push(c);if(document.currentScript)document.currentScript.remove();}
  function pend(i){var s=document.currentScript,c=document.createComment('pageql-end:'+i);var p=s.parentNode;if(p&&p.tagName==='HEAD'&&document.body){p.removeChild(s);document.body.appendChild(c);}else{s.replaceWith(c);}var a=window.pageqlMarkers[i];if(!a)a=window.pageqlMarkers[i]=[];var m=a[a.length-1];if(m)m.e=c;else{a.push({e:c});}if(document.currentScript)document.currentScript.remove();}
  function pprevioustag(i){var s=document.currentScript,p=s.parentNode,t=s.previousElementSibling;if(p&&p.tagName==='HEAD'&&document.body){p.removeChild(s);t=null;p=document.body;}else{s.remove();}window.pageqlMarkers[i]=t||p;if(document.currentScript)document.currentScript.remove();}
  function pset(i,v){var a=window.pageqlMarkers[i];if(!a||!a.length)return;var s=a[a.length-1],e=s.e,r=document.createRange();r.setStartAfter(s);r.setEndBefore(e);r.deleteContents();var t=document.createElement('template');t.innerHTML=v;var c=t.content;var sc=c.querySelectorAll('script');e.parentNode.insertBefore(c,e);for(var j=0;j<sc.length;j++){var os=sc[j];var ns=document.createElement('script');for(var k=0;k<os.attributes.length;k++){var at=os.attributes[k];ns.setAttribute(at.name,at.value);}ns.text=os.textContent;os.parentNode.replaceChild(ns,os);}if(window.htmx){var x=s.nextSibling;while(x&&x!==e){var nx=x.nextSibling;if(x.nodeType===1)htmx.process(x);x=nx;}}if(document.currentScript)document.currentScript.remove();}
  function pdelete(i){var a=window.pageqlMarkers[i];if(!a||!a.length){if(document.currentScript)document.currentScript.remove();return;}var m=a.pop(),e=m.e,r=document.createRange();r.setStartBefore(m);r.setEndAfter(e);r.deleteContents();if(!a.length)delete window.pageqlMarkers[i];if(document.currentScript)document.currentScript.remove();}
  function pupdate(o,n,v){var ao=window.pageqlMarkers[o];if(!ao||!ao.length){if(document.currentScript)document.currentScript.remove();return;}var m=ao.pop(),e=m.e;m.textContent='pageql-start:'+n;e.textContent='pageql-end:'+n;var an=window.pageqlMarkers[n];if(!an)an=window.pageqlMarkers[n]=[];an.push(m);pset(n,v);if(window.htmx){var x=m.nextSibling;while(x&&x!==e){var nx=x.nextSibling;if(x.nodeType===1)htmx.process(x);x=nx;}}if(document.currentScript)document.currentScript.remove();}
  function pinsert(i,v){var a=window.pageqlMarkers[i];if(!a)a=window.pageqlMarkers[i]=[];var mid=i.split('_')[0];var ca=window.pageqlMarkers[mid];if(!ca||!ca.length){if(document.currentScript)document.currentScript.remove();return;}var c=ca[ca.length-1];var m=document.createComment('pageql-start:'+i);var e=document.createComment('pageql-end:'+i);m.e=e;a.push(m);c.e.parentNode.insertBefore(m,c.e);var t=document.createElement('template');t.innerHTML=v;c.e.parentNode.insertBefore(t.content,c.e);c.e.parentNode.insertBefore(e,c.e);if(window.htmx){var x=m.nextSibling;while(x&&x!==e){var nx=x.nextSibling;if(x.nodeType===1)htmx.process(x);x=nx;}}if(document.currentScript)document.currentScript.remove();}
  function pupdatetag(i,c){var t=window.pageqlMarkers[i];var d=document.createElement('template');d.innerHTML=c;var n=d.content.firstChild;if(!n)return;for(var j=t.attributes.length-1;j>=0;j--){var a=t.attributes[j].name;if(!n.hasAttribute(a))t.removeAttribute(a);}for(var j=0;j<n.attributes.length;j++){var at=n.attributes[j];t.setAttribute(at.name,at.value);}if(document.currentScript)document.currentScript.remove();}
  function orderdelete(i,idx){var a=window.pageqlMarkers[i];if(!a){if(document.currentScript)document.currentScript.remove();return;}var m=a[idx];if(!m){if(document.currentScript)document.currentScript.remove();return;}a.splice(idx,1);var e=m.e,r=document.createRange();r.setStartBefore(m);r.setEndAfter(e);r.deleteContents();if(!a.length)delete window.pageqlMarkers[i];if(document.currentScript)document.currentScript.remove();}
  function orderinsert(i,idx,v){var a=window.pageqlMarkers[i];if(!a){if(document.currentScript)document.currentScript.remove();return;}if(idx>a.length)idx=a.length;var m=document.createComment('pageql-start');var e=document.createComment('pageql-end');m.e=e;a.splice(idx,0,m);var ref=a[idx+1];var p;if(ref){p=ref.parentNode;p.insertBefore(m,ref);var t=document.createElement('template');t.innerHTML=v;p.insertBefore(t.content,ref);p.insertBefore(e,ref);}else{var last=a[idx-1]||a[0];p=last.e?last.e.parentNode:last.parentNode;p.insertBefore(m,last.e||null);var t=document.createElement('template');t.innerHTML=v;p.insertBefore(t.content,last.e||null);p.insertBefore(e,last.e||null);}if(window.htmx){var x=m.nextSibling;while(x&&x!==e){var nx=x.nextSibling;if(x.nodeType===1)htmx.process(x);x=nx;}}if(document.currentScript)document.currentScript.remove();}
  function orderupdate(i,o,n,v){var a=window.pageqlMarkers[i];if(!a){if(document.currentScript)document.currentScript.remove();return;}var m=a[o];if(!m){if(document.currentScript)document.currentScript.remove();return;}var e=m.e;if(o!==n){a.splice(o,1);a.splice(n,0,m);var p=e.parentNode;var r=document.createRange();r.setStartBefore(m);r.setEndAfter(e);var f=r.extractContents();var t=a[n+1];if(t)t.parentNode.insertBefore(f,t);else p.appendChild(f);}var r=document.createRange();r.setStartAfter(m);r.setEndBefore(e);r.deleteContents();var d=document.createElement('template');d.innerHTML=v;var c=d.content;var sc=c.querySelectorAll('script');e.parentNode.insertBefore(c,e);for(var j=0;j<sc.length;j++){var os=sc[j];var ns=document.createElement('script');for(var k=0;k<os.attributes.length;k++){var at=os.attributes[k];ns.setAttribute(at.name,at.value);}ns.text=os.textContent;os.parentNode.replaceChild(ns,os);}if(window.htmx){var x=m.nextSibling;while(x&&x!==e){var nx=x.nextSibling;if(x.nodeType===1)htmx.process(x);x=nx;}}if(document.currentScript)document.currentScript.remove();}
  function maybe_load_more(el,mid){var can=true;function h(){if(!can)return;var sp=(el===window||el===document.body?window.scrollY+window.innerHeight:el.scrollTop+el.clientHeight);var sh=(el===window||el===document.body?document.documentElement.scrollHeight:el.scrollHeight)-1500;if(sp>=sh){var msg='infinite_load_more '+mid;if(window.pageqlSocket&&window.pageqlSocket.readyState===1)window.pageqlSocket.send(msg);else{if(!window.pageqlSendQueue)window.pageqlSendQueue=[];window.pageqlSendQueue.push(msg);}can=false;}};(el===window||el===document.body?window:el).addEventListener('scroll',h);}
  document.currentScript.remove()
</script>
<script>
  (function() {
    const host = window.location.hostname;
    const port = window.location.port;
    const clientId = "{client_id}";
    function setup() {
      document.body.addEventListener('htmx:configRequest', (evt) => {
        evt.detail.headers['ClientId'] = clientId;
      });
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws_url = `${proto}://${host}:${port}/reload-request-ws?clientId=${clientId}`;

      function forceReload() {
        const socket = new WebSocket(ws_url);
        socket.onopen = () => {
          window.location.reload();
        };
        socket.onerror = () => {
          setTimeout(forceReload, 100);
        };
      }

        const socket = new WebSocket(ws_url);
        window.pageqlSocket = socket;
        socket.onopen = () => {
          console.log("WebSocket opened with id", clientId);
          if(window.pageqlSendQueue){for(var i=0;i<window.pageqlSendQueue.length;i++){socket.send(window.pageqlSendQueue[i]);}window.pageqlSendQueue=[];}
        };

      socket.onmessage = (event) => {
        if (event.data == "reload") {
          window.location.reload();
        } else if (event.data === "get body text content") {
          socket.send(getBodyTextContent());
        } else {
          try {
            eval(event.data);
          } catch (e) {
            console.error("Failed to eval script", event.data, e);
          }
        }
      };

      socket.onclose = () => {
        setTimeout(forceReload, 100);
      };

        socket.onerror = () => {
          setTimeout(forceReload, 100);
        };
      }
    if (document.body) {
      setup();
    } else {
      window.addEventListener('DOMContentLoaded', setup);
    }
    document.currentScript.remove();

  })();
</script>
"""

def client_script(client_id: str) -> str:
    return _CLIENT_SCRIPT_TEMPLATE.replace("{client_id}", client_id)


