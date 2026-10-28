#!/usr/bin/env python3
"""One granted exact shipped-package smoke, no build/re-sign/network or retry."""
import hashlib, importlib.util, json, os, plistlib, re, shutil, signal, stat, subprocess, sys, time, uuid, zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
CONTEXT=None
SCOPE=OWNED_ROOT=ASSETS=ZIP=BUNDLE=BINDING=TEMPLATE=None
ZIP_SHA=PAYLOAD_SHA=HEAD=None
CASE='CleanSendUITests/ShareExtensionEntryTests/testPDFReceivedByExtensionThenImported'
APP_ID='io.github.4alvit.cleansend';GROUP='group.io.github.4alvit.cleansend'
CAP=2*2**30;FLOOR=12*2**30

def version(text):
 parts=[int(p) for p in text.split('.')];assert 1<=len(parts)<=3
 return tuple((parts+[0,0,0])[:3])

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(name):
 name={'window_budget':'window','bounded_lifecycle':'lifecycle','prepare_config':'config'}.get(name,name)
 spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def validate_grant(path):
 global CONTEXT,SCOPE,OWNED_ROOT,ASSETS,ZIP,BUNDLE,BINDING,TEMPLATE,ZIP_SHA,PAYLOAD_SHA,HEAD
 if not __debug__:raise SystemExit('Python assertions must be enabled')
 assert os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_EVENT_NAME')=='pull_request'
 raw=path.read_bytes();assert len(raw)<=1024*1024 and hashlib.sha256(raw).hexdigest()==os.environ['RELEASE_SMOKE_CONTEXT_SHA']
 grant=json.loads(raw)
 assert grant['repository']==os.environ['GITHUB_REPOSITORY']=='4alvit/document-sanitizer-ios'
 assert grant['head']==os.environ['EXPECTED_HEAD_SHA'] and grant['run']==os.environ['GITHUB_RUN_ID'] and grant['attempt']==os.environ['GITHUB_RUN_ATTEMPT'] and grant['checkout']==os.environ['GITHUB_SHA']
 expected=Path(os.environ['RUNNER_TEMP'])/f"redact-package-smoke-{grant['run']}-attempt-{grant['attempt']}"
 assert Path(grant['base'])==expected and Path(grant['scope'])==expected/'native'
 assert grant['seconds']==780 and grant['owned_cap_bytes']==CAP and grant['free_floor_bytes']==FLOOR
 assert grant['get_count']==0 and grant['native_worker_count']==1 and grant['retry_authorized'] is False
 assert grant['device_type']=='com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M4-16GB'
 assert grant['runtime_id']=='com.apple.CoreSimulator.SimRuntime.iOS-18-5' and grant['runtime_version']=='18.5' and grant['xcode_build']=='16F6'
 assert time.time()<grant['expires_unix'] and time.monotonic()+780<grant['pipeline_deadline']
 total=0
 for name,digest in grant['source_files'].items():
  assert time.monotonic()+780<grant['pipeline_deadline']
  candidate=ROOT/name;assert not candidate.is_symlink() and candidate.is_file() and candidate.is_relative_to(ROOT) and '..' not in candidate.parts
  total+=candidate.stat().st_size;assert total<=16*2**20
  assert sha(candidate)==digest
 CONTEXT=grant;SCOPE=Path(grant['scope']);OWNED_ROOT=expected;ASSETS=Path(grant['assets']);BINDING=Path(grant['runner_binding']);TEMPLATE=Path(grant['runner_template'])
 assert ASSETS==expected/'release-assets' and BINDING==expected/'runner-binding.json' and TEMPLATE==expected/'privacy-inputs/generated-original.xctestrun'
 ZIP=ASSETS/'RedactLeaf-adhoc-simulator.zip';BUNDLE=SCOPE/'extracted/CleanSend.app'
 ZIP_SHA=grant['adhoc_zip_sha256'];PAYLOAD_SHA=grant['payload_manifest_sha256'];HEAD=grant['head']
 return grant

class Resources:
 def __init__(self,start):self.start=start;self.device=None;self.last=0;self.maximum=0
 def check(self,phase=560):
  assert time.monotonic()<self.start+phase,'original phase deadline'
  assert shutil.disk_usage(SCOPE).free>=FLOOR,'free floor'
  assert time.monotonic()<self.start+phase,'deadline after free-floor observation'
  if time.monotonic()-self.last<1:return
  total=0;count=0
  for root in [OWNED_ROOT]+([self.device] if self.device and self.device.exists() else []):
   for directory,dirs,files in os.walk(root,followlinks=False):
    assert time.monotonic()<self.start+phase
    for name in ['.']+dirs+files:
     assert time.monotonic()<self.start+phase,'owned entry deadline'
     path=Path(directory)/name
     try:info=path.lstat()
     except FileNotFoundError:continue  # Concurrent simulator deletion; no traversal or inferred content.
     count+=1
     assert count<=100000,'owned inventory entry cap'
     # Symlinks in simulator OS state are counted but never traversed.
     assert time.monotonic()<self.start+phase,'owned stat deadline'
     total+=info.st_blocks*512
     if name in dirs and stat.S_ISLNK(info.st_mode):dirs.remove(name)
  assert time.monotonic()<self.start+phase,'final inventory deadline'
  self.maximum=max(self.maximum,total);self.last=time.monotonic()
  assert total<=CAP,'owned allocation cap'

def extract_exact(b,e,resources,expected):
 assert ZIP.stat().st_size==CONTEXT['adhoc_zip_bytes'] and sha(ZIP)==ZIP_SHA
 BUNDLE.parent.mkdir(mode=0o700)
 with zipfile.ZipFile(ZIP) as archive:
  rows=archive.infolist();assert len(rows)<=2000 and sum(r.file_size for r in rows)<=32*2**20
  names={}
  for row in rows:
   resources.check();name=row.filename.rstrip('/');b.safe(name)
   assert row.filename==row.orig_filename and name not in names and not row.flag_bits&1
   assert name=='CleanSend.app' or name.startswith('CleanSend.app/')
   relative='.' if name=='CleanSend.app' else name.removeprefix('CleanSend.app/')
   assert relative in expected and row.file_size<=8*2**20
   mode=row.external_attr>>16;assert not stat.S_ISLNK(mode)
   assert stat.S_IFMT(mode) in (stat.S_IFDIR,stat.S_IFREG) and stat.S_ISDIR(mode)==row.is_dir()
   assert f'{stat.S_IMODE(mode):04o}'==expected[relative]['mode'];names[name]=(row,relative)
  assert {r for _,r in names.values()}==set(expected)
  for name,(row,relative) in sorted(names.items(),key=lambda pair:(pair[0].count('/'),pair[0])):
   destination=BUNDLE.parent/name
   if row.is_dir():
    destination.mkdir(mode=int(expected[relative]['mode'],8));destination.chmod(int(expected[relative]['mode'],8))
   else:
    assert not expected[relative].get('directory')
    with archive.open(row) as stream:raw=stream.read(row.file_size+1)
    assert len(raw)==row.file_size and hashlib.sha256(raw).hexdigest()==expected[relative]['sha256']
    with b.directory(destination.parent) as fd:
     target=os.open(destination.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,int(expected[relative]['mode'],8),dir_fd=fd)
     try:
      assert os.write(target,raw)==len(raw);os.fchmod(target,int(expected[relative]['mode'],8));os.fsync(target)
     finally:os.close(target)
 assert e.payload_inventory(BUNDLE,b,resources.check)==expected

def worker(start,grant):
 b,e,l,c=load('window_budget'),load('evidence'),load('bounded_lifecycle'),load('prepare_config')
 l.OUT=SCOPE;l.ROOT=HERE;l.CONFIGURATION='Release'
 run=l.Run();run.start=start
 run.meta.update(owner_worker_pid=os.getpid(),binary_kind='exact verified shipped adhoc simulator ZIP; same-run provenance-bound Release UI runner',build_configuration='Release',build_scheme=None,test_plan=None,context_sha256=sha(Path(sys.argv[1])),head=HEAD)
 resources=Resources(start);uid=None;failures=[];sampler=None;expected=None
 def interrupted(*_):
  if run.meta.get('cleanup_phase'):return
  raise InterruptedError('SIGTERM')
 signal.signal(signal.SIGTERM,interrupted)
 def command(args,name,limit=15,required=True):
  if run.end==560:resources.check()
  return run.command(args,name,limit,required)
 def output(args,name,limit=15):
  command(args,name,limit);return (SCOPE/name).read_text().strip()
 def container(kind,name,identifier=APP_ID):
  path=Path(output(['xcrun','simctl','get_app_container',uid,identifier,kind],name))
  assert path.is_absolute() and str(path)==str(path.resolve()) and path.is_relative_to(resources.device/'data')
  with b.directory(path):pass
  return path
 def installed(name):
  runner=c.verify_runner(json.loads(BINDING.read_bytes()))
  l.save(SCOPE/(name+'.runner.json'),runner)
  path=container('app',name+'-path.txt');value=e.payload_inventory(path,b,resources.check)
  l.save(SCOPE/name,{'path':str(path),'files':value,'exact_payload':value==expected});assert value==expected
  frozen=json.loads(BINDING.read_bytes())
  actual_runner=container('app',name+'-runner-path.txt',frozen['runner_Info']['CFBundleIdentifier'])
  runner_receipt=e.verify_installed_runner(actual_runner,frozen['runner_entries'],b,resources.check)
  l.save(SCOPE/(name+'.installed-runner.json'),runner_receipt)
  return path
 try:
  assert CONTEXT['head']==HEAD and CONTEXT['tree'] and CONTEXT['checkout']
  assert sha(ASSETS/'payload-sha256.json')==PAYLOAD_SHA
  expected=json.loads((ASSETS/'payload-sha256.json').read_bytes())[ZIP.name]
  extract_exact(b,e,resources,expected)
  developer=Path(output(['xcode-select','-p'],'developer.txt'))
  xcode=output(['xcodebuild','-version'],'xcode-version.txt',20)
  assert xcode=='Xcode 16.4\nBuild version '+grant['xcode_build'],'same-run runner toolchain mismatch; no substitute'
  runtimes=json.loads(output(['xcrun','simctl','list','runtimes','--json'],'runtimes.json',60))['runtimes']
  runtime=[r for r in runtimes if r['identifier']==grant['runtime_id'] and r.get('isAvailable')]
  assert len(runtime)==1 and runtime[0]['version']==grant['runtime_version'] and os.uname().machine in runtime[0]['supportedArchitectures']
  assert grant['device_type'] in {d['identifier'] for d in runtime[0]['supportedDeviceTypes']}
  types=json.loads(output(['xcrun','simctl','list','devicetypes','--json'],'device-types.json'))['devicetypes']
  device=[d for d in types if d['identifier']==grant['device_type']];assert len(device)==1
  assert version(device[0]['minRuntimeVersionString'])<=version(grant['runtime_version'])<=version(device[0]['maxRuntimeVersionString'])
  appinfo=plistlib.loads((BUNDLE/'Info.plist').read_bytes());assert version(appinfo['MinimumOSVersion'])<=version(grant['runtime_version'])
  run.meta['runtime']=runtime[0];run.meta['device_type']=device[0]
  config=c.prepare(BUNDLE,developer,SCOPE/'config',BINDING,TEMPLATE,HEAD,grant['tree'])
  encoded=(SCOPE/'config/exact-package-share.xctestrun').read_bytes()
  assert b'storekit' not in encoded.lower() and b'commerce' not in encoded.lower(),'commerce configuration rejected'
  frozen=json.loads(BINDING.read_bytes())
  assert frozen['runner_Info']['DTXcodeBuild']==grant['xcode_build']
  assert version(frozen['runner_Info']['MinimumOSVersion'])<=version(grant['runtime_version'])
  for label,bundle in [('app',BUNDLE),('extension',BUNDLE/'PlugIns/CleanSendShare.appex'),('runner',Path(frozen['runner']))]:
   command(['codesign','--verify','--strict','--all-architectures',bundle],'signature-'+label+'.log',15)
  assert run.remaining()>=304,'insufficient test admission before device creation'
  # Startup commands use the original work deadline; their maximum allowances
  # are not accumulated as a mandatory minimum. XCTest still needs 304s below.
  name='RedactLeaf-Exact-Package-'+str(uuid.uuid4());run.meta['owned_device_name']=name;run.persist()
  uid=output(['xcrun','simctl','create',name,grant['device_type'],grant['runtime_id']],'create.txt');uuid.UUID(uid)
  run.meta['owned_uuid']=uid;resources.device=Path.home()/'Library/Developer/CoreSimulator/Devices'/uid;run.persist()
  command(['xcrun','simctl','boot',uid],'boot.log',20)
  command(['xcrun','simctl','bootstatus',uid,'-b'],'bootstatus.log',90)
  assert run.remaining()>=304,'insufficient test admission after boot'
  command(['xcrun','simctl','ui',uid,'content_size',l.AX5],'set-ax5.log',60)
  assert output(['xcrun','simctl','ui',uid,'content_size'],'ax5-readback.txt',60)==l.AX5
  command(['xcrun','simctl','install',uid,BUNDLE],'install.log',30)
  command(['xcrun','simctl','install',uid,Path(frozen['runner'])],'install-runner.log',30)
  installed('installed-before.json')
  # The app creates its own state; the driver never seeds a workspace or queue.
  command(['xcrun','simctl','launch',uid,APP_ID],'initial-launch.log',20)
  data=container('data','data-container.txt');group=container(GROUP,'group-container.txt')
  assert data!=group
  sampler=e.Observer(b,resources.check);sampler.started=start
  with (SCOPE/'container-events.jsonl').open('xb') as events:
   baseline=sampler.event(group/'SharedInbox',data/'tmp/CleanSend',events)
   assert not baseline['group']['entries'] and not baseline['tmp']['entries']
   assert run.remaining()>=304,'insufficient full300s XCTest admission'
   argv=['xcodebuild','test-without-building','-xctestrun',str(SCOPE/'config/exact-package-share.xctestrun'),'-destination','platform=iOS Simulator,id='+uid,'-parallel-testing-enabled','NO','-maximum-concurrent-test-simulator-destinations','1','-only-testing:'+CASE,'-test-timeouts-enabled','YES','-maximum-test-execution-time-allowance','240','-collect-test-diagnostics','never','-resultBundlePath',str(SCOPE/'result.xcresult')]
   item={'args':argv,'started_at':l.now(),'timeout_seconds':300};run.meta['commands'].append(item);run.persist()
   proc=None;during=False;tail=b'';log_read=0;end=min(time.monotonic()+300,start+560-4)
   previous_end=run.end;run.end=min(previous_end,end-start)
   try:
    with (SCOPE/'test.log').open('xb') as log:
     proc=subprocess.Popen(argv,cwd=HERE,env=l.ENV,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
     item['owned_process_group']=proc.pid;run.persist()
     with (SCOPE/'test.log').open('rb') as reader:
      while proc.poll() is None:
       resources.check();assert time.monotonic()<end,'XCTest outer300s limit'
       chunk=reader.read(65536);log_read+=len(chunk);assert log_read<=16*2**20,'test log read cap'
       tail=(tail+chunk)[-131072:]
       if not during and b"testPDFReceivedByExtensionThenImported]' started" in tail:
        installed('installed-during.json');during=True
       sampler.event(group/'SharedInbox',data/'tmp/CleanSend',events)
       time.sleep(min(.25,max(0,end-time.monotonic())))
    run.meta['xcodebuild_returncode']=proc.returncode;assert proc.returncode==0
    assert during,'selected testcase was not observed; no inferred installed identity'
   finally:
    if proc is not None:
     l.stop_group(proc,item);item['returncode']=proc.returncode
    item['finished_at']=l.now();run.end=previous_end;run.persist()
   installed('installed-after.json')
   sampler.event(group/'SharedInbox',data/'tmp/CleanSend',events)
   run.meta['share_copy_cleanup']=sampler.assert_workflow()
  assert e.payload_inventory(BUNDLE,b,resources.check)==expected
  run.meta['original_extracted_payload_unchanged']=True
 except BaseException as error:failures.append(repr(error))
 finally:
  mark_cleanup(run,start,failures,l)
  run.end=l.RECOVERY_END
  if not uid and run.meta.get('owned_device_name'):
   try:
    devices=json.loads(run.output(['xcrun','simctl','list','devices','--json'],'create-recovery.json'))['devices']
    matches=[d['udid'] for values in devices.values() for d in values if d['name']==run.meta['owned_device_name']]
    assert len(matches)<=1;uid=matches[0] if matches else None;run.meta['owned_uuid']=uid
   except BaseException as error:failures.append('device recovery: '+repr(error))
  if uid:
   cleanup={}
   for action,limit,deadline in [('shutdown',30,l.SHUTDOWN_END),('delete',12,l.DELETE_END)]:
    run.end=deadline
    try:cleanup[action]=run.command(['xcrun','simctl',action,uid],'cleanup-'+action+'.log',limit,False)
    except BaseException as error:cleanup[action]=repr(error)
   run.end=l.CLEANUP_END
   try:
    devices=json.loads(run.output(['xcrun','simctl','list','devices','--json'],'devices-after.json'))['devices']
    run.meta['device_removed']=not any(d['udid']==uid for values in devices.values() for d in values)
    assert cleanup=={'shutdown':0,'delete':0} and run.meta['device_removed']
   except BaseException as error:failures.append('device cleanup: '+repr(error))
   run.meta['cleanup']=cleanup
   run.persist()
  run.end=772
  try:
   assert run.meta.get('xcodebuild_returncode')==0
   for kind in ['summary','tests']:
    run.command(['xcrun','xcresulttool','get','test-results',kind,'--path',SCOPE/'result.xcresult','--format','json'],kind+'.json',15)
   summary=json.loads((SCOPE/'summary.json').read_bytes())
   assert tuple(summary.get(k) for k in ['passedTests','failedTests','skippedTests','totalTestCount'])==(1,0,0,1)
   assert 'testPDFReceivedByExtensionThenImported' in (SCOPE/'tests.json').read_text()
   run.command(['xcrun','xcresulttool','export','attachments','--path',SCOPE/'result.xcresult','--output-path',SCOPE/'attachments'],'attachments-export.log',40)
  except BaseException as error:failures.append('result evidence: '+repr(error))
  try:
   resources.check(772)
   assert sha(ZIP)==ZIP_SHA and sha(ASSETS/'payload-sha256.json')==PAYLOAD_SHA
   c.verify_runner(json.loads(BINDING.read_bytes()));run.meta['runner_and_package_unchanged']=True
  except BaseException as error:failures.append('final integrity/resources: '+repr(error))
  run.meta.update(result='failed' if failures else 'passed_pending_independent_review',failures=failures,finished_at=l.now(),elapsed_seconds=time.monotonic()-start,maximum_observed_owned_allocation=resources.maximum)
  run.persist()
 return 1 if failures else 0

def mark_cleanup(run,start,failures,lifecycle):
 run.meta['cleanup_phase']={'entered_monotonic':time.monotonic(),'absolute_deadline':start+lifecycle.CLEANUP_END}
 try:run.persist()
 except BaseException as error:failures.append('Cleanup acknowledgement persistence: '+repr(error))
 # A failed acknowledgement write does not skip the owned-device cleanup attempts.


def cleanup_metadata():
 path=SCOPE/'metadata.json'
 assert path.stat().st_size<=256*1024
 return json.loads(path.read_bytes())

def await_cleanup_ack(proc,start,intent,*,clock=time.monotonic,sleep=time.sleep,read=cleanup_metadata):
 # Three seconds belong to the existing owned-group stop, plus two for receipt acknowledgement.
 absolute_end=start+660;ack_end=min(absolute_end,clock()+5);acknowledged=False
 while proc.poll() is None and clock()<absolute_end:
  try:
   meta=read();phase=meta.get('cleanup_phase',{})
   entered=phase.get('entered_monotonic')
   acknowledged=(type(entered) in (int,float) and start<=entered<=clock()
                 and phase.get('absolute_deadline')==absolute_end)
   if acknowledged:
    intent['cleanup_acknowledged']=True
    if meta.get('device_removed') is True:
     intent['device_absence_observed']=True;return
  except (OSError,ValueError,AssertionError) as error:intent['cleanup_observation_error']=repr(error)
  if not acknowledged and clock()>=ack_end:break
  limit=absolute_end if acknowledged else ack_end
  sleep(min(.1,max(0,limit-clock())))
 intent['cleanup_wait_ended_monotonic']=clock()
 intent['cleanup_absolute_deadline']=absolute_end

def final_read(path,deadline,clock=time.monotonic):
 assert clock()<deadline,'whole deadline before final read'
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  info=os.fstat(fd);assert stat.S_ISREG(info.st_mode) and info.st_size<=256*1024
  raw=bytearray()
  while True:
   assert clock()<deadline,'whole deadline during final read'
   block=os.read(fd,min(65536,256*1024-len(raw)+1))
   assert clock()<deadline,'whole deadline after final read'
   if not block:break
   raw.extend(block);assert len(raw)<=256*1024
  after=os.fstat(fd)
  assert (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
  assert len(raw)==info.st_size
  return bytes(raw)
 finally:os.close(fd)

def retain_cleanup_obligation(intent,start):
 try:
  raw=final_read(SCOPE/'metadata.json',start+780);meta=json.loads(raw);owned_uuid=meta.get('owned_uuid');owned_name=meta.get('owned_device_name')
  if owned_uuid:uuid.UUID(owned_uuid)
  removed=meta.get('device_removed') is True
  requested=bool(owned_uuid or owned_name or any(c.get('args',[])[:3]==['xcrun','simctl','create'] for c in meta.get('commands',[])))
  digest=hashlib.sha256(raw).hexdigest();assert time.monotonic()<start+780,'whole deadline after metadata hash'
  intent['cleanup_obligation']={'owned_uuid':owned_uuid,'owned_name':owned_name,'absence_verified':removed,'cleanup_required':requested,
      'worker_cleanup':meta.get('cleanup'),'metadata_sha256':digest,
      'status':'SATISFIED' if removed else ('UNCONFIRMED_REQUIRES_OWNED_DEVICE_FOLLOWUP' if requested else 'NOT_REQUIRED_NO_CREATE_COMMAND_RECORDED'),
      'required_if_unconfirmed':[] if removed or not requested else ['Recover only the recorded unique owned name if UUID unavailable','Shutdown/delete only the owned UUID under a coordinated cleanup grant','Verify owned UUID absent; preserve the failure receipt']}
 except BaseException as error:
  intent['cleanup_obligation']={'status':'UNKNOWN_REQUIRES_OWNERSHIP_RECOVERY','absence_verified':False,'error':repr(error)}

def final_write(value,start,clock=time.monotonic):
 deadline=start+780
 assert clock()<deadline,'whole deadline before final serialization'
 raw=(json.dumps(value,indent=2)+'\n').encode();assert len(raw)<=256*1024
 assert clock()<deadline,'whole deadline after final serialization'
 path=SCOPE/'invocation-final.json';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  offset=0
  while offset<len(raw):
   assert clock()<deadline,'whole deadline before final write'
   count=os.write(fd,raw[offset:offset+65536]);assert count>0;offset+=count
   assert clock()<deadline,'whole deadline after final write'
  os.fsync(fd);assert clock()<deadline,'whole deadline after final fsync'
 finally:os.close(fd)
 return str(path)

def aggregate_command_groups(meta,start,clock=time.monotonic,probe=os.killpg):
 commands=meta.get('commands',[]);assert len(commands)<=128
 groups=[]
 for command in commands:
  assert clock()<start+780,'whole deadline before owned-command group proof'
  pid=command.get('owned_process_group')
  if pid is None:continue
  assert type(pid) is int and pid>1
  row={'pid':pid,'args':command.get('args'),'leader_returncode':command.get('returncode'),'owner_worker':meta.get('owner_worker_pid'),'cleanup_observation':command.get('cleanup_observation'),'cleanup_error':command.get('cleanup_error')}
  if command.get('owned_group_absent') is True:row.update(absent=True,basis='worker recorded bounded group closure')
  else:
   try:probe(pid,0);row.update(absent=False,basis='group still present; no blind signal after worker exit')
   except ProcessLookupError:row.update(absent=True,basis='terminal read-only group probe absent; leader reap only if recorded')
   except OSError as error:row.update(absent=False,basis='group proof unavailable',error=repr(error))
  assert clock()<start+780,'whole deadline after owned-command group proof'
  groups.append(row)
 return {'all_absent':all(row['absent'] for row in groups),'groups':groups,
         'unresolved_group_ids':[row['pid'] for row in groups if not row['absent']]}


def terminal_stdout(value,start,clock=time.monotonic,write=os.write):
 if clock()>=start+780:return False
 raw=(json.dumps(value)+'\n').encode()
 if len(raw)>8192 or clock()>=start+780:return False
 offset=0
 while offset<len(raw):
  if clock()>=start+780:return False
  count=write(1,raw[offset:offset+4096])
  if count<=0 or clock()>=start+780:return False
  offset+=count
 return True


def close_worker_group(proc,receipt,lifecycle,start):
 assert time.monotonic()+3<=start+780,'no whole-window owned-group closure reserve'
 lifecycle.stop_group(proc,receipt)
 assert receipt.get('owned_group_absent') is True
 assert time.monotonic()<start+780,'owned-group closure exceeded whole window'

def supervise(grant_path,grant):
 assert not SCOPE.exists();SCOPE.mkdir(mode=0o700);start=time.monotonic();l=load('bounded_lifecycle')
 intent={'started_at':l.now(),'start_monotonic':start,'context_sha256':sha(grant_path),'seconds':780,'status':'running'}
 l.save(SCOPE/'invocation.json',intent);proc=None
 try:
  with (SCOPE/'driver.log').open('xb') as log:
   proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),str(grant_path),'--worker',str(start)],cwd=HERE,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   intent['owned_worker']=proc.pid
   monitor=Resources(start)
   while proc.poll() is None:
    assert time.monotonic()<start+772,'worker deadline'
    metadata=SCOPE/'metadata.json'
    if metadata.exists():
     assert metadata.stat().st_size<=256*1024
     value=json.loads(metadata.read_bytes()).get('owned_uuid')
     if value:
      uuid.UUID(value);monitor.device=Path.home()/'Library/Developer/CoreSimulator/Devices'/value
    monitor.check(772)
    time.sleep(min(1,max(0,start+772-time.monotonic())))
   intent['maximum_observed_owned_allocation']=monitor.maximum
   assert proc.returncode==0
   close_worker_group(proc,intent,l,start)
   intent['status']='passed_pending_independent_review'
 except BaseException as error:intent.update(status='failed',error=repr(error))
 finally:
  if time.monotonic()>=start+780:raise SystemExit(1)  # No further I/O after the original whole deadline.
  if proc is not None and proc.poll() is None:
   try:
    try:already_cleaning=bool(cleanup_metadata().get('cleanup_phase'))
    except (OSError,ValueError,AssertionError):already_cleaning=False
    if not already_cleaning:os.killpg(proc.pid,signal.SIGTERM)
    await_cleanup_ack(proc,start,intent)
    proc.wait(timeout=min(3,max(.01,start+775-time.monotonic())))
   except (ProcessLookupError,subprocess.TimeoutExpired):
    try:
     meta=json.loads((SCOPE/'metadata.json').read_bytes());active=[c for c in meta['commands'] if 'owned_process_group' in c and ('finished_at' not in c or c.get('owned_group_absent') is False)]
     assert len(active)<=2;intent['last_resort_children']=[]
     for child in active:intent['last_resort_children']+=l.stop_recorded_children(proc.pid,{'commands':[child]},min(start+778,time.monotonic()+2))
    except BaseException as error:intent['last_resort_error']=repr(error)
    try:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=max(.01,start+779-time.monotonic()))
    except (ProcessLookupError,subprocess.TimeoutExpired):intent['worker_reap_unconfirmed']=True
  if proc is not None and intent.get('owned_group_absent') is not True:
   try:close_worker_group(proc,intent,l,start)
   except BaseException as error:intent.update(status='failed',worker_group_closure_error=repr(error),owned_group_absent=False)
  try:
   meta=json.loads(final_read(SCOPE/'metadata.json',start+780))
   intent['owned_command_groups']=aggregate_command_groups(meta,start)
   if not intent['owned_command_groups']['all_absent']:intent['status']='failed'
  except BaseException as error:intent.update(status='failed',owned_command_groups={'all_absent':False,'error':repr(error)})
  retain_cleanup_obligation(intent,start)
  if not intent['cleanup_obligation'].get('absence_verified'):intent['status']='failed'
  intent.update(returncode=proc.returncode if proc else None,elapsed_seconds=time.monotonic()-start)
  if intent['elapsed_seconds']>=780:intent['status']='failed'
  try:intent['terminal_receipt']=final_write(intent,start)
  except BaseException as error:intent.update(status='failed',terminal_receipt_error=repr(error))
  if time.monotonic()>=start+780:intent['status']='failed'
  if not terminal_stdout({'status':intent['status'],'terminal_receipt':intent.get('terminal_receipt'),'terminal_receipt_error':intent.get('terminal_receipt_error'),'cleanup_obligation':intent.get('cleanup_obligation'),'owned_command_groups':{key:intent.get('owned_command_groups',{}).get(key) for key in ('all_absent','unresolved_group_ids')}},start):intent['status']='failed'
 return 0 if intent['status']=='passed_pending_independent_review' else 1

if __name__=='__main__':
 grant_path=Path(sys.argv[1]);assert grant_path.is_absolute();grant=validate_grant(grant_path)
 if sys.argv[2:3]==['--worker']:
  started=float(sys.argv[3]);assert 0<=time.monotonic()-started<780
  raise SystemExit(worker(started,grant))
 assert len(sys.argv)==2
 raise SystemExit(supervise(grant_path,grant))
