"""Small bounded read-only payload/container observations; never native or network."""
import hashlib, json, os, stat, time
from pathlib import Path

def identity(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)

class Observer:
 def __init__(self,budget,check,*,hash_cap=128*2**20,event_cap=8*2**20):
  self.b,self.check=budget,check;self.hash_cap,self.event_cap=hash_cap,event_cap
  self.hashed=0;self.visited=0;self.evidence_bytes=0;self.cache={};self.previous=None
  self.roots={};self.events=[];self.exported={};self.queued={};self.matches=set()
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
       digest=hashlib.sha256();count=0
       while True:
        self.check();block=os.read(filefd,min(65536,meta.st_size-count+1))
        if not block:break
        count+=len(block);self.hashed+=len(block)
        assert count<=meta.st_size and self.hashed<=self.hash_cap
        digest.update(block)
       assert count==meta.st_size and identity(os.fstat(filefd))==identity(before_file),'partial/changed observed file'
       assert identity(os.stat(name,dir_fd=fd,follow_symlinks=False))==identity(before_file),'file replaced while observed'
       self.cache[token]=digest.hexdigest()
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

def payload_inventory(root,budget,check):
 observer=Observer(budget,check);snapshot=observer.snapshot(root)
 assert snapshot['exists']
 result={'.':{'mode':f'{stat.S_IMODE(Path(root).lstat().st_mode):04o}','directory':True}}
 for row in snapshot['entries']:
  result[row['path']]={k:v for k,v in row.items() if k in ('mode','directory','sha256')}
 return result


def verify_installed_runner(root,entries,budget,check):
 actual=payload_inventory(root,budget,check)
 expected={key:{k:v for k,v in row.items() if k in ('mode','directory','sha256')} for key,row in entries.items()}
 assert actual==expected,'installed runner differs from pinned original'
 info=Path(root).lstat()
 return {'path':str(root),'root_device_inode':[info.st_dev,info.st_ino],'files':actual,'exact_payload':True}
