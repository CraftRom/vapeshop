"""Bounded parallel public-IP probes and strict DNS JSON with no network."""
import importlib.util
from pathlib import Path
import json
import threading
from unittest.mock import patch
from qa_common import Report
r=Report('Origin API contracts')
path=Path(__file__).resolve().parents[2]/'deploy/promo-controller/controller.py'
spec=importlib.util.spec_from_file_location('origin_api',path);origin=importlib.util.module_from_spec(spec);spec.loader.exec_module(origin)
class Reply:
 def __init__(self,value):self.value=value
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self,limit):return self.value
barrier=threading.Barrier(3)
def ip_reply(request,timeout):
 barrier.wait(timeout=2)
 return Reply(b'8.8.8.8' if 'ifconfig' not in request.full_url else b'1.1.1.1')
with patch.object(origin,'urlopen',side_effect=ip_reply):
 ip,values,errors=origin._fetch_public_ip(4)
r.check(ip=='8.8.8.8' and len(values)==3 and not errors,'IPv4 providers run concurrently and majority agreement is preserved')
barrier=threading.Barrier(2);calls=[]
def family(version):
 calls.append(version);barrier.wait(timeout=2)
 return ('8.8.8.8' if version==4 else '2606:4700::1111'),[],[]
with patch.object(origin,'_fetch_public_ip',side_effect=family),patch.object(origin,'PUBLIC_IPV4_OVERRIDE',''),patch.object(origin,'PUBLIC_IPV6_OVERRIDE',''):
 first=origin.public_ip_info(force=True);second=origin.public_ip_info()
r.check(first['ipv4']=='8.8.8.8' and first['ipv6']=='2606:4700::1111' and len(calls)==2,'IPv4/IPv6 run concurrently and cached status performs no extra probes')
calls=[]
def dns(request,timeout):
 calls.append(request.full_url)
 body={'Status':2,'Answer':[{'type':2,'data':'bad.invalid'}]} if len(calls)==1 else {'Status':0,'Answer':[{'type':2,'data':'NS1.EXAMPLE.COM.'}]}
 return Reply(json.dumps(body).encode())
with patch.object(origin,'urlopen',side_effect=dns):
 names,error=origin._doh_ns_query('example.com')
r.check(names==['ns1.example.com'] and len(calls)==2,'DNS-over-HTTPS rejects unsuccessful envelopes and uses fallback provider')
with patch.object(origin,'urlopen',return_value=Reply(b'[]')):
 names,error=origin._doh_ns_query('example.com')
r.check(names==[] and error is not None,'malformed DNS JSON is reported without crashing')
import subprocess
for body in ({'Status':2,'Answer':[{'type':1,'data':'8.8.8.8'}]}, {'Status':0,'Answer':{'type':1,'data':'8.8.8.8'}}):
 with patch.object(origin,'urlopen',return_value=Reply(json.dumps(body).encode())):
  addresses,error=origin._doh_address_query('https://dns.google/resolve','example.com','A')
 r.check(addresses==[] and bool(error),'address resolver rejects unsuccessful or malformed DNS envelopes')
with patch.object(origin,'urlopen',return_value=Reply(b'{"Status":0,"Answer":[null,{"type":1,"data":"8.8.8.8"},{"type":1,"data":"127.0.0.1"}]}')):
 addresses,error=origin._doh_address_query('https://dns.google/resolve','example.com','A')
r.check(addresses==['8.8.8.8'] and error is None,'address resolver accepts only valid public addresses and ignores malformed rows')
script=Path(__file__).resolve().parents[2]/'deploy/certbot-init.sh'
legacy=subprocess.run(['bash',str(script),'example.com','--buypass'],stdin=subprocess.DEVNULL,capture_output=True,text=True)
r.check(legacy.returncode==2 and 'Buypass' in legacy.stderr and "Let's Encrypt" in legacy.stderr,'retired Buypass mode fails before email prompt or certificate issuance')
raise SystemExit(bool(r.done()))
