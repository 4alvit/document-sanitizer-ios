"""Bind the same-run Release UI runner to the separately packaged Release AUT."""
import copy, hashlib, json, os, plistlib, stat
from pathlib import Path
CASE='ShareExtensionEntryTests/testPDFReceivedByExtensionThenImported'

def verify_runner(binding):
 selected=Path(binding['selected_test_source_path'])
 assert selected.is_file() and not selected.is_symlink() and hashlib.sha256(selected.read_bytes()).hexdigest()==binding['test_source_sha256']
 runner=Path(binding['runner']);actual={}
 assert sorted(p.name for p in runner.parent.iterdir())==[runner.name]
 for path in [runner,*sorted(runner.rglob('*'))]:
  before=path.lstat();assert not stat.S_ISLNK(before.st_mode)
  entry={'mode':f'{stat.S_IMODE(before.st_mode):04o}','device':before.st_dev,'inode':before.st_ino}
  if stat.S_ISDIR(before.st_mode):entry['directory']=True
  else:
   assert stat.S_ISREG(before.st_mode)
   entry.update(bytes=before.st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
  after=path.lstat();assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
  actual[str(path.relative_to(runner))]=entry
 assert actual==binding['runner_entries'],'runner content/mode/identity mismatch'
 return actual

def prepare(app,developer,output,binding_path,template_path,head,tree):
 if not __debug__:raise RuntimeError('Assertions must be enabled')
 binding=json.loads(binding_path.read_bytes());raw=template_path.read_bytes()
 assert hashlib.sha256(raw).hexdigest()==binding['template_sha256'];verify_runner(binding)
 runner=Path(binding['runner']);original_runner=binding['original_runner'];original_app=binding['original_AUT'];original_products=str(Path(original_runner).parent.parent)
 assert sorted(p.name for p in app.parent.iterdir())==[app.name]
 assert app.is_dir() and app.name=='CleanSend.app' and developer.is_absolute()
 data=plistlib.loads(raw);assert data['__xctestrun_metadata__']['FormatVersion']==2
 assert len(data['TestConfigurations'])==1 and data['TestConfigurations'][0].get('IsEnabled',True)
 targets=[t for t in data['TestConfigurations'][0]['TestTargets'] if t['BlueprintName']=='CleanSendUITests'];assert len(targets)==1
 target=targets[0];assert target['IsUITestBundle'] and target['IsXCTRunnerHostedTestBundle']
 assert target.get('UITargetAppEnvironmentVariables',{})=={} and target.get('UITargetAppCommandLineArguments',[])==[]
 before=copy.deepcopy(target)
 replacements={'__TESTROOT__':original_products,'__TESTHOST__':original_runner,'__PLATFORMS__':str(developer/'Platforms'),'__DERIVEDDATA__':str(output/'runner-derived'),original_runner:str(runner),original_app:str(app)}
 def resolve(value):
  if isinstance(value,str):
   for old,new in replacements.items():value=value.replace(old,new)
   return value
  if isinstance(value,list):return [resolve(v) for v in value]
  if isinstance(value,dict):return {k:resolve(v) for k,v in value.items()}
  return value
 target=resolve(target);assert target['UITargetAppPath']==str(app) and target['TestHostPath']==str(runner)
 framework=developer/'Platforms/iPhoneSimulator.platform/Developer/Library/Frameworks';libraries=developer/'Platforms/iPhoneSimulator.platform/Developer/usr/lib'
 assert (framework/'XCTest.framework/XCTest').is_file() and libraries.is_dir()
 frameworks=[str(runner/'Frameworks'),str(framework)] if (runner/'Frameworks').is_dir() else [str(framework)]
 target['TestingEnvironmentVariables'].update(DYLD_FRAMEWORK_PATH=':'.join(frameworks),DYLD_LIBRARY_PATH=str(libraries),__XCODE_BUILT_PRODUCTS_DIR_PATHS=str(app.parent)+':'+str(runner.parent),__XPC_DYLD_FRAMEWORK_PATH=':'.join(frameworks),__XPC_DYLD_LIBRARY_PATH=str(libraries))
 target.update(OnlyTestIdentifiers=[CASE],SkipTestIdentifiers=[],TestLanguage='en',TestRegion='US',TestTimeoutsEnabled=True,DefaultTestExecutionTimeAllowance=120,MaximumTestExecutionTimeAllowance=240,UserAttachmentLifetime='keepAlways',SystemAttachmentLifetime='keepAlways',UITargetAppEnvironmentVariables={},UITargetAppCommandLineArguments=[],DependentProductPaths=[str(app),str(app/'PlugIns/CleanSendShare.appex'),str(runner),str(runner/'PlugIns/CleanSendUITests.xctest')])
 assert all(Path(p).exists() for p in target['DependentProductPaths'])
 data=resolve(data);data.pop('CodeCoverageBuildableInfos',None);data['TestConfigurations'][0]['TestTargets']=[target]
 encoded=plistlib.dumps(data)
 assert original_products.encode() not in encoded and b'Debug-iphonesimulator' not in encoded
 assert b'storekit' not in encoded.lower() and b'commerce' not in encoded.lower()
 assert not any(t in encoded for t in (b'__TESTROOT__',b'__TESTHOST__',b'__PLATFORMS__',b'__DERIVEDDATA__'))
 output.mkdir(mode=0o700,exist_ok=False)
 with (output/'exact-package-share.xctestrun').open('xb') as stream:stream.write(encoded)
 receipt={'app_head':head,'app_tree':tree,'runner_origin':binding,'selected_case':CASE,'AUT':str(app),'AUT_rebuilt':False,'configuration_sha256':hashlib.sha256(encoded).hexdigest(),'target_changes':{k:{'before':before.get(k),'after':target.get(k)} for k in before.keys()|target.keys() if before.get(k)!=target.get(k)}}
 with (output/'config-binding.json').open('x') as stream:json.dump(receipt,stream,indent=2)
 return receipt
