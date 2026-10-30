#!/usr/bin/env python3
"""Bounded same-run artifact preparation for the exact Release package smoke."""
import hashlib, importlib.util, io, json, os, plistlib, re, shutil, stat, sys, time, uuid, zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
REPO='4alvit/document-sanitizer-ios'
RELEASE=('RedactLeaf-source.zip','RedactLeaf-unsigned-simulator.zip','RedactLeaf-adhoc-simulator.zip','preview-build.json','payload-sha256.json','release-binary-scan.json','PREVIEW-README.txt','SHA256SUMS')
PRIVACY=('tested-payloads.zip','generated-original.xctestrun','selected.xctestrun','source-provenance.json','payload-before.json','payload-after.json','payload-node-modes-before.json','payload-node-modes-after.json','metadata.json','summary.json','selected-cases.json','invocation.json')

def load(name,path=None):
 path=path or HERE/(name+'.py');spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def identities(data,repo,run,attempt,head):
 assert data['total_count']<=100 and len(data['artifacts'])==data['total_count']
 result=[]
 for prefix in ('release-simulator-packages','privacy-ipad-evidence'):
  name=f'{prefix}-{run}-attempt-{attempt}'
  matches=[a for a in data['artifacts'] if a['name']==name];assert len(matches)==1,'one exact current producer artifact required'
  a=matches[0];assert not a['expired'] and a['workflow_run']['id']==int(run) and a['workflow_run']['head_sha']==head,'artifact provenance'
  digest=a['digest'];assert re.fullmatch(r'sha256:[a-f0-9]{64}',digest)
  assert type(a['id']) is int and a['id']>0 and 0<a['size_in_bytes']<=(16 if prefix.startswith('release') else 256)*2**20
  result.append({'repo':repo,'run':int(run),'attempt':int(attempt),'head':head,'name':name,'id':a['id'],'bytes':a['size_in_bytes'],'sha256':digest[7:]})
 return result

def reserve_archives(window, rows):
 # A streamed file may allocate beyond its logical length. Precharge a finite
 # ceiling; retain exact copy length/hash and the unchanged cumulative cap.
 plans=[];allocation_limits={}
 for row,folder in zip(rows,('release-assets','privacy-inputs')):
  name=str(row['id'])+'.zip';size=row['bytes']
  plans.extend([(name,'file',size),(folder,'directory',0)])
  quantum=4*2**20
  allocation_limits[name]=max(16*2**20,((2*size+quantum-1)//quantum)*quantum)
 window.reserve(plans,allocation_limits=allocation_limits)
 return allocation_limits

def index(archive,w,total=512*2**20):
 rows=archive.infolist();assert len(rows)<=4000 and sum(r.file_size for r in rows)<=total
 result={};aliases=set()
 for row in rows:
  w.check();name=row.filename.rstrip('/');w.safe(name)
  assert row.filename==row.orig_filename and name not in result
  alias=name.casefold();assert alias not in aliases;aliases.add(alias)
  mode=row.external_attr>>16;assert not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in (0,stat.S_IFREG,stat.S_IFDIR)
  assert not row.flag_bits&1 and row.file_size>=0
  result[name]=row
 return result

def failure_detail(error):
 # The caller owns these exceptions; no command argv, token, environment or
 # response content is included in this bounded diagnostic.
 frames=[];trace=error.__traceback__
 while trace is not None:
  frames.append({'file':Path(trace.tb_frame.f_code.co_filename).name,'line':trace.tb_lineno,'function':trace.tb_frame.f_code.co_name})
  trace=trace.tb_next
 result={'type':type(error).__name__,'frames':frames[-4:]}
 row=getattr(error,'ledger_row',None)
 if isinstance(row,dict):
  result['ledger_row']={key:row[key] for key in ('kind','logical','allocated','logical_charge','allocated_charge')}
  result['ledger_row']['name']=row['name'][:256]
 return result

def bootstrap_context(preview, preview_sha256):
 value=os.environ.get('REDACT_BOOTSTRAP_DIAGNOSTIC');assert value in (None,'1')
 diagnostic=preview.get('bootstrap_observation')
 if value is None:
  assert diagnostic is None,'Diagnostic producer cannot pass normal Release acceptance'
  return None
 assert diagnostic is not None and diagnostic['mode']=='root-onAppear-only'
 setting='SWIFT_ACTIVE_COMPILATION_CONDITIONS=$(inherited) REDACT_BOOTSTRAP_OBSERVATION'
 assert diagnostic['compile_setting']==setting and diagnostic['diagnostic_only'] is True and diagnostic['exact_release_acceptance'] is False
 builds=diagnostic['builds'];assert len(builds)==2 and [b['signed'] for b in builds]==[False,True]
 for build in builds:
  argv=build['argv'];assert build['returncode']==0 and argv[0]=='xcodebuild' and argv[-1]=='build'
  assert argv.count(setting)==1 and '-xcconfig' not in argv
  assert argv[argv.index('-configuration')+1]=='Release' and argv[argv.index('-sdk')+1]=='iphonesimulator'
  assert argv[argv.index('-scheme')+1]=='CleanSend'
  assert ('CODE_SIGNING_ALLOWED=YES' if build['signed'] else 'CODE_SIGNING_ALLOWED=NO') in argv
 return {'mode':'root-onAppear-only','nonce':str(uuid.uuid4()),'producer_preview_sha256':preview_sha256}


def main():
 if not __debug__:raise SystemExit('Assertions must be enabled')
 assert os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_OS')=='macOS'
 assert os.uname().machine=='arm64','reviewed ARM host profile required'
 assert os.environ.get('GITHUB_EVENT_NAME')=='pull_request' and os.environ['GITHUB_REPOSITORY']==REPO
 run,attempt,head=os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'],os.environ['EXPECTED_HEAD_SHA']
 assert re.fullmatch('[1-9][0-9]*',run) and re.fullmatch('[1-9][0-9]*',attempt) and re.fullmatch('[0-9a-f]{40}',head)
 base=Path(os.environ['RUNNER_TEMP'])/f'redact-package-smoke-{run}-attempt-{attempt}'
 assert base.is_absolute() and not base.exists();base.mkdir(mode=0o700)
 start=time.monotonic();b,t=load('window'),load('transport');b.CAP=512*2**20;b.SECONDS=300
 b.IDENTITY={'repository':REPO,'run':run,'attempt':attempt,'head':head}
 w=b.Window.admit(base,started=start);w.safe=b.safe
 w.reserve([('preparation.json','file',256*1024),('artifact-list.json','file',1024*1024),('context.json','file',1024*1024),('runner-binding.json','file',1024*1024)])
 report={'identity':b.IDENTITY,'stage':'admitted','transports':[],'status':'running','started':start,'transfer_end':start+180,'preparation_end':start+300};primary=None
 def save(name,value):
  raw=(json.dumps(value,indent=2)+'\n').encode();return w.copy(io.BytesIO(raw),name,len(raw))
 def git(args,name,cap=512*1024):
  transport=t.Transport(start+300,str(ROOT));report['transports'].append(transport.report)
  w.reserve([(name,'file',cap)])
  with transport.command('source',12,cap,lambda _:['/usr/bin/git',*args],t.environment()) as stream:w.copy(stream,name)
  with w.reader(name) as stream:return stream.read(cap+1).decode().strip()
 try:
  assert t.GH and Path(t.GH).is_file() and Path(t.CURL).is_file()
  report['stage']='artifact_metadata_command'
  listing=t.Transport(start+180,str(ROOT));report['transports'].append(listing.report)
  with listing.command('artifact_metadata',12,1024*1024,lambda _:[t.GH,'api',f'repos/{REPO}/actions/runs/{run}/artifacts?per_page=100'],t.environment(True)) as stream:
   report['stage']='artifact_metadata_copy';w.copy(stream,'artifact-list.json')
   report['stage']='artifact_metadata_transport_close'
  report['stage']='artifact_metadata_read'
  with w.reader('artifact-list.json') as stream:
   data=json.load(stream,object_pairs_hook=b.unique);report['stage']='artifact_metadata_identities'
   rows=identities(data,REPO,run,attempt,head);report['stage']='artifact_metadata_reader_close'
  report['artifacts']=rows
  report['stage']='archive_reservation'
  report['archive_allocation_limits']=reserve_archives(w,rows)
  report['stage']='artifact_authentication'
  auth=t.Transport(start+180,str(ROOT));report['transports'].append(auth.report);token=auth.token()
  for row,folder,allowed in zip(rows,('release-assets','privacy-inputs'),(RELEASE,PRIVACY)):
   report['stage']='download:'+folder
   name=str(row['id'])+'.zip'
   transport=t.Transport(start+180,str(ROOT));report['transports'].append(transport.report)
   t.URL=f'https://api.github.com/repos/{REPO}/actions/artifacts/{row["id"]}/zip'
   report['stage']='download_command:'+folder
   with transport.zip(token,row['bytes']) as stream:
    report['stage']='download_copy:'+folder;w.copy(stream,name,row['bytes'],row['sha256'])
    report['stage']='download_transport_close:'+folder
   report['stage']='extract:'+folder
   w.mkdir(folder)
   with w.reader(name) as stream,zipfile.ZipFile(stream) as archive:
    contents=index(archive,w);assert set(allowed)<=set(contents)
    if folder=='release-assets':assert set(contents)==set(RELEASE)
    for member in allowed:
     item=contents[member];maximum=(32*2**20 if member=='tested-payloads.zip' else 8*2**20 if member.endswith('.zip') else 512*1024)
     assert not item.is_dir() and item.file_size<=maximum
     target=folder+'/'+member;w.reserve([(target,'file',item.file_size)])
     with archive.open(item) as source:w.copy(source,target,item.file_size)
  del token
  assert time.monotonic()<=start+180,'transfer exceeded original180s allowance'
  def raw(name,cap=512*1024):
   with w.reader(name) as stream:data=stream.read(cap+1)
   assert len(data)<=cap;return data
  def doc(name):return json.loads(raw(name),object_pairs_hook=b.unique)
  report['stage']='producer_and_source_provenance'
  privacy=doc('privacy-inputs/source-provenance.json');meta=doc('privacy-inputs/metadata.json')
  assert privacy['published_head']==head and privacy['run_id']==run and privacy['run_attempt']==attempt
  assert privacy['host_architecture']==os.uname().machine=='arm64','privacy producer profile mismatch'
  assert privacy['build_configuration']=='Release' and privacy['sdk']=='18.5' and privacy['xcode']=='Xcode 16.4\nBuild version 16F6'
  assert privacy['equal_trees'] and privacy['actual_tree']==privacy['head_tree']
  assert meta['source_and_built_payloads_unchanged'] and meta['device_removed'] and meta['cleanup']=={'shutdown':0,'delete':0}
  assert meta['xcodebuild_returncode']==0 and not meta['failures']
  summary=doc('privacy-inputs/summary.json');assert tuple(summary[k] for k in ('passedTests','failedTests','skippedTests','totalTestCount'))==(1,0,0,1)
  before=doc('privacy-inputs/payload-before.json');assert before==doc('privacy-inputs/payload-after.json')
  modes=doc('privacy-inputs/payload-node-modes-before.json');assert modes==doc('privacy-inputs/payload-node-modes-after.json')
  checkout=git(['rev-parse','HEAD'],'checkout.txt',128);tree=git(['rev-parse','HEAD^{tree}'],'tree.txt',128)
  assert checkout==os.environ['GITHUB_SHA']==privacy['actual_checkout'] and tree==privacy['actual_tree']
  assert git(['rev-parse',head+'^{tree}'],'head-tree.txt',128)==tree
  assert not git(['status','--porcelain','--untracked-files=no'],'source-status.txt')
  names=git(['ls-files'],'tracked-files.txt').splitlines();assert set(names)==set(privacy['source_files'])
  source_bytes=0
  for name in names:
   w.check();b.safe(name);file=ROOT/name;assert file.is_file() and not file.is_symlink()
   source_bytes+=file.stat().st_size;assert source_bytes<=16*2**20 and file.stat().st_size<=8*2**20
   assert hashlib.sha256(file.read_bytes()).hexdigest()==privacy['source_files'][name]
  checksums={}
  for line in raw('release-assets/SHA256SUMS').decode().splitlines():
   digest,name=line.split('  ');assert re.fullmatch('[0-9a-f]{64}',digest) and name in RELEASE and name not in checksums;checksums[name]=digest
  assert set(checksums)==set(RELEASE)-{'SHA256SUMS'}
  for name,digest in checksums.items():
   with w.reader('release-assets/'+name) as stream:
    hasher=hashlib.sha256()
    while True:
     w.check();block=stream.read(65536)
     if not block:break
     hasher.update(block)
   assert hasher.hexdigest()==digest
  preview=doc('release-assets/preview-build.json');provenance=preview['provenance']
  assert preview['host_architecture']==privacy['host_architecture'] and preview['xcode']==privacy['xcode'],'Release producer profile mismatch'
  assert preview['source_commit']==checkout and preview['source_tree']==tree and preview['configuration']=='Release' and preview['platform']=='iPhoneSimulator' and preview['app_store_release'] is False
  assert provenance['published_head']==head and provenance['published_head_tree']==tree and provenance['checkout_tree_matches_published_head'] is True
  assert provenance['github']['run_id']==run and provenance['github']['run_attempt']==attempt and provenance['github']['repository']==REPO
  bootstrap=bootstrap_context(preview,checksums['preview-build.json'])
  with w.reader('release-assets/RedactLeaf-source.zip') as stream,zipfile.ZipFile(stream) as archive:
   contents=index(archive,w,16*2**20);files={n.removeprefix('RedactLeaf-source/'):r for n,r in contents.items() if not r.is_dir()}
   assert set(files)==set(names)
   for name,row in files.items():
    w.check();assert row.file_size<=8*2**20
    with archive.open(row) as member:data=member.read(row.file_size+1)
    assert len(data)==row.file_size and hashlib.sha256(data).hexdigest()==privacy['source_files'][name]
  report['stage']='release_binary_scans'
  scanner=load('verify_release_package',ROOT/'scripts/verify_release_package.py');scans=doc('release-assets/release-binary-scan.json')
  for variant in ('unsigned','adhoc'):
   name=f'RedactLeaf-{variant}-simulator.zip'
   with w.reader('release-assets/'+name) as stream,zipfile.ZipFile(stream) as archive:
    binary_rows=index(archive,w,32*2**20);assert all(r.file_size<=8*2**20 for r in binary_rows.values())
   w.check();actual=scanner.scan_package(base/'release-assets'/name);w.check()
   assert actual['ok'] and actual==scans[variant+'_zip'] and actual['binaries']==scans[variant+'_app']['binaries'],'live binary scan mismatch'
   assert all(any(s['architecture']=='arm64' for s in binary['slices']) for binary in actual['binaries']),'ARM simulator slice required'
  report['stage']='runner_reconstruction'
  runner_folder='runner/CleanSendUITests-Runner.app';w.reserve([('runner','directory',0)]);w.mkdir('runner')
  runner_modes=modes['runner'];assert set(before['runner']['files'])=={n for n,v in runner_modes.items() if not v['directory']}
  for name,mode in sorted(runner_modes.items(),key=lambda pair:(pair[0].count('/'),pair[0])):
   b.safe(name) if name!='.' else None
   relative=runner_folder if name=='.' else runner_folder+'/'+name
   if mode['directory']:
    w.reserve([(relative,'directory',0)]);w.mkdir(relative);(base/relative).chmod(int(mode['mode'],8))
  with w.reader('privacy-inputs/tested-payloads.zip') as stream,zipfile.ZipFile(stream) as archive:
   contents=index(archive,w,128*2**20);selected={name.removeprefix('runner/'):row for name,row in contents.items() if name.startswith('runner/') and not row.is_dir()}
   assert set(selected)==set(before['runner']['files'])
   for name,row in selected.items():
    assert row.file_size<=32*2**20 and f'{stat.S_IMODE(row.external_attr>>16):04o}'==runner_modes[name]['mode'],'runner ZIP mode mismatch'
    relative=runner_folder+'/'+name;w.reserve([(relative,'file',row.file_size)])
    with archive.open(row) as source:w.copy(source,relative,row.file_size,before['runner']['files'][name])
    (base/relative).chmod(int(runner_modes[name]['mode'],8))
  runner=base/runner_folder;entries={}
  for name,mode in runner_modes.items():
   file=runner if name=='.' else runner/name;info=file.lstat();row={'mode':mode['mode'],'device':info.st_dev,'inode':info.st_ino}
   if mode['directory']:row['directory']=True
   else:row.update(bytes=info.st_size,sha256=before['runner']['files'][name])
   entries[name]=row
  build_commands=[c for c in meta['commands'] if c.get('args',[None])[0]=='xcodebuild' and 'build-for-testing' in c['args']]
  assert len(build_commands)==1 and build_commands[0]['returncode']==0 and build_commands[0]['owned_group_absent'] is True
  args=build_commands[0]['args']
  assert args[args.index('-scheme')+1]=='CleanSendPrivacyRelease' and args[args.index('-configuration')+1]=='Release'
  assert 'ENABLE_TESTABILITY=NO' in args
  assert 'ARCHS=arm64' in args and 'ONLY_ACTIVE_ARCH=YES' in args,'UI runner producer architecture mismatch'
  producer={'host_architecture':privacy['host_architecture'],'head':head,'tree':tree,'checkout':checkout,'run':run,'attempt':attempt,'configuration':privacy['build_configuration'],
   'xcode':privacy['xcode'],'sdk':privacy['sdk'],'source_provenance_sha256':hashlib.sha256(raw('privacy-inputs/source-provenance.json')).hexdigest(),
   'build_for_testing':{k:build_commands[0][k]for k in ('args','returncode','owned_group_absent')}}
  binding={'producer':producer,'runner':str(runner),'runner_entries':entries,'runner_source_commit':checkout,'selected_test_source_path':str(ROOT/'Tests/UITests/ShareExtensionEntryTests.swift'),'test_source_sha256':privacy['source_files']['Tests/UITests/ShareExtensionEntryTests.swift'],'runner_Info':{k:plistlib.loads((runner/'Info.plist').read_bytes()).get(k) for k in ('CFBundleIdentifier','MinimumOSVersion','DTXcodeBuild')},'original_runner':before['runner']['path'],'original_AUT':before['AUT']['path'],'template_sha256':hashlib.sha256(raw('privacy-inputs/generated-original.xctestrun')).hexdigest()}
  saved_binding=save('runner-binding.json',binding)
  report['stage']='native_context'
  context={'host_architecture':os.uname().machine,'repository':REPO,'run':run,'attempt':attempt,'head':head,'tree':tree,'checkout':checkout,'base':str(base),'scope':str(base/'native'),'assets':str(base/'release-assets'),'runner_binding':str(base/'runner-binding.json'),'runner_binding_sha256':saved_binding['sha256'],'runner_template':str(base/'privacy-inputs/generated-original.xctestrun'),'adhoc_zip_sha256':checksums['RedactLeaf-adhoc-simulator.zip'],'adhoc_zip_bytes':(base/'release-assets/RedactLeaf-adhoc-simulator.zip').stat().st_size,'payload_manifest_sha256':checksums['payload-sha256.json'],'runtime_id':meta['runtime']['identifier'],'device_type':meta['device_type']['identifier'],'runtime_version':'18.5','xcode_build':'16F6','seconds':780,'owned_cap_bytes':2*2**30,'free_floor_bytes':12*2**30,'get_count':0,'native_worker_count':1,'retry_authorized':False,'pipeline_deadline':start+1080,'expires_unix':time.time()+300,'source_files':privacy['source_files']}
  if bootstrap is not None:context['bootstrap_observation']=bootstrap
  assert context['runtime_id']=='com.apple.CoreSimulator.SimRuntime.iOS-18-5'
  assert context['device_type']=='com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M4-16GB'
  assert time.monotonic()<start+300 and shutil.disk_usage(base).free>=14*2**30
  saved=save('context.json',context);report.update(status='prepared',context_sha256=saved['sha256'],context=str(base/'context.json'))
  with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:output.write('context='+str(base/'context.json')+'\ncontext_sha256='+saved['sha256']+'\nscope='+str(base)+'\n')
 except BaseException as error:primary=error;report.update(status='failed',error=type(error).__name__,primary_error=failure_detail(error))
 finally:
  report['elapsed_seconds']=time.monotonic()-start
  report['last_capacity_sample']=getattr(w,'last_capacity_sample',None)
  try:report['window']=w.state()
  except BaseException as error:
   report['window_error']=failure_detail(error);report['status']='failed'
   if primary is None:primary=error;report['primary_error']=failure_detail(error)
  try:save('preparation.json',report)
  except BaseException as error:
   report['receipt_error']=failure_detail(error)
   primary=primary or error
  if primary and time.monotonic()<start+300:
   diagnostic={'status':'failed','stage':report['stage'],'identity':b.IDENTITY,'primary_error':report.get('primary_error'),'window_error':report.get('window_error'),'receipt_error':report.get('receipt_error'),'last_capacity_sample':getattr(w,'last_capacity_sample',None)}
   encoded=(json.dumps(diagnostic)+'\n').encode()
   if len(encoded)<=4096 and time.monotonic()<start+300:
    os.write(2,encoded)
 if primary:raise SystemExit(1)

if __name__=='__main__':main()
