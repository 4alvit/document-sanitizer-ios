#!/usr/bin/env python3
"""One bounded same-host native StoreKit invocation; no build, account sign-in or retry."""
import datetime as dt
import hashlib, importlib.util, json, os, plistlib, re, shutil, signal, stat, subprocess, sys, time, uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
SCOPE=OWNED_ROOT=None
CAP=2*2**30;FLOOR=12*2**30
APP_ID='io.github.4alvit.cleansend'
REPO='4alvit/document-sanitizer-ios'
CASE_NAMES=('testPurchaseAndNewStoreRestoreFromVerifiedHistory','testRefundRevokesThroughListenerAndOnNextLaunch','testUserCancellationNeverUnlocksPro','testPendingPurchaseUnlocksOnlyAfterApproval','testUnverifiedTransactionNeverUnlocksPro','testCachedEntitlementSurvivesProductNetworkFailure','testFailedRestoreKeepsVerifiedEntitlement','testRestoreWithoutPurchaseDoesNotUnlockPro')
CASES={'ProStoreTests/'+name for name in CASE_NAMES}
RUNTIME='com.apple.CoreSimulator.SimRuntime.iOS-18-5'
DEVICE='com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def version(value):return tuple(([int(x) for x in value.split('.')]+[0,0])[:3])
def load(name):
 name={'bounded_lifecycle':'lifecycle','window_budget':'window'}.get(name,name)
 spec=importlib.util.spec_from_file_location(name,HERE/'release_smoke'/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def safe_failure(error):
 trace=error.__traceback__;frames=[]
 while trace:
  frames.append({'file':Path(trace.tb_frame.f_code.co_filename).name,'line':trace.tb_lineno,'function':trace.tb_frame.f_code.co_name});trace=trace.tb_next
 return {'type':type(error).__name__,'frames':frames[-4:]}

def admit_job(data,run,attempt,head,now,native_remaining):
 assert data['total_count']==len(data['jobs']) and len(data['jobs'])<=3
 jobs=[j for j in data['jobs'] if j['name']=='macOS core, independent export corpus, iOS build']
 assert len(jobs)==1
 job=jobs[0]
 assert job['run_id']==int(run) and job['run_attempt']==int(attempt) and job['head_sha']==head
 assert job['status']=='in_progress' and job['runner_id'] and job['labels']==['macos-15']
 started=dt.datetime.fromisoformat(job['started_at'].replace('Z','+00:00'))
 elapsed=(now-started).total_seconds();assert elapsed>=0
 remaining=1800-elapsed
 assert 0<native_remaining<=780 and remaining>=native_remaining+120+60,'job cleanup/upload reserve unavailable'
 return {'job_id':job['id'],'started_at':job['started_at'],'observed_at':now.isoformat(),'remaining_job_seconds':remaining,'required_remaining_seconds':native_remaining+180,'runner_id':job['runner_id'],'runner_name':job.get('runner_name'),'job_limit_minutes':30}

def validate_test_plan(data):
 options=data['defaultOptions'];assert options['testTimeoutsEnabled'] is True
 assert options['maximumTestExecutionTimeAllowance']==180 and options['defaultTestExecutionTimeAllowance']==120
 targets=[t for t in data['testTargets'] if t['target']['name']=='CleanSendTests'];assert len(targets)==1 and targets[0]['parallelizable'] is False
 # The local configuration is owned by SKTestSession; no invented test-plan key.
 assert 'storekit' not in json.dumps(data).lower()
 return {'cases':sorted(CASES),'maximum_case_seconds':180,'outer_seconds':300,'command_count':1}

def test_arguments(uid,result):
 uuid.UUID(uid)
 return ['xcodebuild','test-without-building','-project','CleanSend.xcodeproj','-scheme','CleanSend','-testPlan','CleanSend','-derivedDataPath','.derivedData','-destination','platform=iOS Simulator,id='+uid,'-parallel-testing-enabled','NO','-maximum-concurrent-test-simulator-destinations','1','-only-testing:CleanSendTests/ProStoreTests','-test-timeouts-enabled','YES','-maximum-test-execution-time-allowance','180','-collect-test-diagnostics','never','-resultBundlePath',str(result)]

def accepted_cases(data):
 rows=[]
 def walk(value):
  if isinstance(value,dict):
   if value.get('nodeType')=='Test Case':rows.append(value)
   for child in value.values():walk(child)
  elif isinstance(value,list):
   for child in value:walk(child)
 walk(data)
 actual=[]
 for row in rows:
  name=row['nodeIdentifier'];name=name[:-2] if name.endswith('()') else name
  if name.startswith('CleanSendTests/'):name=name[len('CleanSendTests/'):]
  assert name in CASES and row['result']=='Passed'
  actual.append(name)
 assert len(actual)==8 and len(set(actual))==8 and set(actual)==CASES
 return sorted(actual)

def write_small(path,value,start):
 assert time.monotonic()<start+780
 raw=(json.dumps(value,indent=2)+'\n').encode();assert len(raw)<=1024*1024
 with path.open('xb') as stream:
  assert time.monotonic()<start+780;assert stream.write(raw)==len(raw);stream.flush();os.fsync(stream.fileno())
 assert time.monotonic()<start+780

def prepare_context(start):
 global SCOPE,OWNED_ROOT
 assert __debug__ and os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_OS')=='macOS'
 assert os.environ.get('GITHUB_EVENT_NAME')=='pull_request' and os.environ['GITHUB_REPOSITORY']==REPO
 run,attempt,head=os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'],os.environ['EXPECTED_HEAD_SHA']
 assert re.fullmatch('[1-9][0-9]*',run) and re.fullmatch('[1-9][0-9]*',attempt) and re.fullmatch('[0-9a-f]{40}',head)
 SCOPE=ROOT/'.qa/native-storekit'/f'run-{run}-attempt-{attempt}';OWNED_ROOT=SCOPE
 assert not SCOPE.exists();SCOPE.parent.mkdir(parents=True,exist_ok=True)
 b=load('window');
 with b.directory(SCOPE.parent):pass
 SCOPE.mkdir(mode=0o700)
 report={'head':head,'run':run,'attempt':attempt,'phase':'admission','native_worker_started':False,'metadata_GETs':0,'payload_GETs':0,'retry':False,'status':'running'}
 failure=None
 try:
  assert shutil.disk_usage(SCOPE).free>=FLOOR
  t=load('transport');transport=t.Transport(min(start+30,start+780),str(ROOT));report['transport']=transport.report
  report['metadata_GETs']=1
  with transport.command('job_metadata',12,1024*1024,lambda _:[t.GH,'api','--method','GET',f'repos/{REPO}/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100'],t.environment(True)) as stream:
   raw=bytearray()
   while True:
    block=stream.read(min(65536,1024*1024-len(raw)+1))
    if not block:break
    raw.extend(block);assert len(raw)<=1024*1024
  assert time.monotonic()<start+30
  data=json.loads(raw);job=admit_job(data,run,attempt,head,dt.datetime.now(dt.timezone.utc),start+780-time.monotonic())
  write_small(SCOPE/'job-metadata.json',data,start)
  context={'repository':REPO,'run':run,'attempt':attempt,'head':head,'checkout':os.environ['GITHUB_SHA'],'scope':str(SCOPE),'seconds':780,'start_monotonic':start,'job_admission':job,'case_identities':sorted(CASES),'case_count':8,'outer_seconds':300,'case_seconds':180,'runtime':RUNTIME,'device_type':DEVICE,'no_real_account_sign_in':True,'retry':False}
  write_small(SCOPE/'context.json',context,start);report.update(status='admitted',job_admission=job,context_sha256=sha(SCOPE/'context.json'))
 except BaseException as error:failure=error;report.update(status='failed',error=safe_failure(error))
 finally:
  os.environ.pop('GH_TOKEN',None);os.environ.pop('GITHUB_TOKEN',None)
  if time.monotonic()<start+780:write_small(SCOPE/'admission.json',report,start)
 if failure:raise failure
 return SCOPE/'context.json',context

def validate_context(path,start):
 global SCOPE,OWNED_ROOT
 assert __debug__ and 0<=time.monotonic()-start<780
 raw=path.read_bytes();assert len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==os.environ['NATIVE_STOREKIT_CONTEXT_SHA']
 context=json.loads(raw);assert context['repository']==REPO and context['start_monotonic']==start
 assert context['case_identities']==sorted(CASES) and context['case_count']==8 and context['outer_seconds']==300 and context['case_seconds']==180 and context['seconds']==780
 assert context['runtime']==RUNTIME and context['device_type']==DEVICE and context['retry'] is False
 assert context['head']==os.environ['EXPECTED_HEAD_SHA'] and context['run']==os.environ['GITHUB_RUN_ID'] and context['attempt']==os.environ['GITHUB_RUN_ATTEMPT'] and context['checkout']==os.environ['GITHUB_SHA']
 SCOPE=Path(context['scope']);OWNED_ROOT=SCOPE
 assert SCOPE==ROOT/'.qa/native-storekit'/f"run-{context['run']}-attempt-{context['attempt']}" and path==SCOPE/'context.json'
 assert 'GH_TOKEN' not in os.environ and 'GITHUB_TOKEN' not in os.environ
 return context

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


def worker(start,context):
 b,e,l=load('window'),load('evidence'),load('lifecycle')
 l.OUT=SCOPE;l.ROOT=ROOT;l.CONFIGURATION='Debug'
 run=l.Run();run.start=start
 run.meta.update(owner_worker_pid=os.getpid(),head=context['head'],binary_kind='same-host existing Debug application and hosted unit-test products',build_configuration='Debug',build_scheme='CleanSend',test_plan='CleanSend',native_storekit_tests=0,native_storekit_selected_cases=sorted(CASES),job_admission=context['job_admission'],context_sha256=sha(SCOPE/'context.json'))
 resources=Resources(start);uid=None;failures=[];sources={};expected=None;host=ROOT/'.derivedData/Build/Products/Debug-iphonesimulator/CleanSend.app';during=False
 def interrupted(*_):
  if run.meta.get('cleanup_phase'):return
  raise InterruptedError('SIGTERM')
 signal.signal(signal.SIGTERM,interrupted)
 def command(args,name,limit=15,required=True):
  if run.end==560:resources.check()
  return run.command(args,name,limit,required)
 def output(args,name,limit=15):
  command(args,name,limit);return (SCOPE/name).read_text().strip()
 def source_hashes(names,phase):
  result={};total=0
  for name in names:
   resources.check(phase);b.safe(name);file=ROOT/name
   assert file.is_file() and not file.is_symlink();total+=file.stat().st_size
   assert file.stat().st_size<=8*2**20 and total<=16*2**20
   result[name]=sha(file);resources.check(phase)
  return result
 def installed(name):
  value=output(['xcrun','simctl','get_app_container',uid,APP_ID,'app'],name+'-path.txt')
  path=Path(value);assert path.is_absolute() and str(path)==str(path.resolve()) and path.is_relative_to(resources.device/'data')
  files=e.payload_inventory(path,b,resources.check);assert files==expected
  l.save(SCOPE/name,{'path':str(path),'exact_payload':True,'files':files});return path
 try:
  names=output(['git','ls-files'],'tracked-files.txt').splitlines();assert 0<len(names)<=1000
  checkout=output(['git','rev-parse','HEAD'],'checkout.txt');tree=output(['git','rev-parse','HEAD^{tree}'],'tree.txt')
  assert checkout==context['checkout'] and output(['git','rev-parse',context['head']+'^{tree}'],'head-tree.txt')==tree
  assert not output(['git','status','--porcelain','--untracked-files=no'],'source-status.txt')
  sources=source_hashes(names,560)
  l.save(SCOPE/'source-provenance.json',{'published_head':context['head'],'checkout':checkout,'tree':tree,'source_files':sources,'run':context['run'],'attempt':context['attempt']})
  assert output(['xcodebuild','-version'],'xcode-version.txt',20)=='Xcode 16.4\nBuild version 16F6'
  runtimes=json.loads(output(['xcrun','simctl','list','runtimes','--json'],'runtimes.json',60))['runtimes']
  runtime=[r for r in runtimes if r['identifier']==RUNTIME and r.get('isAvailable')];assert len(runtime)==1 and runtime[0]['version']=='18.5'
  assert os.uname().machine in runtime[0]['supportedArchitectures'] and DEVICE in {d['identifier'] for d in runtime[0]['supportedDeviceTypes']}
  types=json.loads(output(['xcrun','simctl','list','devicetypes','--json'],'device-types.json'))['devicetypes']
  device=[d for d in types if d['identifier']==DEVICE];assert len(device)==1 and version(device[0]['minRuntimeVersionString'])<=version('18.5')<=version(device[0]['maxRuntimeVersionString'])
  run.meta['runtime']=runtime[0];run.meta['device_type']=device[0]
  unit=host/'PlugIns/CleanSendTests.xctest';assert unit.is_dir() and not unit.is_symlink()
  info=plistlib.loads((host/'Info.plist').read_bytes());unitinfo=plistlib.loads((unit/'Info.plist').read_bytes())
  assert info['CFBundleIdentifier']==APP_ID and info['DTXcodeBuild']=='16F6' and version(info['MinimumOSVersion'])<=version('18.5')
  assert unitinfo['CFBundleIdentifier']=='io.github.4alvit.cleansend.tests'
  assert sha(unit/'CleanSend.storekit')==sources['App/CleanSend.storekit']
  plan=validate_test_plan(json.loads((ROOT/'CleanSend.xctestplan').read_bytes()))
  scheme=ROOT/'CleanSend.xcodeproj/xcshareddata/xcschemes/CleanSend.xcscheme';assert scheme.is_file() and not scheme.is_symlink();scheme_hash=sha(scheme)
  expected=e.payload_inventory(host,b,resources.check)
  l.save(SCOPE/'compiled-host-before.json',expected)
  l.save(SCOPE/'config-binding.json',{'plan':plan,'plan_sha256':sources['CleanSend.xctestplan'],'scheme_sha256':scheme_hash,'configuration_sha256':sources['App/CleanSend.storekit'],'native_tests_source_sha256':sources['Tests/EntitlementTests/ProStoreTests.swift'],'host':str(host),'unit_bundle':str(unit),'rebuild':False,'resign':False,'host_UI':'existing Debug EmptyView test host; real production ProStore constructed by each case','no_real_account_sign_in':True})
  command(['codesign','--verify','--strict','--all-architectures',host],'signature-host.log',15)
  assert run.remaining()>=304,'full test admission unavailable before device creation'
  name='RedactLeaf-Native-Payment-'+str(uuid.uuid4());run.meta['owned_device_name']=name;run.persist()
  uid=output(['xcrun','simctl','create',name,DEVICE,RUNTIME],'create.txt');uuid.UUID(uid)
  run.meta['owned_uuid']=uid;resources.device=Path.home()/'Library/Developer/CoreSimulator/Devices'/uid;run.persist()
  command(['xcrun','simctl','boot',uid],'boot.log',20);command(['xcrun','simctl','bootstatus',uid,'-b'],'bootstatus.log',90)
  command(['xcrun','simctl','install',uid,host],'install.log',30);installed('installed-before.json')
  assert run.remaining()>=304,'full300s XCTest admission unavailable'
  argv=test_arguments(uid,SCOPE/'result.xcresult');item={'args':argv,'started_at':l.now(),'timeout_seconds':300};run.meta['commands'].append(item);run.persist()
  proc=None;tail=b'';log_read=0;end=min(time.monotonic()+300,start+560-4);previous_end=run.end;run.end=min(previous_end,end-start)
  try:
   with (SCOPE/'test.log').open('xb') as log:
    proc=subprocess.Popen(argv,cwd=ROOT,env=l.ENV,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    item['owned_process_group']=proc.pid;run.persist()
    with (SCOPE/'test.log').open('rb') as reader:
     while proc.poll() is None:
      resources.check();assert time.monotonic()<end,'native StoreKit outer300s limit'
      chunk=reader.read(65536);log_read+=len(chunk);assert log_read<=16*2**20
      tail=(tail+chunk)[-131072:]
      if not during and b'ProStoreTests test' in tail and b"' started" in tail:
       installed('installed-during.json');during=True
      time.sleep(min(.25,max(0,end-time.monotonic())))
   run.meta['xcodebuild_returncode']=proc.returncode;assert proc.returncode==0 and during
  finally:
   if proc is not None:l.stop_group(proc,item);item['returncode']=proc.returncode
   item['finished_at']=l.now();run.end=previous_end;run.persist()
  installed('installed-after.json')
  assert e.payload_inventory(host,b,resources.check)==expected and sha(scheme)==scheme_hash
  run.meta['compiled_host_unchanged']=True
 except BaseException as error:failures.append(safe_failure(error))
 finally:
  mark_cleanup(run,start,failures,l)
  run.end=l.RECOVERY_END
  if not uid and run.meta.get('owned_device_name'):
   try:
    devices=json.loads(run.output(['xcrun','simctl','list','devices','--json'],'create-recovery.json'))['devices']
    matches=[d['udid'] for values in devices.values() for d in values if d['name']==run.meta['owned_device_name']]
    assert len(matches)<=1;uid=matches[0] if matches else None;run.meta['owned_uuid']=uid
   except BaseException as error:failures.append({'phase':'device recovery',**safe_failure(error)})
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
   except BaseException as error:failures.append({'phase':'device cleanup',**safe_failure(error)})
   run.meta['cleanup']=cleanup
   run.persist()
  run.end=772
  try:
   assert (SCOPE/'result.xcresult').is_dir()
   for kind in ['summary','tests']:
    run.command(['xcrun','xcresulttool','get','test-results',kind,'--path',SCOPE/'result.xcresult','--format','json'],kind+'.json',15)
   # Preserve failed-case observations before enforcing complete acceptance.
   # Run.command still forbids evidence children after unresolved group closure.
   run.command(['xcrun','xcresulttool','export','attachments','--path',SCOPE/'result.xcresult','--output-path',SCOPE/'attachments'],'attachments-export.log',40)
   summary=json.loads((SCOPE/'summary.json').read_bytes())
   assert run.meta.get('xcodebuild_returncode')==0
   assert tuple(summary.get(k) for k in ['passedTests','failedTests','skippedTests','totalTestCount'])==(8,0,0,8)
   run.meta['passed_native_case_identities']=accepted_cases(json.loads((SCOPE/'tests.json').read_bytes()))
   run.meta['native_storekit_tests']=8
  except BaseException as error:failures.append({'phase':'result evidence',**safe_failure(error)})
  try:
   resources.check(772)
   assert sources and source_hashes(list(sources),772)==sources
   assert expected and e.payload_inventory(host,b,lambda:resources.check(772))==expected
   run.meta['source_and_compiled_host_unchanged']=True
  except BaseException as error:failures.append({'phase':'final integrity',**safe_failure(error)})
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

def supervise(grant_path,grant,start):
 assert SCOPE.is_dir();l=load('bounded_lifecycle')
 intent={'started_at':l.now(),'start_monotonic':start,'context_sha256':sha(grant_path),'seconds':780,'status':'running'}
 l.save(SCOPE/'invocation.json',intent);proc=None
 try:
  with (SCOPE/'driver.log').open('xb') as log:
   child_env={k:os.environ[k] for k in ('HOME','USER','LOGNAME','PATH','TMPDIR','DEVELOPER_DIR','GITHUB_ACTIONS','RUNNER_OS','GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','EXPECTED_HEAD_SHA') if k in os.environ}
   child_env['NATIVE_STOREKIT_CONTEXT_SHA']=sha(grant_path)
   proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),str(grant_path),'--worker',str(start)],cwd=ROOT,env=child_env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
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
 if len(sys.argv)>1:
  assert len(sys.argv)==4 and sys.argv[2]=='--worker'
  path=Path(sys.argv[1]);started=float(sys.argv[3]);context=validate_context(path,started)
  raise SystemExit(worker(started,context))
 started=time.monotonic()
 try:
  path,context=prepare_context(started)
  result=supervise(path,context,started)
 except BaseException as error:
  if time.monotonic()<started+780:
   raw=(json.dumps({'status':'failed','error':safe_failure(error)})+'\n').encode()
   if len(raw)<=4096 and time.monotonic()<started+780:os.write(2,raw)
  result=1
 raise SystemExit(result)
