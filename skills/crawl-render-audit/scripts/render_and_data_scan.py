#!/usr/bin/env python3
"""Evidence-oriented raw/rendered/schema scan; never labels JS use alone as a defect."""
import sys,re,json,urllib.request,urllib.error
from urllib.parse import urlparse,urljoin
from audit_common import visible_text, canonicalize
TIMEOUT=12
REQUIRED={"Organization":["name","url"],"LocalBusiness":["name","address"],"Product":["name"],"Offer":["price","priceCurrency","availability"],"Article":["headline","datePublished"],"FAQPage":["mainEntity"]}
def fetch(url):
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"brand-ai-readiness-audit/1.1"}),timeout=TIMEOUT) as r:return r.status,r.read().decode("utf8","replace")
 except urllib.error.HTTPError as e:return e.code,""
 except Exception as e:return None,str(e)
def blocks(html): return re.findall(r'(?is)<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',html)
def flatten(x,out):
 if isinstance(x,list):
  for n in x:flatten(n,out)
 elif isinstance(x,dict):
  if "@graph" in x: flatten(x["@graph"],out)
  else: out.append(x)
def schema(html,url,raw):
 parsed=[]; errors=[]
 for i,b in enumerate(blocks(html),1):
  try: flatten(json.loads(b.strip()),parsed)
  except Exception as e: errors.append({"block":i,"error":str(e)})
 results=[]; identities=[]
 for e in parsed:
  ts=e.get("@type",[]);ts=ts if isinstance(ts,list) else [ts]
  for t in ts:
   if t in REQUIRED: results.append({"type":t,"missing_important_fields":[f for f in REQUIRED[t] if not e.get(f)],"id":e.get("@id")})
  if any(t in ("Organization","LocalBusiness") for t in ts): identities.append({"name":e.get("name"),"url":e.get("url"),"sameAs":e.get("sameAs",[]),"@id":e.get("@id")})
 names=[x["name"] for x in identities if x.get("name")]; visible_name_consistency=[n for n in names if n.lower() not in raw.lower()]
 canon=re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']',html,re.I)
 canonical=canonicalize(url,canon.group(1)) if canon else None
 return {"jsonld_blocks_found":len(blocks(html)),"jsonld_parse_errors":errors,"entities":len(parsed),"validation":results,"organization_identity":identities,"organization_names_not_visible":visible_name_consistency,"canonical":canonical,"canonical_matches_fetched_url": canonicalize(url,url)==canonical if canonical else None,"duplicate_entity_ids":sorted({e.get("@id") for e in parsed if e.get("@id") and sum(1 for z in parsed if z.get("@id")==e.get("@id"))>1})}
def meta(html):
 def val(pattern):
  m=re.search(pattern,html,re.I|re.S);return m.group(1).strip() if m else None
 return {"title":val(r'<title[^>]*>(.*?)</title>'),"meta_description":val(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']'),"viewport_meta_present":bool(re.search(r'<meta[^>]+name=["\']viewport["\']',html,re.I))}
def main():
 if len(sys.argv)!=2:raise SystemExit("usage: render_and_data_scan.py URL")
 url=sys.argv[1];status,html=fetch(url);out={"url":url,"fetch_status":status,"budget":{"http_timeout_seconds":TIMEOUT,"render_timeout_seconds":TIMEOUT}}
 if status!=200: out["error"]="unavailable; no finding should be emitted without other evidence";print(json.dumps(out,indent=2));return
 raw=visible_text(html);out["raw_text_word_count"]=len(raw.split());out["raw_text_sample"]=raw[:500];out["meta"]=meta(html);out["structured_data"]=schema(html,url,raw)
 # Rendering is supplemental. A gap is material only if named core elements/facts appear rendered but not raw.
 try:
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
   b=p.chromium.launch();page=b.new_page();page.goto(url,timeout=TIMEOUT*1000,wait_until="domcontentloaded"); rendered=page.locator("body").inner_text(timeout=TIMEOUT*1000); b.close()
  rw=set(re.findall(r"[\w'-]{3,}",raw.lower()));dw=set(re.findall(r"[\w'-]{3,}",rendered.lower()));added=sorted(dw-rw)
  out["render_diff"]={"available":True,"rendered_text_word_count":len(rendered.split()),"rendered_only_word_count":len(added),"material_gap_candidate":len(raw.split())<40 and len(rendered.split())>120,"evidence":"Raw page contains %d words; rendered DOM contains %d. JS alone is not a finding."%(len(raw.split()),len(rendered.split()))}
 except Exception as e: out["render_diff"]={"available":False,"unavailable_reason":str(e),"note":"No render conclusion made."}
 print(json.dumps(out,indent=2))
if __name__=="__main__":main()
