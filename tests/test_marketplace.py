import json,sys,unittest,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT/'skills/crawl-render-audit/scripts')); sys.path.insert(0,str(ROOT/'skills/trust-corroboration-graph/scripts'))
from audit_common import parse_robots,robot_decision
from corroboration_scorer import score_fact,assess_collision_risk
sys.path.insert(0,str(ROOT/'skills/crawl-render-audit/scripts'))
from render_and_data_scan import schema
sys.path.insert(0,str(ROOT/'skills/audit-orchestrator/scripts'))
from compose_report import dedupe, compute_summary
sys.path.insert(0,str(ROOT/'skills/citation-simulator/scripts'))
from generate_queries import build_queries
class MarketplaceTests(unittest.TestCase):
 def test_robots_partial_and_allow_override(self):
  g=parse_robots('User-agent: GPTBot\nDisallow: /private\nAllow: /private/public\nUser-agent: *\nDisallow:')
  self.assertFalse(robot_decision(g,'GPTBot','/private/x')['allowed']);self.assertTrue(robot_decision(g,'GPTBot','/private/public/x')['allowed']);self.assertTrue(robot_decision(g,'ClaudeBot','/')['allowed'])
 def test_corroboration_requires_evidence(self):
  r=score_fact({'fact':'x','sources':[{'domain':'x.com','is_brand_owned':False,'supports_fact':True}]});self.assertEqual(r['corroboration_strength'],'uncorroborated')
 def test_collision_requires_plausibility(self): self.assertEqual(assess_collision_risk([{'domain':'other.test','same_or_adjacent_industry':False}],{})['risk'],'none_detected')
 def test_schema_invalid_partial_and_visible_consistency(self):
  html='<script type="application/ld+json">{"@type":"Organization","name":"Hidden Corp"}</script><script type="application/ld+json">bad</script>'
  x=schema(html,'https://example.test/','Welcome');self.assertEqual(len(x['jsonld_parse_errors']),1);self.assertIn('url',x['validation'][0]['missing_important_fields']);self.assertEqual(x['organization_names_not_visible'],['Hidden Corp'])
 def test_static_content_not_render_finding_without_render_evidence(self):
  # The scanner's material condition requires a specific rendered/raw core-content gap.
  x=schema('<script type="application/ld+json">{"@type":"Product","name":"Widget"}</script>','https://x.test','Widget price $10');self.assertEqual(x['organization_names_not_visible'],[])
 def test_dedupe_and_severity_counts(self):
  fs=[{'title':'Missing canonical','category':'structured-data','severity':'low','evidence':'page A missing canonical','source_skill':'a','fingerprint':'canonical:/a','suggested_action':{'summary':'add','priority':'low','how_to_fix':'add tag'}},{'title':'Canonical absent','category':'structured-data','severity':'high','evidence':'page A confirms absent','source_skill':'b','fingerprint':'canonical:/a','suggested_action':{'summary':'add','priority':'high','how_to_fix':'add tag'}}]
  out=dedupe(fs);self.assertEqual(len(out),1);self.assertEqual(out[0]['severity'],'high');self.assertEqual(compute_summary(out)['high'],1)
 def test_fetch_failure_is_not_a_finding(self):
  # Network error output is an inconclusive scan record, leaving finding creation to evidence-aware orchestration.
  p=subprocess.run([sys.executable,str(ROOT/'skills/crawl-render-audit/scripts/render_and_data_scan.py'),'http://127.0.0.1:1'],capture_output=True,text=True,timeout=15); self.assertIn('unavailable',p.stdout)
 def test_citation_queries_do_not_assume_commerce(self):
  q=build_queries({'brand_name':'Public Agency','category':'agency'}); self.assertEqual(len(q),2); self.assertFalse(any('cost' in x['query'] for x in q))
 def test_skill_frontmatter_and_manifest(self):
  m=json.loads((ROOT/'marketplace.json').read_text()); self.assertEqual(sum(x.get('entrypoint',False) for x in m['skills']),1)
  for s in m['skills']:
   p=ROOT/s['path']/'SKILL.md'; self.assertTrue(p.exists()); head=p.read_text(encoding='utf-8').split('---',2)[1]
  keys=set(x.split(':',1)[0] for x in head.splitlines() if x and not x.startswith((' ','\t')) and ':' in x)
  # name+description are required by the agentskills.io spec; license and allowed-tools are
  # optional there but explicitly requested by the Round 3 handout. Assert required-as-subset,
  # not an exact set, so declaring the optional fields is not a test failure.
  self.assertTrue({'name','description'}<=keys, f"{s['id']} frontmatter missing required keys: {keys}")
  self.assertTrue(keys<={'name','description','license','allowed-tools'}, f"{s['id']} has unrecognised frontmatter keys: {keys}")
  name_line=[x for x in head.splitlines() if x.startswith('name:')][0].split(':',1)[1].strip()
  self.assertEqual(name_line,s['id'],"SKILL.md name must match the marketplace skill id and folder name")
 def test_report_validation_rejects_weak_action(self):
  r={'site':'x','audited_at':'2026-01-01T00:00:00Z','summary':{'total_findings':1,'critical':0,'high':0,'medium':0,'low':1},'findings':[{'id':'F-001','title':'x','severity':'low','evidence':'concrete observed evidence','suggested_action':{'summary':'x','priority':'low'}}]}
  with tempfile.NamedTemporaryFile(mode='w',suffix='.json',delete=False) as f:json.dump(r,f);n=f.name
  p=subprocess.run([sys.executable,str(ROOT/'skills/audit-orchestrator/scripts/compose_report.py'),'validate','--input',n],capture_output=True,text=True);self.assertNotEqual(p.returncode,0)
 def test_report_merge_accepts_utf8_bom(self):
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/'findings.json'; f.write_text('[]',encoding='utf-8-sig'); out=Path(d)/'report.json'
   p=subprocess.run([sys.executable,str(ROOT/'skills/audit-orchestrator/scripts/compose_report.py'),'merge','--site','https://example.test','--input',str(f),'--output',str(out)],capture_output=True,text=True)
   self.assertEqual(p.returncode,0,p.stderr)
if __name__=='__main__':unittest.main()
