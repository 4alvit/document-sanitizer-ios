"""Small bounded read-only payload/container observations; never native or network."""
import hashlib, json, os, stat, struct, time
from pathlib import Path

def identity(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)

class Observer:
 def __init__(self,budget,check,*,hash_cap=128*2**20,event_cap=8*2**20):
  self.b,self.check=budget,check;self.hash_cap,self.event_cap=hash_cap,event_cap
  self.hashed=0;self.visited=0;self.evidence_bytes=0;self.cache={};self.previous=None
  self.roots={};self.events=[];self.exported={};self.queued={};self.matches=set()
  self.loader_paths=frozenset();self.loader_headers={}
 def snapshot(self,root,*,skip_incomplete=False):
  self.check();root=Path(root)
  try:info=root.lstat()
  except FileNotFoundError:return {'exists':False,'entries':[]}
  assert stat.S_ISDIR(info.st_mode) and not root.is_symlink()
  key=str(root);previous=self.roots.setdefault(key,(info.st_dev,info.st_ino))
  assert previous==(info.st_dev,info.st_ino),'observed container root changed identity'
  rows=[]
  def visit(fd,prefix):
   self.check();before=os.fstat(fd)
   names=sorted(os.listdir(fd));assert len(names)<=2048
   for name in names:
    assert name not in ('.','..') and '/' not in name and '\\' not in name
    self.check();self.visited+=1;assert self.visited<=200000,'cumulative entry observation cap'
    assert len(rows)<2048,'snapshot entry cap'
    meta=os.stat(name,dir_fd=fd,follow_symlinks=False);path=prefix+name
    row={'path':path,'mode':f'{stat.S_IMODE(meta.st_mode):04o}'}
    if stat.S_ISDIR(meta.st_mode):
     row['directory']=True;rows.append(row)
     if skip_incomplete and name.endswith('.incomplete'):
      row['uncommitted_copy_not_read']=True;continue
     child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
     try:visit(child,path+'/')
     finally:os.close(child)
    else:
     assert stat.S_ISREG(meta.st_mode),'symlink/special observation rejected'
     assert meta.st_size<=16*2**20,'individual observed file cap'
     token=(key,path,identity(meta))
     if token not in self.cache:
      assert self.hashed+meta.st_size<=self.hash_cap,'cumulative hashing cap'
      filefd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
      try:
       before_file=os.fstat(filefd);assert identity(before_file)==identity(meta)
       digest=hashlib.sha256();count=0;loader_bytes=bytearray() if path in self.loader_paths else None
       while True:
        self.check();block=os.read(filefd,min(65536,meta.st_size-count+1))
        if not block:break
        count+=len(block);self.hashed+=len(block)
        assert count<=meta.st_size and self.hashed<=self.hash_cap
        digest.update(block)
        if loader_bytes is not None:loader_bytes.extend(block)
       assert count==meta.st_size and identity(os.fstat(filefd))==identity(before_file),'partial/changed observed file'
       assert identity(os.stat(name,dir_fd=fd,follow_symlinks=False))==identity(before_file),'file replaced while observed'
       self.cache[token]=digest.hexdigest()
       if loader_bytes is not None:self.loader_headers[path]=loader_header_types(loader_bytes)
      finally:os.close(filefd)
     assert identity(os.stat(name,dir_fd=fd,follow_symlinks=False))==identity(meta),'cached or read file changed before observation completed'
     row.update(bytes=meta.st_size,sha256=self.cache[token]);rows.append(row)
   after=os.fstat(fd)
   assert identity(before)==identity(after),'directory changed during observation'
  with self.b.directory(root) as fd:visit(fd,'')
  return {'exists':True,'root_device_inode':list(previous),'entries':rows}
 def event(self,group,tmp,stream):
  state={'group':self.snapshot(group,skip_incomplete=True),'tmp':self.snapshot(tmp)}
  if state!=self.previous:
   raw=(json.dumps({'elapsed':time.monotonic()-self.started,**state},sort_keys=True)+'\n').encode()
   assert self.evidence_bytes+len(raw)<=self.event_cap,'cumulative event evidence cap'
   assert stream.write(raw)==len(raw);stream.flush();self.evidence_bytes+=len(raw)
   self.events.append(state);self.previous=state
  for row in state['tmp']['entries']:
   if 'sha256' in row and row['path'].lower().endswith('.pdf'):self.exported[row['sha256']]=row['path']
  for row in state['group']['entries']:
   if 'sha256' in row and any(part.endswith('.ready') for part in Path(row['path']).parts):self.queued[row['sha256']]=row['path']
  self.matches=set(self.exported)&set(self.queued)
  return state
 def assert_workflow(self):
  assert self.events and not self.events[0]['group']['entries'] and not self.events[0]['tmp']['entries'],'nonempty initial inbox/export baseline'
  assert len(self.matches)==1,'exactly one exported PDF must match an actual committed queue copy'
  assert not self.events[-1]['group']['entries'] and not self.events[-1]['tmp']['entries'],'queued/export temporary files remain'
  return {'matched_hashes':sorted(self.matches),'exported':self.exported,'queued':self.queued,'cumulative_hashed_bytes':self.hashed,'cumulative_entries':self.visited,'event_bytes':self.evidence_bytes,'events':len(self.events)}

def payload_inventory(root,budget,check,*,loader_headers=None):
 observer=Observer(budget,check)
 if loader_headers is not None:observer.loader_paths=frozenset(INSTALLED_RUNNER_LOADERS)
 snapshot=observer.snapshot(root)
 if loader_headers is not None:loader_headers.update(observer.loader_headers)
 assert snapshot['exists']
 result={'.':{'mode':f'{stat.S_IMODE(Path(root).lstat().st_mode):04o}','directory':True}}
 for row in snapshot['entries']:
  result[row['path']]={k:v for k,v in row.items() if k in ('mode','directory','sha256')}
 return result


# Complete loader-only transition set observed on the iOS18.5 installed UI runner.
# The app and main runner executable are excluded. Types are verified from the
# same no-follow, stable, SHA-bound file read used by the initial inventory.
INSTALLED_RUNNER_LOADERS={
 'Frameworks/Testing.framework/Testing':6,
 'Frameworks/XCTAutomationSupport.framework/XCTAutomationSupport':6,
 'Frameworks/XCTest.framework/XCTest':6,
 'Frameworks/XCTestCore.framework/XCTestCore':6,
 'Frameworks/XCTestSupport.framework/XCTestSupport':6,
 'Frameworks/XCUIAutomation.framework/XCUIAutomation':6,
 'Frameworks/XCUnit.framework/XCUnit':6,
 'Frameworks/libXCTestSwiftSupport.dylib':6,
 'PlugIns/CleanSendUITests.xctest/CleanSendUITests':8,
}

def loader_header_types(raw):
 # At most one already-capped16MiB file is buffered; no second read/hash.
 # This identifies loader headers only, not a substitute for codesign/content checks.
 try:
  def thin(offset,size):
   assert size>=32 and 0<=offset<=len(raw)-size
   magic=bytes(raw[offset:offset+4]);assert magic in (b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf')
   endian='<' if magic==b'\xcf\xfa\xed\xfe' else '>'
   _,cpu,_,kind,*_=struct.unpack_from(endian+'8I',raw,offset)
   assert cpu in (0x0100000c,0x01000007)
   return {'cpu':cpu,'filetype':kind}
  magic=bytes(raw[:4])
  if magic in (b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf'):return [thin(0,len(raw))]
  formats={b'\xca\xfe\xba\xbe':('>',False),b'\xbe\xba\xfe\xca':('<',False),b'\xca\xfe\xba\xbf':('>',True),b'\xbf\xba\xfe\xca':('<',True)}
  endian,wide=formats[magic];count=struct.unpack_from(endian+'I',raw,4)[0]
  assert 1<=count<=16
  row_size=32 if wide else 20;header_end=8+count*row_size;assert header_end<=len(raw)
  result=[];ranges=[]
  for index in range(count):
   row=struct.unpack_from(endian+('IIQQII' if wide else 'IIIII'),raw,8+index*row_size)
   cpu,_,offset,size,align=row[:5]
   assert not wide or row[5]==0
   assert align<=31 and offset>=header_end and offset%(1<<align)==0
   assert 0<size<=len(raw)-offset and not any(offset<end and begin<offset+size for begin,end in ranges)
   part=thin(offset,size);assert part['cpu']==cpu and cpu not in [r['cpu'] for r in result]
   ranges.append((offset,offset+size));result.append(part)
  return result
 except (AssertionError,KeyError,struct.error):return None

def verify_installed_runner(root,entries,budget,check,record,*,initial_install=False,installed_identity=None):
 loader_headers={} if initial_install else None
 actual=payload_inventory(root,budget,check,loader_headers=loader_headers)
 expected={key:{k:v for k,v in row.items() if k in ('mode','directory','sha256')} for key,row in entries.items()}
 differences=[]
 for name in sorted(set(actual)|set(expected)):
  found,wanted=actual.get(name),expected.get(name)
  if found==wanted:continue
  kind='added' if name not in expected else 'missing' if name not in actual else 'changed'
  fields=[]
  if kind=='changed':
   if bool(found.get('directory'))!=bool(wanted.get('directory')):fields.append('type')
   if found.get('mode')!=wanted.get('mode'):fields.append('mode')
   if found.get('sha256')!=wanted.get('sha256'):fields.append('sha256')
   if set(found)!=set(wanted):fields.append('entry_fields')
  differences.append({'path':name,'change':kind,'fields':fields,'expected':wanted,'actual':found})
 info=Path(root).lstat()
 accepted=(initial_install and {d['path'] for d in differences}==set(INSTALLED_RUNNER_LOADERS)
  and all(d['change']=='changed' and d['fields']==['mode'] and set(d['expected'])==set(d['actual'])=={'mode','sha256'}
   and d['expected']['mode']=='0755' and d['actual']['mode']=='0644'
   and d['expected']['sha256']==d['actual']['sha256'] and len(d['actual']['sha256'])==64
   and loader_headers.get(d['path']) and any(h['cpu']==0x0100000c for h in loader_headers[d['path']])
   and all(h['filetype']==INSTALLED_RUNNER_LOADERS[d['path']] for h in loader_headers[d['path']]) for d in differences))
 identity_matches=(installed_identity is None or installed_identity=={'path':str(root),'root_device_inode':[info.st_dev,info.st_ino]})
 receipt={'installed_identity_matches':identity_matches,'comparison_basis':'pinned_original_runner' if initial_install else 'exact_expected_inventory','accepted_payload':bool(actual==expected or accepted),
  'accepted_install_transitions':differences if accepted else [],'loader_headers':loader_headers,
  'path':str(root),'root_device_inode':[info.st_dev,info.st_ino],'files':actual,'exact_payload':actual==expected,'differences':differences,'expected_entries':len(expected),'actual_entries':len(actual)}
 check();record(receipt);check()
 assert (actual==expected or accepted) and identity_matches,'installed runner differs from admitted inventory; bounded inventory saved'
 return receipt
