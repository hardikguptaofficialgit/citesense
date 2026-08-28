#!/usr/bin/env python3
"""Read-only robots audit. Tests actual sample paths, not merely Disallow: /."""
import json, sys, urllib.request, urllib.error
from urllib.parse import urlparse, urljoin
from audit_common import AI_USER_AGENTS, parse_robots, robot_decision
TIMEOUT=8
def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"brand-ai-readiness-audit/1.1"}),timeout=TIMEOUT) as r: return r.status,r.read().decode("utf8","replace")
    except urllib.error.HTTPError as e:return e.code,""
    except Exception as e:return None,str(e)
def main():
    if len(sys.argv)<2: raise SystemExit("usage: crawlability_check.py URL [PATH ...]")
    p=urlparse(sys.argv[1]); origin=f"{p.scheme}://{p.netloc}"; paths=sys.argv[2:] or ["/","/pricing","/products","/about"]
    status,body=fetch(urljoin(origin,"/robots.txt")); out={"site":origin,"budget":{"http_timeout_seconds":TIMEOUT},"checks":{}}
    if status==200:
        groups=parse_robots(body); decisions={a:{path:robot_decision(groups,a,path) for path in paths} for a in AI_USER_AGENTS}
        blocked={a:[path for path,d in ds.items() if not d["allowed"]] for a,ds in decisions.items()}; blocked={a:x for a,x in blocked.items() if x}
        sitemaps=[x.split(":",1)[1].strip() for x in body.splitlines() if x.lower().startswith("sitemap:")]
        out["checks"]["robots_txt"]={"found":True,"url":urljoin(origin,"/robots.txt"),"tested_paths":paths,"agent_path_decisions":decisions,"partially_blocked_agents":blocked,"sitemaps_declared":sitemaps}
    else: out["checks"]["robots_txt"]={"found":False,"status":status,"note":"No readable robots.txt; default allow, but audit did not infer crawlability from a failed network request."}; sitemaps=[]
    for n in ("llms.txt","llms-full.txt","ai.txt"):
        s,_=fetch(urljoin(origin,"/"+n));out["checks"][n.replace(".","_")]={"found":s==200,"status":s}
    candidates=list(dict.fromkeys((sitemaps or [urljoin(origin,"/sitemap.xml")])[:3])); out["checks"]["sitemaps"]=[{"url":u,"found":fetch(u)[0]==200} for u in candidates]
    print(json.dumps(out,indent=2))
if __name__=="__main__":main()
